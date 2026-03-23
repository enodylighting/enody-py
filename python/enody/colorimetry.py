from colour import SpectralDistribution

from ._enody_rs import Chromaticity, SpectralSample

class XYZ:
    def __init__(self, x, y, z):
        self._x = x
        self._y = y
        self._z = z

    def x(self):
        return self._x

    def y(self):
        return self._y

    def z(self):
        return self._z

class SpectralData:
    @classmethod
    def from_rs(cls, spectral_data_rs, name=None):
        """Create an Emitter from a native RemoteEmitter (device-backed)."""
        wavelengths = spectral_data_rs.wavelengths()
        measurements = spectral_data_rs.measurements()
        samples = [SpectralSample(w, v) for (w, v) in zip(wavelengths, measurements)]
        return cls(samples, name)

    def __init__(self, samples, name=None):
        self._samples = samples
        self._name = name

    def name(self):
        return self._name

    def samples(self):
        return self._samples

    def sample_count(self):
        return len(self._samples)

    def wavelengths(self):
        return [sample.wavelength for sample in self._samples]

    def measurements(self):
        return [sample.measurement for sample in self._samples]

    def spectral_distribution(self):
        data = {}
        for sample in self._samples:
            data[round(sample.wavelength)] = sample.measurement
        dist = SpectralDistribution(data, name=self._name)
        return dist

    def tensor(self):
        from tinygrad.tensor import Tensor, dtypes
        return Tensor(self.measurements(), dtype=dtypes.float32)
