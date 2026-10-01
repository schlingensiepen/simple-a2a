"""The MCP package: the files under mcp/, byte for byte, the same on every instance.

The archive is static — nothing in it depends on the instance serving it — and that
is only worth anything if it is checked against the files themselves rather than
against a description of them.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from simple_a2a.describe import mcp_package

MCP = Path(__file__).resolve().parents[2] / "mcp"


def members(archive: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        return {info.filename: opened.read(info) for info in opened.infolist()}


def test_the_directory_holds_exactly_the_members_that_ship() -> None:
    """A third file under mcp/ would be left out silently; this makes it loud."""
    present = {
        path.name
        for path in MCP.iterdir()
        if path.is_file() or (path.is_dir() and path.name != "__pycache__")
    }

    assert present == set(mcp_package.MEMBERS)


def test_the_files_are_read_from_the_tree_when_run_from_it() -> None:
    """Run from the source tree, the served bytes are the written ones — no copy."""
    assert mcp_package.source() == MCP


def test_the_archive_is_the_files_byte_for_byte() -> None:
    inside = members(mcp_package.build_archive())

    assert list(inside) == [f"{mcp_package.FOLDER}/{name}" for name in mcp_package.MEMBERS]
    for name in mcp_package.MEMBERS:
        assert inside[f"{mcp_package.FOLDER}/{name}"] == (MCP / name).read_bytes(), name


def test_two_builds_are_the_same_bytes() -> None:
    assert mcp_package.build_archive() == mcp_package.build_archive()


def test_every_member_carries_the_fixed_time() -> None:
    with zipfile.ZipFile(io.BytesIO(mcp_package.build_archive())) as opened:
        for info in opened.infolist():
            assert info.date_time == mcp_package.FIXED_TIME, info.filename


def test_nothing_in_the_package_depends_on_an_instance() -> None:
    """No address and no build: the program is told where it is when it starts."""
    for name, content in members(mcp_package.build_archive()).items():
        text = content.decode("utf-8")
        assert "%%" not in text, name
        assert "localhost" not in text and "127.0.0.1" not in text, name
        assert "build_id" not in text, name


def test_the_instructions_say_first_that_this_is_not_the_contract() -> None:
    """The first paragraph, not a later one: it is what a reader who stops early has read."""
    readme = (MCP / "README.md").read_text(encoding="utf-8")
    first = readme.split("\n\n")[1]

    assert first.startswith("**This MCP server is not the contract.**")
    assert "/openapi.json" in first and "/guide" in first


def test_the_instructions_name_the_limit_of_notifications() -> None:
    readme = (MCP / "README.md").read_text(encoding="utf-8")

    assert "does not wake a sleeping one" in readme.replace("\n", " ")


def test_the_instructions_name_the_variables_and_the_rule_for_identities() -> None:
    readme = " ".join((MCP / "README.md").read_text(encoding="utf-8").split())

    for variable in ("A2A_MCP_IDENTITIES", "A2A_MCP_ADDRESS", "A2A_MCP_TOKEN", "A2A_MCP_LABEL"):
        assert variable in readme, variable
    assert "With more than one identity, every call has to say which one acts" in readme
    assert "There is no default" in readme
    assert "lives only in that process" in readme and "writes no token to disk" in readme
    assert "simple-a2a://<label>/inbox" in readme
