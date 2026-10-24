"""Serving the self-description, and turning a refusal into an answer.

This is the one place where a refusal from the operations becomes a status and a
text. It lives here because the catalogue and the texts live here; the surfaces
say *which operation* they are, and nothing else about saying no.

Two of the thirteen types belong to the address rather than to an operation —
there is no such address, and there is such an address but not that verb — so they
are answered by the application itself, before any operation is reached.

The seven token-free routes are built once, from a parameter, for the same reason
the gate is one gate: three copies of the same seven routes drift the moment
somebody fixes one. The participant surface adds an eighth, the MCP package, by
the same parameter.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Annotated, Any, get_args

from fastapi import APIRouter, FastAPI, Header, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.routing import Match

from simple_a2a.core.base_address import base_address
from simple_a2a.core.clock import now_iso
from simple_a2a.describe import mcp_package, package
from simple_a2a.describe.guide import GUIDE, Guide
from simple_a2a.describe.rejections import Rejection, Type
from simple_a2a.describe.teaching import Register, unknown_field
from simple_a2a.domain import refusals

logger = logging.getLogger("simple_a2a")

#: Data is JSON, in answers and in request bodies. A rejection is data, so it is
#: JSON too — not a separate error media type, which would be a second convention
#: to learn about the same service.
JSON = "application/json; charset=utf-8"

#: The header every operation behind a token reads, described once. Declared at
#: module level so that it can be used as an annotation: this module postpones
#: annotation evaluation, and a name from a closure would not resolve.
#:
#: The example is an obvious placeholder on purpose. An agent reads an example and
#: sends it, so an example of a secret is either unmistakably not one or absent.
Authorization = Annotated[
    str | None,
    Header(
        description="The token, as `Bearer <token>`. Every operation except the entry, "
        "the guide, the health check, the build stamp, the interface description and the "
        "packages needs one.",
        examples=["Bearer <your token>"],
    ),
]

#: The name of a guide part in the path.
PartName = Annotated[
    str,
    Path(
        description="Which part of the guide. The entry at GET / lists the parts this surface has.",
        examples=["concepts"],
    ),
]

#: Prose and raw text are negotiated: `text/markdown` when the caller asks for it,
#: plain text otherwise. The same Markdown is in both; only the label differs.
MARKDOWN = "text/markdown; charset=utf-8"
PLAIN = "text/plain; charset=utf-8"


class RefusedAt(Exception):
    """A refusal, with the operation it happened at.

    The operation is what decides the text, so it has to travel with the refusal.
    Carried in an exception rather than looked up afterwards, because afterwards
    the call stack — the only thing that knows where it came from — is gone.
    """

    def __init__(self, operation_id: str, refusal: refusals.Refused) -> None:
        super().__init__(f"{operation_id}: {refusal}")
        self.operation_id = operation_id
        self.refusal = refusal


@contextmanager
def guard(operation_id: str) -> Iterator[None]:
    """Name the operation for anything that refuses inside it."""
    try:
        yield
    except refusals.Refused as refusal:
        raise RefusedAt(operation_id, refusal) from refusal


def prose(text: str, request: Request) -> Response:
    """Answer with prose, labelled the way the caller asked for it."""
    ranges = accepted(request.headers.get("accept"))
    wants_markdown = any(media == "text/markdown" and q > 0 for media, q in ranges)
    return PlainTextResponse(text, media_type=MARKDOWN if wants_markdown else PLAIN)


def accepted(header: str | None) -> list[tuple[str, float]]:
    """The media ranges of an Accept header, lower case, each with its quality.

    Parameters other than the quality are dropped, and so is anything after it; a
    quality that is not a number counts as zero rather than as a wish.
    """
    ranges: list[tuple[str, float]] = []
    for part in (header or "").split(","):
        media, *parameters = (piece.strip() for piece in part.split(";"))
        if media.count("/") != 1:
            continue
        quality = 1.0
        for parameter in parameters:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
                quality = min(max(quality, 0.0), 1.0) if math.isfinite(quality) else 0.0
                break
        ranges.append((media.lower(), quality))
    return ranges


def quality(ranges: list[tuple[str, float]], media: str) -> float:
    """How welcome `media` is: the quality of the most specific range that matches it.

    `type/subtype` before `type/*` before `*/*`; no range that matches is zero.
    """
    kind = media.split("/")[0]
    for candidate in (media, f"{kind}/*", "*/*"):
        found = [q for name, q in ranges if name == candidate]
        if found:
            return max(found)
    return 0.0


#: The prose an address with both offers, as its description names it.
PROSE_MEDIA = ("text/plain", "text/markdown")


def wants_data(request: Request) -> bool:
    """Whether the caller prefers JSON to prose, by its Accept header.

    Only where an address offers both — and every such address asks here. JSON is
    the answer only when it is more welcome than either kind of prose: each is
    weighed by the most specific range that names it, so `application/*` asks for
    data, and `*/*;q=1` outweighs `application/json;q=0.5`. A tie keeps the prose,
    so does a missing header or `*/*`: prose is what anybody gets who does not ask.
    """
    ranges = accepted(request.headers.get("accept"))
    data = quality(ranges, "application/json")
    text = max(quality(ranges, media) for media in PROSE_MEDIA)
    return data > text


#: The two kinds of answer an address with both offers, for its description.
PROSE_OR_DATA = {media: {"schema": {"type": "string"}} for media in PROSE_MEDIA}


def identifier_of(route: APIRoute) -> str:
    """An operation's identifier in the description: the name it has in the code.

    The framework's default glues the path and the verb onto the name, which makes
    every identifier unique and none of them readable. Ours are unique per surface
    already — a test says so — and whoever generates a client from the description
    gets `send_to_peers` rather than `send_to_peers_peers_messages_post`.
    """
    return route.name


def rejected(rejection: Rejection) -> JSONResponse:
    return JSONResponse(rejection.body(), status_code=rejection.status, media_type=JSON)


def _placeholder_pattern(request: Request) -> str | None:
    """The route whose shape this address has, if a placeholder made it match."""
    for route in request.app.router.routes:
        if not isinstance(route, APIRoute) or not route.param_convertors:
            continue
        match, _ = route.matches(request.scope)
        if match is not Match.NONE:
            return route.path_format
    return None


async def _read_instead(request: Request) -> tuple[int, bytes]:
    """Ask this surface for the same address with GET, in-process, as the caller.

    Read-only by construction: a GET here changes nothing. The body of the original
    request is not passed on.
    """
    scope = {
        key: request.scope[key]
        for key in (
            "type",
            "asgi",
            "http_version",
            "scheme",
            "server",
            "client",
            "root_path",
            "path",
            "raw_path",
            "query_string",
        )
        if key in request.scope
    }
    scope["method"] = "GET"
    scope["headers"] = [
        (name, value)
        for name, value in request.scope.get("headers", [])
        if name not in (b"content-length", b"content-type", b"transfer-encoding")
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await request.app(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), 500)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def install_handlers(
    app: FastAPI, register: Register, *, surface_entry: Callable[[Request], str]
) -> None:
    """Everything this surface says when something goes wrong.

    The address-level answers name the **entry** of this surface, which lists every
    address it has — and no other surface's. That is what a caller who guessed
    wrong actually needs, and it is all they may be told.
    """

    @app.exception_handler(RefusedAt)
    async def _refused(request: Request, exc: RefusedAt) -> JSONResponse:
        return rejected(register.rejection(exc.operation_id, exc.refusal))

    @app.exception_handler(404)
    async def _unknown_address(request: Request, exc: Exception) -> JSONResponse:
        return rejected(
            Rejection(
                type=Type.UNKNOWN_ADDRESS,
                message=(
                    "This surface has no such address. Its entry lists every address "
                    "it has, each with one sentence saying what it is for: GET /"
                ),
            )
        )

    @app.exception_handler(405)
    async def _wrong_verb(request: Request, exc: Exception) -> Response:
        """Say "wrong verb" only about an address that exists.

        The router decides by the *shape* of an address. `/services/{name}` makes
        `/services/messages` look like an address — with `messages` as the name of a
        service nobody has — and answering "it exists, but not with POST" sent an
        agent looking for the right verb at an address that was never there. So where
        a placeholder matched and the address can be read, it is read first, with the
        caller's own credentials: if that read succeeds, the thing exists and the
        verb was wrong; if not, its refusal is the true answer — "no service called
        messages", or "no token" for a caller who could not have read it either.
        """
        allowed = getattr(exc, "headers", {}).get("Allow") if hasattr(exc, "headers") else None
        pattern = _placeholder_pattern(request)
        if pattern and allowed and "GET" in allowed.replace(" ", "").split(","):
            status, body = await _read_instead(request)
            if status != 200:
                return Response(body, status_code=status, media_type="application/json")
        message = "That address exists, but not with this method."
        if allowed:
            message += f" It takes: {allowed}."
        if pattern:
            message += f" It is the address {pattern}."
        message += " The entry at GET / lists every address of this surface."
        return rejected(Rejection(type=Type.WRONG_VERB, message=message))

    @app.exception_handler(RequestValidationError)
    async def _malformed(request: Request, exc: RequestValidationError) -> JSONResponse:
        """A body or a parameter that did not fit, answered from **our** catalogue.

        Left to the framework this is a 422 with a shape of its own — a rejection
        outside a catalogue that says it is closed, and a second error format for a
        caller to learn. It is the same `invalid-input` as any other malformed
        input, and it says so with the text of the operation it happened at.
        """
        route = request.scope.get("route")
        # `path_format`, not `path`: a parameter that takes the rest of the address is
        # written `{file_name:path}` in the route and `{file_name}` everywhere else —
        # in the description and in the texts — and the text is found by the latter.
        operation_id = (
            f"{request.method} {getattr(route, 'path_format', route.path)}" if route else ""
        )
        # A name the request does not have is answered before anything else that
        # did not fit: it is usually the cause of the rest — `to` sent for
        # `recipient` is an unknown field and a missing one — and the operation's
        # own text, about how its fields fit together, would send the reader to
        # the wrong place.
        unknown = _unknown_field(exc, route)
        field = unknown[0] if unknown else _first_field(exc)
        try:
            rejection = register.rejection(
                operation_id, refusals.InvalidInput(field or "body", reason="does not fit")
            )
            if unknown:
                rejection = replace(rejection, message=unknown[1])
        except KeyError:
            # No text for this operation and type: that is a build error rather than
            # a caller's problem, so it is answered as ours.
            rejection = Rejection(
                type=Type.INTERNAL,
                message=(
                    "Something went wrong on our side. Nothing here is fire-and-forget "
                    "by accident: send the same request again."
                ),
            )
        return rejected(rejection)

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        # Logged with its traceback before it is answered. The answer deliberately
        # says nothing about what went wrong — that is ours, not the caller's — but
        # an unexplained 500 that leaves no trace is a bug that hides. This handler
        # once turned a wrong field name into a silent 500 for exactly that reason.
        logger.exception("%s %s failed", request.method, request.url.path)
        # The caller is told what to do rather than what happened: sending is
        # fire-and-forget, so sending again is the answer.
        return rejected(
            Rejection(
                type=Type.INTERNAL,
                message=(
                    "Something went wrong on our side. Nothing here is fire-and-forget "
                    "by accident: send the same request again."
                ),
            )
        )


def _first_field(exc: RequestValidationError) -> str | None:
    """Which field the framework tripped on, in the caller's own words.

    The framework reports a location as a tuple — body, then the field. The field is
    what a caller can act on; the rest is our internal shape.
    """
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query")]
        if location:
            return ".".join(location)
    return None


def _unknown_field(exc: RequestValidationError, route: Any) -> tuple[str, str] | None:
    """The first name in the body that its object does not have, and what it teaches.

    The path is written the way `field` always is — `attachments.0.size` — and the
    fields listed are those of the object the name was found in, read from the
    route's own request model, so the list cannot drift from what is accepted.
    Nothing is answered here for a name whose object cannot be found in the model;
    that case keeps the operation's own text.
    """
    model = _model_in(getattr(getattr(route, "body_field", None), "field_info", None))
    if model is None:
        return None
    for error in exc.errors():
        location = list(error.get("loc", ()))
        if error.get("type") != "extra_forbidden" or location[:1] != ["body"]:
            continue
        parts = location[1:]
        owner = _model_at(model, parts[:-1])
        if not parts or owner is None:
            continue
        within = ".".join(str(part) for part in parts[:-1])
        if _plain(parts):
            path = ".".join(str(part) for part in parts)
            return path, unknown_field(path, within, _field_names(owner))
        # The name is the caller's own input, of any length and with any character
        # in it — a backtick, a line break, a dot that reads as a path. It is not
        # repeated, neither in the sentence nor in `field`; the object it was found
        # in is ours to name, and the request itself is named `body`, as wherever
        # a refusal has no single field.
        return within or "body", unknown_field(None, within, _field_names(owner))
    return None


#: What a name must look like to be repeated back: short and plain, so that it
#: cannot break out of the quotes around it, read as a path, or fill the answer.
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
_PLAIN_PATH_MAX = 200


def _plain(parts: list[Any]) -> bool:
    """Whether every part of a path can be repeated to the caller as it came."""
    for part in parts:
        if isinstance(part, int) and not isinstance(part, bool):
            continue
        if not isinstance(part, str) or _PLAIN_NAME.fullmatch(part) is None:
            return False
    return len(".".join(str(part) for part in parts)) <= _PLAIN_PATH_MAX


def _field_names(model: type[BaseModel]) -> list[str]:
    """The fields of a request object, as a caller writes them, in the model's order."""
    return [info.alias or name for name, info in model.model_fields.items()]


