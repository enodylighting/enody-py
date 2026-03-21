import argparse
import json
import signal
import sys

import enody


def cmd_list(args):
    env = enody.UsbEnvironment()
    runtimes = env.runtimes()

    if not runtimes:
        print("No Enody devices found.")
        return

    for runtime in runtimes:
        host = runtime.host()
        print(f"Device {host.identifier()}")
        print(f"\tVersion: {host.version()}")


def cmd_info(args):
    env = enody.UsbEnvironment()
    runtimes = env.runtimes()

    if not runtimes:
        print("No Enody devices found.")
        return

    for device_idx, runtime in enumerate(runtimes):
        if device_idx > 0:
            print()

        print("\u2550" * 62)
        print(f"Device {device_idx + 1}")
        print("\u2550" * 62)

        host = runtime.host()

        print()
        print("Host")
        print("\u2500" * 62)
        print(f"  Identifier: {host.identifier()}")
        print(f"  Version:    {host.version()}")

        fixtures = host.fixtures()
        print(f"  Fixtures:   {len(fixtures)}")

        for fixture_idx, fixture in enumerate(fixtures):
            print()
            print(f"Fixture {fixture_idx + 1}")
            print("\u2500" * 62)
            print(f"  Identifier: {fixture.identifier()}")

            sources = fixture.sources()
            print(f"  Sources:    {len(sources)}")

            for source_idx, source in enumerate(sources):
                print()
                print(f"  Source {source_idx + 1}")
                print("  " + "\u2500" * 60)
                print(f"    Identifier: {source.identifier()}")
                print(f"    Emitters:   {len(source.emitters())}")


def cmd_monitor(args):
    enody.init_logging()

    env = enody.UsbEnvironment()
    runtimes = env.runtimes()

    if not runtimes:
        print("No Enody devices found.")
        return

    print(f"Monitoring {len(runtimes)} device(s). Press Ctrl+C to exit.")

    for runtime in runtimes:
        runtime.enable_logging()

    try:
        signal.pause()
    except KeyboardInterrupt:
        pass

    print("\nShutting down...")


def cmd_download_spectral_data(args):
    env = enody.UsbEnvironment()
    runtimes = env.runtimes()

    if not runtimes:
        print("No Enody devices found.")
        return

    host = runtimes[0].host()
    print(f"Host: {host.identifier()} (v{host.version()})")

    fixtures = host.fixtures()
    print(f"Fixtures: {len(fixtures)}")

    fixture_outputs = []

    for fi, fixture in enumerate(fixtures):
        print(f"  Fixture {fi}: {fixture.identifier()}")

        sources = fixture.sources()
        print(f"    Sources: {len(sources)}")

        source_outputs = []

        for si, source in enumerate(sources):
            print(f"    Source {si}: {source.identifier()}")

            emitters = source.emitters()
            print(f"      Emitters: {len(emitters)}")

            emitter_outputs = []

            for ei, emitter in enumerate(emitters):
                print(f"      Emitter {ei}: {emitter.identifier()}")

                sd = emitter.spectral_data()
                samples = sd.samples()
                print(f"        Samples: {len(samples)}")

                emitter_outputs.append({
                    "identifier": emitter.identifier(),
                    "spectral_data": [
                        {
                            "wavelength": s.wavelength,
                            "measurement": s.measurement,
                        }
                        for s in samples
                    ],
                })

            source_outputs.append({
                "identifier": source.identifier(),
                "emitters": emitter_outputs,
            })

        fixture_outputs.append({
            "identifier": fixture.identifier(),
            "sources": source_outputs,
        })

    output = {
        "host": {
            "identifier": host.identifier(),
            "version": host.version(),
        },
        "fixtures": fixture_outputs,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Spectral data written to {args.output}")


def cmd_update(args):
    targets = enody.UpdateTarget.discover()

    if not targets:
        print("No EP01 devices found.")
        return

    if len(targets) == 1:
        target = targets[0]
    else:
        print("Available devices:")
        for idx, t in enumerate(targets):
            print(f"  {idx + 1}. {t.identifier()} (version {t.version()})")

        prompt = f"Select device [1-{len(targets)}]: "
        try:
            selection = int(input(prompt))
        except (ValueError, EOFError):
            print("Invalid selection.")
            return

        if selection < 1 or selection > len(targets):
            print(f"Selection {selection} is out of range.")
            return

        target = targets[selection - 1]

    print(f"Device: {target.identifier()} (version {target.version()})")

    if args.firmware:
        print(f"Flashing local firmware image: {args.firmware}")
        target.flash_firmware_image(args.firmware)
        print("Flash complete.")
        return

    versions = target.available_firmware()
    if not versions:
        print("No firmware versions available.")
        return

    print("Available firmware versions:")
    for idx, v in enumerate(versions):
        print(f"  {idx + 1}. {v}")

    default = 1
    prompt = f"Select version [1-{len(versions)}, default: {default}]: "
    try:
        line = input(prompt).strip()
    except EOFError:
        line = ""

    if not line:
        selection = default
    else:
        try:
            selection = int(line)
        except ValueError:
            print(f"Invalid selection '{line}'.")
            return

    if selection < 1 or selection > len(versions):
        print(f"Selection {selection} is out of range.")
        return

    selected_version = versions[selection - 1]
    print(f"Updating to version {selected_version}...")
    target.update_device(selected_version)
    print("Update complete.")


def main():
    parser = argparse.ArgumentParser(
        prog="enody",
        description="Enody Host SDK CLI",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all attached Enody devices")
    subparsers.add_parser("info", help="Display detailed information about all attached devices")
    subparsers.add_parser("monitor", help="Monitor log output from all attached devices")

    dl_parser = subparsers.add_parser(
        "download-spectral-data",
        help="Download spectral data from all emitters and save as JSON",
    )
    dl_parser.add_argument(
        "-o", "--output",
        default="spectral-data.json",
        help="Output file path (default: spectral-data.json)",
    )

    update_parser = subparsers.add_parser(
        "update",
        help="Update selected device to newest firmware",
    )
    update_parser.add_argument(
        "-f", "--firmware",
        metavar="FILE",
        help="Path to an offline firmware image (.bin)",
    )

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "info": cmd_info,
        "monitor": cmd_monitor,
        "download-spectral-data": cmd_download_spectral_data,
        "update": cmd_update,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
