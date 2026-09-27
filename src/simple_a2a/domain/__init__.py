"""The operations, each written exactly once.

Create a realm, create a team, obtain an invitation and redeem it, revoke,
send, deliver, resolve recipients, find or assign an alias, check a name.

Several of these are reachable from two surfaces. Were each surface to carry
its own copy, the copies would drift apart the moment somebody touched one —
which is why they live here instead.

Knows nothing of HTTP, of surfaces.
"""
