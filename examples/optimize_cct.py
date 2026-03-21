"""
Optimize emitter mix across all sources to match a blackbody spectrum.

Discovers the first attached EP01 via UsbEnvironment, reads the calibrated
spectral power distribution (SPD) from each emitter, then runs gradient
descent to find per-emitter duty cycles that best approximate a blackbody
radiator at the requested correlated color temperature (CCT).

The loss function is a weighted sum of two terms:
  1. Spectral Similarity Index (SSI) — penalizes spectral shape mismatch
     across the 380-680 nm range.
  2. CIE 1931 chromaticity distance — penalizes deviation of the mixed
     spectrum's (x, y) coordinate from the reference blackbody's (x, y).

Architecture:

    UsbEnvironment          Discovery surface that scans the USB bus and
        └── Runtime         creates one RemoteRuntime per attached device.
              └── Host      The physical compute resource (EP01 board).
                    └── Fixture     An addressable light-output unit.
                          └── Source    An independently controllable region.
                                └── Emitter   A single LED channel with its own SPD.

Usage:
    python examples/optimize_cct.py <cct>
    python examples/optimize_cct.py 2700
"""

import sys
import time

import colour
from tinygrad import nn, TinyJit
from tinygrad.tensor import Tensor, dtypes

from enody import Configuration, Flux, UsbEnvironment
from enody.optimize import ssi, cie_1931_chromaticity

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <cct>")
    raise SystemExit(1)

TARGET_CCT = int(sys.argv[1])

# Count of gradient descent iterations
ITERATIONS = 10_000

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
# fixture.source() returns one or more Sources within the Fixture
# source.emitter() returns one or more Emitters within the Source

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
# Build the reference blackbody spectrum
# ---------------------------------------------------------------------------
# colour.sd_blackbody generates a theoretical Planckian radiator spectrum at
# the target CCT.  The spectral shape (380-780 nm, 1 nm steps) matches the
# emitter SPD sampling so the tensors are directly comparable.
# We tile the reference across num_sources so every source is optimized
# toward the same target.

spectral_shape = colour.SpectralShape(380, 780, 1)
ref_sd = colour.sd_blackbody(TARGET_CCT, spectral_shape)
ref_values = ref_sd.values.tolist()
ref_tensor = Tensor([ref_values] * num_sources, dtype=dtypes.float32)

# ---------------------------------------------------------------------------
# Spectral Optimization 
# ---------------------------------------------------------------------------
# The weight tensor has shape (num_sources, n) — one scalar weight per
# emitter per source.  During forward passes the weights are clipped to
# [0, 1] to represent physically valid duty cycles. 

weights = Tensor.ones(num_sources, n, dtype=dtypes.float32) * 0.5
optimizer = nn.optim.Adam([weights], lr=1e-4)

# Loss weighting coefficients. These coefficients were chosen empirically.
SSI_WEIGHT = 1.0 / 2500.0
CHROM_WEIGHT = 1.0 / 5.0

@TinyJit
def step():
    Tensor.training = True
    optimizer.zero_grad()

    # Clip weights to valid duty-cycle range [0, 1].
    duty_cycles = weights.clip(0, 1)

    # Mix emitter SPDs by duty cycle for each source independently.
    # duty_cycles:  (num_sources, n)       -> unsqueeze -> (num_sources, 1, n)
    # spd_matrices: (num_sources, n, 401)
    # Batched matmul produces (num_sources, 1, 401), squeezed to
    # (num_sources, 401).  The small epsilon prevents division-by-zero in
    # downstream chromaticity and SSI calculations.
    emission = (duty_cycles.unsqueeze(1) @ spd_matrices).squeeze(1) + 1e-9

    # --- SSI loss ---
    # SSI (Spectral Similarity Index) compares spectral shape over the
    # 375-675 nm range (301 samples: 375-379 nm are zeros, then 380-675 nm from emission).
    pad_zeros = Tensor.zeros(emission.shape[0], 5, dtype=emission.dtype)
    emission_ssi = Tensor.cat([pad_zeros, emission.shrink((None, (0, 296)))], axis=1)
    ref_ssi = Tensor.cat([pad_zeros, ref_tensor.shrink((None, (0, 296)))], axis=1)
    ssi_score = ssi(emission_ssi, ref_ssi)
    spectral_loss = (100.0 - ssi_score).sum()

    # --- Chromaticity loss ---
    # Euclidean distance in CIE 1931 (x, y) space between the mixed
    # spectrum and the reference blackbody, computed over the full 401
    # sample range.  This keeps the color point on-target even if the
    # spectral shape has residual differences.
    emission_xy = cie_1931_chromaticity(emission)
    ref_xy = cie_1931_chromaticity(ref_tensor)
    chrom_delta = emission_xy - ref_xy
    chrom_loss = (chrom_delta.square().sum(axis=0) + 1e-9).sqrt().sum()

    # Weighted combination of the two objectives.
    loss = SSI_WEIGHT * spectral_loss + CHROM_WEIGHT * chrom_loss

    loss.backward()
    optimizer.step()
    return loss, ssi_score, chrom_loss

# ---------------------------------------------------------------------------
# Optimization loop
# ---------------------------------------------------------------------------

print(f"\nOptimizing {num_sources} source(s) for {TARGET_CCT}K CCT...")
t_loop = time.monotonic()

for i in range(ITERATIONS):
    t_step = time.monotonic()
    loss, ssi_score, chrom_loss = step()
    t_compute = time.monotonic() - t_step

    # Every UPDATE_INTERVAL iterations, push the current duty cycles to the
    # physical device so the light output reflects the optimizer's progress.
    if (i + 1) % UPDATE_INTERVAL == 0:
        t_device = time.monotonic()
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
        t_device = time.monotonic() - t_device

        ssi_vals = ssi_score.numpy().flatten().tolist()
        elapsed = time.monotonic() - t_loop
        print(f"[{i+1}/{ITERATIONS}] SSI={[f'{v:.1f}' for v in ssi_vals]}"
              f" chrom_loss={chrom_loss.numpy().item():.6f}"
              f" step={t_compute*1000:.0f}ms device={t_device*1000:.0f}ms"
              f" elapsed={elapsed:.1f}s")

# ---------------------------------------------------------------------------
# Final weights
# ---------------------------------------------------------------------------

w_final = weights.clip(0, 1).numpy()
for s_idx in range(num_sources):
    print(f"\nSource {s_idx} weights: "
          f"{[round(float(w), 4) for w in w_final[s_idx]]}")
