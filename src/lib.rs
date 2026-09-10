use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::{
    collections::HashMap,
    sync::{Arc, Mutex, OnceLock, Weak},
    time::Duration,
};

fn get_or_init_runtime() -> &'static tokio::runtime::Runtime {
    static RT: std::sync::OnceLock<tokio::runtime::Runtime> = std::sync::OnceLock::new();
    RT.get_or_init(|| tokio::runtime::Runtime::new().unwrap())
}

// All closures contain only native values. Python argument extraction and
// result wrapping stay on the GIL side of this boundary.
fn run_native<T: Send>(py: Python<'_>, operation: impl FnOnce() -> T + Send) -> T {
    py.allow_threads(operation)
}

// The upstream transport was previously serialized by the GIL. Retain that
// ordering per native connection, including its child handles, without blocking
// Python or other connections. Admission is intentionally not deadline-bound.
type DeviceGate = Arc<Mutex<()>>;

fn device_gate(runtime: &enody::runtime::remote::RemoteRuntime) -> DeviceGate {
    static GATES: OnceLock<Mutex<HashMap<usize, Weak<Mutex<()>>>>> = OnceLock::new();
    // Cloned runtimes expose the same Arc connection. Key by allocation identity,
    // not host UUID: two independent connections to one host must not share a gate.
    let connection = runtime.connection();
    let key = Arc::as_ptr(&connection) as *const () as usize;
    let mut gates = GATES.get_or_init(Mutex::default).lock().unwrap();
    gates.retain(|_, gate| gate.strong_count() != 0);
    if let Some(gate) = gates.get(&key).and_then(Weak::upgrade) {
        return gate;
    }
    let gate = Arc::new(Mutex::new(()));
    gates.insert(key, Arc::downgrade(&gate));
    gate
}

fn run_device<T: Send>(
    py: Python<'_>,
    gate: &Mutex<()>,
    operation: impl FnOnce() -> Result<T, enody::Error> + Send,
) -> Result<T, enody::Error> {
    run_native(py, move || {
        let _guard = gate.lock().map_err(|_| {
            enody::Error::Debug("device operation lock poisoned by a native panic".into())
        })?;
        operation()
    })
}

// USB backends are thread-affine (not Send/Sync). Keep discovery environments on
// one native owner thread, including destruction, and release the GIL while
// waiting for replies. No unsafe Send implementation or Python objects cross it.
type EnvironmentJob<T> = Box<dyn FnOnce(&mut T) + Send>;
struct EnvironmentWorker<T> {
    sender: std::sync::mpsc::Sender<EnvironmentJob<T>>,
}

impl<T: 'static> EnvironmentWorker<T> {
    fn new(
        py: Python<'_>,
        create: impl FnOnce() -> Result<T, enody::Error> + Send + 'static,
    ) -> PyResult<Self> {
        run_native(py, move || {
            let (sender, receiver) = std::sync::mpsc::channel::<EnvironmentJob<T>>();
            let (ready_tx, ready_rx) = std::sync::mpsc::sync_channel(1);
            std::thread::Builder::new()
                .name("enody-discovery".into())
                .spawn(move || {
                    let _context = get_or_init_runtime().enter();
                    match create() {
                        Ok(mut environment) => {
                            if ready_tx.send(Ok(())).is_ok() {
                                for job in receiver {
                                    job(&mut environment);
                                }
                            }
                            // Environment teardown can join threads and disconnect devices.
                            // It deliberately runs here, never in Python's GC with the GIL.
                        }
                        Err(error) => {
                            let _ = ready_tx.send(Err(error));
                        }
                    }
                })
                .map_err(|e| enody::Error::Debug(e.to_string()))?;
            ready_rx
                .recv()
                .map_err(|_| enody::Error::Debug("discovery worker stopped".into()))??;
            Ok(Self { sender })
        })
        .map_err(enody_err)
    }

    fn call<R: Send + 'static>(
        &self,
        py: Python<'_>,
        operation: impl FnOnce(&mut T) -> R + Send + 'static,
    ) -> PyResult<R> {
        run_native(py, || {
            let (tx, rx) = std::sync::mpsc::sync_channel(1);
            self.sender
                .send(Box::new(move |environment| {
                    let _ = tx.send(operation(environment));
                }))
                .map_err(|_| enody::Error::Debug("discovery worker stopped".into()))?;
            rx.recv()
                .map_err(|_| enody::Error::Debug("discovery worker stopped".into()))
        })
        .map_err(enody_err)
    }
}

fn enody_err(e: enody::Error) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{:?}", e))
}

fn argument_err(message: impl Into<String>) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyValueError, _>(message.into())
}

fn parse_identifier(identifier: &str) -> PyResult<enody::Identifier> {
    identifier
        .parse()
        .map_err(|_| argument_err(format!("invalid identifier: {identifier}")))
}

