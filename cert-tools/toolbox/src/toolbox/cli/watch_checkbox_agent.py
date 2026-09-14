import sys
import time
from argparse import ArgumentParser

from toolbox.devices import LocalHost
from toolbox.devices.lab import LabDevice

SERVICE = "snap.checkbox.agent.service"
JOURNALCTL = [
    "journalctl",
    "-u",
    SERVICE,
    "-n",
    "1",
    "--output=short-unix",
    "--no-pager",
]


def parse_last_timestamp(output: str) -> float | None:
    """Parse the unix timestamp of the last short-unix journal line."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return None

    timestamp, *_ = lines[-1].split(maxsplit=1)
    try:
        return float(timestamp)
    except ValueError:
        return None


def main():
    parser = ArgumentParser(
        description="Monitor checkbox agent logs and run a command if they become stale"
    )
    parser.add_argument(
        "--timeout",
        required=True,
        type=int,
        help="Maximum allowed age (seconds) of latest checkbox agent journal entry",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=30,
        help="Delay between checks in seconds",
    )
    parser.add_argument(
        "--command",
        required=True,
        help="Command to run when the latest checkbox agent journal entry is older than --timeout",
    )
    args = parser.parse_args()

    device = LabDevice()
    host = LocalHost()

    while True:
        result = device.run(command=JOURNALCTL, hide=True)
        if result.failed:
            time.sleep(args.delay)
            continue

        last_timestamp = parse_last_timestamp(result.stdout)
        if last_timestamp is None:
            time.sleep(args.delay)
            continue

        age = time.time() - last_timestamp
        if age > args.timeout:
            command_result = host.run(args.command)
            sys.exit(command_result.exited)

        time.sleep(args.delay)


if __name__ == "__main__":
    main()
