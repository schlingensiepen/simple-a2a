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
from typing import Any, Self

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
    """The first block of each language: the watcher comes before any other example."""
    found: dict[str, str] = {}
    for language, code in FENCE.findall(text):
        found.setdefault(language, code)
    return found


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


def redemption_example() -> str:
    """The one shell example on the entry that redeems an invitation."""
    examples = [code for language, code in FENCE.findall(served()[0]) if language == "sh"]
    redeeming = [code for code in examples if "/invitations/redeem" in code]
    assert len(redeeming) == 1, "one redemption example on the entry"
    assert redeeming[0].count(REDEMPTION_PLACEHOLDER) == 1
    return redeeming[0]


REDEMPTION_PLACEHOLDER = "<your invitation>"


def redeem_as_written(instance: Instance, home: Path, member: str) -> Path:
    """A fresh invitation, redeemed by the entry's example with `home` as HOME.

    It runs in a working directory of its own beside `home`, which has to stay
    empty: the answer belongs in the private directory, not where one works.
    Returns the file the example names on its last line.
    """
    work = home.parent / f"{home.name}-work"
    work.mkdir(exist_ok=True)
    voucher = http(
        "POST",
        f"{instance.admin}/realms/household/teams/kitchen/invitations",
        {"member_name": member, "member_mission": "m", "display_name": member},
        ADMIN_SECRET,
    )["invitation"]
    finished = subprocess.run(
        ["sh", "-c", redemption_example().replace(REDEMPTION_PLACEHOLDER, voucher)],
        env={"PATH": os.environ.get("PATH", ""), "A2A_BASE": instance.base, "HOME": str(home)},
        cwd=work,
        capture_output=True,
        check=True,
        timeout=PATIENCE,
    )
    assert list(work.iterdir()) == [], "the answer landed where one works"
    return Path(finished.stdout.decode().splitlines()[-1])


@pytest.mark.skipif(shutil.which("curl") is None, reason="the example needs curl")
def test_the_redemption_example_on_the_entry_keeps_the_answer_in_a_private_file(
    instance: Instance, tmp_path: Path
) -> None:
    """Run as written: the answer lands unchanged in a file only its owner can read."""
    home = tmp_path / "home"
    home.mkdir()
    named = redeem_as_written(instance, home, "Nora")
    (kept,) = (home / ".a2a").glob("redeemed-*.json")
    assert named == kept, "the last line names the file to read"
    assert kept.stat().st_mode & 0o077 == 0, "readable by others"
    assert (home / ".a2a").stat().st_mode & 0o777 == 0o700, "the directory is not private"
    token = json.loads(kept.read_text())["token"]
    assert http("GET", f"{instance.base}/inbox", token=token)["entries"] == []
    assert "( umask 077;" in redemption_example(), "the umask ends with the example"


@pytest.mark.skipif(shutil.which("curl") is None, reason="the example needs curl")
def test_the_redemption_example_names_no_file_when_the_address_is_unreachable(
    tmp_path: Path,
) -> None:
    """Only a file the answer was written into is named; without HOME it says why."""
    home = tmp_path / "home"
    home.mkdir()
    code = redemption_example().replace(REDEMPTION_PLACEHOLDER, "x")
    path = os.environ.get("PATH", "")
    unreachable = subprocess.run(
        ["sh", "-c", code],
        env={"PATH": path, "A2A_BASE": f"http://127.0.0.1:{free_port()}", "HOME": str(home)},
        cwd=tmp_path,
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )
    homeless = subprocess.run(
        ["sh", "-c", code],
        env={"PATH": path, "A2A_BASE": f"http://127.0.0.1:{free_port()}"},
        cwd=tmp_path,
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )

    assert unreachable.returncode != 0 and unreachable.stdout == b""
    assert unreachable.stderr != b"", "the error says why"
    assert list((home / ".a2a").glob("redeemed-*.json")) == []
    assert homeless.returncode != 0 and homeless.stdout == b""
    assert b"HOME" in homeless.stderr


@pytest.mark.skipif(shutil.which("curl") is None, reason="the example needs curl")
def test_redeeming_twice_keeps_the_first_answer(instance: Instance, tmp_path: Path) -> None:
    """A second invitation does not overwrite the only copy of the first token."""
    home = tmp_path / "home"
    home.mkdir()
    named = {redeem_as_written(instance, home, member) for member in ("Olga", "Paula")}
    kept = sorted((home / ".a2a").glob("redeemed-*.json"))
    assert len(kept) == 2, "the second answer replaced the first"
    assert named == set(kept)
    tokens = {json.loads(answer.read_text())["token"] for answer in kept}
    assert len(tokens) == 2
    for token in tokens:
        assert http("GET", f"{instance.base}/inbox", token=token)["entries"] == []


