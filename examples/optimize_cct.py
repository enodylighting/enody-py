"""
Optimize emitter mix across all sources to match a blackbody spectrum.

Discovers the first attached EP01, reads spectral data from each emitter,
then simultaneously optimizes all sources using a two-dimensional weight
tensor (one row per source).

Usage:
    python examples/optimize_cct.py <cct>
    python examples/optimize_cct.py 2700
"""

import sys
import time

import colour
from tinygrad import nn, TinyJit
from tinygrad.tensor import Tensor, dtypes

import enody
import enody.device
from enody import Configuration, Fixture, Flux
from enody.optimize import ssi, cie_1931_chromaticity

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <cct>")
    raise SystemExit(1)

TARGET_CCT = int(sys.argv[1])
ITERATIONS = 10000
UPDATE_INTERVAL = 100

# Discover attached devices
runtimes = enody.device.discover()
if not runtimes:
    print("No EP01 devices found.")
    raise SystemExit(1)

runtime = runtimes[0]
print(f"Connected to runtime (connected={runtime.is_connected()})")

host = runtime.host()
print(f"Host {host.identifier()} (v{host.version()})")

remote_fixture = host.fixtures()[0]
fixture = Fixture.from_device(remote_fixture)
sources = fixture.sources()
num_sources = len(sources)
n = len(sources[0].emitters())
print(f"Fixture {fixture.identifier()} has {num_sources} source(s), {n} emitter(s) each")

# (num_sources, n, 401) per-source emitter SPD matrices
spd_matrices = Tensor.stack([s.tensor() for s in sources])

# Reference blackbody spectrum
spectral_shape = colour.SpectralShape(380, 780, 1)
ref_sd = colour.sd_blackbody(TARGET_CCT, spectral_shape)
ref_values = ref_sd.values.tolist()
ref_tensor = Tensor([ref_values] * num_sources, dtype=dtypes.float32)

# Two-dimensional weight tensor — one row per source
weights = Tensor.ones(num_sources, n, dtype=dtypes.float32) * 0.5
optimizer = nn.optim.Adam([weights], lr=1e-4)

SSI_WEIGHT = 1.0 / 2500.0
CHROM_WEIGHT = 1.0 / 5.0

@TinyJit
def step():
    Tensor.training = True
    optimizer.zero_grad()

    duty_cycles = weights.clip(0, 1)
    # Per-source emission: (num_sources, 1, n) @ (num_sources, n, 401) -> (num_sources, 401)
    emission = (duty_cycles.unsqueeze(1) @ spd_matrices).squeeze(1) + 1e-9

    # SSI loss: compare first 301 samples (380-680nm)
    emission_ssi = emission.shrink((None, (0, 301)))
    ref_ssi = ref_tensor.shrink((None, (0, 301)))
    ssi_score = ssi(emission_ssi, ref_ssi)
    spectral_loss = (100.0 - ssi_score).sum()

    # Chromaticity loss: compare on full 401 samples
    emission_xy = cie_1931_chromaticity(emission)
    ref_xy = cie_1931_chromaticity(ref_tensor)
    chrom_delta = emission_xy - ref_xy
    chrom_loss = (chrom_delta.square().sum(axis=0) + 1e-9).sqrt().sum()

    loss = SSI_WEIGHT * spectral_loss + CHROM_WEIGHT * chrom_loss

    loss.backward()
    optimizer.step()
    return loss, ssi_score, chrom_loss

print(f"\nOptimizing {num_sources} source(s) for {TARGET_CCT}K CCT...")
t_loop = time.monotonic()

for i in range(ITERATIONS):
    t_step = time.monotonic()
    loss, ssi_score, chrom_loss = step()
    t_compute = time.monotonic() - t_step

    if (i + 1) % UPDATE_INTERVAL == 0:
        t_device = time.monotonic()
        w_np = weights.clip(0, 1).numpy()
        for s_idx, source in enumerate(sources):
            for e_idx, emitter in enumerate(source.emitters()):
                emitter.set_flux(Flux.relative(float(w_np[s_idx][e_idx])))
        fixture.display(Configuration.manual(), Flux.relative(1.0))
        t_device = time.monotonic() - t_device
        ssi_vals = ssi_score.numpy().flatten().tolist()
        elapsed = time.monotonic() - t_loop
        print(f"[{i+1}/{ITERATIONS}] SSI={[f'{v:.1f}' for v in ssi_vals]}"
              f" chrom_loss={chrom_loss.numpy().item():.6f}"
              f" step={t_compute*1000:.0f}ms device={t_device*1000:.0f}ms"
              f" elapsed={elapsed:.1f}s")
    elif (i + 1) % 500 == 0:
        elapsed = time.monotonic() - t_loop
        print(f"[{i+1}/{ITERATIONS}] step={t_compute*1000:.0f}ms elapsed={elapsed:.1f}s")

w_final = weights.clip(0, 1).numpy()
for s_idx in range(num_sources):
    print(f"\nSource {s_idx} weights: {[round(float(w), 4) for w in w_final[s_idx]]}")
