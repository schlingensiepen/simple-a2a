"""Sending, delivering and reading — the promises of §4, one test each.

These are the ones where a shape carries a rule instead of a rule carrying it,
and each of them has a way of quietly not holding.
"""

from __future__ import annotations

import pytest
from conftest import World

from simple_a2a.domain import access, messages, refusals
from simple_a2a.domain.callers import Peer
from simple_a2a.domain.context import Context

INBOX, OUTBOX = messages.INBOX, messages.OUTBOX


def send(context: Context, sender: Peer, **kwargs) -> messages.Sent:
    kwargs.setdefault("recipients", [])
    kwargs.setdefault("subject", "Betreff")
    kwargs.setdefault("body", "Inhalt.")
    return messages.send_to_peers(context, sender, **kwargs)


# ------------------------------------------------------------------- resolution


def test_an_empty_list_means_everybody_else_and_is_resolved_when_sent(
    context: Context, world: World, invite
) -> None:
    """The envelope names the actual recipients, so a broadcast stays traceable."""
    sent = send(context, world.anna.caller)

    assert [p.name for p in sent.recipients] == ["Berta"]
    assert sent.warnings == []

    # Somebody joining afterwards is not retroactively a recipient.
    invite(world.realm_id, world.team_id, "Clara")
    again = messages.envelope(context, world.anna.caller, sent.message_id)
    assert [p.name for p in again.recipients] == ["Berta"]


def test_the_sender_is_left_out_whether_named_or_not(context: Context, world: World) -> None:
    """Naming oneself is allowed and has no effect: own messages are in the outbox."""
    named = send(context, world.anna.caller, recipients=["Anna", "Berta"])
    only_self = send(context, world.anna.caller, recipients=["Anna"])

    assert [p.name for p in named.recipients] == ["Berta"]
    assert only_self.recipients == []
    assert only_self.warnings == [refusals.NO_RECIPIENT]


