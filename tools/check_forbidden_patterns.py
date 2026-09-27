#!/usr/bin/env python3
r"""Check a tree of files for text that must not be in it.

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

**A pattern is matched against the whole file, not line by line**, so one that
allows whitespace in the middle survives a line wrap. That matters more than it
sounds: prose gets rewrapped, and a host name broken across two lines is exactly
the copy that slips through. Write such a pattern with `\s*` where the wrap can
land — the sample in the second field is what proves you did.

**A path is checked as well as a file's contents.** A name can carry the thing
you are hunting for just as well as a line can.

**Nothing is skipped quietly.** A file that cannot be read as text — binary, or
an encoding this does not handle — is named in the report, not just counted, and
so is a symbolic link, which is listed rather than followed: following one leads
out of the tree you asked about, and into loops.

Usage:

    python tools/check_forbidden_patterns.py --patterns LIST --root DIR

There is a second mode, `--prove`, and it is the more important one. Point it at
a fixture written on purpose to be found, and it insists that **every** pattern
matches something there — naming the ones that did not. The per-pattern sample in
the list proves each pattern in isolation; this proves the whole chain: reading
the list, walking the tree, matching, reporting. A check that has never hit
anything has proved nothing, and one that hits with two of its twenty patterns
has proved two.

Exit status: 0 when nothing matched and every pattern proved itself, 1 when
something matched, 2 when the list or the arguments were unusable. Under
`--prove` the sense is reversed: 0 when every pattern matched something, 1 when
any pattern matched nothing.
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
    """One match: which pattern, where, and what it sat in."""

    pattern: Pattern
    path: Path
    line_number: int
    line: str
    #: True when the match was in the path rather than in the contents.
    in_path: bool = False


@dataclass(frozen=True)
class Skipped:
    """A file that was not searched, and why. Named, never merely counted."""

    path: Path
    reason: str


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


#: Byte-order marks that say which encoding a file is in. UTF-16 is the reason
#: this list exists: such a file is full of NUL bytes, so a plain "is there a
#: NUL" test calls it binary and skips it — with the forbidden text sitting in
#: it, in plain sight of anyone who opens it in an editor.
BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


def read_as_text(path: Path) -> str | None:
    """The file's text, or `None` when it is not text at all.

    The byte-order mark is consulted first, because the usual "a NUL byte means
    binary" test gets UTF-16 exactly wrong. After that a NUL really does mean
    binary, and decoding is forgiving: a file that is mostly UTF-8 with a few
    bad bytes is still worth searching, and the bad bytes cannot hide anything
    the patterns are looking for.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for mark, encoding in BOMS:
        if raw.startswith(mark):
            try:
                return raw.decode(encoding, errors="replace")
            except (LookupError, UnicodeError):
                return None
    if b"\x00" in raw[:SNIFF_BYTES]:
        return None
    return raw.decode("utf-8", errors="replace")


def entries_under(root: Path, skip: frozenset[str]) -> tuple[list[Path], list[Skipped]]:
    """Every file under the root, and the links that were listed instead.

    A symbolic link is not followed — that leads out of the tree and into loops
    — but it is reported. A link that vanishes from the report altogether is
    indistinguishable from an empty directory, which is the one thing a check
    like this must never look like.
    """
    files: list[Path] = []
    skipped: list[Skipped] = []
    for path in sorted(root.rglob("*")):
        if any(part in skip for part in path.parts):
            continue
        if path.is_symlink():
            skipped.append(Skipped(path=path, reason="symbolic link, not followed"))
            continue
        if path.is_file():
            files.append(path)
    return files, skipped


def _line_of(text: str, offset: int) -> tuple[int, str]:
    """Which line an offset falls on, and that line's text."""
    number = text.count("\n", 0, offset) + 1
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return number, text[start : end if end != -1 else len(text)]


def scan(
    root: Path, patterns: list[Pattern], skip: frozenset[str]
) -> tuple[list[Hit], list[Skipped]]:
    """Walk the tree. Returns the matches and the files that were not searched."""
    hits: list[Hit] = []
    files, skipped = entries_under(root, skip)
    for path in files:
        relative = path.relative_to(root).as_posix()
        for pattern in patterns:
            if pattern.regex.search(relative):
                # The name carries it. Reported as line 0, because there is no
                # line: the finding is the path itself.
                hits.append(
                    Hit(
                        pattern=pattern,
                        path=path,
                        line_number=0,
                        line=relative,
                        in_path=True,
                    )
                )
        text = read_as_text(path)
        if text is None:
            skipped.append(Skipped(path=path, reason="not readable as text"))
            continue
        for pattern in patterns:
            # Searched over the whole file rather than line by line, so that a
            # pattern written to tolerate whitespace still finds what a line wrap
            # split in half.
            for match in pattern.regex.finditer(text):
                number, line = _line_of(text, match.start())
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
    parser.add_argument(
        "--prove",
        action="store_true",
        help="invert: every pattern must match something in the tree, and the ones that "
        "match nothing are named. For a fixture written on purpose to be found.",
    )
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

    skips = frozenset(DEFAULT_SKIP) | set(args.skip)
    hits, skipped = scan(args.root, patterns, skips)

    if args.prove:
        matched = {hit.pattern.source for hit in hits}
        missing = [p for p in patterns if p.source not in matched]
        for pattern in missing:
            print(
                f"error: {args.patterns}:{pattern.line_number}: {pattern.source!r} matched "
                "nothing in the fixture, so nothing proves it works end to end",
                file=sys.stderr,
            )
        if not args.quiet:
            print(
                f"{len(patterns) - len(missing)} of {len(patterns)} patterns matched the "
                f"fixture; {len(skipped)} files skipped",
                file=sys.stderr,
            )
        return 1 if missing else 0

    for hit in hits:
        where = "in the name" if hit.in_path else str(hit.line_number)
        print(f"{hit.path}:{where}: {hit.pattern.source} :: {hit.line.strip()}")
    if not args.quiet:
        # Every skipped file by name, not just a count. A number tells nobody
        # which file went unsearched, and that is the one place something can
        # sit unseen after a green run.
        for entry in skipped:
            print(f"skipped {entry.path}: {entry.reason}", file=sys.stderr)
        searched = len(entries_under(args.root, skips)[0]) - sum(
            1 for entry in skipped if entry.reason == "not readable as text"
        )
        print(
            f"{len(patterns)} patterns, all proved; {searched} files searched, "
            f"{len(skipped)} skipped; {len(hits)} matches",
            file=sys.stderr,
        )
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