fn wifi_auth_to_string(auth: &enody::message::WifiAuth) -> &'static str {
    match auth {
        enody::message::WifiAuth::Unknown => "unknown",
        enody::message::WifiAuth::Open => "open",
        enody::message::WifiAuth::Secured => "secured",
    }
}

fn format_bssid(bssid: &[u8; 6]) -> String {
    format!(
        "{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}",
        bssid[0], bssid[1], bssid[2], bssid[3], bssid[4], bssid[5]
    )
}

// ---------------------------------------------------------------------------
// SpectralData
// ---------------------------------------------------------------------------

#[pyclass(name = "SpectralData")]
pub struct PySpectralData {
    inner: enody::spectral::SpectralData,
}

#[pymethods]
impl PySpectralData {
    fn samples(&self) -> Vec<PySpectralSample> {
        self.inner
            .samples()
            .iter()
            .map(|s| PySpectralSample { inner: s.clone() })
            .collect()
    }

    fn wavelengths(&self) -> Vec<f32> {
        self.inner
            .samples()
            .iter()
            .map(|s| s.wavelength())
            .collect()
    }

    fn measurements(&self) -> Vec<f32> {
        self.inner
            .samples()
            .iter()
            .map(|s| s.measurement())
            .collect()
    }

    fn sample_count(&self) -> usize {
        self.inner.samples().len()
    }

    fn __repr__(&self) -> String {
        format!("SpectralData(samples={})", self.inner.samples().len())
    }
}

// ---------------------------------------------------------------------------
// SpectralSample
// ---------------------------------------------------------------------------

#[pyclass(name = "SpectralSample")]
#[derive(Clone)]
pub struct PySpectralSample {
    inner: enody::spectral::SpectralSample,
}

#[pymethods]
impl PySpectralSample {
    #[new]
    fn new(wavelength: f32, measurement: f32) -> Self {
        Self {
            inner: enody::spectral::SpectralSample::new(wavelength, measurement),
        }
    }

    #[getter]
    fn wavelength(&self) -> f32 {
        self.inner.wavelength()
    }

    #[getter]
    fn measurement(&self) -> f32 {
        self.inner.measurement()
    }

    fn __repr__(&self) -> String {
        format!(
            "SpectralSample(wavelength={}, measurement={})",
            self.inner.wavelength(),
            self.inner.measurement()
        )
    }
}

// ---------------------------------------------------------------------------
// Chromaticity
// ---------------------------------------------------------------------------

#[pyclass(name = "Chromaticity")]
#[derive(Clone)]
pub struct PyChromaticity {
    inner: enody::message::Chromaticity,
}

#[pymethods]
impl PyChromaticity {
    #[new]
    fn new(x: f32, y: f32) -> Self {
        Self {
            inner: enody::message::Chromaticity { x, y },
        }
    }

    #[getter]
    fn x(&self) -> f32 {
        self.inner.x
    }

    #[getter]
    fn y(&self) -> f32 {
        self.inner.y
    }

    fn __repr__(&self) -> String {
        format!("Chromaticity(x={}, y={})", self.inner.x, self.inner.y)
    }
}

// ---------------------------------------------------------------------------
// Flux
// ---------------------------------------------------------------------------

#[pyclass(name = "Flux")]
#[derive(Clone)]
pub struct PyFlux {
    inner: enody::message::Flux,
}

#[pymethods]
impl PyFlux {
    #[staticmethod]
    fn relative(value: f32) -> Self {
        Self {
            inner: enody::message::Flux::Relative(value),
        }
    }

    #[getter]
    fn value(&self) -> f32 {
        match self.inner {
            enody::message::Flux::Relative(v) => v,
        }
    }

    fn __repr__(&self) -> String {
        match self.inner {
            enody::message::Flux::Relative(v) => format!("Flux.relative({})", v),
        }
    }
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

#[pyclass(name = "Configuration")]
#[derive(Clone)]
pub struct PyConfiguration {
    inner: enody::message::Configuration,
}

#[pymethods]
impl PyConfiguration {
    #[staticmethod]
    fn blackbody(cct: f32) -> Self {
        Self {
            inner: enody::message::Configuration::Blackbody(cct),
        }
    }

    #[staticmethod]
    fn chromatic(x: f32, y: f32) -> Self {
        Self {
            inner: enody::message::Configuration::Chromatic(enody::message::Chromaticity { x, y }),
        }
    }

    #[staticmethod]
    fn manual() -> Self {
        Self {
            inner: enody::message::Configuration::Manual,
        }
    }

    #[staticmethod]
    fn flux() -> Self {
        Self {
            inner: enody::message::Configuration::Flux,
        }
    }

