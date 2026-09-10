"""Real extension regressions, each in a process protected by a hard watchdog.

Build first: cargo build --example native-test-peer, then maturin develop.
The fake device is itself a separate process and uses the real Noise protocol.
"""
import os
import signal
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PEER = Path(os.environ.get("ENODY_TEST_PEER", ROOT / ("target/debug/examples/native-test-peer.exe" if os.name == "nt" else "target/debug/examples/native-test-peer")))


@pytest.mark.parametrize("scenario", ["operations", "delayed-connect", "pairing-delay", "host-timeout", "display-timeout", "callbacks", "concurrent", "discovery", "tokens"])
def test_native_io(scenario):
    assert PEER.is_file(), "Build the local peer: cargo build --example native-test-peer"
    # A parent process can kill a child whose native call holds the GIL forever.
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/native/runner.py"), str(PEER), scenario],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stdout + stderr
    finally:
        # Kill the whole group, including the peer, if the child holds the GIL
        # forever. The peer also has its own watchdog for non-POSIX platforms.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=3)
