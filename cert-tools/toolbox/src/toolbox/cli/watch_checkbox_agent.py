import json
import sys
import time
from argparse import ArgumentParser, ArgumentTypeError

from paramiko.ssh_exception import SSHException
from toolbox.devices import LocalHost
from toolbox.devices.lab import LabDevice

SERVICE = "snap.checkbox.agent.service"
JOURNALCTL = (
    f"journalctl -u {SERVICE} -n 1 --output=json --no-pager"
)
SSH_FAILURE_MARKERS = (
    "SSHException",
    "NoValidConnectionsError",
    "AuthenticationException",
    "socket.gaierror",
    "TimeoutError",
)


def parse_last_timestamp(output: str) -> float | None:
    """Parse the monotonic timestamp from the last JSON journal line."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return None

    try:
        payload = json.loads(lines[-1])
        microseconds = payload["__MONOTONIC_TIMESTAMP"]
        return float(microseconds) / 1_000_000
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
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
    observed_timestamp = None
    observed_at = None

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
                observed_timestamp = last_timestamp
                observed_at = now
            elif now >= recovery_deadline:
                sys.exit(1)
            time.sleep(args.delay)
            continue

        if observed_timestamp is None or last_timestamp > observed_timestamp:
            observed_timestamp = last_timestamp
            observed_at = now
        elif observed_at is not None and now - observed_at > args.timeout:
            try:
                host.run(args.command)
            except (OSError, TimeoutError):
                sys.exit(255)
            recovery_timestamp = last_timestamp
            recovery_deadline = now + args.recovery_timeout

        time.sleep(args.delay)


if __name__ == "__main__":
    main()