# Reads list/Optional of one model only; test_request_bodies_have_the_shape_read_here pins it.
def _model_in(found: Any) -> type[BaseModel] | None:
    """The model a field holds, through `None`, lists and the field's own wrapper."""
    annotation = getattr(found, "annotation", found)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for argument in get_args(annotation):
        model = _model_in(argument)
        if model is not None:
            return model
    return None


# Steps through model fields and list indexes only; test_request_bodies_have_the_shape_read_here.
def _model_at(model: type[BaseModel], parts: list[Any]) -> type[BaseModel] | None:
    """The model of the object at `parts` inside `model`; a list index stays in place."""
    current: type[BaseModel] | None = model
    for part in parts:
        if isinstance(part, int):
            continue
        fields = {info.alias or name: info for name, info in current.model_fields.items()}
        if part not in fields:
            return None
        current = _model_in(fields[part])
        if current is None:
            return None
    return current


def _pruned(document: dict[str, Any]) -> dict[str, Any]:
    """The generated description, with what we never answer taken out.

    The framework documents a validation error of its own shape on every route that
    takes a body or a parameter. We never answer with it — such a case comes back as
    `invalid-input` from the closed catalogue — so leaving it in the description
    would advertise a fourteenth kind of rejection that does not exist.
    """
    for verbs in (document.get("paths") or {}).values():
        for operation in verbs.values():
            if isinstance(operation, dict):
                (operation.get("responses") or {}).pop("422", None)
    schemas = (document.get("components") or {}).get("schemas") or {}
    for invented in ("HTTPValidationError", "ValidationError"):
        schemas.pop(invented, None)
    return document


