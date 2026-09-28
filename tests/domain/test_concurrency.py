"""Many writers on one data directory at once, in separate processes.

The holdings promise correctness without a lock: a name is claimed by exclusive
creation, a state changes by a rename, and a delivery is a new directory under
a name nobody else can produce. That promise is about *simultaneous* writers,
and agents at conversational speed almost never are simultaneous — so it is
tested here, with processes lined up on a barrier and released together, rather
than hoped for from a test with agents in it.

Processes rather than threads, because the claim is about the filesystem as the
referee between independent writers, and threads in one interpreter share more
than two service processes on one directory would.

Every race is run for several rounds: a window that is a few microseconds wide
is not hit by one attempt, and a test that only sometimes looks is worse than
none.
"""

from __future__ import annotations

import multiprocessing
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import ADMIN_SECRET, Member, World

from simple_a2a.core import config
from simple_a2a.domain import access, messages, refusals
from simple_a2a.domain.callers import Peer
from simple_a2a.domain.context import Context
from simple_a2a.store.holdings import Holdings
from simple_a2a.store.layout import Layout, State
from simple_a2a.store.records import token_hash

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="needs fork and a local POSIX filesystem"
)

WRITERS = 8
ROUNDS = 25
MESSAGES_EACH = 15

_fork = multiprocessing.get_context("fork")


def _context_on(data_dir: str) -> Context:
    """A context of its own, as a second service process would have."""
    return Context(
        holdings=Holdings(Layout(root=Path(data_dir))),
        config=config.load({config.DATA_DIR: data_dir}),
        admin_secret=ADMIN_SECRET,
    )


def _outcome(call: Callable[[], object]) -> str:
    """What happened, as a word: the refusal's class name, or "ok".

    Anything that is not a refusal is reported with its type, because that is
    the finding — a writer that loses a race has to be told so in the catalogue's
    words, not with a crash.
    """
    try:
        call()
    except refusals.Refused as refused:
        return type(refused).__name__
    except Exception as crash:  # noqa: BLE001 — the crash *is* the result here
        return f"crash:{type(crash).__name__}:{crash}"
    return "ok"


def _race(work: Callable[[int], str]) -> list[str]:
    """Release WRITERS processes at the same instant and collect what each saw."""
    barrier = _fork.Barrier(WRITERS)
    results = _fork.Queue()

    def run(index: int) -> None:
        barrier.wait()
        results.put(work(index))

    processes = [_fork.Process(target=run, args=(i,)) for i in range(WRITERS)]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(timeout=60)
    return outcomes


def test_simultaneous_claims_on_one_team_name_have_exactly_one_winner(
    context: Context, world: World
) -> None:
    data_dir = str(context.holdings.layout.root)
    for round_ in range(ROUNDS):
        name = f"lager-{round_}"

        def claim(_: int, name: str = name) -> str:
            return _outcome(
                lambda: access.create_team(_context_on(data_dir), world.realm_id, name, "Vorrat.")
            )

        outcomes = _race(claim)
        assert outcomes.count("ok") == 1, outcomes
        assert set(outcomes) - {"ok"} == {"NameTaken"}, outcomes


def test_one_voucher_redeemed_simultaneously_makes_exactly_one_identity(
    context: Context, world: World
) -> None:
    data_dir = str(context.holdings.layout.root)
    for round_ in range(ROUNDS):
        name = f"Gast {round_}"
        voucher = access.obtain_member_invitation(
            context,
            realm_id=world.realm_id,
            team_id=world.team_id,
            member_name=name,
            mission="Kommt vorbei.",
            display_name=f"Zettel {round_}",
            issued_by_kind="operator",
            issued_by_name="operator",
            grants_realm_master=False,
        )

        def redeem(_: int, voucher: str = voucher) -> str:
            return _outcome(lambda: access.redeem(_context_on(data_dir), voucher))

        outcomes = _race(redeem)
        assert outcomes.count("ok") == 1, outcomes
        assert set(outcomes) - {"ok"} == {"InvitationUsed"}, outcomes

        # And the holdings say the same thing afterwards: consumed, once, and not
        # open as well. A voucher that shows as open after it was spent would be
        # offered again by every listing.
        located = context.holdings.invitation_for(world.realm_id, voucher)
        assert located is not None and located.state is State.CONSUMED
        digest = token_hash(voucher)
        digest_dirs = [
            state
            for state in State
            if context.holdings.layout.invitation(world.realm_id, digest, state).is_dir()
        ]
        assert digest_dirs == [State.CONSUMED], digest_dirs
        assert context.holdings.member_named(world.realm_id, world.team_id, name) is not None