    #[staticmethod]
    fn spectral() -> Self {
        Self {
            inner: enody::message::Configuration::Spectral,
        }
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}

// ---------------------------------------------------------------------------
// Transition
// ---------------------------------------------------------------------------

#[pyclass(name = "Transition")]
#[derive(Clone)]
pub struct PyTransition {
    configuration: enody::message::Configuration,
    flux: enody::message::Flux,
    method: enody::message::TransitionMethod,
}

impl PyTransition {
    fn fixture_transition(&self) -> enody::message::Transition<enody::message::FixtureState> {
        enody::message::Transition {
            target: enody::message::FixtureState::new(
                self.configuration.clone(),
                self.flux.clone(),
            ),
            method: self.method.clone(),
        }
    }

    fn source_transition(&self) -> enody::message::Transition<enody::message::SourceState> {
        enody::message::Transition {
            target: enody::message::SourceState::new(self.configuration.clone(), self.flux.clone()),
            method: self.method.clone(),
        }
    }
}

#[pymethods]
impl PyTransition {
    #[staticmethod]
    fn linear(configuration: &PyConfiguration, flux: &PyFlux, duration: f64) -> PyResult<Self> {
        let duration = Duration::try_from_secs_f64(duration).map_err(|_| {
            argument_err("duration must be a finite, non-negative number of seconds")
        })?;

        Ok(Self {
            configuration: configuration.inner.clone(),
            flux: flux.inner.clone(),
            method: enody::message::TransitionMethod::Linear(duration),
        })
    }

    #[getter]
    fn configuration(&self) -> PyConfiguration {
        PyConfiguration {
            inner: self.configuration.clone(),
        }
    }

    #[getter]
    fn flux(&self) -> PyFlux {
        PyFlux {
            inner: self.flux.clone(),
        }
    }

    #[getter]
    fn duration(&self) -> f64 {
        self.method.duration().as_secs_f64()
    }

    fn __repr__(&self) -> String {
        format!(
            "Transition.linear({:?}, {:?}, {})",
            self.configuration,
            self.flux,
            self.method.duration().as_secs_f64()
        )
    }
}

// ---------------------------------------------------------------------------
// Token
// ---------------------------------------------------------------------------

#[pyclass(name = "Token")]
#[derive(Clone)]
pub struct PyToken {
    inner: enody::message::Token,
}

#[pymethods]
impl PyToken {
    #[new]
    fn new(host_id: String, key_id: String, data: Vec<u8>) -> PyResult<Self> {
        Ok(Self {
            inner: enody::message::Token {
                host_id: parse_identifier(&host_id)?,
                key_id: key_id
                    .as_str()
                    .try_into()
                    .map_err(|_| argument_err("key_id is too long"))?,
                data: data
                    .as_slice()
                    .try_into()
                    .map_err(|_| argument_err("token data is too long"))?,
            },
        })
    }

    fn host_id(&self) -> String {
        self.inner.host_id.to_string()
    }

    fn key_id(&self) -> String {
        self.inner.key_id.to_string()
    }

    fn data(&self) -> Vec<u8> {
        self.inner.data.to_vec()
    }

    fn __repr__(&self) -> String {
        format!(
            "Token(host_id='{}', key_id='{}', data=<redacted>)",
            self.inner.host_id, self.inner.key_id
        )
    }
}

// ---------------------------------------------------------------------------
// TokenStore
// ---------------------------------------------------------------------------

#[pyclass(name = "TokenStore")]
#[derive(Clone)]
pub struct PyTokenStore {
    inner: enody::token_store::TokenStore,
}

#[pymethods]
impl PyTokenStore {
    #[new]
    fn new() -> Self {
        Self {
            inner: enody::token_store::TokenStore::default(),
        }
    }

    #[staticmethod]
    fn load() -> PyResult<Self> {
        enody::token_store::TokenStore::load()
            .map(|inner| Self { inner })
            .map_err(enody_err)
    }

    #[staticmethod]
    fn load_from_path(path: String) -> PyResult<Self> {
        enody::token_store::TokenStore::load_from_path(path)
            .map(|inner| Self { inner })
            .map_err(enody_err)
    }

    #[staticmethod]
    fn path() -> PyResult<String> {
        enody::token_store::TokenStore::path()
            .map(|path| path.display().to_string())
            .map_err(enody_err)
    }

    #[staticmethod]
    fn config_dir() -> PyResult<String> {
        enody::token_store::TokenStore::config_dir()
            .map(|path| path.display().to_string())
            .map_err(enody_err)
    }

    #[staticmethod]
    fn save_token(token: &PyToken) -> PyResult<String> {
        enody::token_store::TokenStore::save_token(&token.inner)
            .map(|path| path.display().to_string())
            .map_err(enody_err)
    }

    fn tokens(&self) -> Vec<PyToken> {
        self.inner
            .tokens()
            .iter()
            .cloned()
            .map(|inner| PyToken { inner })
            .collect()
    }

