"""What an operation needs to hand: the holdings, the limits, the one secret.

Passed in rather than reached for, so that every operation here can be exercised
against a directory in a temporary folder — which is what makes the rules
testable without a request, a port or a process.
"""

from __future__ import annotations

from dataclasses import dataclass

from simple_a2a.core.config import Config
from simple_a2a.store.holdings import Holdings


@dataclass(frozen=True)
class Context:
    """One instance's world.

    `admin_secret` is here and not in the holdings, and that is deliberate: it
    has to work when there is nothing else at all, or a bare start would have no
    way in.
    """

    holdings: Holdings
    config: Config
    admin_secret: str | None = None
