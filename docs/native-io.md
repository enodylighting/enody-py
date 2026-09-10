# Native I/O and Python threads

This patch changes only the Python bindings and their tests. The `enody-rs`
submodule stays at its original revision; its transport and timeout behavior are
unchanged.

Device calls remain synchronous. Invoke them in an executor when using asyncio.
The bindings release the GIL around native waits, so unrelated Python threads
(including an asyncio event loop) can continue running. Python arguments are
extracted before the native call; results are wrapped afterwards. Pairing
callbacks reacquire the GIL and preserve Python exceptions.

## Concurrency

Previously the GIL serialized synchronous Python device calls. The bindings now
serialize them per native connection with a mutex acquired after releasing the
GIL. Runtime, host, fixture, source, and emitter handles for the same connection
share that mutex, including repeated wrappers returned by discovery. This keeps
Python calls from racing connection lifecycle changes or overlapping transport
writes. Independent connections can proceed concurrently, even to the same host.
The binding mutex does not alter the Rust SDK's own background discovery behavior.

A long transition or stalled operation delays subsequent Python calls on that
connection. Waiting for the mutex does not hold the GIL, and the native response
wait starts after admission. This preserves the serialization imposed by the old
bindings while allowing unrelated connections and Python threads to run.
Token-file operations also retain process-local serialization after releasing
the GIL, so concurrent load/upsert/save calls cannot lose token updates.

USB and WiFi discovery environments retain their existing Python thread affinity.
Each environment owns a native worker thread, because the USB backend contains
thread-affine hotplug registrations. Construction, operations, and destruction
run on that owner thread; waiting for replies releases the GIL. Dropping the
Python environment closes its work queue; native teardown follows asynchronously
on its owner thread. No unsafe Send/Sync declarations are needed. Source and
emitter handles use binding-owned `Arc`s rather than adding Clone to Rust types.

## Timeouts and cancellation

This is a responsiveness fix, not a hard-deadline guarantee. The upstream SDK's
existing response windows remain: normally 500 ms, 10 seconds for WiFi scan/join
and USB token generation, 45 seconds for physical WiFi pairing approval after the
handshake, and the requested transition duration plus two seconds. Discovery
retains its caller-supplied window. Traversal and spectral downloads make multiple
requests. `next_runtime_event()` remains an intentional stream wait.

TCP connection, Noise handshake, write, filesystem, and firmware operations gain
no new deadlines. Connection-lock admission is also unbounded. An unreachable or
unresponsive device can therefore still occupy an executor worker and delay
other calls on its connection, even though Python remains responsive.

Cancelling an asyncio executor future does not stop a native call already in
progress, including one waiting for the binding mutex. Let that call finish before
assuming it is safe to submit an operation that must not overlap. The bindings do
not abandon native futures, add retry policies, or claim new partial-connection
cleanup guarantees. Strict deadlines and transport cancellation remain separate
Rust SDK work.

## Regression tests

Build the real extension in a Python environment with pytest, and the separate
local peer:

```sh
maturin develop --extras science,dev
cargo build --example native-test-peer
DEV=CPU python -m pytest tests
cargo test --manifest-path enody-rs/Cargo.toml --lib
```

`tests/test_native_io.py` launches a watchdog-protected child for each scenario.
The child drives the actual extension in an executor while measuring asyncio
heartbeat gaps. A separate Rust peer implements the real Noise/Postcard protocol.
Delayed handshakes eventually receive replies; they are not tests of a new SDK
connection deadline. The external watchdog prevents a GIL regression from hanging
the test runner.

Tests cover delayed connection and pairing, independent connections, serialized
connect/disconnect, shared locking across descendant handles and long transitions,
metadata/display response timeouts and recovery, source/emitter operations, WiFi
commands, discovery, Python approval callback errors, FIFO-backed token reads,
and concurrent token saves. No lighting fixtures, WiFi credentials, or real Home
Assistant instance are required. Discovery only scans; its environment uses an
empty token list and cannot connect to real devices. Physical USB and firmware
flashing still require hardware validation.
