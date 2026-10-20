"""The lookout on its own, against a service that answers what each test says.

The cross test runs the program against a real instance, which cannot fail on
request; whether mail is lost after a failed first look needs a service that does.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROGRAM = Path(__file__).resolve().parents[2] / "mcp" / "simple_a2a_mcp.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("simple_a2a_mcp", PROGRAM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


mcp = _load()


def stamp(when: datetime) -> str:
    """A time as the service writes it: UTC, milliseconds, a Z."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def entry(message_id: str, sent_at: str) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "sender_kind": "peer",
        "sender_name": "Anna",
        "sent_at": sent_at,
        "subject": "hello",
    }


class Scripted:
    """A service whose answers to GET /inbox are given in advance, one per look."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)

    def request(self, method: str, path: str, **_: Any) -> Any:
        assert method == "GET" and path.startswith(mcp.INBOX_PATH)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer()
        body = json.dumps({"entries": answer}).encode()
        return mcp.Answer(200, "application/json", body)


def lookout(*answers: Any) -> tuple[Any, list[dict[str, Any]]]:
    identity = mcp.Identity("default", "http://127.0.0.1:9", "a-token")
    identity.service = Scripted(*answers)
    told: list[dict[str, Any]] = []
    return mcp.Lookout(identity, 3600.0, threading.Event(), told.append), told


def now() -> str:
    return stamp(datetime.now(UTC))


def test_mail_that_arrives_after_a_failed_first_look_is_still_news() -> None:
    watching, told = lookout(mcp.Unreachable("offline"), lambda: [entry("new-after-start", now())])
    assert watching.trouble is not None

    watching._look()

    assert watching._known == {"new-after-start"}
    assert watching.arrived == ["new-after-start"]
    assert [m["params"]["meta"]["message_id"] for m in told] == ["new-after-start"]


def test_after_a_failed_first_look_what_was_there_before_stays_old() -> None:
    before = stamp(datetime.now(UTC) - timedelta(minutes=5))
    watching, told = lookout(
        mcp.Unreachable("offline"),
        lambda: [entry("new", now()), entry("old", before), entry("undated", "never")],
    )

    watching._look()

    assert watching._known == {"new", "old", "undated"}
    assert watching.arrived == ["new"]
    assert len(told) == 1


def test_what_the_first_look_finds_is_never_news() -> None:
    """However recent it is: the first look that works at once is the baseline."""
    later = stamp(datetime.now(UTC) + timedelta(minutes=5))
    watching, told = lookout([entry("there", later)], [entry("there", later)])

    watching._look()

    assert watching._known == {"there"}
    assert watching.arrived == []
    assert told == []


def test_a_failed_look_after_the_baseline_loses_nothing() -> None:
    watching, told = lookout([], mcp.Unreachable("offline"), lambda: [entry("late", now())])

    watching._look()
    watching._look()

    assert watching.arrived == ["late"]
    assert len(told) == 1
