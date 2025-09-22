import colour

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

class Chromaticity:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x
    
    def y(self):
        return self._y

class Measurement:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

class SpectralSample:
    def __init__(self, wavelength, value):
        self._wavelength = wavelength
        self._value = value

    def wavelength(self):
        return self._wavelength
    
    def value(self):
        return self._value

class SpectralData:
    def __init__(self, samples):
        self._samples = samples

    # @classmethod
    # def mix(cls, components, weights):
    #     components = [c._spectral_data_t for c in components]
    #     mix_spectral_data_t = lib.spectral_data_mix(components, weights, len(components))
    #     return SpectralData.from_spectral_data_t(mix_spectral_data_t)

    def sample_count(self):
        return len(self._samples)

    def samples(self):
        return self._samples

    def wavelengths(self):
        wavelengths = []
        for sample in self._samples:
            wavelengths.append(sample.wavelength())
        return wavelengths

    def values(self):
        values = []
        for sample in self._samples:
            values.append(sample.value())
        return values

    def spectral_distribution(self):
        data = {}
        for sample in self._samples:
            data[round(sample._wavelength)] = sample._value
        dist = colour.SpectralDistribution(data)
        return dist

    def luminance(self):
        spd = self.spectral_distribution()
        luminance = colour.sd_to_XYZ(spd)[1]
        return luminance