def test_simultaneous_senders_lose_nothing_and_double_nothing(
    context: Context, world: World, invite: Callable[..., Member]
) -> None:
    team = [world.anna, world.berta] + [
        invite(world.realm_id, world.team_id, f"Helfer {i}") for i in range(WRITERS - 2)
    ]
    names = [member.caller.name for member in team]
    tokens = [member.token for member in team]
    data_dir = str(context.holdings.layout.root)

    def send(index: int) -> str:
        own = _context_on(data_dir)
        sender = access.authenticate(own, tokens[index])
        assert isinstance(sender, Peer)
        others = [name for name in names if name != sender.name]
        sent: list[str] = []
        for number in range(MESSAGES_EACH):
            try:
                result = messages.send_to_peers(
                    own,
                    sender,
                    recipients=others,
                    subject=f"{sender.name} Nr. {number}",
                    body="Gleichzeitig.",
                )
            except Exception as crash:  # noqa: BLE001
                return f"crash:{type(crash).__name__}:{crash}"
            sent.append(result.message_id)
        return ",".join(sent)

    outcomes = _race(send)
    assert not [o for o in outcomes if o.startswith("crash:")], outcomes
    sent_ids = [message_id for outcome in outcomes for message_id in outcome.split(",")]
    assert len(sent_ids) == WRITERS * MESSAGES_EACH
    assert len(set(sent_ids)) == len(sent_ids), "a message id was produced twice"

    for member in team:
        caller = access.authenticate(context, member.token)
        assert isinstance(caller, Peer)
        inbox = context.holdings.mailbox_entries(messages.mailbox_of(context, caller, "inbox"))
        received = [entry.message_id for entry in inbox]
        # Everybody else sent MESSAGES_EACH to everybody else: nothing lost, nothing
        # twice, nothing from oneself.
        assert len(received) == (WRITERS - 1) * MESSAGES_EACH, member.caller.name
        assert len(set(received)) == len(received), member.caller.name
        assert set(received) <= set(sent_ids)
        outbox = context.holdings.mailbox_entries(messages.mailbox_of(context, caller, "outbox"))
        assert len(outbox) == MESSAGES_EACH, member.caller.name


def test_a_revocation_racing_writes_into_the_member_leaves_one_member_in_one_state(
    context: Context, world: World, invite: Callable[..., Member]
) -> None:
    """Revoke while others write into the member: its self-image, its right.

    The writes used to create the member's directory again behind the move, so
    the member stood in "active" and "revoked" at once — and a second revocation
    then failed on the leftover. Half the writers revoke, half write; afterwards
    there is one member, revoked, with one first timestamp that everybody who
    revoked was told.
    """
    data_dir = str(context.holdings.layout.root)
    for round_ in range(ROUNDS):
        name = f"Wackel {round_}"
        target = invite(world.realm_id, world.team_id, name)
        member_id = target.caller.member_id

        def work(index: int, member_id: str = member_id, name: str = name) -> str:
            own = _context_on(data_dir)
            holdings = own.holdings
            try:
                if index % 2 == 0:
                    revocation = access.revoke_member_token(
                        own, world.realm_id, world.team_id, name
                    )
                    return f"revoked:{revocation.revoked_at}"
                if index % 4 == 1:
                    holdings.set_member_self_image(
                        world.realm_id, world.team_id, member_id, State.ACTIVE, "Ich wackle."
                    )
                else:
                    holdings.set_realm_master(world.realm_id, world.team_id, member_id, True)
            except Exception as crash:  # noqa: BLE001
                return f"crash:{type(crash).__name__}:{crash}"
            return "ok"

        outcomes = _race(work)
        assert not [o for o in outcomes if o.startswith("crash:")], outcomes
        stamps = {o.split(":", 1)[1] for o in outcomes if o.startswith("revoked:")}
        assert len(stamps) == 1 and "None" not in stamps, outcomes

        layout = context.holdings.layout
        states = [
            state
            for state in (State.ACTIVE, State.REVOKED)
            if layout.member(world.realm_id, world.team_id, member_id, state).is_dir()
        ]
        assert states == [State.REVOKED], states
        located = context.holdings.member(world.realm_id, world.team_id, member_id)
        assert located is not None and located.record.revoked_at in stamps
