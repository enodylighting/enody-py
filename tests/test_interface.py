import os
import json
import pytest
import colour
from enody.interface import Emitter, Source, Fixture
from enody.colorimetry import SpectralData

TEST_DATA_EMITTER_REL_PATH = "../data/emitter.json"
TEST_DATA_SOURCE_REL_PATH = "../data/source.json"
TEST_DATA_FIXTURE_REL_PATH = "../data/fixture.json"

TEST_DATA_EMITTER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), TEST_DATA_EMITTER_REL_PATH))
TEST_DATA_SOURCE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), TEST_DATA_SOURCE_REL_PATH))
TEST_DATA_FIXTURE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), TEST_DATA_FIXTURE_REL_PATH))

def test_emitter_deserialization():
    # Load test data
    with open(TEST_DATA_EMITTER_PATH, 'r') as f:
        emitter_data = json.load(f)
    
    # Create Emitter object from JSON
    emitter = Emitter.from_json(emitter_data)
    
    # Verify basic properties
    assert emitter._identifier == emitter_data["identifier"]
    assert isinstance(emitter._characteristic_spectral_distribution, SpectralData)
    
    # Check some values in the spectral distribution
    csd = emitter._characteristic_spectral_distribution
    values = csd.values()
    json_values = emitter_data["characteristic_spectral_distribution"]["values"]
    
    for i in range(len(json_values)):
        assert values[i] == pytest.approx(float(json_values[i]))

def test_source_deserialization():
    # Load test data
    with open(TEST_DATA_SOURCE_PATH, 'r') as f:
        source_data = json.load(f)
    
    # Create Source object from JSON
    source = Source.from_json(source_data)
    
    # Verify basic properties
    assert source._identifier == source_data["identifier"]
    assert len(source._emitters) == len(source_data["emitters"])
    
    # Verify each emitter
    for i, emitter in enumerate(source._emitters):
        assert emitter._identifier == source_data["emitters"][i]["identifier"]
        assert isinstance(emitter._characteristic_spectral_distribution, SpectralData)

def test_fixture_deserialization():
    # Load test data
    with open(TEST_DATA_FIXTURE_PATH, 'r') as f:
        fixture_data = json.load(f)
    
    # Create Fixture object from JSON
    fixture = Fixture.from_json(fixture_data)
    
    # Verify basic properties
    assert fixture._identifier == fixture_data["identifier"]
    assert len(fixture._sources) == len(fixture_data["sources"])
    
    # Verify each source
    for i, source in enumerate(fixture._sources):
        assert source._identifier == fixture_data["sources"][i]["identifier"]
        assert len(source._emitters) == len(fixture_data["sources"][i]["emitters"])