def serve_described_openapi(app: FastAPI) -> None:
    """Make the application serve the pruned description rather than the raw one.

    Replaced on the application rather than filtered at the route, so that anything
    reading `app.openapi()` — the gate in the tests included — sees exactly what a
    caller sees. Two versions of the description would be the drift this whole block
    exists to prevent.
    """
    generated = app.openapi

    def described() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _pruned(generated())
        return app.openapi_schema

    app.openapi = described  # type: ignore[method-assign]


def guide_of(request: Request, surface: str) -> Guide:
    """The texts of this surface, rendered for this request.

    The base address is measured from the request: the host exactly as received,
    and the scheme from the forwarded header, which is believed. Behind a proxy the
    service cannot know either from the inside.
    """
    return Guide(
        surface=surface,
        base_address=base_address(
            request.headers.get("host"), request.headers.get("x-forwarded-proto")
        ),
    )


def cascade(
    surface: str, *, description: str, build: dict[str, str | None], offers_mcp: bool = False
) -> APIRouter:
    """The seven token-free routes, built once from a parameter.

    Every one of them answers without a token, and the entry answers **the same
    thing always, with status 200**: it does not read the holdings and has no second
    mode of operation. An instance that has nothing in it looks exactly like one
    that is in use.

    The participant surface has an eighth, the MCP package, and only that surface:
    it is the one where agents do their work, and the only one a ready-made set of
    tools is offered for.
    """
    router = APIRouter()

    @router.get(
        "/",
        summary="The entry of this surface: what it is, and every form of help it offers.",
        response_class=PlainTextResponse,
    )
    async def entry(request: Request) -> Response:
        return prose(guide_of(request, surface).entry(), request)

    @router.get(
        "/guide",
        summary="The guide: what this surface is for, and what its parts contain.",
        response_class=PlainTextResponse,
    )
    async def guide_entry(request: Request) -> Response:
        return prose(guide_of(request, surface).part(GUIDE), request)

    @router.get(
        "/guide/{part}",
        summary="One part of the guide: a single concern, readable on its own.",
        response_class=PlainTextResponse,
    )
    async def guide_part(part: PartName, request: Request) -> Response:
        made = guide_of(request, surface)
        if not made.has_part(part) or part == GUIDE:
            with guard("GET /guide/{part}"):
                raise refusals.UnknownName(part, namespace="guide part")
        return prose(made.part(part), request)

    @router.get("/health", summary="Whether the process answers. Nothing more than that.")
    async def health() -> dict[str, Any]:
        # It says the process answers, and deliberately nothing about the holdings
        # or about content: a second notion of health for a message dispatcher is
        # something an operator would then have to interpret.
        return {"healthy": True, "checked_at": now_iso()}

    @router.get("/build", summary="Which build this is, so a finding can be tied to one.")
    async def build_stamp() -> dict[str, str | None]:
        return dict(build)

    @router.get(
        "/skill.zip",
        summary="The guide as an archive, for a harness that keeps its instructions.",
    )
    async def skill(request: Request) -> Response:
        made = guide_of(request, surface)
        archive = package.build_archive(
            made, description=description, build=build.get("build_id") or "unknown"
        )
        return Response(
            archive,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="skill.zip"'},
        )

    if offers_mcp:
        # Read once, when the surface is built: the package is the same bytes for
        # every caller and every instance of this release, and a missing file is a
        # broken build that should stop the start rather than surface as a 500.
        archive = mcp_package.build_archive()

        @router.get(
            "/mcp.zip",
            summary="A ready-made MCP server for this surface, for a harness that would "
            "rather call tools than build them. Not the contract: its tools are made from "
            "/openapi.json when it starts.",
            response_class=Response,
            responses={
                200: {
                    "description": "The program and its instructions, as a zip archive. "
                    "The same bytes on every instance of the same release.",
                    "content": {
                        "application/zip": {"schema": {"type": "string", "format": "binary"}}
                    },
                }
            },
        )
        async def mcp() -> Response:
            return Response(
                archive,
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="mcp.zip"'},
            )

    return router


#: The media type of a served file, from the extension of the name in the address.
#: Derived rather than stored: a browser can then show what a browser can show, and the
#: service keeps nothing for it. Anything unrecognised is a download, which is the safe
#: answer — a wrong guess here is a wrong guess in somebody's browser.
MEDIA_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
}


def raw_body(media_type: str, schema: dict[str, Any], description: str) -> dict[str, Any]:
    """A request body the framework cannot see, described by hand.

    Some operations read their body raw rather than through a model — the text of
    a self-image or a setup note, the bytes of a file — because a JSON wrapper around either is
    exactly the escaping the raw body exists to avoid. The framework infers a body
    only from a model, so without this the description would say these operations
    take nothing, and a caller building from it would send nothing.
    """
    return {
        "requestBody": {
            "required": True,
            "description": description,
            "content": {media_type: {"schema": schema}},
        }
    }


def media_type(name: str) -> str:
    """What to label a served file, from its name alone."""
    for extension, found in MEDIA_TYPES.items():
        if name.lower().endswith(extension):
            return found
    return "application/octet-stream"