def test_the_entry_and_the_guide_carry_the_same_shell_watcher_byte_for_byte() -> None:
    """The entry's copy is not run by the watcher tests; this keeps it the guide's."""
    entry, guide, _ = served()
    first_sh = [
        next(code for language, code in FENCE.findall(text) if language == "sh")
        for text in (entry, guide)
    ]
    assert first_sh[0].encode() == first_sh[1].encode()


def test_the_texts_say_how_to_hand_the_watcher_its_seen_id() -> None:
    """On the start line, fresh, never exported; from entries[0]; unset when empty."""
    receiving = Guide(surface="messaging", base_address="https://a2a.example.org").part("receiving")
    for text in served()[:2]:
        said = " ".join(text.split())
        assert "`A2A_SEEN=<message_id> sh watch.sh`" in said
        assert "`entries[0].message_id`" in said
        assert "never `export" in said
        assert "if the inbox was empty, leave it unset" in said
    said = " ".join(receiving.split())
    # Inline, with the script's default: a fresh shell has no `$handled`, and an
    # empty A2A_SEEN would pass silently for an unset one.
    listed = '"${A2A_HANDLED:-$HOME/.a2a/handled}"'
    assert f"`A2A_SEEN=$(tail -n 1 {listed}) sh watch.sh`" in said
    assert f"`printf '%s\\n' \"<message_id>\" >> {listed}`" in said
    prose = " ".join(FENCE.sub("", receiving).split())
    assert '"$handled"' not in prose, "the prose relies on a variable of the script"
    assert "handled.txt" not in said, "the prose names the list the script reads"


# ------------------------------------------------------------------ the receiving part


def receiving_example(marker: str) -> str:
    """The one shell example of the receiving part that names `marker`."""
    text = Guide(surface="messaging", base_address="https://a2a.example.org").part("receiving")
    found = [code for language, code in FENCE.findall(text) if language == "sh" and marker in code]
    assert len(found) == 1, f"one example with {marker} in the receiving part"
    return found[0]


