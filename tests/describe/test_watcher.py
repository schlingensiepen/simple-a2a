"""The watcher the texts hand out, run as written against a running instance.

The service never contacts anybody, so every agent is told to set up a watcher of its
own: a background command that asks the inbox and ends as soon as there is new mail.
The texts carry it ready to use, in a shell and in Python — and a ready-made example
that does not run, or ends before anything arrived, would wake an agent for nothing
or never. So the examples are taken out of the served texts and run, here, against a
real instance on real ports: still running while nothing arrives, ended within two
intervals once something does.

The one change made to them is the interval, from the recommended fifteen seconds to
one, so that the test does not take minutes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from simple_a2a.describe import package
from simple_a2a.describe.guide import GUIDE, Guide

ADMIN_SECRET = "w" * 40
INTERVAL = 1.0
#: What a process may take beyond the interval to start, ask and end, on a loaded machine.
SLACK = 1.5
PATIENCE = 20.0

FENCE = re.compile(r"```(sh|python)\n(.*?)```", re.DOTALL)


def blocks(text: str) -> dict[str, str]:
    return {language: code for language, code in FENCE.findall(text)}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def http(method: str, url: str, body: Any = None, token: str | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=PATIENCE) as answer:
        return json.loads(answer.read())


class Instance:
    def __init__(self, data: Path) -> None:
        self.port, admin_port = free_port(), free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.admin = f"http://127.0.0.1:{admin_port}"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "simple_a2a"],
            env={
                **os.environ,
                "SIMPLE_A2A_BIND": "127.0.0.1",
                "SIMPLE_A2A_PORT": str(self.port),
                "SIMPLE_A2A_ADMIN_PORT": str(admin_port),
                "SIMPLE_A2A_OBSERVER_PORT": "",
                "SIMPLE_A2A_DATA_DIR": str(data),
                "SIMPLE_A2A_ADMIN_SECRET": ADMIN_SECRET,
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            try:
                http("GET", f"{self.base}/health")
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("the instance did not come up")

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=PATIENCE)
        except subprocess.TimeoutExpired:
            self.process.kill()

    def member(self, name: str) -> str:
        voucher = http(
            "POST",
            f"{self.admin}/realms/household/teams/kitchen/invitations",
            {"member_name": name, "member_mission": "m", "display_name": name},
            ADMIN_SECRET,
        )["invitation"]
        return http("POST", f"{self.base}/invitations/redeem", {"invitation": voucher})["token"]

    def send(self, token: str, to: str, subject: str) -> None:
        http(
            "POST",
            f"{self.base}/peers/messages",
            {"recipients": [to], "subject": subject, "body": "b"},
            token,
        )


@pytest.fixture(scope="module")
def instance(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Instance]:
    running = Instance(tmp_path_factory.mktemp("holdings"))
    try:
        http("POST", f"{running.admin}/realms", {"realm_name": "household"}, ADMIN_SECRET)
        http(
            "POST",
            f"{running.admin}/realms/household/teams",
            {"team_name": "kitchen", "team_purpose": "We cook."},
            ADMIN_SECRET,
        )
        yield running
    finally:
        running.stop()


def served() -> tuple[str, str, str]:
    """The entry, the first part of the guide, and SKILL.md, as they are handed out."""
    guide = Guide(surface="messaging", base_address="https://a2a.example.org")
    return guide.entry(), guide.part(GUIDE), package.skill_half(guide, "the participant surface")


def test_the_fact_and_the_watcher_stand_near_the_top_of_every_text() -> None:
    """In the first paragraphs, not after the reader has stopped reading."""
    for text in served():
        head = text[: text.find("```")]
        assert "never contacts you" in head
        assert "exits as soon as there is new mail" in " ".join(head.split())
        assert "wakes you when" in " ".join(head.split())
        assert "15 seconds" in head
        assert text.find("never contacts you") < 1600
    entry, guide, skill = served()
    assert blocks(guide) == blocks(skill)
    assert blocks(entry)["sh"] == blocks(guide)["sh"], "one watcher, not two that drift"
    assert set(blocks(guide)) == {"sh", "python"}


def runnable(code: str, language: str) -> list[str]:
    """The example as written, with the interval shortened and nothing else changed."""
    marker = {"sh": "sleep 15", "python": "time.sleep(15)"}[language]
    assert code.count(marker) == 1, "the recommended interval is where this test expects it"
    shortened = code.replace(marker, marker.replace("15", f"{INTERVAL:g}"))
    if language == "sh":
        return ["sh", "-c", shortened]
    return [sys.executable, "-c", shortened]


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_examples_end_once_mail_arrives_and_not_before(instance: Instance) -> None:
    """Both examples, on an inbox that has mail already and on an empty one."""
    anna, berta, clara = (instance.member(name) for name in ("Anna", "Berta", "Clara"))
    instance.send(anna, "Berta", "already there")
    examples = blocks(served()[1])
    watchers: list[tuple[str, str, subprocess.Popen[bytes]]] = []
    try:
        for who, token in (("Berta", berta), ("Clara", clara)):
            for language, code in examples.items():
                watchers.append(
                    (
                        who,
                        language,
                        subprocess.Popen(
                            runnable(code, language),
                            env={
                                "PATH": os.environ.get("PATH", ""),
                                "A2A_BASE": instance.base,
                                "A2A_TOKEN": token,
                            },
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        ),
                    )
                )

        time.sleep(INTERVAL * 3.5)
        for who, language, watcher in watchers:
            assert watcher.poll() is None, f"{language} for {who} ended with nothing new"

        instance.send(anna, "Berta", "new")
        instance.send(anna, "Clara", "new")
        arrived = time.monotonic()
        for who, language, watcher in watchers:
            out, err = watcher.communicate(timeout=PATIENCE)
            took = time.monotonic() - arrived
            assert watcher.returncode == 0, (language, who, err)
            assert b"New mail" in out, (language, who)
            assert took <= 2 * INTERVAL + SLACK, f"{language} for {who} took {took:.1f}s"
    finally:
        for _, _, watcher in watchers:
            if watcher.poll() is None:
                watcher.kill()
                watcher.wait()


def test_a_wrong_token_ends_the_watcher_at_once_instead_of_waking_later(
    instance: Instance,
) -> None:
    """A watcher that cannot ask must say so now, not sleep on a refusal."""
    for language, code in blocks(served()[1]).items():
        if language == "sh" and shutil.which("curl") is None:
            continue
        finished = subprocess.run(
            runnable(code, language),
            env={
                "PATH": os.environ.get("PATH", ""),
                "A2A_BASE": instance.base,
                "A2A_TOKEN": "not-a-token",
            },
            capture_output=True,
            timeout=PATIENCE,
            check=False,
        )
        assert finished.returncode != 0, language
        assert b"New mail" not in finished.stdout, language
