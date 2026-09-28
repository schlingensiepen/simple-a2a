"""The guide: one document in parts, served from where the parts live.

It is hypertext even though it arrives as prose. The parts **are** the guide;
`/guide` is its entry and at the same time its first part. There is no full guide
beside the parts, because a second copy of the same text ages separately and the
reader has no way of telling which one is current.

The parts are cut by the reader's **concern**, not by our building blocks. An
agent that wants to send a message reads one part and is done; it does not need to
know that sending touches four of our modules.

**Exactly one place carries the base address**, and that is the entry. Everywhere
else an address is a bare path. A part that carried a host name would be wrong the
moment the same service is reached under a second one — and behind a proxy that is
the normal case rather than the exception.

The same path may appear on two surfaces and be a different document there: each
surface carries its own guide and names no other. They sit on different ports and
usually under different host names, so a prefix per surface would be a distinction
for a reader who never sees two at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Where the written texts live. Loaded from disk rather than held in Python
#: strings so that whoever writes them works in Markdown, in a file, with the
#: whole text in front of them.
TEXTS = Path(__file__).parent / "texts"

#: The one placeholder. Replaced in the entry, and nowhere else has one.
BASE_PLACEHOLDER = "%%BASE%%"

#: The entry is a part of the document as well as its front door, so it is named
#: like the others.
GUIDE = "guide"
ENTRY = "entry"

#: Marks around the paragraph that only holds when the address is plain HTTP. The
#: sentence is written once, in the administration entry, and removed rather than
#: reworded when it does not apply — an operator can act on it, and nobody else
#: can, which is why it is not in the other entries.
PLAIN_HTTP_OPEN = "<!-- plain-http -->"
PLAIN_HTTP_CLOSE = "<!-- /plain-http -->"

#: The parts of each surface, in reading order. Twelve across the three, plus
#: three guide entries — the number the smoke test counts.
PARTS: dict[str, tuple[str, ...]] = {
    "messaging": ("concepts", "sending", "receiving", "directories", "files"),
    "admin": ("first-access", "realms", "tokens", "notes"),
    "observe": ("concepts", "traffic", "contents"),
}

#: What the skill package calls itself, per surface. Short, because it lands in a
#: frontmatter that an agent reads before it reads anything else.
PACKAGE_NAME = {
    "messaging": "simple-a2a-participant",
    "admin": "simple-a2a-administration",
    "observe": "simple-a2a-observation",
}


@dataclass(frozen=True)
class Guide:
    """The texts of one surface, rendered for one caller.

    Built per request because the entry carries the base address, and the base
    address comes from the request. The parts do not, so they are the same bytes
    for every caller and for every instance — which is what lets the big half of
    the skill package be shared.
    """

    surface: str
    base_address: str

    def part_names(self) -> tuple[str, ...]:
        return PARTS[self.surface]

    def has_part(self, name: str) -> bool:
        return name == GUIDE or name in PARTS[self.surface]

    def _read(self, name: str) -> str:
        path = TEXTS / self.surface / f"{name}.md"
        try:
            return path.read_bytes().decode("utf-8")
        except OSError as exc:
            # A missing text is a broken build, not a caller's mistake: the parts
            # are shipped with the code.
            raise FileNotFoundError(f"the {self.surface} text {name!r} is missing") from exc

    def part(self, name: str) -> str:
        """One part, exactly as written. No address is put into it."""
        if not self.has_part(name):
            raise KeyError(name)
        return self._read(name)

    def parts(self) -> dict[str, str]:
        """Every part of this surface, the guide entry included."""
        return {name: self._read(name) for name in (GUIDE, *self.part_names())}

    def entry(self) -> str:
        """The surface's entry, with the base address put in.

        The plain-HTTP paragraph is **removed** when the address is not plain HTTP,
        rather than reworded: one text, one truth, and nothing that has to be kept
        in step with a condition.
        """
        text = self._read(ENTRY)
        text = (
            _without_plain_http(text)
            if not self.base_address.startswith("http://")
            else _unmark(text)
        )
        return text.replace(BASE_PLACEHOLDER, self.base_address)


def _unmark(text: str) -> str:
    """Drop the marks and keep the paragraph."""
    return text.replace(PLAIN_HTTP_OPEN + "\n", "").replace(PLAIN_HTTP_CLOSE + "\n", "")


def _without_plain_http(text: str) -> str:
    """Drop the marks and the paragraph between them."""
    start = text.find(PLAIN_HTTP_OPEN)
    end = text.find(PLAIN_HTTP_CLOSE)
    if start == -1 or end == -1 or end < start:
        return text
    return text[:start].rstrip("\n") + "\n" + text[end + len(PLAIN_HTTP_CLOSE) :].lstrip("\n")
