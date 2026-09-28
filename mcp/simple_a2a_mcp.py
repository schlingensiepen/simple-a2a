#!/usr/bin/env python3
"""An MCP server for the participant surface of a simple-a2a installation.

**This program is not the contract.** The contract is the self-description of the
installation it is started against: the entry at the base address, the guide under
`/guide`, and the interface description at `/openapi.json`. Every tool offered here
is generated from that description when the program starts — one tool per
operation, everything but the self-description — so a tool cannot describe an
operation the installation does not have, and an operation cannot be missing a
tool. Where a pipe cannot carry what an operation takes or gives, the tool is
adapted by hand, and only there: a file is deposited **from a local path**, a file
is fetched **to a local path**, and a raw text body is a plain string argument.

**One process, one identity.** It is started with exactly one base address and at
most one token, both from the environment rather than the command line, because
arguments stand in the process list for anybody to read. Whoever holds two
identities starts two processes; a parameter deciding which token to send with
would be the one mistake this shape rules out. Started without a token it offers
the same tools — and redeeming an invitation is the one that will work, which is
how somebody who was handed an invitation rather than a token gets going.

**Only the standard library.** Nothing else is installed next to an agent to run
this, so nothing else can break it or be broken into through it. The price is that
the protocol is spoken here by hand: JSON-RPC 2.0, one message per line, over
standard input and output. Standard output carries protocol messages and nothing
else; everything meant for a human goes to standard error. Messages are handled one
after the other, so a slow call delays the next — a cancellation included.

**Two protocol eras.** Revision 2026-07-28 made the protocol stateless: every
request carries its version in `_meta`, `server/discover` replaces the handshake,
and `subscriptions/listen` replaces `resources/subscribe`. Harnesses in use still
open with `initialize`. Both are answered, each in its own terms, because an MCP
server that only one kind of harness can start is a third of an offer.

**The inbox is a resource**, and a subscription to it makes this program ask the
service at intervals and say when the listing changed. That makes a *running*
agent responsive. It does not wake a sleeping one: nothing reaches an agent that
is not running, and nothing is kept for it here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NAME = "simple-a2a-mcp"
#: The release of the service this program ships with. It is the same for every
#: instance of that release, which is why it may be written here: the program is
#: an artefact of the release, not of an installation.
VERSION = "0.1.0.dev0"

#: The environment, and nothing else. Deliberately outside the service's own
#: `SIMPLE_A2A_*` namespace: those are the operational parameters of the service,
#: and a client's settings in the same namespace would read like a ninth one.
ADDRESS_VARIABLE = "A2A_MCP_ADDRESS"
TOKEN_VARIABLE = "A2A_MCP_TOKEN"
POLL_VARIABLE = "A2A_MCP_POLL_SECONDS"
POLL_DEFAULT = 15.0

#: How long one call to the service may take. Generous, because a file of the
#: default maximum size has to fit through it on an ordinary line.
HTTP_TIMEOUT = 120

#: Revisions spoken per request, and revisions opened with `initialize`. The
#: legacy ones differ from each other in nothing this program uses.
MODERN = ("2026-07-28",)
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SUPPORTED = MODERN + LEGACY

META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER = "io.modelcontextprotocol/serverInfo"
META_SUBSCRIPTION = "io.modelcontextprotocol/subscriptionId"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_VERSION = -32022
#: What "no such resource" was before 2026-07-28, when it became -32602.
LEGACY_NOT_FOUND = -32002

INBOX_URI = "simple-a2a://inbox"
INBOX_PATH = "/inbox"

#: The one hour a listing of tools stays true for: they are fixed for the life of
#: this process, and a restart is the only thing that changes them.
LIST_TTL_MS = 3_600_000

TOOL_NAME = re.compile(r"[^A-Za-z0-9_.-]")

UPLOAD_HINT = (
    "Before you use this, agree with the other agent whether the two of you run on the "
    "same machine. If you do, do not upload: grant each other read access and send the "
    "path in the body of a message instead — the other side reads the file where it "
    "lies. Depositing is the fallback for separate machines. This tool reads the file "
    "at `path` on the machine this MCP server runs on and deposits its bytes unchanged."
)

DOWNLOAD_HINT = (
    "Give `save_to` — a path on the machine this MCP server runs on — to have the bytes "
    "written there unchanged; for anything that is not text that is the only way that "
    "keeps them intact. Without it, text comes back as text."
)


def log(message: str) -> None:
    """One line for a human, on standard error — standard output is the protocol's."""
    sys.stderr.write(f"{NAME}: {_redact(message)}\n")
    sys.stderr.flush()


