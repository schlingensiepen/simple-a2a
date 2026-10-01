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

**One process, several identities.** An identity is a label, a base address and a
token. They come from the environment rather than the command line, because
arguments stand in the process list for anybody to read, or are added while the
process runs — by a tool, or by redeeming an invitation, which adds the identity it
creates. One process for all of them is the point: a process per identity would
cost an agent with two teams twice what a ready-made server is meant to save.
The price is the chance of acting as the wrong one, and it is paid openly: with more
than one identity every call has to name the one that acts, there is no default,
and every result says which one it was. Started with an address and no token at
all, the same tools are there and redeeming is the one that will work.

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

**Each identity's inbox is a resource**, and a subscription to it makes this
program ask the service at intervals and say when the listing changed. That makes a
*running* agent responsive. It does not wake a sleeping one: nothing reaches an
agent that is not running, and nothing is kept for it here.

**No token is written to disk** by this program, and none appears in anything it
writes — except once: in the answer to the redeeming that created it.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
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
LABEL_VARIABLE = "A2A_MCP_LABEL"
IDENTITIES_VARIABLE = "A2A_MCP_IDENTITIES"
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

INBOX_PATH = "/inbox"
#: One inbox per identity, named by its label.
INBOX_URI = "simple-a2a://{label}/inbox"
INBOX_URI_PATTERN = re.compile(r"simple-a2a://(?P<label>[^/]+)/inbox")

#: What a label may be: short, and safe in a resource address. Compared without
#: regard to case, so `Nord` and `nord` cannot both exist and be confused.
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
LABEL_RULE = (
    "a label is 1 to 32 letters, digits, dots, hyphens or underscores, starting with a "
    "letter or digit"
)
#: The label of the identity given as the single pair, when A2A_MCP_LABEL says none.
DEFAULT_LABEL = "default"

#: The inputs this program adds to the tools that are made from the description.
IDENTITY_INPUT = "identity"

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
class Entry:
    """One identity as the environment names it: a label, an address, a token."""

    label: str
    address: str
    token: str


@dataclass(frozen=True)
class Settings:
    #: The identities given at start, in the order given.
    entries: tuple[Entry, ...]
    #: An address given without a token: the start of the way that begins with an
    #: invitation. Until an identity exists, redeeming is the one call that works,
    #: and every other is refused by the service itself, in its own words.
    bare_address: str | None
    poll_seconds: float

    @classmethod
    def from_environment(cls, environment: dict[str, str] | os._Environ[str]) -> Settings:
        """The identities, or a refusal naming the variable that is wrong.

        Two forms, usable together: one pair in `A2A_MCP_ADDRESS` and
        `A2A_MCP_TOKEN` (the token may be missing — then it is the address to
        redeem at), and any number in `A2A_MCP_IDENTITIES`, a JSON list. Nothing in
        a message here ever repeats a token.
        """
        address = (environment.get(ADDRESS_VARIABLE) or "").strip()
        token = (environment.get(TOKEN_VARIABLE) or "").strip() or None
        listed = (environment.get(IDENTITIES_VARIABLE) or "").strip()
        if not address and not listed:
            raise StartRefused(
                f"neither {ADDRESS_VARIABLE} nor {IDENTITIES_VARIABLE} is set. Start this "
                f"program with {ADDRESS_VARIABLE} set to the base address of the participant "
                f"surface (and {TOKEN_VARIABLE} to a token, once you have one), or with "
                f"{IDENTITIES_VARIABLE} listing identities — in the environment, not on the "
                "command line. README.md shows both.",
                2,
            )
        if token and not address:
            raise StartRefused(
                f"{TOKEN_VARIABLE} is set but {ADDRESS_VARIABLE} is not: a token belongs to "
                "the address that issued it, and is worthless without it.",
                2,
            )
        entries: list[Entry] = []
        bare: str | None = None
        if address:
            where = _address(address, ADDRESS_VARIABLE)
            label = (environment.get(LABEL_VARIABLE) or "").strip() or DEFAULT_LABEL
            if not LABEL.fullmatch(label):
                raise StartRefused(f"{LABEL_VARIABLE}: {LABEL_RULE}", 2)
            if token:
                entries.append(Entry(label, where, token))
            else:
                bare = where
        if listed:
            entries += _listed(listed)
        seen: set[str] = set()
        for entry in entries:
            if entry.label.lower() in seen:
                raise StartRefused(
                    f"the label {entry.label!r} is given twice. Labels are compared without "
                    "regard to case and name one identity each.",
                    2,
                )
            seen.add(entry.label.lower())
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
        return cls(entries=tuple(entries), bare_address=bare, poll_seconds=poll)


