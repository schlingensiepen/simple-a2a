"""The pattern check finds what it is pointed at — and says so when it cannot.

Two halves matter here and only one of them is obvious. The obvious half is
that a forbidden string in a file is reported. The other half is that a check
like this fails silently: a pattern that matches nothing looks exactly like a
clean tree, every day, until somebody notices years of green meant nothing. So
the tool refuses to run a pattern that cannot match its own sample, and that
refusal is tested here as carefully as the finding is.

The deliberate hit — a file written on purpose to be found — is the only thing
that proves the machinery works at all.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check_forbidden_patterns.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("check_forbidden_patterns", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = load_tool()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_deliberate_hit_is_found(tmp_path: Path) -> None:
    """The counter-test. A check that has never hit anything has proved nothing."""
    patterns = write(tmp_path / "list.tsv", "internal\\.example\tinternal.example\n")
    root = tmp_path / "tree"
    write(root / "docs" / "page.md", "See https://internal.example/runbook for the rest.\n")
    write(root / "src" / "fine.py", "x = 1\n")

    hits, skipped = check.scan(root, check.load_patterns(patterns), frozenset(check.DEFAULT_SKIP))

    assert len(hits) == 1
    assert hits[0].path.name == "page.md"
    assert hits[0].line_number == 1
    assert not skipped


def test_a_clean_tree_is_clean(tmp_path: Path) -> None:
    patterns = write(tmp_path / "list.tsv", "internal\\.example\tinternal.example\n")
    root = tmp_path / "tree"
    write(root / "README.md", "Nothing to see here.\n")

    hits, _ = check.scan(root, check.load_patterns(patterns), frozenset(check.DEFAULT_SKIP))

    assert hits == []


def test_a_pattern_that_cannot_match_its_own_sample_is_an_error(tmp_path: Path) -> None:
    """The silent-failure guard. A typo must cost a red run, not nothing."""
    patterns = write(tmp_path / "list.tsv", "intrenal\\.example\tinternal.example\n")

    broken = check.unproven(check.load_patterns(patterns))

    assert [p.source for p in broken] == ["intrenal\\.example"]


def test_a_line_without_a_sample_is_refused(tmp_path: Path) -> None:
    patterns = write(tmp_path / "list.tsv", "internal\\.example\n")

    with pytest.raises(ValueError, match="no tab"):
        check.load_patterns(patterns)


def test_an_empty_list_is_refused(tmp_path: Path) -> None:
    """An empty list would pass on everything, which is worse than no check."""
    patterns = write(tmp_path / "list.tsv", "# only a comment\n\n")

    with pytest.raises(ValueError, match="no patterns"):
        check.load_patterns(patterns)


def test_a_broken_regex_is_refused(tmp_path: Path) -> None:
    patterns = write(tmp_path / "list.tsv", "a(b\tab\n")

    with pytest.raises(ValueError, match="not a valid regex"):
        check.load_patterns(patterns)


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    patterns = write(
        tmp_path / "list.tsv",
        "# a heading\n\nfirst\tfirst\n  # indented comment\nsecond\tsecond\n",
    )

    loaded = check.load_patterns(patterns)

    assert [p.source for p in loaded] == ["first", "second"]
    assert [p.line_number for p in loaded] == [3, 5]


def test_matching_ignores_case_unless_told_otherwise(tmp_path: Path) -> None:
    patterns = write(tmp_path / "list.tsv", "secret\tSECRET\n")
    root = tmp_path / "tree"
    write(root / "notes.txt", "A Secret slipped in.\n")

    loose = check.load_patterns(patterns)
    strict = check.load_patterns(patterns, ignore_case=False)

    assert check.scan(root, loose, frozenset(check.DEFAULT_SKIP))[0]
    assert not check.scan(root, strict, frozenset(check.DEFAULT_SKIP))[0]


def test_a_binary_file_is_skipped_and_reported_as_skipped(tmp_path: Path) -> None:
    """Skipping quietly would be a hiding place; the count says how many."""
    patterns = write(tmp_path / "list.tsv", "secret\tsecret\n")
    root = tmp_path / "tree"
    root.mkdir()
    (root / "blob.bin").write_bytes(b"secret\x00\x01\x02")

    hits, skipped = check.scan(root, check.load_patterns(patterns), frozenset(check.DEFAULT_SKIP))

    assert hits == []
    assert [p.name for p in skipped] == ["blob.bin"]


def test_the_default_skips_keep_version_control_out(tmp_path: Path) -> None:
    patterns = write(tmp_path / "list.tsv", "secret\tsecret\n")
    root = tmp_path / "tree"
    write(root / ".git" / "COMMIT_EDITMSG", "secret\n")
    write(root / "kept.md", "clean\n")

    hits, _ = check.scan(root, check.load_patterns(patterns), frozenset(check.DEFAULT_SKIP))

    assert hits == []


def test_the_exit_status_says_which_of_the_three_outcomes_it_was(tmp_path: Path) -> None:
    """0 clean, 1 something matched, 2 the list or the arguments were unusable."""
    root = tmp_path / "tree"
    write(root / "page.md", "internal.example\n")
    good = write(tmp_path / "good.tsv", "internal\\.example\tinternal.example\n")
    typo = write(tmp_path / "typo.tsv", "intrenal\\.example\tinternal.example\n")
    clean = write(tmp_path / "clean.tsv", "nowhere-at-all\tnowhere-at-all\n")

    assert check.main(["--patterns", str(good), "--root", str(root), "--quiet"]) == 1
    assert check.main(["--patterns", str(clean), "--root", str(root), "--quiet"]) == 0
    assert check.main(["--patterns", str(typo), "--root", str(root), "--quiet"]) == 2
    assert check.main(["--patterns", str(good), "--root", str(tmp_path / "nope")]) == 2
