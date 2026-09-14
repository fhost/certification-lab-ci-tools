import pytest
from invoke import Result

from toolbox.cli import watch_checkbox_agent


def test_parse_last_timestamp_success():
    output = "1726317513.470225 host snap.checkbox.agent[100]: ping\n"
    assert watch_checkbox_agent.parse_last_timestamp(output) == 1726317513.470225


def test_parse_last_timestamp_invalid_returns_none():
    assert watch_checkbox_agent.parse_last_timestamp("not-a-timestamp entry\n") is None


def test_main_runs_command_when_timestamp_is_stale(mocker):
    device = mocker.Mock()
    device.run.return_value = Result(
        stdout="100.0 host snap.checkbox.agent[100]: ping\n", exited=0
    )
    host = mocker.Mock()
    host.run.return_value = Result(exited=7)

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
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        watch_checkbox_agent.main()

    assert exc_info.value.code == 7
    host.run.assert_called_once_with("echo recover")


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
            "--command",
            "echo recover",
        ],
    )

    with pytest.raises(RuntimeError, match="stop"):
        watch_checkbox_agent.main()

    assert device.run.call_count == 2
    host.run.assert_not_called()
