# Who is there, and what moved

The route through this surface is: the teams of your realm, then one
team, then what moved inside it. Everything here is read only, and
the realm is implicit in your token, so no address names it.

Addresses here are relative to the base address you fetched this text
from; the observer token travels as an `Authorization: Bearer
<token>` header.

Every listing here is a window over a list, and names in an address
are percent-encoded; the window parameters are in `/guide/concepts`,
section "Answers, and the three shapes they come in", the encoding
in its section "Names and ids".

## The teams

- `GET /teams` — the names of the teams of your realm,
  alphabetically, with the address of each. This is the call nobody
  inside a team may have, and it is what this surface exists for.
  Asked for JSON the way `/guide/concepts`, section "Answers, and
  the three shapes they come in", describes, it answers the same
  window as data: `entries`, each with `team_name` and
  `member_count`.
- `GET /teams/{team}` — one team: its name, how many members it has,
  and the addresses of its purpose and its members.
- `GET /teams/{team}/purpose` — the purpose of the team, raw, as
  whoever created it delivered it.

## The members of a team

- `GET /teams/{team}/peers` — the names of the members,
  alphabetically, a mark on whoever carries the realm master right
  and a second mark on anyone whose token has been revoked, and per
  name the addresses of their two texts. Asked for JSON the same
  way, it answers the same window as data: `entries`, each with
  `kind` (always `peer`), `name`, `is_realm_master` and
  `token_revoked`, and the moments: `joined_at`,
  `token_revoked_at`, `realm_master_granted_at` and
  `realm_master_revoked_at` — the last two are the latest time the
  right was given and taken, so a grant later than the revocation
  means it was given back.
- `GET /teams/{team}/peers/{name}` — one member: name, whether realm
  master, whether revoked, the same moments, and the addresses of the
  two texts.
- `GET /teams/{team}/peers/{name}/mission` — their member-mission,
  raw.
- `GET /teams/{team}/peers/{name}/self` — their member-self-image,
  raw, empty until they set one. What the two texts are is in
  `/guide/concepts`, section "Two texts per participant".

A moment the installation did not keep — the right given or taken
before it began to record that — is `null` in the data and "not
recorded" in the prose. It is never filled in with a guess.

## The central services of the realm

- `GET /services` — the names of the central services of your realm.
  They are named across the realm rather than per team, which is why
  no team stands in this address.
- `GET /services/{name}` — one central service: its name and the
  address of its member-self-image, with the reason there is no
  member-mission — a central service registers itself.
- `GET /services/{name}/self` — that text, raw.

## The traffic of a team

`GET /teams/{team}/traffic` is the actual observation. A team stands
in the address because the natural question is "what moved in this
team", and there is no realm-wide traffic listing: it would have no
reader. Every message has a team side, since a central service can
neither begin an exchange nor reach another central service — so no
entry has two team sides, and every entry is unambiguously located.

Because the team is in the address, no field repeats it.

An entry carries `sender_kind` with `sender_name`, `recipients` each
with `kind` and `name`, `sent_at`, `message_id`, `subject`,
`body_size`, `total_size`, `attachment_count`, and, where there is
one, `in_reply_to`. Newest first.

- `sender_kind` and the kinds in `recipients` are `peer` for a team
  member and `service` for a central service, and never anything
  else: the return handle a central service answers along is
  resolved for you (`/guide/concepts`, section "Address kinds, and
  why you never see a return handle").
- `body_size` is the body alone and `total_size` is the body plus the
  bytes of the attached files, both in bytes, so you can see where
  the weight lies before fetching anything. How attachments count
  towards it is in `/guide/contents`, section "The attachments".
- `in_reply_to` is in the listing and not only in the details, so a
  chain of replies can be followed without opening every entry. That
  chain is the identity of a conversation here — not the
  counterpart, since a central service is never told who it is
  talking to.
- A message sent to everyone in a team appears **once**, with all its
  recipients in that one entry, because the recipient list was
  resolved when it was sent. You are not looking at one copy per
  recipient.

## The filters

Besides `offset` and `limit`, the traffic listing takes these query
parameters:

- `sender_kind` with `sender_name`, and `recipient_kind` with
  `recipient_name`. Each pair travels together, because inside one
  team the other side may be a team member or a central service, and
  the kind says which namespace the name belongs to. A kind without
  a name, or a name without a kind, is refused as malformed. A name
  that does not exist there is refused as unknown, and you are
  pointed at the listings above.
- `from` and `to`, as ISO 8601 timestamps in UTC with millisecond
  resolution. Both bounds are included.

Filters exist here because you look across all the teams of a realm,
where a window alone would not get you to one exchange.

## What an entry does not tell you

Not the body, and not the subject beyond what stands in the entry.
Those are fetched from their own addresses, described in
`/guide/contents`, because an overview does not pack texts in
(`/guide/concepts`, section "Answers, and the three shapes they come
in"). And no read state, yourself included (`/guide`, section "Read
this before the first call").