def test_alone_in_the_team_the_message_is_accepted_and_warns(context: Context) -> None:
    """The sender did everything they could, so it is not a refusal."""
    realm = access.create_realm(context, "haus")
    realm_id = context.holdings.realm_named(realm).id
    access.create_team(context, realm_id, "allein", "")
    team_id = context.holdings.team_named(realm_id, "allein").id
    voucher = access.obtain_member_invitation(
        context,
        realm_id=realm_id,
        team_id=team_id,
        member_name="Einzel",
        mission="allein",
        display_name="Zettel",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    caller = access.authenticate(context, access.redeem(context, voucher).token)

    sent = send(context, caller)

    assert sent.recipients == []
    assert sent.warnings == [refusals.NO_RECIPIENT]
    assert len(messages.list_mailbox(context, caller, OUTBOX, offset=0, limit=25)) == 1


def test_an_unknown_recipient_is_refused_by_name(context: Context, world: World) -> None:
    with pytest.raises(refusals.UnknownName) as raised:
        send(context, world.anna.caller, recipients=["Niemand"])
    assert raised.value.name == "Niemand"


def test_delivery_to_a_revoked_identity_succeeds(context: Context, world: World) -> None:
    """Nothing is deleted, the mailbox keeps collecting, and there is no warning."""
    access.revoke_member_token(context, world.realm_id, world.team_id, "Berta")

    sent = send(context, world.anna.caller, recipients=["Berta"])

    assert [p.name for p in sent.recipients] == ["Berta"]
    assert sent.warnings == []
    assert messages.list_mailbox(context, world.berta.caller, INBOX, offset=0, limit=25)


def test_a_revoked_identity_counts_towards_an_empty_list(context: Context, world: World) -> None:
    access.revoke_member_token(context, world.realm_id, world.team_id, "Berta")

    assert [p.name for p in send(context, world.anna.caller).recipients] == ["Berta"]


# ------------------------------------------------------------------ the mailbox


def test_an_own_message_is_in_the_outbox_and_not_in_the_inbox(
    context: Context, world: World
) -> None:
    send(context, world.anna.caller)

    assert messages.list_mailbox(context, world.anna.caller, OUTBOX, offset=0, limit=25)
    assert messages.list_mailbox(context, world.anna.caller, INBOX, offset=0, limit=25) == []
    assert messages.list_mailbox(context, world.berta.caller, INBOX, offset=0, limit=25)


def test_the_window_is_newest_first(context: Context, world: World) -> None:
    """Ordered by the timestamp, and equal timestamps have no order.

    That last part is not a gap to be fixed: the specification says it outright.
    Five messages sent inside one millisecond share a timestamp, so this checks
    what is actually promised — that a later timestamp comes first — rather than
    the send order, which nothing guarantees. The order within one millisecond is
    arbitrary but *stable*, which is what a window over a list needs.
    """
    older = send(context, world.anna.caller, subject="alt").message_id
    _freeze(context, world, older, "2026-01-01T00:00:00.000Z")
    newer = send(context, world.anna.caller, subject="neu").message_id

    seen = messages.list_mailbox(context, world.berta.caller, INBOX, offset=0, limit=25)

    assert [entry.message_id for entry in seen] == [newer, older]
    assert (
        messages.list_mailbox(context, world.berta.caller, INBOX, offset=0, limit=1)[0].message_id
        == newer
    )


def test_a_window_over_the_whole_list_returns_every_message_once(
    context: Context, world: World
) -> None:
    """Even where timestamps collide: the order is arbitrary there, not unstable."""
    ids = {send(context, world.anna.caller, subject=f"Nummer {n}").message_id for n in range(7)}

    paged = []
    for offset in range(0, 9, 2):
        paged += [
            entry.message_id
            for entry in messages.list_mailbox(
                context, world.berta.caller, INBOX, offset=offset, limit=2
            )
        ]

    assert sorted(paged) == sorted(ids)
    assert len(paged) == len(set(paged))


def _freeze(context: Context, world: World, message_id: str, stamp: str) -> None:
    """Move one delivery back in time, because a test cannot wait a millisecond.

    Reaches into the holdings on purpose: the point is to produce two *different*
    timestamps, which is the only thing the ordering promises anything about.
    """
    mailbox = (
        context.holdings.layout.member_mailbox(
            world.realm_id, world.team_id, world.berta.caller.member_id
        )
        / INBOX
    )
    for entry in mailbox.iterdir():
        if entry.name.endswith(message_id):
            entry.rename(mailbox / f"{stamp}-{message_id}")


def test_the_window_moves_with_offset(context: Context, world: World) -> None:
    for n in range(5):
        send(context, world.anna.caller, subject=f"Nummer {n}")

    first = messages.list_mailbox(context, world.berta.caller, INBOX, offset=0, limit=2)
    second = messages.list_mailbox(context, world.berta.caller, INBOX, offset=2, limit=2)

    assert {e.message_id for e in first}.isdisjoint({e.message_id for e in second})


# -------------------------------------------------------------------- the alias


def test_a_delivery_to_a_service_mints_an_alias_in_the_sender_s_place(
    context: Context, world: World, register
) -> None:
    """The service sees `alias` and a name it was given; it never learns a name."""
    wetter = register(world.anna.caller, "Wetter")

    sent = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="Wie warm?"
    )

    inbox = messages.list_mailbox(context, wetter.caller, INBOX, offset=0, limit=25)
    assert len(inbox) == 1
    assert inbox[0].sender["kind"] == "alias"
    assert inbox[0].sender["name"] != "Anna"
    assert [p.name for p in sent.recipients] == ["Wetter"]
    assert sent.recipients[0].kind == "service"


def test_a_service_reads_its_own_message_as_coming_from_the_alias(
    context: Context, world: World, register
) -> None:
    """Its own delivery, so the envelope it settled with — never a name."""
    wetter = register(world.anna.caller, "Wetter")
    sent = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="Wie warm?"
    )

    seen = messages.envelope(context, wetter.caller, sent.message_id)

    assert seen.sender.kind == "alias"
    assert seen.sender.name != "Anna"


def test_the_sender_reads_their_own_message_as_their_own(
    context: Context, world: World, register
) -> None:
    register(world.anna.caller, "Wetter")
    sent = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="Wie warm?"
    )

    seen = messages.envelope(context, world.anna.caller, sent.message_id)

    assert (seen.sender.kind, seen.sender.name) == ("peer", "Anna")


def test_whoever_was_not_a_recipient_sees_the_original_sender(
    context: Context, world: World
) -> None:
    """A passed-on identifier: the capability approach, and §4.2 says so outright."""
    sent = messages.send_to_peers(
        context, world.anna.caller, recipients=["Berta"], subject="B", body="nur an Berta"
    )
    clara = access.authenticate(context, _fresh_peer(context, world))

    seen = messages.envelope(context, clara, sent.message_id)

    assert (seen.sender.kind, seen.sender.name) == ("peer", "Anna")


