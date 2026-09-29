"""The MCP program against a running instance, spoken to the way a harness speaks to it.

This is where the promise "it does not fall behind" is checked rather than made. The
program cannot look into the service — the second lock forbids it — so the check
sits out here: a real service on real ports, the program as a subprocess with its
two variables, and JSON-RPC over its standard input and output. What it reports
about itself is held against what the instance says about itself, in both
directions and without a list of exceptions.

Two agents take part, as they would: Anna and Berta, one process each, because one
process carries one identity.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

PROGRAM = Path(__file__).resolve().parents[2] / "mcp" / "simple_a2a_mcp.py"
ADMIN_SECRET = "s" * 40
MODERN = "2026-07-28"
META = {
    "io.modelcontextprotocol/protocolVersion": MODERN,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "the-cross-test", "version": "1"},
}
#: How long anything may take before the test calls it lost. Generous, because a
#: loaded machine is not a failure of the program.
PATIENCE = 20.0


# ------------------------------------------------------------------ the instance


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def http(
    method: str, url: str, body: Any = None, token: str | None = None, raw: bytes | None = None
) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else raw
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=PATIENCE) as answer:
            raw = answer.read()
            status = answer.status
    except urllib.error.HTTPError as refused:
        raw, status = refused.read(), refused.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", errors="replace")


class Instance:
    """The service, started the way the image starts it: its own entry point."""

    def __init__(self, data: Path) -> None:
        self.port, self.admin_port = free_port(), free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.admin = f"http://127.0.0.1:{self.admin_port}"
        environment = {
            **os.environ,
            "SIMPLE_A2A_BIND": "127.0.0.1",
            "SIMPLE_A2A_PORT": str(self.port),
            "SIMPLE_A2A_ADMIN_PORT": str(self.admin_port),
            "SIMPLE_A2A_OBSERVER_PORT": "",
            "SIMPLE_A2A_DATA_DIR": str(data),
            "SIMPLE_A2A_ADMIN_SECRET": ADMIN_SECRET,
        }
        self.process = subprocess.Popen(
            [sys.executable, "-m", "simple_a2a"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            try:
                if http("GET", f"{self.base}/health")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        self.stop()
        raise RuntimeError("the instance did not come up")

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=PATIENCE)
        except subprocess.TimeoutExpired:
            self.process.kill()

    def invitation(self, name: str) -> str:
        """An invitation from the operator, which carries the realm-master right."""
        status, answer = http(
            "POST",
            f"{self.admin}/realms/household/teams/kitchen/invitations",
            {"member_name": name, "member_mission": f"{name} helps.", "display_name": name},
            ADMIN_SECRET,
        )
        assert status == 200, answer
        return answer["invitation"]

    def redeem(self, voucher: str, **extra: str) -> str:
        status, redeemed = http(
            "POST", f"{self.base}/invitations/redeem", {"invitation": voucher, **extra}
        )
        assert status == 200, redeemed
        return redeemed["token"]

    def member(self, name: str) -> str:
        return self.redeem(self.invitation(name))

    def invited_by(self, inviter: str, name: str) -> str:
        """A member invited by a member: in the team, without the realm-master right."""
        status, answer = http(
            "POST",
            f"{self.base}/invitations/peer",
            {"member_name": name, "member_mission": f"{name} helps.", "display_name": name},
            inviter,
        )
        assert status == 200, answer
        return self.redeem(answer["invitation"])

    def service(self, inviter: str, name: str) -> str:
        status, answer = http(
            "POST",
            f"{self.base}/invitations/service",
            {"service_name": name, "display_name": f"for {name}"},
            inviter,
        )
        assert status == 200, answer
        return self.redeem(answer["invitation"], member_self_image=f"I am {name}.")

    def revoked(self, name: str) -> str:
        token = self.member(name)
        status, answer = http(
            "DELETE",
            f"{self.admin}/realms/household/teams/kitchen/members/{name}/token",
            token=ADMIN_SECRET,
        )
        assert status == 200, answer
        return token


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
        running.anna = running.member("Anna")  # type: ignore[attr-defined]
        running.berta = running.member("Berta")  # type: ignore[attr-defined]
        yield running
    finally:
        running.stop()


# ------------------------------------------------------------------ the program


class Program:
    """The MCP program as a harness has it: a subprocess, and two pipes."""

    def __init__(self, environment: dict[str, str]) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(PROGRAM)],
            env={"PATH": os.environ.get("PATH", ""), **environment},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.lines: list[str] = []
        self.inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self.next_id = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            line = raw.decode("utf-8")
            self.lines.append(line)
            self.inbox.put(json.loads(line))

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def ask(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One request, and its response; notifications on the way are kept."""
        self.next_id += 1
        identifier = self.next_id
        self.send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}})
        return self.wait(lambda message: message.get("id") == identifier)

    def wait(self, wanted: Any, patience: float = PATIENCE) -> dict[str, Any]:
        kept: list[dict[str, Any]] = []
        deadline = time.monotonic() + patience
        try:
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"nothing arrived that was wanted; saw {kept}")
                try:
                    message = self.inbox.get(timeout=left)
                except queue.Empty:
                    continue
                if wanted(message):
                    return message
                kept.append(message)
        finally:
            for message in kept:
                self.inbox.put(message)

    def initialize(self) -> dict[str, Any]:
        answer = self.ask(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "the-cross-test", "version": "1"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return answer

    def call(self, tool: str, /, **arguments: Any) -> dict[str, Any]:
        return self.ask("tools/call", {"name": tool, "arguments": arguments})["result"]

    def close(self) -> tuple[str, str]:
        """Close the input, as a harness does, and hand back everything it wrote."""
        assert self.process.stdin is not None and self.process.stderr is not None
        self.process.stdin.close()
        self.process.wait(timeout=PATIENCE)
        self.reader.join(timeout=PATIENCE)
        return "".join(self.lines), self.process.stderr.read().decode("utf-8")


def text_of(result: dict[str, Any]) -> str:
    return "".join(part["text"] for part in result["content"] if part["type"] == "text")


@pytest.fixture
def programs(instance: Instance) -> Iterator[Any]:
    """Start programs, with a token or without; at the end, none has let its token out."""
    started: list[tuple[Program, str | None]] = []

    def start(token: str | None, **extra: str) -> Program:
        environment = {"A2A_MCP_ADDRESS": instance.base, **extra}
        if token is not None:
            environment["A2A_MCP_TOKEN"] = token
        program = Program(environment)
        started.append((program, token))
        return program

    yield start
    for program, token in started:
        stdout, stderr = program.close()
        assert program.process.returncode == 0, stderr
        if token is not None:
            assert token not in stdout, "the token left the program on standard output"
            assert token not in stderr, "the token left the program on standard error"


# ------------------------------------------------------------------ the checks


#: The addresses that describe the service rather than use it — named one by one,
#: not derived. Deriving them with the rule the program itself uses would only show
#: that two copies of one rule agree, and could never find an operation the rule
#: leaves out by mistake. `/openapi.json` is named although the framework does not
#: list it: if it ever did, it would still not be an operation.
SELF_DESCRIPTION = {
    ("GET", "/"),
    ("GET", "/guide"),
    ("GET", "/guide/{part}"),
    ("GET", "/openapi.json"),
    ("GET", "/skill.zip"),
    ("GET", "/mcp.zip"),
    ("GET", "/health"),
    ("GET", "/build"),
}


def operations(document: dict[str, Any]) -> dict[str, str]:
    """Every operation of the description but the self-description: name to address."""
    found = {}
    for path, verbs in document["paths"].items():
        for verb, operation in verbs.items():
            if (verb.upper(), path) not in SELF_DESCRIPTION:
                found[operation["operationId"]] = f"`{verb.upper()} {path}`"
    return found


def mismatch(expected: dict[str, str], tools: list[dict[str, Any]]) -> tuple[set, set, set]:
    """Operations without a tool, tools without an operation, tools naming another address."""
    names = {tool["name"] for tool in tools}
    wrong = {
        tool["name"]
        for tool in tools
        if tool["name"] in expected and expected[tool["name"]] not in tool["description"]
    }
    return set(expected) - names, names - set(expected), wrong


def test_the_tools_are_exactly_the_operations(instance: Instance, programs: Any) -> None:
    """Both directions, and nothing left out but the self-description named above."""
    _, document = http("GET", f"{instance.base}/openapi.json")
    described = {
        (verb.upper(), path) for path, verbs in document["paths"].items() for verb in verbs
    }
    assert SELF_DESCRIPTION - {("GET", "/openapi.json")} <= described, "a named address moved"
    expected = operations(document)
    anna = programs(instance.anna)
    anna.initialize()

    tools = anna.ask("tools/list")["result"]["tools"]

    assert mismatch(expected, tools) == (set(), set(), set())
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert "$ref" not in json.dumps(tool["inputSchema"]), "a schema has to stand alone"
    assert len(tools) == 28
    assert "redeem" in expected, "redeeming is an operation, and so a tool"


def test_the_comparison_finds_a_missing_an_extra_and_a_misplaced_tool(instance: Instance) -> None:
    """The red probe: the comparison above is shown failing on each kind of drift."""
    _, document = http("GET", f"{instance.base}/openapi.json")
    expected = operations(document)
    exact = [{"name": name, "description": where} for name, where in expected.items()]

    one_short = [tool for tool in exact if tool["name"] != "redeem"]
    one_over = [*exact, {"name": "invented", "description": "`GET /invented`"}]
    misplaced = [
        {**tool, "description": "`GET /elsewhere`"} if tool["name"] == "inbox" else tool
        for tool in exact
    ]

    assert mismatch(expected, exact) == (set(), set(), set())
    assert mismatch(expected, one_short)[0] == {"redeem"}
    assert mismatch(expected, one_over)[1] == {"invented"}
    assert mismatch(expected, misplaced)[2] == {"inbox"}


def test_the_handshake_says_first_that_it_is_not_the_contract(
    instance: Instance, programs: Any
) -> None:
    answer = programs(instance.anna).initialize()["result"]

    assert answer["protocolVersion"] == "2025-11-25"
    assert answer["capabilities"]["resources"]["subscribe"] is True
    assert "tools" in answer["capabilities"]
    said = answer["instructions"]
    assert said.startswith("This MCP server is not the contract.")
    assert f"{instance.base}/guide" in said
    assert "does not wake a sleeping one" in said


def test_an_older_revision_is_answered_in_its_own_terms(instance: Instance, programs: Any) -> None:
    anna = programs(instance.anna)

    answer = anna.ask("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})

    assert answer["result"]["protocolVersion"] == "2024-11-05"
    assert anna.ask("ping")["result"] == {}


def test_the_current_revision_is_spoken_per_request(instance: Instance, programs: Any) -> None:
    anna = programs(instance.anna)

    found = anna.ask("server/discover", {"_meta": META})["result"]
    listed = anna.ask("tools/list", {"_meta": META})["result"]

    assert MODERN in found["supportedVersions"]
    assert found["resultType"] == "complete"
    assert found["instructions"].startswith("This MCP server is not the contract.")
    assert found["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "simple-a2a-mcp"
    assert listed["resultType"] == "complete" and listed["ttlMs"] > 0
    assert len(listed["tools"]) == 28


def test_what_does_not_fit_the_protocol_is_answered_as_the_protocol_says(
    instance: Instance, programs: Any
) -> None:
    anna = programs(instance.anna)

    no_version = anna.ask("tools/list")
    old_unknown = anna.ask("tools/list", {"_meta": {**META, META_KEY: "1900-01-01"}})
    no_method = anna.ask("tools/invented", {"_meta": META})
    no_tool = anna.ask("tools/call", {"_meta": META, "name": "invented", "arguments": {}})

    assert no_version["error"]["code"] == -32602
    assert old_unknown["error"]["code"] == -32022
    assert MODERN in old_unknown["error"]["data"]["supported"]
    assert no_method["error"]["code"] == -32601
    assert no_tool["error"]["code"] == -32602


def test_ping_belongs_to_the_handshake_revisions_only(instance: Instance, programs: Any) -> None:
    """Revision 2026-07-28 removed it; asked in that revision, it does not exist."""
    anna = programs(instance.anna)

    modern = anna.ask("ping", {"_meta": META})
    anna.initialize()
    legacy = anna.ask("ping")

    assert modern["error"]["code"] == -32601
    assert legacy["result"] == {}


META_KEY = "io.modelcontextprotocol/protocolVersion"


def test_a_message_goes_there_and_the_answer_comes_back(instance: Instance, programs: Any) -> None:
    """The whole point, through two processes: Anna asks, Berta answers."""
    anna, berta = programs(instance.anna), programs(instance.berta)
    anna.initialize()
    berta.initialize()

    sent = json.loads(
        text_of(
            anna.call(
                "send_to_peers", recipients=["Berta"], subject="Yeast?", body="Do we have any?"
            )
        )
    )
    arrived = json.loads(text_of(berta.call("inbox")))["entries"][0]
    body = text_of(berta.call("message_body", message_id=arrived["message_id"]))
    berta.call(
        "send_to_peers",
        recipients=["Anna"],
        subject="Re: Yeast?",
        body="Two packets.",
        in_reply_to=arrived["message_id"],
    )
    answered = json.loads(text_of(anna.call("inbox")))["entries"][0]

    assert arrived["message_id"] == sent["message_id"]
    assert (arrived["sender_name"], arrived["subject"]) == ("Anna", "Yeast?")
    assert body == "Do we have any?"
    assert answered["in_reply_to"] == sent["message_id"]
    assert text_of(anna.call("message_body", message_id=answered["message_id"])) == "Two packets."


UNKNOWN_ID = "A" * 43

#: A provocation: the token to start the program with, the tool and its arguments,
#: and the same request made directly — verb, path, body (bytes for a raw one) and
#: token.
Case = tuple[str | None, str, dict[str, Any], tuple[str, str, Any, str | None]]


def no_token(i: Instance) -> Case:
    return None, "inbox", {}, ("GET", "/inbox", None, None)


def token_revoked(i: Instance) -> Case:
    token = i.revoked("Carla")
    return token, "inbox", {}, ("GET", "/inbox", None, token)


def wrong_token(i: Instance) -> Case:
    token = i.service(i.anna, "weather")
    return token, "own_team", {}, ("GET", "/team", None, token)


def not_realm_master(i: Instance) -> Case:
    token = i.invited_by(i.anna, "Dora")
    asked = {"service_name": "radio", "display_name": "for radio"}
    return token, "invite_service", asked, ("POST", "/invitations/service", asked, token)


def unknown_name(i: Instance) -> Case:
    return i.anna, "one_peer", {"name": "Nobody"}, ("GET", "/peers/Nobody", None, i.anna)


def unknown_identifier(i: Instance) -> Case:
    asked = {"message_id": UNKNOWN_ID}
    return i.anna, "envelope", asked, ("GET", f"/messages/{UNKNOWN_ID}", None, i.anna)


def name_taken(i: Instance) -> Case:
    asked = {"member_name": "Berta", "member_mission": "Again.", "display_name": "Berta again"}
    return i.anna, "invite_peer", asked, ("POST", "/invitations/peer", asked, i.anna)


def too_large(i: Instance) -> Case:
    text = "x" * 9000
    return i.anna, "set_my_self_image", {"text": text}, ("PUT", "/me/self", text.encode(), i.anna)


def invalid_input(i: Instance) -> Case:
    asked = {"subject": "x", "body": "y", "size": 3}
    return i.anna, "send_to_peers", asked, ("POST", "/peers/messages", asked, i.anna)


def invitation_used(i: Instance) -> Case:
    voucher = i.invitation("Erik")
    i.redeem(voucher)
    asked = {"invitation": voucher}
    return None, "redeem", asked, ("POST", "/invitations/redeem", asked, None)


#: Every rejection type of the catalogue that a tool can meet on this surface. Three
#: are not here, and cannot be: `wrong-verb` and `unknown-address` — every tool calls
#: an address of the description with the verb the description gives it, so no tool
#: can send another (a slash in a file name once reached `unknown-address`; the name is
#: now taken as the rest of the address and its directory parts dropped) — and
#: `internal-error`, which needs the service itself to break, and no call from
#: outside can arrange that.
REFUSALS = {
    "no-token": no_token,
    "token-revoked": token_revoked,
    "wrong-token": wrong_token,
    "not-realm-master": not_realm_master,
    "unknown-name": unknown_name,
    "unknown-identifier": unknown_identifier,
    "name-taken": name_taken,
    "too-large": too_large,
    "invalid-input": invalid_input,
    "invitation-used": invitation_used,
}


@pytest.mark.parametrize("kind", sorted(REFUSALS))
def test_every_refusal_comes_through_unchanged(
    kind: str, instance: Instance, programs: Any
) -> None:
    """Status, type and teaching text, exactly as the service sends them directly."""
    token, tool, arguments, (verb, path, body, direct_token) = REFUSALS[kind](instance)
    program = programs(token)
    program.initialize()

    result = program.call(tool, **arguments)
    raw = body if isinstance(body, bytes) else None
    status, direct = http(verb, f"{instance.base}{path}", None if raw else body, direct_token, raw)

    assert direct["type"] == kind, direct
    assert result["isError"] is True
    said = text_of(result)
    assert f"status: {status}" in said
    assert f"type: {direct['type']}" in said
    assert direct["message"] in said


def test_a_file_goes_up_from_a_path_and_comes_down_to_one(
    instance: Instance, programs: Any, tmp_path: Path
) -> None:
    """Bytes that are not text, and not one of them changed on the way."""
    original = bytes(range(256)) * 64
    (tmp_path / "up.bin").write_bytes(original)
    anna = programs(instance.anna)
    anna.initialize()

    deposited = json.loads(text_of(anna.call("deposit", path=str(tmp_path / "up.bin"))))
    saved = anna.call(
        "fetch",
        file_id=deposited["file_id"],
        file_name="copy.bin",
        save_to=str(tmp_path / "down.bin"),
    )
    unsaved = anna.call("fetch", file_id=deposited["file_id"], file_name="copy.bin")

    assert deposited["size"] == len(original)
    assert saved["isError"] is False, text_of(saved)
    assert (tmp_path / "down.bin").read_bytes() == original
    assert unsaved["isError"] is True and "save_to" in text_of(unsaved)


def test_the_deposit_tool_says_to_agree_on_co_location_first(
    instance: Instance, programs: Any
) -> None:
    anna = programs(instance.anna)
    anna.initialize()

    tools = {tool["name"]: tool for tool in anna.ask("tools/list")["result"]["tools"]}

    said = tools["deposit"]["description"]
    assert "same machine" in said and "send the path in the body" in said


def test_the_raw_self_image_is_a_plain_string(instance: Instance, programs: Any) -> None:
    anna = programs(instance.anna)
    anna.initialize()

    written = anna.call("set_my_self_image", text="I know where the *yeast* is.\n")

    assert written["isError"] is False, text_of(written)
    assert text_of(anna.call("my_self_image")) == "I know where the *yeast* is.\n"


def test_a_subscription_to_the_inbox_hears_a_delivery(instance: Instance, programs: Any) -> None:
    """The handshake way: subscribe, a message arrives, the change is announced."""
    anna = programs(instance.anna)
    berta = programs(instance.berta, A2A_MCP_POLL_SECONDS="0.2")
    anna.initialize()
    berta.initialize()

    resources = berta.ask("resources/list")["result"]["resources"]
    assert berta.ask("resources/subscribe", {"uri": "simple-a2a://inbox"})["result"] == {}
    anna.call("send_to_peers", recipients=["Berta"], subject="Ping", body="Are you there?")
    heard = berta.wait(lambda m: m.get("method") == "notifications/resources/updated")
    read = berta.ask("resources/read", {"uri": "simple-a2a://inbox"})["result"]

    assert [r["uri"] for r in resources] == ["simple-a2a://inbox"]
    assert "does not wake a sleeping one" in resources[0]["description"]
    assert heard["params"]["uri"] == "simple-a2a://inbox"
    assert json.loads(read["contents"][0]["text"])["entries"][0]["subject"] == "Ping"


def test_a_listening_stream_hears_a_delivery(instance: Instance, programs: Any) -> None:
    """The current way: listen, get the acknowledgement, then the tagged notification."""
    anna = programs(instance.anna)
    berta = programs(instance.berta, A2A_MCP_POLL_SECONDS="0.2")
    anna.initialize()

    berta.send(
        {
            "jsonrpc": "2.0",
            "id": "listening",
            "method": "subscriptions/listen",
            "params": {
                "_meta": META,
                "notifications": {
                    "resourceSubscriptions": ["simple-a2a://inbox"],
                    "toolsListChanged": True,
                },
            },
        }
    )
    acknowledged = berta.wait(
        lambda m: m.get("method") == "notifications/subscriptions/acknowledged"
    )
    anna.call("send_to_peers", recipients=["Berta"], subject="Pong", body="Here.")
    heard = berta.wait(lambda m: m.get("method") == "notifications/resources/updated")
    berta.send(
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "listening"},
        }
    )

    tag = "io.modelcontextprotocol/subscriptionId"
    assert acknowledged["params"]["_meta"][tag] == "listening"
    assert acknowledged["params"]["notifications"] == {
        "resourceSubscriptions": ["simple-a2a://inbox"]
    }, "what is not honoured is left out of the acknowledgement"
    assert heard["params"]["_meta"][tag] == "listening"


def test_nothing_but_protocol_goes_to_standard_output(instance: Instance, programs: Any) -> None:
    """Every line a JSON-RPC message — the reader thread would have failed otherwise."""
    anna = programs(instance.anna)
    anna.initialize()
    anna.call("inbox")

    for line in anna.lines:
        assert json.loads(line)["jsonrpc"] == "2.0"


# ------------------------------------------------------------------ refusing to start


@pytest.mark.parametrize("given", [{"A2A_MCP_TOKEN": "t"}, {}])
def test_without_an_address_it_does_not_start_and_says_so(given: dict[str, str]) -> None:
    started = subprocess.run(
        [sys.executable, str(PROGRAM)],
        env={"PATH": os.environ.get("PATH", ""), **given},
        input=b"",
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )

    assert started.returncode == 2
    assert started.stdout == b"", "standard output is the protocol's"
    assert "A2A_MCP_ADDRESS" in started.stderr.decode()


def test_with_only_an_invitation_it_starts_and_redeeming_works(
    instance: Instance, programs: Any
) -> None:
    """The way an agent handed an invitation begins: start without a token, redeem.

    The new token is in the redeem result, once — the one moment it exists — and
    the second instance, started with it, works as that identity.
    """
    voucher = instance.invitation("Fiona")
    bare = programs(None)

    said = bare.initialize()["result"]["instructions"]
    redeemed = bare.call("redeem", invitation=voucher)
    token = json.loads(text_of(redeemed))["token"]
    refused = bare.call("inbox")
    second = programs(token)
    second.initialize()
    me = second.call("me")

    assert said.startswith("This MCP server is not the contract.")
    assert "started without a token" in said and "`redeem`" in said
    assert "A2A_MCP_TOKEN" in said
    assert redeemed["isError"] is False
    assert "".join(bare.lines).count(token) == 1, "the new token appears exactly once"
    assert refused["isError"] is True and "type: no-token" in text_of(refused)
    assert me["isError"] is False and "Fiona" in text_of(me)


def test_without_a_token_a_subscription_is_refused_in_the_service_words(
    instance: Instance, programs: Any
) -> None:
    """Not a subscription that never hears anything: the refusal, as the service gave it."""
    bare = programs(None)
    bare.initialize()

    subscribed = bare.ask("resources/subscribe", {"uri": "simple-a2a://inbox"})
    listened = bare.ask(
        "subscriptions/listen",
        {"_meta": META, "notifications": {"resourceSubscriptions": ["simple-a2a://inbox"]}},
    )

    for answer in (subscribed, listened):
        assert answer["error"]["data"]["type"] == "no-token"
        assert "type: no-token" in answer["error"]["message"]


def test_an_open_stream_is_closed_with_its_result_when_the_input_ends(
    instance: Instance, programs: Any
) -> None:
    """An orderly end the client can tell from a dropped connection."""
    berta = programs(instance.berta)
    berta.send(
        {
            "jsonrpc": "2.0",
            "id": "stream",
            "method": "subscriptions/listen",
            "params": {
                "_meta": META,
                "notifications": {"resourceSubscriptions": ["simple-a2a://inbox"]},
            },
        }
    )
    berta.wait(lambda m: m.get("method") == "notifications/subscriptions/acknowledged")

    stdout, _ = berta.close()

    closing = [json.loads(line) for line in stdout.splitlines()][-1]
    assert closing["id"] == "stream"
    assert closing["result"]["resultType"] == "complete"
    assert closing["result"]["_meta"]["io.modelcontextprotocol/subscriptionId"] == "stream"


def test_a_redirect_is_never_followed(tmp_path: Path) -> None:
    """A redirect would carry the token to whatever address it names; it is answered, not taken.

    Two small servers: one that describes an inbox and redirects every call to it,
    and one at the redirect's target that records whoever arrives.
    """
    import http.server

    token = "a-token-that-must-stay-home"
    arrived: list[dict[str, str]] = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            arrived.append(dict(self.headers))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
    elsewhere = f"http://127.0.0.1:{target.server_address[1]}/inbox"
    described = {
        "paths": {
            "/inbox": {
                "get": {
                    "operationId": "inbox",
                    "summary": "The inbox.",
                    "parameters": [{"name": "authorization", "in": "header"}],
                }
            }
        }
    }

    class Redirecting(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/openapi.json":
                body = json.dumps(described).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(302)
            self.send_header("Location", elsewhere)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    source = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirecting)
    for server in (target, source):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        program = Program(
            {
                "A2A_MCP_ADDRESS": f"http://127.0.0.1:{source.server_address[1]}",
                "A2A_MCP_TOKEN": token,
            }
        )
        program.initialize()
        result = program.call("inbox")
        stdout, stderr = program.close()
    finally:
        for server in (target, source):
            server.shutdown()

    assert result["isError"] is True
    assert "302" in text_of(result)
    assert arrived == [], "nothing reached the redirect's target, least of all the token"
    assert token not in stdout and token not in stderr


def test_arguments_are_refused_because_they_stand_in_the_process_list() -> None:
    started = subprocess.run(
        [sys.executable, str(PROGRAM), "--token", "secret-on-the-command-line"],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )

    assert started.returncode == 2
    assert "A2A_MCP_TOKEN" in started.stderr.decode()


def test_an_address_without_a_description_is_refused_clearly() -> None:
    token = "a-token-that-must-not-be-repeated"
    started = subprocess.run(
        [sys.executable, str(PROGRAM)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "A2A_MCP_ADDRESS": f"http://127.0.0.1:{free_port()}",
            "A2A_MCP_TOKEN": token,
        },
        input=b"",
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )

    assert started.returncode == 1
    assert "/openapi.json" in started.stderr.decode()
    assert token not in started.stderr.decode()


def test_an_address_that_is_not_the_participant_surface_is_refused(instance: Instance) -> None:
    """The administration surface also takes tokens; it is not what this program is for."""
    started = subprocess.run(
        [sys.executable, str(PROGRAM)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "A2A_MCP_ADDRESS": instance.admin,
            "A2A_MCP_TOKEN": ADMIN_SECRET,
        },
        input=b"",
        capture_output=True,
        timeout=PATIENCE,
        check=False,
    )

    assert started.returncode == 1
    assert "participant surface" in started.stderr.decode()
    assert ADMIN_SECRET not in started.stderr.decode()


def test_the_running_instance_serves_the_package_of_the_tree(instance: Instance) -> None:
    from simple_a2a.describe import mcp_package

    with urllib.request.urlopen(f"{instance.base}/mcp.zip", timeout=PATIENCE) as answer:
        served = answer.read()

    assert served == mcp_package.build_archive()
