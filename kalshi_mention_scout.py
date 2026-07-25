#!/usr/bin/env python3
"""
kalshi_mention_scout_v16.py

Find active/upcoming Kalshi mention-style markets, with a disk-backed cache.

Time concepts are intentionally separated:
  * event date/time: parent-event occurrence/start metadata when supplied; then
    strike_date, a human-readable parent subtitle date (for example ``On Jun 23,
    2026``), a date encoded in the event ticker, then expected expiration as a
    clearly labelled last resort.
  * trading close: the time Kalshi stops accepting orders. It can be long after
    the speech/game/show, so it is not a reliable schedule for upcoming events.

Default behavior: show open and unopened mention events whose Kalshi event date
falls in the next N calendar days, including today. Use --status upcoming (or
--include-inactive) to additionally include temporarily inactive/paused markets;
use --window all for the entire selected-status inventory.

Changes in v7:
  * Fixes the central scheduling bug: sorts and filters upcoming events by their
    event date rather than their trading close time.
  * Shows both event time/date and trading-close time in human output.
  * Adds --sort auto|event|close. ``auto`` uses event order for --window event
    and trading-close order for --window all/closing.
  * Defaults to a compact mention-only cache. It discovers live events through
    /events with nested markets, then persists only matching mention contracts.
  * Adds --full-cache for the old, much larger complete /markets snapshot.

Changes in v9:
  * Reads event dates from parent-event subtitles such as ``On Jun 23, 2026``.
  * Checks multiple Kalshi schedule fields before falling back to ticker dates.
  * Reconstructs a missing parent event ticker from a child contract ticker.

Changes in v10:
  * Fixes compact-cache status handling: nested market API status ``active`` is
    now kept as display metadata while the requested query status (``open`` or
    ``unopened``) is used for filtering. This prevents a fresh compact cache
    from being incorrectly filtered down to zero results.
  * Bumps the cache format so a v9 compact cache is rebuilt once with the
    corrected query-status marker.

Changes in v16:
  * Adds a clickable Kalshi event-page URL to new-market notification emails.
    The URL uses any explicit Kalshi URL field when present; otherwise it is
    built from the parent series/event ticker and a safe title slug.

Changes in v15:
  * Adds Gmail credential loading from ``~/.config/.google-password`` for
    ``--email-new`` and a fail-fast ``--test-email`` path. The credential file
    is sourced with zsh so a non-exported ``GOOGLE_PASSWORD=...`` assignment
    works just like it does in an interactive zsh shell.

Changes in v14:
  * Adds ``--queue-initialized`` for ``--watch-new``. The scout writes a small,
    durable JSON handoff file for each mention event containing one or more
    initialized/unopened contracts. A separate opener watcher can consume those
    files without repeating the scout's broad discovery scan.
  * Changes the default watch refresh interval from 15 minutes to 5 minutes.

Changes in v13:
  * Adds opt-in ``--email-new`` for ``--watch-new``. Each newly discovered
    parent mention event triggers one concise overview email through ``swaks``.
    Credentials stay outside the script in the ``GOOGLE_PASSWORD`` environment
    variable; no password is written to the scout cache or terminal output.

Changes in v12:
  * Adds ``--watch-new``: prints an initial overview, then refreshes on an
    interval (15 minutes by default) and loudly prints full detailed contract
    information only for newly discovered parent mention events.
  * Watch mode defaults to the all-status upcoming inventory (open, unopened,
    paused/inactive) and can still respect an explicitly supplied --status or
    --window filter.

Changes in v11:
  * Adds ``--status upcoming`` and ``--include-inactive``. Both include
    Kalshi's paused query state (raw lifecycle status ``inactive``) alongside
    active and unopened contracts.
  * Adds ``--status paused`` for inactive-only inspection. Because /events does
    not offer a paused filter, compact discovery supplements its efficient
    open/unopened event scan with a targeted ``/markets?status=paused`` pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION = "16.0.0"
CACHE_FORMAT_VERSION = 5
DEFAULT_MENTION_CACHE_FILE = ".kalshi_mention_scout_mentions_cache.json"
DEFAULT_FULL_CACHE_FILE = ".kalshi_mention_scout_full_cache.json"
DEFAULT_CACHE_TTL_SECONDS = 300.0
DEFAULT_OPEN_QUEUE_DIR = "mention_open_queue"
QUEUE_FORMAT_VERSION = 1
DEFAULT_GOOGLE_PASSWORD_FILE = Path("~/.config/.google-password")

BASE_URLS = {
    "prod": "https://api.elections.kalshi.com/trade-api/v2",
    "external": "https://external-api.kalshi.com/trade-api/v2",
    "demo": "https://demo-api.kalshi.co/trade-api/v2",
}

# Conventional ticker names catch series such as KXTRUMPMENTION. Text rules
# catch series such as KXTRUMPSAY, whose titles ask what someone will say.
MENTION_RE = re.compile(
    r"(?:\bmention(?:s|ed|ing)?\b|\b(?:say|says|said|saying)\b[^.]{0,100}?\b(?:word|words|phrase|phrases|times?)\b)",
    re.IGNORECASE,
)
SAY_EVENT_RE = re.compile(
    r"\bwhat\s+(?:will|would|does|did)\b.{0,120}?\b(?:say|says|said)\b",
    re.IGNORECASE,
)

# Many Kalshi event tickers encode an event date such as ``-26JUN23``. This is
# a useful date-only fallback when the parent event does not expose strike_date.
EVENT_TICKER_DATE_RE = re.compile(
    r"(?<!\d)(?P<yy>\d{2})(?P<mon>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(?P<day>\d{2})(?!\d)",
    re.IGNORECASE,
)
MONTH_NUMBERS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "magenta": "\033[35m",
}


def color(text: str, name: str, enabled: bool) -> str:
    """Return ANSI-colored text only when color output is enabled."""
    return f"{ANSI[name]}{text}{ANSI['reset']}" if enabled else text


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 value into an aware UTC datetime, or return None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def iso_utc(value: datetime) -> str:
    """Render an aware datetime as a compact canonical UTC ISO string."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def money(value: Any) -> str:
    """Format Kalshi decimal-dollar fields as percentages while preserving zero."""
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return str(value)


def canonical_base_url(value: str) -> str:
    return value.rstrip("/")


