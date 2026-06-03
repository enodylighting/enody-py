from colour.plotting import plot_multi_sds, plot_sds_in_chromaticity_diagram_CIE1931
import matplotlib.pyplot as plt
import time

from . import colorimetry, _enody_rs

WIFI_TOKEN_VERIFY_ATTEMPTS = 8
WIFI_TOKEN_VERIFY_RETRY_MS = 500


def _coerce_token(token):
    if isinstance(token, Token):
        return token
    if isinstance(token, dict):
        return Token.from_dict(token)
    if isinstance(token, _enody_rs.Token):
        return Token.from_rs(token)
    raise TypeError("expected Token, token dict, or native token")


def _coerce_token_rs(token):
    return _coerce_token(token)._token_rs


def _coerce_discovered_device(device):
    if isinstance(device, WifiDiscoveredDevice):
        return device
    if isinstance(device, _enody_rs.WifiDiscoveredDevice):
        return WifiDiscoveredDevice.from_rs(device)
    raise TypeError("expected WifiDiscoveredDevice")


class Token:
    @classmethod
    def from_rs(cls, token_rs):
        token = cls.__new__(cls)
        token._token_rs = token_rs
        return token

    @classmethod
    def from_dict(cls, data):
        return cls(data["host_id"], data["key_id"], data["data"])

    def __init__(self, host_id, key_id, data):
        self._token_rs = _enody_rs.Token(host_id, key_id, list(data))

    def host_id(self):
        return self._token_rs.host_id()

    def key_id(self):
        return self._token_rs.key_id()

    def data(self):
        return list(self._token_rs.data())

    def to_dict(self):
        return {
            "host_id": self.host_id(),
            "key_id": self.key_id(),
            "data": self.data(),
        }

    def __repr__(self):
        return f"Token(host_id={self.host_id()!r}, key_id={self.key_id()!r}, data=<redacted>)"


class TokenStore:
    @classmethod
    def load(cls):
        return cls.from_rs(_enody_rs.TokenStore.load())

    @classmethod
    def load_from_path(cls, path):
        return cls.from_rs(_enody_rs.TokenStore.load_from_path(path))

    @classmethod
    def from_rs(cls, token_store_rs):
        store = cls.__new__(cls)
        store._token_store_rs = token_store_rs
        return store

    @staticmethod
    def path():
        return _enody_rs.TokenStore.path()

    @staticmethod
    def config_dir():
        return _enody_rs.TokenStore.config_dir()

    @staticmethod
    def save_token(token):
        return _enody_rs.TokenStore.save_token(_coerce_token_rs(token))

    def __init__(self, tokens=None):
        self._token_store_rs = _enody_rs.TokenStore()
        for token in tokens or []:
            self.upsert(token)

    def tokens(self):
        return [Token.from_rs(t) for t in self._token_store_rs.tokens()]

    def upsert(self, token):
        self._token_store_rs.upsert(_coerce_token_rs(token))

    def save(self):
        return self._token_store_rs.save()

    def save_to_path(self, path):
        return self._token_store_rs.save_to_path(path)


class WifiNetwork:
    @classmethod
    def from_rs(cls, network_rs):
        network = cls.__new__(cls)
        network._network_rs = network_rs
        return network

    def ssid(self):
        return self._network_rs.ssid()

    def bssid(self):
        return self._network_rs.bssid()

    def channel(self):
        return self._network_rs.channel()

    def rssi(self):
        return self._network_rs.rssi()

    def auth(self):
        return self._network_rs.auth()

    def to_dict(self):
        return {
            "ssid": self.ssid(),
            "bssid": self.bssid(),
            "channel": self.channel(),
            "rssi": self.rssi(),
            "auth": self.auth(),
        }

    def __repr__(self):
        return (
            "WifiNetwork("
            f"ssid={self.ssid()!r}, bssid={self.bssid()!r}, "
            f"channel={self.channel()!r}, rssi={self.rssi()!r}, auth={self.auth()!r})"
        )


