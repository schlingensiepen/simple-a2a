"""The holdings: reading and writing them, and nothing about why.

Every operation here is one of four moves, and the interesting part is that
none of them needs a lock:

- **put** — write an object's `meta.json` and its raw texts into its directory.
- **get** — read one back.
- **claim** — take a name, exclusively, in the one step that also tests whether
  it was free. This is what makes uniqueness safe without a lock: two callers
  racing for one name both try to create the same index entry, and the
  filesystem lets exactly one of them win.
- **move** — change a thing's state by renaming its directory.

Raw texts are stored as their own files rather than inside the JSON. Whatever a
participant delivered comes back out byte for byte under its own address, and a
round trip through JSON is not byte for byte — it normalises, it re-encodes, and
it turns an unusual character into an escape that a caller never wrote.

**What belongs one floor up.** Nothing here decides whether an operation is
allowed, what a rejection says, or what a caller is shown. This module knows
that a name can be taken and says so; which rejection that becomes is decided
where the rejections live.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from simple_a2a.core import atomic
from simple_a2a.core.clock import now_iso
from simple_a2a.store.layout import ENVELOPE, META, Layout, State
from simple_a2a.store.records import (
    Alias,
    Invitation,
    MailboxEntry,
    Member,
    Message,
    Observer,
    Realm,
    Record,
    Service,
    StoredFile,
    Team,
    TokenPointer,
    token_hash,
)

#: The names of the raw text files an object can carry. Each one is an address a
#: caller can read back, which is why each one is a file.
MISSION = "mission"
SELF_IMAGE = "self-image"
PURPOSE = "purpose"
SUBJECT = "subject"
BODY = "body"
CONTENT = "content"


class NameTaken(Exception):
    """This name is already taken, revoked or not.

    A name stays taken for good, because nothing is deleted: somebody who lost
    their token comes back under a new name. Raised rather than returned, because
    a caller who forgets to check a return value writes the second `Otto`.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"the name {name!r} is taken")
        self.name = name


@dataclass(frozen=True)
class Located[T]:
    """A record, with the state it was found in.

    The state is not in the record — it is the directory — so anything reading a
    record also gets told where it sat.
    """

    record: T
    state: State


