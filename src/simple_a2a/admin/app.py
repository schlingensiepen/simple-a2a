"""The administration surface: the only door in, and the only place that revokes.

Nothing is implicit here. The operator works across realms, so every address names
the realm it is about — unlike the participant surface, where the token says it.
The overlap with the observation surface is deliberate: another purpose, other
fields, and it has to keep working when observation is switched off.

Every operation on this surface takes the administration secret and no other kind.
It is checked against the value the process was started with, which is kept outside
the holdings so that it works on an installation where nothing else exists yet.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Path, Query, Request, Response

from simple_a2a.admin import models, texts
from simple_a2a.core import tokens
from simple_a2a.describe import http
from simple_a2a.describe.http import guard
from simple_a2a.domain import access
from simple_a2a.domain.callers import Operator
from simple_a2a.domain.context import Context

SURFACE = "admin"

#: The names that stand in a path here. Declared at module level because this
#: module postpones annotation evaluation: a name from a closure would not resolve,
#: and the parameter would arrive undescribed — which the gate catches, but only
#: after it has been written wrong.
RealmName = Annotated[
    str,
    Path(
        description="Which realm this is about. The operator works across realms, so it "
        "is named here rather than implied. GET /realms lists them.",
        examples=["household"],
    ),
]
TeamName = Annotated[
    str,
    Path(
        description="Which team in that realm. GET /realms/{realm}/teams lists them.",
        examples=["kitchen"],
    ),
]
MemberName = Annotated[
    str,
    Path(
        description="The name of an identity in that team, compared without regard to "
        "case. GET /realms/{realm}/teams/{team}/members lists them.",
        examples=["Anna"],
    ),
]
ServiceName = Annotated[
    str,
    Path(
        description="The name of a central service in that realm's registry. "
        "GET /realms/{realm}/services lists them.",
        examples=["weather"],
    ),
]
Handle = Annotated[
    str,
    Path(
        description="The display name a secret was given when it came into being. This "
        "is how it is addressed — never the secret itself.",
        examples=["voucher for Anna"],
    ),
]

DESCRIPTION = (
    "Administration of a simple-a2a installation: realms, teams, invitations, "
    "observer tokens, revocations and the two setup notes."
)


def _window(offset: int | None, limit: int | None) -> access.Window:
    return access.Window.of(offset, limit)


def build_app(context: Context, *, build: dict[str, str]) -> FastAPI:
    """The administration application. One of three in one process."""
    register = texts.build()
    app = FastAPI(
        title="simple-a2a administration",
        description=DESCRIPTION,
        openapi_url="/openapi.json",
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=http.identifier_of,
    )
    app.include_router(http.cascade(SURFACE, description=DESCRIPTION, build=build))
    # The generated description, minus the framework's own validation error: we
    # never answer with it, and advertising it would mean a fourteenth kind of
    # rejection in a catalogue that says it is closed.
    http.serve_described_openapi(app)
    http.install_handlers(app, register, surface_entry=lambda request: "/")

    async def operator(request: Request, authorization: http.Authorization = None) -> Operator:
        """Who is calling, and it has to be the operator.

        The operation named in the refusal is the address being called, because that
        is what decides the text — not the place the check happens to live.
        """
        with guard(f"{request.method} {request.scope['route'].path}"):
            return access.as_operator(
                access.authenticate(context, tokens.from_authorization(authorization))
            )

    # Declared as defaults rather than as annotations: this module postpones
    # annotation evaluation, so a name that exists only inside this function cannot
    # be resolved from outside it — the dependency would silently become a query
    # parameter, which is exactly how the first version of this failed.
    caller_of = Depends(operator)
    offset_of = Query(None, description="Where the window starts. From 0.", examples=[0])
    limit_of = Query(
        None, description="How many entries at most. Defaults to 25, at most 100.", examples=[25]
    )

    def realm_id(request: Request, realm: str) -> str:
        with guard(f"{request.method} {request.scope['route'].path}"):
            return access.realm_by_name(context, realm).id

    def team_id(request: Request, realm: str, team: str) -> tuple[str, str]:
        with guard(f"{request.method} {request.scope['route'].path}"):
            found = access.realm_by_name(context, realm)
            return found.id, access.team_by_name(context, found.id, team).id

    # -- realms ------------------------------------------------------------

    @app.post(
        "/realms",
        summary="Create a realm. A container for teams and one registry; an empty one is fine.",
        response_model=models.RealmOut,
    )
    async def create_realm(
        body: models.RealmIn, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("POST /realms"):
            return {"realm_name": access.create_realm(context, body.realm_name)}

    @app.get(
        "/realms",
        summary="Every realm of this installation, with how much is in each.",
        response_model=models.RealmList,
    )
    async def list_realms(
        request: Request,
        caller: Operator = caller_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /realms"):
            return {"realms": access.realms(context, _window(offset, limit))}

    # -- teams -------------------------------------------------------------

    @app.post(
        "/realms/{realm}/teams",
        summary="Create a team in a realm. An empty team is idle, not broken.",
        response_model=models.TeamOut,
    )
    async def create_team(
        realm: RealmName, body: models.TeamIn, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("POST /realms/{realm}/teams"):
            found = access.realm_by_name(context, realm)
            return {
                "team_name": access.create_team(
                    context, found.id, body.team_name, body.team_purpose
                )
            }

    @app.get(
        "/realms/{realm}/teams",
        summary="The teams of one realm, by name.",
        response_model=models.TeamList,
    )
    async def list_teams(
        realm: RealmName,
        request: Request,
        caller: Operator = caller_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /realms/{realm}/teams"):
            found = access.realm_by_name(context, realm)
            return {"teams": access.teams(context, found.id, _window(offset, limit))}

    @app.get(
        "/realms/{realm}/teams/{team}/members",
        summary="The identities of one team: management state, no content.",
        response_model=models.MemberList,
    )
    async def list_members(
        realm: RealmName,
        team: TeamName,
        request: Request,
        caller: Operator = caller_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /realms/{realm}/teams/{team}/members"):
            in_realm, in_team = team_id(request, realm, team)
            return {"members": access.members(context, in_realm, in_team, _window(offset, limit))}

    # -- the registry ------------------------------------------------------

    @app.get(
        "/realms/{realm}/services",
        summary="The registry of one realm: which central services it has.",
        response_model=models.ServiceList,
    )
    async def list_services(
        realm: RealmName,
        request: Request,
        caller: Operator = caller_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /realms/{realm}/services"):
            found = access.realm_by_name(context, realm)
            return {"services": access.services(context, found.id, _window(offset, limit))}

    # -- invitations -------------------------------------------------------

    @app.post(
        "/realms/{realm}/teams/{team}/invitations",
        summary="Obtain an invitation into a team. Whoever redeems it becomes a realm master.",
        response_model=models.InvitationOut,
    )
    async def obtain_invitation(
        realm: RealmName,
        team: TeamName,
        body: models.InvitationIn,
        request: Request,
        caller: Operator = caller_of,
    ) -> Any:
        with guard("POST /realms/{realm}/teams/{team}/invitations"):
            found = access.realm_by_name(context, realm)
            in_team = access.team_by_name(context, found.id, team)
            voucher = access.obtain_member_invitation(
                context,
                realm_id=found.id,
                team_id=in_team.id,
                member_name=body.member_name,
                mission=body.member_mission,
                display_name=body.display_name,
                issued_by_kind="operator",
                issued_by_name="operator",
                grants_realm_master=True,
            )
            return {
                "display_name": body.display_name,
                "invitation": voucher,
                "team_name": in_team.name,
            }

    @app.get(
        "/realms/{realm}/invitations",
        summary="Every invitation of one realm, used-up and revoked ones included.",
        response_model=models.InvitationList,
        # A field that does not apply is absent rather than null: `issued_by` is
        # named only where somebody in a team obtained it, and `redeemed_at` only
        # once it has been used. A null would say "there is one, and it is nothing".
        response_model_exclude_none=True,
    )
    async def list_invitations(
        realm: RealmName,
        request: Request,
        caller: Operator = caller_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /realms/{realm}/invitations"):
            found = access.realm_by_name(context, realm)
            return {"invitations": access.invitations(context, found.id, _window(offset, limit))}

    @app.delete(
        "/realms/{realm}/invitations/{display_name}",
        summary="Revoke an invitation by its handle. Never by the secret.",
        response_model=models.InvitationRevoked,
        response_model_exclude_none=True,
    )
    async def revoke_invitation(
        realm: RealmName, display_name: Handle, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("DELETE /realms/{realm}/invitations/{display_name}"):
            found = access.realm_by_name(context, realm)
            revoked = access.revoke_invitation(context, found.id, display_name)
            return {
                "display_name": revoked.name,
                "revoked": revoked.revoked,
                "revoked_at": revoked.revoked_at,
            }

    # -- revocations -------------------------------------------------------

    @app.delete(
        "/realms/{realm}/teams/{team}/members/{name}/token",
        summary="Revoke an identity's token. The identity stays, visible and readable.",
        response_model=models.MemberRevoked,
        response_model_exclude_none=True,
    )
    async def revoke_member(
        realm: RealmName,
        team: TeamName,
        name: MemberName,
        request: Request,
        caller: Operator = caller_of,
    ) -> Any:
        with guard("DELETE /realms/{realm}/teams/{team}/members/{name}/token"):
            in_realm, in_team = team_id(request, realm, team)
            revoked = access.revoke_member_token(context, in_realm, in_team, name)
            return {
                "member_name": revoked.name,
                "token_revoked": revoked.revoked,
                "revoked_at": revoked.revoked_at,
            }

    @app.delete(
        "/realms/{realm}/services/{name}/token",
        summary="Revoke a central service's token. It stays in the registry.",
        response_model=models.ServiceRevoked,
        response_model_exclude_none=True,
    )
    async def revoke_service(
        realm: RealmName, name: ServiceName, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("DELETE /realms/{realm}/services/{name}/token"):
            found = access.realm_by_name(context, realm)
            revoked = access.revoke_service_token(context, found.id, name)
            return {
                "service_name": revoked.name,
                "token_revoked": revoked.revoked,
                "revoked_at": revoked.revoked_at,
            }

    @app.delete(
        "/realms/{realm}/teams/{team}/members/{name}/realmmaster",
        summary="Take the one stored right away. The token stays valid.",
        response_model=models.RealmMasterOut,
    )
    async def revoke_realm_master(
        realm: RealmName,
        team: TeamName,
        name: MemberName,
        request: Request,
        caller: Operator = caller_of,
    ) -> Any:
        with guard("DELETE /realms/{realm}/teams/{team}/members/{name}/realmmaster"):
            in_realm, in_team = team_id(request, realm, team)
            access.revoke_realm_master(context, in_realm, in_team, name)
            return {"member_name": name, "is_realm_master": False}

    # -- observer tokens ---------------------------------------------------

    @app.post(
        "/realms/{realm}/observer-tokens",
        summary="Issue a token for watching one realm. Whenever you like, and again after a revocation.",
        response_model=models.ObserverOut,
    )
    async def issue_observer(
        realm: RealmName, body: models.ObserverIn, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("POST /realms/{realm}/observer-tokens"):
            found = access.realm_by_name(context, realm)
            handle, token = access.issue_observer_token(context, found.id, body.display_name)
            return {"display_name": handle, "token": token}

    @app.get(
        "/realms/{realm}/observer-tokens",
        summary="The observer tokens of one realm by their handles. Never the secrets.",
        response_model=models.ObserverList,
    )
    async def list_observers(
        realm: RealmName,
        request: Request,
        caller: Operator = caller_of,
        offset: int | None = offset_of,
        limit: int | None = limit_of,
    ) -> Any:
        with guard("GET /realms/{realm}/observer-tokens"):
            found = access.realm_by_name(context, realm)
            return {"observer_tokens": access.observers(context, found.id, _window(offset, limit))}

    @app.delete(
        "/realms/{realm}/observer-tokens/{display_name}",
        summary="Revoke an observer token by its handle.",
        response_model=models.ObserverRevoked,
        response_model_exclude_none=True,
    )
    async def revoke_observer(
        realm: RealmName, display_name: Handle, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("DELETE /realms/{realm}/observer-tokens/{display_name}"):
            found = access.realm_by_name(context, realm)
            revoked = access.revoke_observer_token(context, found.id, display_name)
            return {
                "display_name": revoked.name,
                "token_revoked": revoked.revoked,
                "revoked_at": revoked.revoked_at,
            }

    # -- the two notes -----------------------------------------------------

    @app.get(
        "/setup-note",
        summary="The installation-wide note, exactly as somebody wrote it.",
        response_class=Response,
    )
    async def read_note(request: Request, caller: Operator = caller_of) -> Response:
        with guard("GET /setup-note"):
            return http.prose(access.read_note(context), request)

    @app.put(
        "/setup-note",
        summary="Replace the installation-wide note. There is no appending.",
        response_model=models.NoteLength,
    )
    async def write_note(request: Request, caller: Operator = caller_of) -> Any:
        with guard("PUT /setup-note"):
            return {"length": access.write_note(context, await _raw(request))}

    @app.get(
        "/realms/{realm}/setup-note",
        summary="The note of one realm, exactly as somebody wrote it.",
        response_class=Response,
    )
    async def read_realm_note(
        realm: RealmName, request: Request, caller: Operator = caller_of
    ) -> Response:
        with guard("GET /realms/{realm}/setup-note"):
            found = access.realm_by_name(context, realm)
            return http.prose(access.read_note(context, found.id), request)

    @app.put(
        "/realms/{realm}/setup-note",
        summary="Replace the note of one realm. There is no appending.",
        response_model=models.NoteLength,
    )
    async def write_realm_note(
        realm: RealmName, request: Request, caller: Operator = caller_of
    ) -> Any:
        with guard("PUT /realms/{realm}/setup-note"):
            found = access.realm_by_name(context, realm)
            return {"length": access.write_note(context, await _raw(request), found.id)}

    return app


async def _raw(request: Request) -> str:
    """A raw body, as UTF-8 text.

    The body *is* the field here: there is no envelope around it, so an invalid
    encoding is reported against the body itself.
    """
    from simple_a2a.domain import refusals

    raw = await request.body()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise refusals.InvalidInput("body", reason="not valid UTF-8") from None
