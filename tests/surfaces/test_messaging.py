"""The participant surface over HTTP, walked the way an arriving agent walks it.

The long test at the top is the one that matters: an operator sets a team up, two
agents redeem their invitations and talk, a central service is registered and
answers along its alias. It is the shape of the whole service in one pass, and every
promise that only shows up in combination shows up here.
"""

from __future__ import annotations

import pytest
from conftest import bearer
from fastapi.testclient import TestClient

from simple_a2a.describe import gate

# --------------------------------------------------------------------- setting up


def a_team(admin: TestClient) -> None:
    admin.post("/realms", json={"realm_name": "household"})
    admin.post("/realms/household/teams", json={"team_name": "kitchen", "team_purpose": "We cook."})


def invited(admin: TestClient, name: str) -> str:
    return admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={
            "member_name": name,
            "member_mission": f"{name} helps.",
            "display_name": f"for {name}",
        },
    ).json()["invitation"]


def joined(admin: TestClient, participants: TestClient, name: str) -> str:
    voucher = invited(admin, name)
    return participants.post("/invitations/redeem", json={"invitation": voucher}).json()["token"]


# ------------------------------------------------------------------- the whole way


def test_the_whole_way_from_an_invitation_to_an_answered_service(
    admin: TestClient, participants: TestClient
) -> None:
    """One pass through everything, in the order somebody actually does it."""
    a_team(admin)

    # Anna arrives with nothing but an invitation, and the redemption is the one call
    # that needs no standing token.
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    assert anna["kind"] == "peer"
    assert anna["name"] == "Anna"
    assert anna["team_name"] == "kitchen"
    assert anna["is_realm_master"] is True, "the operator obtained it, so it grants the right"
    # And nothing in that answer names the realm: for her it is the universe.
    assert "household" not in str(anna)

    # Her first call is her team, and it tells her where to look next.
    overview = participants.get("/team", headers=bearer(anna["token"]))
    assert overview.status_code == 200
    assert "kitchen" in overview.text
    assert "GET /peers" in overview.text

    # Alone, a broadcast is accepted and says it reached nobody.
    alone = participants.post(
        "/peers/messages",
        json={"subject": "Anybody?", "body": "."},
        headers=bearer(anna["token"]),
    ).json()
    assert alone["recipients"] == []
    assert alone["warnings"][0]["code"] == "no-recipient"
    assert "outbox" in alone["warnings"][0]["message"]

    # Anna invites Berta herself — anybody in a team may — and hers does not grant
    # the right.
    voucher = participants.post(
        "/invitations/peer",
        json={
            "member_name": "Berta",
            "member_mission": "Berta shops.",
            "display_name": "for Berta",
        },
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    berta = participants.post("/invitations/redeem", json={"invitation": voucher}).json()
    assert berta["is_realm_master"] is False

    # Now the team has two, and each sees the other's two texts.
    listing = participants.get("/peers", headers=bearer(berta["token"]))
    assert "Anna" in listing.text
    assert "realm master" in listing.text
    assert "Berta" not in listing.text, "a listing of the others does not include the reader"
    assert (
        participants.get("/peers/Anna/mission", headers=bearer(berta["token"])).text
        == "Anna helps."
    )

    # Berta writes what she actually does, and Anna can read it.
    participants.put("/me/self", content=b"I keep the list.", headers=bearer(berta["token"]))
    assert (
        participants.get("/peers/Berta/self", headers=bearer(anna["token"])).text
        == "I keep the list."
    )

    # An empty recipient list now resolves to the other one.
    sent = participants.post(
        "/peers/messages",
        json={"subject": "Yeast", "body": "We are out of yeast."},
        headers=bearer(anna["token"]),
    ).json()
    assert [p["name"] for p in sent["recipients"]] == ["Berta"]
    assert sent["warnings"] == []

    # Berta finds it in her inbox, with the envelope and not the body.
    inbox = participants.get("/inbox", headers=bearer(berta["token"])).json()["entries"]
    assert len(inbox) == 1
    entry = inbox[0]
    assert (entry["sender_kind"], entry["sender_name"]) == ("peer", "Anna")
    assert entry["subject"] == "Yeast"
    assert entry["body_size"] == len("We are out of yeast.")
    assert "body" not in entry
    # The body has its own address, and comes back exactly as it was sent.
    assert (
        participants.get(
            f"/messages/{entry['message_id']}/body", headers=bearer(berta["token"])
        ).text
        == "We are out of yeast."
    )
    # Her own message is in her outbox, not her inbox.
    assert participants.get("/outbox", headers=bearer(anna["token"])).json()["entries"]
    assert participants.get("/inbox", headers=bearer(anna["token"])).json()["entries"] == []

    # Berta answers, tying it to the question.
    participants.post(
        "/peers/messages",
        json={
            "recipients": ["Anna"],
            "subject": "Yeast",
            "body": "Bought.",
            "in_reply_to": entry["message_id"],
        },
        headers=bearer(berta["token"]),
    )
    back = participants.get("/inbox", headers=bearer(anna["token"])).json()["entries"][0]
    assert back["in_reply_to"] == entry["message_id"], "in the listing, so nothing has to be opened"

    # A central service: only a realm master may obtain the invitation, so Berta is
    # told to ask one.
    refused = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(berta["token"]),
    )
    assert refused.status_code == 403
    assert refused.json()["type"] == "not-realm-master"
    assert "ask" in refused.json()["message"].lower()

    service_voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    weather = participants.post(
        "/invitations/redeem",
        json={"invitation": service_voucher, "member_self_image": "I answer about weather."},
    ).json()
    assert weather["kind"] == "service"
    assert "team_name" not in weather, "a central service has no team"
    assert "is_realm_master" not in weather, "and cannot carry the right"

    # Anna asks it something. It sees an alias where her name would be.
    asked = participants.post(
        "/services/messages",
        json={"recipient": "weather", "subject": "How warm?", "body": "Today?"},
        headers=bearer(anna["token"]),
    ).json()
    assert asked["recipients"] == [{"kind": "service", "name": "weather"}]

    theirs = participants.get("/inbox", headers=bearer(weather["token"])).json()["entries"][0]
    assert theirs["sender_kind"] == "alias"
    assert theirs["sender_name"] != "Anna"
    alias = theirs["sender_name"]

    # It answers along the alias. It never learns a name — not here, not in its own
    # outbox.
    replied = participants.post(
        f"/aliases/{alias}/messages",
        json={"subject": "Twelve", "body": "Twelve degrees."},
        headers=bearer(weather["token"]),
    ).json()
    assert replied["recipients"] == [{"kind": "alias", "name": alias}]
    own = participants.get("/outbox", headers=bearer(weather["token"])).json()["entries"][0]
    assert own["recipients"] == [{"kind": "alias", "name": alias}]

    # And Anna sees an ordinary message from a name she can address, tied to her
    # question, with no alias anywhere in sight.
    hers = participants.get("/inbox", headers=bearer(anna["token"])).json()["entries"][0]
    assert (hers["sender_kind"], hers["sender_name"]) == ("service", "weather")
    assert hers["in_reply_to"] == asked["message_id"]
    assert alias not in str(hers)


