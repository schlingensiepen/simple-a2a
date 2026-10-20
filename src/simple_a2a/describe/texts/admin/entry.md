# Administration of this simple-a2a installation

This is the administration surface of a simple-a2a installation. It
is where realms and teams are created, where invitations and
observer tokens are obtained, and it is the only place where
anything is revoked. It shows administrative state and never
content.

Base address of this installation: %%BASE%%

Every address listed below is absolute and can be used as it
stands. The administration token travels as an `Authorization:
Bearer <token>` header; the addresses on this page answer without
one.

<!-- plain-http -->
A token sent to a plain, unencrypted address travels in the clear,
readable by anything on the way. This service terminates no
encryption of its own, so that protection comes from the proxy in
front of it — and the proxy has to announce it by setting the
`X-Forwarded-Proto` header, because the base address above is
derived from what the request reports. Where that header is
missing, the address above reads `http` even if only `https`
answers from outside, and every document and every package that
carries the address will keep saying so until the proxy is fixed.
<!-- /plain-http -->

Keep the base address and the token together as one pair, and hand
secrets on the same way. A token without the address it belongs to
is worthless, and a token presented at the wrong address is given
away to strangers — nothing here will tell you that it happened,
because no answer names a host.

## Prose and data

This page and the guide are prose. Every operation here answers
with data, JSON, and no address on this surface offers both: there
is no `Accept: application/json` to send for it. The two setup notes
come back as the raw text that was written.

## The guide

The guide is one document spread over several addresses. Each part
is a single concern and reads on its own.

- %%BASE%%/guide — what this administration is, what it never does,
  and what the parts below contain.
- %%BASE%%/guide/first-access — from a bare start to a working
  team, in order, with the mistakes that cannot be undone.
- %%BASE%%/guide/realms — realms, teams, members and central
  services: creating the containers and reading the listings.
- %%BASE%%/guide/tokens — the secrets: obtaining an invitation,
  issuing an observer token, and revoking either.
- %%BASE%%/guide/notes — the two setup notes, where you write down
  what you did and what you handed to whom.

## The same knowledge in other packaging

- %%BASE%%/skill.zip — the parts above as an archive, for a harness
  that has its own way of holding instructions. The parts are the
  same files, unchanged; a small separate file carries the base
  address and the build.
- %%BASE%%/openapi.json — the interface description of this
  surface, generated from the running code, with a description and
  an example at every route and every field.

## What this installation says about itself

- %%BASE%%/health — whether the process answers. It says nothing
  about the holdings.
- %%BASE%%/build — version, build id and build time, so that a
  report can be tied to one build. The build time is `null` where
  the build did not record one, rather than a guess.