    fn upsert(&mut self, token: &PyToken) {
        self.inner.upsert(token.inner.clone());
    }

    fn save(&self) -> PyResult<String> {
        self.inner
            .save()
            .map(|path| path.display().to_string())
            .map_err(enody_err)
    }

    fn save_to_path(&self, path: String) -> PyResult<()> {
        self.inner.save_to_path(path).map_err(enody_err)
    }
}

// ---------------------------------------------------------------------------
// WifiNetwork
// ---------------------------------------------------------------------------

#[pyclass(name = "WifiNetwork")]
#[derive(Clone)]
pub struct PyWifiNetwork {
    inner: enody::message::WifiNetwork,
}

#[pymethods]
impl PyWifiNetwork {
    fn ssid(&self) -> Option<String> {
        self.inner.ssid.as_ref().map(|ssid| ssid.to_string())
    }

    fn bssid(&self) -> Option<String> {
        self.inner.bssid.as_ref().map(format_bssid)
    }

    fn channel(&self) -> Option<u8> {
        self.inner.channel
    }

    fn rssi(&self) -> Option<i8> {
        self.inner.rssi
    }

    fn auth(&self) -> Option<String> {
        self.inner
            .auth
            .as_ref()
            .map(wifi_auth_to_string)
            .map(str::to_string)
    }

    fn __repr__(&self) -> String {
        format!(
            "WifiNetwork(ssid={:?}, bssid={:?}, channel={:?}, rssi={:?}, auth={:?})",
            self.ssid(),
            self.bssid(),
            self.inner.channel,
            self.inner.rssi,
            self.auth()
        )
    }
}

// ---------------------------------------------------------------------------
// EnvironmentRuntimeEvent
// ---------------------------------------------------------------------------

#[pyclass(name = "EnvironmentRuntimeEvent")]
#[derive(Clone)]
pub struct PyEnvironmentRuntimeEvent {
    kind: String,
    runtime: PyRuntime,
}

#[pymethods]
impl PyEnvironmentRuntimeEvent {
    fn kind(&self) -> String {
        self.kind.clone()
    }

    fn runtime(&self) -> PyRuntime {
        self.runtime.clone()
    }

    fn __repr__(&self) -> String {
        format!("EnvironmentRuntimeEvent(kind='{}')", self.kind)
    }
}

fn environment_runtime_event(
    event: enody::environment::EnvironmentRuntimeEvent,
) -> PyEnvironmentRuntimeEvent {
    match event {
        enody::environment::EnvironmentRuntimeEvent::Arrived(runtime) => {
            PyEnvironmentRuntimeEvent {
                kind: "arrived".to_string(),
                runtime: PyRuntime::from_native(runtime),
            }
        }
        enody::environment::EnvironmentRuntimeEvent::Left(runtime) => PyEnvironmentRuntimeEvent {
            kind: "left".to_string(),
            runtime: PyRuntime::from_native(runtime),
        },
    }
}

// ---------------------------------------------------------------------------
// UsbEnvironment
// ---------------------------------------------------------------------------

#[pyclass(name = "UsbEnvironment", unsendable)]
pub struct PyUsbEnvironment {
    inner: EnvironmentWorker<enody::usb::UsbEnvironment>,
}

#[pymethods]
impl PyUsbEnvironment {
    #[new]
    fn new(py: Python<'_>) -> PyResult<Self> {
        let inner = EnvironmentWorker::new(py, || Ok(enody::usb::UsbEnvironment::new()))?;
        Ok(Self { inner })
    }

    fn runtimes(&self, py: Python<'_>) -> PyResult<Vec<PyRuntime>> {
        use enody::environment::Environment;
        let runtimes = self.inner.call(py, |inner| inner.runtimes())?;
        Ok(runtimes.into_iter().map(PyRuntime::from_native).collect())
    }

    fn start_discovery(&mut self, py: Python<'_>) -> PyResult<()> {
        use enody::environment::DiscoveryEnvironment;
        self.inner
            .call(py, |inner| {
                get_or_init_runtime().block_on(inner.start_discovery())
            })?
            .map_err(enody_err)
    }

    fn stop_discovery(&mut self, py: Python<'_>) -> PyResult<()> {
        use enody::environment::DiscoveryEnvironment;
        self.inner
            .call(py, |inner| {
                get_or_init_runtime().block_on(inner.stop_discovery())
            })?
            .map_err(enody_err)
    }