# ------------------------------------------------------------------- the cascade


def test_the_seven_token_free_addresses_answer_without_one(participants: TestClient) -> None:
    for address in ("/", "/guide", "/health", "/build", "/openapi.json", "/skill.zip", "/mcp.zip"):
        assert participants.get(address).status_code == 200, address
    for part in ("concepts", "sending", "receiving", "directories", "files"):
        assert participants.get(f"/guide/{part}").status_code == 200, part


def test_the_mcp_package_is_the_same_bytes_whoever_serves_it(context) -> None:
    """Static: two instances under two addresses hand out one archive.

    Two clients with different base addresses stand in for two instances — the
    request's host is the only thing an instance could put in, and it does not.
    """
    from conftest import BUILD

    from simple_a2a.describe import mcp_package
    from simple_a2a.messaging.app import build_app

    served = []
    for base, build in (
        ("http://one.test", BUILD),
        ("https://two.test:9000", {**BUILD, "build_id": "other"}),
    ):
        with TestClient(build_app(context, build=build), base_url=base) as client:
            answer = client.get("/mcp.zip")
            assert answer.status_code == 200
            assert answer.headers["content-type"] == "application/zip"
            served.append(answer.content)

    assert served[0] == served[1] == mcp_package.build_archive()


def test_the_entry_names_the_mcp_package_with_its_purpose(participants: TestClient) -> None:
    """Linked like every other form, and its item says at once that it is not the contract."""
    entry = participants.get("/").text

    item = next(item for item in entry.split("\n- ") if "/mcp.zip" in item)
    assert item.startswith("http://testserver/mcp.zip — ")
    assert "not the contract" in " ".join(item.split())


