"""Where things live under the data directory.

Only the parts that are not the holdings themselves live here: the root, the
place for temporary work, and the file the administration secret is kept in. How
realms, teams, messages and files are laid out is the business of the block that
owns them — a path layout written down in two places is two layouts as soon as
one of them moves.

The secret is the one thing that is deliberately *not* part of the holdings. It
has to be readable when there is nothing else at all, because otherwise a bare
start has no way in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from simple_a2a.core.atomic import ensure_private_directory

#: The file the generated administration secret is kept in, inside the data
#: directory, readable by its owner only.
ADMIN_SECRET_FILE = "admin-secret"


@dataclass(frozen=True)
class Layout:
    """The data directory, as paths rather than as strings."""

    root: Path

    @property
    def admin_secret(self) -> Path:
        return self.root / ADMIN_SECRET_FILE

    def prepare(self) -> None:
        """Make the data directory exist, owned and enterable by us alone.

        Called at start. A service that creates its data directory on first
        write instead leaves an operator unable to tell "not configured" from
        "nothing has happened yet".
        """
        ensure_private_directory(self.root)
