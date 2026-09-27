"""The measures, in one place, in bytes or characters as the thing is measured.

Two of them are operational parameters because an operator has a reason to move
them; the rest are properties of the service. They are gathered here so that the
number a request is checked against and the number the self-description
announces are the same number — a limit that is announced in one place and
enforced from another is a limit that eventually disagrees with itself.

Characters are counted as characters, and bytes as bytes. A subject of 256
characters is about a person reading a listing; a body of a mebibyte is about
memory and transfer, and it stays a byte count wherever it is shown.
"""

from __future__ import annotations

#: Characters.
SUBJECT_MAX_CHARS = 256
MEMBER_MISSION_MAX_CHARS = 8192
MEMBER_SELF_IMAGE_MAX_CHARS = 8192
TEAM_PURPOSE_MAX_CHARS = 8192
SETUP_NOTE_MAX_CHARS = 8192
ATTACHMENT_NAME_MAX_CHARS = 256

#: Bytes. Both of these are the defaults of an operational parameter.
BODY_MAX_BYTES_DEFAULT = 1 * 1024 * 1024
FILE_MAX_BYTES_DEFAULT = 50 * 1024 * 1024

#: Entries. Files and references to messages counted together.
ATTACHMENTS_MAX = 64

#: The window over a list. Asking for more is refused and told the limit:
#: shortening quietly would tell an agent it had reached the end of a list.
WINDOW_OFFSET_DEFAULT = 0
WINDOW_LIMIT_DEFAULT = 25
WINDOW_LIMIT_MAX = 100

#: The administration secret an operator sets. Shorter than this and the start
#: is refused: a secret that is the only door in does not get to be guessable.
ADMIN_SECRET_MIN_CHARS = 32
