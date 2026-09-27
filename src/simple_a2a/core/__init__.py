"""Operational parameters, identifiers, paths, atomic file operations, tokens.

The ground every other block stands on: the eight operational parameters and
their defaults, the one identifier space, the layout of the data directory,
writing a file so that a reader never sees it half-written, checking a token,
and deriving the base address from a request.

Knows nothing of HTTP, of messages, of surfaces.
"""
