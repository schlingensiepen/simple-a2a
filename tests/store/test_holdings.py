"""The holdings: names are taken atomically, states are directories, nothing goes.

Three properties carry the whole design, and each is checked here:

- a name is taken in one step, so two callers racing for it cannot both win;
- a state change is a rename, so nothing is ever half-changed;
- nothing is deleted, so a name stays taken and a revoked thing stays readable.
"""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from simple_a2a.core.ids import new_id
from simple_a2a.store.holdings import Holdings, NameTaken
from simple_a2a.store.layout import ENTRY_SEPARATOR, Layout, State
from simple_a2a.store.records import Alias, MailboxEntry, Message, Participant


@pytest.fixture
def holdings(tmp_path: Path) -> Holdings:
    made = Holdings(Layout(root=tmp_path / "data"))
    made.prepare()
    return made


@pytest.fixture
def realm(holdings: Holdings):
    return holdings.create_realm(new_id(), "haus")


@pytest.fixture
def team(holdings: Holdings, realm):
    return holdings.create_team(realm.id, new_id(), "kueche", "Wir kochen.")


def test_a_realm_is_found_by_its_name_whatever_the_case(holdings: Holdings, realm) -> None:
    assert holdings.realm_named("HAUS") is not None
    assert holdings.realm_named("haus").id == realm.id
    assert holdings.realm_named("keller") is None


def test_a_name_can_be_taken_only_once(holdings: Holdings, realm) -> None:
    with pytest.raises(NameTaken):
        holdings.create_realm(new_id(), "Haus")


def test_the_two_name_spaces_are_independent(holdings: Holdings, realm, team) -> None:
    """Members are unique per team, services per realm — so one cannot block the other."""
    other = holdings.create_team(realm.id, new_id(), "bad", "Wir waschen.")
    holdings.create_member(realm.id, team.id, new_id(), "Otto", token=new_id(), mission="a")
    holdings.create_member(realm.id, other.id, new_id(), "Otto", token=new_id(), mission="b")
    holdings.create_service(realm.id, new_id(), "Otto", token=new_id(), self_image="c")

    assert holdings.member_named(realm.id, team.id, "otto") is not None
    assert holdings.member_named(realm.id, other.id, "otto") is not None
    assert holdings.service_named(realm.id, "otto") is not None


def test_a_display_name_is_unique_per_kind_not_per_realm(holdings: Holdings, realm, team) -> None:
    """An invitation does not block an observer's name, and neither blocks the other's."""
    holdings.create_invitation(
        realm.id,
        voucher=new_id(),
        kind="member",
        display_name="Zettel",
        invited_name="Berta",
        issued_by_kind="admin",
        issued_by_name="operator",
        team_id=team.id,
    )
    holdings.create_observer(realm.id, new_id(), "Zettel", token=new_id())
    holdings.create_invitation(
        realm.id,
        voucher=new_id(),
        kind="service",
        display_name="Zettel",
        invited_name="Berta",
        issued_by_kind="peer",
        issued_by_name="Otto",
    )

    assert holdings.invitation_named(realm.id, "member", "zettel") is not None
    assert holdings.invitation_named(realm.id, "service", "zettel") is not None
    assert holdings.observer_named(realm.id, "zettel") is not None

    with pytest.raises(NameTaken):
        holdings.create_observer(realm.id, new_id(), "ZETTEL", token=new_id())


def test_a_raw_text_comes_back_byte_for_byte(holdings: Holdings, realm) -> None:
    """Which is why texts are files and not fields in the JSON."""
    awkward = 'Zeile eins\r\nZeile "zwei"\t\\ ende\n\n  Einrückung \N{SNOWMAN}\n'
    team = holdings.create_team(realm.id, new_id(), "roh", awkward)

    assert holdings.team_purpose(realm.id, team.id) == awkward


def test_a_token_is_found_in_one_read_and_never_stored_in_the_clear(
    holdings: Holdings, realm, team
) -> None:
    token = new_id()
    member = holdings.create_member(realm.id, team.id, new_id(), "Otto", token=token, mission="a")

    pointer = holdings.token_pointer(token)
    assert pointer is not None
    assert (pointer.kind, pointer.realm_id, pointer.team_id, pointer.subject_id) == (
        "peer",
        realm.id,
        team.id,
        member.id,
    )
    assert holdings.token_pointer(new_id()) is None

    # Nowhere in the holdings, in any file, in the clear.
    for path in holdings.layout.root.rglob("*"):
        if path.is_file():
            assert token not in path.read_text(encoding="utf-8", errors="replace")
            assert token not in path.name


