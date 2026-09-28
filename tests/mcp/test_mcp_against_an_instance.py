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


def http(method: str, url: str, body: Any = None, token: str | None = None) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
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

    def member(self, name: str) -> str:
        _, answer = http(
            "POST",
            f"{self.admin}/realms/household/teams/kitchen/invitations",
            {"member_name": name, "member_mission": f"{name} helps.", "display_name": name},
            ADMIN_SECRET,
        )
        status, redeemed = http(
            "POST", f"{self.base}/invitations/redeem", {"invitation": answer["invitation"]}
        )
        assert status == 200, redeemed
        return redeemed["token"]


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
    """Start programs for tokens; at the end, none of them has let its token out."""
    started: list[tuple[Program, str]] = []

    def start(token: str, **extra: str) -> Program:
        program = Program({"A2A_MCP_ADDRESS": instance.base, "A2A_MCP_TOKEN": token, **extra})
        started.append((program, token))
        return program

    yield start
    for program, token in started:
        stdout, stderr = program.close()
        assert program.process.returncode == 0, stderr
        assert token not in stdout, "the token left the program on standard output"
        assert token not in stderr, "the token left the program on standard error"


# ------------------------------------------------------------------ the checks


def test_the_tools_are_exactly_the_operations_that_take_a_token(
    instance: Instance, programs: Any
) -> None:
    """Both directions, no exception list: every operation a tool, every tool an operation."""
    _, document = http("GET", f"{instance.base}/openapi.json")
    expected = {}
    for path, verbs in document["paths"].items():
        for verb, operation in verbs.items():
            if any(
                p["in"] == "header" and p["name"].lower() == "authorization"
                for p in operation.get("parameters", [])
            ):
                expected[operation["operationId"]] = f"`{verb.upper()} {path}`"
    anna = programs(instance.anna)
    anna.initialize()

    tools = anna.ask("tools/list")["result"]["tools"]

    assert {tool["name"] for tool in tools} == set(expected)
    for tool in tools:
        assert expected[tool["name"]] in tool["description"], tool["name"]
        assert tool["inputSchema"]["type"] == "object"
        assert "$ref" not in json.dumps(tool["inputSchema"]), "a schema has to stand alone"
    assert len(tools) == 27


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
    assert len(listed["tools"]) == 27


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


def test_a_refusal_comes_through_unchanged(instance: Instance, programs: Any) -> None:
    """Status, type and teaching text, exactly as the service sent them."""
    status, direct = http("GET", f"{instance.base}/peers/Nobody", token=instance.anna)
    anna = programs(instance.anna)
    anna.initialize()

    result = anna.call("one_peer", name="Nobody")

    assert status != 200
    assert result["isError"] is True
    said = text_of(result)
    assert f"status: {status}" in said
    assert f"type: {direct['type']}" in said
    assert direct["message"] in said


def test_a_malformed_body_is_refused_by_the_service_in_its_own_words(
    instance: Instance, programs: Any
) -> None:
    """An argument the tool does not know goes to the service, whose text is better."""
    anna = programs(instance.anna)
    anna.initialize()

    result = anna.call("send_to_peers", subject="x", body="y", size=3)

    assert result["isError"] is True
    assert "type: " in text_of(result)


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


@pytest.mark.parametrize(
    ("given", "named"),
    [
        ({"A2A_MCP_TOKEN": "t"}, ["A2A_MCP_ADDRESS"]),
        ({"A2A_MCP_ADDRESS": "http://127.0.0.1:1"}, ["A2A_MCP_TOKEN"]),
        ({}, ["A2A_MCP_ADDRESS", "A2A_MCP_TOKEN"]),
    ],
)
def test_without_its_pair_it_does_not_start_and_says_what_is_missing(
    given: dict[str, str], named: list[str]
) -> None:
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
    for variable in named:
        assert variable in started.stderr.decode()


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