def test_the_examples_of_the_receiving_part_do_not_displace_the_watcher() -> None:
    """The first shell block of every served text is still the plain watcher."""
    entry, guide, skill = served()
    assert blocks(skill)["sh"] == blocks(guide)["sh"] == blocks(entry)["sh"]
    assert "A2A_SHOW_BODY" not in blocks(skill)["sh"]
    assert "A2A_HANDLED" not in blocks(skill)["sh"]


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_showing_watcher_ends_at_new_mail_and_prints_what_arrived(
    instance: Instance,
) -> None:
    """It waits like the plain one, then prints each new envelope back to the one it knew."""
    code = receiving_example("A2A_SHOW_BODY")
    sender, iris = instance.member("Moritz"), instance.member("Iris")
    instance.send(sender, "Iris", "read already")
    seen = newest_id(instance, iris)
    envelopes = watch(code, "sh", iris, instance.base, deadline=PATIENCE, seen=seen)
    bodies = subprocess.Popen(
        runnable(code, "sh", deadline_in_seconds=True),
        env={
            "PATH": os.environ.get("PATH", ""),
            "A2A_BASE": instance.base,
            "A2A_TOKEN": iris,
            "A2A_WATCH_MINUTES": f"{PATIENCE:g}",
            "A2A_SHOW_BODY": "1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    watchers = [("envelopes", envelopes), ("bodies", bodies)]
    time.sleep(INTERVAL * 2.5)
    for which, watcher in watchers:
        assert watcher.poll() is None, f"{which} ended with nothing new"
    instance.send(sender, "Iris", "first new")
    instance.send(sender, "Iris", "second new")
    fresh = newest_id(instance, iris)
    for which, out, err, status in ended(watchers):
        assert status == 0, (which, err)
        said = out.decode()
        assert said.startswith("New mail"), which
        assert DEADLINE_LINE not in out, which
        assert f"--- {fresh}" in said, which
        assert "first new" in said and "second new" in said, which
        assert "read already" not in said and f"--- {seen}" not in said, which
        assert said.count("--- ") == 2, which
        envelope = said.split(f"--- {fresh}\n", 1)[1].splitlines()[0]
        assert json.loads(envelope)["message_id"] == fresh, which


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_showing_watcher_prints_bodies_only_when_asked(instance: Instance) -> None:
    code = receiving_example("A2A_SHOW_BODY")
    sender, jan = instance.member("Nils"), instance.member("Jan")
    instance.send(sender, "Jan", "old")
    seen = newest_id(instance, jan)
    for show in ("", "1"):
        instance.send(sender, "Jan", f"show {show or 'none'}")
        finished = subprocess.run(
            runnable(code, "sh", deadline_in_seconds=True),
            env={
                "PATH": os.environ.get("PATH", ""),
                "A2A_BASE": instance.base,
                "A2A_TOKEN": jan,
                "A2A_WATCH_MINUTES": f"{PATIENCE:g}",
                "A2A_SEEN": seen,
                "A2A_SHOW_BODY": show,
            },
            capture_output=True,
            timeout=PATIENCE,
            check=True,
        )
        lines = finished.stdout.decode().splitlines()
        assert lines[0].startswith("New mail")
        # The body the test sends is "b": a marked line of its own only when asked for.
        assert ("> b" in lines) is (show == "1"), lines
        assert "b" not in lines, "a body line stands unmarked"
        seen = newest_id(instance, jan)


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_list_of_handled_ids_names_what_is_left_oldest_first(
    instance: Instance, tmp_path: Path
) -> None:
    """Run as written: what is not in the list, oldest first; then nothing, once handled."""
    code = receiving_example("A2A_HANDLED")
    sender, karla = instance.member("Otto"), instance.member("Karla")
    instance.send(sender, "Karla", "handled")
    handled = newest_id(instance, karla)
    instance.send(sender, "Karla", "older")
    older = newest_id(instance, karla)
    instance.send(sender, "Karla", "newer")
    newer = newest_id(instance, karla)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "A2A_BASE": instance.base,
        "A2A_TOKEN": karla,
        "HOME": str(tmp_path),
    }
    kept_list = tmp_path / ".a2a" / "handled"
    kept_list.parent.mkdir(mode=0o700)
    kept_list.write_text(handled + "\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def left() -> list[str]:
        finished = subprocess.run(
            ["sh", "-c", code],
            env=environment,
            cwd=elsewhere,
            capture_output=True,
            timeout=PATIENCE,
            check=True,
        )
        return finished.stdout.decode().split()

    first = left()
    with kept_list.open("a") as kept:
        kept.writelines(f"{identifier}\n" for identifier in first)
    second = left()
    last = kept_list.read_text().splitlines()[-1]
    assert list(elsewhere.iterdir()) == [], "the list is not where the script runs"

    assert first == [older, newer]
    assert second == []
    assert last == newer, "the last line is the A2A_SEEN to hand the watcher"


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_list_of_handled_ids_starts_empty_and_a_wrong_token_fails(
    instance: Instance, tmp_path: Path
) -> None:
    code = receiving_example("A2A_HANDLED")
    sender, lea = instance.member("Paul"), instance.member("Lea")
    instance.send(sender, "Lea", "the only one")
    only = newest_id(instance, lea)
    base = {"PATH": os.environ.get("PATH", ""), "A2A_BASE": instance.base}
    kept = tmp_path / "mine.txt"

    listed = subprocess.run(
        ["sh", "-c", code],
        env={**base, "A2A_TOKEN": lea, "A2A_HANDLED": str(kept)},
        capture_output=True,
        timeout=PATIENCE,
        check=True,
    )
    refused = subprocess.run(
        ["sh", "-c", code],
        env={**base, "A2A_TOKEN": "not-a-token", "A2A_HANDLED": str(kept)},
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )

    home = tmp_path / "home"
    home.mkdir()
    by_default = subprocess.run(
        ["sh", "-c", code],
        env={**base, "A2A_TOKEN": lea, "HOME": str(home)},
        cwd=tmp_path,
        capture_output=True,
        timeout=PATIENCE,
        check=True,
    )

    assert listed.stdout.decode().split() == [only]
    assert kept.exists() and kept.read_text() == ""
    assert refused.returncode != 0 and refused.stdout == b""
    assert by_default.stdout.decode().split() == [only]
    default = home / ".a2a" / "handled"
    assert default.exists() and default.read_text() == ""
    assert default.parent.stat().st_mode & 0o777 == 0o700, "the directory is not private"
    assert default.stat().st_mode & 0o077 == 0, "the list is readable by others"


# ------------------------------------------------------------------ an inbox of chosen ids


def chosen_id(number: int, start: str = "") -> str:
    """An id of the service's shape; with `start`, beginning with it (e.g. `-A`)."""
    tail = f"{number:041d}".replace("0", "x")
    return (start + tail)[:43].ljust(43, "y")


class FixedInbox:
    """An inbox that holds the given ids, newest first, and bodies chosen for them.

    Real ids are random; these are chosen, so that ids beginning with `-` and
    windows of exactly 100 are tested every time rather than by chance.
    """

    def __init__(self, ids: list[str], bodies: dict[str, str] | None = None) -> None:
        import http.server
        import threading
        import urllib.parse

        held, written = list(ids), dict(bodies or {})

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                url = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(url.query)
                kind = "application/json"
                if url.path == "/inbox":
                    limit = int(query.get("limit", ["20"])[0])
                    offset = int(query.get("offset", ["0"])[0])
                    entries = [
                        {"message_id": i, "subject": "s", "sender_name": "x"}
                        for i in held[offset : offset + limit]
                    ]
                    body = json.dumps({"entries": entries}).encode()
                elif url.path.endswith("/body"):
                    found = url.path.split("/")[2]
                    body, kind = written.get(found, "b").encode(), "text/plain"
                elif url.path.startswith("/messages/"):
                    found = url.path.split("/")[2]
                    body = json.dumps({"message_id": found, "subject": "s"}).encode()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def handled_left(inbox: FixedInbox, handled: list[str], tmp_path: Path) -> list[str]:
    """The lines the handled-ids example prints, with `handled` as the list."""
    kept = tmp_path / "handled"
    kept.write_text("".join(f"{i}\n" for i in handled))
    finished = subprocess.run(
        ["sh", "-c", receiving_example("A2A_HANDLED")],
        env={
            "PATH": os.environ.get("PATH", ""),
            "A2A_BASE": inbox.base,
            "A2A_TOKEN": "t",
            "A2A_HANDLED": str(kept),
        },
        capture_output=True,
        timeout=PATIENCE,
        check=True,
    )
    assert finished.stderr == b"", finished.stderr
    return finished.stdout.decode().splitlines()


#: Ids beginning with `-`, as one in 64 real ids does; `-A`, `-m` and `-e` are
#: options of grep that take an argument, `--` ends its options.
DASHED = [chosen_id(n, start) for n, start in enumerate(["-A", "-m", "-e", "--", "-v", "-x"])]


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_list_of_handled_ids_takes_ids_beginning_with_a_dash_as_ids(
    tmp_path: Path,
) -> None:
    """The handled ones are never named again, the others once, oldest first."""
    newest_first = [*DASHED, chosen_id(99)]
    handled = DASHED[::2]
    with FixedInbox(newest_first) as inbox:
        left = handled_left(inbox, handled, tmp_path)
        none_left = handled_left(inbox, newest_first, tmp_path)

    assert left == [chosen_id(99), DASHED[5], DASHED[3], DASHED[1]]
    assert none_left == []


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_list_of_handled_ids_says_when_more_than_its_window_may_be_new(
    tmp_path: Path,
) -> None:
    newest_first = [chosen_id(n) for n in range(150, 0, -1)]
    with FixedInbox(newest_first) as inbox:
        all_new = handled_left(inbox, [], tmp_path)
        reached = handled_left(inbox, newest_first[99:], tmp_path)
        fewer = handled_left(inbox, newest_first[60:], tmp_path)

    assert all_new[:-1] == newest_first[:100][::-1]
    assert all_new[-1].startswith("More than 100 may be new") and "offset=100" in all_new[-1]
    assert reached == newest_first[:99][::-1], "the oldest in the window was handled"
    assert fewer == newest_first[:60][::-1]


def showing(inbox: FixedInbox, seen: str, show_body: bool = False) -> list[str]:
    """What the showing watcher prints when `seen` is not the newest any more."""
    finished = subprocess.run(
        runnable(receiving_example("A2A_SHOW_BODY"), "sh", deadline_in_seconds=True),
        env={
            "PATH": os.environ.get("PATH", ""),
            "A2A_BASE": inbox.base,
            "A2A_TOKEN": "t",
            "A2A_WATCH_MINUTES": f"{PATIENCE:g}",
            "A2A_SEEN": seen,
            "A2A_SHOW_BODY": "1" if show_body else "",
        },
        capture_output=True,
        timeout=PATIENCE,
        check=True,
    )
    return finished.stdout.decode().splitlines()


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_showing_watcher_says_when_more_than_its_window_may_be_new(tmp_path: Path) -> None:
    newest_first = [*DASHED, *(chosen_id(n) for n in range(150, 0, -1))]
    with FixedInbox(newest_first) as inbox:
        unknown = showing(inbox, chosen_id(999))
        known = showing(inbox, newest_first[50])

    assert unknown[0].startswith("New mail")
    assert [line for line in unknown if line.startswith("--- ")] == [
        f"--- {i}" for i in newest_first[:100]
    ]
    assert unknown[-1].startswith("More than 100 may be new") and "offset=100" in unknown[-1]
    assert sum(line.startswith("--- ") for line in known) == 50
    assert not any(line.startswith("More than") for line in known)


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_showing_watcher_marks_every_body_line_and_cuts_a_long_body(tmp_path: Path) -> None:
    """A body cannot pass for structure, and one body cannot flood the output."""
    forged = chosen_id(7)
    long_id, short_id, old = chosen_id(1), chosen_id(2), chosen_id(3)
    long_body = f"--- {forged}\nNew mail, newest first:\n" + "z" * 6000 + "\nend\n"
    short_body = f"line one\n--- {forged}\n"
    with FixedInbox([long_id, short_id, old], {long_id: long_body, short_id: short_body}) as inbox:
        said = showing(inbox, old, show_body=True)

    structure = [line for line in said if not line.startswith("> ")]
    assert structure[0] == "New mail, newest first:"
    assert [line for line in structure if line.startswith("--- ")] == [
        f"--- {long_id}",
        f"--- {short_id}",
    ]
    assert f"> --- {forged}" in said and said.count("> New mail, newest first:") == 1
    assert "> line one" in said
    assert sum(line.startswith("(cut") for line in said) == 1
    cut_at = said.index(next(line for line in said if line.startswith("(cut")))
    assert cut_at < said.index(f"--- {short_id}"), "the long body is the one cut"
    assert "> end" not in said
    shown = said[said.index(f"--- {long_id}") + 2 : cut_at]
    assert all(line.startswith("> ") for line in shown)
    assert sum(len(line) - len("> ") + 1 for line in shown) == 4000 + 1, "cut at 4000 bytes"


@pytest.mark.skipif(shutil.which("curl") is None, reason="the shell example needs curl")
def test_the_showing_watcher_drops_control_characters_from_bodies(tmp_path: Path) -> None:
    """Other line breaks and escape sequences cannot pass for structure either."""
    forged = chosen_id(8)
    new, old = chosen_id(4), chosen_id(5)
    body = f"first\r--- {forged}\x1b[2Ksecond\x0b--- {forged}\x0c\x1e\x7fthird\ttab\n"
    with FixedInbox([new, old], {new: body}) as inbox:
        finished = subprocess.run(
            runnable(receiving_example("A2A_SHOW_BODY"), "sh", deadline_in_seconds=True),
            env={
                "PATH": os.environ.get("PATH", ""),
                "A2A_BASE": inbox.base,
                "A2A_TOKEN": "t",
                "A2A_WATCH_MINUTES": f"{PATIENCE:g}",
                "A2A_SEEN": old,
                "A2A_SHOW_BODY": "1",
            },
            capture_output=True,
            timeout=PATIENCE,
            check=True,
        )
    out = finished.stdout.decode()

    for control in ("\r", "\x1b", "\x0b", "\x0c", "\x1e", "\x7f"):
        assert control not in out, repr(control)
    said = out.splitlines()
    assert [line for line in said if line.startswith("--- ")] == [f"--- {new}"]
    (shown,) = [line for line in said if forged in line]
    assert shown == f"> first--- {forged}[2Ksecond--- {forged}third\ttab"


def test_the_entry_points_to_the_concepts_for_the_realm_master_field() -> None:
    """Half a sentence by the redemption example, not an explanation of its own."""
    entry = served()[0]
    after = entry[entry.find("/invitations/redeem") :]
    said = " ".join(after[: after.find("## ")].split())
    assert "`is_realm_master`" in said
    assert "https://a2a.example.org/guide/concepts" in said
