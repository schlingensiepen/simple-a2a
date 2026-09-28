"""The administration surface over HTTP: every operation, and every way it says no.

One test per row of the specification's table, plus the answers that belong to the
address rather than to an operation. The point of testing it through HTTP rather
than through the operations is that this is where the two can disagree: a route
that calls the wrong operation, a field that is named differently on the way out, a
rejection that loses its text.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from conftest import ADMIN_SECRET, BUILD
from fastapi.testclient import TestClient

from simple_a2a.describe import gate

# ------------------------------------------------------------------ the cascade


def test_the_seven_token_free_addresses_answer_without_one(no_token: TestClient) -> None:
    """Six fixed and the parts of this surface. None of them needs a token."""
    for address in ("/", "/guide", "/health", "/build", "/openapi.json", "/skill.zip"):
        assert no_token.get(address).status_code == 200, address
    for part in ("first-access", "realms", "tokens", "notes"):
        assert no_token.get(f"/guide/{part}").status_code == 200, part


def test_the_entry_always_answers_the_same_and_always_200(
    no_token: TestClient, admin: TestClient
) -> None:
    """It does not read the holdings and has no second mode of operation.

    So an installation with nothing in it looks exactly like one in use — which is
    what stops the entry from being a way of asking whether anything is there.
    """
    empty = no_token.get("/")
    admin.post("/realms", json={"realm_name": "household"})
    filled = no_token.get("/")

    assert empty.status_code == filled.status_code == 200
    assert empty.text == filled.text


def test_the_entry_carries_the_address_the_request_arrived_on(no_token: TestClient) -> None:
    """Measured, not configured: behind a proxy the service cannot know from inside."""
    plain = no_token.get("/", headers={"Host": "admin.example.test"})
    secure = no_token.get("/", headers={"Host": "admin.example.test", "X-Forwarded-Proto": "https"})

    assert "http://admin.example.test" in plain.text
    assert "https://admin.example.test" in secure.text
    # And only the operator is told about a plain address, because only they can act.
    assert "travels in the clear" in plain.text
    assert "travels in the clear" not in secure.text


def test_health_says_the_process_answers_and_nothing_more(no_token: TestClient) -> None:
    body = no_token.get("/health").json()

    assert body["healthy"] is True
    assert set(body) == {"healthy", "checked_at"}


def test_the_build_stamp_names_the_build(no_token: TestClient) -> None:
    assert no_token.get("/build").json() == BUILD


def test_the_skill_package_is_an_archive_of_two_halves(no_token: TestClient) -> None:
    answer = no_token.get("/skill.zip")

    assert answer.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(answer.content)) as archive:
        assert sorted(archive.namelist()) == ["INSTANCE.md", "SKILL.md"]


def test_the_generated_description_passes_the_gate(no_token: TestClient) -> None:
    """Every route described, every field with an example, and no invented rejection."""
    document = no_token.get("/openapi.json").json()

    found = gate.check_description(document, gate.Rules(surface="admin"))

    assert found, found.report()


def test_the_description_does_not_advertise_a_fourteenth_rejection(
    no_token: TestClient,
) -> None:
    """The framework documents a validation error of its own. We never answer with it."""
    document = no_token.get("/openapi.json").json()

    schemas = (document.get("components") or {}).get("schemas") or {}
    assert not [name for name in schemas if "Validation" in name]
    for verbs in document["paths"].values():
        for operation in verbs.values():
            assert "422" not in (operation.get("responses") or {})


# ------------------------------------------------------- what belongs to the address


def test_an_address_this_surface_does_not_have_names_its_entry(no_token: TestClient) -> None:
    answer = no_token.get("/nonsense")

    assert answer.status_code == 404
    assert answer.json()["type"] == "unknown-address"
    assert "GET /" in answer.json()["message"]


def test_an_address_with_the_wrong_method_says_which_it_takes(admin: TestClient) -> None:
    answer = admin.delete("/realms")

    assert answer.status_code == 405
    assert answer.json()["type"] == "wrong-verb"


def test_a_guide_part_this_surface_has_not_points_at_the_entry(no_token: TestClient) -> None:
    answer = no_token.get("/guide/sending")

    assert answer.status_code == 404
    assert answer.json()["type"] == "unknown-name"
    assert "GET /" in answer.json()["message"]


# --------------------------------------------------------------------- the token


def test_nothing_behind_the_cascade_answers_without_a_secret(no_token: TestClient) -> None:
    answer = no_token.get("/realms")

    assert answer.status_code == 401
    assert answer.json()["type"] == "no-token"
    # And it says where to get one, with a way that works from here.
    assert "Authorization" in answer.json()["message"]
    assert "new" in answer.json()["message"]


def test_a_secret_nobody_issued_is_answered_as_no_token(no_token: TestClient) -> None:
    answer = no_token.get("/realms", headers={"Authorization": "Bearer " + "b" * 43})

    assert answer.status_code == 401
    assert answer.json()["type"] == "no-token"


def test_the_administration_secret_works_on_an_empty_installation(admin: TestClient) -> None:
    """Which is why it is kept outside the holdings."""
    assert admin.get("/realms").json() == {"realms": []}


# --------------------------------------------------------------------- the realms


def test_a_realm_is_created_and_comes_back_without_a_secret(admin: TestClient) -> None:
    answer = admin.post("/realms", json={"realm_name": "household"})

    assert answer.status_code == 200
    assert answer.json() == {"realm_name": "household"}


def test_creating_the_same_realm_twice_is_refused_by_name(admin: TestClient) -> None:
    admin.post("/realms", json={"realm_name": "household"})

    answer = admin.post("/realms", json={"realm_name": "HOUSEHOLD"})

    assert answer.status_code == 409
    assert answer.json()["type"] == "name-taken"
    assert answer.json()["name"] == "HOUSEHOLD"
    assert "GET /realms" in answer.json()["message"]


@pytest.mark.parametrize("bad", [" leading", "trailing ", "two  spaces", "with/slash", "x" * 65])
def test_an_unusable_realm_name_names_the_field_and_an_example(admin: TestClient, bad: str) -> None:
    answer = admin.post("/realms", json={"realm_name": bad})

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"
    assert answer.json()["field"] == "realm_name"
    assert "Example" in answer.json()["message"]


def test_a_body_that_does_not_fit_at_all_is_still_our_own_rejection(admin: TestClient) -> None:
    """Left to the framework this is a shape of its own, outside a closed catalogue."""
    answer = admin.post("/realms", json={"nonsense": 1})

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"
    assert answer.json()["field"] == "realm_name"


def test_the_realm_listing_counts_what_is_in_each(admin: TestClient) -> None:
    admin.post("/realms", json={"realm_name": "household"})
    admin.post("/realms/household/teams", json={"team_name": "kitchen"})

    assert admin.get("/realms").json() == {
        "realms": [{"realm_name": "household", "team_count": 1, "service_count": 0}]
    }


def test_a_window_over_a_listing_is_refused_above_a_hundred(admin: TestClient) -> None:
    answer = admin.get("/realms?limit=101")

    assert answer.status_code == 413
    assert answer.json()["type"] == "too-large"
    assert answer.json()["limit"] == 100


# ---------------------------------------------------------------------- the teams


def test_a_team_is_created_in_a_realm_and_may_be_empty(admin: TestClient) -> None:
    admin.post("/realms", json={"realm_name": "household"})

    answer = admin.post("/realms/household/teams", json={"team_name": "kitchen"})

    assert answer.json() == {"team_name": "kitchen"}
    assert admin.get("/realms/household/teams").json() == {
        "teams": [{"team_name": "kitchen", "member_count": 0}]
    }


def test_a_team_in_an_unknown_realm_says_where_the_realms_are(admin: TestClient) -> None:
    answer = admin.post("/realms/nowhere/teams", json={"team_name": "kitchen"})

    assert answer.status_code == 404
    assert answer.json()["type"] == "unknown-name"
    assert "GET /realms" in answer.json()["message"]


def test_a_purpose_over_the_limit_is_refused_with_the_limit(admin: TestClient) -> None:
    admin.post("/realms", json={"realm_name": "household"})

    answer = admin.post(
        "/realms/household/teams", json={"team_name": "kitchen", "team_purpose": "x" * 8193}
    )

    assert answer.status_code == 413
    assert answer.json()["limit"] == 8192


# ---------------------------------------------------------------- the invitations


def founded(admin: TestClient) -> None:
    admin.post("/realms", json={"realm_name": "household"})
    admin.post("/realms/household/teams", json={"team_name": "kitchen", "team_purpose": "We cook."})


def test_an_invitation_is_shown_once_and_makes_a_realm_master(admin: TestClient) -> None:
    founded(admin)

    answer = admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "member_mission": "Lists.", "display_name": "voucher"},
    )

    body = answer.json()
    assert set(body) == {"display_name", "invitation", "team_name"}
    assert len(body["invitation"]) == 43
    assert body["team_name"] == "kitchen"
    # And it is never shown again: the listing names it by its handle.
    listed = admin.get("/realms/household/invitations").json()["invitations"]
    assert body["invitation"] not in str(listed)


def test_the_invitation_listing_names_the_handle_and_never_the_secret(
    admin: TestClient,
) -> None:
    founded(admin)
    admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "member_mission": "Lists.", "display_name": "voucher"},
    )

    entry = admin.get("/realms/household/invitations").json()["invitations"][0]

    assert entry["display_name"] == "voucher"
    assert entry["target_name"] == "Anna"
    assert entry["kind"] == "member"
    assert entry["team_name"] == "kitchen"
    assert entry["issued_by_kind"] == "operator"
    assert entry["revoked"] is False
    # Absent rather than null: a field that does not apply says nothing at all.
    assert "issued_by" not in entry
    assert "redeemed_at" not in entry


def test_an_invitation_is_revoked_by_its_handle(admin: TestClient) -> None:
    founded(admin)
    admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "member_mission": "Lists.", "display_name": "voucher"},
    )

    answer = admin.delete("/realms/household/invitations/voucher")

    assert answer.json()["revoked"] is True
    assert answer.json()["display_name"] == "voucher"
    assert admin.get("/realms/household/invitations").json()["invitations"][0]["revoked"] is True


def test_revoking_an_invitation_nobody_has_points_at_the_listing(admin: TestClient) -> None:
    founded(admin)

    answer = admin.delete("/realms/household/invitations/nothing")

    assert answer.status_code == 404
    assert "GET /realms/{realm}/invitations" in answer.json()["message"]


# ----------------------------------------------------------------- the revocations


def test_revoking_a_token_keeps_the_identity_and_repeats_the_first_time(
    admin: TestClient, context
) -> None:
    from simple_a2a.domain import access

    founded(admin)
    voucher = admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "member_mission": "Lists.", "display_name": "voucher"},
    ).json()["invitation"]
    access.redeem(context, voucher)

    first = admin.delete("/realms/household/teams/kitchen/members/Anna/token").json()
    second = admin.delete("/realms/household/teams/kitchen/members/Anna/token").json()

    assert first["member_name"] == "Anna"
    assert first["token_revoked"] is True
    assert first["revoked_at"] == second["revoked_at"], "the first time, repeated"
    listed = admin.get("/realms/household/teams/kitchen/members").json()["members"]
    assert listed == [{"member_name": "Anna", "is_realm_master": True, "token_revoked": True}]


def test_taking_the_right_away_leaves_the_token_valid(admin: TestClient, context) -> None:
    from simple_a2a.domain import access
    from simple_a2a.domain.callers import Peer

    founded(admin)
    voucher = admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "member_mission": "Lists.", "display_name": "voucher"},
    ).json()["invitation"]
    token = access.redeem(context, voucher).token

    answer = admin.delete("/realms/household/teams/kitchen/members/Anna/realmmaster")

    assert answer.json() == {"member_name": "Anna", "is_realm_master": False}
    still = access.authenticate(context, token)
    assert isinstance(still, Peer)
    assert not still.is_realm_master


def test_revoking_for_a_name_nobody_has_points_at_the_member_listing(
    admin: TestClient,
) -> None:
    founded(admin)

    answer = admin.delete("/realms/household/teams/kitchen/members/Nobody/token")

    assert answer.status_code == 404
    assert "members" in answer.json()["message"]


# -------------------------------------------------------------- observer tokens


def test_an_observer_token_is_shown_once_and_listed_by_its_handle(admin: TestClient) -> None:
    founded(admin)

    answer = admin.post("/realms/household/observer-tokens", json={"display_name": "the eye"})

    token = answer.json()["token"]
    assert len(token) == 43
    listed = admin.get("/realms/household/observer-tokens").json()["observer_tokens"]
    assert listed[0]["display_name"] == "the eye"
    assert listed[0]["token_revoked"] is False
    assert token not in str(listed)


def test_an_observer_token_can_be_issued_again_after_a_revocation(admin: TestClient) -> None:
    founded(admin)
    admin.post("/realms/household/observer-tokens", json={"display_name": "the eye"})
    admin.delete("/realms/household/observer-tokens/the eye")

    answer = admin.post("/realms/household/observer-tokens", json={"display_name": "another eye"})

    assert answer.status_code == 200
    assert len(admin.get("/realms/household/observer-tokens").json()["observer_tokens"]) == 2


def test_a_handle_is_unique_per_kind_so_an_invitation_does_not_block_an_observer(
    admin: TestClient,
) -> None:
    founded(admin)
    admin.post(
        "/realms/household/teams/kitchen/invitations",
        json={"member_name": "Anna", "member_mission": "Lists.", "display_name": "same"},
    )

    answer = admin.post("/realms/household/observer-tokens", json={"display_name": "same"})

    assert answer.status_code == 200


# ------------------------------------------------------------------- the notes


def test_a_note_comes_back_exactly_as_it_was_written(admin: TestClient) -> None:
    """Deliberately not ours to shape: the service keeps it, it does not know it."""
    awkward = "# Where things are\r\n\r\n  Participants: another host.\t\\ done\n"

    answer = admin.put("/setup-note", content=awkward.encode("utf-8"))

    assert answer.json() == {"length": len(awkward)}
    assert admin.get("/setup-note").text == awkward


def test_writing_a_note_replaces_it(admin: TestClient) -> None:
    admin.put("/setup-note", content=b"first")
    admin.put("/setup-note", content=b"second")

    assert admin.get("/setup-note").text == "second"


def test_the_two_notes_are_two_subjects(admin: TestClient) -> None:
    founded(admin)
    admin.put("/setup-note", content=b"about the installation")
    admin.put("/realms/household/setup-note", content=b"about this realm")

    assert admin.get("/setup-note").text == "about the installation"
    assert admin.get("/realms/household/setup-note").text == "about this realm"


def test_an_empty_note_is_empty_and_not_missing(admin: TestClient) -> None:
    assert admin.get("/setup-note").status_code == 200
    assert admin.get("/setup-note").text == ""


def test_a_note_over_the_limit_is_refused(admin: TestClient) -> None:
    answer = admin.put("/setup-note", content=("x" * 8193).encode("utf-8"))

    assert answer.status_code == 413
    assert answer.json()["limit"] == 8192


def test_a_note_that_is_not_utf_8_is_refused_against_the_body(admin: TestClient) -> None:
    answer = admin.put("/setup-note", content=b"\xff\xfe not text")

    assert answer.status_code == 400
    assert answer.json()["type"] == "invalid-input"


def test_prose_is_labelled_the_way_the_caller_asked(admin: TestClient) -> None:
    admin.put("/setup-note", content=b"# A heading")

    plain = admin.get("/setup-note")
    markdown = admin.get("/setup-note", headers={"Accept": "text/markdown"})

    assert plain.headers["content-type"].startswith("text/plain")
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert plain.text == markdown.text


# ------------------------------------------------------------- every text exists


def test_every_rejection_this_surface_can_give_has_a_text() -> None:
    """Checked against the register, so a missing text is a red build."""
    from simple_a2a.admin import texts

    found = gate.check_teaching(texts.build())

    assert found, found.report()


def test_the_secret_is_never_in_an_answer(admin: TestClient) -> None:
    """Not in a listing, not in a rejection, not in the description."""
    founded(admin)
    for address in ("/", "/guide", "/openapi.json", "/realms", "/realms/household/teams"):
        assert ADMIN_SECRET not in admin.get(address).text, address
