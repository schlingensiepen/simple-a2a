# The containers, and what the listings show

A **realm** encloses exactly one **registry** of central services
and holds the **teams**. A team lies in exactly one realm. An
**identity** is a member in a team: two pieces of information, not a
compound name, and the same name in another team is a different
identity. A **central service** belongs to one realm and stands in
its registry; it has no team.

For the participants inside a realm, the realm is not visible — for
them it is the universe. It is a nameable thing here and nowhere
else.

Addresses here are relative to the base address you fetched this
text from. The administration token travels as an `Authorization:
Bearer <token>` header.

## Names, and why a collision is refused rather than reused

A name is letters, digits, underscore, hyphen and space, 1 to 64
characters. Names are compared without regard to upper and lower
case, so that two spellings do not end up as two participants in one
team. Leading, trailing and doubled spaces are **refused, not
trimmed**: if the service kept a different name from the one you
sent, the two would disagree from then on.

A name that is taken is refused with status 409 rather than quietly
reused, so a typo shows itself at the refusal instead of creating a
second thing that looks like the first. And a name stays taken
permanently, because nothing is deleted — a revoked identity holds
its name, and an invitation issued under a name that is already
taken will keep being refused.

Team member names are unique per team, central service names per
realm. A display name — the handle of an invitation or an observer
token — is unique per kind within a realm, so an invitation does not
block an observer's name.

Names in an address are percent-encoded, because a name may contain
spaces.

## Creating

`POST /realms` takes `realm_name` and answers with the name.
**No secret**: a realm is a container, and an empty one is allowed —
idle, but allowed.

`POST /realms/{realm}/teams` takes `team_name` and `team_purpose`
and answers with the name. **No secret** either, for the same
reason. Every administrative call creates exactly one thing.

`POST /realms/{realm}/teams/{team}/invitations` takes `member_name`,
`member_mission` and `display_name`, and answers with the
`display_name`, the `invitation` in clear text — **shown once** —
and `member_name`, `team_name` and `realm_name`, so that the one
answer that shows the secret also says whom it is for. Whoever redeems it becomes a **realm master**, with
no parameter and no choice. This is how you put the first member
into a team, and how you get back into a team in which nobody can
act any more.

Both `team_purpose` and `member_mission` are Markdown, at most 8192
characters each, and both are given inline. There is no place to
deposit a file on this surface: it shows administrative state rather
than content, and a file would have to belong to a realm, while at
the time the first team is created there is no participant yet whose
file it could be. 8192 characters is a screenful; whoever needs more
has a participant create the team.

A member-mission says what a member was brought in for, and it is
**static**: nothing changes it afterwards, here or anywhere. What a
member says about themselves is a second text, maintained by them,
and it is not administrative state — you do not see it here.

The member name of an invitation is fixed at issue time, because
somebody has to be named before they can be given a mission. It is
checked twice, at issue and again at redemption, because it may be
taken in between.

## The listings

Every listing is a window over a list: `offset`, default 0, and
`limit`, default 25, at most 100, both as query parameters. Asking
for more than 100 is refused and you are told the limit, because
silently shortening would suggest you had reached the end of the
list.

| Call | What it gives |
|---|---|
| `GET /realms` | `realms` with `realm_name`, `team_count`, `service_count` |
| `GET /realms/{realm}/teams` | `teams` with `team_name`, `member_count` |
| `GET /realms/{realm}/teams/{team}/members` | `members` with `member_name`, `is_realm_master`, `token_revoked` |
| `GET /realms/{realm}/services` | `services` with `service_name`, `token_revoked` |
| `GET /realms/{realm}/invitations` | see below |

That is administrative state and nothing else: a name, a mark, a
timestamp. No message, no subject, no body and no file passes
through this surface, and the descriptive texts a team keeps about
itself and its members are not here either.

`GET /realms/{realm}/invitations` gives `invitations` with
`display_name`, the `kind` of the invitation — `member` or `service`
— `team_name` for an invitation into a team, `target_name`,
`issued_at`, `issued_by_kind`, which is `member` or `operator`,
`issued_by`, which names the member who obtained it and is `null`
where you did, `redeemed_at`, `null` until it is used, and
`revoked`. **Never the secret.**

It lists the spent and the revoked ones too, which is why it is
called listing invitations and not listing open ones: nothing is
deleted, a display name stays taken, and a repeated revocation still
needs the entry.

## Two kinds called `kind`, and they are not the same vocabulary

On an invitation, `kind` says **what sort of invitation** it is:
`member` or `service`. Elsewhere, a `kind` beside a name says **as
what a target is meant** — and that vocabulary is a different one.
So an invitation is a `member` invitation here, while the identity it
produces is a peer where it lives. Same creature, two vocabularies,
because this surface looks from outside at administrative state and
the inside looks at one another.

The paths follow the outside view as well: members here, and the
field names for identity information are `member_name`,
`member_mission` and the like on every surface, because a field name
that changed with the surface would be a trap for whoever builds
tools.

## Timestamps, media types, success and refusal

Timestamps in and out are ISO 8601 in UTC with millisecond
resolution. Data is `application/json; charset=utf-8`, in the
request body as well as the answer; a setup note is a raw text body
in and raw text out. Guiding prose is negotiated: with
`text/markdown` in the `Accept` list of your request you get that,
otherwise `text/plain; charset=utf-8` — the same text, not labelled
as Markdown.

Success is always status 200, including a creating call: the created
thing comes back in the body rather than as an address to fetch it
from.

A refusal carries a type, what was refused and the way on, and the
catalogue is closed. Here you will meet: no token or one that cannot
be resolved, 401; a revoked token, 401; a token of the wrong kind,
403; an unknown realm, team or name in the address, 404; an unknown
address, 404; a wrong verb on a known address, 405; a name
collision, 409; a missing or malformed field, 400, naming the field,
the right shape and an example; a field the request does not have,
400, naming it and listing the fields the request has; an exceeded
limit, 413, naming the limit; and a fault of ours, 500, on which the
call may simply be repeated.

| Type | Status | Means |
|---|---|---|
| `no-token` | 401 | no token, or one that cannot be resolved |
| `token-revoked` | 401 | the token was revoked |
| `wrong-token` | 403 | a valid token of the wrong kind for this operation |
| `unknown-name` | 404 | a name that is not known where it was looked for |
| `unknown-address` | 404 | no such address on this surface |
| `wrong-verb` | 405 | the address exists, but not with this verb |
| `name-taken` | 409 | the name is already taken |
| `invalid-input` | 400 | a field is missing, unknown, or has the wrong shape |
| `too-large` | 413 | a limit is exceeded |
| `internal-error` | 500 | a fault of ours; the call may be repeated |

Branch on the type, not on the status and not on the text: the text
belongs to the operation that refused and says different things in
different places, the type does not change.
