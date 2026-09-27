"""The holdings on disk, maildir-style.

Realms, teams, identities, invitations, messages, files, notes. The state of a
thing is the directory it sits in, and a change of state is an atomic rename —
no lock lies on the path of anything. Nothing is ever deleted.

Knows nothing of HTTP, of surfaces.
"""
