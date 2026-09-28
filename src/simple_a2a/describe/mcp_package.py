"""The MCP package: a program that lives beside the service, served as it is.

The program is not part of this package and imports nothing from it — it is an
ordinary client of the participant surface that happens to ship with the release.
This module only finds its files and wraps them, and the wrapping is **static**:
unlike the skill package there is no half that carries an address or a build. The
program is told where the service is when it is started, so the archive is the
same bytes on every instance of the same release.

**Where the files are depends on how the service runs.** Installed from a wheel,
the build has copied them next to this module; run from a source tree, they are at
the top of the repository, where they are written. Both places hold the same
bytes — the wheel's are a copy made at build time — and a test holds the served
archive against the files in the tree.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

#: The members, in the order they go into the archive. Named rather than globbed,
#: so that a stray file beside them — a cache, an editor's backup — never ships.
#: A test says the directory holds exactly these.
MEMBERS = ("README.md", "simple_a2a_mcp.py")

#: The folder the archive unpacks into, so unpacking does not scatter two files
#: into whatever directory somebody happened to be in.
FOLDER = "simple-a2a-mcp"

#: A fixed timestamp for every member, for the same reason as in the skill
#: package: the current one would make two builds of the same files different
#: bytes.
FIXED_TIME = (2026, 1, 1, 0, 0, 0)

#: Installed: copied here by the wheel build. From a source tree: the top of the
#: repository, three levels above the package directory.
INSTALLED = Path(__file__).parent / "mcp"
SOURCE_TREE = Path(__file__).resolve().parents[3] / "mcp"


def source() -> Path:
    """The directory the program is read from, whichever of the two exists."""
    for candidate in (INSTALLED, SOURCE_TREE):
        if all((candidate / name).is_file() for name in MEMBERS):
            return candidate
    raise FileNotFoundError(
        f"the MCP program is in neither {INSTALLED} nor {SOURCE_TREE}; the build did not include it"
    )


def build_archive(directory: Path | None = None) -> bytes:
    """The package, as bytes, reproducibly.

    The program is marked executable inside the archive, so that unpacking it on a
    system that honours the mode leaves something that can be started directly.
    """
    where = directory or source()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in MEMBERS:
            info = zipfile.ZipInfo(filename=f"{FOLDER}/{name}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".py") else 0o644) << 16
            archive.writestr(info, (where / name).read_bytes())
    return buffer.getvalue()
