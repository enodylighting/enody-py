# enody

Python SDK for [Enody Lighting](https://enody.lighting) spectrally tunable fixtures.

`enody` provides device discovery and control over USB and WiFi, spectral data access, colorimetric calculations, and GPU-accelerated spectral optimization via [tinygrad](https://github.com/tinygrad/tinygrad). It wraps the [enody-rs](https://github.com/enodylighting/enody-rs) Rust core through native PyO3 bindings.

## Updating an EP01

Install the package, connect your EP01 over USB, and run:

```bash
pip install enody
enody update
```

The CLI will detect the device, list available firmware versions, and prompt you to select one. To use an offline firmware image instead:

```bash
enody update -f firmware.bin
```

Other useful commands:

```bash
enody list                    # List connected devices
enody info                    # Show device details (fixtures, sources, emitters)
enody wifi-scan               # Scan WiFi networks through a USB-attached device
enody wifi-setup              # Join WiFi and save a USB-authenticated token
enody wifi-generate-token     # Generate and verify a WiFi token over WiFi
enody download-spectral-data  # Save emitter spectral data to JSON
```

## Installation

Requires Python >= 3.8.

```bash
pip install enody
```

### System dependencies

USB device access requires [libusb](https://libusb.info/):

| Platform | Command |
|----------|---------|
| macOS | `brew install libusb` |
| Debian / Ubuntu | `sudo apt install libusb-1.0-0` |
| Fedora / RHEL | `sudo dnf install libusb1` |
| Arch | `sudo pacman -S libusb` |
| Alpine | `apk add libusb` |
| Windows | Bundled — no action needed |

### Building from source

Requires [maturin](https://www.maturin.rs/) and a Rust toolchain:

```bash
pip install maturin
maturin develop
```

## Quick start

### Discover and connect to a device

```python
import enody

env = enody.UsbEnvironment()
runtimes = env.runtimes()
runtime = runtimes[0]

host = runtime.host()
print(f"Host {host.identifier()} (v{host.version()})")

fixture = host.fixtures()[0]
sources = fixture.sources()
```

### Set up WiFi

WiFi setup starts from a USB-attached EP01. The host scans nearby networks,
joins the selected SSID, then a token can be generated and stored for later
WiFi discovery.

```python
import enody

usb = enody.UsbEnvironment()
runtime = usb.runtimes()[0]
host = runtime.host()

for network in host.wifi_scan():
    print(network.ssid(), network.rssi(), network.auth())

host.wifi_join("Studio WiFi", "password")
token = runtime.generate_token()
enody.TokenStore.save_token(token)
```

### Pair and authorize over WiFi

For integrations such as Home Assistant, use the WiFi pairing flow. It discovers
EP01 devices over mDNS, waits for physical approval on the device, verifies the
token by reconnecting over WiFi, and returns a `Token` that can be stored by the
integration.

```python
import enody

token = enody.generate_wifi_token(
    on_approval=lambda instruction: print("Approval required:", instruction),
    save=False,
)

runtime = enody.WifiConnection.runtime_from_endpoint(token, "192.168.1.50:8788")
runtime.connect()
host = runtime.host()
print(host.identifier())
runtime.disconnect()
```

Saved tokens can be loaded through the token store and used for WiFi discovery:

```python
tokens = enody.TokenStore.load().tokens()
wifi = enody.WifiEnvironment(tokens)
for runtime in wifi.runtimes():
    print(runtime.host().identifier())
```

### Control emitters directly

```python
from enody import Configuration, Flux

for emitter in sources[0].emitters():
    emitter.set_flux(Flux.relative(0.5))
fixture.display(Configuration.manual(), Flux.relative(1.0))
```

### Use built-in display modes

```python
from enody import Configuration, Flux

# Set to 2700K blackbody
fixture.display(Configuration.blackbody(2700), Flux.relative(1.0))

# Set to a CIE 1931 chromaticity coordinate
fixture.display(Configuration.chromatic(0.3127, 0.3290), Flux.relative(0.8))
```

### Work offline with sample data

No device required — use bundled spectral data for algorithm development:

```python
import enody.data

fixture = enody.data.sample_fixture()   # 1 source, 12 emitters
source = enody.data.sample_source()     # First source from fixture
emitter = enody.data.sample_emitter()   # First emitter from source
```

## Architecture

Enody is a federated system where Runtimes communicate via message passing. An **Environment** is the entry point for device discovery and resource access — it owns connections to remote Runtimes and exposes the resources they contain. Discovery environments (`UsbEnvironment`, `WifiEnvironment`) actively scan for devices, while user-defined environments allow manual organization of resources.

Fixtures are addressed by identifier, independent of which Host owns them. Commands route through the Enody device network with hop-aware routing, enabling location transparency and multi-hop delivery.

### Entity hierarchy

```
Environment → Runtime → Host → Fixture → Source → Emitter
```

- **Environment** — Discovery and organizational surface. Owns connections to remote Runtimes and provides access to their resources.
- **Runtime** — A message-passing participant in the Enody mesh. Has exactly one Host.
- **Host** — The physical device, identified by UUID and firmware version.
- **Fixture** — An addressable light output unit.
- **Source** — An independently controllable region within a fixture.
- **Emitter** — A single LED channel with a characteristic spectral distribution (380--780 nm, 1 nm resolution, 401 samples).

Each level can be constructed from a connected device (`from_device`) or from JSON data (`from_json`).

## Spectral optimization

Every `Emitter`, `Source`, and `Fixture` exposes a `.tensor()` method returning a tinygrad `Tensor` of spectral values, ready for differentiable optimization.

### Match a blackbody spectrum

```python
import colour
from tinygrad import nn
from tinygrad.tensor import Tensor, dtypes
from enody import Flux
from enody.optimize import ssi, cie_1931_chromaticity

source = fixture.sources()[0]
spd_matrix = source.tensor()  # (n_emitters, 401)
n = len(source.emitters())

# Reference blackbody at 4000K
ref_sd = colour.sd_blackbody(4000, colour.SpectralShape(380, 780, 1))
ref = Tensor([ref_sd.values.tolist()], dtype=dtypes.float32)

weights = Tensor.ones(1, n, dtype=dtypes.float32) * 0.5
optimizer = nn.optim.Adam([weights], lr=1e-3)

for i in range(1000):
    optimizer.zero_grad()
    duty_cycles = weights.clip(0, 1)
    emission = (duty_cycles @ spd_matrix) + 1e-9

    # SSI loss (uses 380-680nm, 301 samples)
    ssi_score = ssi(emission.shrink((None, (0, 301))),
                    ref.shrink((None, (0, 301))))
    spectral_loss = (100.0 - ssi_score).sum()

    # Chromaticity loss (uses full 401 samples)
    chrom_loss = ((cie_1931_chromaticity(emission)
                 - cie_1931_chromaticity(ref)).square().sum(axis=0) + 1e-9).sqrt().sum()

    loss = spectral_loss / 2500 + chrom_loss / 5
    loss.backward()
    optimizer.step()
```

Apply optimized weights to hardware:

```python
w = weights.clip(0, 1).numpy().flatten()
for idx, emitter in enumerate(source.emitters()):
    emitter.set_flux(Flux.relative(float(w[idx])))
fixture.display(Configuration.manual(), Flux.relative(1.0))
```

## API reference

### `enody.data`

All sample data is extracted from a single bundled fixture (`data/fixture.json`).

| Function | Returns |
|---|---|
| `sample_fixture()` | `Fixture` with 1 source, 12 emitters |
| `sample_source()` | First `Source` from the sample fixture |
| `sample_emitter()` | First `Emitter` from the sample source |
| `melanopic_action()` | Melanopic response measurements (list of float) |
| `rhodopic_action()` | Rhodopic response measurements |
| `s_cone_action()` | S-cone-opic response measurements |
| `m_cone_action()` | M-cone-opic response measurements |
| `l_cone_action()` | L-cone-opic response measurements |
| `cie_x_action()` | CIE X color matching function measurements |
| `cie_y_action()` | CIE Y color matching function measurements |
| `cie_z_action()` | CIE Z color matching function measurements |

### `enody.optimize`

All photopic response functions accept `(n, 401)` tensors (380--780 nm):

| Function | Description |
|---|---|
| `melanopic_response(t)` | Melanopic (ipRGC) response |
| `rhodopic_response(t)` | Rhodopic (rod) response |
| `s_cone_response(t)` | S-cone-opic response |
| `m_cone_response(t)` | M-cone-opic response |
| `l_cone_response(t)` | L-cone-opic response |
| `cie_x_response(t)` | CIE X tristimulus response |
| `cie_y_response(t)` | CIE Y tristimulus response |
| `cie_z_response(t)` | CIE Z tristimulus response |
| `cie_1931_chromaticity(t)` | CIE 1931 (x, y) chromaticity coordinates |

SSI accepts `(n, 301)` tensors (380--680 nm):

| Function | Description |
|---|---|
| `ssi(test, reference)` | Spectral Similarity Index (0--100) |

### `enody.colorimetry`

Pure Python color science types with `colour-science` integration:

- `SpectralData(samples)` — spectral distribution with `.spectral_distribution()` and `.tensor()`
- `SpectralSample(wavelength, measurement)` — single wavelength/measurement pair (properties, not methods)
- `Chromaticity(x, y)`
- `XYZ(x, y, z)`

### Core types (from `enody._enody_rs`)

| Type | Description |
|---|---|
| `Flux.relative(value)` | Relative flux (0.0--1.0) |
| `Configuration.blackbody(cct)` | Blackbody spectrum at given CCT |
| `Configuration.chromatic(x, y)` | Target CIE 1931 chromaticity |
| `Configuration.manual()` | Manual per-emitter control |
| `Configuration.flux()` | Flux-only control mode |
| `Configuration.spectral()` | Spectral control mode |
| `SpectralSample(wavelength, measurement)` | Single wavelength/measurement pair |
| `SpectralData` | Collection of spectral samples |
| `Chromaticity(x, y)` | CIE chromaticity coordinate |
| `Token(host_id, key_id, data)` | WiFi authorization token |
| `TokenStore` | Load, save, and upsert stored WiFi tokens |
| `WifiEnvironment(tokens)` | Discover authenticated devices over WiFi |
| `WifiConnection` | mDNS discovery, pairing, and direct WiFi runtime helpers |
| `WifiNetwork` | WiFi scan result |
| `WifiDiscoveredDevice` | mDNS-discovered EP01 metadata |

## JSON data format

Spectral data is encoded as a list of `SpectralSample` objects, directly reflecting the internal type:

```json
{
  "identifier": "uuid-string",
  "sources": [{
    "identifier": "uuid-string",
    "emitters": [{
      "identifier": "uuid-string",
      "spectral_data": [
        {"wavelength": 380.0, "measurement": 0.0},
        {"wavelength": 381.0, "measurement": 0.001},
        ...
      ]
    }]
  }]
}
```

Response data (`response.json`) uses the same sample list format:

```json
{
  "Melanopic response": [
    {"wavelength": 380.0, "measurement": 0.0},
    ...
  ]
}
```

## Dependencies

- [tinygrad](https://github.com/tinygrad/tinygrad) — tensor operations and automatic differentiation
- [colour-science](https://www.colour-science.org/) — color science computations and plotting
- [enody-rs](https://github.com/enodylighting/enody-rs) — Rust core SDK (compiled via PyO3)

## License

MIT
