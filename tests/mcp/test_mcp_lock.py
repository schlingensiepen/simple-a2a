"""The second lock: the MCP program reaches nothing but the standard library.

It runs beside an agent, on a machine that is not ours, so everything it imports is
something that has to be there and something that can break. And it reaches nothing
of the service: it is a client of the participant surface like any other, and the
moment it imported a module of the service it would be a second copy of its
knowledge, ageing on its own.

The check reads the imports rather than trusting them, and it is proven able to
fail: a lock that has never been seen shut looks exactly like one that is broken.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MCP = Path(__file__).resolve().parents[2] / "mcp"

#: The package of the service, which the program must never reach.
SERVICE = "simple_a2a"


def foreign_imports(source: str, filename: str = "<source>") -> list[str]:
    """Every import in `source` that is not the standard library, or is the service.

    A relative import counts as foreign: there is no package around the program,
    so one could only reach something that is not supposed to be there.
    """
    tree = ast.parse(source, filename=filename)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                targets = [node.module] if node.module else [a.name for a in node.names]
                found += ["." * node.level + target for target in targets]
                continue
            names = [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top == SERVICE or top not in sys.stdlib_module_names:
                found.append(name)
    return found


def program_files() -> list[Path]:
    found = sorted(MCP.rglob("*.py"))
    assert found, "no Python file under mcp/; this test would pass on nothing"
    return found


def test_every_import_of_the_program_is_the_standard_library() -> None:
    for path in program_files():
        foreign = foreign_imports(path.read_text(encoding="utf-8"), str(path))
        assert not foreign, f"{path.name} imports {foreign}; the program may use the stdlib only"


def test_the_lock_shuts_on_a_foreign_import() -> None:
    """The red probe: one smuggled import of each kind, and each one is caught."""
    smuggled = (
        "import json\n"
        "import requests\n"
        "from simple_a2a.core import tokens\n"
        "import simple_a2a\n"
        "from . import neighbour\n"
        "from urllib import parse\n"
    )

    found = foreign_imports(smuggled)

    assert found == ["requests", "simple_a2a.core", "simple_a2a", ".neighbour"]


def test_the_lock_shuts_on_an_import_hidden_inside_a_function() -> None:
    """An import in a function body is still an import — the walk goes everywhere."""
    hidden = "def later():\n    import yaml\n    return yaml\n"

    assert foreign_imports(hidden) == ["yaml"]


def test_the_program_says_the_release_it_ships_with() -> None:
    """Its version is the service's, because it is an artefact of the same release.

    Written twice — once in the program, which cannot ask the package — so the two
    are held together here.
    """
    import tomllib

    declared = tomllib.loads((MCP.parent / "pyproject.toml").read_text(encoding="utf-8"))
    tree = ast.parse((MCP / "simple_a2a_mcp.py").read_text(encoding="utf-8"))
    version = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    )

    assert version == declared["project"]["version"]
