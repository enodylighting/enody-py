from tinygrad.tensor import Tensor

from enody.optimize import melanopic_response
from enody.data import sample_source

def test_melanopic_response():
    source = sample_source()
    values = []

    for emitter in source.emitters():
        csd = emitter._characteristic_spectral_distribution
        values.append(csd.values())

    values_tensor = Tensor(values)
    print(melanopic_response(values_tensor).numpy())