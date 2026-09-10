"""Child test runner. Do not import this module in pytest's main process."""
import asyncio
from functools import partial
from contextlib import contextmanager
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

# Optional diagnostic override for comparing an older compiled extension.
if os.environ.get("ENODY_TEST_EXTENSION"):
    spec = importlib.util.spec_from_file_location("_enody_rs", os.environ["ENODY_TEST_EXTENSION"])
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
else:
    from enody import _enody_rs as native

assert any(native.__file__.endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES)

HOST = "00000000-0000-0000-0000-000000000001"


@contextmanager
def peer(mode):
    process = subprocess.Popen([sys.argv[1], mode], stdout=subprocess.PIPE, text=True)
    try:
        endpoint = process.stdout.readline().strip()
        assert endpoint.startswith("127.0.0.1:"), endpoint
        yield endpoint, process
    finally:
        process.terminate()
        process.wait(timeout=3)


def runtime(endpoint):
    return native.WifiConnection.runtime_from_endpoint(native.Token(HOST, "test", [7] * 32), endpoint)


async def in_thread(operation, *args):
    # Keep the harness usable on the SDK's minimum Python (3.8).
    return await asyncio.get_running_loop().run_in_executor(None, partial(operation, *args))


async def responsive(operation, minimum=0.15):
    """Start heartbeat BEFORE submitting native work, also sample after return."""
    ticks = []
    stop = False

    async def heartbeat():
        while not stop:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.03)
    start = time.monotonic()
    try:
        return await asyncio.get_running_loop().run_in_executor(None, operation)
    finally:
        elapsed = time.monotonic() - start
        await asyncio.sleep(0.03)
        stop = True
        await task
        gaps = [b-a for a, b in zip(ticks, ticks[1:])]
        assert elapsed >= minimum, (elapsed, minimum)
        assert max(gaps) < 0.15, f"GIL held: max heartbeat gap {max(gaps):.3f}s during {elapsed:.3f}s call"
        print(f"elapsed={elapsed:.3f}s max_gap={max(gaps):.3f}s", flush=True)


def expect_timeout(operation):
    start = time.monotonic()
    try:
        operation()
    except RuntimeError as error:
        assert "timeout" in str(error).lower() or "timed out" in str(error).lower(), str(error)
    else:
        raise AssertionError("expected native timeout")
    return time.monotonic() - start