#: The token this process runs with, once it is known, so that nothing leaving the
#: process can carry it — not a log line, not a tool result, not an error. Only this
#: one: a token *redeemed* through a tool is a different string, and its one
#: appearance, in that tool's result, is the point of redeeming.
_SECRET: list[str] = []


def _redact(text: str) -> str:
    for secret in _SECRET:
        text = text.replace(secret, "<token>")
    return text


# ------------------------------------------------------------------ settings


class StartRefused(Exception):
    """A reason not to start, worded for whoever reads standard error."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Settings:
    address: str
    #: None when started with an invitation rather than a token: then redeeming is
    #: the one call that will succeed, and every other one is refused by the
    #: service itself, in its own words.
    token: str | None
    poll_seconds: float

    @classmethod
    def from_environment(cls, environment: dict[str, str] | os._Environ[str]) -> Settings:
        """The address, or a refusal naming it; the token if there is one."""
        address = (environment.get(ADDRESS_VARIABLE) or "").strip()
        token = (environment.get(TOKEN_VARIABLE) or "").strip() or None
        if not address:
            raise StartRefused(
                f"{ADDRESS_VARIABLE} is not set. Start this program with {ADDRESS_VARIABLE} "
                "set to the base address of the participant surface and, once you have one, "
                f"{TOKEN_VARIABLE} set to the token of the one identity it acts as — both in "
                "the environment, not on the command line.",
                2,
            )
        if not address.startswith(("http://", "https://")):
            raise StartRefused(
                f"{ADDRESS_VARIABLE} is not an address: it has to start with http:// or "
                "https://, the way the entry of the participant surface names it.",
                2,
            )
        raw_poll = (environment.get(POLL_VARIABLE) or "").strip()
        try:
            poll = float(raw_poll) if raw_poll else POLL_DEFAULT
        except ValueError:
            poll = -1.0
        if not poll > 0:
            raise StartRefused(
                f"{POLL_VARIABLE} has to be a number of seconds above zero, or unset for "
                f"{POLL_DEFAULT:g}.",
                2,
            )
        return cls(address=address.rstrip("/"), token=token, poll_seconds=poll)


# ------------------------------------------------------------------ the service


@dataclass(frozen=True)
class Answer:
    status: int
    content_type: str
    data: bytes

    def is_json(self) -> bool:
        return self.content_type.split(";")[0].strip().lower() == "application/json"

    def is_text(self) -> bool:
        return self.content_type.split(";")[0].strip().lower().startswith("text/")


class Unreachable(Exception):
    """The service did not answer at all — which is not the same as saying no."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is answered as what it is, never followed.

    Following one would carry the token to whatever address the answer names, and
    the service never redirects: an address that does is not the one this process
    was started for.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Service:
    """The participant surface, as an ordinary HTTP client sees it."""

    def __init__(self, address: str, token: str | None) -> None:
        self.address = address
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect())

    def description(self) -> dict[str, Any]:
        """The interface description. It answers without a token, so none is sent."""
        answer = self.request("GET", "/openapi.json", with_token=False)
        if answer.status != 200:
            raise Unreachable(f"GET /openapi.json answered with status {answer.status}")
        try:
            document = json.loads(answer.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Unreachable(f"GET /openapi.json did not answer with JSON ({exc})") from None
        if not isinstance(document, dict):
            raise Unreachable("GET /openapi.json did not answer with a JSON object")
        return document

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        with_token: bool = True,
    ) -> Answer:
        sent = dict(headers or {})
        if with_token and self._token:
            sent["Authorization"] = f"Bearer {self._token}"
        if content_type is not None:
            sent["Content-Type"] = content_type
        sent.setdefault("Accept", "application/json, text/markdown, */*")
        request = urllib.request.Request(
            self.address + path, data=body, method=method, headers=sent
        )
        try:
            with self._opener.open(request, timeout=HTTP_TIMEOUT) as response:
                return Answer(
                    response.status, response.headers.get("Content-Type", ""), response.read()
                )
        except urllib.error.HTTPError as refused:
            with refused:
                return Answer(refused.code, refused.headers.get("Content-Type", ""), refused.read())
        except (urllib.error.URLError, OSError, ValueError) as failed:
            reason = getattr(failed, "reason", failed)
            raise Unreachable(str(reason)) from None


# ------------------------------------------------------------------ the tools


class DescriptionError(Exception):
    """The interface description holds something this program cannot map."""


