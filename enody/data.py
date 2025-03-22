import json
import os
from . import interface

def _json_data(relative_path):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.abspath(os.path.join(current_dir, relative_path))
    with open(data_path, 'r') as f:
        return json.load(f)

def sample_emitter():
    emitter_data = _json_data("../data/emitter.json")
    if emitter_data is not None:
        return interface.Emitter.from_json(emitter_data)

def sample_source():
    source_data = _json_data("../data/source.json")
    if source_data is not None:
        return interface.Source.from_json(source_data)

def sample_fixture():
    fixture_data = _json_data("../data/fixture.json")
    if fixture_data is not None:
        return interface.Fixture.from_json(fixture_data)