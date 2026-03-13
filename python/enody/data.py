import json
import os
from . import interface

_data_cache = {}

def _json_data(relative_path):
    if relative_path in _data_cache:
        return _data_cache[relative_path]

    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.abspath(os.path.join(current_dir, relative_path))
    with open(data_path, 'r') as f:
        data = json.load(f)
        _data_cache[relative_path] = data
        return data

def sample_emitter():
    emitter_data = _json_data("../../data/emitter.json")
    if emitter_data is not None:
        return interface.Emitter.from_json(emitter_data)

def sample_source():
    source_data = _json_data("../../data/source.json")
    if source_data is not None:
        return interface.Source.from_json(source_data)

def sample_fixture():
    fixture_data = _json_data("../../data/fixture.json")
    if fixture_data is not None:
        return interface.Fixture.from_json(fixture_data)

def melanopic_action():
    response_data =  _json_data("../../data/response.json")
    return response_data["Melanopic response"]

def rhodopic_action():
    response_data =  _json_data("../../data/response.json")
    return response_data["Rhodopic response"]

def s_cone_action():
    response_data = _json_data("../../data/response.json")
    return response_data["S-cone-opic response"]

def m_cone_action():
    response_data = _json_data("../../data/response.json")
    return response_data["M-cone-opic response"]

def l_cone_action():
    response_data = _json_data("../../data/response.json")
    return response_data["L-cone-opic response"]

def cie_x_action():
    response_data = _json_data("../../data/response.json")
    return response_data["CIE-X response"]

def cie_y_action():
    response_data = _json_data("../../data/response.json")
    return response_data["CIE-Y response"]

def cie_z_action():
    response_data = _json_data("../../data/response.json")
    return response_data["CIE-Z response"]