def http_get_json(url: str, timeout: float, retries: int, verbose: bool) -> dict[str, Any]:
    """Fetch one JSON response with modest retry/backoff for transient failures."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"kalshi-mention-scout/{VERSION}",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("Kalshi returned JSON that was not an object")
            return decoded
        except HTTPError as exc:
            last_error = exc
            if exc.code != 429 and not 500 <= exc.code <= 599:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"HTTP {exc.code} from Kalshi: {body or exc.reason}") from exc
            if attempt >= retries:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"HTTP {exc.code} from Kalshi: {body or exc.reason}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                raise RuntimeError(f"Unable to fetch Kalshi data: {exc}") from exc

        delay = min(8.0, 0.75 * (2**attempt))
        if verbose:
            print(f"retrying after {delay:.2f}s: {last_error}", file=sys.stderr)
        time.sleep(delay)

    raise RuntimeError(f"Unable to fetch Kalshi data: {last_error}")


def iter_markets(
    base_url: str,
    timeout: float,
    retries: int,
    verbose: bool,
    statuses: tuple[str, ...],
) -> Iterable[dict[str, Any]]:
    """Yield every non-MVE market in each requested live status.

    v3 intentionally does not send min_close_ts/max_close_ts here. Kalshi's
    documented compatibility table allows those filters with closed or
    unfiltered queries, not with the open/unopened scans used by this tool.
    The requested close-time window is therefore applied locally afterward.
    """
    for wanted_status in statuses:
        cursor: str | None = None
        page_number = 0
        while True:
            params: dict[str, Any] = {
                "status": wanted_status,
                "limit": 1000,
                "mve_filter": "exclude",
            }
            if cursor:
                params["cursor"] = cursor

            url = f"{canonical_base_url(base_url)}/markets?{urlencode(params)}"
            payload = http_get_json(url, timeout, retries, verbose)
            markets = payload.get("markets", [])
            if not isinstance(markets, list):
                raise RuntimeError("Kalshi response did not contain a markets list")

            page_number += 1
            if verbose:
                print(
                    f"{wanted_status} page {page_number}: fetched {len(markets)} markets",
                    file=sys.stderr,
                )

            for market in markets:
                if isinstance(market, dict):
                    market_copy = dict(market)
                    # Preserve the actual query used, regardless of whether
                    # this API response names the market status 'open' or 'active'.
                    market_copy.setdefault("_scan_status", wanted_status)
                    yield market_copy

            next_cursor = payload.get("cursor")
            if not next_cursor:
                break
            if not isinstance(next_cursor, str):
                raise RuntimeError("Kalshi response included a malformed cursor")
            cursor = next_cursor



def iter_events_with_nested_markets(
    base_url: str,
    timeout: float,
    retries: int,
    verbose: bool,
    statuses: tuple[str, ...],
) -> Iterable[tuple[dict[str, Any], str]]:
    """Yield live parent events with their nested market objects.

    This is the default discovery path. Kalshi does not expose a general title /
    regex search parameter for ``/markets``; the scanner therefore still has to
    inspect live event metadata, but it writes only matching mention contracts to
    disk. ``with_nested_markets=true`` lets one event scan provide the child
    contracts and parent metadata together.
    """
    for wanted_status in statuses:
        cursor: str | None = None
        page_number = 0
        while True:
            params: dict[str, Any] = {
                "status": wanted_status,
                "limit": 200,
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            url = f"{canonical_base_url(base_url)}/events?{urlencode(params)}"
            payload = http_get_json(url, timeout, retries, verbose)
            events = payload.get("events", [])
            if not isinstance(events, list):
                raise RuntimeError("Kalshi event response did not contain an events list")
            page_number += 1
            if verbose:
                print(
                    f"{wanted_status} event page {page_number}: fetched {len(events)} events",
                    file=sys.stderr,
                )
            for event in events:
                if isinstance(event, dict):
                    yield dict(event), wanted_status
            next_cursor = payload.get("cursor")
            if not next_cursor:
                break
            if not isinstance(next_cursor, str):
                raise RuntimeError("Kalshi event response included a malformed cursor")
            cursor = next_cursor


def event_text_for_match(event: dict[str, Any]) -> str:
    """Return parent event fields useful for lightweight mention detection."""
    fields = ("event_ticker", "series_ticker", "title", "sub_title", "category")
    return "\n".join(str(event.get(field, "")) for field in fields)


def is_mention_event(event: dict[str, Any]) -> bool:
    """Classify a parent event before persisting any nested child contracts."""
    ticker_text = f"{event.get('event_ticker', '')} {event.get('series_ticker', '')}".upper()
    if "MENTION" in ticker_text:
        return True
    text = event_text_for_match(event)
    return bool(MENTION_RE.search(text) or SAY_EVENT_RE.search(text))


def compact_event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """Keep parent metadata without duplicating its nested child market array."""
    return {key: value for key, value in event.items() if key != "markets"}


def scan_mention_events(
    base_url: str,
    timeout: float,
    retries: int,
    verbose: bool,
    statuses: tuple[str, ...],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    """Discover live events and retain only mention-style child contracts.

    Returns compact mention markets, parent event metadata, and the count of
    parent event records inspected. A market can appear in more than one event
    status scan, so ticker-level de-duplication is applied before caching.
    """
    by_ticker: dict[str, dict[str, Any]] = {}
    event_details: dict[str, dict[str, Any]] = {}
    source_event_count = 0

    for event, requested_status in iter_events_with_nested_markets(
        base_url, timeout, retries, verbose, statuses
    ):
        source_event_count += 1
        event_ticker = event.get("event_ticker")
        markets = event.get("markets", [])
        nested_markets = [item for item in markets if isinstance(item, dict)] if isinstance(markets, list) else []

        # Some parent events are unambiguously mention markets from their
        # ticker/title. Others are recognized from the child market text/rules,
        # retaining compatibility with the older full-market classifier.
        matches_event = is_mention_event(event) or any(is_mention_market(item) for item in nested_markets)
        if not matches_event:
            continue

        if isinstance(event_ticker, str) and event_ticker:
            event_details[event_ticker] = {
                "fetched_at_utc": iso_utc(datetime.now(timezone.utc)),
                "event": compact_event_metadata(event),
            }

        for child in nested_markets:
            market = dict(child)
            if not market.get("event_ticker") and isinstance(event_ticker, str):
                market["event_ticker"] = event_ticker
            # ``status`` on a nested market can be the display/lifecycle value
            # ``active`` even when this parent event was returned by the API's
            # ``status=open`` query.  Keep the raw API value for display, but
            # preserve the query status for reliable later filtering.
            market["_scan_status"] = requested_status

            # Preserve the existing detection semantics. A parent match alone
            # is sufficient: the child outcomes are the words/phrases inside
            # that mention event even when an individual title lacks the word.
            if not is_mention_event(event) and not is_mention_market(market):
                continue

            ticker = market.get("ticker")
            if not isinstance(ticker, str) or not ticker:
                continue
            # Prefer an explicitly open result if a ticker is duplicated across
            # the open/unopened event scans.
            existing = by_ticker.get(ticker)
            if existing is None or (
                cached_market_status(existing) != "open" and cached_market_status(market) == "open"
            ):
                by_ticker[ticker] = market

    return list(by_ticker.values()), event_details, source_event_count


def scan_paused_mention_markets(
    base_url: str,
    timeout: float,
    retries: int,
    verbose: bool,
) -> tuple[list[dict[str, Any]], int]:
    """Discover temporarily inactive mention markets via ``status=paused``.

    Kalshi's /events endpoint accepts only unopened/open/closed/settled filters.
    The /markets endpoint additionally accepts ``paused``, which maps to raw
    market lifecycle status ``inactive``.  We therefore use this small second
    scan only when the user explicitly requests inactive contracts.
    """
    paused_markets = list(iter_markets(base_url, timeout, retries, verbose, ("paused",)))
    mentions: list[dict[str, Any]] = []
    for raw_market in paused_markets:
        market = dict(raw_market)
        market["_scan_status"] = "paused"
        if is_mention_market(market):
            mentions.append(market)
    return mentions, len(paused_markets)


def merge_market_lists(*market_lists: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-duplicate markets from open/unopened event scans and paused scan.

    The same ticker should not normally occur in multiple lifecycle filters, but
    keeping this defensive merge makes cache contents deterministic if Kalshi
    transitions a contract during a paginated discovery run.
    """
    rank = {"open": 0, "paused": 1, "unopened": 2}
    by_ticker: dict[str, dict[str, Any]] = {}
    for market_list in market_lists:
        for market in market_list:
            ticker = market.get("ticker")
            if not isinstance(ticker, str) or not ticker:
                continue
            existing = by_ticker.get(ticker)
            if existing is None:
                by_ticker[ticker] = market
                continue
            old_status = cached_market_status(existing) or "unknown"
            new_status = cached_market_status(market) or "unknown"
            if rank.get(new_status, 99) < rank.get(old_status, 99):
                by_ticker[ticker] = market
    return list(by_ticker.values())


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    """Yield consecutive slices without creating one oversized API query."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def fetch_event_metadata(
    base_url: str,
    event_tickers: list[str],
    timeout: float,
    retries: int,
    verbose: bool,
) -> dict[str, dict[str, Any]]:
    """Fetch concise event title/subtitle metadata in bounded batch requests.

    Kalshi's /events endpoint accepts a comma-separated ``tickers`` parameter.
    Event records describe the parent real-world event, unlike the individual
    child markets whose titles are often the specific words/outcomes.
    """
    found: dict[str, dict[str, Any]] = {}
    for ticker_batch in chunks(event_tickers, 50):
        params = {"tickers": ",".join(ticker_batch)}
        url = f"{canonical_base_url(base_url)}/events?{urlencode(params)}"
        payload = http_get_json(url, timeout, retries, verbose)
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise RuntimeError("Kalshi event response did not contain an events list")
        for event in events:
            if not isinstance(event, dict):
                continue
            ticker = event.get("event_ticker")
            if isinstance(ticker, str) and ticker:
                found[ticker] = event
    return found


# ---------------------------------------------------------------------------
# Disk cache: complete open/unopened snapshot, not a seven-day subwindow.
# ---------------------------------------------------------------------------


def cache_file_default(full_cache: bool) -> Path:
    """Keep cache files local, using separate files for compact/full modes."""
    return Path.cwd() / (DEFAULT_FULL_CACHE_FILE if full_cache else DEFAULT_MENTION_CACHE_FILE)


def load_cache(cache_path: Path, verbose: bool) -> dict[str, Any] | None:
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        if verbose:
            print(f"ignoring unreadable cache {cache_path}: {exc}", file=sys.stderr)
        return None

    if not isinstance(payload, dict) or payload.get("cache_format_version") != CACHE_FORMAT_VERSION:
        if verbose:
            print(f"ignoring incompatible cache {cache_path}", file=sys.stderr)
        return None
    if not isinstance(payload.get("markets"), list) or not isinstance(payload.get("statuses"), list):
        if verbose:
            print(f"ignoring malformed cache {cache_path}", file=sys.stderr)
        return None
    return payload


def cache_usable(
    cache: dict[str, Any],
    base_url: str,
    statuses: tuple[str, ...],
    now: datetime,
    ttl_seconds: float,
    cache_mode: str,
) -> tuple[bool, str, float | None]:
    """Return whether a compact mention or complete full snapshot is fresh."""
    if canonical_base_url(str(cache.get("api_base_url", ""))) != canonical_base_url(base_url):
        return False, "API endpoint differs", None
    if cache.get("cache_mode") != cache_mode:
        return False, "cache mode differs", None

    fetched_at = parse_iso(cache.get("fetched_at_utc"))
    raw_statuses = cache.get("statuses")
    if fetched_at is None or not isinstance(raw_statuses, list):
        return False, "cache metadata is incomplete", None

    age_seconds = max(0.0, (now - fetched_at).total_seconds())
    if age_seconds > ttl_seconds:
        return False, f"age {age_seconds:.0f}s exceeds TTL {ttl_seconds:.0f}s", age_seconds

    cached_statuses = {item for item in raw_statuses if isinstance(item, str)}
    if not set(statuses).issubset(cached_statuses):
        return False, "cached status set is too narrow", age_seconds

    expected_scope = "complete_markets_scan" if cache_mode == "full" else "mention_events_scan"
    if cache.get("snapshot_scope") != expected_scope:
        return False, "cache snapshot scope differs", age_seconds
    return True, "fresh", age_seconds

def write_cache_atomic(cache_path: Path, payload: dict[str, Any]) -> None:
    """Write cache atomically and keep cache files private to the local user."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, cache_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def build_cache_payload(
    base_url: str,
    statuses: tuple[str, ...],
    markets: list[dict[str, Any]],
    cache_mode: str,
    event_details: dict[str, dict[str, Any]] | None = None,
    source_event_count: int | None = None,
    source_paused_market_count: int | None = None,
) -> dict[str, Any]:
    """Create an on-disk cache payload for compact mention or full mode."""
    full_mode = cache_mode == "full"
    return {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "tool_version": VERSION,
        "fetched_at_utc": iso_utc(datetime.now(timezone.utc)),
        "api_base_url": canonical_base_url(base_url),
        "statuses": list(statuses),
        "cache_mode": cache_mode,
        "snapshot_scope": "complete_markets_scan" if full_mode else "mention_events_scan",
        "market_count": len(markets),
        "source_event_count": source_event_count,
        "source_paused_market_count": source_paused_market_count,
        # In compact mode these parent records came from the discovery scan.
        # In full mode they are lazily filled on demand for overview/event dates.
        "event_details": event_details or {},
        "markets": markets,
    }