    fn next_runtime_event(&self, py: Python<'_>) -> PyResult<PyEnvironmentRuntimeEvent> {
        use enody::environment::DiscoveryEnvironment;
        let event = self
            .inner
            .call(py, |inner| {
                get_or_init_runtime().block_on(inner.next_runtime_event())
            })?
            .map_err(enody_err)?;
        Ok(environment_runtime_event(event))
    }
}

// ---------------------------------------------------------------------------
// Runtime (wraps RemoteRuntime)
// ---------------------------------------------------------------------------

#[pyclass(name = "Runtime")]
#[derive(Clone)]
pub struct PyRuntime {
    inner: enody::runtime::remote::RemoteRuntime,
    gate: DeviceGate,
}

impl PyRuntime {
    fn from_native(inner: enody::runtime::remote::RemoteRuntime) -> Self {
        let gate = device_gate(&inner);
        Self { inner, gate }
    }
}

#[pymethods]
impl PyRuntime {
    fn host(&self, py: Python<'_>) -> PyResult<PyHost> {
        let inner = self.inner.clone();
        let host = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.host())
        })
        .map_err(enody_err)?;
        Ok(PyHost {
            inner: host,
            gate: self.gate.clone(),
        })
    }

    fn connect(&self, py: Python<'_>) -> PyResult<()> {
        let inner = self.inner.clone();
        run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.connect())
        })
        .map_err(enody_err)
    }

    fn disconnect(&self, py: Python<'_>) -> PyResult<()> {
        let inner = self.inner.clone();
        run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.disconnect())
        })
        .map_err(enody_err)
    }

    fn is_connected(&self) -> bool {
        self.inner.is_connected()
    }

    fn enable_logging(&self) {
        self.inner.enable_logging();
    }

    fn generate_token(&self, py: Python<'_>) -> PyResult<PyToken> {
        let inner = self.inner.clone();
        let token = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.generate_token())
        })
        .map_err(enody_err)?;
        Ok(PyToken { inner: token })
    }
}

// ---------------------------------------------------------------------------
// Host (wraps RemoteHost)
// ---------------------------------------------------------------------------

#[pyclass(name = "Host")]
#[derive(Clone)]
pub struct PyHost {
    inner: enody::host::remote::RemoteHost,
    gate: DeviceGate,
}

#[pymethods]
impl PyHost {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn version(&self) -> String {
        self.inner.version().to_string()
    }

    fn fixtures(&self, py: Python<'_>) -> PyResult<Vec<PyFixture>> {
        let inner = self.inner.clone();
        let fixtures = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.fixtures())
        })
        .map_err(enody_err)?;
        Ok(fixtures
            .into_iter()
            .map(|f| PyFixture {
                inner: f,
                gate: self.gate.clone(),
            })
            .collect())
    }

    fn wifi_scan(&self, py: Python<'_>) -> PyResult<Vec<PyWifiNetwork>> {
        let inner = self.inner.clone();
        let networks = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.wifi_scan())
        })
        .map_err(enody_err)?;
        Ok(networks
            .into_iter()
            .map(|network| match network {
                enody::message::Network::Wifi(inner) => PyWifiNetwork { inner },
            })
            .collect())
    }

    #[pyo3(signature = (ssid, password = ""))]
    fn wifi_join(&self, py: Python<'_>, ssid: &str, password: &str) -> PyResult<()> {
        let inner = self.inner.clone();
        let ssid = ssid.to_owned();
        let password = password.to_owned();
        run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.wifi_join(&ssid, &password))
        })
        .map_err(enody_err)
    }
}

// ---------------------------------------------------------------------------
// Fixture (wraps RemoteFixture)
// ---------------------------------------------------------------------------

#[pyclass(name = "Fixture")]
#[derive(Clone)]
pub struct PyFixture {
    inner: enody::fixture::remote::RemoteFixture,
    gate: DeviceGate,
}

#[pymethods]
impl PyFixture {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn sources(&self, py: Python<'_>) -> PyResult<Vec<PySource>> {
        let inner = self.inner.clone();
        let sources = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.sources())
        })
        .map_err(enody_err)?;
        Ok(sources
            .into_iter()
            .map(|s| PySource {
                inner: Arc::new(s),
                gate: self.gate.clone(),
            })
            .collect())
    }

    fn display(
        &self,
        py: Python<'_>,
        config: &PyConfiguration,
        flux: &PyFlux,
    ) -> PyResult<(PyConfiguration, PyFlux)> {
        let inner = self.inner.clone();
        let config = config.inner.clone();
        let flux = flux.inner.clone();
        let (cfg, f) = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.display(config, flux))
        })
        .map_err(enody_err)?;
        Ok((PyConfiguration { inner: cfg }, PyFlux { inner: f }))
    }

    fn transition(
        &self,
        py: Python<'_>,
        transition: &PyTransition,
    ) -> PyResult<(PyConfiguration, PyFlux)> {
        let inner = self.inner.clone();
        let transition = transition.fixture_transition();
        let state = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.transition(transition))
        })
        .map_err(enody_err)?;
        Ok((
            PyConfiguration {
                inner: state.configuration,
            },
            PyFlux { inner: state.flux },
        ))
    }
}

// ---------------------------------------------------------------------------
// Source (wraps RemoteSource)
// ---------------------------------------------------------------------------

