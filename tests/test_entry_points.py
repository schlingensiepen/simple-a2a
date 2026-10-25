"""The three modules beside the blocks do what they are documented to do.

Small, and here because each promise is written down elsewhere and a refactor can
break any of them without anything else complaining: the service refuses what it
cannot serve, the probe measures, and the helper prints the secret the service
settled — and writes nothing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from simple_a2a import __main__, first_prompt, probe
from simple_a2a.core import config
from simple_a2a.core.paths import Layout


def test_an_unusable_parameter_stops_the_start_and_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It never gets as far as serving, and it says which parameter it was.

    Non-zero matters: a platform that restarts on failure has to see a failure, not a
    process that printed something and exited happily.
    """
    monkeypatch.setenv(config.PORT, "not-a-port")

    status = __main__.main([])

    assert status == 2
    assert config.PORT in capsys.readouterr().err


def test_with_every_surface_off_it_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    """A process serving nothing is not a running service, it is a puzzle."""
    for name in (config.PORT, config.ADMIN_PORT, config.OBSERVER_PORT):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv(config.DATA_DIR, str(tmp_path / "data"))

    status = __main__.main([])

    assert status == 2
    assert "switched off" in capsys.readouterr().err


def test_a_surface_with_no_port_is_not_built_at_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Not built rather than built and unreachable: an application that answers
    nowhere is a thing to wonder about later."""
    monkeypatch.setenv(config.ADMIN_PORT, "")
    monkeypatch.setenv(config.DATA_DIR, str(tmp_path / "data"))
    resolved = config.load()
    context, _ = __main__.make_context(resolved)

    running = __main__.servers(context, resolved)

    assert [server.config.port for server in running] == [8251, 8253]


def test_the_build_stamp_is_in_its_own_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SIMPLE_A2A_*` belongs to the eight operational parameters, and this is not one."""
    monkeypatch.setenv(__main__.BUILD_VARIABLE, "abc123")

    stamp = __main__.build_stamp()

    assert stamp["build_id"] == "abc123"
    assert set(stamp) == {"version", "build_id", "built_at"}
    assert not __main__.BUILD_VARIABLE.startswith(config.PREFIX)


def test_a_build_that_did_not_say_when_says_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not the start time: a restart is not a build, and the field says "built"."""
    monkeypatch.delenv(f"{__main__.BUILD_VARIABLE}_AT", raising=False)
    assert __main__.build_stamp()["built_at"] is None

    monkeypatch.setenv(f"{__main__.BUILD_VARIABLE}_AT", "2026-09-28T12:00:00Z")
    assert __main__.build_stamp()["built_at"] == "2026-09-28T12:00:00Z"


def test_an_unknown_build_says_so_rather_than_inventing_one() -> None:
    stamp = __main__.build_stamp()

    assert stamp["build_id"] == "unknown"


def test_the_probe_asks_every_surface_that_is_on() -> None:
    assert probe.ports_of(config.load({})) == [8251, 8252, 8253]
    assert probe.ports_of(config.load({config.PORT: ""})) == [8252, 8253]
    assert probe.ports_of(config.load({config.ADMIN_PORT: "9000"})) == [8251, 9000, 8253]


def test_a_port_nobody_is_serving_does_not_answer() -> None:
    """The check has to be a measurement; an optimistic probe is no probe."""
    assert not probe.answers(1)


def test_with_every_surface_off_the_probe_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A container serving nothing is not healthy, it is pointless."""
    for name in (config.PORT, config.ADMIN_PORT, config.OBSERVER_PORT):
        monkeypatch.setenv(name, "")

    assert probe.main() == 1
    assert "switched off" in capsys.readouterr().err


def test_a_configuration_the_service_could_not_start_with_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unhealthy is the honest answer, not an error about the answer."""
    monkeypatch.setenv(config.PORT, "not-a-port")

    assert probe.main() == 1
    assert config.PORT in capsys.readouterr().err


# --- the helper: simple-a2a first-prompt ---------------------------------------


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under the data directory with its size and its mode: what "writes
    nothing" has to mean, down to a file mode."""
    found: dict[str, tuple[int, int]] = {}
    for path in sorted(root.rglob("*")):
        state = path.stat()
        found[str(path.relative_to(root))] = (state.st_size, state.st_mode)
    return found


@pytest.fixture
def settled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, str]:
    """A data directory in which the service has settled a secret, as after a start."""
    monkeypatch.setenv(config.DATA_DIR, str(tmp_path / "data"))
    monkeypatch.delenv(config.ADMIN_SECRET, raising=False)
    resolved = config.load()
    _, value = __main__.make_context(resolved)
    assert value
    return resolved.data_dir, value


