import argparse
import getpass
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
    import os
    if os.path.exists(args.output):
        print(f"Error: Output file already exists: {args.output}", file=sys.stderr)
        sys.exit(1)

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

    # Warn about unresponsive devices (nil UUID means HostInfo query failed)
    nil_uuid = "00000000-0000-0000-0000-000000000000"
    unresponsive = [t for t in targets if t.identifier() == nil_uuid]

    if unresponsive and not args.force:
        print("Warning: The following device(s) did not respond to host identification:")
        for t in unresponsive:
            mac = t.mac_address() or "unknown"
            print(f"  - MAC address: {mac}")
        print("Verify only EP01 devices are attached to this computer before force updating.")
        try:
            answer = input("Continue? [y/N]: ").strip()
        except EOFError:
            answer = ""
        if answer.lower() != "y":
            print("Update aborted.")
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


def _first_usb_runtime():
    env = enody.UsbEnvironment()
    runtimes = env.runtimes()
    if not runtimes:
        raise RuntimeError("No Enody devices found over USB.")
    return env, runtimes[0]


def _print_wifi_networks(networks):
    if not networks:
        print("No WiFi networks found.")
        return

    print("WiFi networks:")
    for idx, network in enumerate(networks):
        ssid = network.ssid() or "<hidden>"
        rssi = network.rssi() if network.rssi() is not None else "-"
        channel = network.channel() if network.channel() is not None else "-"
        auth = network.auth() or "unknown"
        print(f"  {idx + 1:>2}. {ssid:<32} rssi={rssi!s:>4} channel={channel!s:<2} auth={auth}")


def _select_wifi_ssid(networks):
    _print_wifi_networks(networks)
    if not networks:
        return _prompt_manual_ssid()

    while True:
        line = input("Pick a network number (Enter to type SSID): ").strip()
        if not line:
            return _prompt_manual_ssid()
        try:
            selected = int(line)
        except ValueError:
            print(f"Enter a number from 1 to {len(networks)} or press Enter to type an SSID.")
            continue
        if selected < 1 or selected > len(networks):
            print(f"Enter a number from 1 to {len(networks)} or press Enter to type an SSID.")
            continue

        ssid = networks[selected - 1].ssid()
        if ssid:
            return ssid
        print("Selected network has a hidden SSID.")
        return _prompt_manual_ssid()


def _prompt_manual_ssid():
    while True:
        ssid = input("SSID: ").strip()
        if ssid:
            return ssid
        print("SSID cannot be empty.")


def _select_wifi_device(devices):
    if not devices:
        raise RuntimeError("No EP01 devices found for WiFi token generation.")
    if len(devices) == 1:
        return devices[0]

    print("Available EP01s:")
    for idx, device in enumerate(devices):
        host_id = device.host_id() or "unknown"
        endpoint = device.endpoint() or "unknown"
        firmware = device.firmware_version() or "unknown firmware"
        print(f"  {idx + 1:>2}. host={host_id} endpoint={endpoint} firmware={firmware}")

    while True:
        line = input(f"Pick an EP01 number [1-{len(devices)}]: ").strip()
        try:
            selected = int(line)
        except ValueError:
            print(f"Enter a number from 1 to {len(devices)}.")
            continue
        if 1 <= selected <= len(devices):
            return devices[selected - 1]
        print(f"Enter a number from 1 to {len(devices)}.")


def cmd_wifi_scan(args):
    _, runtime = _first_usb_runtime()
    networks = runtime.host().wifi_scan()
    _print_wifi_networks(networks)


def cmd_wifi_join(args):
    _, runtime = _first_usb_runtime()
    password = args.password
    if password is None:
        password = getpass.getpass("Password (leave empty for open network): ")
    print(f"Joining WiFi network {args.ssid!r}...")
    runtime.host().wifi_join(args.ssid, password)
    print(f"Joined WiFi network {args.ssid!r}.")