def test_the_raw_bodies_are_in_the_description(participants: TestClient) -> None:
    """Two operations read their body raw; the description says so, and what it takes.

    Without it, the description says they take nothing — and a client built from it
    sends nothing.
    """
    document = participants.get("/openapi.json").json()

    self_image = document["paths"]["/me/self"]["put"]["requestBody"]
    assert list(self_image["content"]) == ["text/plain"]
    assert "8192" in self_image["description"]
    deposit = document["paths"]["/files"]["post"]["requestBody"]
    assert list(deposit["content"]) == ["application/octet-stream"]
    assert "52428800" in deposit["description"], "the limit of this installation"
    fetched = document["paths"]["/files/{file_id}/{file_name}"]["get"]["responses"]["200"]
    assert "application/octet-stream" in fetched["content"]


def test_the_generated_description_passes_the_gate(participants: TestClient) -> None:
    document = participants.get("/openapi.json").json()

    found = gate.check_description(document, gate.Rules(surface="messaging"))

    assert found, found.report()


def test_nothing_on_this_surface_names_another(participants: TestClient) -> None:
    """A hard promise: no answer here makes an administration or an observation visible."""
    texts = [participants.get(address).text for address in ("/", "/guide", "/openapi.json")]
    for part in ("concepts", "sending", "receiving", "directories", "files"):
        texts.append(participants.get(f"/guide/{part}").text)

    for text in texts:
        for giveaway in ("8252", "8253", "/realms", "/observer-tokens", "/traffic", "/setup-note"):
            assert giveaway not in text, giveaway


def test_every_rejection_this_surface_can_give_has_a_text() -> None:
    from simple_a2a.messaging import texts

    found = gate.check_teaching(texts.build())

    assert found, found.report()


# --------------------------------------------------------------- what a service is not


def test_a_service_is_refused_team_operations_with_its_own_way_forward(
    admin: TestClient, participants: TestClient
) -> None:
    """Told what it can do, not to obtain a token it cannot obtain."""
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    weather = participants.post(
        "/invitations/redeem", json={"invitation": voucher, "member_self_image": "x"}
    ).json()
    token = bearer(weather["token"])

    for address in ("/team", "/team/purpose", "/peers", "/services"):
        answer = participants.get(address, headers=token)
        assert answer.status_code == 403, address
        assert answer.json()["type"] == "wrong-token"
        assert "no team" in answer.json()["message"]
        assert "inbox" in answer.json()["message"], "its own addresses, not an instruction"

    refused = participants.post(
        "/peers/messages", json={"subject": "s", "body": "b"}, headers=token
    )
    assert refused.status_code == 403
    assert "central service" in refused.json()["message"]


def test_a_service_asking_for_its_mission_is_told_why_there_is_none(
    admin: TestClient, participants: TestClient
) -> None:
    """Saying only "wrong kind of token" would read like a fault. It is not one."""
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    weather = participants.post(
        "/invitations/redeem", json={"invitation": voucher, "member_self_image": "x"}
    ).json()

    answer = participants.get("/me/mission", headers=bearer(weather["token"]))

    assert answer.status_code == 403
    assert "registered yourself" in answer.json()["message"]
    assert "/me/self" in answer.json()["message"]


