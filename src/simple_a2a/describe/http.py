"""Serving the self-description, and turning a refusal into an answer.

This is the one place where a refusal from the operations becomes a status and a
text. It lives here because the catalogue and the texts live here; the surfaces
say *which operation* they are, and nothing else about saying no.

Two of the thirteen types belong to the address rather than to an operation —
there is no such address, and there is such an address but not that verb — so they
are answered by the application itself, before any operation is reached.

The seven token-free routes are built once, from a parameter, for the same reason
the gate is one gate: three copies of the same seven routes drift the moment
somebody fixes one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Header, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from simple_a2a.core.base_address import base_address
from simple_a2a.core.clock import now_iso
from simple_a2a.describe import package
from simple_a2a.describe.guide import GUIDE, Guide
from simple_a2a.describe.rejections import Rejection, Type
from simple_a2a.describe.teaching import Register
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
        "skill package needs one.",
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
    wants_markdown = "text/markdown" in (request.headers.get("accept") or "")
    return PlainTextResponse(text, media_type=MARKDOWN if wants_markdown else PLAIN)


def rejected(rejection: Rejection) -> JSONResponse:
    return JSONResponse(rejection.body(), status_code=rejection.status, media_type=JSON)


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
    async def _wrong_verb(request: Request, exc: Exception) -> JSONResponse:
        allowed = getattr(exc, "headers", {}).get("Allow") if hasattr(exc, "headers") else None
        message = "That address exists, but not with this method."
        if allowed:
            message += f" It takes: {allowed}."
        message += " The entry at GET / lists every address of this surface."
        return rejected(Rejection(type=Type.WRONG_VERB, message=message))

    @app.exception_handler(RequestValidationError)
    async def _malformed(request: Request, exc: RequestValidationError) -> JSONResponse:
        """A body or a parameter that did not fit, answered from **our** catalogue.

        Left to the framework this is a 422 with a shape of its own — a rejection
        outside a catalogue that says it is closed, and a second error format for a
        caller to learn. It is the same `ungültige-eingabe` as any other malformed
        input, and it says so with the text of the operation it happened at.
        """
        route = request.scope.get("route")
        operation_id = f"{request.method} {route.path}" if route is not None else ""
        field = _first_field(exc)
        try:
            rejection = register.rejection(
                operation_id, refusals.InvalidInput(field or "body", reason="does not fit")
            )
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


def _pruned(document: dict[str, Any]) -> dict[str, Any]:
    """The generated description, with what we never answer taken out.

    The framework documents a validation error of its own shape on every route that
    takes a body or a parameter. We never answer with it — such a case comes back as
    `ungültige-eingabe` from the closed catalogue — so leaving it in the description
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


def cascade(surface: str, *, description: str, build: dict[str, str]) -> APIRouter:
    """The seven token-free routes, built once from a parameter.

    Every one of them answers without a token, and the entry answers **the same
    thing always, with status 200**: it does not read the holdings and has no second
    mode of operation. An instance that has nothing in it looks exactly like one
    that is in use.
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
    async def build_stamp() -> dict[str, str]:
        return dict(build)

    @router.get(
        "/skill.zip",
        summary="The guide as an archive, for a harness that keeps its instructions.",
    )
    async def skill(request: Request) -> Response:
        made = guide_of(request, surface)
        archive = package.build_archive(
            made, description=description, build=build.get("build_id", "unknown")
        )
        return Response(
            archive,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="skill.zip"'},
        )

    return router
