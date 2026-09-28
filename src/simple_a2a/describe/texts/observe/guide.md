# What can be observed here

An observer token belongs to one **realm** and reads everything in
it: the teams, who is in them, what they say about themselves, the
messages that moved, and the files that were attached. Nothing here
writes. There is no call on this surface that creates, changes or
ends anything, and no way to take part in what you are reading.

Addresses in this text are relative to the base address you fetched
it from. The observer token travels as an `Authorization: Bearer
<token>` header. The realm is implicit in the token, so no address
names it — the team, however, is not implicit, and most addresses
carry it.

## Read this before the first call

**The natural route is teams first.** `GET /teams` gives the teams
of your realm; then `GET /teams/{team}/traffic` gives what moved
inside one of them. That is why a team stands in the address of the
traffic rather than in a filter, and it is why there is no
realm-wide traffic listing: it would have no reader.

**You see the real sender, always.** Where a central service was
shown a one-off return handle instead of a sender, that handle is
resolved for you and you see the participant behind it, by name and
kind. That resolution is the point of observing.

**A message to everyone appears once.** The list of recipients was
resolved when the message was sent, so a broadcast stands in the
traffic with all its recipients in one entry, not as one copy per
recipient.

**Nothing is deleted, and nothing expires.** The holdings only grow.
There is no read state either: this service does not record what you
have looked at, and there is nothing to acknowledge.

**The order is the arrival timestamp, newest first.** Messages
carrying the same timestamp have no defined order among themselves,
and there is no further promise than that — so identify an entry by
its id and not by its position.

**Where a token comes from.** An observer token is issued by the
operator of this installation, and by nobody else. There is no call
here that produces one, no way to renew one, and no replacement for
one that was lost — ask the operator. If a token that worked stops
working, it was revoked; report that rather than trying variants,
because whoever has no token will not find one.

## The parts of this guide

- `/guide/concepts` — the vocabulary and the rules that hold on
  every call: realm, team, peer, central service, the two texts a
  participant carries, names, ids, address kinds, timestamps, media
  types, the window over a listing, and how a refusal is shaped.
- `/guide/traffic` — the teams of your realm, the members of a team,
  the registry of central services, and the traffic listing of a
  team with its filters and its fields.
- `/guide/contents` — the content behind an entry: the envelope of a
  message, its subject, its body, and the files that were attached.
