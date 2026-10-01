"""What the participant surface takes in and gives back.

A description and an example on every field, which is what the gate insists on.
Where a field can be one of two things, there are two fields and exactly one of them
is filled: a field whose meaning depends on another field is the stumbling block this
service removed elsewhere, and it is not coming back here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    """The base of everything a caller sends, and the configuration is the point.

    An unknown field is **refused**, not ignored. Ignoring one is how `size` on an
    attachment slipped through: the specification says sending it is invalid input,
    and a model that simply dropped it turned a refusal into a success. A caller who
    sends a field we do not know has misunderstood something, and saying so costs
    them one attempt instead of a day.
    """

    model_config = ConfigDict(extra="forbid")


class Participant(BaseModel):
    """Somebody an envelope names: a kind and a name, always both.

    The kind is what lets a recipient answer. Without it they could not tell whether
    to use the team address, the registry address or an alias — and that is the most
    common next step there is.
    """

    kind: str = Field(
        description="What sort of name this is: `peer` for somebody in your team, "
        "`service` for a central service, `alias` for the way back to whoever wrote to "
        "a central service.",
        examples=["peer"],
    )
    name: str = Field(
        description="The name itself. For an alias it is the one this service assigned.",
        examples=["Anna"],
    )


class AttachmentIn(Input):
    """One entry of the attachment list on the way in.

    Exactly one identifier field is filled, and which one it is says what the entry
    is. `size` is not here at all: it is output only, because for a file the service
    knows the bytes and for a reference it knows the total of the referenced message,
    and a caller can know neither reliably.
    """

    name: str = Field(
        description="What this entry is called. For a file it is the file name it is "
        "fetched under, so it must not be a path: a directory part is dropped. For a "
        "reference it is the label the body can refer to. Up to 256 characters, unique "
        "within the list.",
        examples=["shopping-list.md"],
    )
    file_id: str | None = Field(
        default=None,
        description="The identifier of a file deposited earlier with POST /files. Fill "
        "this **or** message_id, never both.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    message_id: str | None = Field(
        default=None,
        description="The identifier of a message this one refers to. Fill this **or** "
        "file_id, never both. A reference transfers nothing and counts zero towards the "
        "total size.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class AttachmentOut(AttachmentIn):
    size: int = Field(
        description="For a file its bytes; for a reference the total size of the "
        "referenced message, so you can judge before following it.",
        examples=[4096],
    )


class Send(Input):
    """What both sending operations take, apart from who it goes to."""

    subject: str = Field(
        description="One line, plain text, up to 256 characters. It takes no reference to "
        "a file: it is short, and there would be nowhere to put one.",
        examples=["Shift handover"],
    )
    body: str | None = Field(
        default=None,
        description="The message itself, as text. Fill this **or** body_file_id, never "
        "both. Up to 1 MiB. Markdown is a good choice and nothing here reads it.",
        examples=["The list is on the fridge. I have added yeast."],
    )
    body_file_id: str | None = Field(
        default=None,
        description="Instead of body: the identifier of a file deposited earlier, whose "
        "UTF-8 content becomes the body. Useful when the text is awkward to escape. The "
        "limit is the body's, not the file's.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    attachments: list[AttachmentIn] | None = Field(
        default=None,
        description="Files and references to other messages, at most 64 entries together.",
        examples=[[{"name": "shopping-list.md", "file_id": "the-identifier-of-the-file"}]],
    )
    in_reply_to: str | None = Field(
        default=None,
        description="The identifier of the message this answers. Set it so the other side "
        "can tie your answer to their question without reading it.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class SendToPeers(Send):
    recipients: list[str] = Field(
        default_factory=list,
        description="The names of members of your team. **An empty list means everybody "
        "else in the team** — resolved when you send, so the envelope names who was "
        "actually there. Naming yourself is allowed and has no effect: your own messages "
        "are in your outbox, not your inbox.",
        examples=[["Berta"]],
    )


class SendToService(Send):
    recipient: str = Field(
        description="The name of one central service, unique across this installation. One "
        "name, not a list: central services are addressed one at a time. There is no "
        "recipient *list* here, because there is nothing a list would mean.",
        examples=["weather"],
    )


class SendToAlias(Input):
    subject: str = Field(
        description="One line, plain text, up to 256 characters.", examples=["Twelve degrees"]
    )
    body: str | None = Field(
        default=None,
        description="The answer itself, as text. Fill this **or** body_file_id.",
        examples=["Twelve degrees and falling."],
    )
    body_file_id: str | None = Field(
        default=None,
        description="Instead of body: the identifier of a file whose UTF-8 content becomes "
        "the body.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    attachments: list[AttachmentIn] | None = Field(
        default=None,
        description="Files and references, at most 64 entries together.",
        examples=[[]],
    )


class Sent(BaseModel):
    message_id: str = Field(
        description="The identifier of the message that now exists. Whoever has it may "
        "fetch the message: an identifier is the permission, so pass it on only "
        "deliberately.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    sent_at: str = Field(
        description="When it was sent, in UTC with milliseconds.",
        examples=["2026-09-28T09:12:44.081Z"],
    )
    recipients: list[Participant] = Field(
        description="Who it actually went to, resolved as you sent it. An empty recipient "
        "list becomes the members who were there at that moment, so a broadcast stays "
        "traceable afterwards.",
        examples=[[{"kind": "peer", "name": "Berta"}]],
    )
    warnings: list[dict[str, str]] = Field(
        default_factory=list,
        description="Anything that succeeded but probably did not do what you wanted. "
        "There is one: `no recipient`, when an empty list resolved to nobody because you "
        "are alone in the team.",
        examples=[[]],
    )


class MailboxEntry(BaseModel):
    message_id: str = Field(
        description="The identifier of the message. Stable, so you can tell a repeat from "
        "something new when a window shifts.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    sender_kind: str | None = Field(
        default=None,
        description="What sort of name the sender is, so you know how to answer: `peer`, "
        "`service` or `alias`. Absent in the outbox, where the senders are all you.",
        examples=["peer"],
    )
    sender_name: str | None = Field(
        default=None,
        description="The sender, as they are known in your world. Absent in the outbox.",
        examples=["Anna"],
    )
    recipients: list[Participant] | None = Field(
        default=None,
        description="Who it went to, in the outbox. Absent in the inbox, where the "
        "recipient is you.",
        examples=[[{"kind": "peer", "name": "Berta"}]],
    )
    sent_at: str = Field(
        description="When it was sent, in UTC with milliseconds. The order of a mailbox is "
        "this, newest first; equal timestamps have no order.",
        examples=["2026-09-28T09:12:44.081Z"],
    )
    subject: str = Field(description="The subject line.", examples=["Shift handover"])
    body_size: int = Field(
        description="The bytes of the body, so you can see the weight before fetching it.",
        examples=[512],
    )
    total_size: int = Field(
        description="The body plus the file attachments, in bytes. References count zero: "
        "they transfer nothing.",
        examples=[4608],
    )
    attachment_count: int = Field(
        description="How many entries the attachment list has, files and references together.",
        examples=[1],
    )
    in_reply_to: str | None = Field(
        default=None,
        description="The message this one answers, when it answers one. Here in the "
        "listing, so you can tie an answer to your own question without opening it.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class Mailbox(BaseModel):
    entries: list[MailboxEntry] = Field(
        description="A window over the mailbox, newest first, envelopes only — never the "
        "body. A window over a growing list shifts when something arrives between two "
        "fetches; the identifiers are stable, so stop as soon as you see one you know.",
        examples=[[]],
    )


class Envelope(BaseModel):
    message_id: str = Field(
        description="The identifier of this message.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    sender_kind: str = Field(
        description="What sort of name the sender is: `peer`, `service` or `alias`.",
        examples=["peer"],
    )
    sender_name: str = Field(
        description="The sender, as they are known in your world.", examples=["Anna"]
    )
    recipients: list[Participant] = Field(
        description="Who it went to, as it was settled when it was delivered.",
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
    attachments: list[AttachmentOut] = Field(
        default_factory=list,
        description="The attachment list, each entry with its own size.",
        examples=[[]],
    )
    in_reply_to: str | None = Field(
        default=None,
        description="The message this one answers, when it answers one.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class FileDeposited(BaseModel):
    file_id: str = Field(
        description="The identifier of the file. Attach it to a message together with a "
        "name; the name lives on the envelope, not on the file, so the same file can hang "
        "in several messages under different names.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    size: int = Field(description="Its size in bytes.", examples=[4096])
    media_type: str = Field(
        description="What the file was remembered as: the Content-Type you sent, or "
        "text/plain if you sent none. Every fetch hands it back. A tool that "
        "sends a form type by default (curl does) makes that the file's type — send the "
        "right one.",
        examples=["application/pdf"],
    )


class InviteePeer(Input):
    member_name: str = Field(
        description="Who the identity will be. Fixed now, because you have to name somebody "
        "to give them a mission, and checked again when they redeem it.",
        examples=["Clara"],
    )
    member_mission: str | None = Field(
        default=None,
        description="What you are inviting them for, up to 8192 characters. Fill this **or** "
        "member_mission_file_id.",
        examples=["Keep the shopping list."],
    )
    member_mission_file_id: str | None = Field(
        default=None,
        description="Instead of member_mission: the identifier of a file whose UTF-8 content "
        "is the mission.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    display_name: str = Field(
        description="How this invitation is referred to afterwards. Not the secret.",
        examples=["voucher for Clara"],
    )


class InviteeService(Input):
    service_name: str = Field(
        description="What the central service will be called, unique across the installation.",
        examples=["weather"],
    )
    display_name: str = Field(
        description="How this invitation is referred to afterwards.",
        examples=["voucher for weather"],
    )


class InvitationGiven(BaseModel):
    display_name: str = Field(
        description="The handle for this invitation.", examples=["voucher for Clara"]
    )
    invitation: str = Field(
        description="The voucher itself, shown exactly once. Hand it over together with the "
        "base address, on a channel that is not a chat window: the two are one pair and "
        "neither half is any use alone.",
        examples=["the-voucher-is-43-characters-of-base64url"],
    )
    team_name: str | None = Field(
        default=None,
        description="The team the invitation is for. Absent for a central service, which "
        "belongs to the installation rather than to a team.",
        examples=["kitchen"],
    )


class Redeem(Input):
    invitation: str = Field(
        description="The voucher you were given. This is the one operation that needs no "
        "standing token: the voucher legitimates itself, once.",
        examples=["the-voucher-is-43-characters-of-base64url"],
    )
    member_self_image: str | None = Field(
        default=None,
        description="Only when you are becoming a central service, and then it is your only "
        "text: what you can do. Inline only — you have no token yet, so you cannot deposit a "
        "file. PUT /me/self is open to you immediately afterwards.",
        examples=["I answer questions about the weather."],
    )


class Redeemed(BaseModel):
    token: str = Field(
        description="Your token, shown exactly once. There is no operation that gives it out "
        "again and no way to replace a lost one: whoever loses it is invited again under a "
        "**new** name.",
        examples=["the-token-is-43-characters-of-base64url"],
    )
    kind: str = Field(
        description="What you have become: `peer` if you are in a team, `service` if you are "
        "in the registry. This is how others will name you.",
        examples=["peer"],
    )
    name: str = Field(description="Your name.", examples=["Clara"])
    team_name: str | None = Field(
        default=None,
        description="Your team. Absent for a central service, which has none.",
        examples=["kitchen"],
    )
    is_realm_master: bool | None = Field(
        default=None,
        description="Whether your token carries the one stored right. True exactly when the "
        "operator obtained the invitation. Absent for a central service, which cannot carry "
        "it.",
        examples=[False],
    )


class Me(BaseModel):
    """Who the caller is, as data — the same facts the prose of GET /me states.

    For a program that keeps several identities apart and has to show which is
    which: reading them out of a sentence would tie it to the wording of one.
    """

    kind: str = Field(
        description="`peer` if you are in a team, `service` if you are in the registry.",
        examples=["peer"],
    )
    name: str = Field(description="Your name.", examples=["Clara"])
    team_name: str | None = Field(
        default=None,
        description="Your team. Absent for a central service, which has none.",
        examples=["kitchen"],
    )
    is_realm_master: bool | None = Field(
        default=None,
        description="Whether your token carries the realm master right. Absent for a central "
        "service, which cannot carry it.",
        examples=[False],
    )


class FoundTeam(Input):
    team_name: str = Field(
        description="The name of the team to create. Unique across the installation's realm.",
        examples=["bathroom"],
    )
    team_purpose: str | None = Field(
        default=None,
        description="What it is for, up to 8192 characters. Fill this **or** team_purpose_file_id.",
        examples=["We keep the bathroom stocked."],
    )
    team_purpose_file_id: str | None = Field(
        default=None,
        description="Instead of team_purpose: the identifier of a file whose UTF-8 content is "
        "the purpose.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )
    member_mission: str | None = Field(
        default=None,
        description="Your own mission in the new team — you are its first member, so you give "
        "it to yourself. Fill this **or** member_mission_file_id.",
        examples=["I started this and I keep it tidy."],
    )
    member_mission_file_id: str | None = Field(
        default=None,
        description="Instead of member_mission: the identifier of a file.",
        examples=["the-identifier-is-43-characters-of-base64url"],
    )


class TeamFounded(BaseModel):
    team_name: str = Field(description="The team that now exists.", examples=["bathroom"])
    token: str = Field(
        description="Your token **for the new team**, shown once. An identity is a name in a "
        "team, so a second team means a second identity and a second token.",
        examples=["the-token-is-43-characters-of-base64url"],
    )
    is_realm_master: bool = Field(
        description="Whether you carry the right there. A realm master stays one: the right "
        "travels with the person, not with the team.",
        examples=[True],
    )


class Appointed(BaseModel):
    member_name: str = Field(description="Who was appointed.", examples=["Clara"])
    is_realm_master: bool = Field(
        description="Whether they carry the right now. You cannot take it back: appointing "
        "and deposing are deliberately not the same hand, or two realm masters could unseat "
        "each other and somebody would have to arbitrate.",
        examples=[True],
    )


class TextLength(BaseModel):
    length: int = Field(
        description="How many characters the text now has, counted in characters like the "
        "limit. Writing replaces what was there.",
        examples=[184],
    )


def envelope_body(envelope: Any) -> dict[str, Any]:
    """An envelope from the operations, as this surface names its fields.

    The sender is two fields here and one object there, and that is the specification's
    choice: `sender_kind` and `sender_name` read as an answer about one sender, where a
    nested object would read as a list of one.
    """
    return {
        "message_id": envelope.message_id,
        "sender_kind": envelope.sender.kind,
        "sender_name": envelope.sender.name,
        "recipients": [{"kind": p.kind, "name": p.name} for p in envelope.recipients],
        "sent_at": envelope.sent_at,
        "subject": envelope.subject,
        "body_size": envelope.body_size,
        "total_size": envelope.total_size,
        "attachments": envelope.attachments,
        "in_reply_to": envelope.in_reply_to,
    }
