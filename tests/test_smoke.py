"""The smoke test, run here against a locally started instance.

The workflow runs it twice before anything is published — against the installed
wheel and against the built image. Here it runs against the entry point of this
tree, in process mode, so that a change that breaks one of its checks is found by
the ordinary suite rather than by a release. It takes about two seconds, which is
why it sits in the normal run instead of behind a marker.

Two things are held beyond "it passes": the addresses it derives from the running
instance are the ones the code builds, counted from a source it does not read; and
a check that does not hold makes it fail, with the check named.
"""

from __future__ import annotations

import importlib.util
import re
import socket
import sys
from pathlib import Path

import pytest

from simple_a2a.describe.guide import PARTS
from simple_a2a.describe.http import cascade

TOOL = Path(__file__).resolve().parents[1] / "tools" / "smoke.py"

#: The surfaces in the order the smoke test reports them, by the name the texts use.
SURFACES = (("participants", "messaging"), ("administration", "admin"), ("observation", "observe"))


def load_tool():
    spec = importlib.util.spec_from_file_location("smoke", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = load_tool()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run(tmp_path: Path, *extra: str) -> int:
    """The tool's own command line, with three free ports and nothing else set.

    The ports are the one departure from a bare start: the defaults may be taken on
    the machine running the suite. The tool reports them as set.
    """
    ports = [free_port() for _ in range(3)]
    return smoke.main(
        [
            f"--participants=http://127.0.0.1:{ports[0]}",
            f"--administration=http://127.0.0.1:{ports[1]}",
            f"--observation=http://127.0.0.1:{ports[2]}",
            *extra,
            "process",
            f"--work-dir={tmp_path / 'work'}",
            f"--env=SIMPLE_A2A_PORT={ports[0]}",
            f"--env=SIMPLE_A2A_ADMIN_PORT={ports[1]}",
            f"--env=SIMPLE_A2A_OBSERVER_PORT={ports[2]}",
            "--env=A2A_BUILD=0123abcd",
            "--env=A2A_BUILD_AT=2026-10-24T00:00:00Z",
        ]
    )


def expected_addresses() -> dict[str, int]:
    """How many token-free addresses each surface has, from the code that builds them.

    The fixed routes of the cascade, the guide parts the surface ships, and the
    interface description the framework adds. Counted without the description and
    without the entry page, which is what the smoke test reads.
    """
    counted = {}
    for reported, surface in SURFACES:
        router = cascade(surface, description="-", build={}, offers_mcp=surface == "messaging")
        fixed = [route for route in router.routes if "{" not in route.path]
        counted[reported] = len(fixed) + len(PARTS[surface]) + 1
    return counted


def test_the_smoke_test_passes_against_a_local_instance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run(tmp_path, "--expect-build=0123abcd", "--expect-built-at=2026-10-24T00:00:00Z")

    out = capsys.readouterr().out
    assert status == 0, out
    assert out.count("\nok ") + out.startswith("ok ") == 12, out
    assert "smoke test passed" in out
    # The secret is read from the log and used, and never repeated in the report.
    log = (tmp_path / "work" / "service.log").read_text(encoding="utf-8")
    generated = smoke.SECRET_LINE.search(log)
    assert generated is not None
    assert generated.group("secret") not in out


def test_it_finds_every_token_free_address_the_code_builds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path) == 0
    line = next(
        line for line in capsys.readouterr().out.splitlines() if "token-free addresses:" in line
    )
    found = {name: int(count) for name, count in re.findall(r"(\w+) (\d+)", line.split(":")[-1])}
    assert found == expected_addresses()


def test_a_check_that_does_not_hold_fails_the_run_and_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = run(tmp_path, "--expect-build=some-other-commit")

    out = capsys.readouterr().out
    assert status == 1
    assert "FAIL 12 the build stamp" in out
    assert "smoke test passed" not in out
