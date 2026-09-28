"""simple-a2a: a server over which software agents talk to each other.

The service carries and keeps messages, holds the directories in which agents
find one another and the central services of their realm, and explains itself.
It never looks at what a message says.

Three surfaces, one process, three ports: participants, administration,
observation. Seven blocks, each with one responsibility and an explicit list
of what it knows nothing of — `tests/test_architecture.py` is what keeps that
list true.
"""

#: The package version, read from the installed metadata rather than written twice.
#: Two places for one number is how they come to disagree.
try:  # pragma: no cover - depends on how the package was installed
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("simple-a2a")
except (ImportError, PackageNotFoundError):  # pragma: no cover
    # Run from a source tree without being installed. Saying so is better than
    # claiming a version nobody has.
    __version__ = "0.0.0.dev0"
