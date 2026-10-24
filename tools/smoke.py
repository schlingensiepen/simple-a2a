#!/usr/bin/env python3
"""The smoke test: start the artefact that is about to be published, and drive it.

Delivery is by pull, so nobody stands at the far end to notice a broken release.
Every check therefore has to sit before publication, and this is the one that
starts the real thing — the installed entry point, or the built image — and talks
to it from outside, over HTTP, the way everybody after us will. It imports nothing
of the service: what it knows about the service it reads off the running instance,
so a test that passes here passes against what was built, not against the tree.

Two ways to start, one sequence of checks:

    smoke.py process [--command CMD] [--env NAME=VALUE ...]
        starts the command (default: this interpreter with `-m simple_a2a`) as a
        child process, in a working directory of its own, its log in a file there.
        Every SIMPLE_A2A_* variable of the calling environment is removed first,
        so the start is bare unless --env sets one. The holdings land in the
        default place, which is moved into the working directory by pointing
        XDG_STATE_HOME there — not a parameter of the service, so the start stays
        bare.

    smoke.py container --image IMAGE [--name NAME] [--volume VOLUME --keep-volume]
        runs the image with nothing set, only its three ports published on the
        loopback address and a volume of the run's own on the data directory
        (removed afterwards, passed or failed), waits for the
        image's own health check rather than for an open port, reads the log with
        `docker logs`, and restarts by removing the container and running a new one
        on the same volume — what an upgrade does.

What it checks, in this order, one line each; the first failure stops the run with
a non-zero exit and says what was expected and what came back:

1. a bare start: no SIMPLE_A2A_* variable, and every surface answers /health;
2. the administration secret is in the log exactly once, at the place the
   service generated it; the secret itself is never printed here;
3. the secret is accepted, nothing is refused as no token, and so is a secret
   nobody issued;
4. the token-free addresses, derived rather than listed: every GET operation the
   interface description declares without an Authorization header, its one
   templated address (/guide/{part}) expanded by the links on the entry page,
   and the description itself. Both directions are held: every address found
   that way is on the entry page, and every address the entry page names exists
   in the description;
5. no realm yet: every token-free address answers 200, and the same with a token
   presented; a token presented where one is needed is refused as no token;
6. no placeholder in any skill package or rendered text, and no `http` outside
   the entry and the small half of the package that carries the base address;
7. a realm without a team, and
8. a team without a member: the token-free addresses unchanged, an unissued
   token still refused as no token;
9. the token cycle across all three surfaces: an invitation obtained from
   administration, redeemed on the participant surface with the realm-master
   mark set, a call with the token; an observer token issued and read with;
   both revoked, and the revocation repeated with the first time repeated; both
   tokens then refused as revoked;
10. the full holding: every token-free address answers exactly as it did on the
    empty one;
11. a restart on the same holdings: the secret still accepted and not written
    to the log again, the holdings still there, the revoked token still revoked;
12. the build stamp on every surface names the build that was asked for.

Standard library only, so that it runs on a bare runner and next to a wheel in a
clean virtual environment without bringing anything of its own.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The namespace of the operational parameters. A bare start sets none of them.
PREFIX = "SIMPLE_A2A_"

#: The line the service writes once, when it generates the administration secret.
SECRET_LINE = re.compile(
    r"The administration secret is (?P<secret>\S+) — this is the only time it is written to "
    r"the log\. It is kept in (?P<where>\S+), readable"
)
SECRET_MENTION = "The administration secret is "

#: Marks that would mean a template was served unfilled.
PLACEHOLDER_MARKS = ("%%", "{{", "<<")

#: An identifier has 43 characters from this alphabet; a token is an identifier.
ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
ID_LENGTH = 43

#: How long a start may take before the run gives up, and how often to look.
PATIENCE_SECONDS = 60.0
POLL_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = 10.0

#: The ports the image serves its three surfaces on when nothing is set.
IMAGE_PORTS = (8251, 8252, 8253)

JSON_ACCEPT = {"Accept": "application/json"}

#: Names used for the cycle. Fixed, so that a failed run can be read back.
REALM = "smoke"
TEAM = "first"
MEMBER = "Probe"
OBSERVER = "smoke eye"


class Failure(Exception):
    """A check that did not hold. The message says what was expected."""


# ----------------------------------------------------------------------- HTTP


@dataclass(frozen=True)
class Answer:
    status: int
    media: str
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError as exc:
            raise Failure(f"expected JSON, got {self.body[:200]!r}") from exc

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer to look at, not one to follow."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> Answer:
    sent = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        sent["Content-Type"] = "application/json"
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=sent)
    try:
        with _OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return Answer(
                response.status, response.headers.get("content-type", ""), response.read()
            )
    except urllib.error.HTTPError as refused:
        return Answer(refused.code, refused.headers.get("content-type", ""), refused.read())


def answers_health(base: str) -> bool:
    try:
        return call("GET", f"{base}/health").status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def expect_status(answer: Answer, status: int, what: str) -> None:
    if answer.status != status:
        raise Failure(f"{what}: expected {status}, got {answer.status}: {answer.text[:300]}")


def expect_rejection(answer: Answer, status: int, kind: str, what: str) -> None:
    expect_status(answer, status, what)
    found = answer.json().get("type")
    if found != kind:
        raise Failure(f"{what}: expected a rejection of type {kind!r}, got {found!r}")


def unissued_token() -> str:
    """A token of the right shape that nobody issued."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