def test_revoking_moves_the_directory_and_keeps_everything(holdings: Holdings, realm, team) -> None:
    token = new_id()
    member = holdings.create_member(
        realm.id, team.id, new_id(), "Otto", token=token, mission="Er rührt."
    )

    assert holdings.revoke_member(realm.id, team.id, member.id)

    located = holdings.member(realm.id, team.id, member.id)
    assert located is not None
    assert located.state is State.REVOKED
    assert located.record.revoked_at is not None
    # Still visible, still readable: messages from them are in somebody's inbox
    # and one has to be able to look up who that was.
    assert holdings.member_named(realm.id, team.id, "otto") is not None
    assert holdings.member_mission(realm.id, team.id, member.id, State.REVOKED) == "Er rührt."
    # And the token is still known, which is what lets it be answered as revoked
    # rather than as never issued.
    assert holdings.token_pointer(token) is not None


def test_revoking_twice_is_allowed_and_says_what_happened(holdings: Holdings, realm, team) -> None:
    member = holdings.create_member(
        realm.id, team.id, new_id(), "Otto", token=new_id(), mission="a"
    )

    assert holdings.revoke_member(realm.id, team.id, member.id)
    assert not holdings.revoke_member(realm.id, team.id, member.id)
    assert holdings.member(realm.id, team.id, member.id).state is State.REVOKED


def test_a_name_stays_taken_after_a_revocation(holdings: Holdings, realm, team) -> None:
    """Whoever lost a token comes back under a new name — for good."""
    member = holdings.create_member(
        realm.id, team.id, new_id(), "Otto", token=new_id(), mission="a"
    )
    holdings.revoke_member(realm.id, team.id, member.id)

    with pytest.raises(NameTaken):
        holdings.create_member(realm.id, team.id, new_id(), "otto", token=new_id(), mission="b")


def test_an_invitation_is_found_by_its_voucher_and_the_voucher_is_nowhere(
    holdings: Holdings, realm, team
) -> None:
    voucher = new_id()
    holdings.create_invitation(
        realm.id,
        voucher=voucher,
        kind="member",
        display_name="Zettel",
        invited_name="Berta",
        issued_by_kind="admin",
        issued_by_name="operator",
        team_id=team.id,
        mission="Er rührt.",
    )

    located = holdings.invitation_for(realm.id, voucher)
    assert located is not None
    assert located.state is State.OPEN
    assert located.record.team_id == team.id

    for path in holdings.layout.root.rglob("*"):
        if path.is_file():
            assert voucher not in path.read_text(encoding="utf-8", errors="replace")
        assert voucher not in path.name


def test_an_invitation_is_used_up_once(holdings: Holdings, realm, team) -> None:
    voucher = new_id()
    holdings.create_invitation(
        realm.id,
        voucher=voucher,
        kind="member",
        display_name="Zettel",
        invited_name="Berta",
        issued_by_kind="admin",
        issued_by_name="operator",
        team_id=team.id,
    )

    assert holdings.consume_invitation(realm.id, voucher)
    assert not holdings.consume_invitation(realm.id, voucher)
    assert holdings.invitation_for(realm.id, voucher).state is State.CONSUMED


def test_an_invitation_is_revoked_over_its_display_name_never_its_voucher(
    holdings: Holdings, realm, team
) -> None:
    voucher = new_id()
    holdings.create_invitation(
        realm.id,
        voucher=voucher,
        kind="member",
        display_name="Zettel",
        invited_name="Berta",
        issued_by_kind="admin",
        issued_by_name="operator",
        team_id=team.id,
    )

    assert holdings.revoke_invitation_named(realm.id, "member", "ZETTEL")
    assert holdings.invitation_for(realm.id, voucher).state is State.REVOKED
    assert not holdings.consume_invitation(realm.id, voucher)


