from enody._enody_rs import UsbEnvironment

def discover():
    """Discover attached EP01 devices. Returns list of Runtimes."""
    env = UsbEnvironment()
    return env.runtimes()
