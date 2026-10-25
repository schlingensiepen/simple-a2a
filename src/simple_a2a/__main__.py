"""The one entry point: the service itself.

There is no command line for operations. Everything an operator does goes either
through the three surfaces or through the means of their host, so a bare start
takes nothing — it reads the environment, opens the data directory, determines the
administration secret and serves. That bare start is what the image runs.

One word is understood beside it: `simple-a2a first-prompt` prints the first
prompt for an agent, with the administration secret in it, and does not start the
service. It is a helper, not an operation — it reads the secret the way the start
reads it and changes nothing — and it lives in `first_prompt`, with its reasons.
Anything else on the command line is refused rather than served: a misspelt
helper that quietly started a second service would be a puzzle, not a start.

**One process, one binding, three ports.** Not three processes: they would share the
data directory, and three writers on one directory would be three writers for no
reason. Each surface is its own application, each with its own self-description, and
none of them names another.

**A bare start works.** Nothing has to be set, nothing has to be read first. Every
surface is on, and switching one off is the intervention — done by emptying its port
variable. An unusable value stops the start and the message names the parameter,
because a service that comes up with half its configuration understood is a service
nobody can predict from its environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

import uvicorn

from simple_a2a import __version__, first_prompt
from simple_a2a.admin.app import build_app as build_admin
from simple_a2a.core import config, secret
from simple_a2a.core.paths import Layout as SecretLayout
from simple_a2a.domain.context import Context
from simple_a2a.messaging.app import build_app as build_messaging
from simple_a2a.observe.app import build_app as build_observe
from simple_a2a.store.holdings import Holdings
from simple_a2a.store.layout import Layout

logger = logging.getLogger("simple_a2a")

#: The build stamp, in its own namespace. `SIMPLE_A2A_*` belongs to the eight
#: operational parameters, and a build stamp is not one of them: it says which build
#: this is, which is a property of the artefact rather than a setting.
BUILD_VARIABLE = "A2A_BUILD"


def build_stamp() -> dict[str, str | None]:
    """What `GET /build` answers.

    The version does not move between two commits, so on its own it cannot answer the
    one question every deployment eventually asks. The build does.
    """
    import os

    return {
        "version": __version__,
        "build_id": os.environ.get(BUILD_VARIABLE, "unknown"),
        # When the image was built, as the build said — and nothing when it did not.
        # Filling in the start time made every restart claim a new build.
        "built_at": os.environ.get(f"{BUILD_VARIABLE}_AT") or None,
    }


def make_context(resolved: config.Config) -> tuple[Context, str | None]:
    """Open the holdings, work out the secret, and hand back both.

    The data directory is created here rather than on first write: a service that
    made it later would leave an operator unable to tell "not configured" from
    "nothing has happened yet".
    """
    holdings = Holdings(Layout(root=resolved.data_dir))
    holdings.prepare()
    found = secret.resolve(resolved, SecretLayout(root=resolved.data_dir))
    return (
        Context(
            holdings=holdings,
            config=resolved,
            admin_secret=found.value if found else None,
        ),
        found.value if found else None,
    )


def servers(context: Context, resolved: config.Config) -> list[uvicorn.Server]:
    """One server per surface that is on. A surface with no port is not built.

    Not built rather than built and unreachable: an application that exists and
    answers nowhere is a thing to wonder about later.
    """
    stamp = build_stamp()
    made = []
    for port, factory, name in (
        (resolved.port, build_messaging, "participants"),
        (resolved.admin_port, build_admin, "administration"),
        (resolved.observer_port, build_observe, "observation"),
    ):
        if port is None:
            logger.info("the %s surface is switched off: its port variable is empty", name)
            continue
        made.append(
            uvicorn.Server(
                uvicorn.Config(
                    factory(context, build=stamp),
                    host=resolved.bind,
                    port=port,
                    log_level="info",
                    access_log=False,
                )
            )
        )
    return made


async def serve(running: list[uvicorn.Server]) -> None:
    """Run them together, and stop together.

    One process, so one failure takes the rest down rather than leaving a half-served
    installation that looks healthy from one port.
    """
    async with asyncio.TaskGroup() as group:
        for server in running:
            group.create_task(server.serve())


def main(arguments: list[str] | None = None) -> int:
    given = sys.argv[1:] if arguments is None else arguments
    if given and given[0] == first_prompt.SUBCOMMAND:
        return first_prompt.main(given[1:])
    if given:
        print(
            f"simple-a2a takes no arguments; a bare start serves. The one word understood is "
            f"{first_prompt.SUBCOMMAND!r}, which prints the first prompt for an agent and "
            f"starts nothing — {first_prompt.USAGE}",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        resolved = config.load()
        context, _ = make_context(resolved)
    except config.ConfigError as exc:
        # The parameter is named and the process stops. A silent fallback would be a
        # service whose behaviour cannot be predicted from its environment.
        print(f"simple-a2a cannot start: {exc}", file=sys.stderr)
        return 2

    running = servers(context, resolved)
    if not running:
        print(
            "simple-a2a cannot start: every surface is switched off, so there is nothing "
            "to serve. Leave at least one port variable set.",
            file=sys.stderr,
        )
        return 2

    logger.info(
        "simple-a2a serving on %s, ports %s; holdings in %s",
        resolved.bind,
        ", ".join(str(server.config.port) for server in running),
        resolved.data_dir,
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(running))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