def _address(value: str, where: str) -> str:
    if not value.startswith(("http://", "https://")):
        raise StartRefused(
            f"{where} is not an address: it has to start with http:// or https://, the way "
            "the entry of the participant surface names it.",
            2,
        )
    return value.rstrip("/")


def _listed(raw: str) -> list[Entry]:
    """`A2A_MCP_IDENTITIES`: a JSON list of objects with label, address and token."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StartRefused(
            f"{IDENTITIES_VARIABLE} is not JSON ({exc.msg}, at character {exc.pos}). It is "
            'a list like [{"label": "nord", "address": "https://…", "token": "…"}].',
            2,
        ) from None
    if not isinstance(parsed, list) or not parsed:
        raise StartRefused(f"{IDENTITIES_VARIABLE} has to be a non-empty JSON list.", 2)
    found = []
    for number, item in enumerate(parsed, start=1):
        where = f"{IDENTITIES_VARIABLE}, entry {number}"
        if not isinstance(item, dict):
            raise StartRefused(f"{where} is not an object.", 2)
        missing = [
            key
            for key in ("label", "address", "token")
            if not isinstance(item.get(key), str) or not item[key].strip()
        ]
        if missing:
            raise StartRefused(f"{where} has no {', '.join(missing)}.", 2)
        unknown = sorted(set(item) - {"label", "address", "token"})
        if unknown:
            raise StartRefused(f"{where} has fields this program does not know: {unknown}.", 2)
        label = item["label"].strip()
        if not LABEL.fullmatch(label):
            raise StartRefused(f"{where}: {LABEL_RULE}", 2)
        found.append(Entry(label, _address(item["address"].strip(), where), item["token"].strip()))
    return found


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
    file_type: str | None = None
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
            # The service keeps whatever type it is told and hands it back on every
            # fetch, and takes text/plain when told nothing. A file from disk is
            # labelled by its extension, or as plain bytes when that says nothing.
            file_type = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
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
            content_type=(
                file_type
                if operation.body_kind == "file"
                else operation.body_content_type
                if body is not None
                else None
            ),
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


# ------------------------------------------------------------------ identities


@dataclass
class Identity:
    """One identity this server acts as: a label, an address, a token.

    What it is called by the service — kind, name, team — is learned once, when
    the identity is added, and only for display: nothing here decides anything on
    it. The token is never shown.
    """

    label: str
    address: str
    token: str
    kind: str | None = None
    name: str | None = None
    team: str | None = None
    #: The service's own first line about this identity, or why there is none.
    who: str | None = None

    def __post_init__(self) -> None:
        self.service = Service(self.address, self.token)

    @property
    def uri(self) -> str:
        return INBOX_URI.format(label=self.label)

    def public(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "address": self.address,
            "kind": self.kind,
            "name": self.name,
            "team": self.team,
            "who": self.who,
        }

    def heard(self, answer: Answer) -> None:
        """Take who this is from the service's answer to `GET /me`.

        The first line of that answer says it — "You are Anna, in kitchen", or "…, a
        central service". Read leniently: if the wording ever changes, the line is
        still shown as it is, and only the separate fields stay empty.
        """
        text = answer.data.decode("utf-8", errors="replace").strip()
        first = text.splitlines()[0].lstrip("#").strip() if text else ""
        self.who = first or None
        found = WHO.fullmatch(first)
        if found:
            self.name = found["name"]
            self.team = found["team"]
            self.kind = "peer" if found["team"] else "service"


WHO = re.compile(r"You are (?P<name>.+?), (?:in (?P<team>.+)|a central service)")


def derived_label(answer: dict[str, Any], taken: set[str]) -> str:
    """A label for an identity made by redeeming, from its team and name."""
    parts = [answer.get("team_name"), answer.get("name")]
    raw = "-".join(str(part) for part in parts if part) or "identity"
    base = re.sub(r"[^a-z0-9_.-]+", "-", raw.lower()).strip("-.")[:28] or "identity"
    label, number = base, 2
    while label.lower() in taken:
        label, number = f"{base}-{number}", number + 1
    return label


def operation_set(tools: list[Operation]) -> set[tuple[str, str]]:
    """What an instance offers, as verb and address: the thing two instances must share."""
    return {(tool.method, tool.path) for tool in tools}


def identity_inputs(tools: list[Operation]) -> None:
    """Give every tool made from the description the inputs that choose an identity.

    `identity` everywhere: with more than one identity it is required, and that is
    checked at the call, because identities come and go while the tool list stays.
    Redeeming also takes `label` for the identity it creates, and `address` for an
    instance this server does not know yet.
    """
    extra = {
        IDENTITY_INPUT: {
            "type": "string",
            "description": "Which identity acts: the label of one of this server's identities "
            "(list_identities shows them). Required whenever there is more than one — there "
            "is no default.",
        }
    }
    for tool in tools:
        added = dict(extra)
        if not tool.takes_token:
            added[IDENTITY_INPUT] = {
                "type": "string",
                "description": "Optional: the label of an identity on the instance to redeem "
                "at. Needed only when this server knows more than one address.",
            }
            added["label"] = {
                "type": "string",
                "description": "The label for the identity this creates. "
                + LABEL_RULE[0].upper()
                + LABEL_RULE[1:]
                + "; made from the team and name if left out.",
            }
            added["address"] = {
                "type": "string",
                "description": "Optional: the base address of the participant surface the "
                "invitation is from, when it is not one this server knows already.",
            }
        for name, schema in added.items():
            if name in tool.input_schema["properties"]:
                raise DescriptionError(
                    f"{tool.method} {tool.path} has an input {name!r} of its own, and this "
                    "program needs that name to choose an identity"
                )
            tool.input_schema["properties"][name] = schema


#: The tools that are not operations of the service but manage this server's
#: identities. Named so a reader can tell them from the generated ones.
OWN_TOOLS: dict[str, dict[str, Any]] = {
    "list_identities": {
        "description": "The identities this server acts as: label, address, kind, name, team, "
        "and the service's own line about each. Never a token. Not an operation of the "
        "service — it describes this server.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "add_identity": {
        "description": "Add an identity from a label, an address and a token. The token is "
        "checked by asking the service who it belongs to; a refused token adds nothing. The "
        "address must offer the same operations as the instance these tools were made from. "
        "Added identities live only in this process: nothing is written to disk, and after "
        "a restart only the identities in the environment are back. Not an operation of the "
        "service.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": LABEL_RULE[0].upper() + LABEL_RULE[1:]},
                "address": {
                    "type": "string",
                    "description": "The base address of the participant surface.",
                },
                "token": {"type": "string", "description": "The token of that identity."},
            },
            "required": ["label", "address", "token"],
            "additionalProperties": False,
        },
    },
    "remove_identity": {
        "description": "Forget an identity in this process. The service is not told: the "
        "token stays valid there. Not an operation of the service.",
        "inputSchema": {
            "type": "object",
            "properties": {"label": {"type": "string", "description": "The label to forget."}},
            "required": ["label"],
            "additionalProperties": False,
        },
    },
}


def _with_identity(result: dict[str, Any], line: str) -> dict[str, Any]:
    """Every result says first which identity acted — a block of its own."""
    result["content"].insert(0, {"type": "text", "text": line})
    return result


# ------------------------------------------------------------------ the server


def inbox_resource(identity: Identity, poll_seconds: float) -> dict[str, Any]:
    return {
        "uri": identity.uri,
        "name": f"inbox of {identity.label}",
        "title": f"Inbox of {identity.label}",
        "description": (
            f"What arrived for the identity {identity.label}, newest first, envelopes only: "
            f"the answer of GET {INBOX_PATH} at the moment you read it. Subscribe and this "
            f"server asks the service every {poll_seconds:g} seconds and tells you when the "
            f"listing changed; then read it. That makes a running agent responsive. It does "
            f"not wake a sleeping one — while you are not running nothing reaches you and "
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
    """Asking the service about one identity's inbox, for as long as anybody listens.

    The baseline is taken when the first subscription arrives, before it is
    answered: a message that arrives right after the answer then counts as a
    change instead of disappearing into the first look.
    """

    def __init__(self, uri: str, service: Service, interval: float, output: Output) -> None:
        self._uri = uri
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
            log(f"looking at {self._uri} failed: {failed}")
            return None
        if answer.status != 200:
            log(f"looking at {self._uri} was refused: {refusal_text(answer)}")
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

    def close_stream(self, subscription: Any) -> None:
        with self._lock:
            self._streams.discard(subscription)
            self._stop_if_idle()

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
                            "params": {"uri": self._uri},
                        }
                    )
                for subscription in sorted(self._streams, key=str):
                    self._output.send(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/resources/updated",
                            "params": {
                                "_meta": {META_SUBSCRIPTION: subscription},
                                "uri": self._uri,
                            },
                        }
                    )


class Server:
    """The protocol, both eras, over one pair of streams, for any number of identities."""

    def __init__(self, settings: Settings, tools: list[Operation], first_address: str) -> None:
        self.settings = settings
        self.tools = {operation.name: operation for operation in tools}
        self.order = [operation.name for operation in tools]
        for name in OWN_TOOLS:
            if name in self.tools:
                raise DescriptionError(
                    f"an operation is called {name!r}, like a tool of this server"
                )
        self.offered = operation_set(tools)
        self.first_address = first_address
        #: Addresses whose description was compared and found to offer the same.
        self.matching: set[str] = {first_address}
        self.identities: list[Identity] = []
        self.negotiated: str | None = None
        self.output: Output | None = None
        self.watches: dict[str, Watch] = {}
        #: Open `subscriptions/listen` requests, answered only when they end.
        self.listening: list[Any] = []
        #: Tokens to be kept out of every later output, once the one answer that
        #: carries them has gone out.
        self.pending_secrets: list[str] = []
        redeeming = [op.name for op in tools if not op.takes_token]
        self.redeem = redeeming[0] if redeeming else "the tool that redeems an invitation"

    # -- identities ------------------------------------------------------

    def find(self, label: Any) -> Identity | None:
        if not isinstance(label, str):
            return None
        for identity in self.identities:
            if identity.label.lower() == label.lower():
                return identity
        return None

    def labels(self) -> str:
        return ", ".join(identity.label for identity in self.identities) or "none yet"

    def addresses(self) -> list[str]:
        known = [identity.address for identity in self.identities]
        if self.settings.bare_address:
            known.insert(0, self.settings.bare_address)
        return list(dict.fromkeys(known))

    def different(self, address: str) -> str | None:
        """Why the instance at `address` cannot be served with these tools, or None.

        Compared by the operations it offers, verb and address — not by the bytes of
        its description, which differ in a limit or a build without anything a tool
        would do differently.
        """
        if address in self.matching:
            return None
        try:
            document = Service(address, None).description()
            theirs = operation_set(operations_of(document))
        except (Unreachable, DescriptionError) as failed:
            return (
                f"its interface description at {address}/openapi.json could not be read: {failed}"
            )
        if theirs != self.offered:
            missing = sorted(f"{verb} {path}" for verb, path in self.offered - theirs)
            extra = sorted(f"{verb} {path}" for verb, path in theirs - self.offered)
            return (
                f"the instance at {address} offers a different set of operations than the one "
                f"these tools were made from ({self.first_address}) — it lacks "
                f"{', '.join(missing) or 'nothing'} and adds {', '.join(extra) or 'nothing'}. "
                "Its identities would be served with tools that do not fit it. Start a "
                "separate MCP server for that instance."
            )
        self.matching.add(address)
        return None

    def lookup(self, identity: Identity) -> Answer | None:
        """Ask the service who the identity is. None if it could not be reached."""
        try:
            answer = identity.service.request("GET", "/me")
        except Unreachable as failed:
            identity.who = f"not asked: the service could not be reached ({failed})"
            return None
        if answer.status == 200:
            identity.heard(answer)
        else:
            identity.who = f"the service refused this token: {_refusal_data(answer).get('type')}"
        return answer

    def add(self, identity: Identity) -> None:
        if identity.token not in _SECRET:
            _SECRET.append(identity.token)
        self.identities.append(identity)

    def choose(self, chosen: Any) -> tuple[Identity | None, dict[str, Any] | None]:
        """The identity a call acts as, or the refusal that says to name one."""
        if chosen is not None:
            identity = self.find(chosen)
            if identity is None:
                return None, _text_result(
                    f"There is no identity {chosen!r} here. There are: {self.labels()}.",
                    error=True,
                )
            return identity, None
        if len(self.identities) == 1:
            return self.identities[0], None
        if len(self.identities) > 1:
            return None, _text_result(
                f"This server acts as {len(self.identities)} identities, so every call has to "
                f"say which one acts: give `identity` as one of {self.labels()}. There is no "
                "default, on purpose — a message sent as the wrong identity cannot be unsent.",
                error=True,
            )
        return None, None

    # -- the loop --------------------------------------------------------

    def run(self, source: Any, sink: Any) -> None:
        self.output = Output(sink)
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
            for watch in self.watches.values():
                watch.stop()

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
        # A token redeemed in this call has now been shown, once; from here on it is
        # kept out of everything like any other.
        _SECRET.extend(self.pending_secrets)
        self.pending_secrets.clear()

    def notification(self, method: str, params: Any) -> None:
        if method == "notifications/cancelled" and isinstance(params, dict):
            # Ends a listening stream, with no further message for it. A plain request
            # is answered before the next line is read, so there is nothing else
            # left to cancel.
            subscription = params.get("requestId")
            if subscription in self.listening:
                self.listening.remove(subscription)
            for watch in self.watches.values():
                watch.close_stream(subscription)

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
        if method == "tools/list":
            result.update(ttlMs=LIST_TTL_MS, cacheScope="private")
        elif method in ("resources/list", "resources/read"):
            # Identities come and go at runtime, and an inbox changes all the time.
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
        """What a harness is told first. The first sentence is the one that matters."""
        places = "; ".join(
            f"{a} — its entry at {a}/, the guide at {a}/guide and the interface description "
            f"at {a}/openapi.json"
            for a in self.addresses()
        )
        if not self.identities:
            who = (
                f"There is no identity here yet, so only redeeming will work: call "
                f"`{self.redeem}` with the invitation you were given, and a `label` for it if "
                f"you like. The identity it creates is added to this server at once, and its "
                f"token is in that one answer — shown once, because that is the one moment it "
                f"exists, so keep it where you keep secrets. Until then every other tool is "
                f"refused by the service with `no-token`."
            )
        else:
            listed = ", ".join(
                f"{i.label} ({i.who or 'not known who'}, at {i.address})" for i in self.identities
            )
            rule = (
                "Every tool takes `identity`, the label of the identity that acts, and with "
                "more than one identity it is required: there is no default, so name it every "
                "time — a message sent as the wrong identity cannot be unsent."
                if len(self.identities) > 1
                else "Every tool takes `identity`, the label of the identity that acts; with "
                "one identity it may be left out, and as soon as there is a second it is "
                "required."
            )
            who = f"This server acts as these identities: {listed}. {rule}"
        return (
            f"This MCP server is not the contract. The contract is the self-description of "
            f"the simple-a2a participant surface it talks to: {places}. Read the guide "
            f"before your first call: it says what goes wrong otherwise. Every tool here was "
            f"generated from that interface description when this server started, one per "
            f"operation; where a tool and the guide seem to disagree, the guide is right.\n\n"
            f"{who} Every result names, in its first line, the identity that acted.\n\n"
            f"Identities come from the environment at start — {IDENTITIES_VARIABLE} as a "
            f"JSON list of label, address and token, or one pair in {ADDRESS_VARIABLE} and "
            f"{TOKEN_VARIABLE} — or at runtime: `add_identity` adds one, `list_identities` "
            f"shows them without their tokens, `remove_identity` forgets one, and "
            f"`{self.redeem}` adds the identity it creates. What is added at runtime lives "
            f"only in this process: this server writes no token to disk.\n\n"
            f"Each identity's inbox is a resource of its own, simple-a2a://<label>/inbox. "
            f"Subscribe to it and this server asks the service every "
            f"{self.settings.poll_seconds:g} seconds and tells you when it changed. That makes "
            f"a running agent responsive; it does not wake a sleeping one. While you are not "
            f"running nothing reaches you, so read your inboxes whenever you resume.\n\n"
            f"Before you exchange a file, agree with the other agent whether you run on the "
            f"same machine; if you do, send a path in the body of a message instead of "
            f"depositing the file.\n\n"
            f"Calls are handled one after the other: a slow call delays the next, a "
            f"cancellation included."
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
            "ttlMs": 0,
            "cacheScope": "private",
        }

    def tools_list(self) -> dict[str, Any]:
        made = [self.tools[name].tool() for name in self.order]
        own = [{"name": name, **tool} for name, tool in OWN_TOOLS.items()]
        return {"tools": made + own}

    def tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ProtocolError(INVALID_PARAMS, "arguments has to be an object.")
        arguments = dict(arguments)
        if name in OWN_TOOLS:
            return getattr(self, name)(arguments)
        operation = self.tools.get(name) if isinstance(name, str) else None
        if operation is None:
            raise ProtocolError(INVALID_PARAMS, f"There is no tool {name!r} here.")
        chosen = arguments.pop(IDENTITY_INPUT, None)
        if not operation.takes_token:
            return self.redeeming(operation, arguments, chosen)
        identity, refused = self.choose(chosen)
        if refused is not None:
            return refused
        if identity is None:
            # No identity yet: the call goes out without a token, and the service says
            # what that means in its own words.
            service = Service(self.addresses()[0], None)
            return _with_identity(
                call(service, operation, arguments), "identity: none — sent without a token"
            )
        return _with_identity(
            call(identity.service, operation, arguments), f"identity: {identity.label}"
        )

    def redeeming(
        self, operation: Operation, arguments: dict[str, Any], chosen: Any
    ) -> dict[str, Any]:
        """Redeem an invitation, and add the identity it creates under a label.

        The label is checked before the service is asked: a token that came into
        being and then could not be kept anywhere would be lost the moment it was
        made.
        """
        label = arguments.pop("label", None)
        given = arguments.pop("address", None)
        if label is not None and (not isinstance(label, str) or not LABEL.fullmatch(label)):
            return _text_result(f"`label`: {LABEL_RULE}. Nothing was redeemed.", error=True)
        if label is not None and self.find(label) is not None:
            return _text_result(
                f"There is already an identity {label!r} here (labels are compared without "
                f"regard to case). Choose another `label`. Nothing was redeemed.",
                error=True,
            )
        if given is not None:
            if not isinstance(given, str) or not given.startswith(("http://", "https://")):
                return _text_result("`address` has to start with http:// or https://.", error=True)
            address = given.rstrip("/")
            problem = self.different(address)
            if problem:
                return _text_result(f"Nothing was redeemed: {problem}", error=True)
        elif chosen is not None:
            identity = self.find(chosen)
            if identity is None:
                return _text_result(
                    f"There is no identity {chosen!r} here. There are: {self.labels()}.",
                    error=True,
                )
            address = identity.address
        else:
            known = self.addresses()
            if len(known) != 1:
                return _text_result(
                    "This server knows more than one address, so say which instance the "
                    "invitation is from: `identity` (the label of an identity there) or "
                    f"`address`. It knows: {', '.join(known)}.",
                    error=True,
                )
            address = known[0]
        result = call(Service(address, None), operation, arguments)
        if result.get("isError"):
            return _with_identity(result, "identity: none added — the service refused, below")
        try:
            answer = json.loads(result["content"][0]["text"])
            token = answer["token"]
        except (json.JSONDecodeError, KeyError, TypeError, IndexError):
            return _with_identity(result, "identity: none added — the answer carried no token")
        made = Identity(
            label=label or derived_label(answer, {i.label.lower() for i in self.identities}),
            address=address,
            token=token,
            kind=answer.get("kind"),
            name=answer.get("name"),
            team=answer.get("team_name"),
        )
        made.who = f"{made.name}, in {made.team}" if made.team else f"{made.name}, a service"
        self.identities.append(made)
        self.pending_secrets.append(token)
        return _with_identity(
            result,
            f"identity: {made.label} — added by redeeming. Its token is in the answer below, "
            "shown this once: keep it where you keep secrets. This server keeps it only while "
            "it runs.",
        )

    # -- the tools of this server ----------------------------------------

    def list_identities(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            return _text_result("list_identities takes no arguments.", error=True)
        listed = [identity.public() for identity in self.identities]
        return _text_result(json.dumps(listed, ensure_ascii=False, indent=2))

    def add_identity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        label, address, token = (arguments.get(k) for k in ("label", "address", "token"))
        unknown = sorted(set(arguments) - {"label", "address", "token"})
        if isinstance(token, str) and token.strip() and token.strip() not in _SECRET:
            # Kept out of every output from this moment, whatever happens next.
            _SECRET.append(token.strip())
        if unknown:
            return _text_result(f"add_identity does not take {', '.join(unknown)}.", error=True)
        if not all(isinstance(value, str) and value.strip() for value in (label, address, token)):
            return _text_result("add_identity needs `label`, `address` and `token`.", error=True)
        label, address, token = label.strip(), address.strip().rstrip("/"), token.strip()
        if not LABEL.fullmatch(label):
            return _text_result(f"`label`: {LABEL_RULE}.", error=True)
        if self.find(label) is not None:
            return _text_result(
                f"There is already an identity {label!r} here (labels are compared without "
                f"regard to case). There are: {self.labels()}.",
                error=True,
            )
        if not address.startswith(("http://", "https://")):
            return _text_result("`address` has to start with http:// or https://.", error=True)
        problem = self.different(address)
        if problem:
            return _text_result(f"Nothing was added: {problem}", error=True)
        identity = Identity(label=label, address=address, token=token)
        answer = self.lookup(identity)
        if answer is None:
            return _text_result(f"Nothing was added: {identity.who}.", error=True)
        if answer.status != 200:
            return _text_result(
                f"Nothing was added: the service refused the token.\n\n{refusal_text(answer)}",
                error=True,
            )
        self.add(identity)
        rule = (
            f" There are now {len(self.identities)} identities, so every call has to name one "
            "with `identity`."
            if len(self.identities) > 1
            else ""
        )
        return _text_result(
            f"identity: {label} — added: {identity.who}. It lives only in this process; nothing "
            f"was written to disk.{rule}"
        )

    def remove_identity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        identity = self.find(arguments.get("label"))
        if identity is None:
            return _text_result(
                f"There is no identity {arguments.get('label')!r} here. There are: "
                f"{self.labels()}.",
                error=True,
            )
        self.identities.remove(identity)
        watch = self.watches.pop(identity.label.lower(), None)
        if watch is not None:
            watch.stop()
        return _text_result(
            f"identity: {identity.label} — forgotten in this process. Its token is still valid "
            "at the service."
        )

    # -- resources -------------------------------------------------------

    def resources_list(self) -> dict[str, Any]:
        return {
            "resources": [
                inbox_resource(identity, self.settings.poll_seconds) for identity in self.identities
            ]
        }

    def _owner(self, params: dict[str, Any], era: str) -> Identity:
        found = INBOX_URI_PATTERN.fullmatch(str(params.get("uri") or ""))
        identity = self.find(found["label"]) if found else None
        if identity is None:
            raise ProtocolError(
                INVALID_PARAMS if era == "modern" else LEGACY_NOT_FOUND,
                "Resource not found",
                {"uri": params.get("uri"), "identities": [i.label for i in self.identities]},
            )
        return identity

    def _watch(self, identity: Identity) -> Watch:
        assert self.output is not None
        key = identity.label.lower()
        if key not in self.watches:
            self.watches[key] = Watch(
                identity.uri, identity.service, self.settings.poll_seconds, self.output
            )
        return self.watches[key]

    def _inbox(self, identity: Identity) -> Answer:
        """The inbox as the service answers it, or an error carrying its refusal.

        With a revoked token the service refuses, and that refusal is what the
        client gets, as it was sent, rather than a subscription that never hears
        anything.
        """
        try:
            answer = identity.service.request("GET", INBOX_PATH)
        except Unreachable as failed:
            raise ProtocolError(
                INTERNAL_ERROR, f"Could not reach the service at {identity.address}: {failed}"
            ) from None
        if answer.status != 200:
            raise ProtocolError(INTERNAL_ERROR, refusal_text(answer), _refusal_data(answer))
        return answer

    def resources_read(self, params: dict[str, Any], era: str) -> dict[str, Any]:
        identity = self._owner(params, era)
        answer = self._inbox(identity)
        try:
            text = json.dumps(json.loads(answer.data.decode("utf-8")), ensure_ascii=False, indent=2)
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = answer.data.decode("utf-8", errors="replace")
        return {"contents": [{"uri": identity.uri, "mimeType": "application/json", "text": text}]}

    def subscribe(self, params: dict[str, Any], era: str) -> dict[str, Any]:
        identity = self._owner(params, era)
        self._inbox(identity)
        self._watch(identity).subscribe_legacy()
        return {}

    def unsubscribe(self, params: dict[str, Any], era: str) -> dict[str, Any]:
        self._watch(self._owner(params, era)).unsubscribe_legacy()
        return {}

    def listen(self, identifier: Any, params: dict[str, Any]) -> None:
        """Open a stream: acknowledge what is honoured, then answer only when it ends."""
        assert self.output is not None
        wanted = params.get("notifications") or {}
        uris = wanted.get("resourceSubscriptions") if isinstance(wanted, dict) else None
        honoured: list[Identity] = []
        for uri in uris if isinstance(uris, list) else []:
            found = INBOX_URI_PATTERN.fullmatch(str(uri))
            identity = self.find(found["label"]) if found else None
            if identity is not None and identity not in honoured:
                self._inbox(identity)
                honoured.append(identity)
        for identity in honoured:
            self._watch(identity).open_stream(identifier)
        self.listening.append(identifier)
        agreed = {"resourceSubscriptions": [i.uri for i in honoured]} if honoured else {}
        self.output.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/subscriptions/acknowledged",
                "params": {"_meta": {META_SUBSCRIPTION: identifier}, "notifications": agreed},
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


def start(environment: dict[str, str] | os._Environ[str]) -> Server:
    """Everything that has to hold before the first message is read."""
    settings = Settings.from_environment(environment)
    for entry in settings.entries:
        _SECRET.append(entry.token)
    first = settings.bare_address or settings.entries[0].address
    try:
        document = Service(first, None).description()
    except Unreachable as failed:
        raise StartRefused(
            f"could not read the interface description at {first}/openapi.json: {failed}. "
            "The tools are made from it, so without it there are none. The address has to be "
            "the base address of the participant surface.",
            1,
        ) from None
    try:
        tools = operations_of(document)
        identity_inputs(tools)
        if not any(tool.method == "GET" and tool.path == INBOX_PATH for tool in tools):
            raise StartRefused(
                f"{first} describes no GET {INBOX_PATH}, so it is not the participant surface "
                "of simple-a2a. The address has to name that surface.",
                1,
            )
        server = Server(settings, tools, first)
    except DescriptionError as failed:
        raise StartRefused(f"the interface description cannot be mapped: {failed}", 1) from None
    for entry in settings.entries:
        problem = server.different(entry.address)
        if problem:
            raise StartRefused(f"identity {entry.label}: {problem}", 1)
        identity = Identity(entry.label, entry.address, entry.token)
        # Asked once, for display; a refused token is reported, not fatal: the
        # service will say the same to every call, in its own words.
        answer = server.lookup(identity)
        if answer is not None and answer.status != 200:
            log(f"identity {entry.label}: {refusal_text(answer)}")
        server.add(identity)
    return server


def main(arguments: list[str] | None = None) -> int:
    given = sys.argv[1:] if arguments is None else arguments
    if given:
        log(
            "takes no arguments — addresses and tokens would stand in the process list. Set "
            f"{ADDRESS_VARIABLE} and {TOKEN_VARIABLE}, or {IDENTITIES_VARIABLE}, in the "
            "environment instead; README.md says how."
        )
        return 2
    try:
        server = start(os.environ)
    except StartRefused as refused:
        log(str(refused))
        return refused.status
    who = (
        f"identities {server.labels()}"
        if server.identities
        else "no identity yet — only redeeming will work"
    )
    log(f"{len(server.tools)} tools for {', '.join(server.addresses())}, {who}; waiting")
    server.run(sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