def cmd_wifi_setup(args):
    _, runtime = _first_usb_runtime()
    host = runtime.host()

    print("Scanning for WiFi networks...")
    networks = host.wifi_scan()
    ssid = args.ssid or _select_wifi_ssid(networks)
    password = args.password
    if password is None:
        password = getpass.getpass("Password (leave empty for open network): ")

    print(f"Joining WiFi network {ssid!r}...")
    host.wifi_join(ssid, password)
    print(f"Joined WiFi network {ssid!r}.")

    print("Generating USB-authenticated WiFi token...")
    token = runtime.generate_token()
    path = enody.TokenStore.save_token(token)
    print(f"Saved token for host {token.host_id()} to {path}.")


def cmd_wifi_generate_token(args):
    def on_approval(instruction):
        print(f"Approval required: {instruction}")

    if args.endpoint:
        print(f"Generating WiFi token from {args.endpoint}.")
        token = enody.generate_wifi_token(
            endpoint=args.endpoint,
            on_approval=on_approval,
            verify_attempts=args.verify_attempts,
            verify_retry_ms=args.verify_retry_ms,
            save=False,
        )
    else:
        print("Searching for EP01s over mDNS...")
        devices = enody.WifiConnection.discover_token_generation_devices(args.timeout_ms)
        device = _select_wifi_device(devices)
        print(f"Generating WiFi token from {device.endpoint()}.")
        token = enody.generate_wifi_token(
            device=device,
            on_approval=on_approval,
            verify_attempts=args.verify_attempts,
            verify_retry_ms=args.verify_retry_ms,
            save=False,
        )

    print(f"Verified WiFi token for host {token.host_id()}.")
    if args.no_save:
        print("Token was not saved.")
        return

    if args.token_store:
        store = enody.TokenStore.load_from_path(args.token_store)
        store.upsert(token)
        store.save_to_path(args.token_store)
        print(f"Saved token to {args.token_store}.")
    else:
        path = enody.TokenStore.save_token(token)
        print(f"Saved token to {path}.")


def main():
    parser = argparse.ArgumentParser(
        prog="enody",
        description="Enody Host SDK CLI",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all attached Enody devices")
    subparsers.add_parser("info", help="Display detailed information about all attached devices")
    subparsers.add_parser("monitor", help="Monitor log output from all attached devices")

    subparsers.add_parser("wifi-scan", help="Scan WiFi networks using the first USB device")

    wifi_join_parser = subparsers.add_parser(
        "wifi-join",
        help="Join a WiFi network using the first USB device",
    )
    wifi_join_parser.add_argument("ssid", help="WiFi SSID")
    wifi_join_parser.add_argument(
        "-p",
        "--password",
        help="WiFi password. Omit to prompt securely; use an empty string for open networks.",
    )

    wifi_setup_parser = subparsers.add_parser(
        "wifi-setup",
        help="Scan, join WiFi, and save a USB-authenticated token",
    )
    wifi_setup_parser.add_argument("--ssid", help="WiFi SSID. Omit to pick from scan results.")
    wifi_setup_parser.add_argument(
        "-p",
        "--password",
        help="WiFi password. Omit to prompt securely; use an empty string for open networks.",
    )

    wifi_token_parser = subparsers.add_parser(
        "wifi-generate-token",
        help="Generate and verify a WiFi token with device approval",
    )
    wifi_token_parser.add_argument(
        "--endpoint",
        help="Device endpoint as host:port. Omit to discover EP01 devices over mDNS.",
    )
    wifi_token_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=800,
        help="mDNS discovery timeout in milliseconds (default: 800)",
    )
    wifi_token_parser.add_argument(
        "--verify-attempts",
        type=int,
        default=8,
        help="WiFi token verification attempts (default: 8)",
    )
    wifi_token_parser.add_argument(
        "--verify-retry-ms",
        type=int,
        default=500,
        help="Delay between token verification attempts in milliseconds (default: 500)",
    )
    wifi_token_parser.add_argument(
        "--token-store",
        help="Token store path. Defaults to the standard Enody token store.",
    )
    wifi_token_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print verification result without saving the generated token.",
    )

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
    update_parser.add_argument(
        "--force", action="store_true",
        help="Force update even if device does not respond to host identification",
    )

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "info": cmd_info,
        "monitor": cmd_monitor,
        "wifi-scan": cmd_wifi_scan,
        "wifi-join": cmd_wifi_join,
        "wifi-setup": cmd_wifi_setup,
        "wifi-generate-token": cmd_wifi_generate_token,
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
