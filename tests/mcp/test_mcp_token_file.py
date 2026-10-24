"""Reading a token file, in process: what is looked at before anything is opened.

Opening a device can have effects of its own, so a path that is not an ordinary
file is refused from what `stat` says, without being opened. A file replaced
between that look and the opening is refused too, rather than read.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

PROGRAM = Path(__file__).resolve().parents[2] / "mcp" / "simple_a2a_mcp.py"
TOKEN = "a" * 20 + "-" + "B" * 22


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("simple_a2a_mcp", PROGRAM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


mcp = _load()


def opened_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every path `os.open` is called with from now on."""
    calls: list[str] = []
    real = os.open

    def recording(path: Any, *args: Any, **kwargs: Any) -> int:
        calls.append(os.fspath(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording)
    return calls


def special(kind: str, tmp_path: Path) -> Path:
    if kind == "directory":
        return tmp_path
    if kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("no named pipes here")
        os.mkfifo(tmp_path / "pipe")
        return tmp_path / "pipe"
    if not Path("/dev/null").exists():
        pytest.skip("no /dev/null here")
    return Path("/dev/null")


@pytest.mark.parametrize("kind", ["directory", "fifo", "device"])
def test_what_is_not_an_ordinary_file_is_refused_without_being_opened(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = special(kind, tmp_path)
    calls = opened_paths(monkeypatch)

    with pytest.raises(mcp.TokenFileError) as refused:
        mcp.token_from_file(str(path))

    assert calls == [], "opened before it was looked at"
    assert str(path) in str(refused.value)


def test_an_ordinary_file_is_read(tmp_path: Path) -> None:
    held = tmp_path / "t"
    held.write_text(TOKEN + "\n")
    held.chmod(0o600)

    assert mcp.token_from_file(str(held)) == (TOKEN, None)


def test_a_file_replaced_between_looking_and_opening_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held, other = tmp_path / "t", tmp_path / "other"
    held.write_text(TOKEN + "\n")
    other.write_text("c" * 43 + "\n")
    held.chmod(0o600)
    other.chmod(0o600)
    real = os.open

    def swapping(path: Any, *args: Any, **kwargs: Any) -> int:
        if os.fspath(path) == str(held):
            os.replace(other, held)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping)

    with pytest.raises(mcp.TokenFileError) as refused:
        mcp.token_from_file(str(held))

    said = str(refused.value)
    assert "replaced" in said and str(held) in said
    assert TOKEN not in said and "c" * 43 not in said
