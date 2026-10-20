# Who is there, and what moved

The route through this surface is: the teams of your realm, then one
team, then what moved inside it. Everything here is read only, and
the realm is implicit in your token, so no address names it.

Addresses here are relative to the base address you fetched this text
from; the observer token travels as an `Authorization: Bearer
<token>` header.

Every listing is a window over a list: `offset`, default 0, and
`limit`, default 25, at most 100, both as query parameters. Asking
for more than 100 is refused and you are told the limit, because
silently shortening would suggest you had reached the end of the
list. Names in an address are percent-encoded, because a name may
contain spaces.

## The teams

- `GET /teams` — the names of the teams of your realm,
  alphabetically, with the address of each. This is the call nobody
  inside a team may have, and it is what this surface exists for.
  Asked with `Accept: application/json`, it answers the same window
  as data: `entries`, each with `team_name` and `member_count`.
- `GET /teams/{team}` — one team: its name, how many members it has,
  and the addresses of its purpose and its members.
- `GET /teams/{team}/purpose` — the purpose of the team, raw, as
  whoever created it delivered it.

## The members of a team

- `GET /teams/{team}/peers` — the names of the members,
  alphabetically, a mark on whoever carries the realm master right
  and a second mark on anyone whose token has been revoked, and per
  name the addresses of their two texts. Asked with
  `Accept: application/json`, it answers the same window as data:
  `entries`, each with `kind` (always `peer`), `name`,
  `is_realm_master` and `token_revoked`.
- `GET /teams/{team}/peers/{name}` — one member: name, whether realm
  master, whether revoked, and the addresses of the two texts.
- `GET /teams/{team}/peers/{name}/mission` — their member-mission,
  raw: what they were brought in for, set when they joined and static
  since.
- `GET /teams/{team}/peers/{name}/self` — their member-self-image,
  raw: what they say they actually do. Empty until they set one.

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
  else. Where a central service was shown an **alias** — the
  one-delivery return handle it answers along — in place of a
  sender, the alias is resolved for you and the participant behind
  it is named. That resolution is the purpose of this surface.
- `body_size` is the body alone and `total_size` is the body plus the
  bytes of the attached files, both in bytes, so you can see where
  the weight lies before fetching anything. An attachment that is a
  reference to another message transfers nothing and counts zero.
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
Those are fetched from their own addresses, so that reading a listing
does not pull a mebibyte into your context; the part at
`/guide/contents` describes them. And no read state: this service
does not record what anyone has seen, yourself included, and there is
nothing to acknowledge.