# -------------------------------------------------------------------- runners


@dataclass(frozen=True)
class Surfaces:
    participants: str
    administration: str
    observation: str

    def all(self) -> list[tuple[str, str]]:
        return [
            ("participants", self.participants),
            ("administration", self.administration),
            ("observation", self.observation),
        ]


class Runner:
    """Starts the service, restarts it, and hands over its log."""

    #: The SIMPLE_A2A_* variables this run sets, for the bare-start check.
    set_variables: tuple[str, ...] = ()

    #: How the start is described when nothing was set.
    bare = "no SIMPLE_A2A_* variable set"

    def start(self) -> None:
        raise NotImplementedError

    def restart(self) -> None:
        raise NotImplementedError

    def log(self) -> str:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def cleanup(self) -> None:
        """At the end of the run, passed or failed: stop, and remove what was made."""
        self.stop()

    def wait_until_up(self, surfaces: Surfaces) -> None:
        deadline = time.monotonic() + PATIENCE_SECONDS
        while time.monotonic() < deadline:
            self.still_running()
            if all(answers_health(base) for _, base in surfaces.all()):
                return
            time.sleep(POLL_SECONDS)
        raise Failure(f"not every surface answered /health within {PATIENCE_SECONDS:.0f} s")

    def still_running(self) -> None:
        """Raise when the service is known to have stopped."""


