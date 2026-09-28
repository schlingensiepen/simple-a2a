# The two setup notes

This service cannot know what nobody told it. It does not know the
address by which it is reached from outside, it does not know who
runs it, and it does not know who you handed which secret to. What
it can do is offer a place to write that down. It does not **know**,
it **keeps**.

Addresses here are relative to the base address you fetched this
text from. The administration token travels as an `Authorization:
Bearer <token>` header.

## Two notes, because there are two subjects

| Call | What it is for |
|---|---|
| `GET /setup-note` | read the global note |
| `PUT /setup-note` | write the global note |
| `GET /realms/{realm}/setup-note` | read the note of one realm |
| `PUT /realms/{realm}/setup-note` | write the note of one realm |

The **global** note says where this administration belongs: which
address this installation is reached by, which addresses you hand
out, who operates it, whom to ask. The **per-realm** note says what
was done in that realm: which names exist for what, who got which
secret and when, and what is still outstanding.

The reason for them is the same as the reason for keeping a record
of what one has sent: whoever comes back to this installation later
has lost their context, and it may not even be the same person or
the same agent. Unlike the fetching of messages, which belongs to
whoever wants the messages, a note belongs to the **installation**,
which is why it lives here.

## How they behave

Reading gives the text back **raw** — exactly as it was delivered,
with no wrapper. It is empty as long as nothing has been written.

Writing takes the text as the **raw request body**, not JSON.
Markdown is recommended and nothing is enforced; the content has to
be valid UTF-8 and is at most 8192 characters. The answer gives
`length` in characters, the same unit as the limit. Exceeding it is
refused with status 413 and the limit is named; a body that is not
valid UTF-8 is refused as malformed, with what it has to be and
what was wrong with it.

**Writing always replaces.** There is no appending and no second
write behaviour: read first, then write, and whatever was there is
gone. That is the whole mechanism — the loss is named rather than
prevented, because a second write mode would be a second set of
rules for one field.

Naming an unknown realm is refused with status 404, and the refusal
points you at the realm listing, which shows the valid names.

## What is in a note is yours

The service never evaluates the text, filters nothing and warns
about nothing. It comes back out exactly as you put it in.

That is deliberate, and it has a consequence worth stating: what
stands in a note is what **somebody wrote there**. Whoever reads it
is reading your statement, not a finding of this service. It is not
a field the service fills in about itself — if it were, a wrong
address could come back in through the side door, and a wrong
address travelling next to a secret is the one mistake here that
does not look like a mistake.

The notes are administrative state. No one but a holder of the
administration token reads them.
