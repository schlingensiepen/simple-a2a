"""Sending, delivering, and what a reader is shown.

Three things here are worth reading before the code, because each one is a
decision that shows up in the shape rather than in a rule:

**An empty recipient list is shorthand for the sender, resolved at send time.**
What goes into the envelope is the list of the other members of the team *at that
moment*. So a broadcast stays traceable after the next person joins — which is
what the observation surface needs, and "everybody else at time t" is otherwise
lost.

**An alias is minted at every delivery to a central service** and stands in the
sender's place. The service replies to the alias and never learns a name. That is
why "answer, do not start" is not a rule: a service that has received nothing has
no alias, so it has nobody to write to.

**Whoever fetches a message gets the envelope of their own delivery**, if they
have one, and otherwise the message's own. Those are two different readers, not
two answers: a recipient reads what was settled when it was delivered, and
whoever uses a passed-on identifier sees the original sender. A service always has
a delivery of its own — it only learns an identifier from its own mailbox — so it
always sees the alias.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from simple_a2a.core import limits
from simple_a2a.core.clock import now_iso
from simple_a2a.core.ids import is_id, new_id
from simple_a2a.core.names import check_name, comparison_key
from simple_a2a.domain import refusals
from simple_a2a.domain.callers import Caller, Observer, Peer, Service
from simple_a2a.domain.context import Context
from simple_a2a.store.records import Alias, MailboxEntry, Message, Participant

INBOX = "inbox"
OUTBOX = "outbox"

#: The shape of a timestamp a caller may send. Checked rather than parsed: what the
#: comparison needs is the format, and a clock would add a second notion of time.
EXAMPLE_SHAPE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z")


@dataclass(frozen=True)
class Sent:
    """What sending answers with. The recipients are the resolved ones."""

    message_id: str
    sent_at: str
    recipients: list[Participant]
    warnings: list[str]


# ----------------------------------------------------------------- the mailboxes


def mailbox_of(context: Context, caller: Peer | Service, view: str) -> Path:
    if isinstance(caller, Peer):
        return (
            context.holdings.layout.member_mailbox(
                caller.realm_id, caller.team_id, caller.member_id
            )
            / view
        )
    return context.holdings.layout.service_mailbox(caller.realm_id, caller.service_id) / view


def list_mailbox(
    context: Context, caller: Peer | Service, view: str, *, offset: int, limit: int
) -> list[MailboxEntry]:
    """A window over a growing list, newest first, envelopes only.

    A window over a growing list shifts when something arrives between two
    fetches. Bearable because the identifiers are stable: an agent recognises a
    repeat and stops as soon as it sees one it knows — and the self-description
    says so.
    """
    entries = context.holdings.mailbox_entries(mailbox_of(context, caller, view))
    return entries[offset : offset + limit]


# ------------------------------------------------------------------- resolution


def resolve_peers(
    context: Context, sender: Peer, names: object
) -> tuple[list[Participant], list[str]]:
    """Turn what a sender asked for into the list that goes in the envelope.

    An empty list means everybody else in the team. Naming oneself explicitly is
    allowed and has no effect — the sender is left out either way, because one's
    own messages do not land in one's own inbox. If nobody is left, the message is
    still accepted and the answer carries a warning: the sender did everything
    they could.

    Revoked identities count. Delivery to them succeeds, the mailbox keeps
    collecting, and whoever wants to know about the revocation sees the mark in
    the team listing. No warning for that: nothing is broken.
    """
    if names is None:
        names = []
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        raise refusals.InvalidInput("recipients", reason="a list of names")

    members = list(context.holdings.members(sender.realm_id, sender.team_id))
    by_key = {comparison_key(found.record.name): found.record for found in members}

    if not names:
        chosen = [record for key, record in by_key.items() if key != comparison_key(sender.name)]
    else:
        chosen = []
        seen: set[str] = set()
        for asked in names:
            key = comparison_key(asked)
            if key not in by_key:
                raise refusals.UnknownName(asked, namespace="member")
            if key == comparison_key(sender.name) or key in seen:
                continue
            seen.add(key)
            chosen.append(by_key[key])

    resolved = sorted(
        (Participant(kind="peer", name=record.name) for record in chosen), key=lambda p: p.name
    )
    warnings = [refusals.NO_RECIPIENT] if not resolved else []
    return resolved, warnings


def resolve_service(context: Context, sender: Peer, name: object) -> Participant:
    """One name, unique across the realm. Same shape, one word different."""
    if check_name(name) is not None:
        raise refusals.InvalidInput("recipient", reason="a service name")
    assert isinstance(name, str)
    located = context.holdings.service_named(sender.realm_id, name)
    if located is None:
        raise refusals.UnknownName(name, namespace="service")
    return Participant(kind="service", name=located.record.name)


# ------------------------------------------------------------------- attachments


def check_attachments(context: Context, realm_id: str, raw: object) -> tuple[list[dict], int]:
    """Check the list and work out what the file attachments weigh.

    A reference transfers nothing, so it counts zero towards the total. Without
    that the size calculation would be recursive, because a referenced message can
    carry references of its own.

    `size` is output and never input: for a file the service knows the bytes, for a
    reference the total size of the referenced message, and a caller cannot know
    either reliably. A `size` that was sent in is invalid input.
    """
    if raw is None:
        return [], 0
    if not isinstance(raw, list):
        raise refusals.InvalidInput("attachments", reason="a list")
    if len(raw) > limits.ATTACHMENTS_MAX:
        raise refusals.TooLarge(
            "attachments", limit=limits.ATTACHMENTS_MAX, actual=len(raw), unit="entries"
        )

    entries: list[dict] = []
    weight = 0
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise refusals.InvalidInput("attachments", reason="each entry is an object")
        if "size" in entry:
            raise refusals.InvalidInput("attachments.size", reason="output only, never sent in")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise refusals.InvalidInput("attachments.name", reason="missing")
        if len(name) > limits.ATTACHMENT_NAME_MAX_CHARS:
            raise refusals.TooLarge(
                "attachments.name",
                limit=limits.ATTACHMENT_NAME_MAX_CHARS,
                actual=len(name),
                unit="characters",
            )
        # A name is not a path, and the two halves of that are treated differently
        # on purpose. Control characters and line breaks are **refused** with a
        # teaching text — they are a mistake the caller has to see. Directory parts
        # are **discarded** rather than resolved: `reports/2026/x.txt` becomes
        # `x.txt`. A file attachment's name ends up in a response header and in a
        # fetch path, so what remains has to be a plain name; what remains of
        # nothing, or of `.` and `..`, is not one.
        if any(ch in name for ch in "\r\n\t\0"):
            raise refusals.InvalidInput(
                "attachments.name", reason="no control characters and no line breaks"
            )
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if not name or name in (".", ".."):
            raise refusals.InvalidInput(
                "attachments.name", reason="nothing is left of it once the path is dropped"
            )
        key = comparison_key(name)
        if key in seen:
            raise refusals.InvalidInput("attachments.name", reason=f"{name!r} appears twice")
        seen.add(key)

        file_id, message_id = entry.get("file_id"), entry.get("message_id")
        if (file_id is None) == (message_id is None):
            raise refusals.InvalidInput(
                "attachments", reason="exactly one of file_id and message_id"
            )
        if file_id is not None:
            if not is_id(file_id):
                raise refusals.InvalidInput("attachments.file_id", reason="not an identifier")
            stored = context.holdings.file(realm_id, file_id)
            if stored is None:
                raise refusals.UnknownIdentifier("file")
            entries.append({"name": name, "file_id": file_id, "size": stored.size})
            weight += stored.size
        else:
            if not is_id(message_id):
                raise refusals.InvalidInput("attachments.message_id", reason="not an identifier")
            referenced = context.holdings.message(realm_id, message_id)
            if referenced is None:
                raise refusals.UnknownIdentifier("message")
            entries.append({"name": name, "message_id": message_id, "size": referenced.total_size})
    return entries, weight


# ------------------------------------------------------------------------ bodies


def resolve_body(context: Context, realm_id: str, body: object, body_file_id: object) -> str:
    """Text or reference, and exactly one of the two fields is filled.

    The kind hangs on the field name rather than on a field whose meaning depends
    on its content. The limit belongs to the *parameter*, not to the file: a
    referenced file is checked against the body limit, because that is what it has
    become.
    """
    if (body is None) == (body_file_id is None):
        raise refusals.InvalidInput("body", reason="exactly one of body and body_file_id")
    if body is not None:
        if not isinstance(body, str):
            raise refusals.InvalidInput("body", reason="text")
        text = body
    else:
        if not is_id(body_file_id):
            raise refusals.InvalidInput("body_file_id", reason="not an identifier")
        raw = context.holdings.file_content(realm_id, str(body_file_id))
        if raw is None:
            raise refusals.UnknownIdentifier("file")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise refusals.InvalidInput("body_file_id", reason="not valid UTF-8") from None
    size = len(text.encode("utf-8"))
    if size > context.config.body_max_bytes:
        raise refusals.TooLarge(
            "body", limit=context.config.body_max_bytes, actual=size, unit="bytes"
        )
    return text


def check_subject(subject: object) -> str:
    """The subject takes no reference: it is short, and there is nowhere to put one."""
    if not isinstance(subject, str):
        raise refusals.InvalidInput("subject", reason="text")
    if len(subject) > limits.SUBJECT_MAX_CHARS:
        raise refusals.TooLarge(
            "subject", limit=limits.SUBJECT_MAX_CHARS, actual=len(subject), unit="characters"
        )
    return subject


def check_reply_to(context: Context, realm_id: str, in_reply_to: object) -> str | None:
    if in_reply_to is None:
        return None
    if not is_id(in_reply_to):
        raise refusals.InvalidInput("in_reply_to", reason="not an identifier")
    if context.holdings.message(realm_id, str(in_reply_to)) is None:
        raise refusals.UnknownIdentifier("message")
    return str(in_reply_to)


# ------------------------------------------------------------------ the sending


def _store_and_deliver(
    context: Context,
    *,
    realm_id: str,
    team_id: str,
    sender: Participant,
    recipients: list[Participant],
    shown_recipients: list[Participant] | None = None,
    subject: str,
    body: str,
    attachments: list[dict],
    attachment_weight: int,
    in_reply_to: str | None,
    warnings: list[str],
) -> Sent:
    """Write the message once, then one mailbox entry per delivery.

    The order matters: the message exists before any delivery points at it, so a
    crash in between leaves an entry nobody can reach rather than a pointer to
    nothing.
    """
    # What the sender is shown, and what goes into their outbox entry. The same as
    # the true recipients everywhere except one place: a service answering an alias
    # is shown the alias, because its own outbox must not name the person it
    # answered.
    shown = recipients if shown_recipients is None else shown_recipients
    body_size = len(body.encode("utf-8"))
    message = Message(
        id=new_id(),
        created_at=now_iso(),
        team_id=team_id,
        sender={"kind": sender.kind, "name": sender.name},
        recipients=[{"kind": p.kind, "name": p.name} for p in recipients],
        attachments=attachments,
        body_size=body_size,
        total_size=body_size + attachment_weight,
        in_reply_to=in_reply_to,
    )
    context.holdings.put_message(realm_id, message, subject=subject, body=body)

    # The sender's own copy comes first, so that a crash in the middle of the
    # deliveries still leaves the sender able to see what they attempted. Their own
    # message is not in their inbox — that is what the outbox is for — and it
    # exists because an agent loses its context between two instructions and could
    # otherwise not read back what it said itself.
    #
    # The residual is named rather than prevented: there is no journal here, so a
    # crash between two deliveries leaves a message that some recipients got. The
    # sender sees no answer and sends again, which is what fire-and-forget means,
    # and duplicates are deliberately not detected.
    _deliver(
        context,
        _mailbox_for(context, realm_id, team_id, sender, OUTBOX),
        message,
        sender,
        shown,
    )
    for recipient in recipients:
        _deliver_to(context, realm_id, team_id, message, recipient)
    return Sent(
        message_id=message.id,
        sent_at=message.created_at,
        recipients=shown,
        warnings=warnings,
    )


def _mailbox_for(
    context: Context, realm_id: str, team_id: str, who: Participant, view: str
) -> Path | None:
    if who.kind == "peer":
        located = context.holdings.member_named(realm_id, team_id, who.name)
        if located is None:
            return None
        return context.holdings.layout.member_mailbox(realm_id, team_id, located.record.id) / view
    if who.kind == "service":
        found = context.holdings.service_named(realm_id, who.name)
        if found is None:
            return None
        return context.holdings.layout.service_mailbox(realm_id, found.record.id) / view
    return None


def _deliver(
    context: Context,
    mailbox: Path | None,
    message: Message,
    sender: Participant,
    recipients: list[Participant],
) -> None:
    """Put one entry into one mailbox, carrying the envelope as its owner sees it.

    Both halves are the owner's view, not the true one: a service sees an alias
    where a name would be, and it sees that alias in its own outbox too.
    """
    if mailbox is None:
        return
    context.holdings.deliver(
        mailbox,
        MailboxEntry(
            message_id=message.id,
            delivered_at=now_iso(),
            sender={"kind": sender.kind, "name": sender.name},
            recipients=[{"kind": p.kind, "name": p.name} for p in recipients],
        ),
    )


def _deliver_to(
    context: Context, realm_id: str, team_id: str, message: Message, recipient: Participant
) -> None:
    """Delivery has exactly two cases, and both end with a name in the envelope.

    To a central service: find or mint the alias and put it in. To a team member:
    read the sender's team, check the names that hold there, and deliver.
    """
    sender = Participant(kind=message.sender["kind"], name=message.sender["name"])
    if recipient.kind == "service":
        found = context.holdings.service_named(realm_id, recipient.name)
        if found is None:
            return
        as_alias = Participant(
            kind="alias",
            name=_alias_for(context, realm_id, team_id, message, found.record.id, sender),
        )
        mailbox = context.holdings.layout.service_mailbox(realm_id, found.record.id) / INBOX
        # The service is its own recipient, which it already knows; the alias goes
        # where the sender's name would otherwise be.
        _deliver(context, mailbox, message, as_alias, [recipient])
        return
    _deliver(
        context,
        _mailbox_for(context, realm_id, team_id, recipient, INBOX),
        message,
        sender,
        [Participant(kind=r["kind"], name=r["name"]) for r in message.recipients],
    )


def _alias_for(
    context: Context,
    realm_id: str,
    team_id: str,
    message: Message,
    service_id: str,
    sender: Participant,
) -> str:
    """Find the alias of this delivery, or mint it.

    Bound to one message and one service, which is what makes it useless for
    starting anything. Finding comes first so that the same delivery cannot end up
    with two.
    """
    existing = context.holdings.alias_for_delivery(realm_id, message.id, service_id)
    if existing is not None:
        return existing
    value = new_id()
    context.holdings.create_alias(
        realm_id,
        Alias(
            value=value,
            created_at=now_iso(),
            message_id=message.id,
            service_id=service_id,
            team_id=team_id,
            sender={"kind": sender.kind, "name": sender.name},
        ),
    )
    return value


def send_to_peers(
    context: Context,
    sender: Peer,
    *,
    recipients: object,
    subject: object,
    body: object = None,
    body_file_id: object = None,
    attachments: object = None,
    in_reply_to: object = None,
) -> Sent:
    resolved, warnings = resolve_peers(context, sender, recipients)
    text = resolve_body(context, sender.realm_id, body, body_file_id)
    entries, weight = check_attachments(context, sender.realm_id, attachments)
    return _store_and_deliver(
        context,
        realm_id=sender.realm_id,
        team_id=sender.team_id,
        sender=Participant(kind="peer", name=sender.name),
        recipients=resolved,
        subject=check_subject(subject),
        body=text,
        attachments=entries,
        attachment_weight=weight,
        in_reply_to=check_reply_to(context, sender.realm_id, in_reply_to),
        warnings=warnings,
    )


def send_to_service(
    context: Context,
    sender: Peer,
    *,
    recipient: object,
    subject: object,
    body: object = None,
    body_file_id: object = None,
    attachments: object = None,
    in_reply_to: object = None,
) -> Sent:
    target = resolve_service(context, sender, recipient)
    text = resolve_body(context, sender.realm_id, body, body_file_id)
    entries, weight = check_attachments(context, sender.realm_id, attachments)
    return _store_and_deliver(
        context,
        realm_id=sender.realm_id,
        team_id=sender.team_id,
        sender=Participant(kind="peer", name=sender.name),
        recipients=[target],
        subject=check_subject(subject),
        body=text,
        attachments=entries,
        attachment_weight=weight,
        in_reply_to=check_reply_to(context, sender.realm_id, in_reply_to),
        warnings=[],
    )


def send_to_alias(
    context: Context,
    sender: Service,
    *,
    alias: str,
    subject: object,
    body: object = None,
    body_file_id: object = None,
    attachments: object = None,
) -> Sent:
    """The central service's one way of sending, and nobody else's.

    No recipient field: the alias is the recipient. `in_reply_to` is set by the
    service itself, to the message the alias belongs to — a service answers, it
    does not start, and that is the shape rather than a rule.

    No check that the caller was the recipient is needed: they have the alias or
    they do not. A passed-on message identifier is no use for this, there is no
    alias for one's own sent message, and no alias points at a service.
    """
    found = context.holdings.alias(sender.realm_id, alias)
    if found is None or found.service_id != sender.service_id:
        raise refusals.UnknownIdentifier("alias")
    text = resolve_body(context, sender.realm_id, body, body_file_id)
    entries, weight = check_attachments(context, sender.realm_id, attachments)
    # Two views, and both are needed. The **member** sees an ordinary message from a
    # name they can address, so the delivery goes to the real person. The
    # **service** must see the alias it answered — in the response to this call and
    # in its own outbox — because a name there would break the promise at the first
    # follow-up step.
    return _store_and_deliver(
        context,
        realm_id=sender.realm_id,
        team_id=found.team_id,
        sender=Participant(kind="service", name=sender.name),
        recipients=[Participant(kind=found.sender["kind"], name=found.sender["name"])],
        shown_recipients=[Participant(kind="alias", name=alias)],
        subject=check_subject(subject),
        body=text,
        attachments=entries,
        attachment_weight=weight,
        in_reply_to=found.message_id,
        warnings=[],
    )


# ------------------------------------------------------------------ the reading


@dataclass(frozen=True)
class Envelope:
    """A message as one reader sees it.

    `sender` is the one that holds in this reader's world. Everything else is the
    message's own: one message, stored once.
    """

    message_id: str
    sender: Participant
    recipients: list[Participant]
    sent_at: str
    subject: str
    body_size: int
    total_size: int
    attachments: list[dict]
    in_reply_to: str | None


def envelope(context: Context, caller: Caller, message_id: str) -> Envelope:
    """The envelope of the caller's own delivery, or the message's own.

    This is the one place the two rules meet, and they are about two readers
    rather than two answers. A recipient reads what was settled when it was
    delivered — for a service that is an alias where a name would be. Whoever uses
    a **passed-on** identifier sees the original sender, like anybody holding an
    identifier: it is not a leak of the alias promise but the capability approach,
    and what somebody puts in your hand on purpose you may read.

    A service always has a delivery of its own for anything it received, because
    an identifier only ever reaches it through its own mailbox.
    """
    if not is_id(message_id):
        raise refusals.UnknownIdentifier("message")
    realm_id = getattr(caller, "realm_id", None)
    if realm_id is None:
        raise refusals.UnknownIdentifier("message")
    stored = context.holdings.message(realm_id, message_id)
    if stored is None:
        # Unknown, or in another realm — the same answer, because telling a caller
        # that something exists elsewhere would make an identifier a way of asking
        # about other people's holdings.
        raise refusals.UnknownIdentifier("message")

    shown_sender = Participant(kind=stored.sender["kind"], name=stored.sender["name"])
    shown_recipients = [Participant(kind=r["kind"], name=r["name"]) for r in stored.recipients]
    mine = _own_delivery(context, caller, message_id)
    if mine is not None:
        # Both halves come from the delivery, not just the sender: a service that
        # answered an alias must see that alias where the person's name would be,
        # or the promise breaks at the first follow-up step.
        shown_sender = Participant(kind=mine.sender["kind"], name=mine.sender["name"])
        if mine.recipients:
            shown_recipients = [
                Participant(kind=r["kind"], name=r["name"]) for r in mine.recipients
            ]

    return Envelope(
        message_id=stored.id,
        sender=shown_sender,
        recipients=shown_recipients,
        sent_at=stored.created_at,
        subject=context.holdings.message_subject(realm_id, message_id) or "",
        body_size=stored.body_size,
        total_size=stored.total_size,
        attachments=stored.attachments,
        in_reply_to=stored.in_reply_to,
    )


def _own_delivery(context: Context, caller: Caller, message_id: str) -> MailboxEntry | None:
    """This caller's own entry for that message, in either view, or nothing.

    Nothing is the case of a passed-on identifier, and then the message's own
    envelope applies — the original sender, like for anybody holding an identifier.
    """
    if not isinstance(caller, Peer | Service):
        return None
    for view in (INBOX, OUTBOX):
        for entry in context.holdings.mailbox_entries(mailbox_of(context, caller, view)):
            if entry.message_id == message_id:
                return entry
    return None


def subject_of(context: Context, caller: Caller, message_id: str) -> str:
    return envelope(context, caller, message_id).subject


def body_of(context: Context, caller: Caller, message_id: str) -> str:
    """The body, raw. The service has never looked at it."""
    envelope(context, caller, message_id)
    realm_id = getattr(caller, "realm_id", "")
    return context.holdings.message_body(realm_id, message_id) or ""


# -------------------------------------------------------------------- the files


#: What a file is when its depositor did not say: text, like everything else this
#: service hands out unless asked otherwise.
UNSPECIFIED_MEDIA_TYPE = "text/plain"

#: A media type as it may travel in a header: printable ASCII, and not endless.
_MEDIA_TYPE = re.compile(r"[\x21-\x7e][\x20-\x7e]{0,254}")


def deposit_file(
    context: Context, caller: Peer | Service, content: bytes, media_type: object = None
) -> tuple[str, int, str]:
    """Keep a file, and what its depositor said it is.

    The media type is remembered as sent and handed back on every fetch — not
    checked against the bytes and not guessed from a name, because the depositor
    is the one who knows. Absent, the file is plain text. It is only refused where
    it could not be sent back at all: it goes out again in a header.
    """
    if len(content) > context.config.file_max_bytes:
        raise refusals.TooLarge(
            "file", limit=context.config.file_max_bytes, actual=len(content), unit="bytes"
        )
    said = media_type.strip() if isinstance(media_type, str) else ""
    if not said:
        said = UNSPECIFIED_MEDIA_TYPE
    elif not _MEDIA_TYPE.fullmatch(said):
        raise refusals.InvalidInput(
            "Content-Type",
            reason="a media type such as application/pdf, in printable ASCII and at most "
            "255 characters; it is handed back in a header on every fetch",
        )
    stored = context.holdings.put_file(caller.realm_id, new_id(), content, media_type=said)
    return stored.id, stored.size, said


def fetch_file(context: Context, caller: Caller, file_id: str) -> tuple[bytes, str | None]:
    """Whoever has the identifier may fetch it. Only the realm is checked.

    The identifier is the permission, and it is not checked whether the fetcher
    was an addressed recipient. The realm is the outer boundary of every
    identifier, and a fetch from another realm looks exactly like a fetch of
    something that does not exist.
    """
    if not is_id(file_id):
        raise refusals.UnknownIdentifier("file")
    realm_id = getattr(caller, "realm_id", None)
    if realm_id is None:
        raise refusals.UnknownIdentifier("file")
    content = context.holdings.file_content(realm_id, file_id)
    if content is None:
        raise refusals.UnknownIdentifier("file")
    stored = context.holdings.file(realm_id, file_id)
    return content, stored.media_type if stored is not None else None


# -------------------------------------------------------------- the observation


@dataclass(frozen=True)
class Filters:
    """What an observer may narrow the traffic of one team by.

    Kind and name always travel together, like every statement about a participant:
    inside one team the other side can be a member **or** a central service, and the
    kind says which namespace the name is in. One without the other is invalid input
    rather than a guess, because guessing would make the meaning of a name depend on
    another field — the thing this pair exists to avoid.

    `from` and `to` include both ends. An observer asking about a day means the day.
    """

    sender: Participant | None = None
    recipient: Participant | None = None
    since: str | None = None
    until: str | None = None

    @staticmethod
    def of(
        sender_kind: object = None,
        sender_name: object = None,
        recipient_kind: object = None,
        recipient_name: object = None,
        since: object = None,
        until: object = None,
    ) -> Filters:
        return Filters(
            sender=_pair(sender_kind, sender_name, "sender"),
            recipient=_pair(recipient_kind, recipient_name, "recipient"),
            since=_moment(since, "from"),
            until=_moment(until, "to"),
        )

    def keeps(self, envelope: Envelope) -> bool:
        if self.sender is not None and (
            envelope.sender.kind != self.sender.kind
            or comparison_key(envelope.sender.name) != comparison_key(self.sender.name)
        ):
            return False
        if self.recipient is not None and not any(
            person.kind == self.recipient.kind
            and comparison_key(person.name) == comparison_key(self.recipient.name)
            for person in envelope.recipients
        ):
            return False
        if self.since is not None and envelope.sent_at < self.since:
            return False
        return not (self.until is not None and envelope.sent_at > self.until)


#: The kinds a filter may name. `alias` is not among them: an observer sees the real
#: participant, and an alias is resolved before it ever reaches them.
FILTERABLE_KINDS = ("peer", "service")


def _pair(kind: object, name: object, field: str) -> Participant | None:
    if kind is None and name is None:
        return None
    if kind is None or name is None:
        raise refusals.InvalidInput(
            f"{field}_kind" if kind is None else f"{field}_name",
            reason=f"{field}_kind and {field}_name go together",
        )
    if kind not in FILTERABLE_KINDS:
        raise refusals.InvalidInput(f"{field}_kind", reason="one of peer, service")
    if check_name(name) is not None:
        raise refusals.InvalidInput(f"{field}_name", reason="a name")
    return Participant(kind=str(kind), name=str(name))


def _moment(value: object, field: str) -> str | None:
    """A timestamp, checked by shape rather than parsed into a clock.

    Compared as text, which is exactly right for this format: an ISO timestamp in UTC
    sorts lexicographically the way it sorts chronologically, which is the same
    property the mailbox ordering rests on.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not EXAMPLE_SHAPE.match(value):
        raise refusals.InvalidInput(
            field, reason="a timestamp like 2026-09-28T09:12:44.081Z, in UTC with milliseconds"
        )
    return value


