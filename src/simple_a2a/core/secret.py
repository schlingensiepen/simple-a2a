"""The administration secret: where it comes from, in this order.

Administration is the only door in, so the way this resolves decides whether a
freshly pulled image is usable at all. Four steps, and the first one is a refusal:

0. **The administration port is empty** — then there is no port, no secret, and
   no generation either, even if the variable is set. Off means off.
1. **The environment variable.** The operator chose it.
2. **A file in the data directory**, readable by its owner only. Also the
   operator's choice, and the place a generated one is kept.
3. **Otherwise the service generates one**, stores it, and writes it to the log
   exactly once, saying where it now lives and that there is no second time.

That log line is the one deliberate exception to keeping secrets out of logs, and
the reason is that at that moment nothing else is inside: only the service can
mint the first secret, and its only channel outwards is the log. So: one value,
one time, only on generation. Never for a secret the operator set, never on a
restart, never for a way into the service's actual function. It goes out at
warning level so that it is not lost in ordinary startup chatter.

Asking for a new one is done over the same name — `SIMPLE_A2A_ADMIN_SECRET=new`
— and the value has to be removed again afterwards, or every restart mints
another. The line says so at the time, because whoever reads it is exactly the
person who needs to know.

**An unreadable secret file stops the start.** A service that came up without
administration because a file could not be read would be worse than one that
refuses: the first looks healthy and has no way in.

Two functions, because two callers want two different things. `resolve` is the
service at its start: it settles the secret, generating one if it has to. `find`
is everybody else — in practice `simple-a2a first-prompt`, run beside the
service — and it only reads: the same two places, in the same order, and never
step 3. Only the process that serves may mint a secret, or two processes would
disagree about which one is in force.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from simple_a2a.core import atomic
from simple_a2a.core.config import ADMIN_SECRET, REGENERATE, Config, ConfigError
from simple_a2a.core.limits import ADMIN_SECRET_MIN_CHARS
from simple_a2a.core.paths import Layout

logger = logging.getLogger("simple_a2a")

#: Bytes behind a generated secret. Well above the minimum an operator is held
#: to, because nobody has to type this one.
GENERATED_BYTES = 32


class Origin:
    """Where the secret in use came from. Reported, never guessed at."""

    ENVIRONMENT = "environment"
    FILE = "file"
    GENERATED = "generated"


@dataclass(frozen=True)
class Secret:
    value: str
    origin: str


def _read_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(
            ADMIN_SECRET,
            f"the secret file {path} exists and cannot be read ({exc.strerror}). Starting "
            "without administration would leave no way in; fix the file's ownership or "
            f"remove it and set {ADMIN_SECRET}={REGENERATE!r} to have a new one generated",
        ) from exc
    return text or None


def _check_length(value: str, *, where: str) -> None:
    if len(value) < ADMIN_SECRET_MIN_CHARS:
        raise ConfigError(
            ADMIN_SECRET,
            f"the secret in the {where} is {len(value)} characters long and has to be at "
            f"least {ADMIN_SECRET_MIN_CHARS}. Either set a long random value, or set "
            f"{ADMIN_SECRET}={REGENERATE!r} and restart to have one generated",
        )


def _generate(layout: Layout) -> Secret:
    value = secrets.token_urlsafe(GENERATED_BYTES)
    atomic.write_text(layout.admin_secret, value + "\n", mode=atomic.PRIVATE_MODE)
    logger.warning(
        "The administration secret is %s — this is the only time it is written to the log. "
        "It is kept in %s, readable by its owner only. To have a new one made, set %s=%s and "
        "restart, then remove that value again or every restart will mint another.",
        value,
        layout.admin_secret,
        ADMIN_SECRET,
        REGENERATE,
    )
    return Secret(value=value, origin=Origin.GENERATED)


def find(config: Config, layout: Layout) -> Secret | None:
    """The secret that is already settled — environment, then file — or `None`.

    Steps 0 to 2 of the order above, and nothing of step 3: this reads, and it
    writes nothing, not even a file mode. It is the half of `resolve` that a
    process beside the running service may use — `simple-a2a first-prompt` asks
    it which secret the service is using — because a second process that could
    *settle* a secret would be a second writer on the one file, and would mint a
    value the service never sees.

    `None` means there is none to be found: administration is off, or nothing
    has been generated yet. The request for a new one (`SIMPLE_A2A_ADMIN_SECRET=new`)
    is not a secret, so with it set the file is what counts — by the time anyone
    asks, the service has already replaced it at its start.
    """
    if not config.administration_is_on:
        return None

    if config.admin_secret is not None:
        # Already length-checked while the configuration was read; checked again
        # here so that this function is safe to call on a Config from anywhere.
        _check_length(config.admin_secret, where="environment")
        return Secret(value=config.admin_secret, origin=Origin.ENVIRONMENT)

    from_file = _read_file(layout.admin_secret)
    if from_file is not None:
        _check_length(from_file, where=f"file {layout.admin_secret}")
        return Secret(value=from_file, origin=Origin.FILE)

    return None


def resolve(config: Config, layout: Layout) -> Secret | None:
    """The secret in use, or `None` when administration is off.

    What the service calls at its start: `find`, and where that finds nothing,
    generation. The one process that may settle the secret is the one that serves.
    """
    if not config.administration_is_on:
        return None

    if config.regenerate_admin_secret:
        # Asked for on purpose, so an existing file is replaced rather than
        # read. This is the way back for an operator who missed the line and
        # cannot get into the container to read the file.
        return _generate(layout)

    found = find(config, layout)
    if found is not None:
        if found.origin == Origin.FILE:
            # The file may have been placed by the operator with wide permissions.
            # Narrowing it is silent on purpose: refusing to start over a mode we
            # can simply fix would be a mandatory setting in disguise.
            try:
                os.chmod(layout.admin_secret, atomic.PRIVATE_MODE)
            except OSError:
                pass
        return found

    return _generate(layout)