class EnvironmentRuntimeEvent:
    @classmethod
    def from_rs(cls, event_rs):
        event = cls.__new__(cls)
        event._event_rs = event_rs
        return event

    def kind(self):
        return self._event_rs.kind()

    def runtime(self):
        return Runtime.from_rs(self._event_rs.runtime())

    def __repr__(self):
        return f"EnvironmentRuntimeEvent(kind={self.kind()!r})"


class UsbEnvironment:
    def __init__(self): 
        self._environment_rs = _enody_rs.UsbEnvironment()

    def runtimes(self):
        return [Runtime.from_rs(r) for r in self._environment_rs.runtimes()]

    def start_discovery(self):
        return self._environment_rs.start_discovery()

    def stop_discovery(self):
        return self._environment_rs.stop_discovery()

    def next_runtime_event(self):
        return EnvironmentRuntimeEvent.from_rs(self._environment_rs.next_runtime_event())


class WifiEnvironment:
    def __init__(self, tokens=None, timeout_ms=800, excluded_host_ids=None):
        if tokens is None:
            tokens = TokenStore.load().tokens()
        token_rs = [_coerce_token_rs(token) for token in tokens]
        self._environment_rs = _enody_rs.WifiEnvironment(
            token_rs,
            timeout_ms,
            excluded_host_ids or [],
        )

    def runtimes(self):
        return [Runtime.from_rs(r) for r in self._environment_rs.runtimes()]

    def start_discovery(self):
        return self._environment_rs.start_discovery()

    def stop_discovery(self):
        return self._environment_rs.stop_discovery()

    def next_runtime_event(self):
        return EnvironmentRuntimeEvent.from_rs(self._environment_rs.next_runtime_event())

    def exclude_host_id(self, host_id):
        return self._environment_rs.exclude_host_id(host_id)

    def remove_excluded_host_id(self, host_id):
        return self._environment_rs.remove_excluded_host_id(host_id)

class Runtime:
    @classmethod
    def from_rs(cls, runtime_rs):
        """Create a Runtime from a native RemoteRuntime (device-backed)."""
        return cls(runtime_rs=runtime_rs)

    def __init__(self, host=None, runtime_rs=None):
        self._host = host
        self._runtime_rs = runtime_rs

    def host(self):
        if self._host is None:
            self._host = Host.from_rs(self._runtime_rs.host())
        return self._host

    def is_connected(self):
        return self._runtime_rs.is_connected()

    def enable_logging(self):
        self._runtime_rs.enable_logging()

    def connect(self):
        return self._runtime_rs.connect()

    def disconnect(self):
        return self._runtime_rs.disconnect()

    def generate_token(self):
        return Token.from_rs(self._runtime_rs.generate_token())

class Host:
    @classmethod
    def from_rs(cls, host_rs):
        """Create a Host from a native RemoteHost (device-backed)."""
        identifier = host_rs.identifier()
        version = host_rs.version()
        return cls(identifier, version, None, host_rs)

    def __init__(self, identifier, version, fixtures, host_rs):
        self._identifier = identifier
        self._version = version
        self._fixtures = fixtures
        self._host_rs = host_rs

    def identifier(self):
        return self._identifier

    def fixtures(self):
        if self._fixtures is None:
            remote_fixtures = self._host_rs.fixtures()
            self._fixtures = [Fixture.from_device(f) for f in remote_fixtures]
        return self._fixtures

    def version(self):
        return self._version

    def wifi_scan(self):
        return [WifiNetwork.from_rs(n) for n in self._host_rs.wifi_scan()]

    def wifi_join(self, ssid, password=""):
        return self._host_rs.wifi_join(ssid, password)


