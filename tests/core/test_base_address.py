"""The base address is measured, not assumed — and the measurement has one rule.

Everything the service says about itself contains addresses, and behind a proxy
the host and the scheme belong to the proxy. So the host comes from `Host` as
received, no override header is read anywhere, and the scheme comes from
`X-Forwarded-Proto` and is believed.
"""

from __future__ import annotations

import pytest

from simple_a2a.core.base_address import base_address, is_plain_http, scheme_from


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "http"),
        ("", "http"),
        ("http", "http"),
        ("https", "https"),
        ("HTTPS", "https"),
        (" https ", "https"),
        # A chain of proxies appends; the first entry is closest to the caller.
        ("https, http", "https"),
        ("http,https", "http"),
        # Not a scheme we serve. Believing the proxy is about not keeping a list
        # of them, not about pasting arbitrary text into a URL.
        ("gopher", "http"),
        ("javascript:", "http"),
    ],
)
def test_the_scheme_comes_from_the_header_or_is_http(header: str | None, expected: str) -> None:
    assert scheme_from(header) == expected


def test_no_proxy_means_http_and_that_is_the_truth() -> None:
    """All three situations are honest: TLS, no TLS, no proxy."""
    assert base_address("example.test") == "http://example.test"
    assert base_address("example.test", "http") == "http://example.test"
    assert base_address("example.test", "https") == "https://example.test"


def test_the_host_is_taken_exactly_as_received() -> None:
    assert base_address("example.test:8251") == "http://example.test:8251"
    assert base_address("EXAMPLE.test") == "http://EXAMPLE.test"


def test_the_address_has_no_trailing_slash() -> None:
    """Addresses are put together from it, and two slashes are a broken link."""
    assert not base_address("example.test").endswith("/")


@pytest.mark.parametrize("host", [None, "", "   "])
def test_without_a_host_no_address_is_invented(host: str | None) -> None:
    """An invented address would be kept by an agent and used from then on."""
    with pytest.raises(ValueError, match="host name"):
        base_address(host)


def test_plain_http_is_recognisable_so_the_operator_can_be_told() -> None:
    assert is_plain_http("http://example.test")
    assert not is_plain_http("https://example.test")
