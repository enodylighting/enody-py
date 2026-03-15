from enody import UsbEnvironment

environment = UsbEnvironment()

# Discover attached devices
runtimes = environment.runtimes()
if not runtimes:
    print("No EP01 devices found.")
    raise SystemExit(1)

runtime = runtimes[0]
host = runtime.host()
fixture = host.fixtures()[0]
sources = fixture.sources()
sources[0].plot_emitter_spectral_distributions()