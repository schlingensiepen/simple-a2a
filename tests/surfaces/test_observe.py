"""The observation surface: it reads everything, changes nothing, and is invisible.

Three promises carry it, and each is checked here rather than intended: an observer
sees the **real** sender even where the recipient was shown an alias; a broadcast
appears once with all its recipients rather than as one entry per recipient; and there
is no route on this surface that changes anything.
"""

from __future__ import annotations

import pytest
from conftest import bearer
from fastapi.testclient import TestClient

from simple_a2a.describe import gate


def watching(admin: TestClient) -> str:
    admin.post("/realms", json={"realm_name": "household"})
    admin.post("/realms/household/teams", json={"team_name": "kitchen", "team_purpose": "We cook."})
    return admin.post("/realms/household/observer-tokens", json={"display_name": "the eye"}).json()[
        "token"
    ]


def member(admin: TestClient, participants: TestClient, name: str) -> dict:
    voucher = admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={
            "member_name": name,
            "member_mission": f"{name} helps.",
            "display_name": f"for {name}",
        },
    ).json()["invitation"]
    return participants.post("/invitations/redeem", json={"invitation": voucher}).json()


# ------------------------------------------------------------------- the cascade


def test_the_seven_token_free_addresses_answer_without_one(observation: TestClient) -> None:
    for address in ("/", "/guide", "/health", "/build", "/openapi.json", "/skill.zip"):
        assert observation.get(address).status_code == 200, address
    for part in ("concepts", "traffic", "contents"):
        assert observation.get(f"/guide/{part}").status_code == 200, part


def test_the_generated_description_passes_the_gate(observation: TestClient) -> None:
    document = observation.get("/openapi.json").json()

    found = gate.check_description(document, gate.Rules(surface="observe"))

    assert found, found.report()


def test_every_rejection_this_surface_can_give_has_a_text() -> None:
    from simple_a2a.observe import texts

    found = gate.check_teaching(texts.build())

    assert found, found.report()


def test_this_surface_only_reads(observation: TestClient) -> None:
    """Checked rather than intended: an observer that could write would be a second
    administrator under another name."""
    document = observation.get("/openapi.json").json()

    for path, verbs in document["paths"].items():
        assert set(verbs) == {"get"}, f"{path} takes {sorted(verbs)}"


def test_without_a_token_it_says_who_issues_one_and_names_no_address(
    observation: TestClient,
) -> None:
    """Here that is an action, not an address: pointing at one would point nowhere."""
    answer = observation.get("/teams")

    assert answer.status_code == 401
    assert answer.json()["type"] == "no-token"
    message = answer.json()["message"]
    assert "set this installation up" in message
    assert "/realms" not in message and "8252" not in message


# ---------------------------------------------------------------- what it sees


def test_the_teams_are_the_way_in(admin: TestClient, observation: TestClient) -> None:
    token = watching(admin)

    listing = observation.get("/teams", headers=bearer(token))

    assert listing.status_code == 200
    assert "kitchen" in listing.text
    assert "/teams/kitchen/traffic" in listing.text