def test_a_service_answers_by_sending_to_the_alias(
    context: Context, world: World, register
) -> None:
    """And the member sees an ordinary message from a name they can address."""
    wetter = register(world.anna.caller, "Wetter")
    asked = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="Wie warm?"
    )
    alias = messages.list_mailbox(context, wetter.caller, INBOX, offset=0, limit=1)[0].sender[
        "name"
    ]

    answer = messages.send_to_alias(
        context, wetter.caller, alias=alias, subject="Antwort", body="Zwölf Grad."
    )

    # The service is shown the alias it answered, never the person — in this
    # response and in its own outbox. A name here would break the promise at the
    # first follow-up step.
    assert [(p.kind, p.name) for p in answer.recipients] == [("alias", alias)]
    outbox = messages.list_mailbox(context, wetter.caller, OUTBOX, offset=0, limit=25)
    assert outbox[0].recipients == [{"kind": "alias", "name": alias}]
    assert messages.envelope(context, wetter.caller, answer.message_id).recipients[0].name == alias

    inbox = messages.list_mailbox(context, world.anna.caller, INBOX, offset=0, limit=25)
    assert inbox[0].sender == {"kind": "service", "name": "Wetter"}
    # The reference back is set by the service itself, to the message the alias
    # belongs to: a service answers, it does not start.
    assert (
        messages.envelope(context, world.anna.caller, answer.message_id).in_reply_to
        == asked.message_id
    )


def test_the_same_delivery_gets_one_alias_and_a_second_delivery_another(
    context: Context, world: World, register
) -> None:
    """Bound to one message and one service — so two questions are not one caller."""
    wetter = register(world.anna.caller, "Wetter")
    first = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Eins", body="a"
    )
    second = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Zwei", body="b"
    )

    seen = messages.list_mailbox(context, wetter.caller, INBOX, offset=0, limit=25)
    aliases = {entry.message_id: entry.sender["name"] for entry in seen}

    assert aliases[first.message_id] != aliases[second.message_id]


def test_an_alias_of_somebody_else_is_an_unknown_identifier(
    context: Context, world: World, register
) -> None:
    """A service cannot use an alias that was not minted towards it."""
    wetter = register(world.anna.caller, "Wetter")
    uhr = register(world.anna.caller, "Uhr")
    messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="?"
    )
    alias = messages.list_mailbox(context, wetter.caller, INBOX, offset=0, limit=1)[0].sender[
        "name"
    ]

    with pytest.raises(refusals.UnknownIdentifier):
        messages.send_to_alias(context, uhr.caller, alias=alias, subject="A", body="b")


def test_an_unknown_alias_is_refused_like_any_unknown_identifier(
    context: Context, world: World, register
) -> None:
    wetter = register(world.anna.caller, "Wetter")

    with pytest.raises(refusals.UnknownIdentifier):
        messages.send_to_alias(context, wetter.caller, alias="x" * 43, subject="A", body="b")


def test_no_alias_points_at_a_service_and_none_at_one_s_own_message(
    context: Context, world: World, register
) -> None:
    """Aliases only come from delivering to a service, and only a member delivers."""
    register(world.anna.caller, "Wetter")
    sent = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="Frage", body="?"
    )

    # Nothing in the sender's own outbox carries an alias, so there is nothing for
    # a member to answer to — they send to a name and set in_reply_to instead.
    outbox = messages.list_mailbox(context, world.anna.caller, OUTBOX, offset=0, limit=25)
    assert all(entry.sender["kind"] != "alias" for entry in outbox)
    assert messages.envelope(context, world.anna.caller, sent.message_id).sender.kind == "peer"


def _fresh_peer(context: Context, world: World) -> str:
    voucher = access.obtain_member_invitation(
        context,
        realm_id=world.realm_id,
        team_id=world.team_id,
        member_name="Clara",
        mission="c",
        display_name="Zettel Clara",
        issued_by_kind="operator",
        issued_by_name="operator",
        grants_realm_master=True,
    )
    return access.redeem(context, voucher).token


# --------------------------------------------------------------- the attachments


def test_an_attachment_is_a_file_or_a_reference_and_never_both(
    context: Context, world: World
) -> None:
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"inhalt")
    other = send(context, world.anna.caller).message_id

    with pytest.raises(refusals.InvalidInput) as neither:
        send(context, world.anna.caller, attachments=[{"name": "a"}])
    assert "exactly one" in neither.value.reason

    with pytest.raises(refusals.InvalidInput):
        send(
            context,
            world.anna.caller,
            attachments=[{"name": "a", "file_id": file_id, "message_id": other}],
        )


