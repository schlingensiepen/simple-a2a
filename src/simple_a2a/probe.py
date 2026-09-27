"""The image's own health probe: every surface that is configured answers.

This is what the image's health check runs. It is not a command line for the
operator — there is none — it is the container asking itself the one question a
container platform needs answered: should this be restarted.

Two things it deliberately does:

- **It reads the configuration** instead of a fixed port. A health check wired to
  8251 declares the container unhealthy forever if the operator switches the
  participant surface off by emptying its port — a configuration that is
  entirely correct — and a platform then restarts a working service in a loop.
- **It asks every surface that is on**, not one of them. One process serves all
  three, and a surface whose port failed to bind is invisible from any other.

And one thing it deliberately does not do: look at the holdings. `healthy` says
the process answers, and nothing more. A holdings check here would be a second
notion of health for a message dispatcher, and the thing that finds unreadable
holdings is the smoke test, which drives a whole token cycle.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

from simple_a2a.core import config

#: Where the probe knocks. Always the loopback address: it runs inside, and the
#: binding may be narrower than what the outside sees.
LOOPBACK = "127.0.0.1"

HEALTH_PATH = "/health"

TIMEOUT_SECONDS = 3.0


def ports_of(resolved: config.Config) -> list[int]:
    """The ports that are supposed to answer."""
    return [
        p for p in (resolved.port, resolved.admin_port, resolved.observer_port) if p is not None
    ]


def answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(  # a fixed loopback http address
            f"http://{LOOPBACK}:{port}{HEALTH_PATH}", timeout=TIMEOUT_SECONDS
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def main() -> int:
    try:
        resolved = config.load()
    except config.ConfigError as exc:
        # The service could not have started with this configuration either, so
        # unhealthy is the honest answer rather than an error about it.
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1

    ports = ports_of(resolved)
    if not ports:
        # Every surface switched off. Nothing can answer, and nothing should
        # claim to: a container serving nothing is not healthy, it is pointless.
        print("unhealthy: every surface is switched off", file=sys.stderr)
        return 1

    silent = [port for port in ports if not answers(port)]
    if silent:
        print(f"unhealthy: no answer on {', '.join(str(p) for p in silent)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
