from tinygrad.tensor import Tensor

SSI_RESAMPLING_KERNEL = Tensor([0.5] + [1]*9 + [0.5]).reshape(1, 1, 1, 11) / 10.0
SSI_WEIGHTING_KERNEL = Tensor([4/15, 22/45, 32/45, 8/9, 44/45] + [1]*23 + [11/15, 3/15])
SSI_SMOOTHING_KERNEL = Tensor([[[0.22, 0.56, 0.22]]]).reshape(1, 1, 1, 3)

def ssi(test_distributions, refernce_distributions):
    test_shape = test_distributions.shape
    ref_shape = refernce_distributions.shape
    assert test_shape == ref_shape

    spectra_count = test_shape[0]
    sample_count = test_shape[1]
    assert sample_count == 301

    # Reshape the Tensors to ready them for convolution
    test_distributions = test_distributions.reshape(1, 1, spectra_count, sample_count)
    refernce_distributions = refernce_distributions.reshape(1, 1, spectra_count, sample_count)
    
    # Perform the convolution to reduce each spectra to 30 values
    test_resampled = test_distributions.conv2d(SSI_RESAMPLING_KERNEL, stride=(1, 10))
    reference_resampled = refernce_distributions.conv2d(SSI_RESAMPLING_KERNEL, stride=(1, 10))

    # Normalize each spectra to unity power
    test_normalized = test_resampled / test_resampled.sum(axis=3).reshape(1, 1, spectra_count, 1)
    reference_normalized = reference_resampled / reference_resampled.sum(axis=3).reshape(1, 1, spectra_count, 1)

    # Compute difference vector
    D = (test_normalized - reference_normalized) / (reference_normalized + 1/30)

    # Apply weighting
    weighted = D * SSI_WEIGHTING_KERNEL

    # Smooth the vector
    smoothed = weighted.conv2d(SSI_SMOOTHING_KERNEL, padding=(0, 1))

    # Calculate the magnitude of the vector
    vector_magnitude = (smoothed * smoothed).sum(axis=3).sqrt()

    # Calculate per spectra SSI
    SSI = 100 - 32 * vector_magnitude
    return SSI