#[pyclass(name = "Source")]
pub struct PySource {
    inner: Arc<enody::source::remote::RemoteSource>,
    gate: DeviceGate,
}

#[pymethods]
impl PySource {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn emitters(&self, py: Python<'_>) -> PyResult<Vec<PyEmitter>> {
        let inner = self.inner.clone();
        let emitters = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.emitters())
        })
        .map_err(enody_err)?;
        Ok(emitters
            .into_iter()
            .map(|e| PyEmitter {
                inner: Arc::new(e),
                gate: self.gate.clone(),
            })
            .collect())
    }

    fn display(
        &self,
        py: Python<'_>,
        config: &PyConfiguration,
        flux: &PyFlux,
    ) -> PyResult<(PyConfiguration, PyFlux)> {
        let inner = self.inner.clone();
        let config = config.inner.clone();
        let flux = flux.inner.clone();
        let (cfg, f) = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.display(config, flux))
        })
        .map_err(enody_err)?;
        Ok((PyConfiguration { inner: cfg }, PyFlux { inner: f }))
    }

    fn transition(
        &self,
        py: Python<'_>,
        transition: &PyTransition,
    ) -> PyResult<(PyConfiguration, PyFlux)> {
        let inner = self.inner.clone();
        let transition = transition.source_transition();
        let state = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.transition(transition))
        })
        .map_err(enody_err)?;
        Ok((
            PyConfiguration {
                inner: state.configuration,
            },
            PyFlux { inner: state.flux },
        ))
    }
}

// ---------------------------------------------------------------------------
// Emitter (wraps RemoteEmitter)
// ---------------------------------------------------------------------------

#[pyclass(name = "Emitter")]
pub struct PyEmitter {
    inner: Arc<enody::emitter::remote::RemoteEmitter>,
    gate: DeviceGate,
}

#[pymethods]
impl PyEmitter {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn spectral_data(&self, py: Python<'_>) -> PyResult<PySpectralData> {
        let inner = self.inner.clone();
        let sd = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.spectral_data())
        })
        .map_err(enody_err)?;
        Ok(PySpectralData { inner: sd })
    }

    fn set_flux(&self, py: Python<'_>, flux: &PyFlux) -> PyResult<PyFlux> {
        let inner = self.inner.clone();
        let flux = flux.inner.clone();
        let result = run_device(py, &self.gate, move || {
            get_or_init_runtime().block_on(inner.set_flux(flux))
        })
        .map_err(enody_err)?;
        Ok(PyFlux { inner: result })
    }
}

// ---------------------------------------------------------------------------
// WifiDiscoveredDevice
// ---------------------------------------------------------------------------

#[pyclass(name = "WifiDiscoveredDevice")]
#[derive(Clone)]
pub struct PyWifiDiscoveredDevice {
    inner: enody::wifi::WifiDiscoveredDevice,
}

#[pymethods]
impl PyWifiDiscoveredDevice {
    fn instance(&self) -> String {
        self.inner.instance.clone()
    }

    fn host(&self) -> String {
        self.inner.host.clone()
    }

    fn address(&self) -> Option<String> {
        self.inner.address.map(|address| address.to_string())
    }

    fn model(&self) -> Option<String> {
        self.inner.model.clone()
    }

    fn api_version(&self) -> Option<u8> {
        self.inner.api_version
    }

    fn host_id(&self) -> Option<String> {
        self.inner.host_id.map(|host_id| host_id.to_string())
    }

    fn firmware_version(&self) -> Option<String> {
        self.inner.firmware_version.clone()
    }

    fn http_port(&self) -> Option<u16> {
        self.inner.http_port
    }

    fn port(&self) -> Option<u16> {
        self.inner.port
    }

    fn protocol(&self) -> Option<String> {
        self.inner.protocol.clone()
    }

    fn auth(&self) -> Option<String> {
        self.inner.auth.clone()
    }

    fn endpoint(&self) -> Option<String> {
        self.inner.endpoint()
    }

    fn is_ep01(&self) -> bool {
        self.inner.is_ep01()
    }

    fn is_token_generation_candidate(&self) -> bool {
        self.inner.is_token_generation_candidate()
    }

    fn __repr__(&self) -> String {
        format!(
            "WifiDiscoveredDevice(host_id={:?}, endpoint={:?}, firmware_version={:?})",
            self.host_id(),
            self.inner.endpoint(),
            self.inner.firmware_version
        )
    }
}

// ---------------------------------------------------------------------------
// WifiConnection
// ---------------------------------------------------------------------------

#[pyclass(name = "WifiConnection")]
pub struct PyWifiConnection;

