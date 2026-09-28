"""The shape of the holdings on disk.

One rule decides most of this: **the state of a thing is the directory it sits
in.** A token is active because it is under `active`, revoked because somebody
moved it under `revoked`, and a revocation is therefore a rename — one operation
the filesystem either completes or does not. No lock lies on the path of
anything, and there is no field to get out of step with a directory.

Two consequences are worth stating before the tree:

- **Directories are named by identifier, never by name.** A name may contain
  spaces, is compared without regard to case, and belongs to the caller;
  identifiers are ours and are 43 safe characters. Names get their own index —
  see `by_name` — which is also what makes uniqueness atomic.
- **Nothing is ever removed.** Revoking moves a directory; it does not delete
  one. A name therefore stays taken after a revocation, which is exactly the
  promised behaviour: somebody who lost a token comes back under a *new* name.

    <data>/
      admin-secret                  the bootstrap secret, owner-only
      note                          the global setup note
      tokens/<hash>                 which thing a presented token belongs to
      realms/
        by-name/<key>               the realm name, claimed
        <realm_id>/
          meta.json                 name, when
          note                      this realm's setup note
          teams/
            by-name/<key>
            <team_id>/
              meta.json
              purpose               raw, exactly as delivered
              members/
                by-name/<key>       taken for good, revoked or not
                active/<member_id>/     meta.json, mission, self-image
                revoked/<member_id>/
              mailboxes/<member_id>/
                inbox/<message_id>        the envelope as this member sees it
                outbox/<message_id>
          services/
            by-name/<key>
            active/<service_id>/    meta.json, self-image
            revoked/<service_id>/
            mailboxes/<service_id>/
              inbox/<message_id>
              outbox/<message_id>
          observers/
            by-name/<key>
            active/<observer_id>/
            revoked/<observer_id>/
          invitations/
            by-name/<kind>/<key>
            open/<invitation_id>/
            consumed/<invitation_id>/
            revoked/<invitation_id>/
          messages/<message_id>/    meta.json, subject, body
          files/<file_id>/          meta.json, content
          aliases/
            by-value/<alias>        which delivery this alias is the way back to
            by-delivery/<message_id>/<service_id>   the alias of that delivery

An **alias sits in the sender's place**, and only for a delivery to a central
service: the service sees `alias` and a random name, replies to it, and the
service never learns a member's name. It is therefore a property of one delivery
to one service, which is why it is indexed both ways — from the value, to answer a
reply, and from the delivery, so that delivering twice finds the same one.

That is also why a mailbox entry is a small record rather than an empty marker:
the envelope carries the names that hold **in its recipient's world**, and that is
settled when it is delivered, not when it is read.

The mailbox entries are the one place where a name would have been easier and
would have been wrong: a mailbox has no identifier visible from outside, so it
is addressed by whose it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from simple_a2a.core.names import comparison_key

#: The file every object keeps its non-text fields in.
META = "meta.json"

#: The file a mailbox entry is. One per delivery, holding the envelope as its
#: recipient sees it — which for a service means an alias where a name would be.
ENVELOPE = "envelope.json"

#: Where a name is claimed. One entry per taken name, created exclusively, which
#: is what makes "is this name free" and "take it" a single step.
BY_NAME = "by-name"

#: What joins the two halves of a mailbox entry's name, and the whole point of it
#: is that it occurs in **neither** half. A timestamp contains hyphens, colons and
#: a dot; an identifier is base64url, so it can contain hyphens and underscores.
#: A separator that appears in either one turns reading the name back into a
#: guess — which is exactly the mistake that was made first, splitting at the last
#: hyphen of a name whose identifier had hyphens of its own.
#:
#: A tilde is in neither alphabet, and it is unreserved in a path.
ENTRY_SEPARATOR = "~"

#: The two ways into the alias index: from the value a service replies to, and
#: from the delivery it belongs to.
BY_VALUE = "by-value"
BY_DELIVERY = "by-delivery"

#: Where the mailboxes of a team or a registry sit. Named here because it shares a
#: parent with the things it belongs to, so every listing has to know it is not one.
MAILBOXES = "mailboxes"


class State(StrEnum):
    """The directory a thing sits in, which is what its state means."""

    ACTIVE = "active"
    REVOKED = "revoked"
    OPEN = "open"
    CONSUMED = "consumed"


#: The states a token-bearing thing can be in.
TOKEN_STATES = (State.ACTIVE, State.REVOKED)

#: The states an invitation can be in. `open` rather than `active`, because an
#: invitation is not a permission — it is a voucher, and it ends by being used.
INVITATION_STATES = (State.OPEN, State.CONSUMED, State.REVOKED)


@dataclass(frozen=True)
class Layout:
    """Every path in the holdings, computed from the data directory."""

    root: Path

    # -- the two things that live beside the holdings ----------------------

    @property
    def global_note(self) -> Path:
        return self.root / "note"

    @property
    def tokens(self) -> Path:
        """The index from a presented token to the thing it belongs to.

        Entries are named by a hash of the token, never by the token: a path
        ends up in error messages, in stack traces and in listings, and a secret
        that lives in a path eventually lives in a log. The entry also outlives a
        revocation, which is what lets a revoked token be answered as revoked
        rather than as unknown — two different things to be told.
        """
        return self.root / "tokens"

    def token(self, token_hash: str) -> Path:
        return self.tokens / token_hash

    # -- realms ------------------------------------------------------------

    @property
    def realms(self) -> Path:
        return self.root / "realms"

    def realm(self, realm_id: str) -> Path:
        return self.realms / realm_id

    def realm_by_name(self, name: str) -> Path:
        return self.realms / BY_NAME / comparison_key(name)

    def realm_note(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "note"

    # -- teams -------------------------------------------------------------

    def teams(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "teams"

    def team(self, realm_id: str, team_id: str) -> Path:
        return self.teams(realm_id) / team_id

    def team_by_name(self, realm_id: str, name: str) -> Path:
        return self.teams(realm_id) / BY_NAME / comparison_key(name)

    def team_purpose(self, realm_id: str, team_id: str) -> Path:
        return self.team(realm_id, team_id) / "purpose"

    # -- members, per team -------------------------------------------------

    def members(self, realm_id: str, team_id: str) -> Path:
        return self.team(realm_id, team_id) / "members"

    def member(self, realm_id: str, team_id: str, member_id: str, state: State) -> Path:
        return self.members(realm_id, team_id) / state / member_id

    def member_by_name(self, realm_id: str, team_id: str, name: str) -> Path:
        return self.members(realm_id, team_id) / BY_NAME / comparison_key(name)

    # -- services, per realm ----------------------------------------------

    def services(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "services"

    def service(self, realm_id: str, service_id: str, state: State) -> Path:
        return self.services(realm_id) / state / service_id

    def service_by_name(self, realm_id: str, name: str) -> Path:
        return self.services(realm_id) / BY_NAME / comparison_key(name)

    # -- observers, per realm ---------------------------------------------

    def observers(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "observers"

    def observer(self, realm_id: str, observer_id: str, state: State) -> Path:
        return self.observers(realm_id) / state / observer_id

    def observer_by_name(self, realm_id: str, display_name: str) -> Path:
        return self.observers(realm_id) / BY_NAME / comparison_key(display_name)

    # -- invitations, per realm -------------------------------------------

    def invitations(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "invitations"

    def invitation(self, realm_id: str, invitation_id: str, state: State) -> Path:
        return self.invitations(realm_id) / state / invitation_id

    def invitation_by_name(self, realm_id: str, kind: str, display_name: str) -> Path:
        """Display names are unique per *kind* per realm.

        So an invitation does not block an observer's name, and neither blocks
        the other's — which is why the kind is a directory level here rather
        than part of the key.
        """
        return self.invitations(realm_id) / BY_NAME / kind / comparison_key(display_name)

    # -- aliases, per realm ------------------------------------------------

    def aliases(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "aliases"

    def alias_by_value(self, realm_id: str, alias: str) -> Path:
        """From the alias a service replies to, back to the delivery.

        Stored as itself rather than as a hash, unlike a token: an alias is shown
        in an envelope, so it has to be readable back out.
        """
        return self.aliases(realm_id) / BY_VALUE / alias

    def alias_by_delivery(self, realm_id: str, message_id: str, service_id: str) -> Path:
        """From one delivery to the alias it got, so that finding beats minting."""
        return self.aliases(realm_id) / BY_DELIVERY / message_id / service_id

    # -- messages and files, per realm ------------------------------------

    def messages(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "messages"

    def message(self, realm_id: str, message_id: str) -> Path:
        return self.messages(realm_id) / message_id

    def files(self, realm_id: str) -> Path:
        return self.realm(realm_id) / "files"

    def file(self, realm_id: str, file_id: str) -> Path:
        return self.files(realm_id) / file_id

    # -- mailboxes ---------------------------------------------------------

    def team_mailboxes(self, realm_id: str, team_id: str) -> Path:
        return self.team(realm_id, team_id) / MAILBOXES

    def member_mailbox(self, realm_id: str, team_id: str, member_id: str) -> Path:
        return self.team_mailboxes(realm_id, team_id) / member_id

    def service_mailbox(self, realm_id: str, service_id: str) -> Path:
        return self.services(realm_id) / MAILBOXES / service_id