def test_a_peer_at_the_alias_operation_is_told_their_own_way(
    admin: TestClient, participants: TestClient
) -> None:
    """The same act by the means they have, not "get a service token"."""
    a_team(admin)
    token = joined(admin, participants, "Anna")

    answer = participants.post(
        "/aliases/x/messages", json={"subject": "s", "body": "b"}, headers=bearer(token)
    )

    assert answer.status_code == 403
    assert "in_reply_to" in answer.json()["message"]


# ------------------------------------------------------------------ the boundaries


def test_a_token_the_installation_never_issued_is_no_token(participants: TestClient) -> None:
    answer = participants.get("/inbox", headers=bearer("z" * 43))

    assert answer.status_code == 401
    assert answer.json()["type"] == "no-token"
    # And it names the one thing a caller in that position can check.
    assert "right installation" in answer.json()["message"]


def test_a_revoked_token_says_the_way_back_is_a_new_name(
    admin: TestClient, participants: TestClient
) -> None:
    a_team(admin)
    token = joined(admin, participants, "Anna")
    admin.delete("/realms/household/teams/kitchen/members/Anna/token")

    answer = participants.get("/inbox", headers=bearer(token))

    assert answer.status_code == 401
    assert answer.json()["type"] == "token-revoked"
    assert "new name" in answer.json()["message"]


def test_an_unknown_peer_points_at_the_listing(admin: TestClient, participants: TestClient) -> None:
    a_team(admin)
    token = joined(admin, participants, "Anna")

    answer = participants.get("/peers/Nobody", headers=bearer(token))

    assert answer.status_code == 404
    assert "GET /peers" in answer.json()["message"]


def test_a_body_over_the_limit_names_the_three_ways_on(
    admin: TestClient, participants: TestClient
) -> None:
    a_team(admin)
    token = joined(admin, participants, "Anna")

    answer = participants.post(
        "/peers/messages",
        json={"subject": "s", "body": "x" * (1024 * 1024 + 1)},
        headers=bearer(token),
    )

    assert answer.status_code == 413
    message = answer.json()["message"]
    assert "attach" in message and "split" in message and "body_file_id" in message


def test_both_body_fields_at_once_is_refused(admin: TestClient, participants: TestClient) -> None:
    a_team(admin)
    token = joined(admin, participants, "Anna")

    answer = participants.post(
        "/peers/messages",
        json={"subject": "s", "body": "x", "body_file_id": "y" * 43},
        headers=bearer(token),
    )

    assert answer.status_code == 400
    assert "exactly one" in answer.json()["message"]


# ------------------------------------------------------------------------ files


def test_a_file_is_deposited_and_fetched_under_a_name_of_the_fetcher_s_choice(
    admin: TestClient, participants: TestClient
) -> None:
    """The name lives on the envelope, not on the file, so it need not match."""
    a_team(admin)
    token = joined(admin, participants, "Anna")

    deposited = participants.post(
        "/files",
        content=b"one,two\n3,4\n",
        headers={**bearer(token), "Content-Type": "text/csv"},
    ).json()
    assert deposited["size"] == 12
    assert deposited["media_type"] == "text/csv"

    fetched = participants.get(f"/files/{deposited['file_id']}/numbers.txt", headers=bearer(token))

    assert fetched.content == b"one,two\n3,4\n"
    # The type the depositor said, not one guessed from the name the fetcher chose.
    assert fetched.headers["content-type"].startswith("text/csv")
    assert "numbers.txt" in fetched.headers["content-disposition"]


def test_a_file_deposited_without_a_type_is_plain_text_and_says_so(
    admin: TestClient, participants: TestClient
) -> None:
    a_team(admin)
    token = joined(admin, participants, "Anna")

    deposited = participants.post(
        "/files", content=b"%PDF and nothing else", headers=bearer(token)
    ).json()
    fetched = participants.get(f"/files/{deposited['file_id']}/brief.pdf", headers=bearer(token))

    # Not guessed from the name the fetcher chose: nobody said it was a PDF.
    assert deposited["media_type"] == "text/plain"
    assert fetched.headers["content-type"].startswith("text/plain")