def test_a_mailbox_lists_newest_first_without_an_index(holdings: Holdings, realm, team) -> None:
    """The entry's name starts with its timestamp, so the ordering is the listing."""
    member = holdings.create_member(
        realm.id, team.id, new_id(), "Otto", token=new_id(), mission="a"
    )
    mailbox = holdings.layout.member_mailbox(realm.id, team.id, member.id) / "inbox"
    stamps = ["2026-09-27T10:00:00.000Z", "2026-09-27T12:00:00.000Z", "2026-09-27T11:00:00.000Z"]
    for stamp in stamps:
        holdings.deliver(
            mailbox,
            MailboxEntry(
                message_id=new_id(),
                delivered_at=stamp,
                sender={"kind": "peer", "name": "Anna"},
            ),
        )

    listed = holdings.mailbox_entries(mailbox)

    assert [entry.delivered_at for entry in listed] == sorted(stamps, reverse=True)


def test_a_message_is_stored_once_and_a_delivery_carries_its_own_sender(
    holdings: Holdings, realm, team
) -> None:
    """An envelope carries the names that hold in its recipient's world."""
    message = Message(
        id=new_id(),
        created_at="2026-09-27T10:00:00.000Z",
        team_id=team.id,
        sender={"kind": "peer", "name": "Anna"},
        recipients=[{"kind": "service", "name": "Wetter"}],
        body_size=7,
        total_size=7,
    )
    holdings.put_message(realm.id, message, subject="Betreff", body="Inhalt.")

    stored = holdings.message(realm.id, message.id)
    assert stored is not None
    assert stored.sender == {"kind": "peer", "name": "Anna"}
    assert holdings.message_subject(realm.id, message.id) == "Betreff"
    assert holdings.message_body(realm.id, message.id) == "Inhalt."

    service = holdings.create_service(realm.id, new_id(), "Wetter", token=new_id(), self_image="x")
    mailbox = holdings.layout.service_mailbox(realm.id, service.id) / "inbox"
    holdings.deliver(
        mailbox,
        MailboxEntry(
            message_id=message.id,
            delivered_at="2026-09-27T10:00:00.001Z",
            sender={"kind": "alias", "name": "the-alias"},
        ),
    )

    # The service sees an alias where a name would be, and the message itself is
    # untouched — one message, two views of who sent it.
    assert holdings.mailbox_entries(mailbox)[0].sender["kind"] == "alias"
    assert holdings.message(realm.id, message.id).sender["name"] == "Anna"


def test_an_alias_is_found_from_both_sides_so_delivering_twice_mints_once(
    holdings: Holdings, realm, team
) -> None:
    message_id, service_id, value = new_id(), new_id(), new_id()
    assert holdings.alias_for_delivery(realm.id, message_id, service_id) is None

    holdings.create_alias(
        realm.id,
        Alias(
            value=value,
            created_at="2026-09-27T10:00:00.000Z",
            message_id=message_id,
            service_id=service_id,
            team_id=team.id,
            sender={"kind": "peer", "name": "Anna"},
        ),
    )

    assert holdings.alias_for_delivery(realm.id, message_id, service_id) == value
    back = holdings.alias(realm.id, value)
    assert back is not None
    assert back.sender == {"kind": "peer", "name": "Anna"}


def test_a_file_belongs_to_a_realm_and_keeps_no_name(holdings: Holdings, realm) -> None:
    """The name lives on the envelope; kept here too it would be two names."""
    file_id = new_id()
    stored = holdings.put_file(realm.id, file_id, b"\x00\x01binary\xff")

    assert stored.size == 9
    assert holdings.file_content(realm.id, file_id) == b"\x00\x01binary\xff"
    assert "name" not in stored.to_json()


def test_a_participant_is_a_kind_and_a_name() -> None:
    assert Participant(kind="peer", name="Anna").to_json()


def test_the_notes_are_whatever_was_put_in_them(holdings: Holdings, realm) -> None:
    """Deliberately not ours to shape: what the operator writes comes back out."""
    holdings.set_global_note("# Hinweise\n\nRuf 555.\n")
    holdings.set_realm_note(realm.id, "Nur für dieses Realm.\n")

    assert holdings.global_note() == "# Hinweise\n\nRuf 555.\n"
    assert holdings.realm_note(realm.id) == "Nur für dieses Realm.\n"
    assert holdings.realm_note(new_id()) is None


def test_an_empty_realm_and_an_empty_team_are_legal(holdings: Holdings) -> None:
    """Idle, but allowed — and every operation creates exactly one thing."""
    empty_realm = holdings.create_realm(new_id(), "leer")
    assert holdings.team_ids(empty_realm.id) == []

    empty_team = holdings.create_team(empty_realm.id, new_id(), "still", "")
    assert holdings.member_ids(empty_realm.id, empty_team.id, State.ACTIVE) == []
    assert list(holdings.members(empty_realm.id, empty_team.id)) == []


