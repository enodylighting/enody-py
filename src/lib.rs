use pyo3::prelude::*;

fn get_or_init_runtime() -> &'static tokio::runtime::Runtime {
    static RT: std::sync::OnceLock<tokio::runtime::Runtime> = std::sync::OnceLock::new();
    RT.get_or_init(|| tokio::runtime::Runtime::new().unwrap())
}

fn enody_err(e: enody::Error) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{:?}", e))
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
        self.inner.samples().iter().map(|s| s.wavelength()).collect()
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
// UsbEnvironment
// ---------------------------------------------------------------------------

#[pyclass(name = "UsbEnvironment", unsendable)]
pub struct PyUsbEnvironment {
    inner: enody::usb::UsbEnvironment,
}

#[pymethods]
impl PyUsbEnvironment {
    #[new]
    fn new() -> PyResult<Self> {
        let rt = get_or_init_runtime();
        let env = rt.block_on(async {
            tokio::task::block_in_place(|| enody::usb::UsbEnvironment::new())
        });
        Ok(Self { inner: env })
    }

    fn runtimes(&self) -> Vec<PyRuntime> {
        use enody::environment::Environment;
        self.inner
            .runtimes()
            .into_iter()
            .map(|r| PyRuntime { inner: r })
            .collect()
    }
}

// ---------------------------------------------------------------------------
// Runtime (wraps RemoteRuntime)
// ---------------------------------------------------------------------------

#[pyclass(name = "Runtime")]
#[derive(Clone)]
pub struct PyRuntime {
    inner: enody::runtime::remote::RemoteRuntime,
}

#[pymethods]
impl PyRuntime {
    fn host(&self) -> PyResult<PyHost> {
        let rt = get_or_init_runtime();
        let host = rt
            .block_on(self.inner.host())
            .map_err(enody_err)?;
        Ok(PyHost { inner: host })
    }

    fn connect(&self) -> PyResult<()> {
        let rt = get_or_init_runtime();
        rt.block_on(self.inner.connect()).map_err(enody_err)
    }

    fn disconnect(&self) -> PyResult<()> {
        let rt = get_or_init_runtime();
        rt.block_on(self.inner.disconnect()).map_err(enody_err)
    }

    fn is_connected(&self) -> bool {
        self.inner.is_connected()
    }

    fn enable_logging(&self) {
        self.inner.enable_logging();
    }
}

// ---------------------------------------------------------------------------
// Host (wraps RemoteHost)
// ---------------------------------------------------------------------------

#[pyclass(name = "Host")]
#[derive(Clone)]
pub struct PyHost {
    inner: enody::host::remote::RemoteHost,
}

#[pymethods]
impl PyHost {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn version(&self) -> String {
        self.inner.version().to_string()
    }

    fn fixtures(&self) -> PyResult<Vec<PyFixture>> {
        let rt = get_or_init_runtime();
        let fixtures = rt
            .block_on(self.inner.fixtures())
            .map_err(enody_err)?;
        Ok(fixtures
            .into_iter()
            .map(|f| PyFixture { inner: f })
            .collect())
    }
}

// ---------------------------------------------------------------------------
// Fixture (wraps RemoteFixture)
// ---------------------------------------------------------------------------

#[pyclass(name = "Fixture")]
#[derive(Clone)]
pub struct PyFixture {
    inner: enody::fixture::remote::RemoteFixture,
}

#[pymethods]
impl PyFixture {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn sources(&self) -> PyResult<Vec<PySource>> {
        let rt = get_or_init_runtime();
        let sources = rt
            .block_on(self.inner.sources())
            .map_err(enody_err)?;
        Ok(sources
            .into_iter()
            .map(|s| PySource { inner: s })
            .collect())
    }

    fn display(&self, config: &PyConfiguration, flux: &PyFlux) -> PyResult<(PyConfiguration, PyFlux)> {
        let rt = get_or_init_runtime();
        let (cfg, f) = rt
            .block_on(self.inner.display(config.inner.clone(), flux.inner.clone()))
            .map_err(enody_err)?;
        Ok((
            PyConfiguration { inner: cfg },
            PyFlux { inner: f },
        ))
    }
}

// ---------------------------------------------------------------------------
// Source (wraps RemoteSource)
// ---------------------------------------------------------------------------

#[pyclass(name = "Source")]
pub struct PySource {
    inner: enody::source::remote::RemoteSource,
}

#[pymethods]
impl PySource {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn emitters(&self) -> PyResult<Vec<PyEmitter>> {
        let rt = get_or_init_runtime();
        let emitters = rt
            .block_on(self.inner.emitters())
            .map_err(enody_err)?;
        Ok(emitters
            .into_iter()
            .map(|e| PyEmitter { inner: e })
            .collect())
    }

    fn display(&self, config: &PyConfiguration, flux: &PyFlux) -> PyResult<(PyConfiguration, PyFlux)> {
        let rt = get_or_init_runtime();
        let (cfg, f) = rt
            .block_on(self.inner.display(config.inner.clone(), flux.inner.clone()))
            .map_err(enody_err)?;
        Ok((
            PyConfiguration { inner: cfg },
            PyFlux { inner: f },
        ))
    }
}

// ---------------------------------------------------------------------------
// Emitter (wraps RemoteEmitter)
// ---------------------------------------------------------------------------

#[pyclass(name = "Emitter")]
pub struct PyEmitter {
    inner: enody::emitter::remote::RemoteEmitter,
}

#[pymethods]
impl PyEmitter {
    fn identifier(&self) -> String {
        self.inner.identifier().to_string()
    }

    fn spectral_data(&self) -> PyResult<PySpectralData> {
        let rt = get_or_init_runtime();
        let sd = rt
            .block_on(self.inner.spectral_data())
            .map_err(enody_err)?;
        Ok(PySpectralData { inner: sd })
    }

    fn set_flux(&self, flux: &PyFlux) -> PyResult<PyFlux> {
        let rt = get_or_init_runtime();
        let result = rt
            .block_on(self.inner.set_flux(flux.inner.clone()))
            .map_err(enody_err)?;
        Ok(PyFlux { inner: result })
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
        rt.block_on(self.inner.update_available()).map_err(enody_err)
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
    m.add_class::<PyUsbEnvironment>()?;
    m.add_class::<PyRuntime>()?;
    m.add_class::<PyHost>()?;
    m.add_class::<PyFixture>()?;
    m.add_class::<PySource>()?;
    m.add_class::<PyEmitter>()?;
    m.add_class::<PyUpdateTarget>()?;
    m.add_function(pyo3::wrap_pyfunction!(init_logging, m)?)?;
    Ok(())
}