def test_a_media_type_that_could_not_be_handed_back_is_refused(
    admin: TestClient, participants: TestClient
) -> None:
    a_team(admin)
    token = joined(admin, participants, "Anna")

    answer = participants.post(
        "/files",
        content=b"x",
        headers={**bearer(token), "Content-Type": "text/" + "x" * 300},
    )

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"


def test_a_path_in_the_saved_name_is_dropped_rather_than_followed(
    admin: TestClient, participants: TestClient
) -> None:
    """The name goes into a response header, so what is left has to be a plain name.

    Both kinds of slash reach here: the name is taken as the rest of the address, so
    `reports/2026/numbers.csv` is not an address that does not exist but a name with
    directory parts, and they are dropped the way they are in an attachment entry. A
    backslash is what a caller on another kind of machine sends.
    """
    a_team(admin)
    token = joined(admin, participants, "Anna")
    deposited = participants.post("/files", content=b"x", headers=bearer(token)).json()

    answer = participants.get(
        f"/files/{deposited['file_id']}/..%5C..%5Cetc%5Cpasswd", headers=bearer(token)
    )

    assert answer.status_code == 200
    assert "passwd" in answer.headers["content-disposition"]
    assert ".." not in answer.headers["content-disposition"]

    forward = participants.get(
        f"/files/{deposited['file_id']}/reports%2F2026%2Fnumbers.csv", headers=bearer(token)
    )
    assert forward.status_code == 200
    assert 'filename="numbers.csv"' in forward.headers["content-disposition"]


def test_a_name_that_is_no_name_once_the_path_is_dropped_is_refused(
    admin: TestClient, participants: TestClient
) -> None:
    """A bare `..` never reaches here — the router resolves it away — but this does."""
    a_team(admin)
    token = joined(admin, participants, "Anna")
    deposited = participants.post("/files", content=b"x", headers=bearer(token)).json()

    answer = participants.get(f"/files/{deposited['file_id']}/..%5C..", headers=bearer(token))

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"

    # Only directories, or nothing at all: the rest of the address is no name either,
    # and it is refused in the catalogue's words rather than as an address that does
    # not exist.
    for rest in ("reports%2F2026%2F", ""):
        answer = participants.get(f"/files/{deposited['file_id']}/{rest}", headers=bearer(token))
        assert answer.status_code == 400, rest
        assert answer.json()["type"] == "invalid-input", rest


def test_a_field_we_do_not_know_is_refused_rather_than_ignored(
    admin: TestClient, participants: TestClient
) -> None:
    """Ignoring one is how a forbidden field slipped through as a success."""
    a_team(admin)
    token = joined(admin, participants, "Anna")

    answer = participants.post(
        "/peers/messages",
        json={"subject": "s", "body": "b", "invented": True},
        headers=bearer(token),
    )

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"


def test_an_attachment_carries_its_size_out_and_never_in(
    admin: TestClient, participants: TestClient
) -> None:
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    berta = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Berta")}
    ).json()
    deposited = participants.post(
        "/files", content=b"x" * 100, headers=bearer(anna["token"])
    ).json()

    sent = participants.post(
        "/peers/messages",
        json={
            "subject": "s",
            "body": "see the file",
            "attachments": [{"name": "hundred.txt", "file_id": deposited["file_id"]}],
        },
        headers=bearer(anna["token"]),
    ).json()

    envelope = participants.get(
        f"/messages/{sent['message_id']}", headers=bearer(berta["token"])
    ).json()
    assert envelope["attachments"] == [
        {"name": "hundred.txt", "file_id": deposited["file_id"], "size": 100}
    ]
    assert envelope["total_size"] == len("see the file") + 100

    refused = participants.post(
        "/peers/messages",
        json={
            "subject": "s",
            "body": "b",
            "attachments": [{"name": "x", "file_id": deposited["file_id"], "size": 100}],
        },
        headers=bearer(anna["token"]),
    )
    assert refused.status_code == 400


# ------------------------------------------------------------- founding a team


