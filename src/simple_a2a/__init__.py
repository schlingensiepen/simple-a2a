"""simple-a2a: a server over which software agents talk to each other.

The service carries and keeps messages, holds the directories in which agents
find one another and the central services of their realm, and explains itself.
It never looks at what a message says.

Three surfaces, one process, three ports: participants, administration,
observation. Seven blocks, each with one responsibility and an explicit list
of what it knows nothing of — `tests/test_architecture.py` is what keeps that
list true.
"""
