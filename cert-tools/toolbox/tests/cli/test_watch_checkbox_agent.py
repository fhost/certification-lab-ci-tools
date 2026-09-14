import pytest
from invoke import Result

from toolbox.cli import watch_checkbox_agent


def test_parse_last_timestamp_success():
    output = "1726317513.470225 host snap.checkbox.agent[100]: ping\n"
    assert watch_checkbox_agent.parse_last_timestamp(output) == 1726317513.470225


def test_parse_last_timestamp_invalid_returns_none():
    assert watch_checkbox_agent.parse_last_timestamp("not-a-timestamp entry\n") is None


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_non_positive(value):
    with pytest.raises(Exception):
        watch_checkbox_agent.positive_int(value)


@pytest.mark.parametrize(
    ("exited", "stderr", "expected"),
    [
        (255, "SSHException('no route')", True),
        (255, "NoValidConnectionsError()", True),
        (255, "some other error", False),
        (1, "SSHException('no route')", False),
    ],
)
def test_is_ssh_failure(exited, stderr, expected):
    assert watch_checkbox_agent.is_ssh_failure(exited, stderr) is expected


def test_main_runs_command_when_timestamp_is_stale_and_exits_recovery_on_new_timestamp(
    mocker,
):
    device = mocker.Mock()
    device.run.side_effect = [
        Result(stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0),
        Result(stdout="130.0 host snap.checkbox.agent[100]: ping\n", exited=0),
    ]
    host = mocker.Mock()
    host.run.return_value = Result(exited=7)

    mocker.patch.object(watch_checkbox_agent, "LabDevice", return_value=device)
    mocker.patch.object(watch_checkbox_agent, "LocalHost", return_value=host)
    mocker.patch.object(watch_checkbox_agent.time, "time", side_effect=[170.0, 171.0])
    mocker.patch.object(
        watch_checkbox_agent.time,
        "sleep",
        side_effect=[None, RuntimeError("stop")],
    )
    mocker.patch.object(
        watch_checkbox_agent.sys,
        "argv",
        [
            "watch-checkbox-agent",
            "--timeout",
            "60",
            "--delay",
            "1",
            "--recovery-timeout",
            "20",
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(RuntimeError, match="stop"):
        watch_checkbox_agent.main()

    host.run.assert_called_once_with("echo recover")
    assert device.run.call_count == 2


def test_main_retries_on_ssh_failure(mocker):
    device = mocker.Mock()
    device.run.side_effect = [
        Result(stderr="SSHException('no route')", exited=255),
        Result(stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0),
    ]
    host = mocker.Mock()

    mocker.patch.object(watch_checkbox_agent, "LabDevice", return_value=device)
    mocker.patch.object(watch_checkbox_agent, "LocalHost", return_value=host)
    mocker.patch.object(watch_checkbox_agent.time, "time", return_value=120.0)
    mocker.patch.object(
        watch_checkbox_agent.time,
        "sleep",
        side_effect=[None, RuntimeError("stop")],
    )
    mocker.patch.object(
        watch_checkbox_agent.sys,
        "argv",
        [
            "watch-checkbox-agent",
            "--timeout",
            "60",
            "--delay",
            "1",
            "--recovery-timeout",
            "20",
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(RuntimeError, match="stop"):
        watch_checkbox_agent.main()

    assert device.run.call_count == 2
    host.run.assert_not_called()


def test_main_exits_on_non_ssh_journalctl_failure(mocker):
    device = mocker.Mock()
    device.run.return_value = Result(stderr="permission denied", exited=23)
    host = mocker.Mock()

    mocker.patch.object(watch_checkbox_agent, "LabDevice", return_value=device)
    mocker.patch.object(watch_checkbox_agent, "LocalHost", return_value=host)
    mocker.patch.object(
        watch_checkbox_agent.sys,
        "argv",
        [
            "watch-checkbox-agent",
            "--timeout",
            "60",
            "--delay",
            "1",
            "--recovery-timeout",
            "20",
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        watch_checkbox_agent.main()

    assert exc_info.value.code == 23
    host.run.assert_not_called()


def test_main_retries_on_ssh_exception(mocker):
    device = mocker.Mock()
    device.run.side_effect = [
        OSError("network down"),
        Result(stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0),
    ]
    host = mocker.Mock()

    mocker.patch.object(watch_checkbox_agent, "LabDevice", return_value=device)
    mocker.patch.object(watch_checkbox_agent, "LocalHost", return_value=host)
    mocker.patch.object(watch_checkbox_agent.time, "time", return_value=120.0)
    mocker.patch.object(
        watch_checkbox_agent.time,
        "sleep",
        side_effect=[None, RuntimeError("stop")],
    )
    mocker.patch.object(
        watch_checkbox_agent.sys,
        "argv",
        [
            "watch-checkbox-agent",
            "--timeout",
            "60",
            "--delay",
            "1",
            "--recovery-timeout",
            "20",
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(RuntimeError, match="stop"):
        watch_checkbox_agent.main()

    assert device.run.call_count == 2
    host.run.assert_not_called()


def test_main_exits_on_recovery_command_exception(mocker):
    device = mocker.Mock()
    device.run.return_value = Result(
        stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0
    )
    host = mocker.Mock()
    host.run.side_effect = OSError("local command failed")

    mocker.patch.object(watch_checkbox_agent, "LabDevice", return_value=device)
    mocker.patch.object(watch_checkbox_agent, "LocalHost", return_value=host)
    mocker.patch.object(watch_checkbox_agent.time, "time", return_value=170.0)
    mocker.patch.object(
        watch_checkbox_agent.sys,
        "argv",
        [
            "watch-checkbox-agent",
            "--timeout",
            "60",
            "--delay",
            "1",
            "--recovery-timeout",
            "20",
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        watch_checkbox_agent.main()

    assert exc_info.value.code == 255


def test_main_exits_when_no_new_timestamp_during_recovery(mocker):
    device = mocker.Mock()
    device.run.side_effect = [
        Result(stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0),
        Result(stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0),
    ]
    host = mocker.Mock()
    host.run.return_value = Result(exited=0)

    mocker.patch.object(watch_checkbox_agent, "LabDevice", return_value=device)
    mocker.patch.object(watch_checkbox_agent, "LocalHost", return_value=host)
    mocker.patch.object(watch_checkbox_agent.time, "time", side_effect=[170.0, 176.0])
    mocker.patch.object(watch_checkbox_agent.sys, "argv", [
        "watch-checkbox-agent",
        "--timeout",
        "60",
        "--delay",
        "1",
        "--recovery-timeout",
        "5",
        "--command",
        "echo recover",
    ])

    with pytest.raises(SystemExit) as exc_info:
        watch_checkbox_agent.main()

    assert exc_info.value.code == 1
    host.run.assert_called_once_with("echo recover")