def test_a_team_leads_to_its_purpose_its_members_and_its_traffic(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    token = watching(admin)
    member(admin, participants, "Anna")

    seen = observation.get("/teams/kitchen", headers=bearer(token))

    assert "1 member" in seen.text
    assert observation.get("/teams/kitchen/purpose", headers=bearer(token)).text == "We cook."
    assert "Anna" in observation.get("/teams/kitchen/peers", headers=bearer(token)).text
    assert (
        observation.get("/teams/kitchen/peers/Anna/mission", headers=bearer(token)).text
        == "Anna helps."
    )


def test_an_unknown_team_points_at_the_listing(admin: TestClient, observation: TestClient) -> None:
    token = watching(admin)

    answer = observation.get("/teams/nowhere/traffic", headers=bearer(token))

    assert answer.status_code == 404
    assert "GET /teams" in answer.json()["message"]


# ------------------------------------------------------------------ the traffic


def test_a_broadcast_appears_once_with_all_its_recipients(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """Because the list was resolved when it was sent, not when it is read."""
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    member(admin, participants, "Berta")
    member(admin, participants, "Clara")
    participants.post(
        "/peers/messages",
        json={"subject": "All of you", "body": "."},
        headers=bearer(anna["token"]),
    )

    entries = observation.get("/teams/kitchen/traffic", headers=bearer(token)).json()["entries"]

    assert len(entries) == 1, "once, not one per recipient"
    assert sorted(p["name"] for p in entries[0]["recipients"]) == ["Berta", "Clara"]


def test_the_observer_sees_the_real_sender_where_a_service_was_shown_an_alias(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """The whole purpose of watching: the alias is resolved for them."""
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    weather = participants.post(
        "/invitations/redeem", json={"invitation": voucher, "member_self_image": "x"}
    ).json()
    participants.post(
        "/services/messages",
        json={"recipient": "weather", "subject": "How warm?", "body": "?"},
        headers=bearer(anna["token"]),
    )
    alias = participants.get("/inbox", headers=bearer(weather["token"])).json()["entries"][0][
        "sender_name"
    ]
    participants.post(
        f"/aliases/{alias}/messages",
        json={"subject": "Twelve", "body": "Twelve degrees."},
        headers=bearer(weather["token"]),
    )

    entries = observation.get("/teams/kitchen/traffic", headers=bearer(token)).json()["entries"]

    assert len(entries) == 2
    names = {(entry["sender_kind"], entry["sender_name"]) for entry in entries}
    assert names == {("peer", "Anna"), ("service", "weather")}
    # And the alias appears nowhere at all: not as a sender, not as a recipient.
    assert alias not in str(entries)
    for entry in entries:
        assert entry["sender_kind"] != "alias"
        assert all(person["kind"] != "alias" for person in entry["recipients"])


def test_the_traffic_entry_does_not_repeat_the_team(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """No field carries what is already in the path."""
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    member(admin, participants, "Berta")
    participants.post(
        "/peers/messages", json={"subject": "s", "body": "b"}, headers=bearer(anna["token"])
    )

    entry = observation.get("/teams/kitchen/traffic", headers=bearer(token)).json()["entries"][0]

    assert "team_name" not in entry
    assert "team" not in entry


def test_a_filter_takes_a_kind_and_a_name_together(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    berta = member(admin, participants, "Berta")
    participants.post(
        "/peers/messages",
        json={"recipients": ["Berta"], "subject": "from Anna", "body": "."},
        headers=bearer(anna["token"]),
    )
    participants.post(
        "/peers/messages",
        json={"recipients": ["Anna"], "subject": "from Berta", "body": "."},
        headers=bearer(berta["token"]),
    )

    both = observation.get("/teams/kitchen/traffic", headers=bearer(token)).json()["entries"]
    assert len(both) == 2

    only_anna = observation.get(
        "/teams/kitchen/traffic?sender_kind=peer&sender_name=Anna", headers=bearer(token)
    ).json()["entries"]
    assert [entry["subject"] for entry in only_anna] == ["from Anna"]

    to_anna = observation.get(
        "/teams/kitchen/traffic?recipient_kind=peer&recipient_name=Anna", headers=bearer(token)
    ).json()["entries"]
    assert [entry["subject"] for entry in to_anna] == ["from Berta"]


def test_a_kind_without_a_name_is_invalid_input(admin: TestClient, observation: TestClient) -> None:
    """Rather than a guess: guessing would make the meaning of a name depend on
    another field, which is the thing the pair exists to avoid."""
    token = watching(admin)

    answer = observation.get("/teams/kitchen/traffic?sender_kind=peer", headers=bearer(token))

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"
    assert "together" in answer.json()["message"] or "together" in str(answer.json())


def test_a_name_that_is_not_in_the_team_is_refused_rather_than_answered_with_nothing(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """An empty answer to a mistyped name looks exactly like an empty answer to a
    correct one, and there is no way to tell which you got."""
    token = watching(admin)
    member(admin, participants, "Anna")

    answer = observation.get(
        "/teams/kitchen/traffic?sender_kind=peer&sender_name=Nobody", headers=bearer(token)
    )

    assert answer.status_code == 404
    assert answer.json()["type"] == "unknown-name"


def test_an_alias_cannot_be_filtered_by(admin: TestClient, observation: TestClient) -> None:
    """There is nothing to filter: the observer is shown the real participant."""
    token = watching(admin)

    answer = observation.get(
        "/teams/kitchen/traffic?sender_kind=alias&sender_name=x", headers=bearer(token)
    )

    assert answer.status_code == 400
    assert "peer" in answer.json()["message"]


def test_the_time_filters_include_both_ends(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    member(admin, participants, "Berta")
    sent = participants.post(
        "/peers/messages", json={"subject": "s", "body": "b"}, headers=bearer(anna["token"])
    ).json()
    moment = sent["sent_at"]

    inside = observation.get(
        f"/teams/kitchen/traffic?from={moment}&to={moment}", headers=bearer(token)
    ).json()["entries"]
    after = observation.get(
        "/teams/kitchen/traffic?from=2099-01-01T00:00:00.000Z", headers=bearer(token)
    ).json()["entries"]

    assert len(inside) == 1, "a day means the day"
    assert after == []


@pytest.mark.parametrize("bad", ["yesterday", "2026-09-28", "2026-09-28T09:12:44Z"])
def test_a_timestamp_of_another_shape_is_invalid_input(
    admin: TestClient, observation: TestClient, bad: str
) -> None:
    token = watching(admin)

    answer = observation.get(f"/teams/kitchen/traffic?from={bad}", headers=bearer(token))

    assert answer.status_code == 400
    assert "milliseconds" in answer.json()["message"]


# ------------------------------------------------- from an entry to the content


def test_from_an_entry_to_the_envelope_the_body_and_the_file(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    member(admin, participants, "Berta")
    deposited = participants.post(
        "/files",
        content=b"one,two\n",
        headers={**bearer(anna["token"]), "Content-Type": "text/csv"},
    ).json()
    participants.post(
        "/peers/messages",
        json={
            "subject": "Numbers",
            "body": "Attached.",
            "attachments": [{"name": "numbers.csv", "file_id": deposited["file_id"]}],
        },
        headers=bearer(anna["token"]),
    )

    entry = observation.get("/teams/kitchen/traffic", headers=bearer(token)).json()["entries"][0]
    assert entry["attachment_count"] == 1

    envelope = observation.get(f"/messages/{entry['message_id']}", headers=bearer(token)).json()
    assert envelope["attachments"][0]["name"] == "numbers.csv"
    assert (
        observation.get(f"/messages/{entry['message_id']}/body", headers=bearer(token)).text
        == "Attached."
    )
    fetched = observation.get(f"/files/{deposited['file_id']}/anything.csv", headers=bearer(token))
    assert fetched.content == b"one,two\n"
    assert fetched.headers["content-type"].startswith("text/csv")


def test_a_message_from_another_installation_is_an_unknown_identifier(
    admin: TestClient, observation: TestClient
) -> None:
    token = watching(admin)

    answer = observation.get("/messages/" + "z" * 43, headers=bearer(token))

    assert answer.status_code == 404
    assert answer.json()["type"] == "unknown-identifier"


def test_nothing_on_this_surface_names_another(observation: TestClient) -> None:
    texts = [observation.get(address).text for address in ("/", "/guide", "/openapi.json")]
    for part in ("concepts", "traffic", "contents"):
        texts.append(observation.get(f"/guide/{part}").text)

    for text in texts:
        for giveaway in ("8251", "8252", "/inbox", "/outbox", "/realms", "/observer-tokens"):
            assert giveaway not in text, giveaway


# ------------------------------------------------------------- a wrong verb, truly


def test_a_wrong_verb_at_an_address_that_only_looks_like_one_is_not_a_wrong_verb(
    admin: TestClient, participants: TestClient, observation: TestClient
) -> None:
    """The case an agent met: a participant address tried here.

    `POST /services/messages` is how a participant writes to a central service. Here
    it has the shape of `/services/{name}` with `messages` as a service nobody has,
    and the answer used to be "that address exists, but not with POST" — which sent
    the agent looking for the right verb at an address that was never there.
    """
    token = watching(admin)
    anna = member(admin, participants, "Anna")
    voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    participants.post(
        "/invitations/redeem", json={"invitation": voucher, "member_self_image": "Forecasts."}
    )

    nowhere = observation.post("/services/messages", json={}, headers=bearer(token))
    somewhere = observation.post("/services/weather", json={}, headers=bearer(token))
    unannounced = observation.post("/services/messages", json={})

    # No such service: said as what it is.
    assert nowhere.status_code == 404
    assert nowhere.json()["type"] == "unknown-name"
    # A service that exists: the verb really was wrong, and the shape is named.
    assert somewhere.status_code == 405
    assert somewhere.json()["type"] == "wrong-verb"
    assert "/services/{name}" in somewhere.json()["message"]
    # Without a token nothing here can be read, so nothing is said about what exists.
    assert unannounced.status_code == 401
    assert unannounced.json()["type"] == "no-token"


def test_a_wrong_verb_at_a_fixed_address_stays_a_wrong_verb(observation: TestClient) -> None:
    """No placeholder, nothing to look up: the address exists and the verb is wrong."""
    answer = observation.post("/teams", json={})

    assert answer.status_code == 405
    assert answer.json()["type"] == "wrong-verb"
