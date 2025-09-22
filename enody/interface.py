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

    def __init__(self, identifier, characteristic_spectral_distribution):
        self._identifier = identifier
        self._characteristic_spectral_distribution = characteristic_spectral_distribution
    
    def identifier(self):
        return self._identifier

    def characteristic_spectral_distribution(self):
        return self._characteristic_spectral_distribution
    
    def tensor(self):
        return Tensor(self._characteristic_spectral_distribution.values(), dtype=dtypes.float32)
    

class Source:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]

        emitters_data = json_data["emitters"]
        emitters = [Emitter.from_json(emitter_data) for emitter_data in emitters_data]
        
        return cls(identifier, emitters)
    
    def __init__(self, identifier, emitters):
        self._identifier = identifier
        self._emitters = emitters
    
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

class Fixture:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]
        sources_data = json_data["sources"]
        
        # Create Source objects from JSON data
        sources = [Source.from_json(source_data) for source_data in sources_data]
        
        return cls(identifier, sources)

    def __init__(self, identifier, sources):
        self._identifier = identifier
        self._sources = sources
    
    def identifier(self):
        return self._identifier

    def sources(self):
        return self._sources
