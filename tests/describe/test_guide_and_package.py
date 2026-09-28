"""The texts as they are served: every part there, one address, and no leftovers.

These run against the real texts rather than fixtures, because the promises being
checked are about the shipped files: twelve parts across three surfaces, the base
address in exactly one of them, and an archive whose big half is the same bytes
wherever it is served from.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from simple_a2a.describe import gate, package
from simple_a2a.describe.guide import PARTS, Guide

SURFACES = ("messaging", "admin", "observe")

BASE = "https://example.test"
PLAIN = "http://example.test:8252"


def guide_of(surface: str, base: str = BASE) -> Guide:
    return Guide(surface=surface, base_address=base)


def test_there_are_twelve_parts_across_the_three_surfaces() -> None:
    """Five, four and three — the number the smoke test counts."""
    assert [len(PARTS[surface]) for surface in SURFACES] == [5, 4, 3]
    assert sum(len(PARTS[surface]) for surface in SURFACES) == 12


@pytest.mark.parametrize("surface", SURFACES)
def test_every_part_of_every_surface_is_there_and_says_something(surface: str) -> None:
    """A missing text is a broken build: the parts ship with the code."""
    parts = guide_of(surface).parts()

    assert set(parts) == {"guide", *PARTS[surface]}
    for name, text in parts.items():
        assert len(text) > 500, f"{surface}/{name} is too short to be a part"
        assert text.startswith("#"), f"{surface}/{name} has no heading"


@pytest.mark.parametrize("surface", SURFACES)
def test_a_part_this_surface_does_not_have_is_not_served(surface: str) -> None:
    """The refusal is the surface's own; it does not know another's parts."""
    assert not guide_of(surface).has_part("invented")
    with pytest.raises(KeyError):
        guide_of(surface).part("invented")


@pytest.mark.parametrize("surface", SURFACES)
def test_the_base_address_is_in_the_entry_and_nowhere_else(surface: str) -> None:
    """One place carries it, so no part is wrong under a second host name."""
    made = guide_of(surface)

    assert BASE in made.entry()
    for name, text in made.parts().items():
        assert "http" not in text, f"{surface}/{name} carries an address"


@pytest.mark.parametrize("surface", SURFACES)
def test_the_rendered_texts_pass_the_gate(surface: str) -> None:
    """Run on what is served, which is the moment a placeholder is actually wrong."""
    made = guide_of(surface)
    served = {"entry": made.entry(), **made.parts()}

    found = gate.check_texts(served)

    assert found, found.report()


@pytest.mark.parametrize("surface", SURFACES)
def test_no_placeholder_survives_rendering(surface: str) -> None:
    assert "%%" not in guide_of(surface).entry()


def test_the_plain_address_paragraph_is_removed_when_it_does_not_apply() -> None:
    """One text, one truth: the sentence goes rather than being reworded."""
    over_tls = guide_of("admin", BASE).entry()
    in_the_clear = guide_of("admin", PLAIN).entry()

    assert "travels in the clear" in in_the_clear
    assert "travels in the clear" not in over_tls
    assert "<!--" not in over_tls and "<!--" not in in_the_clear
    # And what remains is still one readable document, not a hole.
    assert "\n\n\n\n" not in over_tls


def test_only_the_operator_is_told_about_a_plain_address() -> None:
    """An agent reading the participant guide cannot do anything about it."""
    for surface in ("messaging", "observe"):
        assert "in the clear" not in guide_of(surface, PLAIN).entry()


@pytest.mark.parametrize("surface", SURFACES)
def test_the_big_half_of_the_package_carries_no_address(surface: str) -> None:
    """Which is what lets it be the same bytes on every instance."""
    big = package.skill_half(guide_of(surface), "whatever it is")

    assert "http" not in big
    assert "%%" not in big


@pytest.mark.parametrize("surface", SURFACES)
def test_the_big_half_is_the_same_bytes_on_two_instances(surface: str) -> None:
    here = package.skill_half(guide_of(surface, "https://one.test"), "same")
    there = package.skill_half(guide_of(surface, "https://two.test:9000"), "same")

    assert here == there


@pytest.mark.parametrize("surface", SURFACES)
def test_the_big_half_holds_the_frontmatter_and_every_part_in_reading_order(
    surface: str,
) -> None:
    made = guide_of(surface)
    big = package.skill_half(made, "a description")

    assert big.startswith("---\nname: ")
    assert "description: a description" in big
    positions = [big.index(made.part(name)[:80]) for name in ("guide", *PARTS[surface])]
    assert positions == sorted(positions), "the parts are in reading order"


def test_the_small_half_carries_the_address_and_the_build() -> None:
    """It is the file somebody keeps twice, and the one that says a build moved on."""
    small = package.instance_half(guide_of("messaging"), build="abc123")

    assert BASE in small
    assert "abc123" in small
    assert len(small) < 800, "short on purpose"


def test_the_archive_holds_exactly_the_two_halves() -> None:
    made = package.build_archive(guide_of("admin"), description="d", build="b")

    with zipfile.ZipFile(io.BytesIO(made)) as archive:
        assert sorted(archive.namelist()) == ["INSTANCE.md", "SKILL.md"]
        assert "http" not in archive.read("SKILL.md").decode("utf-8")
        assert BASE in archive.read("INSTANCE.md").decode("utf-8")


def test_two_fetches_of_the_same_build_are_the_same_bytes() -> None:
    """Or an agent that kept one cannot tell a changed service from a changed archive."""
    first = package.build_archive(guide_of("observe"), description="d", build="b")
    second = package.build_archive(guide_of("observe"), description="d", build="b")

    assert first == second


def test_a_different_build_gives_a_different_archive() -> None:
    """Because the small half is the signal that something changed."""
    before = package.build_archive(guide_of("observe"), description="d", build="one")
    after = package.build_archive(guide_of("observe"), description="d", build="two")

    assert before != after


@pytest.mark.parametrize("surface", SURFACES)
def test_no_part_names_another_surface(surface: str) -> None:
    """A hard promise, not a matter of style: no surface makes another recognisable.

    Checked by the addresses, because that is what gives a surface away: a port it
    does not serve, or an address that only exists elsewhere.
    """
    # Only addresses and ports that exist on *another* surface and not on this one.
    # `/teams` is on two of them and is therefore not a giveaway anywhere.
    elsewhere = {
        "messaging": ("8252", "8253", "/realms", "/observer-tokens", "/traffic", "/setup-note"),
        "admin": ("8251", "8253", "/inbox", "/outbox", "/aliases/", "/me/", "/traffic", "/peers/"),
        "observe": (
            "8251",
            "8252",
            "/inbox",
            "/outbox",
            "/realms",
            "/observer-tokens",
            "/me/",
            "/invitations",
        ),
    }[surface]
    texts = {"entry": guide_of(surface).entry(), **guide_of(surface).parts()}

    for name, text in texts.items():
        for giveaway in elsewhere:
            assert giveaway not in text, f"{surface}/{name} names {giveaway!r}"