def team_traffic(
    context: Context,
    observer: Observer,
    team_id: str,
    *,
    offset: int,
    limit: int,
    filters: Filters | None = None,
) -> list[Envelope]:
    """Everything that happened in one team, newest first.

    Read from the messages of the realm rather than from a mailbox: an observer has
    no mailbox, and the traffic of a team is not anybody's delivery. What they see
    is therefore the message's own envelope — the true sender, which is the point
    of watching.
    """
    found = []
    messages = context.holdings.layout.messages(observer.realm_id)
    if not messages.is_dir():
        return []
    for entry in sorted((p.name for p in messages.iterdir() if p.is_dir()), reverse=True):
        stored = context.holdings.message(observer.realm_id, entry)
        if stored is None or stored.team_id != team_id:
            continue
        found.append(
            Envelope(
                message_id=stored.id,
                sender=Participant(kind=stored.sender["kind"], name=stored.sender["name"]),
                recipients=[Participant(kind=r["kind"], name=r["name"]) for r in stored.recipients],
                sent_at=stored.created_at,
                subject=context.holdings.message_subject(observer.realm_id, stored.id) or "",
                body_size=stored.body_size,
                total_size=stored.total_size,
                attachments=stored.attachments,
                in_reply_to=stored.in_reply_to,
            )
        )
    if filters is not None:
        found = [envelope for envelope in found if filters.keeps(envelope)]
    found.sort(key=lambda e: e.sent_at, reverse=True)
    return found[offset : offset + limit]


