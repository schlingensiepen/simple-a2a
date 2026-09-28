"""The two modules beside the blocks do what they are documented to do.

Small, and here because both promises are written down elsewhere and a refactor
can break either without anything else complaining.
"""

from __future__ import annotations

import pytest

from simple_a2a import __main__, probe
from simple_a2a.core import config


def test_an_unusable_parameter_stops_the_start_and_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It never gets as far as serving, and it says which parameter it was.

    Non-zero matters: a platform that restarts on failure has to see a failure, not a
    process that printed something and exited happily.
    """
    monkeypatch.setenv(config.PORT, "not-a-port")

    status = __main__.main()

    assert status == 2
    assert config.PORT in capsys.readouterr().err


def test_with_every_surface_off_it_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    """A process serving nothing is not a running service, it is a puzzle."""
    for name in (config.PORT, config.ADMIN_PORT, config.OBSERVER_PORT):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv(config.DATA_DIR, str(tmp_path / "data"))

    status = __main__.main()

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
