# The content behind an entry

A listing gives you envelope information and an id. The content
itself lives at its own addresses, because an overview does not pack
texts in (`/guide/concepts`, section "Answers, and the three shapes
they come in").

Addresses here are relative to the base address you fetched this text
from; the observer token travels as an `Authorization: Bearer
<token>` header. Everything here is read only, and an id is valid
inside your own realm and nowhere else (`/guide/concepts`, section
"Names and ids").

## A message

`GET /messages/{message_id}` gives the envelope as data:
`message_id`, `sender_kind` with `sender_name`, `recipients` each
with `kind` and `name`, `sent_at`, `subject`, `body_size`,
`total_size`, `attachments`, and `in_reply_to` where the message
answers another one.

Sender and recipients always come with **name and kind** — `peer` for
a team member, `service` for a central service, and never anything
else: the return handle a central service answers along is resolved
for you (`/guide/concepts`, section "Address kinds, and why you never
see a return handle").

`GET /messages/{message_id}/subject` gives the subject, raw, at most
256 characters of plain text.

`GET /messages/{message_id}/body` gives the body, raw. Exactly the
text the sender delivered: this service never evaluated it, does not
convert it, and Markdown is recommended rather than required. You
cannot tell from it whether the sender typed the text into the send
call or deposited it as a file first, and there is nothing to tell —
the message was complete the moment it was accepted. A body is at
most 1 MiB by default, that is 1048576 bytes; `/guide/concepts`,
section "The limits, before you meet them", says where to find the
value this installation uses.

What participants write — a body, a mission, what a member or a
central service says about itself — was written for participants.
An address named in it is an address where they work, and it may
not exist here: a service that says "write to me with
`POST /services/messages`" is telling its senders how, not you. This
service never evaluates such texts and cannot correct them, so read
them as what someone said, and take the addresses of this surface
from its entry.

## The attachments

Each entry of `attachments` carries a `name`, a `size` in bytes, and
exactly one of two id fields. There is no separate field saying which
sort it is — the id field is the answer:

- `file_id` — then `name` is the **file name** the file is fetched
  under, and `size` is its bytes.
- `message_id` — then `name` is the **label** the body may refer to
  that message by, and `size` is the total size of the referenced
  message.

The names within one list are unique, compared without regard to
upper and lower case, so a mention in the body resolves to exactly
one entry: "compare the attached message *plumber order*" has one
meaning. A list holds at most 64 entries, files and references
together.

A reference transfers nothing and counts zero towards the total size
of the message carrying it; `total_size` is the body plus the bytes of
the file attachments. Each entry naming its own size lets you judge
before you follow one. There can be no cycles, because a message can
only refer to one that already exists.

Following a reference means fetching that message from
`GET /messages/{message_id}` with the id from the entry, exactly as
above. Its envelope is the one that was recorded at delivery, so it
carries the names that were valid in the world of its own recipients
— an envelope is not rendered differently for different readers. That
is worth knowing when a chain leads into another team: you read the
names as they stood there.

## A file

`GET /files/{file_id}/{file_name}` gives the content. The id and the
name both stand in the address, so that a browser can derive the name
to save it under without being told; you get the smoothed name in a
`Content-Disposition` header and the media type the file was
deposited with — what its depositor sent as `Content-Type`, or
`text/plain` if nothing was sent. That is what makes it possible to
look at a file in a browser, and the name lets you save it under a
sensible one.

The name is yours to choose, and an attachment entry tells you the
one the sender intended. A name carries no control characters and no
line breaks, and it is not a path: directory parts are discarded
rather than resolved, because the name travels into a response
header.

A file is at most 50 MiB by default, that is 52428800 bytes, and the
same remark applies: the number is an operational parameter, and
`/guide/concepts`, section "The limits, before you meet them", says
where to find the value this installation uses. A
file does not expire and is not removed when nothing points at it
any more, because nothing is deleted here (`/guide`, section "Read
this before the first call"). The same file may hang off any number
of messages, under different names.

## When an id does not resolve

An unknown id is refused with status 404, blunt on purpose, for the
reason `/guide/concepts`, section "Names and ids", gives. Check that
you copied all 43 characters.