def test_a_size_that_was_sent_in_is_invalid_input(context: Context, world: World) -> None:
    """Output only: for a file the service knows the bytes, for a reference the
    total of the referenced message, and a caller can know neither reliably."""
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"inhalt")

    with pytest.raises(refusals.InvalidInput) as raised:
        send(
            context,
            world.anna.caller,
            attachments=[{"name": "a.txt", "file_id": file_id, "size": 6}],
        )

    assert raised.value.field == "attachments.size"


def test_a_reference_counts_nothing_towards_the_total(context: Context, world: World) -> None:
    """Otherwise the calculation would be recursive: a referenced message can
    carry references of its own."""
    file_id, size = messages.deposit_file(context, world.anna.caller, b"x" * 100)
    referenced = send(context, world.anna.caller, body="lang" * 50).message_id

    sent = send(
        context,
        world.anna.caller,
        body="kurz",
        attachments=[
            {"name": "datei.txt", "file_id": file_id},
            {"name": "Voriges", "message_id": referenced},
        ],
    )
    seen = messages.envelope(context, world.berta.caller, sent.message_id)

    assert seen.body_size == len("kurz")
    assert seen.total_size == len("kurz") + size
    # But each entry names its own size, so an agent can judge before following.
    sizes = {entry["name"]: entry["size"] for entry in seen.attachments}
    assert sizes["datei.txt"] == size
    assert sizes["Voriges"] == messages.envelope(context, world.berta.caller, referenced).total_size


def test_the_names_of_one_list_are_unique(context: Context, world: World) -> None:
    """Otherwise a reference from the body is ambiguous, and for files the name
    decides the fetch path."""
    first, _ = messages.deposit_file(context, world.anna.caller, b"eins")
    second, _ = messages.deposit_file(context, world.anna.caller, b"zwei")

    with pytest.raises(refusals.InvalidInput) as raised:
        send(
            context,
            world.anna.caller,
            attachments=[{"name": "A", "file_id": first}, {"name": "a", "file_id": second}],
        )

    assert "twice" in raised.value.reason


@pytest.mark.parametrize("name", ["line\nbreak", "tab\there", "nul\0byte", ".", "..", "dir/"])
def test_an_attachment_name_that_is_no_name_is_refused(
    context: Context, world: World, name: str
) -> None:
    """Control characters are a mistake the caller has to see, so they are refused.

    So is anything of which no name is left once the path is dropped.
    """
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"inhalt")

    with pytest.raises(refusals.InvalidInput) as raised:
        send(context, world.anna.caller, attachments=[{"name": name, "file_id": file_id}])

    assert raised.value.field == "attachments.name"


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("reports/2026/zahlen.csv", "zahlen.csv"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\jemand\\brief.txt", "brief.txt"),
        ("/absolut/pfad.md", "pfad.md"),
        ("schlicht.txt", "schlicht.txt"),
    ],
)
def test_a_directory_part_is_dropped_rather_than_resolved(
    context: Context, world: World, given: str, kept: str
) -> None:
    """Two treatments, and the specification names them with two different verbs.

    Control characters are *refused*; directory parts are *discarded* rather than
    resolved. So a caller who attaches what their own filesystem calls the file
    gets a usable attachment instead of a rejection, and nothing that looks like a
    path reaches a response header or a fetch address.
    """
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"inhalt")

    sent = send(context, world.anna.caller, attachments=[{"name": given, "file_id": file_id}])

    seen = messages.envelope(context, world.berta.caller, sent.message_id)
    assert [entry["name"] for entry in seen.attachments] == [kept]


def test_more_than_sixty_four_entries_are_too_large(context: Context, world: World) -> None:
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"inhalt")

    with pytest.raises(refusals.TooLarge) as raised:
        send(
            context,
            world.anna.caller,
            attachments=[{"name": f"nr {n}", "file_id": file_id} for n in range(65)],
        )

    assert raised.value.limit == 64


def test_an_attachment_in_another_realm_is_an_unknown_identifier(
    context: Context, world: World, invite
) -> None:
    """The realm is the outer boundary of every identifier, and a reach across it
    looks exactly like a reach for something that does not exist."""
    other_realm = access.create_realm(context, "keller")
    other_id = context.holdings.realm_named(other_realm).id
    access.create_team(context, other_id, "kalt", "")
    other_team = context.holdings.team_named(other_id, "kalt").id
    stranger = invite(other_id, other_team, "Fremd")
    elsewhere, _ = messages.deposit_file(context, stranger.caller, b"woanders")

    with pytest.raises(refusals.UnknownIdentifier):
        send(context, world.anna.caller, attachments=[{"name": "a", "file_id": elsewhere}])

    with pytest.raises(refusals.UnknownIdentifier):
        messages.fetch_file(context, world.anna.caller, elsewhere)


