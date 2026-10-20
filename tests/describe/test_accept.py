"""Negotiating prose or data: one function decides it for every address that offers both.

Prose is the default. JSON is the answer only when the Accept header makes it more
welcome than either kind of prose, each weighed by the most specific range that
names it.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from simple_a2a.describe import http


def asking(accept: str | None) -> Request:
    headers = [] if accept is None else [(b"accept", accept.encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.parametrize(
    "accept",
    [
        "application/json",
        "APPLICATION/JSON",
        "application/*",
        "application/*;q=1, text/plain;q=0.5",
        "text/plain;q=0.5, application/json",
        "application/json, text/*;q=0",
        "application/json, */*;q=0.1",
        "application/json;q=0.9, text/*;q=0.8, */*;q=1",
        "application/json; charset=utf-8; q=0.8, text/plain; q=0.7",
        "*/*;q=0.5, application/*;q=0.6",
        "text/markdown;q=0, text/plain;q=0, application/json;q=0.1",
    ],
)
def test_data_when_it_is_more_welcome_than_any_prose(accept: str) -> None:
    assert http.wants_data(asking(accept)) is True


@pytest.mark.parametrize(
    "accept",
    [
        None,
        "",
        "*/*",
        "text/plain",
        "text/markdown",
        "text/*",
        "application/json;q=0.5, */*;q=1",
        "application/json;q=0.5, text/plain",
        "text/markdown, application/json",
        "application/json, text/plain",
        "application/json, */*",
        "application/json;q=0",
        "application/*;q=0, */*",
        "*/*, application/json;q=0",
        "application/json;q=0.8, text/markdown;q=0.9, text/plain;q=0.1",
        "application/json;q=nonsense",
        "text/markdown, application/json;q=0.9, */*;q=0.8",
        "image/png",
    ],
)
def test_prose_when_data_is_not_more_welcome(accept: str | None) -> None:
    assert http.wants_data(asking(accept)) is False


@pytest.mark.parametrize(
    ("accept", "label"),
    [
        (None, "text/plain"),
        ("*/*", "text/plain"),
        ("text/markdown", "text/markdown"),
        ("text/plain, text/markdown;q=0.5", "text/markdown"),
        ("text/markdown;q=0, text/plain", "text/plain"),
    ],
)
def test_prose_is_labelled_markdown_only_when_markdown_is_asked_for(
    accept: str | None, label: str
) -> None:
    answer = http.prose("# text", asking(accept))

    assert answer.headers["content-type"].startswith(label)