fn run_with_approval_callback<F>(
    py: Python<'_>,
    callback: Option<Py<PyAny>>,
    operation: F,
) -> PyResult<PyToken>
where
    F: FnOnce(&mut dyn FnMut(&str)) -> Result<enody::message::Token, enody::Error> + Send,
{
    py.allow_threads(move || {
        let mut callback_error: Option<PyErr> = None;
        let mut on_approval = |instruction: &str| {
            if callback_error.is_some() {
                return;
            }
            if let Some(callback) = callback.as_ref() {
                Python::with_gil(|py| {
                    if let Err(error) = callback.call1(py, (instruction,)) {
                        callback_error = Some(error);
                    }
                });
            }
        };

        let result = operation(&mut on_approval);
        if let Some(error) = callback_error {
            return Err(error);
        }
        result.map(|inner| PyToken { inner }).map_err(enody_err)
    })
}

#[pymethods]
impl PyWifiConnection {
    #[staticmethod]
    #[pyo3(signature = (timeout_ms = 800))]
    fn discover_token_generation_devices(
        py: Python<'_>,
        timeout_ms: u64,
    ) -> PyResult<Vec<PyWifiDiscoveredDevice>> {
        let devices = run_native(py, move || {
            get_or_init_runtime().block_on(
                enody::wifi::WifiConnection::discover_token_generation_devices(
                    Duration::from_millis(timeout_ms),
                ),
            )
        })
        .map_err(enody_err)?;
        Ok(devices
            .into_iter()
            .map(|inner| PyWifiDiscoveredDevice { inner })
            .collect())
    }

    #[staticmethod]
    fn runtime_from_endpoint(token: &PyToken, endpoint: String) -> PyResult<PyRuntime> {
        enody::wifi::WifiConnection::runtime_from_endpoint(&token.inner, endpoint)
            .map(PyRuntime::from_native)
            .map_err(enody_err)
    }

    #[staticmethod]
    fn runtime_from_discovered_device(
        token: &PyToken,
        device: &PyWifiDiscoveredDevice,
    ) -> PyResult<PyRuntime> {
        enody::wifi::WifiConnection::runtime_from_discovered_device(&token.inner, &device.inner)
            .map(PyRuntime::from_native)
            .map_err(enody_err)
    }

    #[staticmethod]
    #[pyo3(signature = (endpoint, on_approval = None))]
    fn generate_token_from_endpoint(
        py: Python<'_>,
        endpoint: String,
        on_approval: Option<Py<PyAny>>,
    ) -> PyResult<PyToken> {
        let rt = get_or_init_runtime();
        run_with_approval_callback(py, on_approval, move |callback| {
            rt.block_on(
                enody::wifi::WifiConnection::generate_token_from_endpoint_with_approval(
                    endpoint, callback,
                ),
            )
        })
    }

    #[staticmethod]
    #[pyo3(signature = (device, on_approval = None))]
    fn generate_token_from_discovered_device(
        py: Python<'_>,
        device: &PyWifiDiscoveredDevice,
        on_approval: Option<Py<PyAny>>,
    ) -> PyResult<PyToken> {
        let rt = get_or_init_runtime();
        let device = device.inner.clone();
        run_with_approval_callback(py, on_approval, move |callback| {
            rt.block_on(
                enody::wifi::WifiConnection::generate_token_from_discovered_device_with_approval(
                    &device, callback,
                ),
            )
        })
    }
}

// ---------------------------------------------------------------------------
// WifiEnvironment
// ---------------------------------------------------------------------------

#[pyclass(name = "WifiEnvironment", unsendable)]
pub struct PyWifiEnvironment {
    inner: EnvironmentWorker<enody::wifi::WifiEnvironment>,
}

#[pymethods]
impl PyWifiEnvironment {
    #[new]
    fn new(
        py: Python<'_>,
        tokens: Vec<PyRef<'_, PyToken>>,
        timeout_ms: u64,
        excluded_host_ids: Vec<String>,
    ) -> PyResult<Self> {
        let tokens = tokens
            .into_iter()
            .map(|token| token.inner.clone())
            .collect::<Vec<_>>();
        let excluded_host_ids = excluded_host_ids
            .iter()
            .map(|host_id| parse_identifier(host_id))
            .collect::<PyResult<Vec<_>>>()?;
        let inner = EnvironmentWorker::new(py, move || {
            get_or_init_runtime().block_on(
                enody::wifi::WifiEnvironment::with_timeout_and_excluded_host_ids(
                    tokens,
                    Duration::from_millis(timeout_ms),
                    excluded_host_ids,
                ),
            )
        })?;
        Ok(Self { inner })
    }

    fn runtimes(&self, py: Python<'_>) -> PyResult<Vec<PyRuntime>> {
        use enody::environment::Environment;
        let runtimes = self.inner.call(py, |inner| inner.runtimes())?;
        Ok(runtimes.into_iter().map(PyRuntime::from_native).collect())
    }

