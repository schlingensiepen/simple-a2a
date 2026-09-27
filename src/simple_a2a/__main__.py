"""The one entry point: the service itself.

There is no command line for operations. Everything an operator does goes
either through the three surfaces or through the means of their host, so this
module takes no subcommand and no argument — it reads the environment, opens
the data directory, determines the administration secret and serves.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Start the service. Not implemented yet."""
    print(
        "simple-a2a: this is the project scaffolding; the service is not built yet.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