class Holdings:
    """The holdings under one data directory."""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    # ------------------------------------------------------------------ moves

    def prepare(self) -> None:
        atomic.ensure_private_directory(self.layout.root)

    @staticmethod
    def _put(
        directory: Path,
        record: Record,
        texts: dict[str, str | bytes] | None = None,
        *,
        as_file: str = META,
    ) -> None:
        atomic.write_text(directory / as_file, record.to_json())
        for name, value in (texts or {}).items():
            if isinstance(value, bytes):
                atomic.write_bytes(directory / name, value)
            else:
                atomic.write_text(directory / name, value)

    @staticmethod
    def _get[T: Record](directory: Path, kind: type[T], *, as_file: str = META) -> T | None:
        try:
            return kind.from_json((directory / as_file).read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _text(path: Path) -> str | None:
        """Read a delivered text back, byte for byte.

        Read as bytes and decoded, rather than as text: reading as text
        translates line endings, so a caller who delivered a `\r\n` would get a
        `\n` back. Which is the whole promise broken, quietly, for the one kind
        of content where "exactly what came in" is the guarantee.
        """
        try:
            return path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _claim(index: Path, value: str) -> None:
        """Take a name, or raise. One step, and the filesystem is the referee."""
        index.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(index, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise NameTaken(index.name) from None
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(value + "\n")

    @staticmethod
    def _claimed(index: Path) -> str | None:
        try:
            return index.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    @staticmethod
    def _ids_in(directory: Path) -> list[str]:
        if not directory.is_dir():
            return []
        return sorted(p.name for p in directory.iterdir() if p.is_dir())

    # ----------------------------------------------------------------- realms

    def create_realm(self, realm_id: str, name: str) -> Realm:
        self._claim(self.layout.realm_by_name(name), realm_id)
        record = Realm(id=realm_id, name=name, created_at=now_iso())
        self._put(self.layout.realm(realm_id), record)
        return record

    def realm(self, realm_id: str) -> Realm | None:
        return self._get(self.layout.realm(realm_id), Realm)

    def realm_named(self, name: str) -> Realm | None:
        realm_id = self._claimed(self.layout.realm_by_name(name))
        return self.realm(realm_id) if realm_id else None

    def realm_ids(self) -> list[str]:
        return self._ids_in(self.layout.realms)

    # ------------------------------------------------------------------ teams

    def create_team(self, realm_id: str, team_id: str, name: str, purpose: str) -> Team:
        self._claim(self.layout.team_by_name(realm_id, name), team_id)
        record = Team(id=team_id, name=name, created_at=now_iso())
        self._put(self.layout.team(realm_id, team_id), record, {PURPOSE: purpose})
        return record

    def team(self, realm_id: str, team_id: str) -> Team | None:
        return self._get(self.layout.team(realm_id, team_id), Team)

    def team_named(self, realm_id: str, name: str) -> Team | None:
        team_id = self._claimed(self.layout.team_by_name(realm_id, name))
        return self.team(realm_id, team_id) if team_id else None

    def team_ids(self, realm_id: str) -> list[str]:
        return self._ids_in(self.layout.teams(realm_id))

    def team_purpose(self, realm_id: str, team_id: str) -> str | None:
        return self._text(self.layout.team_purpose(realm_id, team_id))

    # ---------------------------------------------------------------- members

    def create_member(
        self,
        realm_id: str,
        team_id: str,
        member_id: str,
        name: str,
        *,
        token: str,
        mission: str,
        self_image: str = "",
        is_realm_master: bool = False,
    ) -> Member:
        self._claim(self.layout.member_by_name(realm_id, team_id, name), member_id)
        record = Member(
            id=member_id,
            name=name,
            created_at=now_iso(),
            token_hash=token_hash(token),
            is_realm_master=is_realm_master,
        )
        self._put(
            self.layout.member(realm_id, team_id, member_id, State.ACTIVE),
            record,
            {MISSION: mission, SELF_IMAGE: self_image},
        )
        self.register_token(
            token,
            TokenPointer(kind="peer", realm_id=realm_id, team_id=team_id, subject_id=member_id),
        )
        self.layout.member_mailbox(realm_id, team_id, member_id).mkdir(parents=True, exist_ok=True)
        return record

    def member(self, realm_id: str, team_id: str, member_id: str) -> Located[Member] | None:
        for state in (State.ACTIVE, State.REVOKED):
            found = self._get(self.layout.member(realm_id, team_id, member_id, state), Member)
            if found is not None:
                return Located(record=found, state=state)
        return None

    def member_named(self, realm_id: str, team_id: str, name: str) -> Located[Member] | None:
        """By name, in whatever state — a revoked member stays visible and readable."""
        member_id = self._claimed(self.layout.member_by_name(realm_id, team_id, name))
        return self.member(realm_id, team_id, member_id) if member_id else None

    def member_ids(self, realm_id: str, team_id: str, state: State) -> list[str]:
        return self._ids_in(self.layout.members(realm_id, team_id) / state)

    def members(self, realm_id: str, team_id: str) -> Iterator[Located[Member]]:
        for state in (State.ACTIVE, State.REVOKED):
            for member_id in self.member_ids(realm_id, team_id, state):
                found = self._get(self.layout.member(realm_id, team_id, member_id, state), Member)
                if found is not None:
                    yield Located(record=found, state=state)

    def member_mission(
        self, realm_id: str, team_id: str, member_id: str, state: State
    ) -> str | None:
        return self._text(self.layout.member(realm_id, team_id, member_id, state) / MISSION)

    def member_self_image(
        self, realm_id: str, team_id: str, member_id: str, state: State
    ) -> str | None:
        return self._text(self.layout.member(realm_id, team_id, member_id, state) / SELF_IMAGE)

    def set_member_self_image(
        self, realm_id: str, team_id: str, member_id: str, state: State, text: str
    ) -> None:
        atomic.write_text(
            self.layout.member(realm_id, team_id, member_id, state) / SELF_IMAGE, text
        )

    def revoke_member(self, realm_id: str, team_id: str, member_id: str) -> bool:
        """Move the directory. Idempotent, because revoking twice is allowed."""
        source = self.layout.member(realm_id, team_id, member_id, State.ACTIVE)
        if not source.is_dir():
            return False
        record = self._get(source, Member)
        if record is not None:
            self._put(source, Member(**{**_fields(record), "revoked_at": now_iso()}))
        atomic.move(source, self.layout.member(realm_id, team_id, member_id, State.REVOKED))
        return True

    def set_realm_master(self, realm_id: str, team_id: str, member_id: str, value: bool) -> bool:
        located = self.member(realm_id, team_id, member_id)
        if located is None:
            return False
        directory = self.layout.member(realm_id, team_id, member_id, located.state)
        self._put(directory, Member(**{**_fields(located.record), "is_realm_master": value}))
        return True

    # --------------------------------------------------------------- services

    def create_service(
        self, realm_id: str, service_id: str, name: str, *, token: str, self_image: str
    ) -> Service:
        self._claim(self.layout.service_by_name(realm_id, name), service_id)
        record = Service(
            id=service_id, name=name, created_at=now_iso(), token_hash=token_hash(token)
        )
        self._put(
            self.layout.service(realm_id, service_id, State.ACTIVE),
            record,
            {SELF_IMAGE: self_image},
        )
        self.register_token(
            token, TokenPointer(kind="service", realm_id=realm_id, subject_id=service_id)
        )
        self.layout.service_mailbox(realm_id, service_id).mkdir(parents=True, exist_ok=True)
        return record

    def service(self, realm_id: str, service_id: str) -> Located[Service] | None:
        for state in (State.ACTIVE, State.REVOKED):
            found = self._get(self.layout.service(realm_id, service_id, state), Service)
            if found is not None:
                return Located(record=found, state=state)
        return None

    def service_named(self, realm_id: str, name: str) -> Located[Service] | None:
        service_id = self._claimed(self.layout.service_by_name(realm_id, name))
        return self.service(realm_id, service_id) if service_id else None

    def services(self, realm_id: str) -> Iterator[Located[Service]]:
        for state in (State.ACTIVE, State.REVOKED):
            for service_id in self._ids_in(self.layout.services(realm_id) / state):
                found = self._get(self.layout.service(realm_id, service_id, state), Service)
                if found is not None:
                    yield Located(record=found, state=state)

    def service_self_image(self, realm_id: str, service_id: str, state: State) -> str | None:
        return self._text(self.layout.service(realm_id, service_id, state) / SELF_IMAGE)

    def set_service_self_image(
        self, realm_id: str, service_id: str, state: State, text: str
    ) -> None:
        atomic.write_text(self.layout.service(realm_id, service_id, state) / SELF_IMAGE, text)

    def revoke_service(self, realm_id: str, service_id: str) -> bool:
        source = self.layout.service(realm_id, service_id, State.ACTIVE)
        if not source.is_dir():
            return False
        record = self._get(source, Service)
        if record is not None:
            self._put(source, Service(**{**_fields(record), "revoked_at": now_iso()}))
        atomic.move(source, self.layout.service(realm_id, service_id, State.REVOKED))
        return True

    # -------------------------------------------------------------- observers

    def create_observer(
        self, realm_id: str, observer_id: str, display_name: str, *, token: str
    ) -> Observer:
        self._claim(self.layout.observer_by_name(realm_id, display_name), observer_id)
        record = Observer(
            id=observer_id,
            display_name=display_name,
            created_at=now_iso(),
            token_hash=token_hash(token),
        )
        self._put(self.layout.observer(realm_id, observer_id, State.ACTIVE), record)
        self.register_token(
            token, TokenPointer(kind="observer", realm_id=realm_id, subject_id=observer_id)
        )
        return record

    def observer(self, realm_id: str, observer_id: str) -> Located[Observer] | None:
        for state in (State.ACTIVE, State.REVOKED):
            found = self._get(self.layout.observer(realm_id, observer_id, state), Observer)
            if found is not None:
                return Located(record=found, state=state)
        return None

    def observer_named(self, realm_id: str, display_name: str) -> Located[Observer] | None:
        observer_id = self._claimed(self.layout.observer_by_name(realm_id, display_name))
        return self.observer(realm_id, observer_id) if observer_id else None

    def observers(self, realm_id: str) -> Iterator[Located[Observer]]:
        for state in (State.ACTIVE, State.REVOKED):
            for observer_id in self._ids_in(self.layout.observers(realm_id) / state):
                found = self._get(self.layout.observer(realm_id, observer_id, state), Observer)
                if found is not None:
                    yield Located(record=found, state=state)

    def revoke_observer(self, realm_id: str, observer_id: str) -> bool:
        source = self.layout.observer(realm_id, observer_id, State.ACTIVE)
        if not source.is_dir():
            return False
        record = self._get(source, Observer)
        if record is not None:
            self._put(source, Observer(**{**_fields(record), "revoked_at": now_iso()}))
        atomic.move(source, self.layout.observer(realm_id, observer_id, State.REVOKED))
        return True

    # ------------------------------------------------------------ invitations

    def create_invitation(
        self,
        realm_id: str,
        *,
        voucher: str,
        kind: str,
        display_name: str,
        issued_by_kind: str,
        issued_by_name: str,
        team_id: str | None = None,
        mission: str = "",
    ) -> Invitation:
        """Store an invitation. The voucher itself is never written down.

        Its hash names the directory, which is how a presented one is found, and
        which is why there is nothing here to hand back out.
        """
        digest = token_hash(voucher)
        self._claim(self.layout.invitation_by_name(realm_id, kind, display_name), digest)
        record = Invitation(
            kind=kind,
            display_name=display_name,
            created_at=now_iso(),
            issued_by_kind=issued_by_kind,
            issued_by_name=issued_by_name,
            team_id=team_id,
        )
        self._put(self.layout.invitation(realm_id, digest, State.OPEN), record, {MISSION: mission})
        return record

    def invitation_for(self, realm_id: str, voucher: str) -> Located[Invitation] | None:
        """Find an invitation by the voucher somebody presented."""
        return self._invitation(realm_id, token_hash(voucher))

    def _invitation(self, realm_id: str, digest: str) -> Located[Invitation] | None:
        for state in (State.OPEN, State.CONSUMED, State.REVOKED):
            found = self._get(self.layout.invitation(realm_id, digest, state), Invitation)
            if found is not None:
                return Located(record=found, state=state)
        return None

    def invitation_named(
        self, realm_id: str, kind: str, display_name: str
    ) -> Located[Invitation] | None:
        digest = self._claimed(self.layout.invitation_by_name(realm_id, kind, display_name))
        return self._invitation(realm_id, digest) if digest else None

    def invitations(self, realm_id: str, kind: str | None = None) -> Iterator[Located[Invitation]]:
        for state in (State.OPEN, State.CONSUMED, State.REVOKED):
            for digest in self._ids_in(self.layout.invitations(realm_id) / state):
                found = self._get(self.layout.invitation(realm_id, digest, state), Invitation)
                if found is not None and (kind is None or found.kind == kind):
                    yield Located(record=found, state=state)

    def invitation_mission(self, realm_id: str, digest: str, state: State) -> str | None:
        return self._text(self.layout.invitation(realm_id, digest, state) / MISSION)

    def consume_invitation(self, realm_id: str, voucher: str) -> bool:
        return self._move_invitation(realm_id, token_hash(voucher), State.CONSUMED, "consumed_at")

    def revoke_invitation_named(self, realm_id: str, kind: str, display_name: str) -> bool:
        digest = self._claimed(self.layout.invitation_by_name(realm_id, kind, display_name))
        if digest is None:
            return False
        return self._move_invitation(realm_id, digest, State.REVOKED, "revoked_at")

    def _move_invitation(self, realm_id: str, digest: str, state: State, stamp: str) -> bool:
        source = self.layout.invitation(realm_id, digest, State.OPEN)
        if not source.is_dir():
            return False
        record = self._get(source, Invitation)
        if record is not None:
            self._put(source, Invitation(**{**_fields(record), stamp: now_iso()}))
        atomic.move(source, self.layout.invitation(realm_id, digest, state))
        return True

    # ----------------------------------------------------------------- tokens

    def register_token(self, token: str, pointer: TokenPointer) -> None:
        atomic.write_text(self.layout.token(token_hash(token)), pointer.to_json())

    def token_pointer(self, token: str) -> TokenPointer | None:
        """Which thing this token belongs to, or `None` if none ever did.

        Found in one read rather than by searching the holdings, and the entry
        stays after a revocation — a revoked token and one nobody issued are two
        different answers.
        """
        try:
            return TokenPointer.from_json(
                self.layout.token(token_hash(token)).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------ files

    def put_file(self, realm_id: str, file_id: str, content: bytes) -> StoredFile:
        record = StoredFile(id=file_id, created_at=now_iso(), size=len(content))
        self._put(self.layout.file(realm_id, file_id), record, {CONTENT: content})
        return record

    def file(self, realm_id: str, file_id: str) -> StoredFile | None:
        return self._get(self.layout.file(realm_id, file_id), StoredFile)

    def file_content(self, realm_id: str, file_id: str) -> bytes | None:
        try:
            return (self.layout.file(realm_id, file_id) / CONTENT).read_bytes()
        except OSError:
            return None

    # --------------------------------------------------------------- messages

    def put_message(self, realm_id: str, message: Message, *, subject: str, body: str) -> Message:
        self._put(
            self.layout.message(realm_id, message.id),
            message,
            {SUBJECT: subject, BODY: body},
        )
        return message

    def message(self, realm_id: str, message_id: str) -> Message | None:
        return self._get(self.layout.message(realm_id, message_id), Message)

    def message_subject(self, realm_id: str, message_id: str) -> str | None:
        return self._text(self.layout.message(realm_id, message_id) / SUBJECT)

    def message_body(self, realm_id: str, message_id: str) -> str | None:
        return self._text(self.layout.message(realm_id, message_id) / BODY)

    # -------------------------------------------------------------- mailboxes

    @staticmethod
    def _entry_name(entry: MailboxEntry) -> str:
        """Timestamp first, so a plain directory listing is already in order.

        Newest first is what every listing here wants, and a name that sorts is
        an index that cannot fall out of step with what it indexes. Equal
        timestamps have no order, which the specification says outright.
        """
        return f"{entry.delivered_at}-{entry.message_id}"

    def deliver(self, mailbox: Path, entry: MailboxEntry) -> None:
        self._put(mailbox / self._entry_name(entry), entry, as_file=ENVELOPE)

    def mailbox_entries(self, mailbox: Path, *, newest_first: bool = True) -> list[MailboxEntry]:
        if not mailbox.is_dir():
            return []
        names = sorted((p.name for p in mailbox.iterdir() if p.is_dir()), reverse=newest_first)
        found = []
        for name in names:
            entry = self._get(mailbox / name, MailboxEntry, as_file=ENVELOPE)
            if entry is not None:
                found.append(entry)
        return found

    # ---------------------------------------------------------------- aliases

    def alias_for_delivery(self, realm_id: str, message_id: str, service_id: str) -> str | None:
        return self._claimed(self.layout.alias_by_delivery(realm_id, message_id, service_id))

    def create_alias(self, realm_id: str, alias: Alias) -> None:
        self._put(self.layout.alias_by_value(realm_id, alias.value), alias)
        index = self.layout.alias_by_delivery(realm_id, alias.message_id, alias.service_id)
        index.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(index, alias.value + "\n")

    def alias(self, realm_id: str, value: str) -> Alias | None:
        return self._get(self.layout.alias_by_value(realm_id, value), Alias)

    # ------------------------------------------------------------------ notes

    def global_note(self) -> str | None:
        return self._text(self.layout.global_note)

    def set_global_note(self, text: str) -> None:
        atomic.write_text(self.layout.global_note, text)

    def realm_note(self, realm_id: str) -> str | None:
        return self._text(self.layout.realm_note(realm_id))

    def set_realm_note(self, realm_id: str, text: str) -> None:
        atomic.write_text(self.layout.realm_note(realm_id), text)


def _fields(record: Record) -> dict[str, object]:
    """A record's fields as a dictionary, for writing a changed copy.

    Records are frozen, so a change is a new one. Being explicit about that is
    the point: nothing here mutates a thing that is already on disk.
    """
    return {f.name: getattr(record, f.name) for f in dataclasses.fields(record)}  # type: ignore[arg-type]
