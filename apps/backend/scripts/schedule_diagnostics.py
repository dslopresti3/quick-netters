from __future__ import annotations

import argparse
import json
import os
from datetime import date
from urllib.error import HTTPError, URLError

from app.services.http_client import BROWSER_LIKE_HEADERS, fetch_json
from app.services.real_services import NhlScheduleProvider, _extract_games


def _proxy_snapshot() -> dict[str, str]:
    keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ]
    return {key: os.getenv(key, "") for key in keys}


def run(selected_date: date) -> int:
    provider = NhlScheduleProvider()
    url = f"{provider.base_url}/{selected_date.isoformat()}"
    print("request_url:", url)
    print("headers:", json.dumps(BROWSER_LIKE_HEADERS, indent=2))
    print("proxy_env:", json.dumps(_proxy_snapshot(), indent=2))
    print("proxy_mode: disabled (ProxyHandler({}))")

    try:
        payload = fetch_json(url=url, headers=BROWSER_LIKE_HEADERS)
        games = _extract_games(payload)
        print("raw_response:", json.dumps(payload, indent=2))
        print("extracted_games_count:", len(games))
        return 0
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print("error:", repr(exc))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose NHL schedule fetch behavior for a specific date.")
    parser.add_argument("--date", required=True, help="ISO date, e.g. 2026-03-24")
    args = parser.parse_args()
    return run(date.fromisoformat(args.date))


if __name__ == "__main__":
    raise SystemExit(main())
