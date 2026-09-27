"""The two modules beside the blocks do what they are documented to do.

Small, and here because both promises are written down elsewhere and a refactor
can break either without anything else complaining.
"""

from __future__ import annotations

import pytest

from simple_a2a import __main__, probe
from simple_a2a.core import config


def test_starting_the_service_says_it_is_not_built_and_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Documented as the current behaviour, so it is checked rather than assumed.

    Non-zero matters: a platform that restarts on failure must see a failure, not
    a process that printed something and exited happily.
    """
    status = __main__.main()

    assert status != 0
    assert "not built yet" in capsys.readouterr().err


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
