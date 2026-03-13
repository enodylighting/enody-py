"""
Optimize emitter mix across all sources to hit a target CIE 1931 chromaticity.

Discovers the first attached EP01, reads spectral data from each emitter,
then simultaneously optimizes all sources using a two-dimensional weight
tensor (one row per source).

Usage:
    python examples/optimize_chromaticity.py <x> <y>
    python examples/optimize_chromaticity.py 0.3127 0.3290
"""

import sys

from tinygrad import nn
from tinygrad.tensor import Tensor, dtypes

import enody
import enody.device
from enody import Configuration, Fixture, Flux
from enody.optimize import cie_1931_chromaticity

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <x> <y>")
    raise SystemExit(1)

TARGET_X = float(sys.argv[1])
TARGET_Y = float(sys.argv[2])
ITERATIONS = 1000
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

# Two-dimensional weight tensor — one row per source
weights = Tensor.ones(num_sources, n, dtype=dtypes.float32) * 0.5
optimizer = nn.optim.Adam([weights], lr=1e-3)

target = Tensor([[TARGET_X], [TARGET_Y]])

print(f"\nOptimizing {num_sources} source(s) for chromaticity ({TARGET_X}, {TARGET_Y})...")

for i in range(ITERATIONS):
    Tensor.training = True
    optimizer.zero_grad()

    duty_cycles = weights.clip(0, 1)
    # Per-source emission: (num_sources, 1, n) @ (num_sources, n, 401) -> (num_sources, 401)
    emission = (duty_cycles.unsqueeze(1) @ spd_matrices).squeeze(1) + 1e-9

    xy = cie_1931_chromaticity(emission)
    delta = xy - target
    loss = (delta.square().sum(axis=0) + 1e-9).sqrt().sum()

    loss.backward()
    optimizer.step()

    if (i + 1) % UPDATE_INTERVAL == 0:
        w_np = weights.clip(0, 1).numpy()
        for s_idx, source in enumerate(sources):
            for e_idx, emitter in enumerate(source.emitters()):
                emitter.set_flux(Flux.relative(float(w_np[s_idx][e_idx])))
        fixture.display(Configuration.manual(), Flux.relative(1.0))
        xy_np = xy.numpy().squeeze()
        print(f"[{i+1}/{ITERATIONS}] loss={loss.numpy().item():.6f}"
              f" xy={xy_np.T.tolist()}")

w_final = weights.clip(0, 1).numpy()
for s_idx in range(num_sources):
    print(f"\nSource {s_idx} weights: {[round(float(w), 4) for w in w_final[s_idx]]}")