class WifiDiscoveredDevice:
    @classmethod
    def from_rs(cls, device_rs):
        device = cls.__new__(cls)
        device._device_rs = device_rs
        return device

    def instance(self):
        return self._device_rs.instance()

    def host(self):
        return self._device_rs.host()

    def address(self):
        return self._device_rs.address()

    def model(self):
        return self._device_rs.model()

    def api_version(self):
        return self._device_rs.api_version()

    def host_id(self):
        return self._device_rs.host_id()

    def firmware_version(self):
        return self._device_rs.firmware_version()

    def http_port(self):
        return self._device_rs.http_port()

    def port(self):
        return self._device_rs.port()

    def protocol(self):
        return self._device_rs.protocol()

    def auth(self):
        return self._device_rs.auth()

    def endpoint(self):
        return self._device_rs.endpoint()

    def is_ep01(self):
        return self._device_rs.is_ep01()

    def is_token_generation_candidate(self):
        return self._device_rs.is_token_generation_candidate()

    def to_dict(self):
        return {
            "instance": self.instance(),
            "host": self.host(),
            "address": self.address(),
            "model": self.model(),
            "api_version": self.api_version(),
            "host_id": self.host_id(),
            "firmware_version": self.firmware_version(),
            "http_port": self.http_port(),
            "port": self.port(),
            "protocol": self.protocol(),
            "auth": self.auth(),
            "endpoint": self.endpoint(),
        }

    def __repr__(self):
        return (
            "WifiDiscoveredDevice("
            f"host_id={self.host_id()!r}, endpoint={self.endpoint()!r}, "
            f"firmware_version={self.firmware_version()!r})"
        )


class WifiConnection:
    @staticmethod
    def discover_token_generation_devices(timeout_ms=800):
        return [
            WifiDiscoveredDevice.from_rs(device)
            for device in _enody_rs.WifiConnection.discover_token_generation_devices(timeout_ms)
        ]

    @staticmethod
    def runtime_from_endpoint(token, endpoint):
        return Runtime.from_rs(
            _enody_rs.WifiConnection.runtime_from_endpoint(_coerce_token_rs(token), endpoint)
        )

    @staticmethod
    def runtime_from_discovered_device(token, device):
        device = _coerce_discovered_device(device)
        return Runtime.from_rs(
            _enody_rs.WifiConnection.runtime_from_discovered_device(
                _coerce_token_rs(token),
                device._device_rs,
            )
        )

    @staticmethod
    def generate_token_from_endpoint(endpoint, on_approval=None):
        return Token.from_rs(
            _enody_rs.WifiConnection.generate_token_from_endpoint(endpoint, on_approval)
        )

    @staticmethod
    def generate_token_from_discovered_device(device, on_approval=None):
        device = _coerce_discovered_device(device)
        return Token.from_rs(
            _enody_rs.WifiConnection.generate_token_from_discovered_device(
                device._device_rs,
                on_approval,
            )
        )


def verify_wifi_token_from_runtime(token, runtime):
    token = _coerce_token(token)
    runtime.connect()
    host_id = None
    error = None
    try:
        host_id = runtime.host().identifier()
    except Exception as exc:
        error = exc
    finally:
        try:
            runtime.disconnect()
        except Exception as disconnect_error:
            if error is None:
                error = disconnect_error

    if error is not None:
        raise error
    if host_id != token.host_id():
        raise RuntimeError(
            f"verified host {host_id} does not match token host {token.host_id()}"
        )
    return host_id


def verify_wifi_token_from_endpoint(
    token,
    endpoint,
    attempts=WIFI_TOKEN_VERIFY_ATTEMPTS,
    retry_ms=WIFI_TOKEN_VERIFY_RETRY_MS,
):
    last_error = None
    for attempt in range(attempts):
        runtime = WifiConnection.runtime_from_endpoint(token, endpoint)
        try:
            return verify_wifi_token_from_runtime(token, runtime)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(retry_ms / 1000.0)
    raise last_error


def verify_wifi_token_from_discovered_device(
    token,
    device,
    attempts=WIFI_TOKEN_VERIFY_ATTEMPTS,
    retry_ms=WIFI_TOKEN_VERIFY_RETRY_MS,
):
    device = _coerce_discovered_device(device)
    endpoint = device.endpoint()
    if endpoint is None:
        raise RuntimeError("discovered device has no WiFi endpoint")
    return verify_wifi_token_from_endpoint(token, endpoint, attempts, retry_ms)


