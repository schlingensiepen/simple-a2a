# Administering this installation

This administration creates the containers of a simple-a2a
installation and the secrets that let others use it. It shows
administrative state — names, marks, timestamps — and never content:
no message, no file, no body passes through here.

Addresses in this text are relative to the base address you fetched
it from. The administration token travels as an `Authorization:
Bearer <token>` header.

Nothing here is implicit. Every creating call creates exactly one
thing and names it, and the answer gives that thing back.

## Read this before the first call that creates something

**Nothing is deleted.** The holdings only grow. A name that has
been used stays used, forever, and a mistyped name creates
something that stays — untidy, and not removable. There is no
write-probe that creates something and tidies it away afterwards,
because there is nothing to tidy with. Check a name before you send
it.

**A secret is shown exactly once, in the answer that creates it.**
The service holds no secrets and hands none out: there is no call
that returns an existing secret, no replacement for a lost token,
and no listing with a value in it. Whatever you want to do with a
secret, do it with that one answer — there is no later, because
afterwards the value is nowhere.

**A secret and the address it belongs to travel together, or the
secret is lost.** What this service can say about its own address
is derived from the request that reached it, which is not
necessarily what the outside world reaches. Behind a proxy only you
know the public name, so handing it on is your job and not the
service's. Hand both halves over the same channel, and not a chat
window.

**Revoking ends a permission, not a thing.** The entry stays, with
a mark and a timestamp, and it stays readable, because messages from
a revoked identity are still lying in mailboxes and somebody has to
be able to look up who that was. The verb in the address is the
usual one for "take this away"; it does not mean anything
disappears.

**Appointing and revoking are deliberately asymmetric.** Whoever
may appoint may not depose. Otherwise two holders of the one right
could strip each other, and that needs an arbitration rule — which
is exactly the apparatus this service does without. This
administration is the only place where anything is revoked.

**There is no way to replace a lost token.** Whoever loses theirs is
invited again **under a new name** and introduces themselves to the
others; you cannot restore the old one, and the old name stays
taken. Do not promise anyone otherwise.

## The parts of this guide

- `/guide/first-access` — from a bare start to a team somebody can
  work in: taking the administration secret in hand, looking around
  without creating anything, realm, team, invitation, handover, and
  the one check that creates nothing.
- `/guide/realms` — the containers and the listings: creating a
  realm and a team, obtaining an invitation into a team, and
  reading which teams, members, central services and invitations
  exist.
- `/guide/tokens` — the secrets and their ends: issuing an observer
  token, revoking a member's token, a central service's token, the
  one right, an invitation, or an observer token, and what a
  repeated revocation says.
- `/guide/notes` — the global setup note and the one per realm: the
  place where you write down what you did, because this service
  knows nothing about that and only keeps what you put there.
