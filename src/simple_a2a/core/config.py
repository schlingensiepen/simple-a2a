"""The operational parameters: eight of them, one source, two levels.

Environment variable over default, and that is the whole precedence. There is no
configuration file and there are no flags, so a message about a bad value does
not have to say *where* the value came from — there is only one place it can
have come from, which is the simplification that configuring nothing on the
command line buys. (The one helper, `simple-a2a first-prompt`, takes an address
as its argument; that address is the agent's, not a parameter of the service,
and nothing here reads it.)

Every parameter has a usable default, because whoever pulls the image and runs it
gets a working service: no mandatory setting, nothing to read first. Everything
is on, and switching a surface off is the intervention — done by emptying its
port variable.

**An invalid value stops the start, and the message names the parameter.** A
service that starts with half its configuration understood is a service whose
behaviour nobody can predict from its environment; the five minutes saved are
paid back the first time somebody has to work out why administration is
unreachable.

The eight, and there are eight on purpose — the number is written down as a
defence against its growth:

    SIMPLE_A2A_BIND             the binding, all surfaces
    SIMPLE_A2A_PORT             the participant surface
    SIMPLE_A2A_ADMIN_PORT       the administration surface
    SIMPLE_A2A_OBSERVER_PORT    the observation surface
    SIMPLE_A2A_ADMIN_SECRET     the way in for the operator
    SIMPLE_A2A_DATA_DIR         where the holdings live
    SIMPLE_A2A_BODY_MAX_BYTES   the limit on a message body
    SIMPLE_A2A_FILE_MAX_BYTES   the limit on a file

There is no ninth for regenerating the secret: `SIMPLE_A2A_ADMIN_SECRET=new`
asks for that, over the same name. A second variable for the same subject is how
two names for one thing get into a system.

And there is no operation that reads these values back. What is set is in the
environment, and what is not set is the default; a second account of the
configuration drifts from the first one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from simple_a2a.core.limits import (
    ADMIN_SECRET_MIN_CHARS,
    BODY_MAX_BYTES_DEFAULT,
    FILE_MAX_BYTES_DEFAULT,
)

PREFIX = "SIMPLE_A2A_"

BIND = f"{PREFIX}BIND"
PORT = f"{PREFIX}PORT"
ADMIN_PORT = f"{PREFIX}ADMIN_PORT"
OBSERVER_PORT = f"{PREFIX}OBSERVER_PORT"
ADMIN_SECRET = f"{PREFIX}ADMIN_SECRET"
DATA_DIR = f"{PREFIX}DATA_DIR"
BODY_MAX_BYTES = f"{PREFIX}BODY_MAX_BYTES"
FILE_MAX_BYTES = f"{PREFIX}FILE_MAX_BYTES"

#: All of them, in the order of the specification. Used by the tests to check
#: that no ninth has appeared without a decision behind it.
PARAMETERS = (
    BIND,
    PORT,
    ADMIN_PORT,
    OBSERVER_PORT,
    ADMIN_SECRET,
    DATA_DIR,
    BODY_MAX_BYTES,
    FILE_MAX_BYTES,
)

BIND_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 8251
ADMIN_PORT_DEFAULT = 8252
OBSERVER_PORT_DEFAULT = 8253

#: The value that asks for a new administration secret, over the name of the
#: secret itself. It has to be removed again afterwards, or every restart mints
#: another one — which the log line says at the time.
REGENERATE = "new"

LOWEST_PORT = 1
HIGHEST_PORT = 65535


class ConfigError(Exception):
    """A value that stops the start. Carries the parameter it is about."""

    def __init__(self, parameter: str, problem: str) -> None:
        super().__init__(f"{parameter}: {problem}")
        self.parameter = parameter
        self.problem = problem


@dataclass(frozen=True)
class Config:
    """The eight values, resolved.

    A port of `None` means that surface is off — no port, and for administration
    no secret and no generation either.
    """

    bind: str
    port: int | None
    admin_port: int | None
    observer_port: int | None
    admin_secret: str | None
    regenerate_admin_secret: bool
    data_dir: Path
    body_max_bytes: int
    file_max_bytes: int

    @property
    def administration_is_on(self) -> bool:
        return self.admin_port is not None


def default_data_dir() -> Path:
    """Where the holdings live when nobody said otherwise.

    A fixed place per delivery form, and this is the one for a plain start: the
    state directory of the user running the process. Not `/var/lib/...` — that
    is the image's answer, set there as an environment variable, and a default
    the caller cannot write to would make a bare start fail, which is the one
    thing a bare start may not do.
    """
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "simple-a2a"


def _port(environment: Mapping[str, str], name: str, default: int) -> int | None:
    raw = environment.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        # Emptied on purpose: this surface is off. The one way to switch
        # something off, and it is the intervention rather than the default.
        return None
    try:
        number = int(text, 10)
    except ValueError:
        raise ConfigError(name, f"{text!r} is not a port number") from None
    if not LOWEST_PORT <= number <= HIGHEST_PORT:
        raise ConfigError(name, f"{number} is not a usable port; it has to be between 1 and 65535")
    return number


def _byte_count(environment: Mapping[str, str], name: str, default: int) -> int:
    raw = environment.get(name)
    if raw is None or not raw.strip():
        return default
    text = raw.strip()
    try:
        number = int(text, 10)
    except ValueError:
        raise ConfigError(
            name, f"{text!r} is not a number of bytes; the value is bytes, with no unit"
        ) from None
    if number < 1:
        raise ConfigError(name, f"{number} is not a usable limit; it has to be at least 1 byte")
    return number


def _admin_secret(
    environment: Mapping[str, str], *, administration_is_on: bool
) -> tuple[str | None, bool]:
    """The secret and whether a new one was asked for.

    When administration is off the secret is not looked at *at all* — not
    validated, not generated, not even read. An unusable value behind a closed
    door is not a reason to refuse to start, and a service that minted a secret
    for a surface it is not serving would be writing one to the log for nothing.
    """
    if not administration_is_on:
        return None, False
    raw = environment.get(ADMIN_SECRET)
    if raw is None:
        return None, False
    text = raw.strip()
    if not text:
        return None, False
    if text == REGENERATE:
        return None, True
    if len(text) < ADMIN_SECRET_MIN_CHARS:
        raise ConfigError(
            ADMIN_SECRET,
            f"the secret is {len(text)} characters long and has to be at least "
            f"{ADMIN_SECRET_MIN_CHARS}. Either set a long random value, or set it to "
            f"{REGENERATE!r} and restart to have one generated",
        )
    return text, False


def load(environment: Mapping[str, str] | None = None) -> Config:
    """Resolve the eight values, or raise `ConfigError` naming the parameter."""
    values = os.environ if environment is None else environment

    bind = values.get(BIND, BIND_DEFAULT).strip() or BIND_DEFAULT
    # Emptying the binding is not a way to switch anything off — a surface is
    # switched off by its own port — so an empty value falls back to the default
    # rather than producing a process that listens nowhere and says nothing.

    port = _port(values, PORT, PORT_DEFAULT)
    admin_port = _port(values, ADMIN_PORT, ADMIN_PORT_DEFAULT)
    observer_port = _port(values, OBSERVER_PORT, OBSERVER_PORT_DEFAULT)

    # Two surfaces on one port cannot both be served. Left to the operating
    # system this surfaces as an address-already-in-use error from whichever
    # surface happens to bind second, naming neither parameter; caught here it
    # names both.
    named_ports = ((PORT, port), (ADMIN_PORT, admin_port), (OBSERVER_PORT, observer_port))
    seen: dict[int, str] = {}
    for name, number in named_ports:
        if number is None:
            continue
        if number in seen:
            raise ConfigError(
                name,
                f"port {number} is already taken by {seen[number]}; each surface needs one "
                "of its own",
            )
        seen[number] = name

    secret, regenerate = _admin_secret(values, administration_is_on=admin_port is not None)

    raw_dir = values.get(DATA_DIR, "").strip()
    data_dir = Path(raw_dir).expanduser() if raw_dir else default_data_dir()

    return Config(
        bind=bind,
        port=port,
        admin_port=admin_port,
        observer_port=observer_port,
        admin_secret=secret,
        regenerate_admin_secret=regenerate,
        data_dir=data_dir,
        body_max_bytes=_byte_count(values, BODY_MAX_BYTES, BODY_MAX_BYTES_DEFAULT),
        file_max_bytes=_byte_count(values, FILE_MAX_BYTES, FILE_MAX_BYTES_DEFAULT),
    )
