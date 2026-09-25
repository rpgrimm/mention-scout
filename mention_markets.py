#!/usr/bin/env python3
"""List calendar-added mention events and open Google News tabs per market word.

Discovery only. Never places or cancels orders. Public unauthenticated Kalshi
GET plus local calendar-added JSON; no API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen as stdlib_urlopen

VERSION = "1.0.0"
DEFAULT_JSON_PATH = Path.home() / ".config" / "mention-scout" / "calendar-added.json"
KALSHI_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
KNOWN_ACTIONS = ("google-news",)
DEFAULT_ACTION = "google-news"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3
DEFAULT_SLEEP = 0.15
PAGE_LIMIT = 1000
MAX_PAGES = 20
TRAILING_TIMES_RE = re.compile(r"\s*\(\d+\+?\s+times\)\s*$", re.IGNORECASE)
SLASH_RE = re.compile(r"[/\\]")

urlopen = stdlib_urlopen
Opener = Callable[[str], Any]
SleepFn = Callable[[float], None]
UrlOpenFn = Callable[..., Any]


@dataclass(frozen=True)
class ListedEvent:
    ticker: str
    added_at_utc: str
    matched_phrase: str


@dataclass(frozen=True)
class NewsTab:
    word: str
    url: str
    ticker: str


class MentionMarketsError(RuntimeError):
    """User-facing failure with an actionable message."""


def ticker_from_key(key: str) -> str:
    """Return the event ticker, stripping a ``::calendar_id`` suffix when present."""
    raw = str(key or "").strip()
    if "::" in raw:
        raw = raw.split("::", 1)[0].strip()
    return raw


def _parse_added_at(value: str) -> tuple[int, datetime | str]:
    text = str(value or "")
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        return (0, datetime.fromisoformat(normalized))
    except ValueError:
        return (1, text)


def load_listed_events(path: Path) -> list[ListedEvent]:
    """Load unique event tickers from calendar-added JSON; latest added_at_utc wins."""
    json_path = path.expanduser()
    try:
        raw = json_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MentionMarketsError(
            f"calendar-added JSON not found: {json_path}\n"
            "Pass --json PATH or add events with mention-scout --calendar-add-new."
        ) from exc
    except OSError as exc:
        raise MentionMarketsError(f"cannot read calendar-added JSON {json_path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MentionMarketsError(
            f"calendar-added JSON is not valid JSON ({json_path}): {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise MentionMarketsError(f"calendar-added JSON must be an object: {json_path}")
    if payload.get("version") != 1:
        raise MentionMarketsError(
            f"calendar-added JSON version must be 1 (got {payload.get('version')!r}) in {json_path}"
        )
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise MentionMarketsError(f"calendar-added JSON 'entries' must be an object: {json_path}")

    winners: dict[str, ListedEvent] = {}
    for key, value in entries.items():
        ticker = ticker_from_key(str(key))
        if not ticker:
            continue
        if not isinstance(value, dict):
            raise MentionMarketsError(
                f"calendar-added entry {key!r} must be an object in {json_path}"
            )
        event = ListedEvent(
            ticker=ticker,
            added_at_utc=str(value.get("added_at_utc") or ""),
            matched_phrase=str(value.get("matched_phrase") or ""),
        )
        lookup = ticker.casefold()
        previous = winners.get(lookup)
        if previous is None or _parse_added_at(event.added_at_utc) > _parse_added_at(
            previous.added_at_utc
        ):
            winners[lookup] = event

    return sorted(winners.values(), key=lambda item: _parse_added_at(item.added_at_utc), reverse=True)


def find_event(events: list[ListedEvent], requested: str) -> ListedEvent | None:
    """Match an event ticker case-insensitively; accept a raw ``::`` state key."""
    wanted = ticker_from_key(requested).casefold()
    if not wanted:
        return None
    for event in events:
        if event.ticker.casefold() == wanted:
            return event
    return None


def market_word(market: dict[str, Any]) -> str:
    """Return the human word/phrase for a mention market (trader market_word idea)."""
    custom = market.get("custom_strike") or {}
    if not isinstance(custom, dict):
        custom = {}

    for value in (market.get("yes_sub_title"), market.get("subtitle")):
        if value and SLASH_RE.search(str(value)):
            return str(value)

    word = (
        custom.get("Word")
        or market.get("yes_sub_title")
        or market.get("subtitle")
        or market.get("ticker")
        or "UNKNOWN"
    )
    return str(word)


def google_news_query(word: str) -> str:
    """Turn a market word into a Google ``{cleaned} news`` query."""
    cleaned = str(word or "").replace("/", " ").replace("\\", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = TRAILING_TIMES_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    return f"{cleaned} news"


def google_search_url(query: str) -> str:
    """Return a Google search URL for the query."""
    return "https://www.google.com/search?" + urlencode({"q": query})


def is_open_market(market: dict[str, Any]) -> bool:
    """Keep markets Kalshi reports as active or open."""
    status = str(market.get("status") or "").casefold()
    return status in {"active", "open"}


def public_json_get(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    urlopen_fn: UrlOpenFn | None = None,
    sleep_fn: SleepFn | None = None,
) -> dict[str, Any]:
    """Unauthenticated public Kalshi GET with JSON response and modest retries."""
    opener = urlopen_fn or urlopen
    sleeper = sleep_fn or time.sleep
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"mention-markets/{VERSION}",
            },
            method="GET",
        )
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            decoded = json.loads(raw) if raw else {}
            if not isinstance(decoded, dict):
                raise MentionMarketsError("Kalshi returned JSON that was not an object")
            return decoded
        except HTTPError as exc:
            last_error = exc
            if exc.code != 429 and not 500 <= exc.code <= 599:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                raise MentionMarketsError(
                    f"HTTP {exc.code} from Kalshi: {body or exc.reason}"
                ) from exc
            if attempt >= retries:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                raise MentionMarketsError(
                    f"HTTP {exc.code} from Kalshi: {body or exc.reason}"
                ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                raise MentionMarketsError(f"Unable to fetch Kalshi data: {exc}") from exc
        except MentionMarketsError:
            raise

        delay = min(8.0, 0.75 * (2**attempt))
        sleeper(delay)

    raise MentionMarketsError(f"Unable to fetch Kalshi data: {last_error}")


def fetch_markets_rest_paginated(
    event_ticker: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    urlopen_fn: UrlOpenFn | None = None,
    sleep_fn: SleepFn | None = None,
) -> list[dict[str, Any]]:
    """Fetch markets for one event via public REST limit/cursor pagination."""
    markets: list[dict[str, Any]] = []
    cursor = ""
    pages = 0
    seen_cursors: set[str] = set()
    while True:
        pages += 1
        params: dict[str, Any] = {
            "event_ticker": event_ticker,
            "limit": PAGE_LIMIT,
        }
        if cursor:
            params["cursor"] = cursor
        url = f"{KALSHI_MARKETS_URL}?{urlencode(params)}"
        data = public_json_get(
            url,
            timeout=timeout,
            retries=retries,
            urlopen_fn=urlopen_fn,
            sleep_fn=sleep_fn,
        )
        page_markets = data.get("markets") or []
        if not isinstance(page_markets, list):
            raise MentionMarketsError("Kalshi /markets response did not contain a markets list")
        for item in page_markets:
            if isinstance(item, dict):
                markets.append(item)

        cursor = str(data.get("cursor") or "")
        if not cursor:
            break
        if cursor in seen_cursors:
            raise MentionMarketsError(
                "Kalshi /markets pagination cursor repeated; refusing loop"
            )
        seen_cursors.add(cursor)
        if pages >= MAX_PAGES:
            raise MentionMarketsError(
                f"Stopped after {MAX_PAGES} /markets pages; refusing to continue pagination loop"
            )
    return markets


def news_tabs_for_markets(markets: list[dict[str, Any]]) -> list[NewsTab]:
    """Build one Google News tab per unique active/open market ticker."""
    by_ticker: dict[str, dict[str, Any]] = {}
    for market in markets:
        if not is_open_market(market):
            continue
        ticker = str(market.get("ticker") or "").strip()
        if not ticker or ticker in by_ticker:
            continue
        by_ticker[ticker] = market

    tabs: list[NewsTab] = []
    for ticker, market in by_ticker.items():
        word = market_word(market).strip()
        if not word or word.casefold() == "unknown":
            continue
        query = google_news_query(word)
        if not query:
            continue
        tabs.append(NewsTab(word=word, url=google_search_url(query), ticker=ticker))

    tabs.sort(key=lambda tab: (tab.word.casefold(), tab.ticker))
    return tabs


def looks_headless(environ: Mapping[str, str]) -> bool:
    """True when neither DISPLAY nor WAYLAND_DISPLAY is set."""
    return not environ.get("DISPLAY") and not environ.get("WAYLAND_DISPLAY")


def open_news_tabs(
    tabs: list[NewsTab],
    *,
    opener: Opener,
    sleep: float,
    sleep_fn: SleepFn | None = None,
) -> None:
    """Open one browser tab per market; warn and continue if a single open fails."""
    sleeper = sleep_fn or time.sleep
    for index, tab in enumerate(tabs):
        try:
            accepted = opener(tab.url)
        except Exception as exc:  # noqa: BLE001 - keep going after one tab failure
            print(f"warning: failed to open tab for {tab.word!r}: {exc}", file=sys.stderr)
        else:
            if accepted is False:
                print(
                    f"warning: browser did not accept tab for {tab.word!r}: {tab.url}",
                    file=sys.stderr,
                )
        if sleep > 0 and index < len(tabs) - 1:
            sleeper(sleep)


def cmd_list(json_path: Path) -> int:
    events = load_listed_events(json_path)
    for event in events:
        print(f"{event.ticker}\t{event.added_at_utc}\t{event.matched_phrase}")
    return 0


def cmd_target(
    json_path: Path,
    requested_ticker: str,
    *,
    action: str,
    dry_run: bool,
    sleep: float,
    opener: Opener | None,
    urlopen_fn: UrlOpenFn | None,
    sleep_fn: SleepFn | None,
    environ: Mapping[str, str],
) -> int:
    known = ", ".join(KNOWN_ACTIONS)
    if action not in KNOWN_ACTIONS:
        print(f"Unknown action {action!r}. Known actions: {known}", file=sys.stderr)
        return 1

    events = load_listed_events(json_path)
    event = find_event(events, requested_ticker)
    if event is None:
        print(
            f"Event ticker {requested_ticker!r} not found in {json_path.expanduser()}. "
            "Run: ./mention_markets.py list",
            file=sys.stderr,
        )
        return 1

    markets = fetch_markets_rest_paginated(
        event.ticker,
        urlopen_fn=urlopen_fn,
        sleep_fn=sleep_fn,
    )
    tabs = news_tabs_for_markets(markets)
    if not tabs:
        print(
            f"No active/open mention markets with usable words for {event.ticker}",
            file=sys.stderr,
        )
        return 1

    for tab in tabs:
        print(f"{tab.word}\t{tab.url}")

    if dry_run:
        noun = "tab" if len(tabs) == 1 else "tabs"
        print(f"dry-run: {len(tabs)} {noun}", file=sys.stderr)
        return 0

    if looks_headless(environ):
        print(
            "warning: DISPLAY/WAYLAND_DISPLAY unset; this looks headless, still opening tabs",
            file=sys.stderr,
        )

    open_news_tabs(
        tabs,
        opener=opener or webbrowser.open_new_tab,
        sleep=sleep,
        sleep_fn=sleep_fn,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mention_markets.py",
        description=(
            "List calendar-added mention events and open Google News search tabs "
            "for an event's market words. Discovery only — no trading."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mention_markets.py {VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List event tickers from calendar-added JSON")
    list_parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"calendar-added JSON path (default: {DEFAULT_JSON_PATH})",
    )

    target_parser = sub.add_parser(
        "target",
        help="Fetch one event's mention markets and run an action",
    )
    target_parser.add_argument("event_ticker", help="Event ticker (or calendar-added key)")
    target_parser.add_argument(
        "--action",
        default=DEFAULT_ACTION,
        help=f"Action to run (default: {DEFAULT_ACTION}; known: {', '.join(KNOWN_ACTIONS)})",
    )
    target_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print word/url pairs; do not open a browser",
    )
    target_parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"calendar-added JSON path (default: {DEFAULT_JSON_PATH})",
    )
    target_parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP,
        help=f"Delay in seconds between browser tabs (default: {DEFAULT_SLEEP})",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    opener: Opener | None = None,
    urlopen_fn: UrlOpenFn | None = None,
    sleep_fn: SleepFn | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = environ if environ is not None else os.environ
    try:
        if args.command == "list":
            return cmd_list(args.json_path)
        if getattr(args, "sleep", 0) < 0:
            print("--sleep cannot be negative", file=sys.stderr)
            return 1
        return cmd_target(
            args.json_path,
            args.event_ticker,
            action=str(args.action).strip() or DEFAULT_ACTION,
            dry_run=bool(args.dry_run),
            sleep=float(args.sleep),
            opener=opener,
            urlopen_fn=urlopen_fn,
            sleep_fn=sleep_fn,
            environ=env,
        )
    except MentionMarketsError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
