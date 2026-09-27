"""The base address, derived from the request rather than configured.

Everything the service says about itself contains addresses: the entry page, the
guide, the skill package. They have to be the addresses a caller can actually
reach, which is not something the service can know from the inside — behind a
proxy the host name and the scheme are the proxy's, not its own.

So it measures instead of assuming:

- **The host name comes from `Host`, exactly as received.** No header that a
  proxy might set to override the host is read, anywhere. That is the direction
  an attacker would push, and a rewritten host in a document an agent keeps is
  a rewritten address the agent keeps using.
- **The scheme comes from `X-Forwarded-Proto`, and it is always believed.**
  There is no list of trusted proxies.

The reason there is no trust list is worth having in the code, because it is the
kind of thing somebody adds back: a trust list does not prevent the harmful
direction. A document that says `http` where only `https` answers comes from *no*
header arriving at all, and a list would only have constrained the harmless
direction — while forgetting to maintain it fails silently in the harmful one.
The header tells the truth in all three situations: proxy with TLS says `https`,
proxy without TLS says `http`, no proxy sends nothing and `http` is right.

There is a condition on the deployment that follows, and it is not optional: the
proxy has to set `X-Forwarded-Proto`. Where the derived scheme comes out as
`http`, the administration entry says so in a plain sentence — an operator can do
something about it, whereas an agent reading the participant guide cannot, so it
is not said there.
"""

from __future__ import annotations

HTTP = "http"
HTTPS = "https"

FORWARDED_PROTO = "X-Forwarded-Proto"
HOST = "Host"


def scheme_from(forwarded_proto: str | None) -> str:
    """The scheme, from the header value or `http` when there is none.

    A chain of proxies appends, so the value can be a list; the first entry is
    the one closest to the caller. Anything that is not a scheme we serve is
    ignored rather than passed through — believing the proxy is about not keeping
    a list of them, not about pasting arbitrary text into a URL.
    """
    if not forwarded_proto:
        return HTTP
    first = forwarded_proto.split(",")[0].strip().lower()
    return first if first in (HTTP, HTTPS) else HTTP


def base_address(host: str | None, forwarded_proto: str | None = None) -> str:
    """`scheme://host`, with no trailing slash.

    The host is required. HTTP/1.1 makes it mandatory and every caller sends it;
    a service that invented one here would put an invented address into a
    document that an agent then keeps.
    """
    if not host or not host.strip():
        raise ValueError("a request without a host name cannot say where the service is")
    return f"{scheme_from(forwarded_proto)}://{host.strip()}"


def is_plain_http(base: str) -> bool:
    """Whether this address means a token travels in the clear.

    Used by the administration entry, and by nothing else.
    """
    return base.startswith(f"{HTTP}://")
