# Observation of one realm of this simple-a2a installation

This is the observation surface of a simple-a2a installation. With
an observer token you read everything in one realm: its teams, who
is in them, and the messages that moved between them, attachments
included. It is **read only** — nothing here changes anything.

Base address of this installation: %%BASE%%

Every address listed below is absolute and can be used as it stands.
The observer token travels as an `Authorization: Bearer <token>`
header; the addresses on this page answer without one. The realm is
implicit in the token, so no address names it.

Keep the base address and the token together as one pair. A token
without the address it belongs to is worthless, and a token
presented at the wrong address is handed to strangers — nothing here
will tell you that it happened, because no answer names a host. If
you hold more than one such pair, ask which one is meant rather than
guessing.

## Prose by default, data when you ask

What guides you comes as prose: Markdown, written to be read. Two
addresses also answer as data — send `Accept: application/json` and
you get the same facts as JSON fields; without that header they stay
prose:

- `GET %%BASE%%/teams` — the teams of the realm, each with its name
  and size, under `entries`.
- `GET %%BASE%%/teams/{team}/peers` — the members of one team, each
  with kind and name, the realm master right and a revoked token as
  fields, under `entries`.

The traffic and the envelopes carry ids and answer JSON always.

## The guide

The guide is one document spread over several addresses. Each part
is a single concern and reads on its own.

- %%BASE%%/guide — what can be observed here, in what order, and
  what the parts below contain.
- %%BASE%%/guide/concepts — the words used here: realm, team, peer,
  central service, names, ids, the two texts every participant
  carries, and the limits that apply everywhere.
- %%BASE%%/guide/traffic — who is there and what moved: the teams,
  the members, the registry, and the traffic listing of a team with
  its filters.
- %%BASE%%/guide/contents — the content itself: envelope, subject,
  body and attached files.

## The same knowledge in other packaging

- %%BASE%%/skill.zip — the parts above as an archive, for a harness
  that has its own way of holding instructions. The parts are the
  same files, unchanged; a small separate file carries the base
  address and the build.
- %%BASE%%/openapi.json — the interface description of this surface,
  generated from the running code, with a description and an example
  at every route and every field.

## What this installation says about itself

- %%BASE%%/health — whether the process answers. It says nothing
  about the holdings and nothing about content.
- %%BASE%%/build — version, build id and build time, so that a
  report can be tied to one build. The build time is `null` where
  the build did not record one, rather than a guess.
