from tinygrad.tensor import Tensor

from enody.optimize import melanopic_response, cie_1931_chromaticity
from enody.data import sample_source

def test_melanopic_response():
    source = sample_source()
    values = []

    for emitter in source.emitters():
        csd = emitter.characteristic_spectral_distribution()
        values.append(csd.values())

    values_tensor = Tensor(values)
    print(melanopic_response(values_tensor).numpy())

def test_cie_1931_chromaticity():
    source = sample_source()
    values = []

    for emitter in source.emitters():
        csd = emitter.characteristic_spectral_distribution()
        values.append(csd.values())

    values_tensor = Tensor(values)
    xy = cie_1931_chromaticity(values_tensor)
    assert xy.shape[0] == 2  # x and y components