def test_a_half_written_object_is_invisible_to_every_listing(holdings: Holdings, realm) -> None:
    """What a crash in the middle of a write leaves behind, and why it is harmless.

    A write goes to a temporary file in the target's own directory and is then
    renamed. A crash therefore leaves a stray file, never a half-filled record —
    and every listing here iterates directories, so the stray is not something a
    reader can trip over. It is never cleaned up, because nothing here deletes;
    it costs disk and nothing else.
    """
    leftover = holdings.layout.teams(realm.id) / ".tmp-abcdef.part"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text("half a record", encoding="utf-8")

    assert holdings.team_ids(realm.id) == []
    assert holdings.team_named(realm.id, "whatever") is None


def test_the_reported_delivery_time_is_the_one_the_ordering_uses(
    holdings: Holdings, realm, team
) -> None:
    """One fact, one copy — otherwise a listing can contradict its own order.

    The timestamp lives in the entry's name, because the name is what the ordering
    is made of. Stored in the record as well it would be a second copy, and a
    listing could then hand back an entry dated later than the one above it. Here
    the record is written with one value and the name with another, and the name is
    the one that comes back.
    """
    member = holdings.create_member(
        realm.id, team.id, new_id(), "Otto", token=new_id(), mission="a"
    )
    mailbox = holdings.layout.member_mailbox(realm.id, team.id, member.id) / "inbox"
    message_id = new_id()
    holdings.deliver(
        mailbox,
        MailboxEntry(
            message_id=message_id,
            delivered_at="2026-09-27T12:00:00.000Z",
            sender={"kind": "peer", "name": "Anna"},
        ),
    )
    # Moved in time the way anything here is moved: by renaming.
    entry = next(iter(mailbox.iterdir()))
    entry.rename(mailbox / f"2026-01-01T00:00:00.000Z{ENTRY_SEPARATOR}{message_id}")

    listed = holdings.mailbox_entries(mailbox)

    assert [e.delivered_at for e in listed] == ["2026-01-01T00:00:00.000Z"]


def test_the_separator_occurs_in_neither_half_of_an_entry_name(
    holdings: Holdings, realm, team
) -> None:
    """The property, not the split: a separator in either half makes reading a guess.

    Timestamps carry hyphens, colons and a dot; identifiers are base64url and carry
    hyphens and underscores. This asserts the character is in neither — which is
    the thing that keeps the split exact, and the thing a later change could
    quietly break.
    """
    assert ENTRY_SEPARATOR not in "0123456789-:.TZ"
    assert ENTRY_SEPARATOR not in string.ascii_letters + string.digits + "-_"

    awkward = "a-b_c" + "x" * 38
    holdings.deliver(
        holdings.layout.member_mailbox(realm.id, team.id, "somebody") / "inbox",
        MailboxEntry(
            message_id=awkward,
            delivered_at="2026-09-27T12:00:00.000Z",
            sender={"kind": "peer", "name": "Anna"},
        ),
    )
    listed = holdings.mailbox_entries(
        holdings.layout.member_mailbox(realm.id, team.id, "somebody") / "inbox"
    )

    assert listed[0].delivered_at == "2026-09-27T12:00:00.000Z"
    assert listed[0].message_id == awkward


def test_an_identifier_with_a_hyphen_does_not_confuse_the_split(
    holdings: Holdings, realm, team
) -> None:
    """Both halves carry hyphens of their own; the separator carries none."""
    member = holdings.create_member(
        realm.id, team.id, new_id(), "Otto", token=new_id(), mission="a"
    )
    mailbox = holdings.layout.member_mailbox(realm.id, team.id, member.id) / "inbox"
    awkward = "a-b-c" + "x" * 38
    holdings.deliver(
        mailbox,
        MailboxEntry(
            message_id=awkward,
            delivered_at="2026-09-27T12:00:00.000Z",
            sender={"kind": "peer", "name": "Anna"},
        ),
    )

    listed = holdings.mailbox_entries(mailbox)

    assert listed[0].delivered_at == "2026-09-27T12:00:00.000Z"
    assert listed[0].message_id == awkward
