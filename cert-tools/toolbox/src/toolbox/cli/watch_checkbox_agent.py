import sys
import time
from argparse import ArgumentParser, ArgumentTypeError

from paramiko.ssh_exception import SSHException
from toolbox.devices import LocalHost
from toolbox.devices.lab import LabDevice

SERVICE = "snap.checkbox.agent.service"
JOURNALCTL = (
    f"journalctl -u {SERVICE} -n 1 --output=short-unix --no-pager"
)
SSH_FAILURE_MARKERS = (
    "SSHException",
    "NoValidConnectionsError",
    "AuthenticationException",
    "socket.gaierror",
    "TimeoutError",
)


def parse_last_timestamp(output: str) -> float | None:
    """Parse the unix timestamp of the last short-unix journal line."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return None

    try:
        timestamp = lines[-1].split(maxsplit=1)[0]
        return float(timestamp)
    except (IndexError, ValueError):
        return None


def is_ssh_failure(exit_code: int, stderr: str) -> bool:
    """Return whether a failed command likely failed at SSH transport level."""
    return exit_code == 255 and any(
        marker in stderr for marker in SSH_FAILURE_MARKERS
    )


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ArgumentTypeError("must be a positive integer")
    return parsed


def main():
    parser = ArgumentParser(
        description="Monitor checkbox agent logs and run a command if they become stale"
    )
    parser.add_argument(
        "--timeout",
        required=True,
        type=positive_int,
        help="Maximum allowed age (seconds) of latest checkbox agent journal entry",
    )
    parser.add_argument(
        "--delay",
        type=positive_int,
        default=30,
        help="Delay between checks in seconds",
    )
    parser.add_argument(
        "--command",
        required=True,
        help="Command to run when the latest checkbox agent journal entry is older than --timeout",
    )
    parser.add_argument(
        "--recovery-timeout",
        type=positive_int,
        default=300,
        help=(
            "After running --command, maximum time in seconds allowed to observe a "
            "newer checkbox journal timestamp before exiting"
        ),
    )
    args = parser.parse_args()

    device = LabDevice()
    host = LocalHost()
    recovery_timestamp = None
    recovery_deadline = None

    while True:
        try:
            result = device.run(JOURNALCTL, hide=True)
        except (OSError, SSHException, TimeoutError):
            if recovery_deadline is not None and time.time() >= recovery_deadline:
                sys.exit(1)
            time.sleep(args.delay)
            continue
        if result.failed:
            if is_ssh_failure(result.exited, result.stderr):
                if recovery_deadline is not None and time.time() >= recovery_deadline:
                    sys.exit(1)
                time.sleep(args.delay)
                continue
            sys.exit(result.exited)

        last_timestamp = parse_last_timestamp(result.stdout)
        now = time.time()
        if last_timestamp is None:
            if recovery_deadline is not None and now >= recovery_deadline:
                sys.exit(1)
            time.sleep(args.delay)
            continue

        if recovery_deadline is not None:
            if last_timestamp > recovery_timestamp:
                recovery_timestamp = None
                recovery_deadline = None
            elif now >= recovery_deadline:
                sys.exit(1)
            time.sleep(args.delay)
            continue

        age = now - last_timestamp
        if age > args.timeout:
            try:
                host.run(args.command)
            except (OSError, TimeoutError):
                sys.exit(255)
            recovery_timestamp = last_timestamp
            recovery_deadline = now + args.recovery_timeout

        time.sleep(args.delay)


if __name__ == "__main__":
    main()
