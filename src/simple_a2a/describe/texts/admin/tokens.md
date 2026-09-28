# The secrets, and how they end

Every secret this installation knows names one capability at one
place. It carries no field of rights and no grading: whoever
presents it is the one entitled. That is why there is nothing to
inspect about a secret and nothing to adjust on it — there is only
creating it and ending it.

Addresses here are relative to the base address you fetched this
text from. The administration token travels as an `Authorization:
Bearer <token>` header.

## Two rules that decide everything else

**A secret is shown exactly once, in the answer that creates it.**
The service holds none and hands none out. There is no call that
returns an existing secret, no replacement for a lost one, and no
listing carrying a value. A secret comes into being with the thing
it belongs to, and that one answer is the only moment anything can
be done with it — there is no later, because afterwards the value is
nowhere.

**A listing names a secret, it does not show it.** Invitations and
observer tokens have no name of their own to grasp them by, so each
is given a `display_name` when it is issued. Listing and revoking
run over that name, never over the secret. A display name is unique
per kind within a realm — an invitation does not block an observer's
name — and it obeys the ordinary name rules: letters, digits,
underscore, hyphen and space, 1 to 64 characters, compared without
regard to case, edge and doubled spaces refused, a collision refused
with status 409.

## What can be created here

`POST /realms/{realm}/teams/{team}/invitations` obtains an
invitation into a team: `member_name`, `member_mission`,
`display_name`, and out comes the `display_name`, the `invitation` in
clear text, and `team_name`. Whoever redeems it becomes a realm
master, with no parameter and no choice.

`POST /realms/{realm}/observer-tokens` issues an **observer token**
for a realm: `display_name` in, and out comes the `display_name` and
the `token` in clear text. You may issue one whenever you like, and
again after a revocation; several may exist side by side, each
reachable by its own display name. An observer token reads
everything in its realm, attachments included, and writes nothing.

`GET /realms/{realm}/observer-tokens` lists them with
`display_name`, `issued_at` and `token_revoked` — never the secret.
Like every listing here it is a window over a list: `offset`, default
0, and `limit`, default 25, at most 100, both as query parameters.
Asking for more than 100 is refused and you are told the limit, since
silently shortening would suggest you had reached the end.

An invitation is not a token. It is a voucher: handed on, exchanged
**once** for a token, and then spent. Hand it over together with the
address the installation is reached by and never apart from it, over
a channel that is not a chat window, and then forget it.

## What can be revoked here

This is the only place where anything is revoked, and every
revocation takes effect immediately.

| Call | What it ends |
|---|---|
| `DELETE /realms/{realm}/teams/{team}/members/{name}/token` | a member's token; answers `member_name`, `token_revoked`, `revoked_at` |
| `DELETE /realms/{realm}/services/{name}/token` | a central service's token; answers `service_name`, `token_revoked`, `revoked_at` |
| `DELETE /realms/{realm}/teams/{team}/members/{name}/realmmaster` | the realm master right of a member; answers `member_name`, `is_realm_master`. The token stays valid and the identity stays in its team |
| `DELETE /realms/{realm}/invitations/{display_name}` | an invitation; answers `display_name`, `revoked`, `revoked_at` |
| `DELETE /realms/{realm}/observer-tokens/{display_name}` | an observer token; answers `display_name`, `token_revoked`, `revoked_at` |

Names in an address are percent-encoded, because a name may contain
spaces.

**The verb says take away, not delete.** A revocation ends a
permission, not a thing. The entry stays, with its mark and its
timestamp, and it stays readable — messages from a revoked identity
are still lying in mailboxes, and somebody has to be able to look up
who that was. That is also why the name stays taken. The answer
shows it by going on naming the thing.

**Revoking is repeatable.** A revocation of something already
revoked **succeeds and says so**: `revoked_at` carries the timestamp
of the **first** revocation, so a second attempt tells you it has
happened before without needing a warning or a second refusal type.
You should not have to guess whether your first attempt arrived.

**Delivery to a revoked identity continues.** Nothing is deleted,
the mailbox goes on collecting, and the identity still counts when a
sender addresses everyone in a team. What a revocation ends is the
ability to act with that token, not the existence of the identity.

**Invitations outlive the revocation of their issuer.** Revoking a
member's token leaves the invitations that member issued redeemable.
They have to be revoked **one at a time**, and
`GET /realms/{realm}/invitations` names `issued_by` so that you can
find them — which means that after revoking a token you have to go
and look.

**A revoked token never comes back, and there is no replacement.**
Whoever loses a token, or has one revoked, is invited again **under
a new name** and introduces themselves to the others; the old name
stays taken forever. Whoever presents a revoked token is told
exactly that way, and not to ask you, because you cannot walk it for
them.

## Appointing is not the mirror of revoking

The realm master right sits on an identity, bound to it, and not in
a token — a token that merely asserted a property would be worse
than an honestly kept right, and a right does not sit in a string
you can hand out. It permits two things: obtaining an invitation for
a central service, and appointing further realm masters inside one's
own team. Every token you obtain from this administration carries
it.

Appointing happens inside a team, by someone who already has the
right. Removing it happens only here. The asymmetry is deliberate:
if whoever may appoint could also depose, two holders could strip
each other, and then an arbitration rule is needed — which is
exactly the apparatus this service does without.

And it stays the only right stored on an identity. Everything else
is a capability of a token or of an id.

## What a stolen secret can do

Worth knowing before you hand one out, because it decides how
carefully each has to travel.

| Stolen | Can | Cannot |
|---|---|---|
| a member's token | read that identity's mailbox, send in its name, invite into **that** team, create further teams in the realm | revoke anything, read a realm as a whole, see other teams, reach another realm |
| the same with the realm master right | in addition obtain invitations for central services and appoint further realm masters in its own team | give the right away or take it from anyone |
| a central service's token | read that service's whole mailbox, answer what it received, fetch by id, deposit files | start an exchange, see a team, read the registry, reach a service |
| an observer token | read everything in its realm, attachments included | write anything, see beyond that realm |
| the administration token | the installation | — |
| an invitation | occupy **once** an identity under the name it was issued for | anything more; after that it is spent |

A secret is only valid at the place it belongs to, and an id is only
valid inside its own realm. In one sentence: a stolen participant
secret compromises one identity in one team, a stolen observer token
one realm, and a stolen administration token the installation.

## What none of this includes

No login, no accounts, no key ring, no vault. Against an attacker
who already has the rights of the process using a secret, local
indirection is theatre, and pretending otherwise would be the more
expensive mistake. Nothing expires, either: no token, no invitation.
A secret ends by being revoked, an invitation by being used.
