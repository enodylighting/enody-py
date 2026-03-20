import json
import os
from . import interface

_data_cache = {}
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def _json_data(filename):
    if filename in _data_cache:
        return _data_cache[filename]

    data_path = os.path.join(_DATA_DIR, filename)
    with open(data_path, 'r') as f:
        data = json.load(f)
        _data_cache[filename] = data
        return data

def sample_fixture():
    fixture_data = _json_data("fixture.json")
    if fixture_data is not None:
        return interface.Fixture.from_json(fixture_data)

def sample_source():
    fixture = sample_fixture()
    if fixture is not None:
        return fixture.sources()[0]

def sample_emitter():
    source = sample_source()
    if source is not None:
        return source.emitters()[0]

def _response_measurements(name):
    response_data = _json_data("response.json")
    return [s["measurement"] for s in response_data[name]]

def melanopic_action():
    return _response_measurements("Melanopic response")

def rhodopic_action():
    return _response_measurements("Rhodopic response")

def s_cone_action():
    return _response_measurements("S-cone-opic response")

def m_cone_action():
    return _response_measurements("M-cone-opic response")

def l_cone_action():
    return _response_measurements("L-cone-opic response")

def cie_x_action():
    return _response_measurements("CIE-X response")

def cie_y_action():
    return _response_measurements("CIE-Y response")

def cie_z_action():
    return _response_measurements("CIE-Z response")
