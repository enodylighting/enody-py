import colour
from tinygrad.tensor import Tensor, dtypes

from . import colorimetry


class Emitter:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]

        csd_data = json_data["characteristic_spectral_distribution"]
        wavelengths = csd_data["wavelengths"]
        values = csd_data["values"]
        samples = [colorimetry.SpectralSample(wavelengths[i], values[i]) for i in range(len(wavelengths))]
        characteristic_spectral_distribution = colorimetry.SpectralData(samples)

        return cls(identifier, characteristic_spectral_distribution)

    @classmethod
    def from_device(cls, remote_emitter):
        """Create an Emitter from a native RemoteEmitter (device-backed)."""
        identifier = remote_emitter.identifier()
        sd = remote_emitter.spectral_data()
        return cls(identifier, sd, remote_emitter=remote_emitter)

    def __init__(self, identifier, characteristic_spectral_distribution, remote_emitter=None):
        self._identifier = identifier
        self._characteristic_spectral_distribution = characteristic_spectral_distribution
        self._remote_emitter = remote_emitter

    def identifier(self):
        return self._identifier

    def characteristic_spectral_distribution(self):
        return self._characteristic_spectral_distribution

    def tensor(self):
        return Tensor(self._characteristic_spectral_distribution.values(), dtype=dtypes.float32)

    def set_flux(self, flux):
        """Set flux on the device. Requires a device-backed emitter."""
        if self._remote_emitter is None:
            raise RuntimeError("set_flux requires a device-backed emitter")
        return self._remote_emitter.set_flux(flux)


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
        return [e.characteristic_spectral_distribution().spectral_distribution() for e in self._emitters]

    def tensor(self):
        emitter_values = [e.characteristic_spectral_distribution().values() for e in self._emitters]
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