@dataclass
class Operation:
    """One operation of the participant surface, and the tool that calls it."""

    method: str
    path: str
    name: str
    description: str
    input_schema: dict[str, Any]
    #: Whether the operation reads a token. Only then is one sent: redeeming an
    #: invitation never sees the token of the instance that redeems.
    takes_token: bool = True
    parameters: dict[str, str] = field(default_factory=dict)  # argument -> where it goes
    body_kind: str | None = None  # "json", "text" or "file"
    body_content_type: str | None = None
    body_fields: set[str] = field(default_factory=set)
    save_to: bool = False

    def tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _pointer(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise DescriptionError(f"a reference outside the description: {reference}")
    target: Any = document
    for part in reference[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise DescriptionError(f"a reference to nothing: {reference}")
        target = target[part]
    return target


def inline(node: Any, document: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """The same schema with every local reference replaced by what it points at.

    A tool's input schema has to stand on its own: a harness receives it without
    the description it came from.
    """
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str):
            if reference in seen:
                raise DescriptionError(f"a schema that contains itself: {reference}")
            resolved = inline(_pointer(document, reference), document, (*seen, reference))
            rest = {key: inline(value, document, seen) for key, value in node.items()}
            rest.pop("$ref")
            return {**resolved, **rest}
        return {key: inline(value, document, seen) for key, value in node.items()}
    if isinstance(node, list):
        return [inline(item, document, seen) for item in node]
    return node


def _self_description(method: str, parameters: list[dict[str, Any]]) -> bool:
    """A token-free read: the entry, the guide, the packages, health, build.

    They describe the service rather than use it, and an agent reads them as they
    are. Everything else is an operation and becomes a tool — redeeming an
    invitation too, which takes no token and is exactly what an instance started
    without one is for.
    """
    return method == "get" and not _takes_a_token(parameters)


def _takes_a_token(parameters: list[dict[str, Any]]) -> bool:
    return any(
        parameter.get("in") == "header"
        and str(parameter.get("name", "")).lower() == "authorization"
        for parameter in parameters
    )


def _media(content: dict[str, Any]) -> list[str]:
    return [key.split(";")[0].strip().lower() for key in content]


def _tool_name(operation: dict[str, Any], method: str, path: str) -> str:
    raw = str(operation.get("operationId") or f"{method}_{path}")
    name = TOOL_NAME.sub("_", raw).strip("_")[:128]
    if not name:
        raise DescriptionError(f"{method.upper()} {path} has no usable name")
    return name


def operations_of(document: dict[str, Any]) -> list[Operation]:
    """Every operation of the surface, as a tool, in the order they are described.

    Only the self-description is left out; see `_self_description`.
    """
    found: list[Operation] = []
    names: set[str] = set()
    for path, verbs in (document.get("paths") or {}).items():
        if not isinstance(verbs, dict):
            continue
        for method, operation in verbs.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            parameters = inline(operation.get("parameters") or [], document)
            if _self_description(method.lower(), parameters):
                continue
            made = _operation(document, method.upper(), path, operation, parameters)
            made.takes_token = _takes_a_token(parameters)
            if made.name in names:
                raise DescriptionError(f"two operations would both be the tool {made.name!r}")
            names.add(made.name)
            found.append(made)
    return found


def _operation(
    document: dict[str, Any],
    method: str,
    path: str,
    operation: dict[str, Any],
    parameters: list[dict[str, Any]],
) -> Operation:
    where = f"{method} {path}"
    properties: dict[str, Any] = {}
    required: list[str] = []
    made = Operation(method=method, path=path, name="", description="", input_schema={})

    def claim(name: str, schema: dict[str, Any], is_required: bool) -> None:
        if name in properties:
            raise DescriptionError(f"{where}: two inputs are both called {name!r}")
        properties[name] = schema
        if is_required:
            required.append(name)

    for parameter in parameters:
        place = parameter.get("in")
        name = str(parameter.get("name", ""))
        if place == "header" and name.lower() == "authorization":
            continue
        if place not in ("path", "query", "header"):
            raise DescriptionError(f"{where}: a parameter in {place!r} cannot be sent")
        schema = dict(parameter.get("schema") or {})
        if parameter.get("description"):
            schema["description"] = parameter["description"]
        claim(name, schema, bool(parameter.get("required")) or place == "path")
        made.parameters[name] = place

    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    media = _media(content)
    body_required = bool(body.get("required"))
    if "application/json" in media:
        key = list(content)[media.index("application/json")]
        schema = inline((content[key] or {}).get("schema") or {}, document)
        if schema.get("type") != "object":
            raise DescriptionError(f"{where}: a JSON body that is not an object")
        for name, property_schema in (schema.get("properties") or {}).items():
            claim(name, property_schema, name in (schema.get("required") or []))
            made.body_fields.add(name)
        made.body_kind, made.body_content_type = "json", "application/json"
    elif media and all(kind.startswith("text/") for kind in media):
        # A raw text body: a string carries it through the pipe unchanged.
        key = next(iter(content))
        schema = dict((content[key] or {}).get("schema") or {"type": "string"})
        schema["type"] = "string"
        schema["description"] = body.get("description") or schema.get("description") or ""
        claim("text", schema, body_required)
        made.body_kind, made.body_content_type = "text", f"{media[0]}; charset=utf-8"
    elif media:
        # Raw bytes: a pipe of text cannot carry them intact, a local path can.
        claim(
            "path",
            {
                "type": "string",
                "description": "The file to deposit, as a path on the machine this MCP "
                "server runs on. Its bytes are sent unchanged. " + (body.get("description") or ""),
            },
            True,
        )
        made.body_kind, made.body_content_type = "file", media[0]

    answer = ((operation.get("responses") or {}).get("200") or {}).get("content") or {}
    if any(kind != "application/json" and not kind.startswith("text/") for kind in _media(answer)):
        claim(
            "save_to",
            {
                "type": "string",
                "description": "Where to write the bytes, as a path on the machine this MCP "
                "server runs on. An existing file there is replaced.",
            },
            False,
        )
        made.save_to = True

    summary = str(operation.get("summary") or "").strip()
    detail = str(operation.get("description") or "").strip()
    text = summary if not detail or detail == summary else f"{summary}\n\n{detail}".strip()
    extras = [f"This is `{where}` of the participant surface; the guide explains it."]
    if made.body_kind == "file":
        extras.insert(0, UPLOAD_HINT)
    if made.save_to:
        extras.insert(0, DOWNLOAD_HINT)
    made.name = _tool_name(operation, method, path)
    made.description = "\n\n".join([text, *extras]) if text else "\n\n".join(extras)
    made.input_schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        made.input_schema["required"] = required
    if made.body_kind == "json":
        # Unknown names go to the service in the body, which refuses them with its
        # own teaching text — a better answer than any this program could give.
        made.input_schema.pop("additionalProperties")
    return made


# ------------------------------------------------------------------ calling


def _text_result(text: str, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def refusal_text(answer: Answer) -> str:
    """A refusal of the service, passed on as it came: status, type and message.

    Nothing is reworded. The message is the service's teaching text for exactly
    this operation and this failure, and a paraphrase could only lose something.
    """
    try:
        body = json.loads(answer.data.decode("utf-8"))
        kind, message = body["type"], body["message"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raw = answer.data.decode("utf-8", errors="replace")
        return f"The service answered with HTTP status {answer.status}.\n\n{raw}"
    return f"The service refused this call.\nstatus: {answer.status}\ntype: {kind}\n\n{message}"


def call(service: Service, operation: Operation, arguments: dict[str, Any]) -> dict[str, Any]:
    """One tool call, as one HTTP request."""
    unknown = sorted(
        name
        for name in arguments
        if name not in operation.input_schema["properties"] and operation.body_kind != "json"
    )
    if unknown:
        takes = ", ".join(operation.input_schema["properties"]) or "no arguments"
        return _text_result(
            f"{operation.name} does not take {', '.join(unknown)}. It takes: {takes}.",
            error=True,
        )
    missing = [
        name
        for name, place in operation.parameters.items()
        if place == "path" and arguments.get(name) in (None, "")
    ]
    if missing:
        return _text_result(
            f"{operation.name} needs {', '.join(missing)}: it is part of the address.",
            error=True,
        )

    path = operation.path
    query: list[tuple[str, str]] = []
    headers: dict[str, str] = {}
    for name, place in operation.parameters.items():
        value = arguments.get(name)
        if value is None:
            continue
        rendered = json.dumps(value) if isinstance(value, bool) else str(value)
        if place == "path":
            path = path.replace("{" + name + "}", urllib.parse.quote(rendered, safe=""))
        elif place == "query":
            query.append((name, rendered))
        else:
            headers[name] = rendered
    if query:
        path += "?" + urllib.parse.urlencode(query)

    body: bytes | None = None
    if operation.body_kind == "json":
        payload = {
            name: value
            for name, value in arguments.items()
            if name not in operation.parameters and name != "save_to"
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    elif operation.body_kind == "text":
        body = str(arguments.get("text") or "").encode("utf-8")
    elif operation.body_kind == "file":
        local = arguments.get("path")
        if not local:
            return _text_result(f"{operation.name} needs `path`: the file to deposit.", error=True)
        try:
            body = Path(str(local)).expanduser().read_bytes()
        except OSError as exc:
            return _text_result(
                f"Could not read {local} on this machine: {exc.strerror or exc}. Nothing was sent.",
                error=True,
            )

    try:
        answer = service.request(
            operation.method,
            path,
            body=body,
            content_type=operation.body_content_type if body is not None else None,
            headers=headers,
            with_token=operation.takes_token,
        )
    except Unreachable as failed:
        return _text_result(
            f"Could not reach the service at {service.address}: {failed}. If this was a "
            "send, look at your outbox before sending again — the request may have "
            "arrived even though no answer came back.",
            error=True,
        )
    if answer.status != 200:
        return _text_result(refusal_text(answer), error=True)

    save_to = arguments.get("save_to") if operation.save_to else None
    if save_to:
        target = Path(str(save_to)).expanduser()
        try:
            target.write_bytes(answer.data)
        except OSError as exc:
            return _text_result(
                f"The service answered, but {target} could not be written: {exc.strerror or exc}.",
                error=True,
            )
        return _text_result(f"Saved {len(answer.data)} bytes to {target}.")
    if answer.is_json():
        try:
            parsed = json.loads(answer.data.decode("utf-8"))
            return _text_result(json.dumps(parsed, ensure_ascii=False, indent=2))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    try:
        return _text_result(answer.data.decode("utf-8"))
    except UnicodeDecodeError:
        return _text_result(
            f"The answer is {len(answer.data)} bytes that are not text. Call again with "
            "`save_to` to have them written to a file unchanged.",
            error=True,
        )


# ------------------------------------------------------------------ the server


def instructions(address: str, poll_seconds: float, *, has_token: bool, redeem: str) -> str:
    """What a harness is told first. The first sentence is the one that matters."""
    without = (
        f"This instance was started without a token, so only redeeming will work: call "
        f"`{redeem}` with the invitation you were given. It answers with your token, "
        f"once — that is the one moment it exists. Then start an instance of this server "
        f"with {TOKEN_VARIABLE} set to that token and work there; every other tool here "
        f"is refused by the service with `no-token`.\n\n"
    )
    return (
        f"This MCP server is not the contract. The contract is the self-description of "
        f"the simple-a2a participant surface at {address} — its entry at {address}/, the "
        f"guide at {address}/guide and the interface description at "
        f"{address}/openapi.json. Read the guide before your first call: it says what "
        f"goes wrong otherwise. Every tool here was generated from that interface "
        f"description when this server started, one per operation; where a tool and the "
        f"guide seem to disagree, the guide is right.\n\n"
        + ("" if has_token else without)
        + f"This server acts as exactly one identity, the one whose token it was started "
        f"with. To act as another, redeem its invitation with `{redeem}` and start a "
        f"second instance with the token that gives you — one instance per identity.\n\n"
        f"Your inbox is the resource {INBOX_URI}. Subscribe to it and this server asks "
        f"the service every {poll_seconds:g} seconds and tells you when it changed. That "
        f"makes a running agent responsive; it does not wake a sleeping one. While you "
        f"are not running nothing reaches you, so read your inbox whenever you resume.\n\n"
        f"Before you exchange a file, agree with the other agent whether you run on the "
        f"same machine; if you do, send a path in the body of a message instead of "
        f"depositing the file.\n\n"
        f"Calls are handled one after the other: a slow call delays the next, a "
        f"cancellation included."
    )


def inbox_resource(poll_seconds: float) -> dict[str, Any]:
    return {
        "uri": INBOX_URI,
        "name": "inbox",
        "title": "Your inbox",
        "description": (
            f"What arrived for this identity, newest first, envelopes only: the answer of "
            f"GET {INBOX_PATH} at the moment you read it. Subscribe and this server asks "
            f"the service every {poll_seconds:g} seconds and tells you when the listing "
            f"changed; then read it. That makes a running agent responsive. It does not "
            f"wake a sleeping one — while you are not running nothing reaches you and "
            f"nothing is kept for you here, so read your inbox whenever you resume."
        ),
        "mimeType": "application/json",
    }


class ProtocolError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class Output:
    """Standard output, one message per line, and never two writers at once."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, message: dict[str, Any]) -> None:
        line = _redact(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        with self._lock:
            self._stream.write(line.encode("utf-8") + b"\n")
            self._stream.flush()


class Watch:
    """Asking the service about the inbox, for as long as anybody listens.

    The baseline is taken when the first subscription arrives, before it is
    answered: a message that arrives right after the answer then counts as a
    change instead of disappearing into the first look.
    """

    def __init__(self, service: Service, interval: float, output: Output) -> None:
        self._service = service
        self._interval = interval
        self._output = output
        self._lock = threading.Lock()
        self._legacy = False
        self._streams: set[Any] = set()
        self._last: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _look(self) -> str | None:
        try:
            answer = self._service.request("GET", INBOX_PATH)
        except Unreachable as failed:
            log(f"looking at the inbox failed: {failed}")
            return None
        if answer.status != 200:
            log(f"looking at the inbox was refused: {refusal_text(answer)}")
            return None
        return hashlib.sha256(answer.data).hexdigest()

    def _ensure_running(self) -> None:
        if self._last is None:
            self._last = self._look()
        if self._thread is None or not self._thread.is_alive():
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
            self._thread.start()

    def _stop_if_idle(self) -> None:
        if not self._legacy and not self._streams:
            self._stop.set()
            self._thread = None
            self._last = None

    def subscribe_legacy(self) -> None:
        with self._lock:
            self._legacy = True
            self._ensure_running()

    def unsubscribe_legacy(self) -> None:
        with self._lock:
            self._legacy = False
            self._stop_if_idle()

    def open_stream(self, subscription: Any) -> None:
        with self._lock:
            self._streams.add(subscription)
            self._ensure_running()

    def close_stream(self, subscription: Any) -> bool:
        with self._lock:
            if subscription not in self._streams:
                return False
            self._streams.discard(subscription)
            self._stop_if_idle()
            return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self, stop: threading.Event) -> None:
        while not stop.wait(self._interval):
            seen = self._look()
            with self._lock:
                if stop.is_set() or seen is None:
                    continue
                changed = self._last is not None and seen != self._last
                self._last = seen
                if not changed:
                    continue
                if self._legacy:
                    self._output.send(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/resources/updated",
                            "params": {"uri": INBOX_URI},
                        }
                    )
                for subscription in sorted(self._streams, key=str):
                    self._output.send(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/resources/updated",
                            "params": {
                                "_meta": {META_SUBSCRIPTION: subscription},
                                "uri": INBOX_URI,
                            },
                        }
                    )


class Server:
    """The protocol, both eras, over one pair of streams."""

    def __init__(self, settings: Settings, service: Service, tools: list[Operation]) -> None:
        self.settings = settings
        self.service = service
        self.tools = {operation.name: operation for operation in tools}
        self.order = [operation.name for operation in tools]
        self.negotiated: str | None = None
        self.output: Output | None = None
        self.watch: Watch | None = None
        #: Open `subscriptions/listen` requests, answered only when they end.
        self.listening: list[Any] = []
        redeeming = [op.name for op in tools if not op.takes_token]
        self.redeem = redeeming[0] if redeeming else "the tool that redeems an invitation"

    # -- the loop --------------------------------------------------------

    def run(self, source: Any, sink: Any) -> None:
        self.output = Output(sink)
        self.watch = Watch(self.service, self.settings.poll_seconds, self.output)
        try:
            for raw in source:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self.handle_line(line)
            # The input is closed: the client is done. Every stream still open is
            # ended with its closing result, so the client can tell an orderly end
            # from a dropped connection.
            for subscription in self.listening:
                self.output.send(
                    {
                        "jsonrpc": "2.0",
                        "id": subscription,
                        "result": {
                            "resultType": "complete",
                            "_meta": {META_SUBSCRIPTION: subscription},
                        },
                    }
                )
        finally:
            self.watch.stop()

    def handle_line(self, line: str) -> None:
        assert self.output is not None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            self.output.send(_error(None, PARSE_ERROR, "Not JSON."))
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            self.output.send(
                _error(None, INVALID_REQUEST, "One JSON-RPC 2.0 message per line, as an object.")
            )
            return
        method = message.get("method")
        if not isinstance(method, str):
            return  # a response from the client; this server never asks anything
        if "id" not in message:
            self.notification(method, message.get("params") or {})
            return
        identifier = message["id"]
        try:
            result = self.request(identifier, method, message.get("params") or {})
        except ProtocolError as failed:
            self.output.send(_error(identifier, failed.code, failed.message, failed.data))
            return
        except Exception as failed:  # noqa: BLE001 - one broken call must not end the process
            log(f"{method} failed: {failed!r}")
            self.output.send(_error(identifier, INTERNAL_ERROR, "Something went wrong in here."))
            return
        if result is not None:
            self.output.send({"jsonrpc": "2.0", "id": identifier, "result": result})

    def notification(self, method: str, params: Any) -> None:
        assert self.watch is not None
        if method == "notifications/cancelled" and isinstance(params, dict):
            # Ends a listening stream, with no further message for it. A plain request
            # is answered before the next line is read, so there is nothing else
            # left to cancel.
            subscription = params.get("requestId")
            if subscription in self.listening:
                self.listening.remove(subscription)
            self.watch.close_stream(subscription)

    # -- dispatch --------------------------------------------------------

    def request(self, identifier: Any, method: str, params: Any) -> dict[str, Any] | None:
        if not isinstance(params, dict):
            raise ProtocolError(INVALID_PARAMS, "params has to be an object.")
        if method == "initialize":
            return self.initialize(params)
        era = self.era_of(method, params)
        handlers = {
            "tools/list": self.tools_list,
            "tools/call": lambda: self.tools_call(params),
            "resources/list": self.resources_list,
            "resources/read": lambda: self.resources_read(params, era),
        }
        if era == "modern":
            handlers["server/discover"] = self.discover
            handlers["subscriptions/listen"] = lambda: self.listen(identifier, params)
        else:
            # Revision 2026-07-28 removed ping; the handshake revisions still have it.
            handlers["ping"] = dict
            handlers["resources/subscribe"] = lambda: self.subscribe(params, era)
            handlers["resources/unsubscribe"] = lambda: self.unsubscribe(params, era)
        handler = handlers.get(method)
        if handler is None:
            raise ProtocolError(METHOD_NOT_FOUND, f"There is no method {method!r} here.")
        result = handler()
        if result is None or era != "modern":
            return result
        result.setdefault("resultType", "complete")
        result.setdefault("_meta", {})[META_SERVER] = {"name": NAME, "version": VERSION}
        if method in ("tools/list", "resources/list"):
            result.update(ttlMs=LIST_TTL_MS, cacheScope="private")
        elif method == "resources/read":
            result.update(ttlMs=0, cacheScope="private")
        return result

    def era_of(self, method: str, params: dict[str, Any]) -> str:
        """Which revision this request speaks: its own `_meta`, else the handshake."""
        meta = params.get("_meta")
        declared = meta.get(META_VERSION) if isinstance(meta, dict) else None
        if declared is not None:
            if declared not in SUPPORTED:
                raise ProtocolError(
                    UNSUPPORTED_VERSION,
                    "Unsupported protocol version",
                    {"supported": list(SUPPORTED), "requested": declared},
                )
            if declared in MODERN and not isinstance(meta.get(META_CAPABILITIES), dict):
                raise ProtocolError(
                    INVALID_PARAMS, f"_meta has no {META_CAPABILITIES!r}; every request needs it."
                )
            return "modern" if declared in MODERN else "legacy"
        if self.negotiated is not None or method == "ping":
            return "legacy"
        raise ProtocolError(
            INVALID_PARAMS,
            f"This request carries no {META_VERSION!r} in _meta, and no initialize came "
            f"before it. This server speaks {', '.join(MODERN)} per request, and "
            f"{', '.join(LEGACY)} after initialize.",
            {"supported": list(SUPPORTED)},
        )

    # -- the methods -----------------------------------------------------

    def instructions(self) -> str:
        return instructions(
            self.settings.address,
            self.settings.poll_seconds,
            has_token=self.settings.token is not None,
            redeem=self.redeem,
        )

    def capabilities(self) -> dict[str, Any]:
        return {"tools": {}, "resources": {"subscribe": True}}

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        self.negotiated = requested if requested in LEGACY else LEGACY[0]
        return {
            "protocolVersion": self.negotiated,
            "capabilities": self.capabilities(),
            "serverInfo": {"name": NAME, "version": VERSION},
            "instructions": self.instructions(),
        }

    def discover(self) -> dict[str, Any]:
        return {
            "supportedVersions": list(SUPPORTED),
            "capabilities": self.capabilities(),
            "instructions": self.instructions(),
            "ttlMs": LIST_TTL_MS,
            "cacheScope": "private",
        }

    def tools_list(self) -> dict[str, Any]:
        return {"tools": [self.tools[name].tool() for name in self.order]}

    def tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        operation = self.tools.get(name) if isinstance(name, str) else None
        if operation is None:
            raise ProtocolError(INVALID_PARAMS, f"There is no tool {name!r} here.")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ProtocolError(INVALID_PARAMS, "arguments has to be an object.")
        return call(self.service, operation, arguments)

    def resources_list(self) -> dict[str, Any]:
        return {"resources": [inbox_resource(self.settings.poll_seconds)]}

    def _known(self, params: dict[str, Any], era: str) -> None:
        if params.get("uri") != INBOX_URI:
            raise ProtocolError(
                INVALID_PARAMS if era == "modern" else LEGACY_NOT_FOUND,
                "Resource not found",
                {"uri": params.get("uri")},
            )

    def _inbox(self) -> Answer:
        """The inbox as the service answers it, or an error carrying its refusal.

        Without a token — or with a revoked one — the service refuses, and that
        refusal is what the client gets, as it was sent, rather than a subscription
        that never hears anything.
        """
        try:
            answer = self.service.request("GET", INBOX_PATH)
        except Unreachable as failed:
            raise ProtocolError(
                INTERNAL_ERROR, f"Could not reach the service at {self.service.address}: {failed}"
            ) from None
        if answer.status != 200:
            raise ProtocolError(INTERNAL_ERROR, refusal_text(answer), _refusal_data(answer))
        return answer

    def resources_read(self, params: dict[str, Any], era: str) -> dict[str, Any]:
        self._known(params, era)
        answer = self._inbox()
        try:
            text = json.dumps(json.loads(answer.data.decode("utf-8")), ensure_ascii=False, indent=2)
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = answer.data.decode("utf-8", errors="replace")
        return {"contents": [{"uri": INBOX_URI, "mimeType": "application/json", "text": text}]}

    def subscribe(self, params: dict[str, Any], era: str) -> dict[str, Any]:
        assert self.watch is not None
        self._known(params, era)
        self._inbox()
        self.watch.subscribe_legacy()
        return {}

    def unsubscribe(self, params: dict[str, Any], era: str) -> dict[str, Any]:
        assert self.watch is not None
        self._known(params, era)
        self.watch.unsubscribe_legacy()
        return {}

    def listen(self, identifier: Any, params: dict[str, Any]) -> None:
        """Open a stream: acknowledge what is honoured, then answer only when it ends."""
        assert self.watch is not None and self.output is not None
        wanted = params.get("notifications") or {}
        uris = wanted.get("resourceSubscriptions") if isinstance(wanted, dict) else None
        honoured: dict[str, Any] = {}
        if isinstance(uris, list) and INBOX_URI in uris:
            self._inbox()
            honoured["resourceSubscriptions"] = [INBOX_URI]
        if honoured:
            self.watch.open_stream(identifier)
        self.listening.append(identifier)
        self.output.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/subscriptions/acknowledged",
                "params": {"_meta": {META_SUBSCRIPTION: identifier}, "notifications": honoured},
            }
        )


def _refusal_data(answer: Answer) -> dict[str, Any]:
    """Status and type of a refusal, for a client that reads fields rather than text."""
    data: dict[str, Any] = {"status": answer.status}
    try:
        data["type"] = json.loads(answer.data.decode("utf-8"))["type"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return data


def _error(identifier: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": identifier, "error": error}


# ------------------------------------------------------------------ start


def start(
    environment: dict[str, str] | os._Environ[str],
) -> tuple[Settings, Service, list[Operation]]:
    """Everything that has to hold before the first message is read."""
    settings = Settings.from_environment(environment)
    if settings.token:
        _SECRET.append(settings.token)
    service = Service(settings.address, settings.token)
    try:
        document = service.description()
    except Unreachable as failed:
        raise StartRefused(
            f"could not read the interface description at {settings.address}/openapi.json: "
            f"{failed}. The tools are made from it, so without it there are none. Check "
            f"{ADDRESS_VARIABLE}: it is the base address of the participant surface.",
            1,
        ) from None
    try:
        tools = operations_of(document)
    except DescriptionError as failed:
        raise StartRefused(f"the interface description cannot be mapped: {failed}", 1) from None
    if not any(tool.method == "GET" and tool.path == INBOX_PATH for tool in tools):
        raise StartRefused(
            f"{settings.address} describes no GET {INBOX_PATH}, so it is not the participant "
            f"surface of simple-a2a. {ADDRESS_VARIABLE} has to name that surface.",
            1,
        )
    return settings, service, tools


def main(arguments: list[str] | None = None) -> int:
    given = sys.argv[1:] if arguments is None else arguments
    if given:
        log(
            "takes no arguments — the address and the token would stand in the process "
            f"list. Set {ADDRESS_VARIABLE} and {TOKEN_VARIABLE} in the environment instead; "
            "README.md says how."
        )
        return 2
    try:
        settings, service, tools = start(os.environ)
    except StartRefused as refused:
        log(str(refused))
        return refused.status
    who = "one identity" if settings.token else "no token yet — only redeeming will work"
    log(f"{len(tools)} tools for {settings.address}, {who}; waiting on standard input")
    Server(settings, service, tools).run(sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
