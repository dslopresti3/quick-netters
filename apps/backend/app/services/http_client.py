from __future__ import annotations

import json
from typing import Any
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener


DEFAULT_TIMEOUT_SECONDS = 10

BROWSER_LIKE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.nhl.com/",
    "Origin": "https://www.nhl.com",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def build_no_proxy_opener() -> OpenerDirector:
    return build_opener(ProxyHandler({}))


def build_request(url: str, headers: dict[str, str] | None = None) -> Request:
    combined_headers = dict(BROWSER_LIKE_HEADERS)
    if headers:
        combined_headers.update(headers)
    return Request(url=url, headers=combined_headers)


def fetch_json(
    *,
    url: str,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    opener: OpenerDirector | None = None,
) -> dict[str, Any]:
    request = build_request(url=url, headers=headers)
    http_opener = opener or build_no_proxy_opener()
    with http_opener.open(request, timeout=timeout_seconds) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}, got {type(payload).__name__}.")
    return payload
