"""Shared HTTP helpers for external stock data providers."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}

_SESSION = requests.Session()


def request(method: str, url: str, *, timeout: int | float = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None, **kwargs: Any) -> requests.Response:
    """Send an HTTP request with the system's default provider settings."""
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    resp = _SESSION.request(method, url, headers=merged_headers, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


def get(url: str, *, timeout: int | float = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None, **kwargs: Any) -> requests.Response:
    return request("GET", url, timeout=timeout, headers=headers, **kwargs)


def session() -> requests.Session:
    return _SESSION


def new_session() -> requests.Session:
    return requests.Session()


def get_text(url: str, *, encoding: str | None = None, timeout: int | float = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None, **kwargs: Any) -> str:
    resp = get(url, timeout=timeout, headers=headers, **kwargs)
    if encoding:
        resp.encoding = encoding
    return resp.text


def get_json(url: str, *, timeout: int | float = DEFAULT_TIMEOUT, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
    return get(url, timeout=timeout, headers=headers, **kwargs).json()
