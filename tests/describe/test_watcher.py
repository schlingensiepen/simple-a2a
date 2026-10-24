"""The watcher the texts hand out, run as written against a running instance.

The service never contacts anybody, so every agent is told to set up a watcher of its
own: a background command that asks the inbox and ends as soon as there is new mail.
The texts carry it ready to use, in a shell and in Python — and a ready-made example
that does not run, or ends before anything arrived, would wake an agent for nothing
or never. So the examples are taken out of the served texts and run, here, against a
real instance on real ports: still running while nothing arrives, ended within two
intervals once something does.

Each example also has a deadline of its own, because a harness may end a background
command after a while, and a watcher ended without a word looks like an empty inbox.
It ends with a line of its own once the deadline has passed, and not before.

An agent that restarts the watcher after reading can hand it the newest message it
read as `A2A_SEEN`, so that what arrived between reading and restarting is not taken
for old: then the watcher ends at once, and with the newest one it waits as before.

The one change made to them is the interval, from the recommended fifteen seconds to
one, so that the test does not take minutes — and, where the deadline is under test,
its unit, from minutes to seconds.
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


#: The deadline the examples are given where it is under test, in seconds.
DEADLINE = 4
DEADLINE_LINE = b"Deadline passed"


def runnable(code: str, language: str, *, deadline_in_seconds: bool = False) -> list[str]:
    """The example as written, with the interval shortened and nothing else changed.

    With `deadline_in_seconds`, `A2A_WATCH_MINUTES` is read as seconds instead.
    """
    marker = {"sh": "sleep 15", "python": "time.sleep(15)"}[language]
    assert code.count(marker) == 1, "the recommended interval is where this test expects it"
    shortened = code.replace(marker, marker.replace("15", f"{INTERVAL:g}"))
    if deadline_in_seconds:
        minutes = {"sh": "${A2A_WATCH_MINUTES:-90} * 60", "python": '"90")) * 60'}[language]
        assert shortened.count(minutes) == 1, "the deadline is where this test expects it"
        shortened = shortened.replace(minutes, minutes.removesuffix(" * 60"))
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
            assert DEADLINE_LINE not in out, (language, who)
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


def watch(
    code: str,
    language: str,
    token: str,
    base: str,
    deadline: float = DEADLINE,
    seen: str | None = None,
) -> subprocess.Popen[bytes]:
    """The example with `A2A_WATCH_MINUTES` read as seconds and set to `deadline`.

    With `seen`, `A2A_SEEN` is set to it: the newest message the agent has read.
    """
    extra = {} if seen is None else {"A2A_SEEN": seen}
    return subprocess.Popen(
        runnable(code, language, deadline_in_seconds=True),
        env={
            "PATH": os.environ.get("PATH", ""),
            "A2A_BASE": base,
            "A2A_TOKEN": token,
            "A2A_WATCH_MINUTES": f"{deadline:g}",
            **extra,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_examples_end_at_their_own_deadline_with_a_line_of_their_own(
    instance: Instance,
) -> None:
    """No mail: running until the deadline, then ended, saying it was the deadline."""
    dora = instance.member("Dora")
    watchers = [
        (language, watch(code, language, dora, instance.base))
        for language, code in blocks(served()[1]).items()
    ]
    started = time.monotonic()
    try:
        time.sleep(DEADLINE - INTERVAL - 0.5)
        for language, watcher in watchers:
            assert watcher.poll() is None, f"{language} ended before its deadline"
        for language, watcher in watchers:
            out, err = watcher.communicate(timeout=PATIENCE)
            took = time.monotonic() - started
            assert watcher.returncode == 0, (language, err)
            assert DEADLINE_LINE in out, language
            assert b"New mail" not in out, language
            assert took <= DEADLINE + INTERVAL + SLACK, f"{language} took {took:.1f}s"
    finally:
        for _, watcher in watchers:
            if watcher.poll() is None:
                watcher.kill()
                watcher.wait()


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_mail_before_the_deadline_still_ends_the_examples_with_the_new_mail_line(
    instance: Instance,
) -> None:
    """A deadline of their own does not keep the examples from waking on mail."""
    anton, emil = instance.member("Anton"), instance.member("Emil")
    watchers = [
        (language, watch(code, language, emil, instance.base, deadline=PATIENCE))
        for language, code in blocks(served()[1]).items()
    ]
    try:
        time.sleep(INTERVAL * 1.5)
        for language, watcher in watchers:
            assert watcher.poll() is None, f"{language} ended with nothing new"
        instance.send(anton, "Emil", "before the deadline")
        for language, watcher in watchers:
            out, err = watcher.communicate(timeout=PATIENCE)
            assert watcher.returncode == 0, (language, err)
            assert b"New mail" in out, language
            assert DEADLINE_LINE not in out, language
    finally:
        for _, watcher in watchers:
            if watcher.poll() is None:
                watcher.kill()
                watcher.wait()


def newest_id(instance: Instance, token: str) -> str:
    """The message_id of the newest message in the inbox, as an agent reads it."""
    return http("GET", f"{instance.base}/inbox?limit=1", token=token)["entries"][0]["message_id"]


def ended(
    watchers: list[tuple[str, subprocess.Popen[bytes]]],
) -> Iterator[tuple[str, bytes, bytes, int]]:
    """Each watcher's language, output, errors and exit code, once it has ended."""
    try:
        for language, watcher in watchers:
            out, err = watcher.communicate(timeout=PATIENCE)
            yield language, out, err, watcher.returncode
    finally:
        for _, watcher in watchers:
            if watcher.poll() is None:
                watcher.kill()
                watcher.wait()


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_a_seen_id_that_is_the_newest_keeps_the_examples_waiting_until_their_deadline(
    instance: Instance,
) -> None:
    """`A2A_SEEN` equal to the newest message: nothing is new, the deadline ends them."""
    sender, fritz = instance.member("Karl"), instance.member("Fritz")
    instance.send(sender, "Fritz", "read already")
    seen = newest_id(instance, fritz)
    watchers = [
        (language, watch(code, language, fritz, instance.base, seen=seen))
        for language, code in blocks(served()[1]).items()
    ]
    started = time.monotonic()
    time.sleep(DEADLINE - INTERVAL - 0.5)
    for language, watcher in watchers:
        assert watcher.poll() is None, f"{language} ended with nothing new"
    for language, out, err, code in ended(watchers):
        took = time.monotonic() - started
        assert code == 0, (language, err)
        assert DEADLINE_LINE in out, language
        assert b"New mail" not in out, language
        assert took <= DEADLINE + INTERVAL + SLACK, f"{language} took {took:.1f}s"


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_mail_that_arrived_before_the_restart_ends_the_examples_at_once(
    instance: Instance,
) -> None:
    """`A2A_SEEN` older than the newest message: what arrived in between wakes at once."""
    sender, gerda = instance.member("Ludwig"), instance.member("Gerda")
    instance.send(sender, "Gerda", "read already")
    seen = newest_id(instance, gerda)
    instance.send(sender, "Gerda", "arrived between reading and the restart")
    started = time.monotonic()
    watchers = [
        (language, watch(code, language, gerda, instance.base, deadline=PATIENCE, seen=seen))
        for language, code in blocks(served()[1]).items()
    ]
    for language, out, err, code in ended(watchers):
        took = time.monotonic() - started
        assert code == 0, (language, err)
        assert b"New mail" in out, language
        assert DEADLINE_LINE not in out, language
        assert took < INTERVAL + SLACK, f"{language} took {took:.1f}s, it slept first"


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
@pytest.mark.parametrize("seen", [None, ""], ids=["unset", "empty"])
def test_an_empty_inbox_keeps_the_examples_waiting_and_the_first_mail_ends_them(
    instance: Instance, seen: str | None
) -> None:
    """No message yet: no id to compare is not taken for new mail, the first one is."""
    suffix = "Unset" if seen is None else "Empty"
    sender, hanna = instance.member(f"Ida{suffix}"), instance.member(f"Hanna{suffix}")
    watchers = [
        (language, watch(code, language, hanna, instance.base, deadline=PATIENCE, seen=seen))
        for language, code in blocks(served()[1]).items()
    ]
    time.sleep(INTERVAL * 3.5)
    for language, watcher in watchers:
        assert watcher.poll() is None, f"{language} ended on an empty inbox"
    instance.send(sender, f"Hanna{suffix}", "the first one")
    for language, out, err, code in ended(watchers):
        assert code == 0, (language, err)
        assert b"New mail" in out, language
        assert DEADLINE_LINE not in out, language