# ---------------------------------------------------------------- text or file


def test_a_body_is_a_text_or_a_reference_and_exactly_one(context: Context, world: World) -> None:
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"Aus der Datei.")

    with pytest.raises(refusals.InvalidInput):
        messages.send_to_peers(context, world.anna.caller, recipients=[], subject="s")
    with pytest.raises(refusals.InvalidInput):
        messages.send_to_peers(
            context, world.anna.caller, recipients=[], subject="s", body="x", body_file_id=file_id
        )

    sent = messages.send_to_peers(
        context, world.anna.caller, recipients=[], subject="s", body_file_id=file_id
    )
    assert messages.body_of(context, world.berta.caller, sent.message_id) == "Aus der Datei."


def test_a_referenced_body_is_taken_over_and_the_file_stays(context: Context, world: World) -> None:
    """The message is complete afterwards; the file is not used up and keeps its
    identifier."""
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"Text.")
    sent = messages.send_to_peers(
        context, world.anna.caller, recipients=[], subject="s", body_file_id=file_id
    )

    assert messages.fetch_file(context, world.anna.caller, file_id) == b"Text."
    assert messages.body_of(context, world.berta.caller, sent.message_id) == "Text."


def test_a_referenced_body_is_measured_against_the_body_limit(
    context: Context, world: World
) -> None:
    """The limit belongs to the parameter, not to the file: the text has become a
    body."""
    too_much = b"x" * (context.config.body_max_bytes + 1)
    file_id, _ = messages.deposit_file(context, world.anna.caller, too_much)

    with pytest.raises(refusals.TooLarge) as raised:
        messages.send_to_peers(
            context, world.anna.caller, recipients=[], subject="s", body_file_id=file_id
        )

    assert raised.value.field == "body"


def test_a_referenced_body_that_is_not_utf_8_is_invalid_input(
    context: Context, world: World
) -> None:
    file_id, _ = messages.deposit_file(context, world.anna.caller, b"\xff\xfe nicht utf-8")

    with pytest.raises(refusals.InvalidInput) as raised:
        messages.send_to_peers(
            context, world.anna.caller, recipients=[], subject="s", body_file_id=file_id
        )

    assert raised.value.field == "body_file_id"


def test_the_body_comes_back_exactly_as_it_went_in(context: Context, world: World) -> None:
    """The service has never looked at it, and never normalises it."""
    awkward = 'Zeile eins\r\n\n# Titel\t\\ "zwei" \N{SNOWMAN}\n'
    sent = send(context, world.anna.caller, body=awkward)

    assert messages.body_of(context, world.berta.caller, sent.message_id) == awkward


def test_a_subject_takes_no_reference_and_has_its_own_limit(context: Context, world: World) -> None:
    with pytest.raises(refusals.TooLarge) as raised:
        send(context, world.anna.caller, subject="x" * 257)

    assert raised.value.limit == 256


# ------------------------------------------------------------------ observation


def test_an_observer_sees_the_traffic_of_a_team_with_the_true_sender(
    context: Context, world: World, register
) -> None:
    """Which is the point of watching: no delivery of their own, so no alias."""
    register(world.anna.caller, "Wetter")
    to_peer = send(context, world.anna.caller, subject="an Berta")
    to_service = messages.send_to_service(
        context, world.anna.caller, recipient="Wetter", subject="an Wetter", body="?"
    )
    _, token = access.issue_observer_token(context, world.realm_id, "Auge")
    watcher = access.authenticate(context, token)

    seen = messages.team_traffic(context, watcher, world.team_id, offset=0, limit=25)

    assert {e.message_id for e in seen} == {to_peer.message_id, to_service.message_id}
    assert all(e.sender.name == "Anna" for e in seen)
    assert all(e.sender.kind == "peer" for e in seen)


def test_an_observer_sees_nothing_of_another_team(context: Context, world: World, invite) -> None:
    other = access.create_team(context, world.realm_id, "bad", "Wir waschen.")
    other_id = context.holdings.team_named(world.realm_id, other).id
    invite(world.realm_id, other_id, "Clara")
    send(context, world.anna.caller, subject="in der Küche")
    _, token = access.issue_observer_token(context, world.realm_id, "Auge")
    watcher = access.authenticate(context, token)

    assert messages.team_traffic(context, watcher, other_id, offset=0, limit=25) == []
    assert messages.team_traffic(context, watcher, world.team_id, offset=0, limit=25)
