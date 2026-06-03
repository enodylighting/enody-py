import json

import pytest

import enody


def test_token_round_trip_redacts_secret():
    token = enody.Token(
        "00000000-0000-0000-0000-000000000001",
        "pairing-key",
        list(range(32)),
    )

    data = token.to_dict()
    restored = enody.Token.from_dict(data)

    assert restored.host_id() == token.host_id()
    assert restored.key_id() == token.key_id()
    assert restored.data() == token.data()
    assert "0, 1, 2" not in repr(restored)
    assert "<redacted>" in repr(restored)


def test_token_store_save_load_from_path(tmp_path):
    token = enody.Token(
        "00000000-0000-0000-0000-000000000002",
        "store-key",
        [31] * 32,
    )
    path = tmp_path / "tokens.json"

    store = enody.TokenStore()
    store.upsert(token)
    store.save_to_path(str(path))

    raw = json.loads(path.read_text())
    assert raw["tokens"][0]["host_id"] == token.host_id()
    assert raw["tokens"][0]["key_id"] == token.key_id()

    loaded = enody.TokenStore.load_from_path(str(path))
    loaded_tokens = loaded.tokens()
    assert len(loaded_tokens) == 1
    assert loaded_tokens[0].to_dict() == token.to_dict()


def test_token_store_upsert_replaces_matching_host():
    host_id = "00000000-0000-0000-0000-000000000003"
    first = enody.Token(host_id, "first", [1] * 32)
    second = enody.Token(host_id, "second", [2] * 32)

    store = enody.TokenStore([first])
    store.upsert(second)

    tokens = store.tokens()
    assert len(tokens) == 1
    assert tokens[0].key_id() == "second"
    assert tokens[0].data() == [2] * 32


def test_empty_wifi_environment_does_not_discover():
    env = enody.WifiEnvironment(tokens=[])
    assert env.runtimes() == []


def test_discover_runtimes_can_skip_all_transports():
    discovered = enody.discover_runtimes(include_usb=False, include_wifi=False)
    assert discovered.runtimes() == []
    assert discovered.usb_environment() is None
    assert discovered.wifi_environment() is None


def test_generate_wifi_token_requires_unambiguous_target(monkeypatch):
    monkeypatch.setattr(
        enody.WifiConnection,
        "discover_token_generation_devices",
        staticmethod(lambda timeout_ms=800: []),
    )

    with pytest.raises(RuntimeError, match="no EP01 devices"):
        enody.generate_wifi_token(verify=False)