def test_the_first_prompt_carries_the_secret_and_the_default_address(
    settled: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Secret and address are the pair the agent needs, and the default address is
    the quick start's: the loopback address and the image's administration port."""
    _, value = settled

    status = __main__.main([first_prompt.SUBCOMMAND])

    out, err = capsys.readouterr()
    assert status == 0
    assert err == ""
    assert value in out
    assert first_prompt.DEFAULT_ADDRESS == "http://127.0.0.1:8252"
    assert f"{first_prompt.DEFAULT_ADDRESS}/guide/first-access" in out
    assert "Authorization: Bearer" in out


def test_the_first_prompt_names_the_operations_the_surface_offers(
    settled: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The prompt speaks the administration surface's own vocabulary, so that what the
    agent reads there and what it was asked for are the same thing."""
    __main__.main([first_prompt.SUBCOMMAND])
    out = capsys.readouterr().out

    for term in (
        "realm",
        "team",
        "invitation",
        "realm master",
        "/realms",
        "/teams",
        "/invitations",
    ):
        assert term in out, term


def test_the_address_can_be_overridden(
    settled: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The host port may differ from the container's, and only the operator knows it.
    A trailing slash is dropped so the appended paths read as the guide writes them."""
    _, value = settled

    status = __main__.main([first_prompt.SUBCOMMAND, "http://127.0.0.1:18252/"])

    out = capsys.readouterr().out
    assert status == 0
    assert value in out
    assert "http://127.0.0.1:18252/guide/first-access" in out
    assert "http://127.0.0.1:18252//" not in out
    assert first_prompt.DEFAULT_ADDRESS not in out


def test_an_address_that_is_not_one_is_refused(
    settled: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """A bare host and port would make the agent guess the scheme, and a guess is the
    one thing the pair of address and secret cannot survive."""
    _, value = settled

    for given in (["127.0.0.1:18252"], ["http://"], ["http://a:1", "http://b:2"]):
        status = __main__.main([first_prompt.SUBCOMMAND, *given])
        out, err = capsys.readouterr()
        assert status == 2, given
        assert out == ""
        assert value not in err
        assert first_prompt.SUBCOMMAND in err


def test_without_a_secret_it_says_so_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No secret has been settled: nothing is invented, and the message says what to do."""
    data = tmp_path / "data"
    monkeypatch.setenv(config.DATA_DIR, str(data))
    monkeypatch.delenv(config.ADMIN_SECRET, raising=False)

    status = __main__.main([first_prompt.SUBCOMMAND])

    out, err = capsys.readouterr()
    assert status != 0
    assert out == ""
    assert "no administration secret yet" in err
    assert not data.exists(), "the helper made the data directory; it writes nothing"


def test_with_administration_off_there_is_no_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Off means off: no surface, no secret, and so no prompt — even with the variable set."""
    monkeypatch.setenv(config.DATA_DIR, str(tmp_path / "data"))
    monkeypatch.setenv(config.ADMIN_PORT, "")
    monkeypatch.setenv(config.ADMIN_SECRET, "s" * 40)

    status = __main__.main([first_prompt.SUBCOMMAND])

    out, err = capsys.readouterr()
    assert status != 0
    assert out == ""
    assert "switched off" in err
    assert "s" * 40 not in err


def test_the_helper_writes_nothing(
    settled: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not a file, not a mode. Two processes that could settle the secret would be two
    writers on one file; a wide mode is the service's to narrow, at its start."""
    data, _ = settled
    secret_file = Layout(root=data).admin_secret
    os.chmod(secret_file, 0o644)
    before = snapshot(data)

    assert __main__.main([first_prompt.SUBCOMMAND]) == 0
    capsys.readouterr()

    assert snapshot(data) == before


def test_the_environment_wins_in_the_helper_as_at_the_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same resolution as the service's, so the prompt names the secret in force."""
    data = tmp_path / "data"
    monkeypatch.setenv(config.DATA_DIR, str(data))
    data.mkdir()
    Layout(root=data).admin_secret.write_text("f" * 40, encoding="utf-8")
    monkeypatch.setenv(config.ADMIN_SECRET, "e" * 40)

    assert __main__.main([first_prompt.SUBCOMMAND]) == 0

    out = capsys.readouterr().out
    assert "e" * 40 in out
    assert "f" * 40 not in out


def test_a_bare_start_is_still_a_bare_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The console script calls `main()` with nothing, and reads the process's own
    arguments: a bare `simple-a2a` — the image's entry point — has to reach the
    configuration and stop on an unusable value, not be refused as "arguments". An
    off-by-one on `sys.argv` would make every container start exit 2, and a suite
    that only ever passed lists would stay green."""
    monkeypatch.setattr(sys, "argv", ["simple-a2a"])
    monkeypatch.setenv(config.PORT, "not-a-port")

    assert __main__.main() == 2
    err = capsys.readouterr().err
    assert config.PORT in err
    assert "takes no arguments" not in err


def test_the_console_script_dispatches_the_helper_from_the_process_arguments(
    settled: tuple[Path, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`podman exec simple-a2a simple-a2a first-prompt ADDRESS` arrives as `sys.argv`."""
    _, value = settled
    monkeypatch.setattr(
        sys, "argv", ["simple-a2a", first_prompt.SUBCOMMAND, "http://127.0.0.1:18252"]
    )

    assert __main__.main() == 0
    out = capsys.readouterr().out
    assert value in out
    assert "http://127.0.0.1:18252/" in out


def test_anything_else_on_the_command_line_is_refused_rather_than_served(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A misspelt helper that quietly started a second service would be a puzzle."""
    monkeypatch.setenv(config.DATA_DIR, str(tmp_path / "data"))

    status = __main__.main(["first-promt"])

    out, err = capsys.readouterr()
    assert status == 2
    assert out == ""
    assert first_prompt.SUBCOMMAND in err
    assert not (tmp_path / "data").exists()
