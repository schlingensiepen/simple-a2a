"""What the observation surface gives back. It takes nothing but a window and filters.

The traffic entry is the point of the surface, and it differs from a mailbox entry in
one way that matters: the sender is **always** the real one. Where a central service
was shown an alias, the alias is resolved here — that is what watching is for.

The team is in the address, so no entry carries it as a field: no field carries what
is already in the path, which is the same rule as "no path carries what is already in
the token", one level up.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Participant(BaseModel):
    kind: str = Field(
        description="What sort of name this is: `peer` for a member of the team, `service` "
        "for a central service. Never `alias` here — an alias is resolved to whoever is "
        "behind it.",
        examples=["peer"],
    )
    name: str = Field(description="The name itself.", examples=["Anna"])


class Attachment(BaseModel):
    name: str = Field(
        description="What the entry was called by whoever attached it.",
        examples=["shopping-list.md"],
    )
    file_id: str | None = Field(
        default=None,
        description="Set when the entry is a file. Fetch it at "
        "GET /files/{file_id}/{file_name}, choosing the name you want to save it under.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    message_id: str | None = Field(
        default=None,
        description="Set when the entry refers to another message rather than carrying a "
        "file. A reference transfers nothing.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    size: int = Field(
        description="For a file its bytes; for a reference the total size of the message it "
        "points at.",
        examples=[4096],
    )


class TrafficEntry(BaseModel):
    message_id: str = Field(
        description="The identifier of the message. Fetch its envelope, subject or body with it.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    sender_kind: str = Field(
        description="What sort of name the sender is. Always the real one.", examples=["peer"]
    )
    sender_name: str = Field(
        description="Who sent it. Always the real sender, even where the recipient was shown "
        "an alias instead.",
        examples=["Anna"],
    )
    recipients: list[Participant] = Field(
        description="Everybody it went to, as resolved when it was sent. A message to the "
        "whole team appears **once** with all of them, not as one entry per recipient.",
        examples=[[{"kind": "peer", "name": "Berta"}]],
    )
    sent_at: str = Field(
        description="When it was sent, in UTC with milliseconds. The order here is this, "
        "newest first.",
        examples=["2026-09-28T09:12:44.081Z"],
    )
    subject: str = Field(description="The subject line.", examples=["Shift handover"])
    body_size: int = Field(description="The bytes of the body.", examples=[512])
    total_size: int = Field(
        description="The body plus the file attachments, in bytes. References count zero.",
        examples=[4608],
    )
    attachment_count: int = Field(
        description="How many entries the attachment list has.", examples=[1]
    )
    in_reply_to: str | None = Field(
        default=None,
        description="The message this one answers, when it answers one. That is what makes a "
        "thread readable from here.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class Traffic(BaseModel):
    entries: list[TrafficEntry] = Field(
        description="A window over what was said in this team, newest first, envelopes only.",
        examples=[[]],
    )


class Envelope(BaseModel):
    message_id: str = Field(
        description="The identifier of this message.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    sender_kind: str = Field(
        description="What sort of name the sender is. Always the real one.", examples=["peer"]
    )
    sender_name: str = Field(
        description="Who sent it, always really. An alias shown to a recipient is resolved here.",
        examples=["Anna"],
    )
    recipients: list[Participant] = Field(
        description="Everybody it went to, with their kind and name.",
        examples=[[{"kind": "peer", "name": "Berta"}]],
    )
    sent_at: str = Field(
        description="When it was sent, in UTC with milliseconds.",
        examples=["2026-09-28T09:12:44.081Z"],
    )
    subject: str = Field(description="The subject line.", examples=["Shift handover"])
    body_size: int = Field(description="The bytes of the body.", examples=[512])
    total_size: int = Field(
        description="The body plus the file attachments, in bytes.", examples=[4608]
    )
    attachments: list[Attachment] = Field(
        default_factory=list,
        description="The attachment list, each entry with its own size.",
        examples=[[]],
    )
    in_reply_to: str | None = Field(
        default=None,
        description="The message this one answers, when it answers one.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class TeamEntry(BaseModel):
    team_name: str = Field(
        description="The name of the team. Its traffic is at GET /teams/{team}/traffic.",
        examples=["kitchen"],
    )
    member_count: int = Field(
        description="How many members it has, revoked ones included.", examples=[3]
    )


class Teams(BaseModel):
    """The teams of the realm as data: the same list the prose of GET /teams is."""

    entries: list[TeamEntry] = Field(
        description="A window over the teams of your realm, alphabetically. `offset` and "
        "`limit` move it, as with every listing.",
        examples=[[{"team_name": "kitchen", "member_count": 3}]],
    )


class MemberEntry(BaseModel):
    kind: str = Field(
        description="Always `peer`: a member of the team, as the traffic names them.",
        examples=["peer"],
    )
    name: str = Field(description="The member's name.", examples=["Anna"])
    is_realm_master: bool = Field(
        description="Whether their token carries the realm master right.", examples=[True]
    )
    token_revoked: bool = Field(
        description="Whether their token has been revoked. A revoked member stays listed, "
        "because what they said is still in the traffic.",
        examples=[False],
    )


class Members(BaseModel):
    """The members of one team as data: the same list the prose of its peers is."""

    entries: list[MemberEntry] = Field(
        description="A window over the members of the team, alphabetically. `offset` and "
        "`limit` move it, as with every listing.",
        examples=[
            [{"kind": "peer", "name": "Anna", "is_realm_master": True, "token_revoked": False}]
        ],
    )
