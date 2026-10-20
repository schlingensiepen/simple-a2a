"""The observation surface: reading one installation, and writing nothing.

An observer is not an identity. They carry no texts, have no mailbox and cannot be
addressed; nothing in a team can tell that they exist, and no answer anywhere else
helps anybody find out. That is what makes this a surface of its own rather than a
set of extra rights on another one.

There is exactly one operation here that no participant may have, and it is the one
that justifies the whole surface: listing the teams. Everything else follows from it —
a team, its members, its traffic, and from an entry a message, a body, a file.

Only reading. There is no route here that changes anything, which is checked rather
than intended.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from simple_a2a.core import tokens
from simple_a2a.describe import directories, http
from simple_a2a.describe.http import guard
from simple_a2a.domain import access, messages, refusals
from simple_a2a.domain.callers import Observer
from simple_a2a.domain.context import Context
from simple_a2a.observe import models, prose, texts

SURFACE = "observe"

DESCRIPTION = (
    "The observation surface of a simple-a2a installation: its teams, who is in them, "
    "and what has been said."
)

TeamName = Annotated[
    str,
    Path(
        description="Which team. GET /teams lists them, each pointing at its own traffic.",
        examples=["kitchen"],
    ),
]
MemberName = Annotated[
    str,
    Path(
        description="The name of somebody in that team, compared without regard to case.",
        examples=["Anna"],
    ),
]
ServiceName = Annotated[
    str,
    Path(
        description="The name of a central service. GET /services lists them.",
        examples=["weather"],
    ),
]
MessageId = Annotated[
    str,
    Path(
        description="The identifier of a message, 43 characters. You find them in a team's "
        "traffic.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    ),
]
FileId = Annotated[
    str,
    Path(
        description="The identifier of a file, 43 characters. Attachment entries name them.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    ),
]
FileName = Annotated[
    str,
    Path(
        description="The name to save the file under. Yours to choose, and not a path: "
        "directory parts in it are dropped rather than followed.",
        examples=["shopping-list.md"],
    ),
]


def build_app(context: Context, *, build: dict[str, str]) -> FastAPI:
    register = texts.build()
    app = FastAPI(
        title="simple-a2a observation",
        description=DESCRIPTION,
        openapi_url="/openapi.json",
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=http.identifier_of,
    )
    app.include_router(http.cascade(SURFACE, description=DESCRIPTION, build=build))
    http.install_handlers(app, register, surface_entry=lambda request: "/")
    http.serve_described_openapi(app)

    async def watcher(request: Request, authorization: http.Authorization = None) -> Observer:
        with guard(f"{request.method} {request.scope['route'].path_format}"):
            return access.as_observer(
                access.authenticate(context, tokens.from_authorization(authorization))
            )

    watcher_of = Depends(watcher)
    offset_of = Query(None, description="Where the window starts. From 0.", examples=[0])
    limit_of = Query(
        None, description="How many entries at most. Defaults to 25, at most 100.", examples=[25]
    )
    sender_kind_of = Query(
        None,
        description="Narrow to one sender: `peer` or `service`. Always together with "
        "sender_name — inside one team the other side can be either, and the kind says which "
        "namespace the name is in.",
        examples=["peer"],
    )
    sender_name_of = Query(
        None,
        description="Narrow to one sender, by name. Always together with sender_kind.",
        examples=["Anna"],
    )
    recipient_kind_of = Query(
        None,
        description="Narrow to one recipient: `peer` or `service`. Always together with "
        "recipient_name.",
        examples=["service"],
    )
    recipient_name_of = Query(
        None,
        description="Narrow to one recipient, by name. Always together with recipient_kind.",
        examples=["weather"],
    )
    from_of = Query(
        None,
        alias="from",
        description="Only what was sent at or after this moment, in UTC with milliseconds. "
        "Both ends are included: a day means the day.",
        examples=["2026-09-28T00:00:00.000Z"],
    )
    to_of = Query(
        None,
        alias="to",
        description="Only what was sent at or before this moment, in UTC with milliseconds.",
        examples=["2026-09-28T23:59:59.999Z"],
    )

    def team_of(caller: Observer, name: str) -> str:
        located = context.holdings.team_named(caller.realm_id, name)
        if located is None:
            raise refusals.UnknownName(name, namespace="team")
        return located.id

    # -- the teams ---------------------------------------------------------

    @app.get(
        "/teams",
        summary="The teams of this installation. The one operation no participant has. Prose "
        "by default; with `Accept: application/json`, the same list as data.",
        response_class=Response,
        responses={
            200: {
                "description": "Prose naming each team with its size and the address of its "
                "traffic — or, if you ask for application/json first, the same window as "
                "`entries`.",
                "model": models.Teams,
                "content": http.PROSE_OR_DATA,
            }
        },
    )
    async def teams(
        request: Request,
        caller: Observer = watcher_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Response:
        with guard("GET /teams"):
            window = access.Window.of(offset, limit)
            everything = access.teams(context, caller.realm_id, access.Window.of(0, 100))
            if http.wants_data(request):
                return JSONResponse(
                    {
                        "entries": [
                            {"team_name": entry["team_name"], "member_count": entry["member_count"]}
                            for entry in window.over(everything)
                        ]
                    },
                    media_type=http.JSON,
                )
            return http.prose(
                prose.teams(
                    entries=window.over(everything),
                    offset=window.offset,
                    total=len(everything),
                ),
                request,
            )

    @app.get(
        "/teams/{team}",
        summary="One team: how big it is, and where to look.",
        response_class=Response,
    )
    async def one_team(team: TeamName, request: Request, caller: Observer = watcher_of) -> Response:
        with guard("GET /teams/{team}"):
            team_id = team_of(caller, team)
            record = context.holdings.team(caller.realm_id, team_id)
            purpose = context.holdings.team_purpose(caller.realm_id, team_id) or ""
            return http.prose(
                prose.team(
                    team_name=record.name if record else team,
                    member_count=sum(1 for _ in context.holdings.members(caller.realm_id, team_id)),
                    purpose_set=bool(purpose.strip()),
                ),
                request,
            )

    @app.get(
        "/teams/{team}/purpose",
        summary="What a team is for, in the words of whoever created it.",
        response_class=Response,
    )
    async def team_purpose(
        team: TeamName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /teams/{team}/purpose"):
            team_id = team_of(caller, team)
            return http.prose(
                context.holdings.team_purpose(caller.realm_id, team_id) or "", request
            )

    @app.get(
        "/teams/{team}/peers",
        summary="Who is in a team, with the marks for the right and for a revoked token. Prose "
        "by default; with `Accept: application/json`, the same list as data.",
        response_class=Response,
        responses={
            200: {
                "description": "Prose naming each member with their marks and the addresses "
                "of their texts — or, if you ask for application/json first, the same window "
                "as `entries`, the marks as fields.",
                "model": models.Members,
                "content": http.PROSE_OR_DATA,
            }
        },
    )
    async def peers(
        team: TeamName,
        request: Request,
        caller: Observer = watcher_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Response:
        with guard("GET /teams/{team}/peers"):
            team_id = team_of(caller, team)
            window = access.Window.of(offset, limit)
            everybody = access.members(context, caller.realm_id, team_id, access.Window.of(0, 100))
            if http.wants_data(request):
                return JSONResponse(
                    {"entries": [_member(entry) for entry in window.over(everybody)]},
                    media_type=http.JSON,
                )
            prefix = f"/teams/{_quote(team)}/peers"
            return http.prose(
                directories.peers(
                    entries=window.over(everybody),
                    offset=window.offset,
                    total=len(everybody),
                    prefix=prefix,
                    heading=f"{team}: who is in it",
                    empty="Nobody is in it. An empty team is idle, not broken.",
                    closing=(
                        f"What has been said in this team is at "
                        f"`GET /teams/{_quote(team)}/traffic`."
                    ),
                ),
                request,
            )

    @app.get("/teams/{team}/peers/{name}", summary="One member of a team.", response_class=Response)
    async def one_peer(
        team: TeamName, name: MemberName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /teams/{team}/peers/{name}"):
            located = _peer(context, caller, team_of(caller, team), name)
            return http.prose(
                directories.peer(
                    name=located.record.name,
                    is_realm_master=located.record.is_realm_master,
                    revoked=located.record.revoked_at is not None,
                    prefix=f"/teams/{_quote(team)}/peers",
                    closing=(
                        f"What they have said is at `GET /teams/{_quote(team)}/traffic` with "
                        f"`sender_kind=peer` and `sender_name={located.record.name}`."
                    ),
                ),
                request,
            )

    @app.get(
        "/teams/{team}/peers/{name}/mission",
        summary="What a member was invited for.",
        response_class=Response,
    )
    async def peer_mission(
        team: TeamName, name: MemberName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /teams/{team}/peers/{name}/mission"):
            team_id = team_of(caller, team)
            located = _peer(context, caller, team_id, name)
            return http.prose(
                context.holdings.member_mission(
                    caller.realm_id, team_id, located.record.id, located.state
                )
                or "",
                request,
            )

    @app.get(
        "/teams/{team}/peers/{name}/self",
        summary="What a member says about themselves.",
        response_class=Response,
    )
    async def peer_self(
        team: TeamName, name: MemberName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /teams/{team}/peers/{name}/self"):
            team_id = team_of(caller, team)
            located = _peer(context, caller, team_id, name)
            return http.prose(
                context.holdings.member_self_image(
                    caller.realm_id, team_id, located.record.id, located.state
                )
                or "",
                request,
            )

    # -- the registry ------------------------------------------------------

    @app.get(
        "/services",
        summary="The central services of this installation.",
        response_class=Response,
    )
    async def services(
        request: Request,
        caller: Observer = watcher_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Response:
        with guard("GET /services"):
            window = access.Window.of(offset, limit)
            everything = access.services(context, caller.realm_id, access.Window.of(0, 100))
            return http.prose(
                directories.services(
                    entries=window.over(everything),
                    offset=window.offset,
                    total=len(everything),
                    prefix="/services",
                    heading="Central services",
                    empty="There are none.",
                    closing=(
                        "What a service has been sent and has answered shows up in the "
                        "traffic of the team it was talking to, with `recipient_kind=service` "
                        "or `sender_kind=service`."
                    ),
                ),
                request,
            )

    @app.get("/services/{name}", summary="One central service.", response_class=Response)
    async def one_service(
        name: ServiceName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /services/{name}"):
            located = _service(context, caller, name)
            return http.prose(
                directories.service(
                    name=located.record.name,
                    revoked=located.record.revoked_at is not None,
                    prefix="/services",
                    closing="",
                ),
                request,
            )

    @app.get(
        "/services/{name}/self",
        summary="What a central service says it can do.",
        response_class=Response,
    )
    async def service_self(
        name: ServiceName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /services/{name}/self"):
            located = _service(context, caller, name)
            return http.prose(
                context.holdings.service_self_image(
                    caller.realm_id, located.record.id, located.state
                )
                or "",
                request,
            )

    # -- the traffic -------------------------------------------------------

    @app.get(
        "/teams/{team}/traffic",
        summary="What has been said in one team, newest first. The actual observation.",
        response_model=models.Traffic,
        response_model_exclude_none=True,
    )
    async def traffic(
        team: TeamName,
        request: Request,
        caller: Observer = watcher_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
        sender_kind: str | None = sender_kind_of,
        sender_name: str | None = sender_name_of,
        recipient_kind: str | None = recipient_kind_of,
        recipient_name: str | None = recipient_name_of,
        since: str | None = from_of,
        until: str | None = to_of,
    ) -> Any:
        with guard("GET /teams/{team}/traffic"):
            team_id = team_of(caller, team)
            window = access.Window.of(offset, limit)
            filters = messages.Filters.of(
                sender_kind, sender_name, recipient_kind, recipient_name, since, until
            )
            _known(context, caller, team_id, filters)
            found = messages.team_traffic(
                context,
                caller,
                team_id,
                offset=window.offset,
                limit=window.limit,
                filters=filters,
            )
            return {"entries": [_entry(envelope) for envelope in found]}

    # -- one message, and what hangs on it ---------------------------------

    @app.get(
        "/messages/{message_id}",
        summary="The envelope of one message, with the real sender and every recipient.",
        response_model=models.Envelope,
        response_model_exclude_none=True,
    )
    async def envelope(
        message_id: MessageId, request: Request, caller: Observer = watcher_of
    ) -> Any:
        with guard("GET /messages/{message_id}"):
            return _entry(messages.envelope(context, caller, message_id), with_attachments=True)

    @app.get("/messages/{message_id}/subject", summary="The subject, raw.", response_class=Response)
    async def subject(
        message_id: MessageId, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /messages/{message_id}/subject"):
            return http.prose(messages.subject_of(context, caller, message_id), request)

    @app.get(
        "/messages/{message_id}/body",
        summary="The body, raw and exactly as it was sent.",
        response_class=Response,
    )
    async def body(
        message_id: MessageId, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /messages/{message_id}/body"):
            return http.prose(messages.body_of(context, caller, message_id), request)

    @app.get(
        "/files/{file_id}/{file_name:path}",
        summary="Fetch an attached file under a name of your choosing.",
        response_class=Response,
    )
    async def file(
        file_id: FileId, file_name: FileName, request: Request, caller: Observer = watcher_of
    ) -> Response:
        with guard("GET /files/{file_id}/{file_name}"):
            safe = messages.safe_file_name(file_name)
            content, said = messages.fetch_file(context, caller, file_id)
            return Response(
                content,
                media_type=said or http.media_type(safe),
                headers={"Content-Disposition": f'attachment; filename="{safe}"'},
            )

    return app


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name, safe="")


def _member(entry: dict[str, object]) -> dict[str, object]:
    """One member as data, named as the traffic names a participant."""
    return {
        "kind": "peer",
        "name": entry["member_name"],
        "is_realm_master": entry["is_realm_master"],
        "token_revoked": entry["token_revoked"],
    }


def _peer(context: Context, caller: Observer, team_id: str, name: str):
    located = context.holdings.member_named(caller.realm_id, team_id, name)
    if located is None:
        raise refusals.UnknownName(name, namespace="member")
    return located


def _service(context: Context, caller: Observer, name: str):
    located = context.holdings.service_named(caller.realm_id, name)
    if located is None:
        raise refusals.UnknownName(name, namespace="service")
    return located


def _known(context: Context, caller: Observer, team_id: str, filters: messages.Filters) -> None:
    """A name filtered by has to exist, in the namespace its kind names.

    Refused rather than answered with nothing: an empty answer to a mistyped name
    looks exactly like an empty answer to a correct one, and the observer has no way
    to tell which they got.
    """
    for person in (filters.sender, filters.recipient):
        if person is None:
            continue
        if person.kind == "peer":
            if context.holdings.member_named(caller.realm_id, team_id, person.name) is None:
                raise refusals.UnknownName(person.name, namespace="member")
        elif context.holdings.service_named(caller.realm_id, person.name) is None:
            raise refusals.UnknownName(person.name, namespace="service")


def _entry(envelope: messages.Envelope, *, with_attachments: bool = False) -> dict[str, Any]:
    """One line of the traffic, or one whole envelope.

    The team is not in here: it is in the address, and no field carries what is
    already in the path — the same rule as "no path carries what is already in the
    token", one level up.
    """
    made: dict[str, Any] = {
        "message_id": envelope.message_id,
        "sender_kind": envelope.sender.kind,
        "sender_name": envelope.sender.name,
        "recipients": [{"kind": p.kind, "name": p.name} for p in envelope.recipients],
        "sent_at": envelope.sent_at,
        "subject": envelope.subject,
        "body_size": envelope.body_size,
        "total_size": envelope.total_size,
        "in_reply_to": envelope.in_reply_to,
    }
    if with_attachments:
        made["attachments"] = envelope.attachments
    else:
        made["attachment_count"] = len(envelope.attachments)
    return made