#: How long one ask of the inbox may take in the examples, in seconds.
ASK_LIMIT = 10


class Stalling:
    """An inbox that answers the first ask and leaves every later one hanging."""

    def __init__(self) -> None:
        import http.server
        import threading

        asked = threading.Event()
        self.release = threading.Event()
        release = self.release

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if asked.is_set():
                    release.wait(PATIENCE + ASK_LIMIT)
                    return
                asked.set()
                body = b'{"entries": []}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize("language", ["sh", "python"])
def test_an_ask_that_hangs_does_not_carry_the_watcher_past_its_deadline(language: str) -> None:
    """A stalled ask ends after its own limit, and the deadline still ends the watcher."""
    if language == "sh" and shutil.which("curl") is None:
        pytest.skip("the shell example needs curl")
    stalling = Stalling()
    try:
        watcher = watch(blocks(served()[1])[language], language, "t", stalling.base)
        started = time.monotonic()
        out, err = watcher.communicate(timeout=DEADLINE + ASK_LIMIT + PATIENCE)
        took = time.monotonic() - started
        assert watcher.returncode == 0, err
        assert DEADLINE_LINE in out
        assert took <= DEADLINE + ASK_LIMIT + INTERVAL + SLACK, f"took {took:.1f}s"
    finally:
        stalling.stop()
