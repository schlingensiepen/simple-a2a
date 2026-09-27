"""The package is installed, importable, and has the entry point it promises.

Small checks, and they are here because each one has a failure mode that costs
an afternoon: a block directory that never made it into the wheel, an entry
point named in the metadata but not in the code, a console script that imports
something that is not there.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

import simple_a2a

BLOCKS = ("core", "store", "domain", "describe", "messaging", "admin", "observe")

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.mark.parametrize("block", BLOCKS)
def test_every_block_imports(block: str) -> None:
    assert importlib.import_module(f"simple_a2a.{block}").__doc__, (
        f"the {block!r} block has no docstring; its responsibility and its boundary "
        "are supposed to be written where the code is"
    )


def test_the_console_script_points_at_something_that_exists() -> None:
    """The name in the metadata and the function in the code are two places."""
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    target = metadata["project"]["scripts"]["simple-a2a"]
    module_name, _, attribute = target.partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute)), f"{target} is not callable"


def test_the_package_says_what_it_is() -> None:
    assert simple_a2a.__doc__