def generate_wifi_token(
    device=None,
    endpoint=None,
    timeout_ms=800,
    on_approval=None,
    verify=True,
    verify_attempts=WIFI_TOKEN_VERIFY_ATTEMPTS,
    verify_retry_ms=WIFI_TOKEN_VERIFY_RETRY_MS,
    save=False,
    token_store_path=None,
):
    if device is not None and endpoint is not None:
        raise ValueError("pass either device or endpoint, not both")

    if device is None and endpoint is None:
        devices = WifiConnection.discover_token_generation_devices(timeout_ms)
        if not devices:
            raise RuntimeError("no EP01 devices found for WiFi token generation")
        if len(devices) > 1:
            raise RuntimeError("multiple EP01 devices found; pass a selected device")
        device = devices[0]

    if device is not None:
        device = _coerce_discovered_device(device)
        token = WifiConnection.generate_token_from_discovered_device(device, on_approval)
        if verify:
            verify_wifi_token_from_discovered_device(
                token,
                device,
                attempts=verify_attempts,
                retry_ms=verify_retry_ms,
            )
    else:
        token = WifiConnection.generate_token_from_endpoint(endpoint, on_approval)
        if verify:
            verify_wifi_token_from_endpoint(
                token,
                endpoint,
                attempts=verify_attempts,
                retry_ms=verify_retry_ms,
            )

    if save:
        if token_store_path is None:
            TokenStore.save_token(token)
        else:
            store = TokenStore.load_from_path(token_store_path)
            store.upsert(token)
            store.save_to_path(token_store_path)

    return token


class DiscoveredRuntimes:
    def __init__(self, runtimes, usb_environment=None, wifi_environment=None):
        self._runtimes = runtimes
        self._usb_environment = usb_environment
        self._wifi_environment = wifi_environment

    def runtimes(self):
        return list(self._runtimes)

    def usb_environment(self):
        return self._usb_environment

    def wifi_environment(self):
        return self._wifi_environment


def discover_runtimes(
    tokens=None,
    include_usb=True,
    include_wifi=True,
    wifi_timeout_ms=800,
):
    runtimes = []
    usb_environment = None
    wifi_environment = None

    if include_usb:
        usb_environment = UsbEnvironment()
        runtimes.extend(usb_environment.runtimes())

    excluded_host_ids = []
    for runtime in runtimes:
        try:
            excluded_host_ids.append(runtime.host().identifier())
        except Exception:
            pass

    if include_wifi:
        if tokens is None:
            tokens = TokenStore.load().tokens()
        wifi_environment = WifiEnvironment(
            tokens=tokens,
            timeout_ms=wifi_timeout_ms,
            excluded_host_ids=excluded_host_ids,
        )
        runtimes.extend(wifi_environment.runtimes())

    return DiscoveredRuntimes(
        runtimes,
        usb_environment=usb_environment,
        wifi_environment=wifi_environment,
    )

class Fixture:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]
        sources_data = json_data["sources"]

        # Create Source objects from JSON data
        sources = [Source.from_json(source_data) for source_data in sources_data]

        return cls(identifier, sources)

    @classmethod
    def from_device(cls, remote_fixture):
        """Create a Fixture from a native RemoteFixture (device-backed)."""
        identifier = remote_fixture.identifier()
        remote_sources = remote_fixture.sources()
        sources = [Source.from_device(s) for s in remote_sources]
        return cls(identifier, sources, remote_fixture=remote_fixture)

    def __init__(self, identifier, sources, remote_fixture=None):
        self._identifier = identifier
        self._sources = sources
        self._remote_fixture = remote_fixture

    def identifier(self):
        return self._identifier

    def sources(self):
        return self._sources

    def tensor(self):
        from tinygrad.tensor import Tensor
        return Tensor.stack([s.tensor() for s in self._sources])

    def display(self, config, flux):
        """Send a display command to the device. Requires a device-backed fixture."""
        if self._remote_fixture is None:
            raise RuntimeError("display requires a device-backed fixture")
        return self._remote_fixture.display(config, flux)

