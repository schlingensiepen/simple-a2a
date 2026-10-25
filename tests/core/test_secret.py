"""The four steps to the administration secret, and the one log line.

Administration is the only door in, so this is the sequence that decides whether
a freshly pulled image can be used at all. Each step is checked, and so is the
promise attached to the line: one value, one time, only on generation.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from simple_a2a.core import config, secret
from simple_a2a.core.paths import Layout


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    made = Layout(root=tmp_path / "data")
    made.prepare()
    return made


def test_with_administration_off_nothing_is_resolved_and_nothing_is_written(layout: Layout) -> None:
    resolved = secret.resolve(config.load({config.ADMIN_PORT: ""}), layout)

    assert resolved is None
    assert not layout.admin_secret.exists()


def test_the_environment_wins_and_nothing_is_stored(layout: Layout) -> None:
    value = "e" * 40
    resolved = secret.resolve(config.load({config.ADMIN_SECRET: value}), layout)

    assert resolved is not None
    assert resolved.value == value
    assert resolved.origin == secret.Origin.ENVIRONMENT
    # A secret the operator set is theirs to keep; storing a copy would put it
    # somewhere they did not put it.
    assert not layout.admin_secret.exists()


def test_a_file_is_used_when_the_environment_is_silent(layout: Layout) -> None:
    value = "f" * 40
    layout.admin_secret.write_text(value + "\n", encoding="utf-8")

    resolved = secret.resolve(config.load({}), layout)

    assert resolved is not None
    assert resolved.value == value
    assert resolved.origin == secret.Origin.FILE


def test_a_file_placed_with_wide_permissions_is_narrowed(layout: Layout) -> None:
    """Fixed silently: refusing over a mode we can repair is a setting in disguise."""
    layout.admin_secret.write_text("g" * 40, encoding="utf-8")
    os.chmod(layout.admin_secret, 0o644)

    secret.resolve(config.load({}), layout)

    mode = stat.S_IMODE(layout.admin_secret.stat().st_mode)
    assert mode == 0o600


def test_a_secret_in_the_file_is_held_to_the_same_minimum(layout: Layout) -> None:
    """Stage 2 is also the operator's choice, so it is also checked."""
    layout.admin_secret.write_text("short", encoding="utf-8")

    with pytest.raises(config.ConfigError) as raised:
        secret.resolve(config.load({}), layout)

    assert raised.value.parameter == config.ADMIN_SECRET
    assert "32" in str(raised.value)


def test_an_unreadable_file_stops_the_start(layout: Layout) -> None:
    """Coming up without a way in would look healthy and be useless."""
    layout.admin_secret.write_text("h" * 40, encoding="utf-8")
    os.chmod(layout.admin_secret, 0o000)
    try:
        if os.access(layout.admin_secret, os.R_OK):
            pytest.skip("this process can read a mode-000 file, so the case cannot be staged")
        with pytest.raises(config.ConfigError) as raised:
            secret.resolve(config.load({}), layout)
        assert raised.value.parameter == config.ADMIN_SECRET
        assert config.REGENERATE in str(raised.value)
    finally:
        os.chmod(layout.admin_secret, 0o600)


def test_with_nothing_set_one_is_generated_stored_and_logged_once(
    layout: Layout, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="simple_a2a"):
        resolved = secret.resolve(config.load({}), layout)

    assert resolved is not None
    assert resolved.origin == secret.Origin.GENERATED
    assert layout.admin_secret.read_text(encoding="utf-8").strip() == resolved.value
    assert stat.S_IMODE(layout.admin_secret.stat().st_mode) == 0o600

    lines = [record.getMessage() for record in caplog.records]
    with_secret = [line for line in lines if resolved.value in line]
    assert len(with_secret) == 1, "the secret goes into the log exactly once"
    only_line = with_secret[0]
    assert str(layout.admin_secret) in only_line, "the line says where the secret now lives"
    assert "only time" in only_line, "the line says there is no second time"
    assert config.REGENERATE in only_line, "the line says how to get a new one"
    assert caplog.records[0].levelno >= logging.WARNING


def test_a_restart_reuses_the_stored_one_and_does_not_log_again(
    layout: Layout, caplog: pytest.LogCaptureFixture
) -> None:
    first = secret.resolve(config.load({}), layout)
    assert first is not None

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="simple_a2a"):
        second = secret.resolve(config.load({}), layout)

    assert second is not None
    assert second.value == first.value
    assert second.origin == secret.Origin.FILE
    assert not [line for line in caplog.records if first.value in line.getMessage()]


def test_asking_for_a_new_one_replaces_the_stored_one(
    layout: Layout, caplog: pytest.LogCaptureFixture
) -> None:
    """The way back for an operator who missed the line and cannot read the file."""
    first = secret.resolve(config.load({}), layout)
    assert first is not None

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="simple_a2a"):
        second = secret.resolve(config.load({config.ADMIN_SECRET: config.REGENERATE}), layout)

    assert second is not None
    assert second.value != first.value
    assert second.origin == secret.Origin.GENERATED
    assert layout.admin_secret.read_text(encoding="utf-8").strip() == second.value
    assert len([line for line in caplog.records if second.value in line.getMessage()]) == 1


# --- find: the read-only half ---------------------------------------------------


def test_find_reads_the_same_places_in_the_same_order(layout: Layout) -> None:
    """Environment over file, as at the start, so that a process beside the service
    names the secret the service is using."""
    layout.admin_secret.write_text("f" * 40, encoding="utf-8")

    assert secret.find(config.load({config.ADMIN_SECRET: "e" * 40}), layout) == secret.Secret(
        value="e" * 40, origin=secret.Origin.ENVIRONMENT
    )
    assert secret.find(config.load({}), layout) == secret.Secret(
        value="f" * 40, origin=secret.Origin.FILE
    )


def test_find_never_generates_and_never_writes(layout: Layout) -> None:
    """Only the process that serves may mint a secret; a second one would mint a
    value the service never sees. Not a file, and not a mode either."""
    assert secret.find(config.load({}), layout) is None
    assert not layout.admin_secret.exists()

    layout.admin_secret.write_text("g" * 40, encoding="utf-8")
    os.chmod(layout.admin_secret, 0o644)
    found = secret.find(config.load({}), layout)

    assert found is not None and found.value == "g" * 40
    assert stat.S_IMODE(layout.admin_secret.stat().st_mode) == 0o644


def test_find_treats_the_request_for_a_new_one_as_no_secret(layout: Layout) -> None:
    """`new` is a request, not a value: the file is what counts, because the service
    has already replaced it at its start by the time anyone asks."""
    layout.admin_secret.write_text("h" * 40, encoding="utf-8")

    found = secret.find(config.load({config.ADMIN_SECRET: config.REGENERATE}), layout)

    assert found is not None and found.value == "h" * 40


def test_find_with_administration_off_finds_nothing(layout: Layout) -> None:
    layout.admin_secret.write_text("i" * 40, encoding="utf-8")

    assert secret.find(config.load({config.ADMIN_PORT: ""}), layout) is None


def test_find_holds_the_file_to_the_same_minimum(layout: Layout) -> None:
    """The same rule as at the start; a helper that accepted what the service refuses
    would name a secret the service never used."""
    layout.admin_secret.write_text("short", encoding="utf-8")

    with pytest.raises(config.ConfigError) as caught:
        secret.find(config.load({}), layout)
    assert caught.value.parameter == config.ADMIN_SECRET