async def run(scenario, endpoint, process):
    if scenario == "pairing-delay":
        token = await responsive(
            lambda: native.WifiConnection.generate_token_from_endpoint(endpoint), minimum=2)
        assert token.host_id() == HOST
        return
    if scenario == "callbacks":
        seen = []
        def callback(instruction):
            # Calling Python and the extension inside the callback requires the GIL.
            seen.append((instruction, native.Flux.relative(0.5).value))
        token = await responsive(lambda: native.WifiConnection.generate_token_from_endpoint(endpoint, callback))
        assert token.host_id() == HOST
        assert seen == [("Approve test peer", 0.5)]
        class CallbackError(Exception):
            pass
        def fail(_):
            raise CallbackError("callback failure survives native boundary")
        try:
            await responsive(lambda: native.WifiConnection.generate_token_from_endpoint(endpoint, fail))
        except CallbackError as error:
            assert str(error) == "callback failure survives native boundary"
        else:
            raise AssertionError("callback exception lost")
        return
    r = runtime(endpoint)
    try:
        if scenario == "delayed-connect":
            connect_task = asyncio.create_task(responsive(r.connect, minimum=2))
            assert await in_thread(process.stdout.readline) == "waiting\n"
            # A separate connection to the same host must not share a global lock.
            independent = runtime(endpoint)
            try:
                await responsive(independent.connect)
                assert (await responsive(independent.host)).identifier() == HOST
                assert not connect_task.done(), "independent connection was blocked by slow connect"
            finally:
                await in_thread(independent.disconnect)
            # Disconnect on the original connection waits for connect, without GIL.
            disconnect_task = asyncio.create_task(responsive(r.disconnect))
            await asyncio.gather(connect_task, disconnect_task)
            assert not r.is_connected()
            await responsive(r.connect)
            assert r.is_connected()
            assert (await responsive(r.host)).identifier() == HOST
            return
        await responsive(r.connect)
        if scenario == "host-timeout":
            elapsed = await responsive(lambda: expect_timeout(r.host))
            assert 0.4 <= elapsed < 1.5
        host = await responsive(r.host)
        fixture = (await responsive(host.fixtures))[0]
        config, flux = native.Configuration.blackbody(2700), native.Flux.relative(0.4)
        display = lambda: fixture.display(config, flux)
        if scenario == "display-timeout":
            elapsed = await responsive(lambda: expect_timeout(display))
            assert 0.4 <= elapsed < 1.5
        result = await responsive(display)
        assert abs(result[1].value - 0.4) < 1e-6
        if scenario == "concurrent":
            # Two simultaneous connects must not start duplicate dispatchers.
            await asyncio.gather(in_thread(r.connect), in_thread(r.connect))
            for _ in range(3):
                results = await asyncio.gather(responsive(r.host), responsive(display))
                assert results[0].identifier() == HOST
                assert abs(results[1][1].value - 0.4) < 1e-6
            # Descendant handles share the runtime gate. A queued request's
            # existing response timeout starts only after the transition finishes.
            transition = native.Transition.linear(config, flux, 1.0)
            transition_task = asyncio.create_task(responsive(lambda: fixture.transition(transition)))
            assert await in_thread(process.stdout.readline) == "transition\n"
            queued_host = await responsive(r.host, minimum=1.0)
            assert queued_host.identifier() == HOST
            await transition_task
            source = (await responsive(fixture.sources))[0]
            emitter = (await responsive(source.emitters))[0]
            transition_task = asyncio.create_task(responsive(lambda: source.transition(transition)))
            assert await in_thread(process.stdout.readline) == "transition\n"
            await responsive(lambda: emitter.set_flux(flux), minimum=1.0)
            await transition_task
            await asyncio.gather(in_thread(r.disconnect), in_thread(r.disconnect))
            assert not r.is_connected()
            await responsive(r.connect)
            await responsive(r.host)
        if scenario == "operations":
            source = (await responsive(fixture.sources))[0]
            emitter = (await responsive(source.emitters))[0]
            await responsive(lambda: source.display(config, flux))
            await responsive(lambda: emitter.set_flux(flux))
            assert (await responsive(emitter.spectral_data)).sample_count() == 0
            assert await responsive(host.wifi_scan) == []
            await responsive(lambda: host.wifi_join("test", "password"))
            assert (await responsive(r.generate_token)).host_id() == HOST
            transition = native.Transition.linear(config, flux, 0.3)
            await responsive(lambda: fixture.transition(transition))
            await responsive(lambda: source.transition(transition))
    finally:
        await responsive(r.disconnect, minimum=0)
    assert not r.is_connected()


async def discovery():
    # The environment remains thread-affine at the Python API; construct, call,
    # and destroy it in one executor job. Empty tokens avoid real-device access.
    def operation():
        env = native.WifiEnvironment([], 300, [])
        assert env.runtimes() == []
        env.start_discovery()
        env.stop_discovery()
        env.exclude_host_id(HOST)
        env.remove_excluded_host_id(HOST)
        del env
        native.WifiConnection.discover_token_generation_devices(300)
    # mDNS can legitimately return immediately without a usable interface.
    await responsive(operation, minimum=0)


async def tokens():
    import tempfile
    import uuid
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_CONFIG_HOME"] = directory
        if hasattr(os, "mkfifo"):
            fifo = Path(directory) / "tokens.fifo"
            os.mkfifo(fifo)
            writer = subprocess.Popen([sys.executable, "-c",
                "import sys,time; f=open(sys.argv[1], 'w'); time.sleep(0.25); f.write('{\"tokens\": []}'); f.close()", str(fifo)])
            try:
                store = await responsive(lambda: native.TokenStore.load_from_path(str(fifo)))
                assert store.tokens() == []
            finally:
                writer.wait(timeout=3)
        ids = [str(uuid.UUID(int=i+1)) for i in range(16)]
        await asyncio.gather(*(in_thread(native.TokenStore.save_token,
            native.Token(host_id, "test", [7]*32)) for host_id in ids))
        store = native.TokenStore.load()
        assert sorted(t.host_id() for t in store.tokens()) == sorted(ids)


scenario = sys.argv[2]
if scenario == "tokens":
    asyncio.run(tokens())
elif scenario == "discovery":
    asyncio.run(discovery())
else:
    mode = "delayed" if scenario in {"delayed-connect", "pairing-delay"} else scenario
    with peer(mode) as (endpoint, process):
        asyncio.run(run(scenario, endpoint, process))
