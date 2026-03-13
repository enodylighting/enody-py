# enody

Python SDK for [Enody Lighting](https://enody.lighting) spectrally tunable fixtures.

`enody` provides device discovery and control over USB, spectral data access, colorimetric calculations, and GPU-accelerated spectral optimization via [tinygrad](https://github.com/tinygrad/tinygrad). It wraps the [enody-rs](https://github.com/enodylighting/enody-rs) Rust core through native PyO3 bindings.

## Installation

Requires Python >= 3.8.

```bash
pip install enody
```

Building from source requires [maturin](https://www.maturin.rs/) and a Rust toolchain:

```bash
pip install maturin
maturin develop
```

## Quick start

### Discover and connect to a device

```python
import enody
import enody.device

runtimes = enody.device.discover()
runtime = runtimes[0]

host = runtime.host()
print(f"Host {host.identifier()} (v{host.version()})")

fixture = enody.Fixture.from_device(host.fixtures()[0])
sources = fixture.sources()
```

### Control emitters directly

```python
from enody import Configuration, Flux

for emitter in sources[0].emitters():
    emitter.set_flux(Flux.relative(0.5))
fixture.display(Configuration.manual(), Flux.relative(1.0))
```

### Use built-in display modes

```python
from enody import Configuration, Flux

# Set to 2700K blackbody
fixture.display(Configuration.blackbody(2700), Flux.relative(1.0))

# Set to a CIE 1931 chromaticity coordinate
fixture.display(Configuration.chromatic(0.3127, 0.3290), Flux.relative(0.8))
```

### Work offline with sample data

No device required — use bundled spectral data for algorithm development:

```python
import enody.data

fixture = enody.data.sample_fixture()   # 12-emitter fixture
source = enody.data.sample_source()     # 2-emitter source
emitter = enody.data.sample_emitter()   # Single emitter
```

## Device hierarchy

Enody models a strict hierarchy:

```
Runtime → Host → Fixture → Source → Emitter
```

- **Runtime** — USB connection to a physical device.
- **Host** — The device itself, identified by UUID and firmware version.
- **Fixture** — An addressable light output unit.
- **Source** — An independently controllable region within a fixture.
- **Emitter** — A single LED channel with a characteristic spectral distribution (380--780 nm, 1 nm resolution, 401 samples).

Each level can be constructed from a connected device (`from_device`) or from JSON data (`from_json`).

## Spectral optimization

Every `Emitter`, `Source`, and `Fixture` exposes a `.tensor()` method returning a tinygrad `Tensor` of spectral values, ready for differentiable optimization.

### Match a blackbody spectrum

```python
import colour
from tinygrad import nn
from tinygrad.tensor import Tensor, dtypes
from enody import Flux
from enody.optimize import ssi, cie_1931_chromaticity

source = fixture.sources()[0]
spd_matrix = source.tensor()  # (n_emitters, 401)
n = len(source.emitters())

# Reference blackbody at 4000K
ref_sd = colour.sd_blackbody(4000, colour.SpectralShape(380, 780, 1))
ref = Tensor([ref_sd.values.tolist()], dtype=dtypes.float32)

weights = Tensor.ones(1, n, dtype=dtypes.float32) * 0.5
optimizer = nn.optim.Adam([weights], lr=1e-3)

for i in range(1000):
    optimizer.zero_grad()
    duty_cycles = weights.clip(0, 1)
    emission = (duty_cycles @ spd_matrix) + 1e-9

    # SSI loss (uses 380-680nm, 301 samples)
    ssi_score = ssi(emission.shrink((None, (0, 301))),
                    ref.shrink((None, (0, 301))))
    spectral_loss = (100.0 - ssi_score).sum()

    # Chromaticity loss (uses full 401 samples)
    chrom_loss = ((cie_1931_chromaticity(emission)
                 - cie_1931_chromaticity(ref)).square().sum(axis=0) + 1e-9).sqrt().sum()

    loss = spectral_loss / 2500 + chrom_loss / 5
    loss.backward()
    optimizer.step()
```

Apply optimized weights to hardware:

```python
w = weights.clip(0, 1).numpy().flatten()
for idx, emitter in enumerate(source.emitters()):
    emitter.set_flux(Flux.relative(float(w[idx])))
fixture.display(Configuration.manual(), Flux.relative(1.0))
```

## API reference

### `enody.device`

| Function | Description |
|---|---|
| `discover()` | Returns a list of `Runtime` objects for connected EP01 devices. |

### `enody.data`

| Function | Returns |
|---|---|
| `sample_emitter()` | Single `Emitter` (1 channel) |
| `sample_source()` | `Source` with 2 emitters |
| `sample_fixture()` | `Fixture` with 1 source, 12 emitters |
| `melanopic_action()` | Melanopic response curve data |
| `rhodopic_action()` | Rhodopic response curve data |
| `s_cone_action()` | S-cone-opic response curve data |
| `m_cone_action()` | M-cone-opic response curve data |
| `l_cone_action()` | L-cone-opic response curve data |
| `cie_x_action()` | CIE X color matching function data |
| `cie_y_action()` | CIE Y color matching function data |
| `cie_z_action()` | CIE Z color matching function data |

### `enody.optimize`

All photopic response functions accept `(n, 401)` tensors (380--780 nm):

| Function | Description |
|---|---|
| `melanopic_response(t)` | Melanopic (ipRGC) response |
| `rhodopic_response(t)` | Rhodopic (rod) response |
| `s_cone_response(t)` | S-cone-opic response |
| `m_cone_response(t)` | M-cone-opic response |
| `l_cone_response(t)` | L-cone-opic response |
| `cie_x_response(t)` | CIE X tristimulus response |
| `cie_y_response(t)` | CIE Y tristimulus response |
| `cie_z_response(t)` | CIE Z tristimulus response |
| `cie_1931_chromaticity(t)` | CIE 1931 (x, y) chromaticity coordinates |

SSI accepts `(n, 301)` tensors (380--680 nm):

| Function | Description |
|---|---|
| `ssi(test, reference)` | Spectral Similarity Index (0--100) |

### `enody.colorimetry`

Pure Python color science types with `colour-science` integration:

- `SpectralData(samples)` — spectral distribution with `.spectral_distribution()` and `.luminance()`
- `SpectralSample(wavelength, value)`
- `Chromaticity(x, y)`
- `XYZ(x, y, z)`

### Core types (from `enody._enody_rs`)

| Type | Description |
|---|---|
| `Flux.relative(value)` | Relative flux (0.0--1.0) |
| `Configuration.blackbody(cct)` | Blackbody spectrum at given CCT |
| `Configuration.chromatic(x, y)` | Target CIE 1931 chromaticity |
| `Configuration.manual()` | Manual per-emitter control |
| `Configuration.flux()` | Flux-only control mode |
| `Configuration.spectral()` | Spectral control mode |
| `SpectralSample(wavelength, measurement)` | Single wavelength/value pair |
| `SpectralData` | Collection of spectral samples |
| `Chromaticity(x, y)` | CIE chromaticity coordinate |

## Dependencies

- [tinygrad](https://github.com/tinygrad/tinygrad) — tensor operations and automatic differentiation
- [colour-science](https://www.colour-science.org/) — color science computations and plotting
- [enody-rs](https://github.com/enodylighting/enody-rs) — Rust core SDK (compiled via PyO3)

## License

MIT
