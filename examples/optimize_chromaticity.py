"""
Optimize emitter mix across all sources to hit a target CIE 1931 chromaticity.

Discovers the first attached EP01 via UsbEnvironment, reads the calibrated
spectral power distribution (SPD) from each emitter, then runs gradient
descent to find per-emitter duty cycles that produce the desired (x, y)
chromaticity coordinate.

Architecture:

    UsbEnvironment          Discovery surface that scans the USB bus and
        └── Runtime         creates one RemoteRuntime per attached device.
              └── Host      The physical compute resource (EP01 board).
                    └── Fixture     An addressable light-output unit.
                          └── Source    An independently controllable region.
                                └── Emitter   A single LED channel with its own SPD.

The optimizer adjusts a 2-D weight tensor (one row per Source, one column
per Emitter) so that the weighted combination of SPDs yields a mixed
spectrum whose CIE 1931 (x, y) chromaticity matches the target.

Usage:
    python examples/optimize_chromaticity.py <x> <y>
    python examples/optimize_chromaticity.py 0.3127 0.3290
"""

import sys

from tinygrad import nn
from tinygrad.tensor import Tensor, dtypes

from enody import Configuration, Flux, UsbEnvironment
from enody.optimize import cie_1931_chromaticity

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <x> <y>")
    raise SystemExit(1)

TARGET_X = float(sys.argv[1])
TARGET_Y = float(sys.argv[2])
# Count of gradient descent iterations
ITERATIONS = 1000

# How often (in iterations) to push updated duty cycles to the device so the
# light output tracks the optimizer's progress in real time.
UPDATE_INTERVAL = 100

# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------
# UsbEnvironment is a DiscoveryEnvironment — on construction it enumerates
# every USB-attached Enody device, performs a handshake, and returns a connection
# to the RemoteRuntime.

environment = UsbEnvironment()
runtimes = environment.runtimes()
if not runtimes:
    print("No EP01 devices found.")
    raise SystemExit(1)

# Each Runtime exposes exactly one Host (the physical board).  The Host in
# turn owns one or more Fixtures.  For the EP01 there is always exactly one
# Fixture, but the API generalizes to multi-head products.

runtime = runtimes[0]
print(f"Connected to runtime (connected={runtime.is_connected()})")

host = runtime.host()
print(f"Host {host.identifier()} (v{host.version()})")

# ---------------------------------------------------------------------------
# Fixture / Source / Emitter hierarchy
# ---------------------------------------------------------------------------
# host.fixtures() returns zero or more Fixtures owned by the host.
# fixture.sources() returns one or more Sources within the Fixture
# source.emitters() returns one or more Emitters within the Source

fixtures = host.fixtures()

if len(fixtures) == 0:
    print("No fixtures found on the host.")
    raise SystemExit(1)

fixture = fixtures[0]
sources = fixture.sources()
num_sources = len(sources)
n = len(sources[0].emitters())
print(f"Fixture {fixture.identifier()} has {num_sources} source(s), "
      f"{n} emitter(s) each")

# ---------------------------------------------------------------------------
# Build the per-source SPD matrix
# ---------------------------------------------------------------------------
# source.tensor() returns a (n, 401) Tensor where each row is the SPD of
# one emitter sampled at 1 nm intervals from 380 nm to 780 nm (401 points).
# Stacking across all sources gives shape (num_sources, n, 401).

spd_matrices = Tensor.stack([s.tensor() for s in sources])

# ---------------------------------------------------------------------------
# Chromaticity Optimization
# ---------------------------------------------------------------------------
# The weight tensor has shape (num_sources, n) — one scalar weight per
# emitter per source.  During forward passes the weights are clipped to
# [0, 1] to represent physically valid duty cycles.

weights = Tensor.ones(num_sources, n, dtype=dtypes.float32) * 0.5
optimizer = nn.optim.Adam([weights], lr=1e-3)

# Target chromaticity as a column vector for easy broadcasting against the
# (2, num_sources) output of cie_1931_chromaticity.
target = Tensor([[TARGET_X], [TARGET_Y]])

print(f"\nOptimizing {num_sources} source(s) for chromaticity "
      f"({TARGET_X}, {TARGET_Y})...")

# ---------------------------------------------------------------------------
# Optimization loop
# ---------------------------------------------------------------------------

for i in range(ITERATIONS):
    Tensor.training = True
    optimizer.zero_grad()

    # Clip weights to valid duty-cycle range [0, 1].
    duty_cycles = weights.clip(0, 1)

    # Mix emitter SPDs by duty cycle for each source independently.
    # duty_cycles:  (num_sources, n)       -> unsqueeze -> (num_sources, 1, n)
    # spd_matrices: (num_sources, n, 401)
    # Batched matmul produces (num_sources, 1, 401), squeezed to
    # (num_sources, 401).  The small epsilon prevents division-by-zero in
    # downstream chromaticity calculations.
    emission = (duty_cycles.unsqueeze(1) @ spd_matrices).squeeze(1) + 1e-9

    # Compute CIE 1931 (x, y) chromaticity for each source's mixed spectrum.
    # Returns shape (2, num_sources) — row 0 is x, row 1 is y.
    xy = cie_1931_chromaticity(emission)

    # Euclidean distance from target per source, summed to a scalar loss.
    delta = xy - target
    loss = (delta.square().sum(axis=0) + 1e-9).sqrt().sum()

    loss.backward()
    optimizer.step()

    # Every UPDATE_INTERVAL iterations, push the current duty cycles to the
    # physical device so the light output reflects the optimizer's progress.
    if (i + 1) % UPDATE_INTERVAL == 0:
        w_np = weights.clip(0, 1).numpy()

        # Walk the Source → Emitter hierarchy and set each emitter's flux
        # to the corresponding optimized weight.  Flux.relative() takes a
        # value in [0, 1] representing the fraction of maximum output.
        for s_idx, source in enumerate(sources):
            for e_idx, emitter in enumerate(source.emitters()):
                emitter.set_flux(Flux.relative(float(w_np[s_idx][e_idx])))

        # fixture.display() sends a FixtureCommand::Display to the device
        # via the RemoteRuntime held by the Fixture handle.
        # Configuration.manual() tells the firmware to use the per-emitter
        # flux values we just set, rather than any built-in preset.
        # Supplied flux is ignored as per-emitter settings are utilized
        fixture.display(Configuration.manual(), Flux.relative(1.0))

        xy_np = xy.numpy().squeeze()
        print(f"[{i+1}/{ITERATIONS}] loss={loss.numpy().item():.6f}"
              f" xy={xy_np.T.tolist()}")

# ---------------------------------------------------------------------------
# Final weights
# ---------------------------------------------------------------------------

w_final = weights.clip(0, 1).numpy()
for s_idx in range(num_sources):
    print(f"\nSource {s_idx} weights: "
          f"{[round(float(w), 4) for w in w_final[s_idx]]}")