# ---------------------------------------------------------------------------
# Selection / classification / rendering
# ---------------------------------------------------------------------------


def cached_market_status(market: dict[str, Any]) -> str | None:
    """Return the status requested from Kalshi, normalized for older caches.

    The nested-event endpoint commonly labels a currently tradable market
    ``active``.  The scout's command-line filter, however, uses Kalshi query
    values ``open`` and ``unopened``.  Prefer the saved query marker; map old
    v9 ``active`` markers to ``open`` only as a defensive compatibility path.
    """
    status = market.get("_scan_status") or market.get("status")
    if not isinstance(status, str):
        return None
    normalized = status.strip().lower()
    aliases = {
        "active": "open",
        "opened": "open",
        "open": "open",
        "unopened": "unopened",
        "initialized": "unopened",
        "paused": "paused",
        "inactive": "paused",
    }
    return aliases.get(normalized, normalized)


def close_time(market: dict[str, Any]) -> datetime | None:
    return parse_iso(market.get("close_time"))


def closes_in_window(market: dict[str, Any], start: datetime, end: datetime) -> bool:
    value = close_time(market)
    return value is not None and start <= value <= end


def text_for_market(market: dict[str, Any]) -> str:
    fields = (
        "ticker",
        "event_ticker",
        "title",
        "subtitle",
        "yes_sub_title",
        "no_sub_title",
        "rules_primary",
        "rules_secondary",
    )
    return "\n".join(str(market.get(field, "")) for field in fields)


def is_mention_market(market: dict[str, Any]) -> bool:
    ticker_text = f"{market.get('ticker', '')} {market.get('event_ticker', '')}".upper()
    if "MENTION" in ticker_text:
        return True
    text = text_for_market(market)
    return bool(MENTION_RE.search(text) or SAY_EVENT_RE.search(text))


def contains_filter(market: dict[str, Any], needle: str | None) -> bool:
    return not needle or needle.casefold() in text_for_market(market).casefold()