def test_founding_a_team_gives_a_second_identity_and_carries_the_right(
    admin: TestClient, participants: TestClient
) -> None:
    """An identity is a name in a team, so a second team is a second token."""
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()

    founded = participants.post(
        "/teams",
        json={
            "team_name": "bathroom",
            "team_purpose": "We keep it stocked.",
            "member_mission": "I started this.",
        },
        headers=bearer(anna["token"]),
    ).json()

    assert founded["team_name"] == "bathroom"
    assert founded["token"] != anna["token"]
    assert founded["is_realm_master"] is True, "the right travels with the person"
    assert participants.get("/team", headers=bearer(founded["token"])).text.count("bathroom") >= 1


def test_appointing_needs_the_right_and_cannot_be_taken_back(
    admin: TestClient, participants: TestClient
) -> None:
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    voucher = participants.post(
        "/invitations/peer",
        json={"member_name": "Berta", "member_mission": "m", "display_name": "for Berta"},
        headers=bearer(anna["token"]),
    ).json()["invitation"]
    berta = participants.post("/invitations/redeem", json={"invitation": voucher}).json()

    assert (
        participants.post("/peers/Berta/realmmaster", headers=bearer(berta["token"])).status_code
        == 403
    )
    appointed = participants.post("/peers/Anna/realmmaster", headers=bearer(anna["token"]))
    assert appointed.status_code == 200

    # There is no way to take it back here: deposing is deliberately not this hand.
    assert (
        participants.delete("/peers/Anna/realmmaster", headers=bearer(anna["token"])).status_code
        == 405
    )


# ------------------------------------------------------------ nothing leaks out


def test_no_answer_on_this_surface_names_the_realm(
    admin: TestClient, participants: TestClient
) -> None:
    """For a participant the realm is the universe, and no answer says otherwise."""
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    token = bearer(anna["token"])
    sent = participants.post(
        "/peers/messages", json={"subject": "s", "body": "b"}, headers=token
    ).json()

    seen = [
        participants.get("/team", headers=token).text,
        participants.get("/me", headers=token).text,
        participants.get("/peers", headers=token).text,
        participants.get("/services", headers=token).text,
        participants.get("/inbox", headers=token).text,
        participants.get("/outbox", headers=token).text,
        participants.get(f"/messages/{sent['message_id']}", headers=token).text,
        str(anna),
    ]

    for text in seen:
        assert "household" not in text


@pytest.mark.parametrize(
    "address", ["/team", "/me", "/peers", "/services", "/inbox", "/outbox", "/me/self"]
)
def test_no_answer_carries_an_internal_identifier(
    admin: TestClient, participants: TestClient, context, address: str
) -> None:
    a_team(admin)
    anna = participants.post(
        "/invitations/redeem", json={"invitation": invited(admin, "Anna")}
    ).json()
    from simple_a2a.domain import access

    caller = access.authenticate(context, anna["token"])

    text = participants.get(address, headers=bearer(anna["token"])).text

    assert caller.realm_id not in text
    assert caller.team_id not in text
    assert caller.member_id not in text


# ------------------------------------------------------------------- who you are, as data


def test_me_answers_as_data_when_asked_and_as_prose_otherwise(
    admin: TestClient, participants: TestClient
) -> None:
    """The same facts, for a peer and for a central service; prose stays the default.

    A program keeping several identities apart needs them as fields. Everybody who
    does not ask — no Accept, `*/*`, text first — gets exactly what they got before.
    """
    a_team(admin)
    anna = joined(admin, participants, "Anna")
    voucher = participants.post(
        "/invitations/service",
        json={"service_name": "weather", "display_name": "for weather"},
        headers=bearer(anna),
    ).json()["invitation"]
    weather = participants.post(
        "/invitations/redeem",
        json={"invitation": voucher, "member_self_image": "I answer about weather."},
    ).json()["token"]

    def me(token: str, accept: str | None) -> object:
        headers = bearer(token) | ({"Accept": accept} if accept else {})
        return participants.get("/me", headers=headers)

    as_peer = me(anna, "application/json")
    as_service = me(weather, "application/json")
    prose = me(anna, None)

    assert as_peer.headers["content-type"].startswith("application/json")
    assert as_peer.json() == {
        "kind": "peer",
        "name": "Anna",
        "team_name": "kitchen",
        "is_realm_master": True,
    }
    assert as_service.json() == {"kind": "service", "name": "weather"}
    assert prose.headers["content-type"].startswith("text/plain")
    assert prose.text.startswith("# You are Anna, in kitchen")
    for accept in ("*/*", "text/markdown, application/json", "application/json;q=0.5, text/plain"):
        assert not me(anna, accept).headers["content-type"].startswith("application/json"), accept
    assert me(anna, "text/plain;q=0.5, application/json").json()["name"] == "Anna"


