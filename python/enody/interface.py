import colour
from tinygrad.tensor import Tensor, dtypes

from . import colorimetry, _enody_rs

class UsbEnvironment:
    def __init__(self): 
        self._environment_rs = _enody_rs.UsbEnvironment()

    def runtimes(self):
        return [Runtime.from_rs(r) for r in self._environment_rs.runtimes()]

class Runtime:
    @classmethod
    def from_rs(cls, runtime_rs):
        """Create a Runtime from a native RemoteRuntime (device-backed)."""
        remote_host = runtime_rs.host()
        host = Host.from_rs(remote_host)
        return cls(host, runtime_rs)

    def __init__(self, host, runtime_rs):
        self._host = host
        self._runtime_rs = runtime_rs

    def host(self):
        return self._host

    def is_connected(self):
        return self._runtime_rs.is_connected()

    def enable_logging(self):
        self._runtime_rs.enable_logging()

class Host:
    @classmethod
    def from_rs(cls, host_rs):
        """Create a Host from a native RemoteHost (device-backed)."""
        identifier = host_rs.identifier()
        version = host_rs.version()
        remote_fixtures = host_rs.fixtures()
        fixtures = [Fixture.from_device(f) for f in remote_fixtures]
        return cls(identifier, version, fixtures, host_rs)

    def __init__(self, identifier, version, fixtures, host_rs):
        self._identifier = identifier
        self._version = version
        self._fixtures = fixtures
        self._host_rs = host_rs

    def identifier(self):
        return self._identifier

    def fixtures(self):
        return self._fixtures

    def version(self):
        return self._version

class Fixture:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]
        sources_data = json_data["sources"]

        # Create Source objects from JSON data
        sources = [Source.from_json(source_data) for source_data in sources_data]

        return cls(identifier, sources)

    @classmethod
    def from_device(cls, remote_fixture):
        """Create a Fixture from a native RemoteFixture (device-backed)."""
        identifier = remote_fixture.identifier()
        remote_sources = remote_fixture.sources()
        sources = [Source.from_device(s) for s in remote_sources]
        return cls(identifier, sources, remote_fixture=remote_fixture)

    def __init__(self, identifier, sources, remote_fixture=None):
        self._identifier = identifier
        self._sources = sources
        self._remote_fixture = remote_fixture

    def identifier(self):
        return self._identifier

    def sources(self):
        return self._sources

    def tensor(self):
        return Tensor.stack([s.tensor() for s in self._sources])

    def display(self, config, flux):
        """Send a display command to the device. Requires a device-backed fixture."""
        if self._remote_fixture is None:
            raise RuntimeError("display requires a device-backed fixture")
        return self._remote_fixture.display(config, flux)

class Source:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]

        emitters_data = json_data["emitters"]
        emitters = [Emitter.from_json(emitter_data) for emitter_data in emitters_data]

        return cls(identifier, emitters)

    @classmethod
    def from_device(cls, remote_source):
        """Create a Source from a native RemoteSource (device-backed)."""
        identifier = remote_source.identifier()
        remote_emitters = remote_source.emitters()
        emitters = [Emitter.from_device(e) for e in remote_emitters]
        return cls(identifier, emitters, remote_source=remote_source)

    def __init__(self, identifier, emitters, remote_source=None):
        self._identifier = identifier
        self._emitters = emitters
        self._remote_source = remote_source

    def identifier(self):
        return self._identifier

    def emitters(self):
        return self._emitters

    def _emitter_spectral_distributions(self):
        return [e.spectral_data().spectral_distribution() for e in self._emitters]

    def tensor(self):
        emitter_values = [e.spectral_data().values() for e in self._emitters]
        return Tensor(emitter_values, dtype=dtypes.float32)

    def plot_emitter_spectral_distributions(self):
        colour.plotting.plot_multi_sds(self._emitter_spectral_distributions())

    def plot_emitter_chromaticity_diagram(self):
        colour.plotting.plot_sds_in_chromaticity_diagram_CIE1931(self._emitter_spectral_distributions())

    def display(self, config, flux):
        """Send a display command to the device. Requires a device-backed source."""
        if self._remote_source is None:
            raise RuntimeError("display requires a device-backed source")
        return self._remote_source.display(config, flux)

class Emitter:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]

        sd_data = json_data["spectral_data"]
        wavelengths = sd_data["wavelengths"]
        values = sd_data["values"]
        samples = [colorimetry.SpectralSample(wavelengths[i], values[i]) for i in range(len(wavelengths))]
        spectral_data = colorimetry.SpectralData(samples)

        return cls(identifier, spectral_data)

    @classmethod
    def from_device(cls, remote_emitter):
        """Create an Emitter from a native RemoteEmitter (device-backed)."""
        identifier = remote_emitter.identifier()
        return cls(identifier, None, remote_emitter=remote_emitter)

    def __init__(self, identifier, spectral_data, remote_emitter=None):
        self._identifier = identifier
        self._spectral_data = spectral_data
        self._remote_emitter = remote_emitter

    def identifier(self):
        return self._identifier

    def spectral_data(self):
        if self._spectral_data is None and self._remote_emitter is not None:
            remote_sd = self._remote_emitter.spectral_data()
            self._spectral_data = colorimetry.SpectralData.from_rs(remote_sd)
        return self._spectral_data

    def tensor(self):
        return Tensor(self.spectral_data().values(), dtype=dtypes.float32)

    def set_flux(self, flux):
        """Set flux on the device. Requires a device-backed emitter."""
        if self._remote_emitter is None:
            raise RuntimeError("set_flux requires a device-backed emitter")
        return self._remote_emitter.set_flux(flux)

class UpdateTarget:
    @classmethod
    def discover(cls):
        """Discover attached EP01 devices for firmware updates."""
        return [cls(t) for t in _enody_rs.UpdateTarget.discover()]

    def __init__(self, target_rs):
        self._target_rs = target_rs

    def identifier(self):
        return self._target_rs.identifier()

    def version(self):
        return self._target_rs.version()

    def mac_address(self):
        return self._target_rs.mac_address()

    def available_firmware(self):
        return self._target_rs.available_firmware()

    def update_available(self):
        return self._target_rs.update_available()

    def update_device(self, version):
        return self._target_rs.update_device(version)