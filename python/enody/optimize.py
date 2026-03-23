from . import data

_kernels = {}

def _ssi_kernels():
    if 'resampling' not in _kernels:
        from tinygrad.tensor import Tensor
        _kernels['resampling'] = Tensor([0.5] + [1]*9 + [0.5]).reshape(1, 1, 1, 11) / 10.0
        _kernels['weighting'] = Tensor([4/15, 22/45, 32/45, 8/9, 44/45] + [1]*23 + [11/15, 3/15])
        _kernels['smoothing'] = Tensor([[[0.22, 0.56, 0.22]]]).reshape(1, 1, 1, 3)
    return _kernels['resampling'], _kernels['weighting'], _kernels['smoothing']

def _response_kernel(name, data_fn):
    if name not in _kernels:
        from tinygrad.tensor import Tensor
        _kernels[name] = Tensor(data_fn())
    return _kernels[name]

def ssi(test_distributions, refernce_distributions):
    test_shape = test_distributions.shape
    ref_shape = refernce_distributions.shape
    assert test_shape == ref_shape

    spectra_count = test_shape[0]
    sample_count = test_shape[1]
    assert sample_count == 301

    resampling, weighting, smoothing = _ssi_kernels()

    # Reshape the Tensors to ready them for convolution
    test_distributions = test_distributions.reshape(1, 1, spectra_count, sample_count)
    refernce_distributions = refernce_distributions.reshape(1, 1, spectra_count, sample_count)

    # Perform the convolution to reduce each spectra to 30 values
    test_resampled = test_distributions.conv2d(resampling, stride=(1, 10))
    reference_resampled = refernce_distributions.conv2d(resampling, stride=(1, 10))

    # Normalize each spectra to unity power
    test_normalized = test_resampled / test_resampled.sum(axis=3).reshape(1, 1, spectra_count, 1)
    reference_normalized = reference_resampled / reference_resampled.sum(axis=3).reshape(1, 1, spectra_count, 1)

    # Compute difference vector
    D = (test_normalized - reference_normalized) / (reference_normalized + 1/30)

    # Apply weighting
    weighted = D * weighting

    # Smooth the vector
    smoothed = weighted.conv2d(smoothing, padding=(0, 1))

    # Calculate the magnitude of the vector
    vector_magnitude = (smoothed * smoothed).sum(axis=3).sqrt()

    # Calculate per spectra SSI
    SSI = 100 - 32 * vector_magnitude
    return SSI

# Response kernels
def _photopic_response(test_distributions, response_kernel):
    """
    Base function for calculating photopic responses.

    Args:
        test_distributions: Input spectral distributions tensor
        response_kernel: Response function kernel tensor

    Returns:
        Response values for each spectrum
    """
    test_shape = test_distributions.shape

    spectra_count = test_shape[0]
    sample_count = test_shape[1]
    assert sample_count == 401

    # Reshape the Tensor to prepare for weighting
    test_distributions = test_distributions.reshape(1, 1, spectra_count, sample_count)

    # Weight the spectra by the response kernel
    weighted_spectra = test_distributions * response_kernel.reshape(1, 1, 1, sample_count)

    # Compute the sum for each spectrum
    response_sum = weighted_spectra.sum(axis=3)

    return response_sum

def melanopic_response(test_distributions):
    """Calculate melanopic response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('melanopic', data.melanopic_action))

def rhodopic_response(test_distributions):
    """Calculate rhodopic response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('rhodopic', data.rhodopic_action))

def s_cone_response(test_distributions):
    """Calculate S-cone response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('s_cone', data.s_cone_action))

def m_cone_response(test_distributions):
    """Calculate M-cone response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('m_cone', data.m_cone_action))

def l_cone_response(test_distributions):
    """Calculate L-cone response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('l_cone', data.l_cone_action))

def cie_x_response(test_distributions):
    """Calculate CIE-X response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('cie_x', data.cie_x_action))

def cie_y_response(test_distributions):
    """Calculate CIE-Y response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('cie_y', data.cie_y_action))

def cie_z_response(test_distributions):
    """Calculate CIE-Z response for given spectral distributions."""
    return _photopic_response(test_distributions, _response_kernel('cie_z', data.cie_z_action))

def cie_1931_chromaticity(test_distributions):
    from tinygrad.tensor import Tensor
    x_response = cie_x_response(test_distributions)
    y_response = cie_y_response(test_distributions)
    z_response = cie_z_response(test_distributions)
    response_sum = x_response + y_response + z_response
    chromaticity_x = x_response / response_sum
    chromaticity_y = y_response / response_sum
    return Tensor.stack([chromaticity_x, chromaticity_y])
