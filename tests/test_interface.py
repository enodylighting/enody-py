import os
import json
import pytest
import colour
from enody.interface import Emitter, Source, Fixture
from enody.colorimetry import SpectralData

TEST_DATA_FIXTURE_REL_PATH = "../python/enody/data/fixture.json"
TEST_DATA_FIXTURE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), TEST_DATA_FIXTURE_REL_PATH))

def test_emitter_deserialization():
    # Load test data
    with open(TEST_DATA_FIXTURE_PATH, 'r') as f:
        fixture_data = json.load(f)

    # Create Emitter object from JSON
    emitter_data = fixture_data["sources"][0]["emitters"][0]
    emitter = Emitter.from_json(emitter_data)

    # Verify basic properties
    assert emitter.identifier() == emitter_data["identifier"]
    assert isinstance(emitter.spectral_data(), SpectralData)

    # Check some values in the spectral distribution
    csd = emitter.spectral_data()
    measurements = csd.measurements()
    json_samples = emitter_data["spectral_data"]

    for i, sample in enumerate(json_samples):
        assert measurements[i] == pytest.approx(float(sample["measurement"]))

def test_source_deserialization():
    # Load test data
    with open(TEST_DATA_FIXTURE_PATH, 'r') as f:
        fixture_data = json.load(f)

    # Create Source object from JSON
    source_data = fixture_data["sources"][0]
    source = Source.from_json(source_data)

    # Verify basic properties
    assert source.identifier() == source_data["identifier"]
    assert len(source.emitters()) == len(source_data["emitters"])

    # Verify each emitter
    for i, emitter in enumerate(source.emitters()):
        assert emitter.identifier() == source_data["emitters"][i]["identifier"]
        assert isinstance(emitter.spectral_data(), SpectralData)

def test_fixture_deserialization():
    # Load test data
    with open(TEST_DATA_FIXTURE_PATH, 'r') as f:
        fixture_data = json.load(f)

    # Create Fixture object from JSON
    fixture = Fixture.from_json(fixture_data)

    # Verify basic properties
    assert fixture.identifier() == fixture_data["identifier"]
    assert len(fixture.sources()) == len(fixture_data["sources"])

    # Verify each source
    for i, source in enumerate(fixture.sources()):
        assert source.identifier() == fixture_data["sources"][i]["identifier"]
        assert len(source.emitters()) == len(fixture_data["sources"][i]["emitters"])
