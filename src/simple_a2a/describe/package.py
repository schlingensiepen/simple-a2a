"""The skill package: the same texts, a different wrapping, and in two halves.

An agent with a mechanism for keeping skills wants a file it can keep; one without
reads the same thing online. Offering only one of the two forms decides for the
reader what they are capable of, so both exist and say the same thing.

**Two halves, and the split is the point.** The big half is the parts of this
surface, unchanged, plus a frontmatter naming the package — **instance-independent
and byte-identical everywhere**, because it contains no address. The small half is
the entry: the base address and the build. Whoever wants to reach two instances
keeps the big half once and the small one twice.

**And the small half doubles as the signal that something changed.** It carries the
build, so an agent that kept a package can tell whether the instance it is talking
to is still the one the package was made from — without a version marker anywhere
else and without asking.

No secret goes in. A file that looks like documentation and carries a token is the
worst of both: it travels like a document and grants like a credential.
"""

from __future__ import annotations

import io
import zipfile

from simple_a2a.describe.guide import GUIDE, PACKAGE_NAME, Guide

#: The two members of the archive. Named so that the small one is obviously the
#: one to keep twice.
SKILL_FILE = "SKILL.md"
INSTANCE_FILE = "INSTANCE.md"

#: A fixed timestamp for every member. Zip stores a modification time, and the
#: current one would make two downloads of the same package different bytes —
#: which is exactly the promise the big half makes.
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def frontmatter(surface: str, description: str) -> str:
    """What an agent reads before it reads anything else."""
    return f"---\nname: {PACKAGE_NAME[surface]}\ndescription: {description}\n---\n"


def skill_half(guide: Guide, description: str) -> str:
    """The big half: the frontmatter and every part, unchanged.

    Contains no address, so it is the same bytes on every instance. Assembled in
    reading order rather than alphabetically, because it is read as a document.
    """
    parts = guide.parts()
    pieces = [frontmatter(guide.surface, description)]
    pieces.append(parts[GUIDE])
    for name in guide.part_names():
        pieces.append(parts[name])
    return "\n\n".join(piece.rstrip("\n") for piece in pieces) + "\n"


def instance_half(guide: Guide, *, build: str) -> str:
    """The small half: where this instance is, and which build it is.

    Short on purpose. It is the file somebody keeps twice, and it is the file that
    tells them their kept copy belongs to a different build.
    """
    return (
        f"# This instance\n\n"
        f"Base address: `{guide.base_address}`\n\n"
        f"Build: `{build}`\n\n"
        f"Every address in the accompanying guide is relative to the base address "
        f"above. If the build here differs from the one this copy was made with, "
        f"fetch the guide again: the interface may have moved on.\n"
    )


def build_archive(guide: Guide, *, description: str, build: str) -> bytes:
    """The package, as bytes, reproducibly.

    Deflated rather than stored, and with a fixed timestamp on every member: two
    fetches of the same package from the same build have to be the same bytes, or
    an agent that keeps one cannot tell a changed service from a changed archive.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in (
            (SKILL_FILE, skill_half(guide, description)),
            (INSTANCE_FILE, instance_half(guide, build=build)),
        ):
            info = zipfile.ZipInfo(filename=name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, text)
    return buffer.getvalue()
