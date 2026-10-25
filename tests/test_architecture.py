"""The seven blocks keep to what they know.

Each block was given one responsibility and, next to it, a list of what it
knows nothing of. That second list is the load-bearing half: the names could
be anything, but the boundaries are what keep an operation from being written
twice and a surface from growing its own copy of the holdings.

The checks read the imports rather than trusting them, because an import is
both the cheapest way to break a boundary and the cheapest way to notice.
They parse whatever is there, so they are as true of an empty block as of a
full one, and they grow with the code instead of being remembered later.

What is *not* checked here: that the observation surface only ever reads. That
one is a property of its routes, not of its imports, and it is checked where
the routes are declared.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "simple_a2a"

BLOCKS = ("core", "store", "domain", "describe", "messaging", "admin", "observe")

SURFACES = ("messaging", "admin", "observe")

#: Names that mean "this module knows what HTTP is".
HTTP_NAMES = ("fastapi", "starlette", "uvicorn", "httpx")

#: For each block, the blocks of this service it may not reach.
#:
#: Two things are written into these lists, and it is worth saying which is
#: which. The **column** "knows nothing of" gives: no HTTP below the surfaces,
#: no surface reaching into the holdings' internals, `describe` blind to the
#: holdings. The **layering** — core and store at the bottom, domain above,
#: describe beside, three surfaces on top — gives the rest: that `store` does
#: not reach `domain`, that `domain` does not reach `describe`, that no surface
#: names another. Both are stated in the same place, so both are checked here;
#: the lists are therefore slightly stricter than the column read on its own,
#: and that is deliberate rather than an oversight.
#:
#: The reasons, briefly. `core` is at the bottom and reaches nothing. `store`
#: and `domain` are layered above it, each blind to everything over its head.
#: `describe` sits beside them and above `domain`: it renders what an operation
#: refused, so it has to know the refusals — but it stays blind to the holdings,
#: because an entry page that read them would answer differently on an empty
#: instance, which is precisely what it must not do. And no surface reaches
#: another: none of them names the operations of another, so none has a reason to
#: import one.
#:
#: `describe` was first written as blind to `domain` as well, and that was one
#: tightening too many: a refusal is stated in the words of teams and names, and
#: turning it into a rejection type with a text is this block's whole job. Doing
#: it in each of the three surfaces instead would be the same translation written
#: three times, which is the drift a single gate exists to prevent.
FORBIDDEN_BLOCKS: dict[str, tuple[str, ...]] = {
    "core": ("store", "domain", "describe", "messaging", "admin", "observe"),
    "store": ("domain", "describe", "messaging", "admin", "observe"),
    "domain": ("describe", "messaging", "admin", "observe"),
    "describe": ("store", "messaging", "admin", "observe"),
    "messaging": ("admin", "observe"),
    "admin": ("messaging", "observe"),
    "observe": ("messaging", "admin"),
}

#: The blocks that hold no HTTP at all. The three surfaces are the only place
#: where a request exists; below them a request is an argument list.
NO_HTTP = ("core", "store", "domain")


def modules_of(block: str) -> list[Path]:
    found = sorted((SRC / block).rglob("*.py"))
    assert found, f"the {block!r} block has no modules; this test would pass on nothing"
    return found


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_all_seven_blocks_are_there() -> None:
    """Seven directories, seven blocks, and each one importable.

    A block that quietly vanished would make every other check here pass on
    less than it was written for.
    """
    for block in BLOCKS:
        assert (SRC / block / "__init__.py").is_file(), f"the {block!r} block is missing"
    extra = {
        p.name
        for p in SRC.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and p.name not in BLOCKS
    }
    assert not extra, f"a directory beside the seven blocks: {sorted(extra)}"


def test_the_only_modules_outside_the_blocks_are_the_three_entry_points() -> None:
    """Three modules live beside the blocks, and each one is a way in from outside.

    `__main__` is the service, `probe` is the image asking itself whether it is
    healthy, and `first_prompt` is the one helper — it prints the first prompt for
    an agent, with the secret the service settled. None of them is a block: the
    first two may know what HTTP is because that is their whole job, and the third
    reads the secret and writes to standard output, which belongs to no block
    either. A fourth module appearing here should have to be noticed, as the
    third one was.
    """
    modules = {p.stem for p in SRC.glob("*.py")}

    assert modules == {"__init__", "__main__", "probe", "first_prompt"}


def test_the_helper_reads_the_secret_and_knows_nothing_else() -> None:
    """`first_prompt` reaches `core` and nothing above it.

    It prints a text with the secret in it; a helper that imported a surface, the
    holdings or the operations would be a second way to do something to the
    service, and there is deliberately only one — the surfaces themselves.
    """
    names = imported_modules(SRC / "first_prompt.py")
    reached = {name for name in names if name.startswith("simple_a2a.")}

    assert reached and all(name.startswith("simple_a2a.core") for name in reached), reached
    assert not any(name.split(".")[0] in HTTP_NAMES for name in names), names


@pytest.mark.parametrize("block", NO_HTTP)
def test_the_lower_blocks_know_nothing_of_http(block: str) -> None:
    """Below the surfaces there is no request, only arguments.

    A block down here that can read a request or render a response has taken
    on one caller's shape, and the next caller gets that shape with it.
    """
    for module in modules_of(block):
        for imported in imported_modules(module):
            assert not any(imported.split(".")[0] == name for name in HTTP_NAMES), (
                f"{block}/{module.name} imports {imported}; this block knows nothing of HTTP"
            )


@pytest.mark.parametrize("block", BLOCKS)
def test_a_block_reaches_no_block_it_knows_nothing_of(block: str) -> None:
    """The column, read as an import rule.

    An import in the wrong direction does not announce itself: everything
    still works, and the layering is gone. This is the announcement.
    """
    forbidden = tuple(f"simple_a2a.{other}" for other in FORBIDDEN_BLOCKS[block])
    for module in modules_of(block):
        for imported in imported_modules(module):
            assert not any(
                imported == name or imported.startswith(f"{name}.") for name in forbidden
            ), (
                f"{block}/{module.name} imports {imported}; this block knows nothing of "
                f"{imported.split('.')[1]}"
            )


@pytest.mark.parametrize("surface", SURFACES)
def test_a_surface_knows_the_holdings_only_from_the_outside(surface: str) -> None:
    """Nothing of the internals of the holdings — read literally.

    A surface may hand something to the holdings block; it may not know how
    that block lays out a directory. The difference is visible in the import:
    `simple_a2a.store` is the block, `simple_a2a.store.anything` is its
    inside, and once a surface knows the inside, a change of layout is a
    change to the surfaces.
    """
    for module in modules_of(surface):
        for imported in imported_modules(module):
            assert not imported.startswith("simple_a2a.store."), (
                f"{surface}/{module.name} imports {imported}; a surface knows the holdings "
                "only as a whole, never their internals"
            )