class Source:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]

        emitters_data = json_data["emitters"]
        emitters = [Emitter.from_json(emitter_data) for emitter_data in emitters_data]

        return cls(identifier, emitters)

    @classmethod
    def from_device(cls, remote_source):
        """Create a Source from a native RemoteSource (device-backed)."""
        identifier = remote_source.identifier()
        remote_emitters = remote_source.emitters()
        emitters = [Emitter.from_device(e) for e in remote_emitters]
        return cls(identifier, emitters, remote_source=remote_source)

    def __init__(self, identifier, emitters, remote_source=None):
        self._identifier = identifier
        self._emitters = emitters
        self._remote_source = remote_source

    def identifier(self):
        return self._identifier

    def emitters(self):
        return self._emitters

    def _emitter_spectral_distributions(self):
        return [e.spectral_data().spectral_distribution() for e in self._emitters]

    def tensor(self):
        from tinygrad.tensor import Tensor, dtypes
        emitter_values = [e.spectral_data().measurements() for e in self._emitters]
        return Tensor(emitter_values, dtype=dtypes.float32)

    def _plot(self, plot_fn, display=True, output=None):
        plot_fn(self._emitter_spectral_distributions(), show=False)
        fig = plt.gcf()
        fig.set_size_inches(1920 / 100, 1080 / 100)
        fig.set_dpi(100)
        if output is not None:
            fig.savefig(output, bbox_inches='tight')
        if display:
            plt.show()
        plt.close(fig)

    def plot_emitter_spectral_distributions(self, display=True, output=None):
        self._plot(plot_multi_sds, display=display, output=output)

    def plot_emitter_chromaticity_diagram(self, display=True, output=None):
        self._plot(plot_sds_in_chromaticity_diagram_CIE1931, display=display, output=output)

    def display(self, config, flux):
        """Send a display command to the device. Requires a device-backed source."""
        if self._remote_source is None:
            raise RuntimeError("display requires a device-backed source")
        return self._remote_source.display(config, flux)

class Emitter:
    @classmethod
    def from_json(cls, json_data):
        identifier = json_data["identifier"]

        sd_data = json_data["spectral_data"]
        samples = [colorimetry.SpectralSample(s["wavelength"], s["measurement"]) for s in sd_data]
        spectral_data = colorimetry.SpectralData(samples)

        return cls(identifier, spectral_data)

    @classmethod
    def from_device(cls, remote_emitter):
        """Create an Emitter from a native RemoteEmitter (device-backed)."""
        identifier = remote_emitter.identifier()
        return cls(identifier, None, remote_emitter=remote_emitter)

    def __init__(self, identifier, spectral_data, remote_emitter=None):
        self._identifier = identifier
        self._spectral_data = spectral_data
        self._remote_emitter = remote_emitter

    def identifier(self):
        return self._identifier

    def spectral_data(self):
        if self._spectral_data is None and self._remote_emitter is not None:
            remote_sd = self._remote_emitter.spectral_data()
            name = "Emitter " + self._identifier[:8].upper()
            self._spectral_data = colorimetry.SpectralData.from_rs(remote_sd, name=name)
        return self._spectral_data

    def tensor(self):
        from tinygrad.tensor import Tensor, dtypes
        return Tensor(self.spectral_data().values(), dtype=dtypes.float32)

    def set_flux(self, flux):
        """Set flux on the device. Requires a device-backed emitter."""
        if self._remote_emitter is None:
            raise RuntimeError("set_flux requires a device-backed emitter")
        return self._remote_emitter.set_flux(flux)

class UpdateTarget:
    @classmethod
    def discover(cls):
        """Discover attached EP01 devices for firmware updates."""
        return [cls(t) for t in _enody_rs.UpdateTarget.discover()]

    def __init__(self, target_rs):
        self._target_rs = target_rs

    def identifier(self):
        return self._target_rs.identifier()

    def version(self):
        return self._target_rs.version()

    def mac_address(self):
        return self._target_rs.mac_address()

    def available_firmware(self):
        return self._target_rs.available_firmware()

    def update_available(self):
        return self._target_rs.update_available()

    def update_device(self, version):
        return self._target_rs.update_device(version)

    def flash_firmware_image(self, firmware_path):
        return self._target_rs.flash_firmware_image(firmware_path)