# Parent event data is not perfectly uniform across Kalshi market families.
# The common ``sub_title: On Jun 23, 2026`` form is especially useful for
# scheduled mention markets that do not have a machine-readable start field.
HUMAN_EVENT_DATE_RE = re.compile(
    r"\b(?:on|for|during|at)\s+"
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?[,]?\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
ISO_CALENDAR_DATE_RE = re.compile(r"\b(?P<year>20\d{2})-(?P<mon>\d{2})-(?P<day>\d{2})\b")
HUMAN_MONTH_NUMBERS = {
    "JAN": 1, "JANUARY": 1, "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4, "MAY": 5, "JUN": 6, "JUNE": 6, "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8, "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "OCT": 10,
    "OCTOBER": 10, "NOV": 11, "NOVEMBER": 11, "DEC": 12, "DECEMBER": 12,
}


def market_event_ticker(market: dict[str, Any]) -> str | None:
    """Return the parent event ticker, even if a nested child omitted it.

    Most Kalshi child tickers are ``EVENT-TICKER-OUTCOME``. The compact cache
    sometimes receives a nested market without its redundant event_ticker
    field, so recovering the parent prefix keeps cached event metadata usable.
    """
    raw = market.get("event_ticker")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    ticker = market.get("ticker")
    if isinstance(ticker, str) and "-" in ticker:
        parent, _separator, _outcome = ticker.rpartition("-")
        if parent:
            return parent
    return None


def local_calendar_date_utc(year: int, month: int, day: int, local_tz: ZoneInfo) -> datetime | None:
    """Represent a date-only Kalshi value as local midnight, then normalize UTC."""
    try:
        return datetime(year, month, day, tzinfo=local_tz).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_event_date_value(value: Any, local_tz: ZoneInfo) -> datetime | None:
    """Parse ISO timestamps and date-only ISO fields without losing local date intent."""
    if not isinstance(value, str) or not value.strip():
        return None
    compact = value.strip()
    iso_match = ISO_CALENDAR_DATE_RE.fullmatch(compact)
    if iso_match:
        return local_calendar_date_utc(
            int(iso_match.group("year")), int(iso_match.group("mon")), int(iso_match.group("day")), local_tz
        )
    return parse_iso(compact)


def subtitle_event_date(value: Any, local_tz: ZoneInfo) -> datetime | None:
    """Extract a date from a parent subtitle such as ``On Jun 23, 2026``."""
    if not isinstance(value, str):
        return None
    match = HUMAN_EVENT_DATE_RE.search(" ".join(value.split()))
    if not match:
        return None
    month = HUMAN_MONTH_NUMBERS.get(match.group("mon").upper())
    if month is None:
        return None
    return local_calendar_date_utc(int(match.group("year")), month, int(match.group("day")), local_tz)


def event_ticker_date(event_ticker: Any, local_tz: ZoneInfo) -> datetime | None:
    """Read an event date encoded as YYMONDD from a Kalshi event ticker.

    This fallback deliberately represents the *date* as local midnight. The
    source label makes clear that the exact on-air/start time was not supplied.
    """
    if not isinstance(event_ticker, str):
        return None
    match = EVENT_TICKER_DATE_RE.search(event_ticker.upper())
    if not match:
        return None
    try:
        year = 2000 + int(match.group("yy"))
        month = MONTH_NUMBERS[match.group("mon").upper()]
        day = int(match.group("day"))
        return datetime(year, month, day, tzinfo=local_tz).astimezone(timezone.utc)
    except (KeyError, ValueError):
        return None


def event_schedule_for_market(
    market: dict[str, Any],
    event: dict[str, Any] | None,
    local_tz: ZoneInfo,
) -> tuple[datetime | None, str]:
    """Choose the best available event schedule date/time without using close_time.

    A future start time is not consistently available across Kalshi series. This
    resolver prefers precise parent-event schedule fields, then date-only parent
    fields and subtitles, and finally the date embedded in the event ticker.
    Every fallback is labelled in the terminal output.
    """
    if isinstance(event, dict):
        # Exact or potentially exact schedule fields observed across event APIs.
        for field in (
            "occurrence_datetime", "occurrence_time", "scheduled_datetime",
            "event_datetime", "start_datetime", "start_time", "start_ts",
        ):
            value = parse_event_date_value(event.get(field), local_tz)
            if value is not None:
                return value, f"Kalshi event {field}"

        # These can be date-only, so preserve them in the requested local zone.
        for field in ("strike_date", "event_date", "scheduled_date", "date"):
            value = parse_event_date_value(event.get(field), local_tz)
            if value is not None:
                return value, f"Kalshi event {field}"

        value = subtitle_event_date(event.get("sub_title"), local_tz)
        if value is not None:
            return value, "Kalshi event sub_title date (exact time unavailable)"

    # Some older/full-cache market payloads carry the same useful subtitle.
    for field in ("event_sub_title", "subtitle", "sub_title"):
        value = subtitle_event_date(market.get(field), local_tz)
        if value is not None:
            return value, f"market {field} date (exact time unavailable)"

    value = event_ticker_date(market_event_ticker(market), local_tz)
    if value is not None:
        return value, "ticker date (exact time unavailable)"

    value = parse_event_date_value(market.get("expected_expiration_time"), local_tz)
    if value is not None:
        return value, "expected expiration (schedule fallback)"

    return None, "no event date supplied"


def event_count(markets: list[dict[str, Any]]) -> int:
    return len({str(market_event_ticker(market) or market.get("ticker") or "") for market in markets})


def format_local_time(value: datetime | None, local_tz: ZoneInfo) -> str | None:
    """Render a timestamp including the correct EST/EDT label."""
    if value is None:
        return None
    local = value.astimezone(local_tz)
    return local.strftime("%a, %b %-d, %Y %-I:%M %p %Z")


def market_record(
    market: dict[str, Any],
    local_tz: ZoneInfo,
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    close_utc = close_time(market)
    event_utc, event_time_source = event_schedule_for_market(market, event, local_tz)
    return {
        "ticker": market.get("ticker"),
        "event_ticker": market_event_ticker(market),
        "api_status": market.get("status"),
        "scan_status": market.get("_scan_status"),
        "title": market.get("title") or market.get("subtitle") or market.get("yes_sub_title"),
        "subtitle": market.get("subtitle"),
        "yes_sub_title": market.get("yes_sub_title"),
        "no_sub_title": market.get("no_sub_title"),
        "event_time_utc": iso_utc(event_utc) if event_utc else None,
        "event_time_local": format_local_time(event_utc, local_tz),
        "event_time_source": event_time_source,
        "close_time_utc": iso_utc(close_utc) if close_utc else None,
        "close_time_local": format_local_time(close_utc, local_tz),
        "close_time_local_iso": close_utc.astimezone(local_tz).isoformat() if close_utc else None,
        "expected_expiration_time_utc": (
            iso_utc(value) if (value := parse_iso(market.get("expected_expiration_time"))) else None
        ),
        "yes_bid_dollars": market.get("yes_bid_dollars"),
        "yes_ask_dollars": market.get("yes_ask_dollars"),
        "no_bid_dollars": market.get("no_bid_dollars"),
        "no_ask_dollars": market.get("no_ask_dollars"),
        "last_price_dollars": market.get("last_price_dollars"),
        "volume_fp": market.get("volume_fp"),
        "volume_24h_fp": market.get("volume_24h_fp"),
        "open_interest_fp": market.get("open_interest_fp"),
        "rules_primary": market.get("rules_primary"),
        "rules_secondary": market.get("rules_secondary"),
    }


def record_sort_key(record: dict[str, Any], sort_by: str = "close") -> tuple[datetime, str]:
    """Sort by actual event date or order-close time, then ticker."""
    field = "event_time_utc" if sort_by == "event" else "close_time_utc"
    value = parse_iso(record.get(field))
    return (
        value or datetime.max.replace(tzinfo=timezone.utc),
        str(record.get("ticker", "")),
    )


def status_text(record: dict[str, Any]) -> str:
    return str(record.get("api_status") or record.get("scan_status") or "unknown")


def clean_display_text(value: Any) -> str:
    """Normalize API text so an overview stays one readable terminal line."""
    return " ".join(str(value or "").split()).strip()


def slugify_for_kalshi_url(value: Any) -> str:
    """Make a conservative URL slug for Kalshi's public event route.

    Kalshi's canonical pages include an SEO-friendly middle path segment. The
    parent event ticker at the end is the stable identifier, while this title
    slug keeps the generated URL readable and compatible with the public route.
    """
    text = clean_display_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "market"


def kalshi_event_url(event: dict[str, Any]) -> str | None:
    """Return the best available public Kalshi link for one parent event.

    Some API responses may eventually expose a direct public URL; prefer it.
    Otherwise construct Kalshi's public event-page pattern using stable series
    and event tickers, plus a readable title slug.
    """
    for field in ("web_url", "market_url", "url"):
        value = event.get(field)
        if isinstance(value, str) and value.startswith(("https://kalshi.com/", "http://kalshi.com/")):
            return value

    series_ticker = clean_display_text(event.get("series_ticker"))
    event_ticker = clean_display_text(event.get("event_ticker"))
    if not series_ticker or not event_ticker or event_ticker == "(no event ticker)":
        return None
    title_slug = slugify_for_kalshi_url(event.get("title"))
    return (
        "https://kalshi.com/markets/"
        f"{series_ticker.lower()}/{title_slug}/{event_ticker.lower()}"
    )


def event_overviews(
    records: list[dict[str, Any]],
    event_details: dict[str, dict[str, Any]],
    sort_by: str,
) -> list[dict[str, Any]]:
    """Build one concise display record per Kalshi event."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("event_ticker") or "(no event ticker)")].append(record)

    output: list[dict[str, Any]] = []
    for event_ticker, event_markets in grouped.items():
        event_markets.sort(key=lambda item: record_sort_key(item, sort_by))
        first = event_markets[0]
        cached_detail = event_details.get(event_ticker, {})
        event = cached_detail.get("event") if isinstance(cached_detail, dict) else None
        if not isinstance(event, dict):
            event = {}

        title = clean_display_text(event.get("title")) or clean_display_text(first.get("title"))
        description = (
            clean_display_text(event.get("sub_title"))
            or clean_display_text(event.get("description"))
            or clean_display_text(first.get("subtitle"))
        )
        if description == title:
            description = ""

        close_times = list(dict.fromkeys(
            str(record.get("close_time_local")) for record in event_markets if record.get("close_time_local")
        ))
        event_times = list(dict.fromkeys(
            str(record.get("event_time_local")) for record in event_markets if record.get("event_time_local")
        ))
        event_sources = list(dict.fromkeys(
            str(record.get("event_time_source")) for record in event_markets if record.get("event_time_source")
        ))
        statuses = sorted({status_text(record) for record in event_markets})
        output.append(
            {
                "event_ticker": event_ticker,
                "title": title or "Untitled mention event",
                "description": description or None,
                "category": event.get("category") if isinstance(event.get("category"), str) else None,
                "series_ticker": event.get("series_ticker") if isinstance(event.get("series_ticker"), str) else None,
                "contract_count": len(event_markets),
                "statuses": statuses,
                "event_times_local": event_times,
                "event_time_sources": event_sources,
                "close_times_local": close_times,
                "first_event_time_utc": first.get("event_time_utc"),
                "first_close_time_utc": first.get("close_time_utc"),
            }
        )

    sort_field = "first_event_time_utc" if sort_by == "event" else "first_close_time_utc"
    return sorted(
        output,
        key=lambda item: (
            parse_iso(item.get(sort_field)) or datetime.max.replace(tzinfo=timezone.utc),
            str(item["event_ticker"]),
        ),
    )


def render_overview(events: list[dict[str, Any]], colors: bool) -> None:
    for event in events:
        event_ticker = str(event.get("event_ticker") or "(no event ticker)")
        title = str(event.get("title") or "Untitled mention event")
        event_times = event.get("event_times_local") or []
        close_times = event.get("close_times_local") or []
        event_text = event_times[0] if event_times else "unknown event date"
        close_text = close_times[0] if len(close_times) == 1 else (
            f"{close_times[0]} → {close_times[-1]}" if close_times else "unknown close time"
        )
        sources = ", ".join(str(value) for value in (event.get("event_time_sources") or []))

        print(color(event_ticker, "cyan", colors), color(title, "bold", colors))
        description = event.get("description")
        if description:
            print(f"  description: {description}")
        category = event.get("category")
        if category:
            print(f"  category: {category}")
        print(f"  event: {color(str(event_text), 'magenta', colors)}  |  source: {sources or 'unknown'}")
        print(
            f"  trades close: {color(str(close_text), 'yellow', colors)}  |  "
            f"status: {', '.join(str(x) for x in (event.get('statuses') or ['unknown']))}  |  "
            f"{event.get('contract_count', 0)} contract(s) hidden"
        )
        print()


def render_grouped(records: list[dict[str, Any]], colors: bool, show_rules: bool, sort_by: str) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("event_ticker") or "(no event ticker)")].append(record)

    sorted_groups = sorted(
        grouped.items(),
        key=lambda item: (record_sort_key(min(item[1], key=lambda r: record_sort_key(r, sort_by)), sort_by), item[0]),
    )
    for event_ticker, event_markets in sorted_groups:
        event_markets.sort(key=lambda item: record_sort_key(item, sort_by))
        first = event_markets[0]
        title = str(first.get("title") or "Untitled mention market")
        event_local = str(first.get("event_time_local") or "unknown event date")
        event_source = str(first.get("event_time_source") or "unknown")
        close_local = str(first.get("close_time_local") or "unknown close time")
        print(color(event_ticker, "cyan", colors), color(title, "bold", colors))
        print(f"  event: {color(event_local, 'magenta', colors)}  |  source: {event_source}")
        print(
            f"  trades close: {color(close_local, 'yellow', colors)}  |  "
            f"status: {status_text(first)}  |  {len(event_markets)} contract(s)"
        )
        for record in event_markets:
            ticker = str(record.get("ticker") or "—")
            label = str(record.get("yes_sub_title") or record.get("subtitle") or record.get("title") or "—")
            yes = f"Y {money(record.get('yes_bid_dollars'))}/{money(record.get('yes_ask_dollars'))}"
            no = f"N {money(record.get('no_bid_dollars'))}/{money(record.get('no_ask_dollars'))}"
            volume = record.get("volume_fp")
            print(f"  {color(ticker, 'green', colors)}  {label}")
            print(f"    {yes}  {no}  vol={volume if volume not in (None, '') else '—'}")
            if show_rules:
                rules = str(record.get("rules_primary") or record.get("rules_secondary") or "").strip()
                if rules:
                    print(f"    {color('rules:', 'dim', colors)} {rules}")
        print()


def render_flat(records: list[dict[str, Any]], colors: bool, show_rules: bool) -> None:
    for record in records:
        print(color(str(record.get("ticker") or "—"), "green", colors))
        print(f"  event:  {record.get('event_ticker') or '—'}  |  status: {status_text(record)}")
        print(f"  title:  {record.get('title') or '—'}")
        print(f"  event date:   {color(str(record.get('event_time_local') or '—'), 'magenta', colors)} ({record.get('event_time_source') or 'unknown'})")
        print(f"  trades close: {color(str(record.get('close_time_local') or '—'), 'yellow', colors)}")
        print(
            "  prices: "
            f"YES {money(record.get('yes_bid_dollars'))}/{money(record.get('yes_ask_dollars'))}  "
            f"NO {money(record.get('no_bid_dollars'))}/{money(record.get('no_ask_dollars'))}"
        )
        if show_rules:
            rules = str(record.get("rules_primary") or record.get("rules_secondary") or "").strip()
            if rules:
                print(f"  rules:  {rules}")
        print()


def _argv_has_option(argv: list[str], option: str) -> bool:
    """Return whether ``argv`` contains ``--option`` or ``--option=value``."""
    return any(token == option or token.startswith(f"{option}=") for token in argv)


def _watch_child_arguments(original_argv: list[str]) -> list[str]:
    """Build a one-shot JSON refresh command from the user's watch command.

    The watcher intentionally forces a fresh remote scan every cycle.  It uses
    the normal one-shot code path as the source of truth, so cache behavior,
    event-date parsing, status handling, and future non-watch fixes all remain
    identical between the two modes.
    """
    child: list[str] = []
    skip_next = False
    for token in original_argv:
        if skip_next:
            skip_next = False
            continue
        if token in ("--watch-new", "--email-new", "--queue-initialized"):
            continue
        if token in (
            "--poll-seconds",
            "--email-to",
            "--email-from",
            "--smtp-server",
            "--smtp-auth-user",
            "--queue-dir",
        ):
            skip_next = True
            continue
        if token.startswith((
            "--poll-seconds=",
            "--email-to=",
            "--email-from=",
            "--smtp-server=",
            "--smtp-auth-user=",
            "--queue-dir=",
        )):
            continue
        child.append(token)

    # A watch that is launched with no explicit scope should not silently miss
    # newly listed overnight markets that lack a usable event date.  Respect a
    # caller's explicit choice, but otherwise watch the complete non-closed
    # inventory, including paused/inactive markets.
    if not _argv_has_option(child, "--status"):
        child.extend(("--status", "upcoming"))
    if not _argv_has_option(child, "--window"):
        child.extend(("--window", "all"))

    # ``argparse`` actions are idempotent, so existing occurrences are harmless.
    # No ANSI escapes are captured: this process owns all terminal rendering.
    child.extend(("--overview", "--json", "--refresh", "--no-color"))
    return child


def fetch_watch_snapshot(child_argv: list[str]) -> dict[str, Any]:
    """Run one fresh scout pass and return its machine-readable snapshot."""
    script_path = str(Path(__file__).resolve())
    command = [sys.executable, script_path, *child_argv]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        excerpt = completed.stdout[:500].strip()
        raise RuntimeError(f"watch refresh did not return JSON: {excerpt or exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("watch refresh returned a malformed JSON snapshot")
    if not isinstance(payload.get("markets"), list) or not isinstance(payload.get("event_overview"), list):
        raise RuntimeError("watch refresh JSON is missing markets or event_overview")
    return payload


def _watch_event_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index parent-event overview records by their stable Kalshi event ticker."""
    indexed: dict[str, dict[str, Any]] = {}
    for event in snapshot.get("event_overview", []):
        if not isinstance(event, dict):
            continue
        ticker = event.get("event_ticker")
        if isinstance(ticker, str) and ticker and ticker != "(no event ticker)":
            indexed[ticker] = event
    return indexed


def _watch_records_for_event(snapshot: dict[str, Any], event_ticker: str) -> list[dict[str, Any]]:
    """Return normalized child-contract records belonging to one parent event."""
    return [
        record
        for record in snapshot.get("markets", [])
        if isinstance(record, dict) and record.get("event_ticker") == event_ticker
    ]


def format_overview_email(event: dict[str, Any], detected_at: datetime, local_tz: ZoneInfo) -> str:
    """Build a plain-text event overview suitable for a notification email."""
    event_ticker = str(event.get("event_ticker") or "(no event ticker)")
    title = str(event.get("title") or "Untitled mention event")
    description = event.get("description")
    category = event.get("category")
    event_times = event.get("event_times_local") or []
    close_times = event.get("close_times_local") or []
    sources = ", ".join(str(value) for value in (event.get("event_time_sources") or []))
    event_text = str(event_times[0]) if event_times else "unknown event date"
    close_text = (
        str(close_times[0])
        if len(close_times) == 1
        else (f"{close_times[0]} → {close_times[-1]}" if close_times else "unknown close time")
    )
    statuses = ", ".join(str(value) for value in (event.get("statuses") or ["unknown"]))
    market_url = kalshi_event_url(event)

    lines = [
        "NEW KALSHI MENTION MARKET",
        "",
        f"Ticker: {event_ticker}",
        f"Title: {title}",
    ]
    if market_url:
        lines.append(f"Kalshi market: {market_url}")
    if description:
        lines.append(f"Description: {description}")
    if category:
        lines.append(f"Category: {category}")
    lines.extend(
        [
            f"Event: {event_text}",
            f"Event date source: {sources or 'unknown'}",
            f"Trading close: {close_text}",
            f"Status: {statuses}",
            f"Contracts: {event.get('contract_count', 0)}",
            f"Detected: {format_local_time(detected_at, local_tz)}",
            "",
            "This alert is generated by kalshi_mention_scout --watch-new.",
        ]
    )
    return "\n".join(lines)


def load_google_password(password_file: Path) -> str:
    """Source a zsh credential file and return its GOOGLE_PASSWORD value.

    The file is intentionally sourced rather than parsed as JSON or dotenv so
    either ``GOOGLE_PASSWORD=...`` or ``export GOOGLE_PASSWORD=...`` works.
    It is never printed, cached, or placed in the scout's own environment.
    """
    path = password_file.expanduser()
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Google password file is missing: {path}. "
            "Create it with GOOGLE_PASSWORD='your Gmail app password' and chmod 600 it."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot read Google password file {path}: {exc}") from exc

    if not path.is_file():
        raise RuntimeError(f"Google password path is not a regular file: {path}")
    if stat.st_mode & 0o077:
        raise RuntimeError(
            f"Google password file permissions are too broad: {path} "
            "(run: chmod 600 ~/.config/.google-password)"
        )

    # zsh is preferred because it matches the user's shell; -f skips startup
    # files. A POSIX sh fallback supports ordinary GOOGLE_PASSWORD=... files on
    # hosts that do not have zsh installed.
    commands = [
        [
            "zsh",
            "-f",
            "-c",
            'source "$1" >/dev/null; print -rn -- "${GOOGLE_PASSWORD-}"',
            "kalshi-google-password-loader",
            str(path),
        ],
        [
            "/bin/sh",
            "-c",
            '. "$1" >/dev/null; printf "%s" "${GOOGLE_PASSWORD-}"',
            "kalshi-google-password-loader",
            str(path),
        ],
    ]
    completed: subprocess.CompletedProcess[str] | None = None
    missing_shells = 0
    for command in commands:
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            break
        except FileNotFoundError:
            missing_shells += 1
        except OSError as exc:
            raise RuntimeError(f"Could not source Google password file {path}: {exc}") from exc

    if completed is None:
        raise RuntimeError("Neither zsh nor /bin/sh was available to source ~/.config/.google-password")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        raise RuntimeError(f"Could not source Google password file {path}: {detail[:600]}")

    password = completed.stdout
    if not password:
        raise RuntimeError(
            f"GOOGLE_PASSWORD was not set by {path}. "
            "Set GOOGLE_PASSWORD='your Gmail app password' in that file."
        )
    return password


def run_swaks_email(
    *,
    recipient: str,
    sender: str,
    smtp_server: str,
    auth_user: str,
    password: str,
    subject: str,
    body: str,
) -> None:
    """Send one plain-text Gmail SMTP message using the user's swaks setup."""
    command = [
        "swaks",
        "--to", recipient,
        "--from", sender,
        "--server", smtp_server,
        "--auth", "LOGIN",
        "--auth-user", auth_user,
        "--auth-password", password,
        "--tls",
        "--header", f"Subject: {subject}",
        "--body", body,
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("swaks was not found in PATH; install it before using email alerts") from exc
    except OSError as exc:
        raise RuntimeError(f"could not start swaks: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        raise RuntimeError(f"swaks failed: {detail[:600]}")


def verify_email_configuration(args: argparse.Namespace) -> str:
    """Fail fast and return the Gmail app password for this process."""
    return load_google_password(args.google_password_file)


def send_new_market_email(
    event: dict[str, Any],
    detected_at: datetime,
    local_tz: ZoneInfo,
    recipient: str,
    sender: str,
    smtp_server: str,
    auth_user: str,
    password: str,
    verbose: bool,
) -> None:
    """Send one parent-event overview through the configured swaks/Gmail setup."""
    ticker = str(event.get("event_ticker") or "new mention market")
    run_swaks_email(
        recipient=recipient,
        sender=sender,
        smtp_server=smtp_server,
        auth_user=auth_user,
        password=password,
        subject=f"[Kalshi] NEW mention market: {ticker}",
        body=format_overview_email(event, detected_at, local_tz),
    )
    if verbose:
        print(f"email sent for {ticker} to {recipient}", file=sys.stderr, flush=True)


def send_test_email(args: argparse.Namespace) -> int:
    """Send a standalone SMTP test and exit."""
    password = verify_email_configuration(args)
    now = datetime.now(timezone.utc)
    try:
        local_tz = ZoneInfo(args.timezone)
    except Exception as exc:
        raise SystemExit(f"Invalid --timezone {args.timezone!r}: {exc}") from exc

    run_swaks_email(
        recipient=args.email_to,
        sender=args.email_from,
        smtp_server=args.smtp_server,
        auth_user=args.smtp_auth_user,
        password=password,
        subject="[Kalshi] mention scout SMTP test",
        body=(
            "Kalshi mention-market scout email test.\n\n"
            f"Sent: {format_local_time(now, local_tz)}\n"
            "Sample Kalshi market link:\n"
            "https://kalshi.com/markets/kxearningsmentionccl/what-will-carnival-cruise-say-during-their-next-earnings-call/kxearningsmentionccl-26jun23\n\n"
            "This confirms --email-new can use ~/.config/.google-password and swaks."
        ),
    )
    print(f"test email sent to {args.email_to}", flush=True)
    return 0


def record_is_initialized(record: dict[str, Any]) -> bool:
    """Return whether a normalized record is not yet tradeable/initialized."""
    values = (record.get("scan_status"), record.get("api_status"))
    normalized = {str(value).strip().lower() for value in values if value not in (None, "")}
    return bool(normalized & {"unopened", "initialized"})


def write_initialized_queue_job(
    queue_dir: Path,
    event: dict[str, Any],
    records: list[dict[str, Any]],
    detected_at: datetime,
    api_base_url: str,
) -> Path | None:
    """Atomically create one durable opener-watcher job for an initialized event.

    The job is intentionally event-scoped.  A mention event normally contains
    several child word contracts that transition together, so one file lets the
    opener watcher poll all of them in a single event request. Existing files
    are left untouched: the consumer stores its progress in the same job file.
    """
    initialized = [record for record in records if record_is_initialized(record)]
    if not initialized:
        return None

    event_ticker = str(event.get("event_ticker") or "").strip()
    if not event_ticker:
        return None
    pending_dir = queue_dir.expanduser() / "pending"
    job_path = pending_dir / f"{event_ticker}.json"
    if job_path.exists():
        return job_path

    all_tickers = sorted({str(record.get("ticker")) for record in records if record.get("ticker")})
    initialized_tickers = sorted({str(record.get("ticker")) for record in initialized if record.get("ticker")})
    if not initialized_tickers:
        return None

    payload = {
        "queue_format_version": QUEUE_FORMAT_VERSION,
        "state": "pending",
        "created_at_utc": iso_utc(detected_at),
        "api_base_url": canonical_base_url(api_base_url),
        "event_ticker": event_ticker,
        "event": event,
        "market_tickers": all_tickers,
        "initially_initialized_tickers": initialized_tickers,
        "opened_alerted_tickers": [],
        "last_seen_statuses": {},
    }
    write_cache_atomic(job_path, payload)
    return job_path


def render_watch_new_event(
    event: dict[str, Any],
    records: list[dict[str, Any]],
    colors: bool,
    sort_by: str,
    detected_at: datetime,
    local_tz: ZoneInfo,
) -> None:
    """Render an unmistakable new-parent-market notice and complete details."""
    border = "=" * 78
    print()
    print(color(border, "yellow", colors))
    print(color("*** NEW MARKET CREATED ***", "bold", colors))
    print(f"detected: {format_local_time(detected_at, local_tz)}")
    print(color(border, "yellow", colors))
    print()
    render_overview([event], colors)
    print(color("all contracts / current quotes / available rules:", "bold", colors))
    if records:
        render_grouped(records, colors, True, sort_by)
    else:
        # This should be rare (a transient API inconsistency), but preserve the
        # parent event signal rather than hiding it.
        print("  No child contracts were included in this refresh snapshot.")
        print()


def watch_new_events(args: argparse.Namespace, original_argv: list[str]) -> int:
    """Print an overview baseline, then announce newly discovered event tickers.

    A "new market" in this mode is a new *parent Kalshi event ticker*.  This
    avoids false alarms when an already-known event's quote or status changes.
    The initial inventory is a baseline: it is displayed but never announced as
    newly created.  Ctrl-C exits cleanly.
    """
    if args.flat:
        raise SystemExit("--watch-new prints an overview and cannot be combined with --flat")
    if args.json:
        raise SystemExit("--watch-new owns terminal output and cannot be combined with --json")
    if args.poll_seconds < 30:
        raise SystemExit("--poll-seconds must be at least 30 seconds")

    try:
        local_tz = ZoneInfo(args.timezone)
    except Exception as exc:
        raise SystemExit(f"Invalid --timezone {args.timezone!r}: {exc}") from exc

    if args.email_new:
        try:
            # Fail before the baseline scan/watch loop if the credential file is
            # missing, unsafe, or does not define GOOGLE_PASSWORD.
            args._google_password = verify_email_configuration(args)
        except RuntimeError as exc:
            raise SystemExit(f"email configuration error: {exc}") from exc

    child_argv = _watch_child_arguments(original_argv)
    colors = not args.no_color and sys.stdout.isatty()
    effective_poll = args.poll_seconds

    try:
        snapshot = fetch_watch_snapshot(child_argv)
    except RuntimeError as exc:
        print(color(f"error: initial watch refresh failed: {exc}", "red", colors), file=sys.stderr)
        return 2

    event_map = _watch_event_map(snapshot)
    sort_by = str((snapshot.get("summary") or {}).get("sort") or "event")
    generated_at = parse_iso(snapshot.get("generated_at_utc")) or datetime.now(timezone.utc)
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    status_filter = snapshot.get("status_filter") or "upcoming"

    print(color("Kalshi mention-market scout watch", "bold", colors))
    print("baseline: current overview shown below; existing events do not trigger an alert")
    print(
        f"watching: {len(event_map)} event(s) / {summary.get('matching_contract_count', 0)} contract(s) "
        f"| status: {status_filter} | refresh: every {effective_poll:g}s | Ctrl-C to stop"
    )
    print(f"started: {format_local_time(generated_at, local_tz)}")
    print()
    render_overview(list(event_map.values()), colors)

    queue_dir = args.queue_dir.expanduser()
    initial_queued = 0
    if args.queue_initialized:
        for ticker, event in event_map.items():
            try:
                job_path = write_initialized_queue_job(
                    queue_dir,
                    event,
                    _watch_records_for_event(snapshot, ticker),
                    generated_at,
                    str(snapshot.get("api_base_url") or ""),
                )
            except OSError as exc:
                print(color(f"queue write failed for {ticker}: {exc}", "red", colors), file=sys.stderr, flush=True)
                continue
            if job_path is not None:
                initial_queued += 1
        print(
            f"initialized queue checked: {initial_queued} candidate event(s) in {queue_dir / 'pending'} "
            "(existing files are left in place)",
            flush=True,
        )

    print(f"Watching for new parent markets. Next refresh in {effective_poll:g} seconds.", flush=True)

    known_event_tickers = set(event_map)
    while True:
        try:
            time.sleep(effective_poll)
        except KeyboardInterrupt:
            print("\nWatch stopped.")
            return 0

        try:
            snapshot = fetch_watch_snapshot(child_argv)
        except RuntimeError as exc:
            stamp = format_local_time(datetime.now(timezone.utc), local_tz)
            print(color(f"[{stamp}] refresh failed: {exc}", "red", colors), file=sys.stderr, flush=True)
            continue

        current_events = _watch_event_map(snapshot)
        new_tickers = sorted(
            set(current_events) - known_event_tickers,
            key=lambda ticker: (
                parse_iso(current_events[ticker].get("first_event_time_utc"))
                or parse_iso(current_events[ticker].get("first_close_time_utc"))
                or datetime.max.replace(tzinfo=timezone.utc),
                ticker,
            ),
        )
        current_sort = str((snapshot.get("summary") or {}).get("sort") or "event")
        detected_at = parse_iso(snapshot.get("generated_at_utc")) or datetime.now(timezone.utc)

        if args.queue_initialized:
            queued_now = 0
            for ticker, event in current_events.items():
                try:
                    job_path = write_initialized_queue_job(
                        queue_dir,
                        event,
                        _watch_records_for_event(snapshot, ticker),
                        detected_at,
                        str(snapshot.get("api_base_url") or ""),
                    )
                except OSError as exc:
                    print(color(f"queue write failed for {ticker}: {exc}", "red", colors), file=sys.stderr, flush=True)
                    continue
                if job_path is not None:
                    queued_now += 1
            if args.verbose and queued_now:
                print(f"initialized queue checked for {queued_now} event(s)", flush=True)

        if new_tickers:
            for ticker in new_tickers:
                event = current_events[ticker]
                render_watch_new_event(
                    event,
                    _watch_records_for_event(snapshot, ticker),
                    colors,
                    current_sort,
                    detected_at,
                    local_tz,
                )
                if args.email_new:
                    try:
                        send_new_market_email(
                            event,
                            detected_at,
                            local_tz,
                            args.email_to,
                            args.email_from,
                            args.smtp_server,
                            args.smtp_auth_user,
                            args._google_password,
                            args.verbose,
                        )
                    except RuntimeError as exc:
                        print(
                            color(f"email alert failed for {ticker}: {exc}", "red", colors),
                            file=sys.stderr,
                            flush=True,
                        )
        elif args.verbose:
            print(
                f"[{format_local_time(detected_at, local_tz)}] no new parent markets "
                f"({len(current_events)} currently tracked)",
                flush=True,
            )

        # Do not forget an event just because it temporarily disappears from a
        # later snapshot; a reappearance should not generate a false NEW alert.
        known_event_tickers.update(current_events)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find active/upcoming Kalshi mention-style markets with a compact disk cache.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=7, help="Calendar days for --window event; 24-hour days for --window closing")
    parser.add_argument(
        "--window",
        choices=("event", "all", "closing"),
        default="event",
        help=(
            "event (default) = event dates in the next calendar days; all = every active/upcoming mention; "
            "closing = only contracts whose trading close falls in the --days horizon"
        ),
    )
    parser.add_argument(
        "--sort", choices=("auto", "event", "close"), default="auto",
        help="auto = event date for --window event, trading close otherwise",
    )
    parser.add_argument("--env", choices=sorted(BASE_URLS), default="prod", help="Kalshi API environment")
    parser.add_argument(
        "--status",
        choices=("open", "unopened", "paused", "both", "upcoming"),
        default="both",
        help=(
            "open = active only; unopened = not yet tradable; paused = inactive only; "
            "both = open + unopened (default); upcoming = open + unopened + paused/inactive"
        ),
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Also include paused/inactive markets with the selected --status (same as --status upcoming when status is both).",
    )
    parser.add_argument("--base-url", help="Override the API base URL entirely")
    parser.add_argument("--timezone", default="America/New_York", help="IANA timezone for displayed times and date-only ticker fallback")
    parser.add_argument("--contains", help="Keep only markets whose metadata contains this text")
    parser.add_argument("--flat", action="store_true", help="Do not group contracts under their Kalshi event")
    parser.add_argument("--overview", action="store_true", help="Show one parent event title/description block and hide individual word/outcome contracts")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON to stdout")
    parser.add_argument("--show-rules", action="store_true", help="Include available rules text in human output")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal color")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request HTTP timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Retries for transient failures and rate limits")
    parser.add_argument(
        "--full-cache",
        action="store_true",
        help=(
            "Use the old complete /markets scan and save every live contract. "
            "This is much larger; default mode persists mention contracts only."
        ),
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        help="Override the local JSON cache file. Defaults to separate hidden mention/full cache files in the current directory.",
    )
    parser.add_argument("--cache-ttl", type=float, default=DEFAULT_CACHE_TTL_SECONDS, metavar="SECONDS", help="Reuse the local snapshot for at most this many seconds; 0 always refreshes")
    parser.add_argument("--refresh", action="store_true", help="Ignore any usable cache and fetch a new snapshot")
    parser.add_argument("--no-cache", action="store_true", help="Do not read or write the local cache")
    parser.add_argument(
        "--watch-new",
        action="store_true",
        help=(
            "Print an initial event overview, then refresh repeatedly and loudly show full details "
            "for each newly discovered parent mention event. Defaults to all upcoming statuses/window "
            "unless --status or --window is explicitly supplied."
        ),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=300.0,
        metavar="SECONDS",
        help="Refresh interval for --watch-new (default: 5 minutes; minimum: 30 seconds)",
    )
    parser.add_argument(
        "--queue-initialized",
        action="store_true",
        help=(
            "With --watch-new, write one durable JSON job under --queue-dir/pending for every "
            "mention event that contains initialized/unopened contracts. A separate opener watcher "
            "can poll only those jobs for the open transition. Existing queue jobs are never overwritten."
        ),
    )
    parser.add_argument(
        "--queue-dir",
        type=Path,
        default=Path(DEFAULT_OPEN_QUEUE_DIR),
        help="Directory used by --queue-initialized for durable opener-watcher job files",
    )
    parser.add_argument(
        "--email-new",
        action="store_true",
        help=(
            "With --watch-new, email one concise parent-event overview through swaks "
            "for every newly discovered market. Fails fast unless ~/.config/.google-password "
            "defines GOOGLE_PASSWORD."
        ),
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Source the Google password file, send one SMTP test email, then exit",
    )
    parser.add_argument(
        "--google-password-file",
        type=Path,
        default=DEFAULT_GOOGLE_PASSWORD_FILE,
        help="zsh file sourced for GOOGLE_PASSWORD by --email-new and --test-email",
    )
    parser.add_argument(
        "--email-to",
        default="ryan.grimm@gmail.com",
        help="Notification recipient used by --email-new",
    )
    parser.add_argument(
        "--email-from",
        default="ryan.grimm@gmail.com",
        help="Envelope/header sender used by --email-new",
    )
    parser.add_argument(
        "--smtp-server",
        default="smtp.gmail.com:587",
        help="swaks SMTP server used by --email-new",
    )
    parser.add_argument(
        "--smtp-auth-user",
        default="ryan.grimm@gmail.com",
        help="swaks SMTP auth user used by --email-new",
    )
    parser.add_argument("--verbose", action="store_true", help="Show pagination, cache, and retry diagnostics on stderr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main() -> int:
    original_argv = sys.argv[1:]
    args = build_parser().parse_args()
    if args.test_email:
        if args.watch_new or args.email_new or args.queue_initialized:
            raise SystemExit("--test-email sends once and cannot be combined with --watch-new, --email-new, or --queue-initialized")
        try:
            return send_test_email(args)
        except RuntimeError as exc:
            raise SystemExit(f"email test failed: {exc}") from exc
    if args.email_new and not args.watch_new:
        raise SystemExit("--email-new is only valid together with --watch-new")
    if args.queue_initialized and not args.watch_new:
        raise SystemExit("--queue-initialized is only valid together with --watch-new")
    if args.watch_new:
        return watch_new_events(args, original_argv)
    if args.days <= 0:
        raise SystemExit("--days must be greater than zero")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero")
    if args.retries < 0:
        raise SystemExit("--retries cannot be negative")
    if args.cache_ttl < 0:
        raise SystemExit("--cache-ttl cannot be negative")
    if args.overview and args.flat:
        raise SystemExit("--overview is already event-grouped and cannot be combined with --flat")

    try:
        local_tz = ZoneInfo(args.timezone)
    except Exception as exc:
        raise SystemExit(f"Invalid --timezone {args.timezone!r}: {exc}") from exc

    now = datetime.now(timezone.utc)
    close_window_end = now + timedelta(days=args.days)
    local_today = now.astimezone(local_tz).date()
    event_last_day = local_today + timedelta(days=args.days - 1)
    base_url = canonical_base_url(args.base_url or BASE_URLS[args.env])
    status_presets: dict[str, tuple[str, ...]] = {
        "open": ("open",),
        "unopened": ("unopened",),
        "paused": ("paused",),
        "both": ("open", "unopened"),
        "upcoming": ("open", "unopened", "paused"),
    }
    statuses = status_presets[args.status]
    if args.include_inactive and "paused" not in statuses:
        statuses = (*statuses, "paused")
    status_label = "+".join(statuses)
    cache_mode = "full" if args.full_cache else "mention"
    cache_path = (args.cache_file.expanduser() if args.cache_file else cache_file_default(args.full_cache))
    colors = not args.no_color and sys.stdout.isatty() and not args.json

    cached_markets: list[dict[str, Any]] | None = None
    active_cache_payload: dict[str, Any] | None = None
    cache_used = False
    cache_age: float | None = None
    cache_fetched_at: str | None = None
    source_event_count: int | None = None
    source_paused_market_count: int | None = None
    cache_note = "cache disabled" if args.no_cache else "no usable cache"

    if not args.no_cache and not args.refresh:
        cache = load_cache(cache_path, args.verbose)
        if cache is not None:
            usable, reason, age = cache_usable(cache, base_url, statuses, now, args.cache_ttl, cache_mode)
            if usable:
                cached_markets = [market for market in cache["markets"] if isinstance(market, dict)]
                active_cache_payload = cache
                cache_used = True
                cache_age = age
                cache_fetched_at = str(cache.get("fetched_at_utc"))
                source_event_count = cache.get("source_event_count") if isinstance(cache.get("source_event_count"), int) else None
                source_paused_market_count = cache.get("source_paused_market_count") if isinstance(cache.get("source_paused_market_count"), int) else None
                cache_note = f"cache hit ({age:.0f}s old; {len(cached_markets)} {cache_mode} markets)"
                if args.verbose:
                    print(f"cache hit: {cache_path} ({len(cached_markets)} {cache_mode} markets)", file=sys.stderr)
            else:
                cache_note = f"cache refresh: {reason}"
                if args.verbose:
                    print(f"cache miss: {cache_path}: {reason}", file=sys.stderr)
        elif args.verbose:
            print(f"cache miss: {cache_path} does not exist yet", file=sys.stderr)
    elif args.refresh:
        cache_note = "forced refresh"

    if cached_markets is None:
        try:
            if args.full_cache:
                cached_markets = list(iter_markets(base_url, args.timeout, args.retries, args.verbose, statuses))
                discovered_event_details: dict[str, dict[str, Any]] = {}
            else:
                # /events supports only open/unopened status filters. Paused
                # (raw lifecycle: inactive) contracts are collected separately
                # via /markets?status=paused when requested.
                event_statuses = tuple(status for status in statuses if status in ("open", "unopened"))
                event_markets: list[dict[str, Any]] = []
                discovered_event_details = {}
                source_event_count = 0
                if event_statuses:
                    event_markets, discovered_event_details, source_event_count = scan_mention_events(
                        base_url, args.timeout, args.retries, args.verbose, event_statuses
                    )

                paused_markets: list[dict[str, Any]] = []
                source_paused_market_count = 0
                if "paused" in statuses:
                    paused_markets, source_paused_market_count = scan_paused_mention_markets(
                        base_url, args.timeout, args.retries, args.verbose
                    )

                cached_markets = merge_market_lists(event_markets, paused_markets)
        except RuntimeError as exc:
            print(color(f"error: {exc}", "red", colors), file=sys.stderr)
            return 2

        payload = build_cache_payload(
            base_url,
            statuses,
            cached_markets,
            cache_mode,
            event_details=discovered_event_details,
            source_event_count=source_event_count,
            source_paused_market_count=source_paused_market_count,
        )
        active_cache_payload = payload
        cache_fetched_at = str(payload["fetched_at_utc"])
        if args.no_cache:
            cache_note = f"downloaded ({len(cached_markets)} {cache_mode} markets; cache disabled)"
        else:
            try:
                write_cache_atomic(cache_path, payload)
                cache_note = f"downloaded and cached ({len(cached_markets)} {cache_mode} markets)"
            except OSError as exc:
                cache_note = f"downloaded; cache write failed: {exc}"
                print(f"warning: could not write cache {cache_path}: {exc}", file=sys.stderr)

    # Full mode starts with every market; compact mode already consists only of
    # mention candidates. Keep the final predicate in both modes for backwards
    # compatible --contains/classification behavior and safety against stale data.
    mention_markets = [
        market
        for market in cached_markets
        if cached_market_status(market) in statuses
        and is_mention_market(market)
        and contains_filter(market, args.contains)
    ]

    raw_event_details = active_cache_payload.get("event_details", {}) if isinstance(active_cache_payload, dict) else {}
    event_details: dict[str, dict[str, Any]] = dict(raw_event_details) if isinstance(raw_event_details, dict) else {}
    wanted_event_tickers = sorted({ticker for market in mention_markets if (ticker := market_event_ticker(market))})
    missing_event_tickers = [
        ticker for ticker in wanted_event_tickers
        if not isinstance(event_details.get(ticker), dict) or not isinstance(event_details[ticker].get("event"), dict)
    ]
    event_metadata_fetched = 0
    if missing_event_tickers:
        try:
            fetched_events = fetch_event_metadata(base_url, missing_event_tickers, args.timeout, args.retries, args.verbose)
        except RuntimeError as exc:
            print(f"warning: could not fetch event schedule metadata: {exc}; using ticker-date fallbacks", file=sys.stderr)
        else:
            fetched_at = iso_utc(datetime.now(timezone.utc))
            for event_ticker, event in fetched_events.items():
                event_details[event_ticker] = {"fetched_at_utc": fetched_at, "event": compact_event_metadata(event)}
            event_metadata_fetched = len(fetched_events)
            if isinstance(active_cache_payload, dict) and not args.no_cache and fetched_events:
                active_cache_payload["event_details"] = event_details
                try:
                    write_cache_atomic(cache_path, active_cache_payload)
                except OSError as exc:
                    print(f"warning: could not update event cache {cache_path}: {exc}", file=sys.stderr)
    if event_metadata_fetched:
        cache_note += f"; fetched {event_metadata_fetched} parent event record(s)"

    def event_for(market: dict[str, Any]) -> dict[str, Any] | None:
        detail = event_details.get(str(market_event_ticker(market) or ""), {})
        event = detail.get("event") if isinstance(detail, dict) else None
        return event if isinstance(event, dict) else None

    def on_event_day(market: dict[str, Any]) -> bool:
        when, _source = event_schedule_for_market(market, event_for(market), local_tz)
        if when is None:
            return False
        event_day = when.astimezone(local_tz).date()
        return local_today <= event_day <= event_last_day

    if args.window == "all":
        selected = mention_markets
    elif args.window == "closing":
        selected = [market for market in mention_markets if closes_in_window(market, now, close_window_end)]
    else:
        selected = [market for market in mention_markets if on_event_day(market)]

    records = [market_record(market, local_tz, event_for(market)) for market in selected]
    effective_sort = args.sort if args.sort != "auto" else ("event" if args.window == "event" else "close")
    records.sort(key=lambda record: record_sort_key(record, effective_sort))
    overview_data = event_overviews(records, event_details, effective_sort) if args.overview else []

    inventory_market_count = len(cached_markets)
    inventory_mention_count = len(mention_markets)
    cache_metadata = {
        "enabled": not args.no_cache,
        "used": cache_used,
        "mode": cache_mode,
        "file": str(cache_path),
        "ttl_seconds": args.cache_ttl,
        "fetched_at_utc": cache_fetched_at,
        "age_seconds": round(cache_age, 3) if cache_age is not None else None,
        "source_event_count": source_event_count,
        "note": cache_note,
    }
    summary = {
        "scope": args.window,
        "sort": effective_sort,
        "cache_mode": cache_mode,
        "event_window_start_local_date": local_today.isoformat(),
        "event_window_end_local_date": event_last_day.isoformat(),
        "close_window_start_utc": iso_utc(now),
        "close_window_end_utc": iso_utc(close_window_end),
        "matching_contract_count": len(records),
        "matching_event_count": event_count(selected),
        "all_live_mention_contract_count": inventory_mention_count,
        "all_live_mention_event_count": event_count(mention_markets),
        "cached_market_count": inventory_market_count,
        "source_event_count": source_event_count,
        "source_paused_market_count": source_paused_market_count,
    }

    if args.json:
        print(json.dumps({
            "generated_at_utc": iso_utc(now),
            "timezone": args.timezone,
            "api_base_url": base_url,
            "status_filter": args.status,
            "cache": cache_metadata,
            "summary": summary,
            "markets": records,
            "event_overview": overview_data if args.overview else None,
        }, indent=2, sort_keys=False))
        return 0

    print(color("Kalshi mention-market scout", "bold", colors))
    print(f"view: {'event overview (titles/descriptions only)' if args.overview else ('flat contracts' if args.flat else 'detailed grouped contracts')}")
    print(f"sort: {'Kalshi event date/time' if effective_sort == 'event' else 'trading close time'}, soonest → latest")
    timezone_label = now.astimezone(local_tz).tzname() or args.timezone
    if args.window == "event":
        print("scope: event dates in the next calendar window (includes today; event date sources are shown per result)")
        print(f"event days ({args.timezone}, currently {timezone_label}): {local_today:%a, %b %-d, %Y} → {event_last_day:%a, %b %-d, %Y}")
    elif args.window == "closing":
        print(f"scope: contracts trading-close in next {args.days:g} day(s), not a guaranteed event/speech time")
        print(f"close window ({args.timezone}, currently {timezone_label}): {format_local_time(now, local_tz)} → {format_local_time(close_window_end, local_tz)}")
    else:
        print("scope: all mention-style contracts in the selected non-closed lifecycle statuses (no event-date or close-time horizon)")
    print(f"source: {base_url}  |  status: {status_label}  |  matches: {color(str(len(records)), 'green' if records else 'yellow', colors)} contracts / {event_count(selected)} events")
    if args.full_cache:
        print(f"inventory: {inventory_mention_count} mention contracts / {event_count(mention_markets)} events across {inventory_market_count} cached live markets (FULL cache mode)")
    else:
        discovery_parts: list[str] = []
        if source_event_count is not None:
            discovery_parts.append(f"{source_event_count} open/unopened event records")
        if source_paused_market_count is not None:
            discovery_parts.append(f"{source_paused_market_count} paused market records")
        inspected = f"; discovered from {' + '.join(discovery_parts)}" if discovery_parts else ""
        print(f"inventory: {inventory_mention_count} mention contracts / {event_count(mention_markets)} events in compact mention-only cache{inspected}")
    print(f"data: {cache_note}  |  cache file: {cache_path}")
    if args.contains:
        print(f"contains: {args.contains!r}")
    print()

    if not records:
        if args.window == "event":
            message = "No mention events have a Kalshi event date in this calendar window. Try --window all to inspect every live mention event."
        elif args.window == "closing":
            message = "No mention-style contracts close within this horizon. Try --window all to see every live mention event."
        else:
            message = "No mention-style contracts matched the selected lifecycle statuses."
        print(color(message, "yellow", colors))
        return 0

    if args.overview:
        render_overview(overview_data, colors)
    elif args.flat:
        render_flat(records, colors, args.show_rules)
    else:
        render_grouped(records, colors, args.show_rules, effective_sort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
