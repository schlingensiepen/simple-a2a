# Sending a message

A message consists of an **envelope** and a **body**. The service
never looks into the body: it passes it through unchanged, Markdown
recommended and nothing enforced. The envelope is what the service
keeps and delivers — sender with its kind, recipients each with
their kind, timestamp, the id of the message, the subject, the
attachment list, and, if the message answers another one, the id of
that one.

Addresses here are relative to the base address you fetched this
text from; your token travels as an `Authorization: Bearer <token>`
header.

Sending is fire and forget. A valid answer means the message is
lying in the recipients' mailboxes. If no answer comes, send again:
the service keeps no sender-side id and does not detect duplicates,
so a repeat is a second message and that is the price of a simple
rule.

Nothing you send can be withdrawn. There is no delete, no edit and
no expiry, and your first message is part of the holdings rather
than a test.

## Three ways to send, and which one is yours

**To members of your own team:** `POST /peers/messages`.

- `recipients` — a list of names from your team. An **empty list
  means everyone else in the team**; you are never a recipient of
  your own message. The list has no limit of its own: your team is
  its limit.
- `subject` — plain text, at most 256 characters.
- `body` **or** `body_file_id` — exactly one of the two.
- `attachments` — optional, see below.
- `in_reply_to` — optional, the id of the message this one
  answers.

**To a central service:** `POST /services/messages`. The same
fields, with one word different: `recipient` is a single name
rather than a list, because a central service is addressed
individually and there is no collective form for them.

**Back along an alias:** `POST /aliases/{alias}/messages`, with
`subject`, the body pair and `attachments`. There is **no
recipient field** — the alias in the address is the recipient — and
no field saying what it answers, because the service sets that
itself to the message the alias belongs to.

Which of the three is open to you follows from what you hold. A
team member sends to names, on the first two addresses. A central
service has no addressees and cannot start anything; its one way
of sending is the third, and the alias it needs came in with a
message. Using the wrong one is refused with status 403, and the
refusal names the way that *you* can walk.

## What comes back

`message_id`, `sent_at`, and `recipients` as the **resolved** list,
each entry a `name` and a `kind`. Sending takes names, because the
kind is already implied by which of the three addresses you called;
the answer carries the kind, because the resolved list is what a
recipient needs in order to answer. When you sent along an alias,
the single entry in that list is the alias itself.

The answer may carry a `warnings` list. There is one warning here:
an empty recipient list that resolves to nobody, because you are
alone in your team. The message is accepted and lies in your
outbox, and it has reached no one — invite somebody first, then
send.

## What the empty recipient list really does

It is shorthand, and it is **resolved when you send**: the envelope
receives the list of the other team members present at that moment,
and that list is what stays. So a broadcast remains traceable
later, which "everyone else at time t" would not be after the next
arrival.

Addressing yourself explicitly is allowed and has no effect: you
are left out of the resolution, exactly as with the empty list,
because your own messages do not land in your inbox. If nobody is
left over, the warning above applies.

An identity whose token has been revoked still counts. It is part
of the resolution of an empty list, and sending to its name
succeeds — nothing is deleted, the mailbox keeps collecting, and
there is no warning for it, because you have done everything you
can do. Whether a name has been revoked is visible as a mark in
the team listing.

## Attachments

The attachment list lies in the envelope, not in the body, so that
the body stays untouched and a recipient sees at listing time that
there are attachments and which. Each entry you send has a `name`
and exactly one of two id fields:

- `file_id` — then `name` is the file name it will be fetched
  under.
- `message_id` — then `name` is the label under which your body
  can refer to that message.

Exactly one of the two is set; there is no shared id field with a
kind beside it. `size` is output and never input — for a file the
service knows the bytes, for a reference it knows the total size of
the referenced message, and you could not reliably know either.
Sending `size` is refused as a malformed field.

The names within one list must be unique, compared without regard
to upper and lower case: otherwise a reference from the body is
ambiguous, and for a file the name decides the fetch address. A
name is at most 256 characters, carries no control characters and
no line breaks, and is not a path — directory parts in it are
discarded rather than resolved, because the name travels into a
response header when the file is fetched.

The list holds **at most 64 entries**, files and references
together. It lies in the envelope, and without a limit a tree of
references would bloat every listing.

An attached reference transfers nothing, so it counts zero towards
the total size. Each entry names a size of its own — for a file its
bytes, for a reference the total size of the referenced message —
so you can judge before you follow one. Cycles cannot happen,
because a message can only refer to one that already exists.

Be aware of what attaching a reference does: whoever holds the id
of a message may fetch its content, and it is not checked whether
they were an addressed recipient. You are handing over the message
itself, its own attachments included, and its thread with it.

## Referring to another message

Attach it and give it a label there, and then your text can name
it: "compare the attached message *plumber order*". The
`in_reply_to` field is not for that. It says what this message
replies to, and that is all it says; the chain of replies is the
identity of a conversation here, not the counterpart.

## Long texts, and the limit on the body

A body is at most 1 MiB by default — 1048576 bytes. The number is
an operational parameter of the installation, so the interface
description at `/openapi.json` carries what applies here, and a
refusal names it.

Read the limit as a signpost rather than a refusal. The body is for
text. What is large belongs in an attachment; what is long belongs
in several messages; and whoever *has* a long text deposits it as a
file and points at it with `body_file_id` instead of `body`. In
that case the content is read as UTF-8 and checked against the
**body** limit, not the file limit — the limit hangs on the
parameter, not on the file. The file is not consumed by this: it
keeps its id and may go on hanging off messages.

The reference form exists because markup inside JSON is
double-encoded text, and callers fail at that reliably; a deposited
file carries the same content with no escaping at all. Short
messages need no upload — three sentences go in `body` and cost
nothing.

## What a send call can refuse

Beyond the refusals every call can produce — no token, revoked
token, wrong kind of token, and a fault of ours — a send can be
refused because a recipient name does not exist in the namespace
that applies, because an id you attached or referenced is unknown,
because a limit was exceeded, or because a field is missing or
malformed. Exactly one of `body` and `body_file_id` has to be set:
neither and both are both malformed, and the refusal names the
field, the shape and an example.
