"""Writing so that a reader never sees half of it.

The holdings are files, and the state of a thing is the directory it sits in. No
lock lies anywhere on the path of anything: a write goes to a temporary name in
the same directory, is flushed to disk, and is then moved into place with a
rename — which the filesystem does either completely or not at all.

Two consequences worth stating, because both are load-bearing:

- **The temporary name is in the same directory as the target.** A rename across
  filesystems is not atomic; it becomes a copy and a delete, and the guarantee
  is gone without anything failing.
- **The directory is flushed too, not only the file.** Without that, the file's
  contents are on disk and the name that points at them may not be, so a crash
  can leave an entry that is visible and empty.

This needs a local filesystem. On NFS the rename guarantee is not the one
assumed here, and that belongs in the deployment notes rather than in a comment
nobody reads in time.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: Owner only. Used for anything that is a secret, and harmless everywhere else.
PRIVATE_MODE = 0o600

#: Owner only, for directories.
PRIVATE_DIR_MODE = 0o700


def _flush_directory(directory: Path) -> None:
    """Make the directory entry itself durable.

    Wrapped rather than assumed: not every platform lets a directory be opened
    for this, and where it cannot be done the write is still no worse than an
    ordinary one.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_bytes(path: Path, data: bytes, *, mode: int = PRIVATE_MODE) -> None:
    """Put these bytes at this path, completely or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _flush_directory(path.parent)


def write_text(path: Path, text: str, *, mode: int = PRIVATE_MODE) -> None:
    """The same, for text. UTF-8, because everything here is UTF-8."""
    write_bytes(path, text.encode("utf-8"), mode=mode)


def move(source: Path, target: Path) -> None:
    """Change the state of a thing by moving it, in one step.

    `os.replace` rather than `os.rename`: on some platforms `rename` refuses an
    existing target, and a state change that fails only sometimes is worse than
    one that never does.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    _flush_directory(target.parent)
    if source.parent != target.parent:
        _flush_directory(source.parent)


def ensure_private_directory(path: Path) -> None:
    """A directory only its owner can enter, created if it is not there.

    The mode is set explicitly after creation as well: `mkdir`'s mode is masked
    by the process umask, so asking for 0700 and getting 0755 is normal and
    quiet.
    """
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, PRIVATE_DIR_MODE)
