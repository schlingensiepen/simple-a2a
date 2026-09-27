"""Time, in one format, with the resolution the ordering depends on.

ISO 8601 in UTC with milliseconds. The resolution is a promise rather than a
detail: the order of the holdings *is* the order of the timestamps, and equal
timestamps have no order at all — so a coarser clock would silently turn a
sequence into a set.
"""

from __future__ import annotations

from datetime import UTC, datetime

#: What a timestamp looks like, for a reader who is about to write one down.
EXAMPLE = "2026-09-27T14:03:11.482Z"


def now() -> datetime:
    """The current moment, always aware, always UTC."""
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    """Format a moment the one way: UTC, milliseconds, `Z`.

    A naive datetime is refused rather than assumed to be UTC. Guessing a
    timezone is how a service ends up an hour out for half the year, and the
    guess is invisible in the output.
    """
    if moment.tzinfo is None:
        raise ValueError("a timestamp without a timezone cannot be written down")
    stamp = moment.astimezone(UTC)
    return f"{stamp.strftime('%Y-%m-%dT%H:%M:%S')}.{stamp.microsecond // 1000:03d}Z"


def now_iso() -> str:
    """The current moment, written the one way."""
    return to_iso(now())
