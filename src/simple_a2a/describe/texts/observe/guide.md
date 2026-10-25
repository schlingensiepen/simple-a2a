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
inside one of them. Why the team stands in that address, and why
there is no realm-wide traffic listing, is in `/guide/traffic`,
section "The traffic of a team".

**You see the real sender, always.** The one-off return handle a
central service is shown is resolved for you; `/guide/concepts`,
section "Address kinds, and why you never see a return handle",
says what that handle is.

**A message to everyone appears once,** with all its recipients in
one entry; `/guide/traffic`, section "The traffic of a team", says
why.

**Nothing is deleted, and nothing expires.** The holdings only grow.
There is no read state either: this service does not record what you
have looked at, and there is nothing to acknowledge.

**The order is the arrival timestamp, newest first,** and position
is no identity: `/guide/concepts`, section "Answers, and the three
shapes they come in", says what is promised about the order and
what is not.

**Where a token comes from.** An observer token is issued by the
operator of this installation, and by nobody else. There is no call
here that produces one, no way to renew one, and no replacement for
one that was lost — ask the operator. If a token that worked stops
working, it was revoked; report that rather than trying variants,
because whoever has no token will not find one.

## The parts of this guide

- `/guide/concepts` — the vocabulary and the rules that hold on
  every call: realm, team, peer, central service, the two texts a
  participant carries, names, ids, address kinds and the return
  handle you never see, timestamps, media types, the order of the
  holdings, the window over a listing, the limits, and how a refusal
  is shaped.
- `/guide/traffic` — the teams of your realm, the members of a team,
  the registry of central services, and the traffic listing of a
  team: why a team stands in its address, its fields, how a
  broadcast appears, and its filters.
- `/guide/contents` — the content behind an entry: the envelope of a
  message, its subject, its body, the attachment list and how its
  sizes are counted, and the files that were attached.