class ProcessRunner(Runner):
    """The entry point as a child process, its output in a file that outlives restarts."""

    def __init__(self, command: list[str], extra: dict[str, str], work: Path) -> None:
        self.command = command
        self.work = work
        self.log_path = work / "service.log"
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(PREFIX) and not name.startswith("A2A_BUILD")
        }
        # Not a parameter of the service: the place a bare start chooses for its
        # holdings is moved here, so that this run never touches the caller's own.
        environment["XDG_STATE_HOME"] = str(work / "state")
        environment["PYTHONUNBUFFERED"] = "1"
        environment.update(extra)
        self.environment = environment
        self.set_variables = tuple(sorted(name for name in extra if name.startswith(PREFIX)))
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        with self.log_path.open("ab") as log:
            self.process = subprocess.Popen(
                self.command,
                env=self.environment,
                cwd=self.work,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

    def still_running(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            raise Failure(f"the service exited with status {self.process.returncode}")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=PATIENCE_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def log(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")


class ContainerRunner(Runner):
    """The image, run with nothing set, on a named volume, and run again on it."""

    bare = "no SIMPLE_A2A_* variable set beyond the two the image itself carries"

    def __init__(
        self,
        engine: str,
        image: str,
        name: str,
        ports: tuple[int, ...],
        volume: str | None = None,
        keep_volume: bool = False,
    ) -> None:
        self.engine = engine
        self.image = image
        self.name = name
        self.ports = ports
        # A volume of this run's own unless one is named: a fixed name would hand
        # the next run the holdings — and the secret — of the last one, and its
        # first start would then not be a first start at all.
        self.volume = volume or f"simple-a2a-smoke-{secrets.token_hex(6)}"
        self.keep_volume = keep_volume
        self.earlier = ""

    def _run(self, *arguments: str) -> str:
        done = subprocess.run(
            [self.engine, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise Failure(f"{self.engine} {arguments[0]} failed: {done.stdout.strip()}")
        return done.stdout

    def start(self) -> None:
        # Each address the run was given, onto the port the image serves that
        # surface on by default: nothing inside the container is set.
        published = [
            f"--publish=127.0.0.1:{outside}:{inside}"
            for outside, inside in zip(self.ports, IMAGE_PORTS, strict=True)
        ]
        self._run(
            "run",
            "--detach",
            f"--name={self.name}",
            *published,
            f"--volume={self.volume}:/var/lib/simple-a2a",
            # The image's own check, asked more often: its interval is set for a
            # service that runs for months, and a smoke test should not wait half a
            # minute for the first verdict. The command stays the image's.
            "--health-interval=2s",
            self.image,
        )

    def _health(self) -> str:
        return self._run("inspect", "--format", "{{.State.Health.Status}}", self.name).strip()

    def still_running(self) -> None:
        state = self._run("inspect", "--format", "{{.State.Status}}", self.name).strip()
        if state not in ("running", "created", "restarting"):
            raise Failure(f"the container is {state}")

    def wait_until_up(self, surfaces: Surfaces) -> None:
        # The image's verdict, not an open port: an open port only says that
        # somebody listens. And then the outside view as well, through the
        # published ports, because that is what a caller has.
        deadline = time.monotonic() + PATIENCE_SECONDS
        while time.monotonic() < deadline:
            self.still_running()
            if self._health() == "healthy":
                break
            time.sleep(POLL_SECONDS)
        else:
            raise Failure(
                f"the image's health check did not say healthy within "
                f"{PATIENCE_SECONDS:.0f} s (last: {self._health()})"
            )
        super().wait_until_up(surfaces)

    def restart(self) -> None:
        # Not `restart` on the same container: a new container on the same volume,
        # which is what an upgrade does, and the only way to show that the holdings
        # and the secret live on the volume rather than in a container layer. The
        # log of the old one is kept, so "not written again" is checked across both.
        self.earlier += self._run("logs", self.name)
        self.stop()
        self.start()

    def log(self) -> str:
        return self.earlier + self._run("logs", self.name)

    def _quietly(self, *arguments: str) -> None:
        subprocess.run(
            [self.engine, *arguments],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def stop(self) -> None:
        self._quietly("rm", "--force", self.name)

    def cleanup(self) -> None:
        # The volume holds the secret this run generated. It goes with the run,
        # passed or failed, unless keeping it was asked for by name.
        self.stop()
        if not self.keep_volume:
            self._quietly("volume", "rm", "--force", self.volume)


# ------------------------------------------------------- the token-free addresses


#: What every surface answers without a token, whatever else it offers.
MINIMUM_TOKEN_FREE = {"/", "/guide", "/health", "/build", "/skill.zip", "/openapi.json"}

ADDRESS_IN_TEXT = r"[^\s)`>\]\"'<]*"


def links_on(entry: str, base: str) -> set[str]:
    """Every path on this base that the entry page names, `/` for the base itself."""
    found = set()
    for match in re.finditer(re.escape(base) + ADDRESS_IN_TEXT, entry):
        path = match.group(0)[len(base) :].rstrip(".,;:")
        found.add(path or "/")
    return found


def template_pattern(template: str) -> re.Pattern[str]:
    pieces = re.split(r"(\{[^}]+\})", template)
    return re.compile(
        "".join("[^/]+" if piece.startswith("{") else re.escape(piece) for piece in pieces) + r"\Z"
    )


def needs_token(operation: dict[str, Any]) -> bool:
    return any(
        parameter.get("in") == "header" and parameter.get("name", "").lower() == "authorization"
        for parameter in operation.get("parameters") or []
    ) or bool(operation.get("security"))


def token_free(base: str, surface: str) -> list[str]:
    """Derive the token-free addresses of one surface from the running instance."""
    description = call("GET", f"{base}/openapi.json")
    expect_status(description, 200, f"{surface} /openapi.json")
    paths = description.json().get("paths")
    if not isinstance(paths, dict) or not paths:
        raise Failure(f"{surface}: the interface description has no paths")
    entry = call("GET", f"{base}/")
    expect_status(entry, 200, f"{surface} entry")
    named = links_on(entry.text, base)

    found = {"/openapi.json"}
    for path, verbs in paths.items():
        operation = verbs.get("get")
        if operation is None or needs_token(operation):
            continue
        if "{" not in path:
            found.add(path)
            continue
        pattern = template_pattern(path)
        expanded = {link for link in named if pattern.match(link)}
        if not expanded:
            raise Failure(f"{surface}: the entry page names no address for {path}")
        found |= expanded

    missing = sorted(found - named)
    if missing:
        raise Failure(f"{surface}: token-free but not on the entry page: {', '.join(missing)}")
    templates = [template_pattern(path) for path in paths]
    unknown = sorted(
        link
        for link in named - found
        if "{" not in link and not any(pattern.match(link) for pattern in templates)
    )
    if unknown:
        raise Failure(f"{surface}: the entry page names addresses that do not exist: {unknown}")
    # Derived is only as good as what it was derived from. A description that has
    # lost its token-free routes would leave next to nothing to check, and that
    # nothing would pass; so the floor every surface has is held explicitly.
    absent = sorted(MINIMUM_TOKEN_FREE - found)
    if absent:
        raise Failure(f"{surface}: no token-free address for {', '.join(absent)}")
    if not any(path.startswith("/guide/") for path in found):
        raise Failure(f"{surface}: not one guide part was found")
    return sorted(found)


# ------------------------------------------------------------------ snapshots


def normalised(path: str, answer: Answer) -> tuple[int, str, bytes]:
    """What has to stay the same from one stage to the next.

    Everything, byte for byte — except the moment /health was asked, which is the
    one field that is supposed to move.
    """
    body = answer.body
    if path == "/health":
        document = answer.json()
        if document.get("healthy") is not True:
            raise Failure(f"/health does not say healthy: {document}")
        document.pop("checked_at", None)
        body = json.dumps(document, sort_keys=True).encode()
    return answer.status, answer.media, body


Snapshot = dict[str, tuple[int, str, bytes]]


def snapshot(addresses: dict[str, list[str]], surfaces: Surfaces, token: str | None) -> Snapshot:
    taken: Snapshot = {}
    for surface, base in surfaces.all():
        for path in addresses[surface]:
            answer = call("GET", f"{base}{path}", token=token)
            expect_status(answer, 200, f"{surface} {path}")
            taken[f"{surface} {path}"] = normalised(path, answer)
    return taken


def same_as(before: Snapshot, after: Snapshot, stage: str) -> None:
    for address, then in before.items():
        if after.get(address) != then:
            raise Failure(f"{stage}: {address} answers differently than on the empty holding")


# ----------------------------------------------------------------- the checks


@dataclass
class Run:
    runner: Runner
    surfaces: Surfaces
    expect_build: str | None
    expect_built_at: str | None
    secret: str = ""
    addresses: dict[str, list[str]] = field(default_factory=dict)
    empty: Snapshot = field(default_factory=dict)
    member_token: str = ""
    observer_token: str = ""

    @property
    def admin(self) -> str:
        return self.surfaces.administration

    def as_admin(self, method: str, path: str, body: Any = None) -> Answer:
        return call(method, f"{self.admin}{path}", token=self.secret, body=body)

    # 1
    def bare_start(self) -> str:
        self.runner.start()
        self.runner.wait_until_up(self.surfaces)
        if self.runner.set_variables:
            return "every surface answers; set for this run: " + ", ".join(
                self.runner.set_variables
            )
        return f"{self.runner.bare}, every surface answers /health"

    # 2
    def secret_logged_once(self) -> str:
        log = self.runner.log()
        lines = [line for line in log.splitlines() if SECRET_MENTION in line]
        if len(lines) != 1:
            raise Failure(f"expected one line naming the secret, found {len(lines)}")
        match = SECRET_LINE.search(lines[0])
        if match is None:
            raise Failure("the line naming the secret does not have the expected shape")
        self.secret = match.group("secret")
        count = log.count(self.secret)
        if count != 1:
            raise Failure(f"the secret appears {count} times in the log, not once")
        return f"exactly once, kept in {match.group('where')}"

    # 3
    def secret_accepted(self) -> str:
        listing = self.as_admin("GET", "/realms")
        expect_status(listing, 200, "the logged secret on GET /realms")
        if listing.json() != {"realms": []}:
            raise Failure(f"a fresh holding should have no realm: {listing.text[:200]}")
        expect_rejection(
            call("GET", f"{self.admin}/realms", token=unissued_token()),
            401,
            "no-token",
            "a secret nobody issued",
        )
        expect_rejection(call("GET", f"{self.admin}/realms"), 401, "no-token", "no secret at all")
        return "accepted; an unissued one and none at all refused as no-token"

    # 4
    def derive_addresses(self) -> str:
        for surface, base in self.surfaces.all():
            self.addresses[surface] = token_free(base, surface)
        counts = ", ".join(f"{surface} {len(found)}" for surface, found in self.addresses.items())
        total = sum(len(found) for found in self.addresses.values())
        return f"{total} token-free addresses: {counts}"

    def unissued_refused(self) -> None:
        stranger = unissued_token()
        for surface, base, path in (
            ("participants", self.surfaces.participants, "/me"),
            ("observation", self.surfaces.observation, "/teams"),
            ("administration", self.admin, "/realms"),
        ):
            expect_rejection(
                call("GET", f"{base}{path}", token=stranger, headers=JSON_ACCEPT),
                401,
                "no-token",
                f"an unissued token on {surface} {path}",
            )

    def unchanged(self, stage: str) -> None:
        same_as(self.empty, snapshot(self.addresses, self.surfaces, None), stage)
        same_as(self.empty, snapshot(self.addresses, self.surfaces, unissued_token()), stage)

    # 5
    def empty_holding(self) -> str:
        self.empty = snapshot(self.addresses, self.surfaces, None)
        same_as(self.empty, snapshot(self.addresses, self.surfaces, unissued_token()), "a token")
        self.unissued_refused()
        return "all 200, the same with a token presented; an unissued token is no-token"

    # 6
    def no_placeholder(self) -> str:
        checked = 0
        for surface, base in self.surfaces.all():
            for path in self.addresses[surface]:
                if not (path == "/" or path.startswith("/guide")):
                    continue
                text = call("GET", f"{base}{path}").text
                self.clean(text, f"{surface} {path}", http_allowed=path == "/")
                checked += 1
            archive = call("GET", f"{base}/skill.zip")
            expect_status(archive, 200, f"{surface} /skill.zip")
            with zipfile.ZipFile(io.BytesIO(archive.body)) as package:
                names = package.namelist()
                if sorted(names) != ["INSTANCE.md", "SKILL.md"]:
                    raise Failure(f"{surface} /skill.zip holds {names}")
                for name in names:
                    text = package.read(name).decode("utf-8")
                    self.clean(text, f"{surface} skill {name}", http_allowed=name == "INSTANCE.md")
                    checked += 1
        return f"{checked} texts, no placeholder, `http` only where the base address goes"

    @staticmethod
    def clean(text: str, where: str, *, http_allowed: bool) -> None:
        for mark in PLACEHOLDER_MARKS:
            if mark in text:
                raise Failure(f"{where}: a placeholder is left ({mark})")
        if not http_allowed and "http" in text:
            raise Failure(f"{where}: `http` outside the entry")

    # 7
    def realm_without_team(self) -> str:
        expect_status(self.as_admin("POST", "/realms", {"realm_name": REALM}), 200, "a realm")
        self.unchanged("a realm without a team")
        self.unissued_refused()
        return "token-free addresses unchanged, an unissued token is no-token"

    # 8
    def team_without_member(self) -> str:
        expect_status(
            self.as_admin("POST", f"/realms/{REALM}/teams", {"team_name": TEAM}), 200, "a team"
        )
        self.unchanged("a team without a member")
        self.unissued_refused()
        return "token-free addresses unchanged, an unissued token is no-token"

    # 9
    def token_cycle(self) -> str:
        participants, observation = self.surfaces.participants, self.surfaces.observation
        invited = self.as_admin(
            "POST",
            f"/realms/{REALM}/teams/{TEAM}/invitations",
            {"member_name": MEMBER, "member_mission": "Probe checks.", "display_name": "probe"},
        )
        expect_status(invited, 200, "an invitation")
        redeemed = call(
            "POST",
            f"{participants}/invitations/redeem",
            body={"invitation": invited.json()["invitation"]},
        )
        expect_status(redeemed, 200, "redeeming the invitation")
        if redeemed.json().get("is_realm_master") is not True:
            raise Failure("an invitation the operator obtained has to carry the realm-master mark")
        self.member_token = redeemed.json()["token"]
        me = call("GET", f"{participants}/me", token=self.member_token, headers=JSON_ACCEPT)
        expect_status(me, 200, "GET /me with the new token")
        sent = call(
            "POST",
            f"{participants}/peers/messages",
            token=self.member_token,
            body={"subject": "smoke", "body": "Anybody there?"},
        )
        expect_status(sent, 200, "a message sent with the new token")

        issued = self.as_admin(
            "POST", f"/realms/{REALM}/observer-tokens", {"display_name": OBSERVER}
        )
        expect_status(issued, 200, "an observer token")
        self.observer_token = issued.json()["token"]
        teams = call("GET", f"{observation}/teams", token=self.observer_token, headers=JSON_ACCEPT)
        expect_status(teams, 200, "GET /teams with the observer token")
        if TEAM not in teams.text:
            raise Failure(f"the observer does not see the team: {teams.text[:200]}")
        traffic = call(
            "GET",
            f"{observation}/teams/{TEAM}/traffic",
            token=self.observer_token,
            headers=JSON_ACCEPT,
        )
        expect_status(traffic, 200, "the team's traffic for the observer")

        for what, path in (
            ("the member token", f"/realms/{REALM}/teams/{TEAM}/members/{MEMBER}/token"),
            (
                "the observer token",
                f"/realms/{REALM}/observer-tokens/{urllib.parse.quote(OBSERVER)}",
            ),
        ):
            first = self.as_admin("DELETE", path)
            second = self.as_admin("DELETE", path)
            expect_status(first, 200, f"revoking {what}")
            expect_status(second, 200, f"revoking {what} again")
            then, again = first.json().get("revoked_at"), second.json().get("revoked_at")
            if not then or then != again:
                raise Failure(f"revoking {what} twice: first {then!r}, then {again!r}")

        expect_rejection(
            call("GET", f"{participants}/me", token=self.member_token, headers=JSON_ACCEPT),
            401,
            "token-revoked",
            "the revoked member token",
        )
        expect_rejection(
            call("GET", f"{observation}/teams", token=self.observer_token, headers=JSON_ACCEPT),
            401,
            "token-revoked",
            "the revoked observer token",
        )
        return (
            "invitation, redemption (realm master), a call, an observer reading, both revoked "
            "twice with the first time repeated, both refused as token-revoked"
        )

    # 10
    def full_holding(self) -> str:
        self.unchanged("the full holding")
        return "every token-free address answers as on the empty holding"

    # 11
    def restart(self) -> str:
        self.runner.restart()
        self.runner.wait_until_up(self.surfaces)
        listing = self.as_admin("GET", "/realms")
        expect_status(listing, 200, "the secret after the restart")
        if REALM not in listing.text:
            raise Failure(f"the realm did not survive the restart: {listing.text[:200]}")
        log = self.runner.log()
        if log.count(self.secret) != 1 or log.count(SECRET_MENTION) != 1:
            raise Failure("the restart wrote the secret, or a new one, to the log")
        expect_rejection(
            call("GET", f"{self.surfaces.participants}/me", token=self.member_token),
            401,
            "token-revoked",
            "the revoked member token after the restart",
        )
        self.unchanged("after the restart")
        return "secret still accepted and not logged again, holdings and revocation kept"

    # 12
    def build_stamp(self) -> str:
        stamps = []
        for surface, base in self.surfaces.all():
            answer = call("GET", f"{base}/build")
            expect_status(answer, 200, f"{surface} /build")
            stamps.append(answer.json())
        if any(stamp != stamps[0] for stamp in stamps):
            raise Failure(f"the surfaces disagree about the build: {stamps}")
        stamp = stamps[0]
        if self.expect_build is None:
            return f"not asked for; the stamp says {stamp}"
        if stamp.get("build_id") != self.expect_build:
            raise Failure(f"expected build {self.expect_build!r}, the stamp says {stamp}")
        if self.expect_built_at is not None and stamp.get("built_at") != self.expect_built_at:
            raise Failure(f"expected built at {self.expect_built_at!r}, the stamp says {stamp}")
        return f"build {stamp['build_id']}, version {stamp.get('version')}, built {stamp.get('built_at')}"

    def checks(self) -> list[tuple[str, Callable[[], str]]]:
        return [
            ("a bare start", self.bare_start),
            ("the secret in the log", self.secret_logged_once),
            ("the secret accepted", self.secret_accepted),
            ("the token-free addresses", self.derive_addresses),
            ("stage: no realm", self.empty_holding),
            ("no placeholder", self.no_placeholder),
            ("stage: a realm without a team", self.realm_without_team),
            ("stage: a team without a member", self.team_without_member),
            ("the token cycle", self.token_cycle),
            ("the full holding", self.full_holding),
            ("a restart", self.restart),
            ("the build stamp", self.build_stamp),
        ]


#: Anything shaped like a secret of this service: a long run of the identifier
#: alphabet. Generated secrets, tokens and invitations all are one.
SECRET_SHAPED = re.compile(r"[A-Za-z0-9_-]{32,}")


def redacted(text: str, secret: str) -> str:
    """Text fit to print: the secret, and everything shaped like one, masked.

    Not only the secret that was found: when the line that names it does not
    match, nothing was found, and the log excerpt printed on failure would carry
    it unmasked. So the shape is masked whether or not the value is known —
    which also covers a token that turns up in an answer quoted in a failure.
    """
    if secret:
        text = text.replace(secret, "<the secret>")
    return SECRET_SHAPED.sub("<masked>", text)


def execute(run: Run) -> int:
    try:
        for number, (name, check) in enumerate(run.checks(), start=1):
            try:
                detail = check()
            except Failure as failed:
                print(f"FAIL {number:2d} {name}: {redacted(str(failed), run.secret)}", flush=True)
                with contextlib.suppress(Exception):
                    tail = "\n".join(run.runner.log().splitlines()[-40:])
                    print("---- the end of the service's log ----", file=sys.stderr)
                    print(redacted(tail, run.secret), file=sys.stderr)
                return 1
            print(f"ok   {number:2d} {name}: {detail}", flush=True)
    finally:
        run.runner.cleanup()
    print("smoke test passed", flush=True)
    return 0


# ------------------------------------------------------------------ the command


def parse_assignment(text: str) -> tuple[str, str]:
    name, sign, value = text.partition("=")
    if not sign or not name:
        raise argparse.ArgumentTypeError(f"{text!r} is not NAME=VALUE")
    return name, value


def port_of(base: str) -> int:
    parsed = urllib.parse.urlsplit(base)
    if parsed.port is None:
        raise SystemExit(f"{base} names no port")
    return parsed.port


def arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--participants", default="http://127.0.0.1:8251")
    parser.add_argument("--administration", default="http://127.0.0.1:8252")
    parser.add_argument("--observation", default="http://127.0.0.1:8253")
    parser.add_argument("--expect-build", help="the build id /build has to name")
    parser.add_argument("--expect-built-at", help="the build time /build has to name")
    modes = parser.add_subparsers(dest="mode", required=True)

    process = modes.add_parser("process", help="start the entry point as a child process")
    process.add_argument(
        "--command",
        default=shlex.join([sys.executable, "-m", "simple_a2a"]),
        help="how to start the service (default: this interpreter, -m simple_a2a)",
    )
    process.add_argument(
        "--env",
        type=parse_assignment,
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="a variable to set for the service; every SIMPLE_A2A_* one is reported",
    )
    process.add_argument("--work-dir", type=Path, help="kept afterwards; default: a temporary one")

    container = modes.add_parser("container", help="run an image")
    container.add_argument("--image", required=True)
    container.add_argument("--name", default="simple-a2a-smoke")
    container.add_argument(
        "--volume", help="the volume to use; default: a new one for this run, removed after it"
    )
    container.add_argument(
        "--keep-volume",
        action="store_true",
        help="leave the volume in place afterwards; it holds the generated secret",
    )
    container.add_argument("--engine", default="docker", help="docker or podman")
    return parser.parse_args(argv)


@contextlib.contextmanager
def work_directory(chosen: Path | None) -> Iterator[Path]:
    if chosen is not None:
        chosen.mkdir(parents=True, exist_ok=True)
        yield chosen
        return
    made = Path(tempfile.mkdtemp(prefix="simple-a2a-smoke-"))
    try:
        yield made
    finally:
        shutil.rmtree(made, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    given = arguments(argv)
    surfaces = Surfaces(
        given.participants.rstrip("/"),
        given.administration.rstrip("/"),
        given.observation.rstrip("/"),
    )
    if given.mode == "container":
        ports = tuple(port_of(base) for _, base in surfaces.all())
        runner: Runner = ContainerRunner(
            given.engine, given.image, given.name, ports, given.volume, given.keep_volume
        )
        return execute(Run(runner, surfaces, given.expect_build, given.expect_built_at))
    with work_directory(given.work_dir) as work:
        runner = ProcessRunner(shlex.split(given.command), dict(given.env), work)
        return execute(Run(runner, surfaces, given.expect_build, given.expect_built_at))


if __name__ == "__main__":
    raise SystemExit(main())
