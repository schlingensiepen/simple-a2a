"""Every parameter: its default, and what an unusable value does.

The table is the point. Eight parameters, and for each one the default has to be
usable with nothing set — that is what makes a bare start work — and a bad value
has to stop the start with a message that names the parameter. Both halves are
checked here for all eight, because the failure mode of the second half is a
service that comes up with half its configuration understood.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from simple_a2a.core import config


def test_nothing_set_gives_a_working_service() -> None:
    """A bare start is the case that has to work; there is no mandatory setting."""
    resolved = config.load({})

    assert resolved.bind == config.BIND_DEFAULT
    assert resolved.port == 8251
    assert resolved.admin_port == 8252
    assert resolved.observer_port == 8253
    assert resolved.administration_is_on
    assert resolved.admin_secret is None
    assert not resolved.regenerate_admin_secret
    assert resolved.body_max_bytes == 1_048_576
    assert resolved.file_max_bytes == 52_428_800
    assert resolved.data_dir.is_absolute()


def test_there_are_eight_parameters_and_no_ninth() -> None:
    """The number is written down as a defence against its growth.

    A ninth name would be a decision, and a decision leaves a trace elsewhere.
    Arriving silently is the thing this prevents.
    """
    assert len(config.PARAMETERS) == 8
    assert len(set(config.PARAMETERS)) == 8
    assert all(name.startswith(config.PREFIX) for name in config.PARAMETERS)


@pytest.mark.parametrize(
    "name",
    [config.PORT, config.ADMIN_PORT, config.OBSERVER_PORT],
)
def test_emptying_a_port_switches_that_surface_off(name: str) -> None:
    """The one way to switch something off, and it is the intervention."""
    resolved = config.load({name: ""})

    off = {
        config.PORT: "port",
        config.ADMIN_PORT: "admin_port",
        config.OBSERVER_PORT: "observer_port",
    }
    assert getattr(resolved, off[name]) is None
    still_on = [getattr(resolved, field) for key, field in off.items() if key != name]
    assert all(port is not None for port in still_on)


@pytest.mark.parametrize(
    "name",
    [config.PORT, config.ADMIN_PORT, config.OBSERVER_PORT],
)
@pytest.mark.parametrize("value", ["notaport", "0", "65536", "-1", "8251.5", "8 251"])
def test_an_unusable_port_stops_the_start_and_names_the_parameter(name: str, value: str) -> None:
    with pytest.raises(config.ConfigError) as raised:
        config.load({name: value})

    assert raised.value.parameter == name
    assert name in str(raised.value)


def test_two_surfaces_on_one_port_stops_the_start_and_names_both() -> None:
    """Left to the operating system this names neither parameter."""
    with pytest.raises(config.ConfigError) as raised:
        config.load({config.ADMIN_PORT: "8251"})

    assert raised.value.parameter == config.ADMIN_PORT
    assert config.PORT in str(raised.value)


@pytest.mark.parametrize("name", [config.BODY_MAX_BYTES, config.FILE_MAX_BYTES])
@pytest.mark.parametrize("value", ["1MiB", "0", "-5", "one", "1 048 576"])
def test_an_unusable_limit_stops_the_start_and_names_the_parameter(name: str, value: str) -> None:
    with pytest.raises(config.ConfigError) as raised:
        config.load({name: value})

    assert raised.value.parameter == name


@pytest.mark.parametrize("name", [config.BODY_MAX_BYTES, config.FILE_MAX_BYTES])
def test_a_limit_is_a_plain_byte_count(name: str) -> None:
    """The value is bytes, with no unit — the measure is named in MiB elsewhere."""
    resolved = config.load({name: "4096"})

    assert getattr(resolved, name.removeprefix(config.PREFIX).lower()) == 4096


def test_the_binding_is_taken_as_given_and_an_empty_one_falls_back() -> None:
    """Emptying the binding is not a way to switch anything off."""
    assert config.load({config.BIND: "0.0.0.0"}).bind == "0.0.0.0"
    assert config.load({config.BIND: "  "}).bind == config.BIND_DEFAULT


def test_the_data_directory_is_taken_as_given_and_expanded(tmp_path: Path) -> None:
    resolved = config.load({config.DATA_DIR: str(tmp_path / "holdings")})

    assert resolved.data_dir == tmp_path / "holdings"


def test_a_secret_shorter_than_the_minimum_stops_the_start() -> None:
    """Thirty-two characters, and the message says both ways out."""
    with pytest.raises(config.ConfigError) as raised:
        config.load({config.ADMIN_SECRET: "too-short"})

    message = str(raised.value)
    assert raised.value.parameter == config.ADMIN_SECRET
    assert "9" in message and "32" in message
    assert config.REGENERATE in message


def test_a_secret_of_the_right_length_is_taken() -> None:
    value = "x" * 32
    assert config.load({config.ADMIN_SECRET: value}).admin_secret == value


def test_the_value_new_asks_for_a_new_one_over_the_same_name() -> None:
    """There is no ninth parameter for this."""
    resolved = config.load({config.ADMIN_SECRET: config.REGENERATE})

    assert resolved.regenerate_admin_secret
    assert resolved.admin_secret is None


def test_with_administration_off_the_secret_is_not_looked_at_at_all() -> None:
    """Stage 0: no port, no secret, no generation — even with the variable set.

    Including an unusable one: a bad value behind a closed door is not a reason
    to refuse to start.
    """
    resolved = config.load({config.ADMIN_PORT: "", config.ADMIN_SECRET: "far-too-short"})

    assert not resolved.administration_is_on
    assert resolved.admin_secret is None
    assert not resolved.regenerate_admin_secret