@dataclass(frozen=True)
class MailboxView:
    """One line of a mailbox listing: the envelope, without the body.

    Assembled from two places on purpose. The delivery says who the sender is **in
    this reader's world**; the message says what it weighs and what it is called. A
    listing that took the sender from the message would show a service the name it
    must never see.
    """

    message_id: str
    sender: Participant | None
    recipients: list[Participant] | None
    sent_at: str
    subject: str
    body_size: int
    total_size: int
    attachment_count: int
    in_reply_to: str | None


def mailbox(
    context: Context,
    caller: Peer | Service,
    view: str,
    *,
    offset: int,
    limit: int,
) -> list[MailboxView]:
    """A window over a mailbox, newest first, envelopes only.

    The inbox names the sender and not the recipients — the recipient is the reader.
    The outbox names the recipients and not the sender — the sender is the reader.
    One shape, one word different.
    """
    found: list[MailboxView] = []
    realm_id = caller.realm_id
    for entry in list_mailbox(context, caller, view, offset=offset, limit=limit):
        stored = context.holdings.message(realm_id, entry.message_id)
        if stored is None:
            continue
        found.append(
            MailboxView(
                message_id=entry.message_id,
                sender=(
                    Participant(kind=entry.sender["kind"], name=entry.sender["name"])
                    if view == INBOX
                    else None
                ),
                recipients=(
                    [Participant(kind=r["kind"], name=r["name"]) for r in entry.recipients]
                    if view == OUTBOX
                    else None
                ),
                sent_at=stored.created_at,
                subject=context.holdings.message_subject(realm_id, entry.message_id) or "",
                body_size=stored.body_size,
                total_size=stored.total_size,
                attachment_count=len(stored.attachments),
                in_reply_to=stored.in_reply_to,
            )
        )
    return found


def counted_mailbox(context: Context, caller: Peer | Service, view: str) -> int:
    """How many entries a mailbox has, for a listing that says where its window sits."""
    return len(context.holdings.mailbox_entries(mailbox_of(context, caller, view)))


def safe_file_name(name: str) -> str:
    """The name a file is saved under: smoothed, not trusted.

    It goes into a response header and it is the last part of an address, so control
    characters and quotation marks are **refused** — a caller has to see that mistake —
    and a directory part is **dropped**. The specification uses two verbs there and
    means two things.

    Lives here rather than on a surface because both surfaces that serve a file need
    it, and the second copy is where the two would drift apart.
    """
    if any(ch in name for ch in "\r\n\t\0") or '"' in name:
        raise refusals.InvalidInput(
            "file_name", reason="no control characters and no quotation marks"
        )
    smoothed = name.replace("\\", "/").rsplit("/", 1)[-1]
    if not smoothed or smoothed in (".", ".."):
        raise refusals.InvalidInput("file_name", reason="nothing is left of it as a name")
    return smoothed
