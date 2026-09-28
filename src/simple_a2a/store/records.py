"""What is written in a `meta.json`, and the one rule for changing it.

These are the stored shapes, and they are *internal*: the surfaces decide what a
caller sees, and the two are deliberately not the same thing. The field names
match the wire names where they mean the same thing, because a translation layer
between two identical vocabularies is a place for typos, not a boundary.

**The compatibility rule: a field added later needs a default.** Nothing is ever
deleted here, so records written today are read years from now, by code that has
grown fields in between. A field without a default turns an old record into a
crash — and since the record is on disk, the crash is permanent rather than
transient. Reading also ignores keys it does not know, for the same reason from
the other direction.

**What is *not* stored: any secret that can be presented.** A token is kept as a
hash and a voucher is not kept at all — its hash is its directory name. There is
no operation that hands out an existing secret, so there is nothing to keep one
for, and a store that cannot leak a token does not have to be trusted not to.
The one exception is the alias, which is shown in an envelope and therefore has
to be readable back out.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self


def token_hash(secret: str) -> str:
    """The name a secret is indexed under.

    A plain hash with no salt and no stretching, and that is deliberate: this is
    not a password. It is 256 bits of randomness that cannot be guessed and does
    not need to resist a dictionary, and a per-entry salt would make the index
    unusable — the point is to find an entry from the secret in one step.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class Kind(StrEnum):
    """What something is, in the words the surfaces use.

    `peer` and `service` are how a participant names a target; `alias` is the
    way back to whoever sent a service a message. `member` appears only on
    invitations, because from above a team has members and from inside it has
    peers — one thing, two vocabularies, and the vocabulary follows the surface.
    """

    PEER = "peer"
    SERVICE = "service"
    ALIAS = "alias"
    MEMBER = "member"


def _to_dict(record: Any) -> dict[str, Any]:
    return {
        f.name: getattr(record, f.name)
        for f in dataclasses.fields(record)
        if getattr(record, f.name) is not None
    }


class Record:
    """Serialisation, shared by every stored shape.

    Unknown keys are dropped on read rather than refused: a record written by a
    later version has to stay readable by an earlier one for at least as long as
    it takes somebody to notice they downgraded.
    """

    def to_json(self) -> str:
        return json.dumps(_to_dict(self), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Self:
        raw = json.loads(text)
        known = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
        return cls(**{key: value for key, value in raw.items() if key in known})


@dataclass(frozen=True)
class Realm(Record):
    id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class Team(Record):
    id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class Member(Record):
    """An identity: an agent in a team, with exactly one token and one mailbox.

    `revoked_at` is a note, not the state. The state is which directory the
    record sits in, and there is no second copy of it here to fall out of step
    — a flag and a directory saying different things is the bug this avoids.
    """

    id: str
    name: str
    created_at: str
    token_hash: str
    is_realm_master: bool = False
    revoked_at: str | None = None


@dataclass(frozen=True)
class Service(Record):
    """A central service: in one realm's registry, in no team.

    It carries no mission — it registers itself and enters what it can do — so
    there is no field for one here either.
    """

    id: str
    name: str
    created_at: str
    token_hash: str
    revoked_at: str | None = None


@dataclass(frozen=True)
class Observer(Record):
    """Not an identity: no texts, no mailbox, not addressable.

    Addressed by a display name, because a token is not something to be named
    by and nothing here ever hands one back.
    """

    id: str
    display_name: str
    created_at: str
    token_hash: str
    revoked_at: str | None = None


@dataclass(frozen=True)
class Invitation(Record):
    """A voucher, not a permission: handed on, exchanged once, then used up.

    The voucher itself is nowhere in this record. Its hash is the name of the
    directory the record sits in, which is how a presented voucher is found and
    why a stored one cannot be handed out. Listing and revoking go by the
    display name.
    """

    kind: str
    #: How the operator refers to the voucher: unique per kind per realm, and the
    #: only handle there is — listing and revoking go by it, never by the secret.
    display_name: str
    #: Who the identity will be once it is redeemed. A different thing from the
    #: display name, and fixed here because whoever invites has to give them a
    #: mission — you cannot write an assignment for a person you cannot name.
    invited_name: str
    created_at: str
    issued_by_kind: str
    issued_by_name: str
    team_id: str | None = None
    #: Whether redeeming this one makes its holder a realm master. True for every
    #: invitation the operator obtained — that is their way of putting somebody
    #: into a team, and it is the way back into a team where nobody can act any
    #: more, so it comes without a parameter and without a choice.
    grants_realm_master: bool = False
    consumed_at: str | None = None
    revoked_at: str | None = None


@dataclass(frozen=True)
class StoredFile(Record):
    """A file belongs to one realm — whoever deposited it — and to any number of
    messages, possibly under different names. The name lives on the envelope, not
    here: kept in both places it would be two names for one file.
    """

    id: str
    created_at: str
    size: int
    #: What the depositor said it is, handed back unchanged on every fetch. Absent
    #: only in holdings written before it was kept.
    media_type: str | None = None


@dataclass(frozen=True)
class Participant(Record):
    """A sender or a recipient, as an envelope names them: a kind and a name."""

    kind: str
    name: str


@dataclass(frozen=True)
class Attachment(Record):
    """One entry of the attachment list: a file, or a reference to a message.

    Exactly one of the two identifiers is set, and which one it is says what the
    entry is. A single field whose meaning depended on its content would have to
    be guessed at by every reader.
    """

    name: str
    file_id: str | None = None
    message_id: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class Message(Record):
    """The message itself, stored once.

    The recipients here are the ones resolved at send time — an empty list means
    "everybody else in the team", and it is resolved *then*, so that a broadcast
    stays traceable after the next person joins.

    The sender here is the true one. What a particular recipient sees is in
    their mailbox entry, because an envelope carries the names that hold in its
    recipient's world and that is settled when it is delivered.
    """

    id: str
    created_at: str
    team_id: str
    sender: dict[str, str]
    recipients: list[dict[str, str]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    body_size: int = 0
    total_size: int = 0
    in_reply_to: str | None = None


@dataclass(frozen=True)
class MailboxEntry(Record):
    """One delivery: which message, and the envelope as this recipient sees it.

    `sender` **and** `recipients` are the ones that hold *in this recipient's
    world*. For a central service that means an alias where a name would
    otherwise be — in what it received, and equally in what it sent: the promise
    would be broken at the first follow-up step if its own outbox named the person
    it had answered.

    `delivered_at` is written into the entry's *name*, which is what the ordering
    of a mailbox is made of, and it is read back from there. It is a field here so
    that the name can be built from one place — not so that it can be stored
    twice: two copies of one fact eventually disagree, and then a listing hands
    back an entry dated later than the one above it.

    The two halves of that name are joined by a character that occurs in neither
    of them, so reading it back is a split and not a guess.
    """

    message_id: str
    delivered_at: str
    sender: dict[str, str]
    recipients: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Alias(Record):
    """The way back from one delivery to the member who sent it.

    Bound to one message and one service, which is what makes it useless for
    starting anything: nobody who has not been written to has one.
    """

    value: str
    created_at: str
    message_id: str
    service_id: str
    team_id: str
    sender: dict[str, str]


@dataclass(frozen=True)
class TokenPointer(Record):
    """What the token index holds: which thing a presented token belongs to.

    It outlives a revocation on purpose. Without it, a revoked token and a token
    nobody ever issued would be indistinguishable — and they are two different
    things to be told, one of which has a way forward.
    """

    kind: str
    realm_id: str
    subject_id: str
    team_id: str | None = None
