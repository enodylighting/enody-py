"""
Plot the spectral power distributions of every emitter in the first source.

Discovers the first attached EP01 via UsbEnvironment, walks the
Host → Fixture → Source hierarchy to reach the first Source, then
plots its per-emitter SPDs using the colour-science library.

Architecture:

    UsbEnvironment          Discovery surface that scans the USB bus and
        └── Runtime         creates one RemoteRuntime per attached device.
              └── Host      The physical compute resource (EP01 board).
                    └── Fixture     An addressable light-output unit.
                          └── Source    An independently controllable region.
                                └── Emitter   A single LED channel with its own SPD.

Usage:
    python examples/plot_source.py              # display plot interactively
    python examples/plot_source.py plot.png     # save to file (no display)
"""

import sys

from enody import UsbEnvironment

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------

# Optional positional argument: file path to save the plot to.  When provided
# the interactive display window is suppressed so the script can run headless
# (e.g. in CI or over SSH).
output = sys.argv[1] if len(sys.argv) > 1 else None

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

# ---------------------------------------------------------------------------
# Walk the hierarchy to the first Source and plot
# ---------------------------------------------------------------------------
# Each Runtime exposes exactly one Host (the physical board).  The Host in
# turn owns one or more Fixtures.  For the EP01 there is always exactly one
# Fixture, but the API generalizes to multi-head products.
# host.fixtures() returns zero or more Fixtures owned by the host.
# fixture.sources() returns one or more Sources within the Fixture.
# plot_emitter_spectral_distributions() reads the calibrated SPD from every
# Emitter in the Source and renders them with colour.plotting.

for runtime in runtimes:
    host = runtime.host()
    for fixture in host.fixtures():
        for source in fixture.sources():
            source.plot_emitter_spectral_distributions(
                display=output is None,
                output=output,
            )
            exit(0)
