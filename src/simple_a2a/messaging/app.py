"""The participant surface: where the agents are, and the only one they ever see.

Nothing here names a realm and nothing here names a team in an address: the token
says both. For somebody working here the realm is the universe — they see their team
and the registry of their installation, and there is no answer on this surface from
which anything else can be inferred.

Two kinds of caller share it, and the difference is the shape rather than a rule. A
member of a team has a team, addressees and both texts. A central service has
neither team nor addressee: it answers what it received, by sending to the alias that
came with it. Everything a service cannot do it is refused with **its own** way
forward, because telling it to obtain a token it cannot obtain would cost it an
attempt to find out.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from simple_a2a.core import limits, tokens
from simple_a2a.describe import http
from simple_a2a.describe.http import guard
from simple_a2a.domain import access, messages, refusals
from simple_a2a.domain.callers import Caller, Peer, Service
from simple_a2a.domain.context import Context
from simple_a2a.messaging import models, prose, texts

SURFACE = "messaging"

DESCRIPTION = (
    "The participant surface of a simple-a2a installation: your team, the registry, "
    "sending, receiving, files and invitations."
)

PeerName = Annotated[
    str,
    Path(
        description="The name of somebody in your team, compared without regard to case. "
        "GET /peers lists them.",
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
        description="The identifier of a message, 43 characters. Whoever has it may fetch "
        "the message: an identifier is the permission.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    ),
]
FileId = Annotated[
    str,
    Path(
        description="The identifier of a deposited file, 43 characters.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    ),
]
FileName = Annotated[
    str,
    Path(
        description="The name to save the file under. Yours to choose — it need not match "
        "what any message called it — and it is not a path.",
        examples=["shopping-list.md"],
    ),
]
AliasName = Annotated[
    str,
    Path(
        description="An alias that came with a message you received. It belongs to that one "
        "delivery and to nothing else.",
        examples=["the-alias-is-43-characters-of-base64url"],
    ),
]


#: What a caller might write about themselves; the example of the raw body.
_SELF_IMAGE_EXAMPLE = "I keep the shopping list and know what is in the fridge."


def build_app(context: Context, *, build: dict[str, str]) -> FastAPI:
    register = texts.build()
    app = FastAPI(
        title="simple-a2a participants",
        description=DESCRIPTION,
        openapi_url="/openapi.json",
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=http.identifier_of,
    )
    app.include_router(http.cascade(SURFACE, description=DESCRIPTION, build=build, offers_mcp=True))
    http.install_handlers(app, register, surface_entry=lambda request: "/")
    http.serve_described_openapi(app)

    def here(request: Request) -> str:
        return f"{request.method} {request.scope['route'].path_format}"

    async def anyone(request: Request, authorization: http.Authorization = None) -> Caller:
        with guard(here(request)):
            caller = access.authenticate(context, tokens.from_authorization(authorization))
            if isinstance(caller, Peer | Service):
                return caller
            # An operator's or an observer's secret is valid and of the wrong kind here.
            raise refusals.WrongToken("agent-in-team")

    async def a_peer(request: Request, authorization: http.Authorization = None) -> Peer:
        with guard(here(request)):
            return access.as_peer(
                access.authenticate(context, tokens.from_authorization(authorization))
            )

    async def a_service(request: Request, authorization: http.Authorization = None) -> Service:
        with guard(here(request)):
            return access.as_service(
                access.authenticate(context, tokens.from_authorization(authorization))
            )

    anyone_of = Depends(anyone)
    peer_of = Depends(a_peer)
    service_of = Depends(a_service)
    offset_of = Query(None, description="Where the window starts. From 0.", examples=[0])
    limit_of = Query(
        None, description="How many entries at most. Defaults to 25, at most 100.", examples=[25]
    )

    # -- orientation -------------------------------------------------------

    @app.get(
        "/team",
        summary="Your team: who is in it, and where to look next. The natural first call.",
        response_class=Response,
    )
    async def own_team(request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /team"):
            team = context.holdings.team(caller.realm_id, caller.team_id)
            purpose = context.holdings.team_purpose(caller.realm_id, caller.team_id) or ""
            count = sum(1 for _ in context.holdings.members(caller.realm_id, caller.team_id))
            return http.prose(
                prose.team(
                    team_name=team.name if team else "",
                    member_count=count,
                    purpose_set=bool(purpose.strip()),
                ),
                request,
            )

    @app.get(
        "/team/purpose",
        summary="What your team is for, in the words of whoever created it.",
        response_class=Response,
    )
    async def team_purpose(request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /team/purpose"):
            return http.prose(
                context.holdings.team_purpose(caller.realm_id, caller.team_id) or "", request
            )

    @app.get(
        "/me",
        summary="Who you are here, what you carry, and the two texts about you. Prose by "
        "default; with `Accept: application/json`, the same facts as data.",
        response_class=Response,
        responses={
            200: {
                "description": "Prose that branches to your texts — or, if you ask for "
                "application/json first, your kind, name, team and right as data.",
                "model": models.Me,
                "content": http.PROSE_OR_DATA,
            }
        },
    )
    async def me(request: Request, caller: Caller = anyone_of) -> Response:
        with guard("GET /me"):
            if http.wants_data(request):
                kind = "peer" if isinstance(caller, Peer) else "service"
                facts: dict[str, Any] = {"kind": kind, "name": caller.name}
                if isinstance(caller, Peer):
                    team = context.holdings.team(caller.realm_id, caller.team_id)
                    facts["team_name"] = team.name if team else None
                    facts["is_realm_master"] = caller.is_realm_master
                return JSONResponse(facts, media_type=http.JSON)
            if isinstance(caller, Service):
                located = context.holdings.service(caller.realm_id, caller.service_id)
                text = (
                    context.holdings.service_self_image(
                        caller.realm_id, caller.service_id, located.state
                    )
                    or ""
                    if located
                    else ""
                )
                return http.prose(
                    prose.me_as_service(name=caller.name, self_image_set=bool(text.strip())),
                    request,
                )
            assert isinstance(caller, Peer)
            team = context.holdings.team(caller.realm_id, caller.team_id)
            located = context.holdings.member(caller.realm_id, caller.team_id, caller.member_id)
            text = (
                context.holdings.member_self_image(
                    caller.realm_id, caller.team_id, caller.member_id, located.state
                )
                or ""
                if located
                else ""
            )
            return http.prose(
                prose.me_as_peer(
                    name=caller.name,
                    team_name=team.name if team else "",
                    is_realm_master=caller.is_realm_master,
                    self_image_set=bool(text.strip()),
                ),
                request,
            )

    @app.get(
        "/me/mission",
        summary="What you were invited for. Set when you joined, and unchanged since.",
        response_class=Response,
    )
    async def my_mission(request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /me/mission"):
            located = context.holdings.member(caller.realm_id, caller.team_id, caller.member_id)
            text = (
                context.holdings.member_mission(
                    caller.realm_id, caller.team_id, caller.member_id, located.state
                )
                if located
                else ""
            )
            return http.prose(text or "", request)

    @app.get(
        "/me/self",
        summary="What you say about yourself. Empty until you write something.",
        response_class=Response,
    )
    async def my_self_image(request: Request, caller: Caller = anyone_of) -> Response:
        with guard("GET /me/self"):
            return http.prose(_self_image(context, caller), request)

    @app.put(
        "/me/self",
        summary="Replace what you say about yourself. The body is the text itself.",
        response_model=models.TextLength,
        openapi_extra=http.raw_body(
            "text/plain",
            {"type": "string", "examples": [_SELF_IMAGE_EXAMPLE]},
            "The text itself, raw, in UTF-8 — not JSON, so there is nothing to escape. "
            f"Up to {limits.MEMBER_SELF_IMAGE_MAX_CHARS} characters. Markdown is a good "
            "choice and nothing here reads it.",
        ),
    )
    async def set_my_self_image(request: Request, caller: Caller = anyone_of) -> Any:
        with guard("PUT /me/self"):
            text = await _raw(request)
            return {"length": _write_self_image(context, caller, text)}

    # -- the two directories ----------------------------------------------

    @app.get(
        "/peers",
        summary="Who else is in your team. These are the names you can address. Prose by "
        "default; with `Accept: application/json`, the same list as data.",
        response_class=Response,
        responses={
            200: {
                "description": "Prose naming each member with their marks and the addresses "
                "of their texts — or, if you ask for application/json first, the same window "
                "as `entries`.",
                "model": models.Peers,
                "content": http.PROSE_OR_DATA,
            }
        },
    )
    async def peers(
        request: Request,
        caller: Peer = peer_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Response:
        with guard("GET /peers"):
            window = access.Window.of(offset, limit)
            everyone = access.members(
                context, caller.realm_id, caller.team_id, access.Window.of(0, 100)
            )
            shown = [entry for entry in everyone if entry["member_name"] != caller.name]
            if http.wants_data(request):
                return JSONResponse(
                    {
                        "entries": [
                            {
                                "kind": "peer",
                                "name": entry["member_name"],
                                "is_realm_master": entry["is_realm_master"],
                                "token_revoked": entry["token_revoked"],
                            }
                            for entry in window.over(shown)
                        ]
                    },
                    media_type=http.JSON,
                )
            return http.prose(
                prose.peers(
                    entries=window.over(shown),
                    offset=window.offset,
                    limit=window.limit,
                    total=len(shown),
                ),
                request,
            )

    @app.get("/peers/{name}", summary="One member of your team.", response_class=Response)
    async def one_peer(name: PeerName, request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /peers/{name}"):
            located = _peer(context, caller, name)
            return http.prose(
                prose.peer(
                    name=located.record.name,
                    is_realm_master=located.record.is_realm_master,
                    revoked=located.record.revoked_at is not None,
                ),
                request,
            )

    @app.get(
        "/peers/{name}/mission",
        summary="What they were invited for.",
        response_class=Response,
    )
    async def peer_mission(name: PeerName, request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /peers/{name}/mission"):
            located = _peer(context, caller, name)
            return http.prose(
                context.holdings.member_mission(
                    caller.realm_id, caller.team_id, located.record.id, located.state
                )
                or "",
                request,
            )

    @app.get(
        "/peers/{name}/self", summary="What they say about themselves.", response_class=Response
    )
    async def peer_self(name: PeerName, request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /peers/{name}/self"):
            located = _peer(context, caller, name)
            return http.prose(
                context.holdings.member_self_image(
                    caller.realm_id, caller.team_id, located.record.id, located.state
                )
                or "",
                request,
            )

    @app.get(
        "/services",
        summary="The central services here: addressed by name, and not in your team.",
        response_class=Response,
    )
    async def services(
        request: Request,
        caller: Peer = peer_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Response:
        with guard("GET /services"):
            window = access.Window.of(offset, limit)
            everyone = access.services(context, caller.realm_id, access.Window.of(0, 100))
            return http.prose(
                prose.services(
                    entries=window.over(everyone),
                    offset=window.offset,
                    limit=window.limit,
                    total=len(everyone),
                ),
                request,
            )

    @app.get("/services/{name}", summary="One central service.", response_class=Response)
    async def one_service(name: ServiceName, request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /services/{name}"):
            located = _service(context, caller, name)
            return http.prose(
                prose.service(
                    name=located.record.name, revoked=located.record.revoked_at is not None
                ),
                request,
            )

    @app.get(
        "/services/{name}/self",
        summary="What a central service says it can do. Its only text.",
        response_class=Response,
    )
    async def service_self(name: ServiceName, request: Request, caller: Peer = peer_of) -> Response:
        with guard("GET /services/{name}/self"):
            located = _service(context, caller, name)
            return http.prose(
                context.holdings.service_self_image(
                    caller.realm_id, located.record.id, located.state
                )
                or "",
                request,
            )

    # -- sending -----------------------------------------------------------

    @app.post(
        "/peers/messages",
        summary="Send to members of your team. An empty recipient list means everybody else.",
        response_model=models.Sent,
    )
    async def send_to_peers(
        body: models.SendToPeers, request: Request, caller: Peer = peer_of
    ) -> Any:
        with guard("POST /peers/messages"):
            return _sent(
                messages.send_to_peers(
                    context,
                    caller,
                    recipients=body.recipients,
                    subject=body.subject,
                    body=body.body,
                    body_file_id=body.body_file_id,
                    attachments=_attachments(body.attachments),
                    in_reply_to=body.in_reply_to,
                )
            )

    @app.post(
        "/services/messages",
        summary="Send to one central service. Same shape, one word different.",
        response_model=models.Sent,
    )
    async def send_to_service(
        body: models.SendToService, request: Request, caller: Peer = peer_of
    ) -> Any:
        with guard("POST /services/messages"):
            return _sent(
                messages.send_to_service(
                    context,
                    caller,
                    recipient=body.recipient,
                    subject=body.subject,
                    body=body.body,
                    body_file_id=body.body_file_id,
                    attachments=_attachments(body.attachments),
                    in_reply_to=body.in_reply_to,
                )
            )

    @app.post(
        "/aliases/{alias}/messages",
        summary="Answer along an alias. The central service's one way of sending.",
        response_model=models.Sent,
    )
    async def send_to_alias(
        alias: AliasName,
        body: models.SendToAlias,
        request: Request,
        caller: Service = service_of,
    ) -> Any:
        with guard("POST /aliases/{alias}/messages"):
            return _sent(
                messages.send_to_alias(
                    context,
                    caller,
                    alias=alias,
                    subject=body.subject,
                    body=body.body,
                    body_file_id=body.body_file_id,
                    attachments=_attachments(body.attachments),
                )
            )

    # -- receiving ---------------------------------------------------------

    @app.get(
        "/inbox",
        summary="What arrived, newest first, envelopes only. No read state is kept.",
        response_model=models.Mailbox,
        response_model_exclude_none=True,
    )
    async def inbox(
        request: Request,
        caller: Caller = anyone_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /inbox"):
            return _mailbox(context, caller, messages.INBOX, offset, limit)

    @app.get(
        "/outbox",
        summary="What you sent, newest first. It exists because you lose your context.",
        response_model=models.Mailbox,
        response_model_exclude_none=True,
    )
    async def outbox(
        request: Request,
        caller: Caller = anyone_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /outbox"):
            return _mailbox(context, caller, messages.OUTBOX, offset, limit)

    @app.get(
        "/messages/{message_id}",
        summary="The envelope of one message. Not the body: that has its own address.",
        response_model=models.Envelope,
        response_model_exclude_none=True,
    )
    async def envelope(message_id: MessageId, request: Request, caller: Caller = anyone_of) -> Any:
        with guard("GET /messages/{message_id}"):
            return models.envelope_body(messages.envelope(context, caller, message_id))

    @app.get("/messages/{message_id}/subject", summary="The subject, raw.", response_class=Response)
    async def subject(
        message_id: MessageId, request: Request, caller: Caller = anyone_of
    ) -> Response:
        with guard("GET /messages/{message_id}/subject"):
            return http.prose(messages.subject_of(context, caller, message_id), request)

    @app.get(
        "/messages/{message_id}/body",
        summary="The body, raw and exactly as it was sent. Nothing here has read it.",
        response_class=Response,
    )
    async def message_body(
        message_id: MessageId, request: Request, caller: Caller = anyone_of
    ) -> Response:
        with guard("GET /messages/{message_id}/body"):
            return http.prose(messages.body_of(context, caller, message_id), request)

    # -- files -------------------------------------------------------------

    @app.post(
        "/files",
        summary="Deposit a file. The body is its bytes; the name goes on the envelope.",
        response_model=models.FileDeposited,
        openapi_extra=http.raw_body(
            "application/octet-stream",
            {"type": "string", "format": "binary", "examples": ["<the bytes of the file>"]},
            "The content of the file, raw — not a multipart form. Send its media type as "
            "Content-Type: it is remembered and handed back on every fetch; without one the "
            "file is text/plain. At most "
            f"{context.config.file_max_bytes} bytes on this installation. Agree on "
            "co-location first: on the same machine, a path in a message body beats an "
            "upload.",
        ),
    )
    async def deposit(request: Request, caller: Caller = anyone_of) -> Any:
        with guard("POST /files"):
            assert isinstance(caller, Peer | Service)
            file_id, size, said = messages.deposit_file(
                context, caller, await request.body(), request.headers.get("content-type")
            )
            return {"file_id": file_id, "size": size, "media_type": said}

    @app.get(
        "/files/{file_id}/{file_name:path}",
        summary="Fetch a file. The name in the address is the name it is saved under.",
        response_class=Response,
        responses={
            200: {
                "description": "The bytes, exactly as deposited, with the media type its "
                "depositor sent as Content-Type — text/plain if none was sent.",
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def fetch(
        file_id: FileId, file_name: FileName, request: Request, caller: Caller = anyone_of
    ) -> Response:
        with guard("GET /files/{file_id}/{file_name}"):
            safe = messages.safe_file_name(file_name)
            content, said = messages.fetch_file(context, caller, file_id)
            return Response(
                content,
                media_type=said or http.media_type(safe),
                headers={"Content-Disposition": f'attachment; filename="{safe}"'},
            )

    # -- inviting, founding, appointing ------------------------------------

    @app.post(
        "/invitations/peer",
        summary="Invite somebody into your team. Anybody here may.",
        response_model=models.InvitationGiven,
        response_model_exclude_none=True,
    )
    async def invite_peer(
        body: models.InviteePeer, request: Request, caller: Peer = peer_of
    ) -> Any:
        with guard("POST /invitations/peer"):
            mission = _text_or_file(
                context, caller, body.member_mission, body.member_mission_file_id, "member_mission"
            )
            team = context.holdings.team(caller.realm_id, caller.team_id)
            voucher = access.obtain_member_invitation(
                context,
                realm_id=caller.realm_id,
                team_id=caller.team_id,
                member_name=body.member_name,
                mission=mission,
                display_name=body.display_name,
                issued_by_kind="member",
                issued_by_name=caller.name,
                grants_realm_master=False,
            )
            return {
                "display_name": body.display_name,
                "invitation": voucher,
                "member_name": body.member_name,
                "team_name": team.name if team else None,
            }

    @app.post(
        "/invitations/service",
        summary="Obtain an invitation for a central service. Only a realm master may.",
        response_model=models.InvitationGiven,
        response_model_exclude_none=True,
    )
    async def invite_service(
        body: models.InviteeService, request: Request, caller: Peer = peer_of
    ) -> Any:
        with guard("POST /invitations/service"):
            voucher = access.obtain_service_invitation(
                context, caller, service_name=body.service_name, display_name=body.display_name
            )
            return {
                "display_name": body.display_name,
                "invitation": voucher,
                "service_name": body.service_name,
            }

    @app.post(
        "/invitations/redeem",
        summary="Exchange an invitation for a token. The one call that needs no token.",
        response_model=models.Redeemed,
        response_model_exclude_none=True,
    )
    async def redeem(body: models.Redeem, request: Request) -> Any:
        with guard("POST /invitations/redeem"):
            identity = access.redeem(context, body.invitation, self_image=body.member_self_image)
            answer: dict[str, Any] = {
                "token": identity.token,
                "kind": identity.kind,
                "name": identity.name,
            }
            # A central service has no team and cannot carry the right, so neither
            # field is named for one: a null would say "there is one, and it is
            # nothing".
            if identity.team_name is not None:
                answer["team_name"] = identity.team_name
                answer["is_realm_master"] = identity.is_realm_master
            return answer

    @app.post(
        "/teams",
        summary="Create a team and be its first member. Anybody here may.",
        response_model=models.TeamFounded,
    )
    async def found_team(body: models.FoundTeam, request: Request, caller: Peer = peer_of) -> Any:
        with guard("POST /teams"):
            purpose = _text_or_file(
                context, caller, body.team_purpose, body.team_purpose_file_id, "team_purpose"
            )
            mission = _text_or_file(
                context, caller, body.member_mission, body.member_mission_file_id, "member_mission"
            )
            identity = access.found_team(context, caller, body.team_name, purpose, mission)
            return {
                "team_name": identity.team_name,
                "token": identity.token,
                "is_realm_master": identity.is_realm_master,
            }

    @app.post(
        "/peers/{name}/realmmaster",
        summary="Appoint a realm master in your own team. Only a realm master may.",
        response_model=models.Appointed,
    )
    async def appoint(name: PeerName, request: Request, caller: Peer = peer_of) -> Any:
        with guard("POST /peers/{name}/realmmaster"):
            access.appoint_realm_master(context, caller, name)
            return {"member_name": name, "is_realm_master": True}

    return app


# --------------------------------------------------------------------- helpers


def _peer(context: Context, caller: Peer, name: str):
    located = context.holdings.member_named(caller.realm_id, caller.team_id, name)
    if located is None:
        raise refusals.UnknownName(name, namespace="member")
    return located


def _service(context: Context, caller: Peer, name: str):
    located = context.holdings.service_named(caller.realm_id, name)
    if located is None:
        raise refusals.UnknownName(name, namespace="service")
    return located


def _self_image(context: Context, caller: Caller) -> str:
    if isinstance(caller, Service):
        located = context.holdings.service(caller.realm_id, caller.service_id)
        if located is None:
            return ""
        return (
            context.holdings.service_self_image(caller.realm_id, caller.service_id, located.state)
            or ""
        )
    assert isinstance(caller, Peer)
    located = context.holdings.member(caller.realm_id, caller.team_id, caller.member_id)
    if located is None:
        return ""
    return (
        context.holdings.member_self_image(
            caller.realm_id, caller.team_id, caller.member_id, located.state
        )
        or ""
    )


def _write_self_image(context: Context, caller: Caller, text: str) -> int:
    if len(text) > limits.MEMBER_SELF_IMAGE_MAX_CHARS:
        raise refusals.TooLarge(
            "member_self_image",
            limit=limits.MEMBER_SELF_IMAGE_MAX_CHARS,
            actual=len(text),
            unit="characters",
        )
    if isinstance(caller, Service):
        located = context.holdings.service(caller.realm_id, caller.service_id)
        if located is not None:
            context.holdings.set_service_self_image(
                caller.realm_id, caller.service_id, located.state, text
            )
    else:
        assert isinstance(caller, Peer)
        located = context.holdings.member(caller.realm_id, caller.team_id, caller.member_id)
        if located is not None:
            context.holdings.set_member_self_image(
                caller.realm_id, caller.team_id, caller.member_id, located.state, text
            )
    return len(text)


def _attachments(entries: list[models.AttachmentIn] | None) -> list[dict[str, Any]] | None:
    """Back to plain dictionaries, with absent fields absent.

    The operations check the shape themselves — exactly one identifier, no `size`
    sent in — and they have to see what the caller sent rather than a model's
    defaults filled in around it.
    """
    if entries is None:
        return None
    return [entry.model_dump(exclude_none=True) for entry in entries]


def _sent(sent: messages.Sent) -> dict[str, Any]:
    return {
        "message_id": sent.message_id,
        "sent_at": sent.sent_at,
        "recipients": [{"kind": p.kind, "name": p.name} for p in sent.recipients],
        "warnings": [
            {"code": code, "message": _WARNINGS[code]}
            for code in sent.warnings
            if code in _WARNINGS
        ],
    }


#: The one warning there is, with the text it teaches. A closed catalogue like the
#: rejections', and for the same reason: an open code space beside a closed one lets
#: back in what the closed one shut out.
_WARNINGS = {
    refusals.NO_RECIPIENT: (
        "Nobody else is in your team, so an empty recipient list resolved to nobody. The "
        "message is in your outbox and reached no one. Invite somebody with "
        "POST /invitations/peer and send again."
    )
}


def _mailbox(
    context: Context, caller: Caller, view: str, offset: int | None, limit: int | None
) -> dict[str, Any]:
    assert isinstance(caller, Peer | Service)
    window = access.Window.of(offset, limit)
    lines = messages.mailbox(context, caller, view, offset=window.offset, limit=window.limit)
    return {
        "entries": [
            {
                "message_id": line.message_id,
                "sender_kind": line.sender.kind if line.sender else None,
                "sender_name": line.sender.name if line.sender else None,
                "recipients": (
                    [{"kind": p.kind, "name": p.name} for p in line.recipients]
                    if line.recipients is not None
                    else None
                ),
                "sent_at": line.sent_at,
                "subject": line.subject,
                "body_size": line.body_size,
                "total_size": line.total_size,
                "attachment_count": line.attachment_count,
                "in_reply_to": line.in_reply_to,
            }
            for line in lines
        ]
    }


def _text_or_file(
    context: Context, caller: Peer, text: str | None, file_id: str | None, field: str
) -> str:
    """Text or reference, and exactly one of the two.

    The limit belongs to the **parameter**, not to the file: what a referenced file
    becomes is a mission or a purpose, and that is what it is measured against.
    """
    from simple_a2a.core.ids import is_id

    if (text is None) == (file_id is None):
        raise refusals.InvalidInput(field, reason=f"exactly one of {field} and {field}_file_id")
    if text is not None:
        found = text
    else:
        if not is_id(file_id):
            raise refusals.InvalidInput(f"{field}_file_id", reason="not an identifier")
        raw = context.holdings.file_content(caller.realm_id, str(file_id))
        if raw is None:
            raise refusals.UnknownIdentifier("file")
        try:
            found = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise refusals.InvalidInput(f"{field}_file_id", reason="not valid UTF-8") from None
    limit = {
        "member_mission": limits.MEMBER_MISSION_MAX_CHARS,
        "team_purpose": limits.TEAM_PURPOSE_MAX_CHARS,
    }[field]
    if len(found) > limit:
        raise refusals.TooLarge(field, limit=limit, actual=len(found), unit="characters")
    return found


async def _raw(request: Request) -> str:
    raw = await request.body()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise refusals.InvalidInput("body", reason="not valid UTF-8") from None
