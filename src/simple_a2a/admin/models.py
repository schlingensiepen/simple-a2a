"""What the administration surface takes in and gives back.

Every field carries a description and an example, and that is not decoration: the
example is what the gate insists on, because "the name of the realm" and
`"household"` are different amounts of help and only the second survives being
read by something that has never seen this service.

The names are the ones the specification uses. There is no translation layer
between a field here and a field there — a second vocabulary for one thing is
where typos live.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RealmIn(BaseModel):
    realm_name: str = Field(
        description="The name of the realm to create. Unique across the installation.",
        examples=["household"],
    )


class RealmOut(BaseModel):
    realm_name: str = Field(
        description="The realm that now exists. No secret comes with it: a realm is a "
        "container, and an empty one is allowed.",
        examples=["household"],
    )


class RealmEntry(BaseModel):
    realm_name: str = Field(description="The name of the realm.", examples=["household"])
    team_count: int = Field(
        description="How many teams are in it. Zero is a legitimate answer.", examples=[2]
    )
    service_count: int = Field(
        description="How many central services are in its registry.", examples=[1]
    )


class RealmList(BaseModel):
    realms: list[RealmEntry] = Field(
        description="The realms of this installation, by name, within the window asked for.",
        examples=[[{"realm_name": "household", "team_count": 2, "service_count": 1}]],
    )


class TeamIn(BaseModel):
    team_name: str = Field(
        description="The name of the team to create. Unique within the realm.",
        examples=["kitchen"],
    )
    team_purpose: str = Field(
        default="",
        description="What the team is for, as Markdown. Up to 8192 characters. May be "
        "empty: an empty team is idle, not broken.",
        examples=["We cook, and we agree on who cooks what."],
    )


class TeamOut(BaseModel):
    team_name: str = Field(
        description="The team that now exists. No secret comes with it.", examples=["kitchen"]
    )


class TeamEntry(BaseModel):
    team_name: str = Field(description="The name of the team.", examples=["kitchen"])
    member_count: int = Field(
        description="How many identities are in it, revoked ones included: nothing is "
        "deleted here.",
        examples=[3],
    )


class TeamList(BaseModel):
    teams: list[TeamEntry] = Field(
        description="The teams of this realm, by name, within the window asked for.",
        examples=[[{"team_name": "kitchen", "member_count": 3}]],
    )


class MemberEntry(BaseModel):
    member_name: str = Field(description="The name of the identity.", examples=["Anna"])
    is_realm_master: bool = Field(
        description="Whether this identity carries the one stored right: it may obtain "
        "invitations for central services and appoint further realm masters in its own team.",
        examples=[True],
    )
    token_revoked: bool = Field(
        description="Whether its token has been revoked. The identity stays visible and "
        "readable either way, because messages from it are in other mailboxes.",
        examples=[False],
    )


class MemberList(BaseModel):
    members: list[MemberEntry] = Field(
        description="The identities of this team: management state, no content.",
        examples=[[{"member_name": "Anna", "is_realm_master": True, "token_revoked": False}]],
    )


class ServiceEntry(BaseModel):
    service_name: str = Field(
        description="The name of the central service, unique across the realm.",
        examples=["weather"],
    )
    token_revoked: bool = Field(description="Whether its token has been revoked.", examples=[False])


class ServiceList(BaseModel):
    services: list[ServiceEntry] = Field(
        description="The registry of this realm: management state, no content.",
        examples=[[{"service_name": "weather", "token_revoked": False}]],
    )


class InvitationIn(BaseModel):
    member_name: str = Field(
        description="Who the identity will be once the invitation is redeemed. Fixed here, "
        "because you have to name somebody to give them a mission. Checked again at "
        "redemption, since it can be taken in between.",
        examples=["Anna"],
    )
    member_mission: str = Field(
        default="",
        description="What this person is being invited for, as Markdown, up to 8192 "
        "characters. It stays as it is: a mission is what somebody was asked to do, and a "
        "changed one is no longer that.",
        examples=["Keep the shopping list and say when something runs out."],
    )
    display_name: str = Field(
        description="How you will refer to this invitation afterwards. Listing and revoking "
        "go by it, never by the secret. Unique per kind within the realm.",
        examples=["voucher for Anna"],
    )


class InvitationOut(BaseModel):
    display_name: str = Field(
        description="The handle for this invitation.", examples=["voucher for Anna"]
    )
    invitation: str = Field(
        description="The voucher itself, in the clear, shown exactly once. There is no "
        "operation that gives it out again. Whoever redeems it becomes a realm master, "
        "without a parameter and without a choice: this is how an operator puts somebody "
        "into a team, and how they get back into a team where nobody can act any more.",
        examples=["the-voucher-is-43-characters-long-and-random"],
    )
    member_name: str = Field(
        description="Who the identity will be once it is redeemed. Here beside the secret, so "
        "the one answer that shows it also says whom it is for.",
        examples=["Anna"],
    )
    team_name: str = Field(description="The team the invitation is for.", examples=["kitchen"])
    realm_name: str = Field(description="The realm that team is in.", examples=["household"])


class InvitationEntry(BaseModel):
    display_name: str = Field(
        description="The handle for this invitation.", examples=["voucher for Anna"]
    )
    kind: str = Field(
        description="What kind of invitation it is: `member` for a place in a team, "
        "`service` for a place in the registry.",
        examples=["member"],
    )
    team_name: str | None = Field(
        default=None,
        description="The team it is for, or absent for a `service` invitation: a central "
        "service belongs to the realm and to no team.",
        examples=["kitchen"],
    )
    target_name: str = Field(
        description="Who the identity will be once it is redeemed. A different thing from "
        "the display name.",
        examples=["Anna"],
    )
    issued_at: str = Field(
        description="When it was obtained, in UTC with milliseconds.",
        examples=["2026-09-28T09:12:44.081Z"],
    )
    issued_by_kind: str = Field(
        description="Who obtained it: `operator` for this surface, `member` for somebody in "
        "a team.",
        examples=["operator"],
    )
    issued_by: str | None = Field(
        default=None,
        description="Who obtained it, when that was a person in a team; `null` when you did. "
        "Named so you can find their invitations after revoking their token: those stay "
        "redeemable and have to be revoked one by one.",
        examples=["Anna"],
    )
    redeemed_at: str | None = Field(
        default=None,
        description="When it was used up, or `null` while it is still good. It is good once.",
        examples=["2026-09-28T09:20:01.004Z"],
    )
    revoked: bool = Field(description="Whether it has been revoked.", examples=[False])


class InvitationList(BaseModel):
    invitations: list[InvitationEntry] = Field(
        description="Every invitation of this realm, the used-up and revoked ones included: "
        "nothing is deleted, a display name stays taken, and a repeated revocation needs the "
        "entry.",
        examples=[
            [
                {
                    "display_name": "voucher for Anna",
                    "kind": "member",
                    "team_name": "kitchen",
                    "target_name": "Anna",
                    "issued_at": "2026-09-28T09:12:44.081Z",
                    "issued_by_kind": "operator",
                    "issued_by": None,
                    "redeemed_at": None,
                    "revoked": False,
                }
            ]
        ],
    )


class ObserverIn(BaseModel):
    display_name: str = Field(
        description="How you will refer to this observer token. Listing and revoking go by "
        "it, never by the secret. Unique among observer tokens within the realm.",
        examples=["the reading eye"],
    )


class ObserverOut(BaseModel):
    display_name: str = Field(
        description="The handle for this token.", examples=["the reading eye"]
    )
    token: str = Field(
        description="The token itself, in the clear, shown exactly once. Issue another "
        "whenever you like, including after revoking one; several may exist at the same time.",
        examples=["the-token-is-43-characters-long-and-random"],
    )


class ObserverEntry(BaseModel):
    display_name: str = Field(
        description="The handle for this token.", examples=["the reading eye"]
    )
    issued_at: str = Field(
        description="When it was issued, in UTC with milliseconds.",
        examples=["2026-09-28T09:12:44.081Z"],
    )
    token_revoked: bool = Field(description="Whether it has been revoked.", examples=[False])


class ObserverList(BaseModel):
    observer_tokens: list[ObserverEntry] = Field(
        description="The observer tokens of this realm by their handles. Never the secrets: "
        "a token is shown once, when it comes into being.",
        examples=[
            [
                {
                    "display_name": "the reading eye",
                    "issued_at": "2026-09-28T09:12:44.081Z",
                    "token_revoked": False,
                }
            ]
        ],
    )


class Revoked(BaseModel):
    """What a revocation answers with. The subject keeps being named on purpose.

    Only the timestamp is shared. The boolean is named after **what** was revoked —
    `token_revoked` where a token was, `revoked` where an invitation was — because
    that is what the specification's tables say, and a field renamed on the way out
    is a field somebody has to look up twice.
    """

    revoked_at: str | None = Field(
        default=None,
        description="When it was **first** revoked. Unchanged by a repeat, which is how a "
        "repeat tells you it has already happened.",
        examples=["2026-09-28T09:31:12.900Z"],
    )


class MemberRevoked(Revoked):
    member_name: str = Field(
        description="The identity, still named: a revocation ends a permission, not a "
        "content. It stays in the team, visible and readable.",
        examples=["Anna"],
    )
    token_revoked: bool = Field(
        description="Whether its token is revoked now. Revoking twice is allowed.",
        examples=[True],
    )


class ServiceRevoked(Revoked):
    service_name: str = Field(
        description="The central service, still named and still in the registry.",
        examples=["weather"],
    )
    token_revoked: bool = Field(description="Whether its token is revoked now.", examples=[True])


class InvitationRevoked(Revoked):
    display_name: str = Field(
        description="The handle, still named and still taken.", examples=["voucher for Anna"]
    )
    revoked: bool = Field(
        description="Whether the invitation is revoked now. Revoking one that has already "
        "been redeemed changes nothing, and this says so rather than claiming otherwise.",
        examples=[True],
    )


class ObserverRevoked(Revoked):
    display_name: str = Field(
        description="The handle, still named and still taken.", examples=["the reading eye"]
    )
    token_revoked: bool = Field(description="Whether the token is revoked now.", examples=[True])


class RealmMasterOut(BaseModel):
    member_name: str = Field(description="The identity.", examples=["Anna"])
    is_realm_master: bool = Field(
        description="Whether it carries the right now. Taking it away leaves the token valid "
        "and the identity in its team: only the one stored right goes.",
        examples=[False],
    )


class NoteLength(BaseModel):
    length: int = Field(
        description="How many characters the note now has. Writing replaces it entirely — "
        "there is no appending, so read it before you write it.",
        examples=[184],
    )