def test_the_description_of_me_offers_both_answers(participants: TestClient) -> None:
    document = participants.get("/openapi.json").json()

    offered = document["paths"]["/me"]["get"]["responses"]["200"]["content"]

    assert {"text/plain", "text/markdown", "application/json"} <= set(offered)
    assert offered["application/json"]["schema"]["$ref"].endswith("/Me")
    assert gate.check_description(document, gate.Rules(surface="messaging"))


# ------------------------------------------------------------- your team, as data


def test_peers_answers_as_data_when_asked_and_as_prose_otherwise(
    admin: TestClient, participants: TestClient
) -> None:
    """The same list for a program, with kind, name and the marks the prose shows.

    A program that read the prose as JSON lost a session over it; one that fished the
    names out with a pattern was one rewording away from the same. A central service
    has no team, and is refused the same way in both forms.
    """
    a_team(admin)
    anna = joined(admin, participants, "Anna")
    joined(admin, participants, "Berta")
    voucher = participants.post(
        "/invitations/peer",
        json={"member_name": "Clara", "member_mission": "m", "display_name": "for Clara"},
        headers=bearer(anna),
    ).json()["invitation"]
    participants.post("/invitations/redeem", json={"invitation": voucher})
    admin.delete("/realms/household/teams/kitchen/members/Clara/token")
    weather = participants.post(
        "/invitations/redeem",
        json={
            "invitation": participants.post(
                "/invitations/service",
                json={"service_name": "weather", "display_name": "for weather"},
                headers=bearer(anna),
            ).json()["invitation"],
            "member_self_image": "I answer about weather.",
        },
    ).json()["token"]

    def peers(token: str, accept: str | None, query: str = "") -> object:
        headers = bearer(token) | ({"Accept": accept} if accept else {})
        return participants.get(f"/peers{query}", headers=headers)

    data = peers(anna, "application/json")
    prose = peers(anna, None)

    assert data.headers["content-type"].startswith("application/json")
    assert data.json() == {
        "entries": [
            {"kind": "peer", "name": "Berta", "is_realm_master": True, "token_revoked": False},
            {"kind": "peer", "name": "Clara", "is_realm_master": False, "token_revoked": True},
        ]
    }
    assert prose.headers["content-type"].startswith("text/plain")
    assert "**Clara** (token revoked)" in prose.text
    assert peers(anna, "application/json", "?offset=1&limit=1").json()["entries"] == [
        data.json()["entries"][1]
    ]
    for accept in ("*/*", "text/markdown, application/json"):
        assert not peers(anna, accept).headers["content-type"].startswith("application/json")
    for accept in ("application/json", None):
        refused = peers(weather, accept)
        assert refused.status_code == 403, accept
        assert refused.json()["type"] == "wrong-token", accept


def test_the_description_of_peers_offers_both_answers(participants: TestClient) -> None:
    document = participants.get("/openapi.json").json()

    offered = document["paths"]["/peers"]["get"]["responses"]["200"]["content"]

    assert {"text/plain", "text/markdown", "application/json"} <= set(offered)
    assert offered["application/json"]["schema"]["$ref"].endswith("/Peers")
    assert gate.check_description(document, gate.Rules(surface="messaging"))


def test_the_entry_and_the_guide_say_where_data_can_be_asked_for(
    participants: TestClient,
) -> None:
    entry = participants.get("/").text
    concepts = participants.get("/guide/concepts").text

    assert "Accept: application/json" in entry
    for address in ("/me", "/peers"):
        assert f"{address}` —" in entry, address
    assert "`entries`" in concepts
