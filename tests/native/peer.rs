//! Controlled device peer for tests/test_native_io.py. A separate process so a
//! GIL regression cannot starve the simulated device. Never talks to hardware.
use enody::{message::*, wifi::*, Identifier};
use serde::{de::DeserializeOwned, Serialize};
use std::{io::Write, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
fn id() -> Identifier {
    Identifier::from_u128(1)
}
fn token() -> Token {
    Token {
        host_id: id(),
        key_id: "test".try_into().unwrap(),
        data: [7; 32].as_slice().try_into().unwrap(),
    }
}
async fn read<T: DeserializeOwned>(socket: &mut TcpStream) -> Result<T> {
    let len = socket.read_u16().await? as usize;
    if len > 4096 {
        return Err("oversized frame".into());
    }
    let mut data = vec![0; len];
    socket.read_exact(&mut data).await?;
    Ok(postcard::from_bytes(&data)?)
}
async fn write<T: Serialize>(socket: &mut TcpStream, value: &T) -> Result<()> {
    let data = postcard::to_allocvec(value)?;
    socket.write_u16(data.len() as u16).await?;
    socket.write_all(&data).await?;
    Ok(())
}
async fn event(
    socket: &mut TcpStream,
    noise: &mut snow::TransportState,
    message: Message,
    pairing: bool,
) -> Result<()> {
    let data = postcard::to_allocvec(&message)?;
    let mut encrypted = [0; WIFI_FRAME_PAYLOAD_MAX_LEN];
    let len = noise.write_message(&data, &mut encrypted)?;
    let payload = encrypted[..len].try_into().unwrap();
    let response = if pairing {
        Response::PairingNoise { payload }
    } else {
        Response::Noise { payload }
    };
    write(socket, &response).await
}
async fn serve(mut socket: TcpStream, mode: String, number: usize) -> Result<()> {
    socket.set_nodelay(true)?;
    let first: Request = read(&mut socket).await?;
    if mode == "delayed" && number == 0 {
        // Withhold the handshake, then reply. The SDK has no new timeout in the
        // binding-only patch; the test process watchdog bounds a GIL regression.
        println!("waiting");
        std::io::stdout().flush()?;
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
    let (pairing, mut noise, payload) = match first {
        Request::Hello { key_id, .. } => {
            let mut prologue = b"enody-v1 noise".to_vec();
            prologue.extend(key_id.as_bytes());
            prologue.extend(id().as_bytes());
            let noise = snow::Builder::new(WIFI_NOISE.parse()?)
                .psk(0, &[7; 32])?
                .prologue(&prologue)?
                .build_responder()?;
            let Request::Noise { payload } = read(&mut socket).await? else {
                return Err("expected Noise".into());
            };
            (false, noise, payload)
        }
        Request::PairingNoise { payload, .. } => {
            let noise = snow::Builder::new(WIFI_PAIRING_NOISE.parse()?)
                .prologue(b"enody-v1 pairing")?
                .build_responder()?;
            (true, noise, payload)
        }
        _ => return Err("expected hello".into()),
    };
    let mut buffer = [0; WIFI_FRAME_PAYLOAD_MAX_LEN];
    noise.read_message(&payload, &mut buffer)?;
    let len = noise.write_message(&[], &mut buffer)?;
    let payload = buffer[..len].try_into().unwrap();
    tokio::time::sleep(Duration::from_millis(250)).await;
    write(
        &mut socket,
        &if pairing {
            Response::PairingNoise { payload }
        } else {
            Response::Noise { payload }
        },
    )
    .await?;
    let mut noise = noise.into_transport_mode()?;
    if pairing {
        for e in [
            RuntimeEvent::TokenGenerateApproval("Approve test peer".try_into().unwrap()),
            RuntimeEvent::TokenGenerated(token()),
        ] {
            tokio::time::sleep(Duration::from_millis(250)).await;
            event(
                &mut socket,
                &mut noise,
                Message::Event(EventMessage {
                    identifier: id(),
                    context: None,
                    resource: None,
                    event: Event::Runtime(e),
                }),
                true,
            )
            .await?;
        }
        return Ok(());
    }
    let mut withheld = false;
    loop {
        let Request::Noise { payload } = read(&mut socket).await? else {
            return Err("expected encrypted command".into());
        };
        let len = noise.read_message(&payload, &mut buffer)?;
        let Message::Command(command) = postcard::from_bytes(&buffer[..len])? else {
            continue;
        };
        if !withheld
            && ((mode == "host-timeout"
                && matches!(command.command, Command::Host(HostCommand::Info)))
                || (mode == "display-timeout"
                    && matches!(
                        command.command,
                        Command::Fixture(FixtureCommand::Display(..))
                    )))
        {
            withheld = true;
            continue;
        }
        let response = match command.command.clone() {
            Command::Host(HostCommand::Info) => Event::Host(HostEvent::Info(HostInfo {
                identifier: id(),
                version: Version::new(1, 2, 3),
            })),
            Command::Host(HostCommand::FixtureCount) => Event::Host(HostEvent::FixtureCount(1)),
            Command::Host(HostCommand::FixtureInfo(_)) => {
                Event::Host(HostEvent::FixtureInfo(FixtureInfo { identifier: id() }))
            }
            Command::Fixture(FixtureCommand::SourceCount) => {
                Event::Fixture(FixtureEvent::SourceCount(1))
            }
            Command::Fixture(FixtureCommand::SourceInfo(_)) => {
                Event::Fixture(FixtureEvent::SourceInfo(SourceInfo { identifier: id() }))
            }
            Command::Source(SourceCommand::EmitterCount) => {
                Event::Source(SourceEvent::EmitterCount(1))
            }
            Command::Source(SourceCommand::EmitterInfo(_)) => {
                Event::Source(SourceEvent::EmitterInfo(EmitterInfo::new(id())))
            }
            Command::Fixture(FixtureCommand::Display(c, f)) => {
                Event::Fixture(FixtureEvent::Display(c, f))
            }
            Command::Source(SourceCommand::Display(c, f)) => {
                Event::Source(SourceEvent::Display(c, f))
            }
            Command::Emitter(EmitterCommand::FluxSet(f)) => {
                Event::Emitter(EmitterEvent::FluxSet(f))
            }
            Command::Emitter(EmitterCommand::SpectralData(SpectralDataCommand::SampleCount)) => {
                Event::Emitter(EmitterEvent::SpectralData(SpectralDataEvent::SampleCount(
                    0,
                )))
            }
            Command::Host(HostCommand::NetworkScan(_)) => {
                Event::Host(HostEvent::NetworkScanComplete(Default::default()))
            }
            Command::Host(HostCommand::NetworkJoin(n, _)) => {
                Event::Host(HostEvent::NetworkJoinComplete(n))
            }
            Command::Runtime(RuntimeCommand::TokenGenerate) => {
                Event::Runtime(RuntimeEvent::TokenGenerated(token()))
            }
            Command::Fixture(FixtureCommand::Transition(t)) => {
                println!("transition");
                std::io::stdout().flush()?;
                tokio::time::sleep(t.method.duration()).await;
                Event::Fixture(FixtureEvent::TransitionEnd(t.clone(), t.target))
            }
            Command::Source(SourceCommand::Transition(t)) => {
                println!("transition");
                std::io::stdout().flush()?;
                tokio::time::sleep(t.method.duration()).await;
                Event::Source(SourceEvent::TransitionEnd(t.clone(), t.target))
            }
            _ => Event::Error(enody::Error::Unsupported),
        };
        tokio::time::sleep(Duration::from_millis(200)).await;
        event(
            &mut socket,
            &mut noise,
            Message::Event(EventMessage::response_to(&command, response)),
            false,
        )
        .await?;
    }
}
#[tokio::main]
async fn main() -> Result<()> {
    tokio::spawn(async {
        tokio::time::sleep(Duration::from_secs(25)).await;
        std::process::exit(2);
    });
    let mode = std::env::args().nth(1).unwrap_or_default();
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    println!("{}", listener.local_addr()?);
    std::io::stdout().flush()?;
    let mut number = 0;
    loop {
        let (socket, _) = listener.accept().await?;
        let mode = mode.clone();
        let n = number;
        number += 1;
        tokio::spawn(async move {
            let _ = serve(socket, mode, n).await;
        });
    }
}
