#!/usr/bin/env python3
"""Check a tree of files for text that must not be in it.

Every project has strings that are fine in a private note and wrong in a
published repository: an internal host name, a customer's name, a path from
somebody's laptop, an identifier from a tracker nobody outside can read. They
get in by being copied, one line at a time, and they are found by accident
months later.

This is the check. It takes a list of patterns and a directory, and it says
which files match. Nothing is built in: the patterns come from a file you
point it at, so this repository holds the tool and yours holds the list —
which is what you want anyway, because the list itself is usually the last
thing you would publish.

The list is a TSV file, one pattern per line, two tab-separated fields:

    regex<TAB>a sample of text this pattern must match
    # lines starting with a hash are comments; blank lines are ignored

The second field is not documentation, it is the point. A check like this
fails *silently*: a typo in a pattern reports "clean" every single day, and
looks exactly like success. So each pattern must come with a sample it is
supposed to match, the tool tries it before it scans anything, and a pattern
that cannot match its own sample is an error — not a warning. A check that has
never hit anything has proved nothing.

Usage:

    python tools/check_forbidden_patterns.py --patterns LIST --root DIR

Exit status: 0 when nothing matched and every pattern proved itself, 1 when
something matched, 2 when the list or the arguments were unusable. Binary
files are skipped; so are `.git`, `.venv`, caches and anything else named with
`--skip`.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Directory names skipped by default: version control, virtual environments
#: and tool caches. None of them is content, and the first one would otherwise
#: dominate every report.
DEFAULT_SKIP = (".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache")

#: How much of a file is read to decide whether it is text. A NUL byte in the
#: first few kilobytes is the usual test and is good enough here: the cost of
#: being wrong is a skipped file, reported as skipped.
SNIFF_BYTES = 8192


@dataclass(frozen=True)
class Pattern:
    """One line of the list: a compiled regex and the sample proving it works."""

    source: str
    sample: str
    regex: re.Pattern[str]
    line_number: int


@dataclass(frozen=True)
class Hit:
    """One match: which pattern, which file, which line."""

    pattern: Pattern
    path: Path
    line_number: int
    line: str


def load_patterns(path: Path, *, ignore_case: bool = True) -> list[Pattern]:
    """Read the list. Raises ValueError on anything unusable."""
    patterns: list[Pattern] = []
    flags = re.IGNORECASE if ignore_case else 0
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" not in line:
            raise ValueError(
                f"{path}:{number}: no tab on this line. Every pattern needs a sample it "
                "must match, separated by a tab — a pattern nobody proved is a pattern "
                "that reports success forever."
            )
        source, _, sample = line.partition("\t")
        source, sample = source.strip(), sample.strip()
        if not source or not sample:
            raise ValueError(f"{path}:{number}: both the pattern and the sample must be there")
        try:
            regex = re.compile(source, flags)
        except re.error as exc:
            raise ValueError(f"{path}:{number}: {source!r} is not a valid regex: {exc}") from exc
        patterns.append(Pattern(source=source, sample=sample, regex=regex, line_number=number))
    if not patterns:
        raise ValueError(f"{path}: no patterns; a check with an empty list always passes")
    return patterns


def unproven(patterns: list[Pattern]) -> list[Pattern]:
    """The patterns that do not match their own sample."""
    return [p for p in patterns if not p.regex.search(p.sample)]


def is_text(path: Path) -> bool:
    try:
        head = path.open("rb").read(SNIFF_BYTES)
    except OSError:
        return False
    return b"\x00" not in head


def files_under(root: Path, skip: frozenset[str]) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in skip for part in path.parts):
            continue
        if path.is_file() and not path.is_symlink():
            found.append(path)
    return found


def scan(root: Path, patterns: list[Pattern], skip: frozenset[str]) -> tuple[list[Hit], list[Path]]:
    """Walk the tree. Returns the matches and the files that were skipped."""
    hits: list[Hit] = []
    skipped: list[Path] = []
    for path in files_under(root, skip):
        if not is_text(path):
            skipped.append(path)
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(path)
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern in patterns:
                if pattern.regex.search(line):
                    hits.append(Hit(pattern=pattern, path=path, line_number=number, line=line))
    return hits, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_forbidden_patterns",
        description="Check a tree of files for text that must not be in it.",
    )
    parser.add_argument("--patterns", required=True, type=Path, help="the TSV list of patterns")
    parser.add_argument("--root", default=Path("."), type=Path, help="the tree to check")
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="NAME",
        help="a path component to skip, repeatable; adds to the defaults",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="match case exactly; patterns are case-insensitive by default",
    )
    parser.add_argument("--quiet", action="store_true", help="print matches only, no summary line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    try:
        patterns = load_patterns(args.patterns, ignore_case=not args.case_sensitive)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    broken = unproven(patterns)
    if broken:
        for pattern in broken:
            print(
                f"error: {args.patterns}:{pattern.line_number}: {pattern.source!r} does not "
                f"match its own sample {pattern.sample!r}",
                file=sys.stderr,
            )
        print(
            "error: a pattern that cannot match its own sample would report success forever",
            file=sys.stderr,
        )
        return 2

    hits, skipped = scan(args.root, patterns, frozenset(DEFAULT_SKIP) | set(args.skip))
    for hit in hits:
        print(f"{hit.path}:{hit.line_number}: {hit.pattern.source} :: {hit.line.strip()}")
    if not args.quiet:
        checked = len(files_under(args.root, frozenset(DEFAULT_SKIP) | set(args.skip)))
        print(
            f"{len(patterns)} patterns, all proved; {checked - len(skipped)} text files checked, "
            f"{len(skipped)} skipped; {len(hits)} matches",
            file=sys.stderr,
        )
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