    fn start_discovery(&mut self, py: Python<'_>) -> PyResult<()> {
        use enody::environment::DiscoveryEnvironment;
        self.inner
            .call(py, |inner| {
                get_or_init_runtime().block_on(inner.start_discovery())
            })?
            .map_err(enody_err)
    }

    fn stop_discovery(&mut self, py: Python<'_>) -> PyResult<()> {
        use enody::environment::DiscoveryEnvironment;
        self.inner
            .call(py, |inner| {
                get_or_init_runtime().block_on(inner.stop_discovery())
            })?
            .map_err(enody_err)
    }

    fn next_runtime_event(&self, py: Python<'_>) -> PyResult<PyEnvironmentRuntimeEvent> {
        use enody::environment::DiscoveryEnvironment;
        let event = self
            .inner
            .call(py, |inner| {
                get_or_init_runtime().block_on(inner.next_runtime_event())
            })?
            .map_err(enody_err)?;
        Ok(environment_runtime_event(event))
    }

    fn exclude_host_id(&self, py: Python<'_>, host_id: String) -> PyResult<()> {
        let host_id = parse_identifier(&host_id)?;
        self.inner.call(py, move |inner| {
            get_or_init_runtime().block_on(inner.exclude_host_id(host_id))
        })
    }

    fn remove_excluded_host_id(&self, py: Python<'_>, host_id: String) -> PyResult<()> {
        let host_id = parse_identifier(&host_id)?;
        self.inner
            .call(py, move |inner| inner.remove_excluded_host_id(host_id))
    }
}

// ---------------------------------------------------------------------------
// UpdateTarget (wraps EP01UpdateTarget)
// ---------------------------------------------------------------------------

#[pyclass(name = "UpdateTarget", unsendable)]
pub struct PyUpdateTarget {
    inner: enody::update::EP01UpdateTarget,
}

#[pymethods]
impl PyUpdateTarget {
    #[staticmethod]
    fn discover() -> PyResult<Vec<PyUpdateTarget>> {
        let rt = get_or_init_runtime();
        let targets = rt.block_on(enody::update::EP01UpdateTarget::attached());
        Ok(targets
            .into_iter()
            .map(|t| PyUpdateTarget { inner: t })
            .collect())
    }

    fn identifier(&self) -> String {
        self.inner.info().identifier.to_string()
    }

    fn version(&self) -> String {
        self.inner.info().version.to_string()
    }

    fn mac_address(&self) -> Option<String> {
        self.inner.mac_address().map(|s| s.to_string())
    }

    fn available_firmware(&self) -> PyResult<Vec<String>> {
        let rt = get_or_init_runtime();
        let versions = rt
            .block_on(self.inner.available_firmware())
            .map_err(enody_err)?;
        Ok(versions.iter().map(|fv| fv.version().to_string()).collect())
    }

    fn update_available(&self) -> PyResult<bool> {
        let rt = get_or_init_runtime();
        rt.block_on(self.inner.update_available())
            .map_err(enody_err)
    }

    fn update_device(&self, version: String) -> PyResult<()> {
        let rt = get_or_init_runtime();
        rt.block_on(self.inner.update_device(&version))
            .map_err(enody_err)
    }

    fn flash_firmware_image(&self, firmware_path: String) -> PyResult<()> {
        self.inner
            .flash_firmware_image(std::path::Path::new(&firmware_path))
            .map_err(enody_err)
    }
}

// ---------------------------------------------------------------------------
// Module
// ---------------------------------------------------------------------------

#[pyfunction]
fn init_logging() {
    static ONCE: std::sync::Once = std::sync::Once::new();
    ONCE.call_once(|| {
        env_logger::Builder::from_default_env()
            .format_timestamp_millis()
            .init();
    });
}

#[pymodule]
fn _enody_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySpectralSample>()?;
    m.add_class::<PySpectralData>()?;
    m.add_class::<PyChromaticity>()?;
    m.add_class::<PyFlux>()?;
    m.add_class::<PyConfiguration>()?;
    m.add_class::<PyTransition>()?;
    m.add_class::<PyToken>()?;
    m.add_class::<PyTokenStore>()?;
    m.add_class::<PyWifiNetwork>()?;
    m.add_class::<PyEnvironmentRuntimeEvent>()?;
    m.add_class::<PyUsbEnvironment>()?;
    m.add_class::<PyRuntime>()?;
    m.add_class::<PyHost>()?;
    m.add_class::<PyFixture>()?;
    m.add_class::<PySource>()?;
    m.add_class::<PyEmitter>()?;
    m.add_class::<PyWifiDiscoveredDevice>()?;
    m.add_class::<PyWifiConnection>()?;
    m.add_class::<PyWifiEnvironment>()?;
    m.add_class::<PyUpdateTarget>()?;
    m.add_function(pyo3::wrap_pyfunction!(init_logging, m)?)?;
    Ok(())
}
