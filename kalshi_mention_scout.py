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

Changes in v16.2 / MS-0014:
  * Adds --audit-calendar-matches one-shot to validate calendar-matches.json
    with the same loader rules as watch/calendar preflight. On failure, exits
    non-zero and (by default) emails a FAIL report with subject
    ``[Kalshi] FAIL | calendar-matches audit``; opt out with --no-email-on-fail.
  * Adds --add-calendar-match --match … with optional --time / --duration-minutes
    / --dry-run for safe atomic create/update of phrases (plain string or object
    form), preserving existing entries and default_time.

Changes in v16.1 / MS-0013:
  * Adds repeatable --invite-email for --calendar-add-new. Each newly created
    Google Calendar event can include those addresses as attendees with
    sendUpdates=all so Google notifies guests. Scout SMTP is unchanged (no
    fan-out to invitees).

Changes in v16:
  * Adds a clickable Kalshi event-page URL to new-market notification emails.
    The URL uses any explicit Kalshi URL field when present; otherwise it is
    built from the parent series/event ticker and a safe title slug.
  * MS-0010: optional --calendar-add-new for --watch-new creates Google Calendar
    events when a new parent event matches owner phrases in
    ~/.config/mention-scout/calendar-matches.json. Includes --calendar-auth,
    local dedupe state, and calendar error emails via the existing swaks path.
  * MS-0011: calendar-matches.json may set default_time and per-phrase time /
    duration_minutes so date-only Kalshi schedules become timed local events.

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
import socket
import sys
import time
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION = "16.2.0"
CACHE_FORMAT_VERSION = 5
DEFAULT_MENTION_CACHE_FILE = ".kalshi_mention_scout_mentions_cache.json"
DEFAULT_FULL_CACHE_FILE = ".kalshi_mention_scout_full_cache.json"
DEFAULT_CACHE_TTL_SECONDS = 300.0
DEFAULT_OPEN_QUEUE_DIR = "mention_open_queue"
QUEUE_FORMAT_VERSION = 1
DEFAULT_GOOGLE_PASSWORD_FILE = Path("~/.config/.google-password")
DEFAULT_MENTION_SCOUT_CONFIG_DIR = Path("~/.config/mention-scout")
DEFAULT_CALENDAR_MATCHES_FILE = DEFAULT_MENTION_SCOUT_CONFIG_DIR / "calendar-matches.json"
DEFAULT_CALENDAR_CLIENT_SECRET_FILE = DEFAULT_MENTION_SCOUT_CONFIG_DIR / "client_secret.json"
DEFAULT_CALENDAR_TOKEN_FILE = DEFAULT_MENTION_SCOUT_CONFIG_DIR / "token.json"
DEFAULT_CALENDAR_STATE_FILE = DEFAULT_MENTION_SCOUT_CONFIG_DIR / "calendar-added.json"
DEFAULT_CALENDAR_ID = "primary"
DEFAULT_CALENDAR_DURATION_MINUTES = 60
CALENDAR_MATCH_FILE_VERSION = 1
CALENDAR_STATE_FILE_VERSION = 1
CALENDAR_OAUTH_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
CALENDAR_ERROR_BODY_LIMIT = 1200
MAX_INVITE_EMAILS = 20

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

# ---------------------------------------------------------------------------
# Mention type taxonomy (MS-0006)
# Deterministic, ordered rules. First match wins. Extend this table when the
# owner requests a new family; keep offline unit tests in lockstep.
# Priority: face-the-nation → world-news-tonight → earnings → trump → say → other
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MentionType:
    """Stable machine id + human display label for one mention family."""

    id: str
    label: str


MENTION_TYPE_REGISTRY: tuple[MentionType, ...] = (
    MentionType("face-the-nation", "Face the Nation"),
    MentionType("world-news-tonight", "World News Tonight"),
    MentionType("earnings", "earnings"),
    MentionType("trump", "Trump"),
    MentionType("say", "say"),
    MentionType("other", "other"),
)
MENTION_TYPES: dict[str, MentionType] = {item.id: item for item in MENTION_TYPE_REGISTRY}
KNOWN_MENTION_TYPE_IDS: tuple[str, ...] = tuple(item.id for item in MENTION_TYPE_REGISTRY)

# CLI shortcuts accepted by --type (case-insensitive).
MENTION_TYPE_ALIASES: dict[str, str] = {
    "ftn": "face-the-nation",
    "wnt": "world-news-tonight",
    "world-news": "world-news-tonight",
}

# Ordered (type_id, ticker_regex, title_regex). ticker_regex matches the joined
# uppercased series/event/market tickers; title_regex matches title/description.
_TYPE_RULES: tuple[tuple[str, re.Pattern[str], re.Pattern[str] | None], ...] = (
    (
        "face-the-nation",
        re.compile(r"FTNMENTION|FACETHENATION|FACE[_]?THE[_]?NATION", re.IGNORECASE),
        re.compile(r"\bface\s+the\s+nation\b", re.IGNORECASE),
    ),
    (
        "world-news-tonight",
        re.compile(r"WORLDNEWSMENTION|WORLDNEWS", re.IGNORECASE),
        re.compile(r"\bworld\s+news\s+tonight\b", re.IGNORECASE),
    ),
    (
        "earnings",
        re.compile(r"EARNINGSMENTION|(?=.*\bEARNINGS?\b)(?=.*MENTION)", re.IGNORECASE),
        re.compile(
            r"\bearnings?\s+call\b|\bduring\s+their\s+next\s+earnings\b|\bnext\s+earnings\s+call\b",
            re.IGNORECASE,
        ),
    ),
    (
        "trump",
        re.compile(r"TRUMPMENTION|TRUMPSAY|\bTRUMP\b.*MENTION|MENTION.*\bTRUMP\b", re.IGNORECASE),
        re.compile(r"\btrump\b.*\b(?:mention|say|says|said)\b|\b(?:mention|say|says|said)\b.*\btrump\b", re.IGNORECASE),
    ),
    (
        "say",
        re.compile(r"\bSAY\b|(?<![A-Z])SAY(?![A-Z])|SAYMENTION|[A-Z0-9]*SAY[A-Z0-9]*", re.IGNORECASE),
        re.compile(
            r"\bwhat\s+(?:will|would|does|did)\b.{0,120}?\b(?:say|says|said)\b",
            re.IGNORECASE,
        ),
    ),
)


def mention_type_label(type_id: str | None) -> str:
    """Return the display label for a type id, defaulting to ``other``."""
    if not type_id:
        return MENTION_TYPES["other"].label
    found = MENTION_TYPES.get(str(type_id))
    return found.label if found is not None else MENTION_TYPES["other"].label


def classify_mention_type(
    *,
    series_ticker: Any = "",
    event_ticker: Any = "",
    title: Any = "",
    description: Any = "",
    sub_title: Any = "",
    category: Any = "",
    ticker: Any = "",
) -> MentionType:
    """Return the primary mention type using ordered deterministic rules."""
    ticker_blob = " ".join(
        str(part or "") for part in (series_ticker, event_ticker, ticker)
    ).upper()
    title_blob = " ".join(
        str(part or "") for part in (title, description, sub_title, category)
    )

    for type_id, ticker_re, title_re in _TYPE_RULES:
        if ticker_re.search(ticker_blob):
            return MENTION_TYPES[type_id]
        if title_re is not None and title_re.search(title_blob):
            return MENTION_TYPES[type_id]
    return MENTION_TYPES["other"]


def mention_type_for_event(event_like: dict[str, Any]) -> str:
    """Classify an overview/event-like mapping and return its type id."""
    if not isinstance(event_like, dict):
        return MENTION_TYPES["other"].id
    existing = event_like.get("mention_type")
    if isinstance(existing, str) and existing in MENTION_TYPES:
        return existing
    return classify_mention_type(
        series_ticker=event_like.get("series_ticker"),
        event_ticker=event_like.get("event_ticker"),
        title=event_like.get("title"),
        description=event_like.get("description"),
        sub_title=event_like.get("sub_title"),
        category=event_like.get("category"),
        ticker=event_like.get("ticker"),
    ).id


def mention_type_for_market(
    market: dict[str, Any],
    event: dict[str, Any] | None = None,
) -> str:
    """Classify a child market, preferring parent event fields when present."""
    parent = event if isinstance(event, dict) else {}
    return classify_mention_type(
        series_ticker=parent.get("series_ticker") or market.get("series_ticker"),
        event_ticker=(
            parent.get("event_ticker")
            or market.get("event_ticker")
            or market_event_ticker(market)
        ),
        title=parent.get("title") or market.get("title"),
        description=parent.get("description") or market.get("description"),
        sub_title=parent.get("sub_title") or market.get("subtitle") or market.get("yes_sub_title"),
        category=parent.get("category") or market.get("category"),
        ticker=market.get("ticker"),
    ).id


def format_new_market_email_subject(event_like: dict[str, Any]) -> str:
    """Build the lock-screen-friendly new-market email subject (MS-0006)."""
    ticker = str((event_like or {}).get("event_ticker") or "new mention market")
    type_id = mention_type_for_event(event_like or {})
    label = (event_like or {}).get("mention_type_label")
    if not isinstance(label, str) or not label.strip():
        label = mention_type_label(type_id)
    return f"[Kalshi] {label} | NEW: {ticker}"


def normalize_type_token(token: str) -> str:
    """Map one CLI type token (id or alias) to a canonical type id."""
    cleaned = str(token or "").strip().casefold().replace("_", "-")
    if not cleaned:
        raise ValueError("empty type token")
    if cleaned in MENTION_TYPE_ALIASES:
        return MENTION_TYPE_ALIASES[cleaned]
    for type_id in KNOWN_MENTION_TYPE_IDS:
        if type_id.casefold() == cleaned:
            return type_id
    raise ValueError(token.strip())


def parse_type_filter(raw: str | None) -> frozenset[str] | None:
    """Parse ``--type`` into a frozenset of ids, or None when unrestricted.

    Raises ``SystemExit`` with an actionable message on empty/invalid input.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        raise SystemExit(
            "--type requires at least one type id "
            f"(known: {', '.join(KNOWN_MENTION_TYPE_IDS)})"
        )
    tokens = [part.strip() for part in text.split(",") if part.strip()]
    if not tokens:
        raise SystemExit(
            "--type requires at least one type id "
            f"(known: {', '.join(KNOWN_MENTION_TYPE_IDS)})"
        )
    selected: set[str] = set()
    unknown: list[str] = []
    for token in tokens:
        try:
            selected.add(normalize_type_token(token))
        except ValueError:
            unknown.append(token)
    if unknown:
        alias_help = ", ".join(sorted(MENTION_TYPE_ALIASES))
        raise SystemExit(
            f"Unknown --type value(s): {', '.join(unknown)}. "
            f"Known: {', '.join(KNOWN_MENTION_TYPE_IDS)}. "
            f"Aliases: {alias_help}."
        )
    return frozenset(selected)


def event_matches_types(
    event_like: dict[str, Any],
    selected: frozenset[str] | None,
) -> bool:
    """Return whether an event passes an any-of type filter (None = all)."""
    if selected is None:
        return True
    return mention_type_for_event(event_like) in selected


def market_matches_types(
    market: dict[str, Any],
    selected: frozenset[str] | None,
    event: dict[str, Any] | None = None,
) -> bool:
    """Return whether a market's resolved type is in the selected any-of set."""
    if selected is None:
        return True
    return mention_type_for_market(market, event) in selected


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
        # ticker/title. Others are recognized from nested child product text
        # (ticker/title/subtitles — not settlement rules; see MS-0007).
        matches_event = event_qualifies_as_mention(event, nested_markets)
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
    """Full market text for --contains and human/rules display sources.

    Includes settlement rules so substring search can still find legal prose.
    Binary mention admission must NOT use this string (see
    mention_gate_text_for_market / MS-0007).
    """
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


def mention_gate_text_for_market(market: dict[str, Any]) -> str:
    """Product-facing market text for binary mention discovery membership.

    Excludes rules_primary / rules_secondary so settlement boilerplate cannot
    alone admit a market (MS-0007). Keep text_for_market for contains/display.
    """
    fields = (
        "ticker",
        "event_ticker",
        "title",
        "subtitle",
        "yes_sub_title",
        "no_sub_title",
    )
    return "\n".join(str(market.get(field, "")) for field in fields)


def is_mention_market(market: dict[str, Any]) -> bool:
    ticker_text = f"{market.get('ticker', '')} {market.get('event_ticker', '')}".upper()
    if "MENTION" in ticker_text:
        return True
    text = mention_gate_text_for_market(market)
    return bool(MENTION_RE.search(text) or SAY_EVENT_RE.search(text))


def event_qualifies_as_mention(
    event: dict[str, Any],
    nested_markets: list[dict[str, Any]] | None = None,
) -> bool:
    """Pure helper mirroring scan_mention_events admission boolean (no HTTP)."""
    children = nested_markets if nested_markets is not None else []
    return is_mention_event(event) or any(is_mention_market(item) for item in children)


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
    type_id = mention_type_for_market(market, event)
    return {
        "ticker": market.get("ticker"),
        "event_ticker": market_event_ticker(market),
        "api_status": market.get("status"),
        "scan_status": market.get("_scan_status"),
        "title": market.get("title") or market.get("subtitle") or market.get("yes_sub_title"),
        "subtitle": market.get("subtitle"),
        "yes_sub_title": market.get("yes_sub_title"),
        "no_sub_title": market.get("no_sub_title"),
        "mention_type": type_id,
        "mention_type_label": mention_type_label(type_id),
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
        series_ticker = event.get("series_ticker") if isinstance(event.get("series_ticker"), str) else None
        category = event.get("category") if isinstance(event.get("category"), str) else None
        type_info = classify_mention_type(
            series_ticker=series_ticker,
            event_ticker=event_ticker if event_ticker != "(no event ticker)" else event.get("event_ticker"),
            title=title,
            description=description or event.get("description"),
            sub_title=event.get("sub_title"),
            category=category,
        )
        output.append(
            {
                "event_ticker": event_ticker,
                "title": title or "Untitled mention event",
                "description": description or None,
                "category": category,
                "series_ticker": series_ticker,
                "mention_type": type_info.id,
                "mention_type_label": type_info.label,
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
        type_label = event.get("mention_type_label") or mention_type_label(
            event.get("mention_type") or mention_type_for_event(event)
        )
        print(f"  type: {color(str(type_label), 'blue', colors)}")
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
    # Parent-process-only flags (watch side effects / auth / SMTP / calendar).
    strip_flags = {
        "--watch-new",
        "--email-new",
        "--queue-initialized",
        "--test-email",
        "--calendar-add-new",
        "--calendar-auth",
        "--audit-calendar-matches",
        "--add-calendar-match",
        "--dry-run",
        "--email-on-fail",
        "--no-email-on-fail",
    }
    strip_value_flags = {
        "--poll-seconds",
        "--email-to",
        "--email-from",
        "--smtp-server",
        "--smtp-auth-user",
        "--queue-dir",
        "--google-password-file",
        "--calendar-matches",
        "--calendar-client-secret",
        "--calendar-token",
        "--calendar-id",
        "--calendar-state",
        "--calendar-duration-minutes",
        "--invite-email",
        "--match",
        "--time",
        "--duration-minutes",
    }
    strip_prefixes = tuple(f"{name}=" for name in strip_value_flags)
    for token in original_argv:
        if skip_next:
            skip_next = False
            continue
        if token in strip_flags:
            continue
        if token in strip_value_flags:
            skip_next = True
            continue
        if token.startswith(strip_prefixes):
            continue
        # Defense-in-depth: drop any future/unknown --calendar-* parent flags.
        if token == "--calendar" or token.startswith("--calendar-"):
            if "=" not in token:
                skip_next = True
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

    type_label = event.get("mention_type_label") or mention_type_label(
        event.get("mention_type") or mention_type_for_event(event)
    )
    lines = [
        "NEW KALSHI MENTION MARKET",
        "",
        f"Ticker: {event_ticker}",
        f"Title: {title}",
        f"Type: {type_label}",
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


# ---------------------------------------------------------------------------
# Google Calendar auto-add (MS-0010)
# ---------------------------------------------------------------------------


class CalendarClient(Protocol):
    """Minimal calendar insert surface used by watch mode and unit tests."""

    def insert_event(
        self,
        calendar_id: str,
        body: dict[str, Any],
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        """Create one calendar event and return the API-like response dict."""


class CalendarMatchCache:
    """Load and cache owner match config, reloading when the file mtime changes."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self._mtime_ns: int | None = None
        self._config: CalendarMatchConfig | None = None

    def get_config(self) -> "CalendarMatchConfig":
        try:
            stat = self.path.stat()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"calendar match file is missing: {self.path}. "
                "Copy deploy/config/calendar-matches.example.json to that path "
                "and edit the phrases list."
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"cannot read calendar match file {self.path}: {exc}") from exc

        if self._mtime_ns is not None and stat.st_mtime_ns == self._mtime_ns and self._config is not None:
            return self._config

        config = load_calendar_match_config(self.path)
        self._config = config
        self._mtime_ns = stat.st_mtime_ns
        return config

    def get_phrases(self) -> list[str]:
        return [phrase.match for phrase in self.get_config().phrases]


def _require_google_calendar_libs() -> tuple[Any, Any, Any, Any]:
    """Import optional Google client libraries or raise an actionable error."""
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Calendar support requires optional packages. Install with:\n"
            "  python3 -m pip install google-auth google-auth-oauthlib google-api-python-client\n"
            f"Original import error: {exc}"
        ) from exc
    return Credentials, InstalledAppFlow, build, GoogleAuthRequest


@dataclass(frozen=True)
class CalendarLocalTime:
    """Owner wall-clock time in the scout --timezone."""

    hour: int
    minute: int

    def label(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


@dataclass(frozen=True)
class CalendarPhrase:
    """One match entry from calendar-matches.json (string or object form)."""

    match: str
    time: CalendarLocalTime | None = None
    duration_minutes: int | None = None


@dataclass(frozen=True)
class CalendarMatchConfig:
    """Validated owner calendar match file (MS-0010/MS-0011)."""

    phrases: tuple[CalendarPhrase, ...]
    default_time: CalendarLocalTime | None = None

    def phrase_matches(self) -> list[str]:
        return [phrase.match for phrase in self.phrases]

    def phrase_by_match_casefold(self) -> dict[str, CalendarPhrase]:
        return {phrase.match.casefold(): phrase for phrase in self.phrases}


_CALENDAR_TIME_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


def parse_calendar_local_time(value: object, *, field_name: str, path: Path, index: int | None = None) -> CalendarLocalTime:
    """Parse HH:MM / H:MM (24h) for calendar match config fields."""
    where = f"{field_name}" if index is None else f"{field_name} at phrases[{index}]"
    if not isinstance(value, str):
        raise RuntimeError(
            f"calendar match file {where} must be a string HH:MM in {path}"
        )
    raw = value.strip()
    match = _CALENDAR_TIME_RE.fullmatch(raw)
    if match is None:
        raise RuntimeError(
            f"calendar match file {where} must be 24-hour HH:MM or H:MM "
            f"(got {value!r}) in {path}"
        )
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if hour > 23 or minute > 59:
        raise RuntimeError(
            f"calendar match file {where} is out of range (got {raw!r}; "
            f"hour 0-23, minute 0-59) in {path}"
        )
    return CalendarLocalTime(hour=hour, minute=minute)


def parse_calendar_duration_minutes(value: object, *, path: Path, index: int) -> int:
    """Parse a whole positive minute duration from a phrase object."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(
            f"calendar match phrase at index {index} duration_minutes must be "
            f"a positive whole number of minutes in {path}"
        )
    if isinstance(value, float) and not value.is_integer():
        raise RuntimeError(
            f"calendar match phrase at index {index} duration_minutes must be "
            f"a whole number of minutes (got {value!r}) in {path}"
        )
    minutes = int(value)
    if minutes <= 0:
        raise RuntimeError(
            f"calendar match phrase at index {index} duration_minutes must be "
            f"greater than zero (got {minutes}) in {path}"
        )
    return minutes


def load_calendar_match_config(path: Path) -> CalendarMatchConfig:
    """Load and validate the owner calendar match JSON file.

    Schema (v1, MS-0011)::

        {
          "version": 1,
          "default_time": "18:30",
          "phrases": [
            "simple string",
            {"match": "abc world news tonight", "time": "18:30", "duration_minutes": 30}
          ]
        }

    Plain strings remain valid. Object entries require non-empty ``match`` and
    may set optional ``time`` / ``duration_minutes``. Phrases are de-duplicated
    by casefolded match text (first wins).
    """
    match_path = path.expanduser()
    try:
        raw_text = match_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"calendar match file is missing: {match_path}. "
            "Copy deploy/config/calendar-matches.example.json to that path "
            "and edit the phrases list."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"cannot read calendar match file {match_path}: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"calendar match file is not valid JSON ({match_path}): {exc.msg} "
            f"at line {exc.lineno} column {exc.colno}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"calendar match file must be a JSON object with version/phrases: {match_path}"
        )
    version = payload.get("version")
    if version != CALENDAR_MATCH_FILE_VERSION:
        raise RuntimeError(
            f"calendar match file version must be {CALENDAR_MATCH_FILE_VERSION} "
            f"(got {version!r}) in {match_path}"
        )
    if "phrases" not in payload:
        raise RuntimeError(f"calendar match file is missing 'phrases' array: {match_path}")
    phrases_raw = payload.get("phrases")
    if not isinstance(phrases_raw, list):
        raise RuntimeError(f"calendar match file 'phrases' must be a JSON array: {match_path}")

    default_time = None
    if "default_time" in payload and payload.get("default_time") is not None:
        default_time = parse_calendar_local_time(
            payload.get("default_time"),
            field_name="default_time",
            path=match_path,
        )

    cleaned: list[CalendarPhrase] = []
    seen: set[str] = set()
    for index, item in enumerate(phrases_raw):
        phrase_time: CalendarLocalTime | None = None
        duration_minutes: int | None = None
        if isinstance(item, str):
            phrase_text = item.strip()
            if not phrase_text:
                raise RuntimeError(
                    f"calendar match phrase at index {index} is empty after trim in {match_path}"
                )
        elif isinstance(item, dict):
            if "match" not in item:
                raise RuntimeError(
                    f"calendar match phrase at index {index} object is missing "
                    f"'match' string in {match_path}"
                )
            match_value = item.get("match")
            if not isinstance(match_value, str):
                raise RuntimeError(
                    f"calendar match phrase at index {index} 'match' must be a string in {match_path}"
                )
            phrase_text = match_value.strip()
            if not phrase_text:
                raise RuntimeError(
                    f"calendar match phrase at index {index} 'match' is empty after trim in {match_path}"
                )
            if "time" in item and item.get("time") is not None:
                phrase_time = parse_calendar_local_time(
                    item.get("time"),
                    field_name="time",
                    path=match_path,
                    index=index,
                )
            if "duration_minutes" in item and item.get("duration_minutes") is not None:
                duration_minutes = parse_calendar_duration_minutes(
                    item.get("duration_minutes"),
                    path=match_path,
                    index=index,
                )
        else:
            raise RuntimeError(
                f"calendar match phrase at index {index} must be a string or object in {match_path}"
            )

        key = phrase_text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            CalendarPhrase(
                match=phrase_text,
                time=phrase_time,
                duration_minutes=duration_minutes,
            )
        )

    if not cleaned:
        raise RuntimeError(
            f"calendar match file has no usable phrases after trim/dedupe: {match_path}"
        )
    return CalendarMatchConfig(phrases=tuple(cleaned), default_time=default_time)


def load_calendar_match_phrases(path: Path) -> list[str]:
    """Load match strings only (compatibility wrapper around full config load)."""
    return load_calendar_match_config(path).phrase_matches()


def calendar_phrase_to_payload(phrase: CalendarPhrase) -> str | dict[str, Any]:
    """Serialize one phrase as plain string or object (only set optional fields)."""
    if phrase.time is None and phrase.duration_minutes is None:
        return phrase.match
    payload: dict[str, Any] = {"match": phrase.match}
    if phrase.time is not None:
        payload["time"] = phrase.time.label()
    if phrase.duration_minutes is not None:
        payload["duration_minutes"] = int(phrase.duration_minutes)
    return payload


def calendar_match_config_to_payload(config: CalendarMatchConfig) -> dict[str, Any]:
    """Canonical JSON-serializable dict for version 1 calendar-matches files.

    Known keys only (version, optional default_time, phrases). Unknown top-level
    keys from a prior hand-edit are dropped on rewrite — documented MS-0014 behavior.
    """
    payload: dict[str, Any] = {
        "version": CALENDAR_MATCH_FILE_VERSION,
    }
    if config.default_time is not None:
        payload["default_time"] = config.default_time.label()
    payload["phrases"] = [calendar_phrase_to_payload(phrase) for phrase in config.phrases]
    return payload


def save_calendar_match_config(path: Path, config: CalendarMatchConfig) -> None:
    """Atomically write a validated calendar match config (mode 600)."""
    write_cache_atomic(path.expanduser(), calendar_match_config_to_payload(config))


def format_calendar_phrase_entry(phrase: CalendarPhrase) -> str:
    """Compact JSON-ish entry string for stdout summaries."""
    return json.dumps(calendar_phrase_to_payload(phrase), ensure_ascii=False)


def add_calendar_match(
    path: Path,
    *,
    match: str,
    time: str | None = None,
    duration_minutes: int | None = None,
    create_if_missing: bool = True,
    dry_run: bool = False,
) -> tuple[CalendarMatchConfig, str, CalendarPhrase]:
    """Load-or-create, merge one phrase, validate, and optionally save.

    Returns ``(new_config, action, resulting_phrase)`` where action is one of
    ``created-file``, ``added``, ``updated``, or ``already-present``.
    """
    match_path = path.expanduser()
    phrase_text = str(match).strip()
    if not phrase_text:
        raise RuntimeError("--match must be a non-empty phrase after trim")

    phrase_time: CalendarLocalTime | None = None
    if time is not None:
        phrase_time = parse_calendar_local_time(
            time,
            field_name="--time",
            path=match_path,
        )

    phrase_duration: int | None = None
    if duration_minutes is not None:
        # Reuse file-loader rules (whole minutes > 0) with a CLI-oriented label.
        try:
            phrase_duration = parse_calendar_duration_minutes(
                duration_minutes,
                path=match_path,
                index=0,
            )
        except RuntimeError as exc:
            message = str(exc)
            message = message.replace(
                "calendar match phrase at index 0 duration_minutes",
                "--duration-minutes",
            )
            message = message.replace(f" in {match_path}", "")
            raise RuntimeError(message) from exc

    wants_schedule = phrase_time is not None or phrase_duration is not None
    file_existed = match_path.exists()

    if file_existed:
        try:
            config = load_calendar_match_config(match_path)
        except RuntimeError as exc:
            raise RuntimeError(
                f"refusing to modify invalid calendar match file {match_path}: {exc}. "
                "Fix the file or run: ./mention_scout.py --audit-calendar-matches"
            ) from exc
        phrases = list(config.phrases)
        default_time = config.default_time
        action_created = False
    else:
        if not create_if_missing:
            raise RuntimeError(f"calendar match file is missing: {match_path}")
        phrases = []
        default_time = None
        action_created = True

    key = phrase_text.casefold()
    existing_index: int | None = None
    for index, existing in enumerate(phrases):
        if existing.match.casefold() == key:
            existing_index = index
            break

    if existing_index is None:
        new_phrase = CalendarPhrase(
            match=phrase_text,
            time=phrase_time,
            duration_minutes=phrase_duration,
        )
        phrases.append(new_phrase)
        action = "created-file" if action_created else "added"
    else:
        existing = phrases[existing_index]
        if not wants_schedule:
            new_phrase = existing
            action = "already-present"
        else:
            new_phrase = CalendarPhrase(
                match=existing.match,
                time=phrase_time if phrase_time is not None else existing.time,
                duration_minutes=(
                    phrase_duration
                    if phrase_duration is not None
                    else existing.duration_minutes
                ),
            )
            phrases[existing_index] = new_phrase
            action = "updated"

    new_config = CalendarMatchConfig(phrases=tuple(phrases), default_time=default_time)
    # Ensure the in-memory result is always a complete valid config.
    if not new_config.phrases:
        raise RuntimeError(
            f"calendar match file would have no usable phrases after change: {match_path}"
        )

    if not dry_run and action != "already-present":
        # Parent dir for first create; write_cache_atomic also mkdirs, but keep
        # config dir private when we are the ones creating it.
        if action_created:
            match_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(match_path.parent, 0o700)
            except OSError:
                pass
        save_calendar_match_config(match_path, new_config)
    elif not dry_run and action == "already-present" and action_created:
        # Should not happen (empty create without phrase), but keep safe.
        save_calendar_match_config(match_path, new_config)

    return new_config, action, new_phrase


def format_calendar_matches_audit_fail_email(
    *,
    path: Path,
    error: str,
    detected_at: datetime,
    local_tz: ZoneInfo,
) -> tuple[str, str]:
    """Build subject/body for calendar-matches audit failure (no secrets)."""
    subject = "[Kalshi] FAIL | calendar-matches audit"
    err_text = " ".join(str(error).split())
    if len(err_text) > CALENDAR_ERROR_BODY_LIMIT:
        err_text = err_text[: CALENDAR_ERROR_BODY_LIMIT - 3] + "..."
    abs_path = path.expanduser()
    try:
        abs_path_display = str(abs_path.resolve())
    except OSError:
        abs_path_display = str(abs_path)

    try:
        host = socket.gethostname() or "unknown"
    except OSError:
        host = "unknown"

    body = "\n".join(
        [
            "Kalshi mention-scout calendar-matches AUDIT FAILURE",
            "",
            f"Time: {format_local_time(detected_at, local_tz)}",
            f"Host: {host}",
            f"Version: {VERSION}",
            f"Path: {abs_path_display}",
            "",
            "Error:",
            f"  {err_text}",
            "",
            "Schema reminder (version 1):",
            "  {",
            '    "version": 1,',
            '    "default_time": "18:30",',
            '    "phrases": [',
            '      "simple string",',
            '      {"match": "phrase", "time": "18:30", "duration_minutes": 30}',
            "    ]",
            "  }",
            "",
            "Remediation ideas:",
            "  - Fix JSON syntax (commas, quotes, brackets)",
            "  - Validate times as 24-hour HH:MM / H:MM",
            '  - Or re-add via: ./mention_scout.py --add-calendar-match --match "…"',
            "  - Example: deploy/config/calendar-matches.example.json",
            "  - After fix: ./mention_scout.py --audit-calendar-matches",
            "",
            "This alert is from --audit-calendar-matches (MS-0014).",
            "Watch startup FAIL mail (MS-0012), when enabled, is separate.",
        ]
    )
    return subject, body


def run_audit_calendar_matches(args: argparse.Namespace) -> int:
    """One-shot validate calendar-matches.json; optional FAIL email on error."""
    match_path = args.calendar_matches.expanduser()
    try:
        local_tz = ZoneInfo(args.timezone)
    except Exception as exc:
        raise SystemExit(f"Invalid --timezone {args.timezone!r}: {exc}") from exc

    try:
        config = load_calendar_match_config(match_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        if getattr(args, "email_on_fail", True):
            try:
                password = verify_email_configuration(args)
            except RuntimeError as mail_exc:
                print(
                    f"audit FAIL email skipped: {mail_exc}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                try:
                    subject, body = format_calendar_matches_audit_fail_email(
                        path=match_path,
                        error=str(exc),
                        detected_at=datetime.now(timezone.utc),
                        local_tz=local_tz,
                    )
                    run_swaks_email(
                        recipient=args.email_to,
                        sender=args.email_from,
                        smtp_server=args.smtp_server,
                        auth_user=args.smtp_auth_user,
                        password=password,
                        subject=subject,
                        body=body,
                    )
                    if args.verbose:
                        print(
                            f"audit FAIL email sent to {args.email_to}",
                            file=sys.stderr,
                            flush=True,
                        )
                except RuntimeError as mail_exc:
                    print(
                        f"audit FAIL email failed: {mail_exc}",
                        file=sys.stderr,
                        flush=True,
                    )
        return 1

    try:
        path_display = str(match_path.resolve())
    except OSError:
        path_display = str(match_path)

    lines = [
        "calendar-matches audit ok",
        f"path: {path_display}",
        f"version: {CALENDAR_MATCH_FILE_VERSION}",
        f"phrases: {len(config.phrases)}",
    ]
    if config.default_time is not None:
        lines.append(f"default_time: {config.default_time.label()}")
    else:
        lines.append("default_time: (none)")
    print("\n".join(lines), flush=True)

    if args.verbose:
        for phrase in config.phrases:
            print(f"  - {format_calendar_phrase_entry(phrase)}", flush=True)
    return 0


def run_add_calendar_match(args: argparse.Namespace) -> int:
    """One-shot add/update a calendar match phrase with atomic write."""
    match_path = args.calendar_matches.expanduser()
    raw_match = getattr(args, "match", None)
    if raw_match is None:
        raise SystemExit("--add-calendar-match requires --match")

    time_value = getattr(args, "match_time", None)
    duration_value = getattr(args, "match_duration_minutes", None)
    dry_run = bool(getattr(args, "dry_run", False))

    try:
        config, action, phrase = add_calendar_match(
            match_path,
            match=str(raw_match),
            time=time_value,
            duration_minutes=duration_value,
            create_if_missing=True,
            dry_run=dry_run,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        path_display = str(match_path.resolve())
    except OSError:
        path_display = str(match_path)

    lines = [
        "calendar-matches dry-run" if dry_run else "calendar-matches updated",
        f"path: {path_display}",
        f"action: {action}",
        f"entry: {format_calendar_phrase_entry(phrase)}",
        f"phrases_total: {len(config.phrases)}",
    ]
    if dry_run:
        lines.append("dry-run: not written")
    print("\n".join(lines), flush=True)
    return 0


def resolve_calendar_match_options(
    matched_phrases: list[str],
    config: CalendarMatchConfig,
) -> tuple[CalendarLocalTime | None, int | None, str | None]:
    """Pick owner time/duration from matched phrases (first hit wins per field).

    Returns ``(owner_time_or_none, duration_override_or_none, time_source_label)``.
    Time source label is the phrase match text, ``default_time``, or None.
    """
    by_key = config.phrase_by_match_casefold()
    owner_time: CalendarLocalTime | None = None
    time_source: str | None = None
    duration_override: int | None = None

    for matched in matched_phrases:
        phrase = by_key.get(str(matched).casefold())
        if phrase is None:
            continue
        if owner_time is None and phrase.time is not None:
            owner_time = phrase.time
            time_source = phrase.match
        if duration_override is None and phrase.duration_minutes is not None:
            duration_override = phrase.duration_minutes
        if owner_time is not None and duration_override is not None:
            break

    if owner_time is None and config.default_time is not None:
        owner_time = config.default_time
        time_source = "default_time"

    return owner_time, duration_override, time_source


def event_calendar_haystack(
    event: dict[str, Any],
    records: list[dict[str, Any]] | None = None,
) -> str:
    """Build casefold match text from parent overview fields + child titles/tickers.

    Intentionally omits settlement rules boilerplate (false-positive magnet).
    """
    parts: list[str] = []
    for field in (
        "title",
        "sub_title",
        "subtitle",
        "description",
        "category",
        "event_ticker",
        "series_ticker",
    ):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    for record in records or []:
        if not isinstance(record, dict):
            continue
        for field in ("title", "subtitle", "yes_sub_title", "no_sub_title", "ticker", "event_ticker"):
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())

    return " ".join(parts).casefold()


def matching_calendar_phrases(haystack: str, phrases: Iterable[str]) -> list[str]:
    """Return owner phrases that are case-insensitive substrings of ``haystack``.

    ``haystack`` should already be casefolded (see event_calendar_haystack).
    Returned phrases preserve the owner's original spelling/casing from the file.
    """
    text = haystack if haystack == haystack.casefold() else haystack.casefold()
    hits: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        cleaned = str(phrase).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        if key in text:
            seen.add(key)
            hits.append(cleaned)
    return hits


def calendar_dedupe_key(event_ticker: str, calendar_id: str) -> str:
    """Stable local-state key for one parent event on one calendar."""
    return f"{str(event_ticker).strip()}::{str(calendar_id).strip() or DEFAULT_CALENDAR_ID}"


def load_calendar_added_state(path: Path) -> dict[str, Any]:
    """Load calendar dedupe state, or an empty v1 document when missing."""
    state_path = path.expanduser()
    if not state_path.exists():
        return {"version": CALENDAR_STATE_FILE_VERSION, "entries": {}}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"calendar state file is not valid JSON ({state_path}): {exc.msg}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"cannot read calendar state file {state_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"calendar state file must be a JSON object: {state_path}")
    entries = payload.get("entries")
    if entries is None:
        entries = {}
    if not isinstance(entries, dict):
        raise RuntimeError(f"calendar state file 'entries' must be an object: {state_path}")
    return {
        "version": int(payload.get("version") or CALENDAR_STATE_FILE_VERSION),
        "entries": dict(entries),
    }


def save_calendar_added_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically persist calendar dedupe state."""
    payload = {
        "version": int(state.get("version") or CALENDAR_STATE_FILE_VERSION),
        "entries": dict(state.get("entries") or {}),
    }
    write_cache_atomic(path.expanduser(), payload)


def calendar_already_added(state: dict[str, Any], event_ticker: str, calendar_id: str) -> bool:
    """Return whether local state already recorded a successful insert."""
    entries = state.get("entries") if isinstance(state, dict) else None
    if not isinstance(entries, dict):
        return False
    return calendar_dedupe_key(event_ticker, calendar_id) in entries


def mark_calendar_added(
    state: dict[str, Any],
    *,
    event_ticker: str,
    calendar_id: str,
    added_at_utc: str,
    calendar_event_id: str | None = None,
    html_link: str | None = None,
    matched_phrase: str | None = None,
    kind: str = "event",
) -> dict[str, Any]:
    """Record a successful insert or a deduped error outcome in local state."""
    if not isinstance(state.get("entries"), dict):
        state["entries"] = {}
    key = calendar_dedupe_key(event_ticker, calendar_id)
    entry: dict[str, Any] = {
        "added_at_utc": added_at_utc,
        "kind": kind,
    }
    if calendar_event_id:
        entry["calendar_event_id"] = calendar_event_id
    if html_link:
        entry["html_link"] = html_link
    if matched_phrase:
        entry["matched_phrase"] = matched_phrase
    state["entries"][key] = entry
    return state


def _schedule_is_date_only(_event_local: datetime, source: str) -> bool:
    """Return True when the schedule source is date-only (no reliable clock time)."""
    source_l = source.casefold()
    if "exact time unavailable" in source_l:
        return True
    return any(
        token in source_l
        for token in (
            "strike_date",
            "event_date",
            "scheduled_date",
            "ticker date",
            "kalshi event date",
        )
    )


def resolve_calendar_schedule(
    event: dict[str, Any],
    records: list[dict[str, Any]],
    local_tz: ZoneInfo,
) -> tuple[datetime | None, str, bool]:
    """Resolve start time/date for a calendar row from overview + child records.

    Returns ``(start_utc_or_none, source_label, is_date_only)``.
    """
    first_iso = event.get("first_event_time_utc")
    parsed = parse_iso(first_iso) if isinstance(first_iso, str) else None
    sources = event.get("event_time_sources") or []
    source = str(sources[0]) if sources else "event overview"

    if parsed is None:
        for record in records:
            if not isinstance(record, dict):
                continue
            candidate = parse_iso(record.get("event_time_utc"))
            if candidate is not None:
                parsed = candidate
                source = str(record.get("event_time_source") or source)
                break

    if parsed is None:
        return None, "no event date supplied", False

    date_only = _schedule_is_date_only(parsed.astimezone(local_tz), source)
    return parsed, source, date_only



def validate_email_address(addr: str, *, flag: str = "--invite-email") -> str:
    """Return a stripped email address or raise RuntimeError with an actionable message."""
    value = str(addr or "").strip()
    if not value:
        raise RuntimeError(f"invalid {flag}: address is empty")
    if any(ch.isspace() for ch in value):
        raise RuntimeError(f"invalid {flag}: address must not contain whitespace: {value!r}")
    for bad in ("\r", "\n", ",", ";", "<", ">", '"', "\\"):
        if bad in value:
            raise RuntimeError(f"invalid {flag}: address contains forbidden character: {value!r}")
    if value.count("@") != 1:
        raise RuntimeError(f"invalid {flag}: expected one @ in address: {value!r}")
    local, domain = value.split("@", 1)
    if not local or not domain:
        raise RuntimeError(f"invalid {flag}: missing local or domain part: {value!r}")
    if "." not in domain:
        raise RuntimeError(f"invalid {flag}: domain must contain a dot: {value!r}")
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise RuntimeError(f"invalid {flag}: malformed domain: {value!r}")
    return value


def normalize_invite_emails(raw: list[str] | None, *, flag: str = "--invite-email") -> list[str]:
    """Validate, dedupe (casefold), and preserve order for --invite-email values."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        addr = validate_email_address(item, flag=flag)
        key = addr.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    if len(out) > MAX_INVITE_EMAILS:
        raise RuntimeError(
            f"{flag} accepts at most {MAX_INVITE_EMAILS} addresses "
            f"(got {len(out)} after dedupe)"
        )
    return out


def build_calendar_event_body(
    event: dict[str, Any],
    *,
    matched_phrases: list[str],
    local_tz: ZoneInfo,
    duration_minutes: int,
    detected_at: datetime,
    records: list[dict[str, Any]] | None = None,
    schedule: tuple[datetime | None, str, bool] | None = None,
    owner_time: CalendarLocalTime | None = None,
    owner_time_source: str | None = None,
    invite_emails: list[str] | None = None,
) -> dict[str, Any]:
    """Build a Google Calendar events.insert body for one parent mention event.

    Date-only Kalshi schedules become all-day unless ``owner_time`` is set
    (MS-0011), in which case the event is timed on that local date. Real timed
    Kalshi schedules are never overridden by owner_time.

    Raises RuntimeError when no usable schedule exists (caller should email).
    """
    if duration_minutes <= 0:
        raise RuntimeError("--calendar-duration-minutes must be greater than zero")

    records = records or []
    if schedule is None:
        start_utc, source, date_only = resolve_calendar_schedule(event, records, local_tz)
    else:
        start_utc, source, date_only = schedule

    if start_utc is None:
        raise RuntimeError(
            "no usable event schedule for calendar insert "
            f"(ticker={event.get('event_ticker')!r}; source={source})"
        )

    title = clean_display_text(event.get("title")) or clean_display_text(event.get("event_ticker")) or "Untitled mention event"
    type_label = clean_display_text(event.get("mention_type_label"))
    if type_label and type_label.casefold() not in {"", "other"}:
        summary = f"[Kalshi] {type_label}: {title}"
    else:
        summary = f"[Kalshi] {title}"

    local_start = start_utc.astimezone(local_tz)
    applied_owner_time = False
    if date_only and owner_time is not None:
        day = local_start.date()
        local_start = datetime(
            day.year,
            day.month,
            day.day,
            owner_time.hour,
            owner_time.minute,
            tzinfo=local_tz,
        )
        source_note = owner_time_source or "calendar-matches"
        source = f"{source}; owner time {owner_time.label()} from {source_note}"
        date_only = False
        applied_owner_time = True

    event_ticker = clean_display_text(event.get("event_ticker")) or "(no event ticker)"
    description_bits = [
        f"Event ticker: {event_ticker}",
        f"Matched phrase(s): {', '.join(matched_phrases) if matched_phrases else '(none)'}",
    ]
    if type_label:
        description_bits.append(f"Mention type: {type_label}")
    url = kalshi_event_url(event)
    if url:
        description_bits.append(f"Kalshi: {url}")
    desc = clean_display_text(event.get("description"))
    if desc:
        description_bits.append("")
        description_bits.append(desc)
    description_bits.extend(
        [
            "",
            f"Schedule source: {source}",
            f"Detected: {format_local_time(detected_at, local_tz)}",
            "Created by mention-scout --watch-new --calendar-add-new.",
        ]
    )
    if applied_owner_time and owner_time is not None:
        description_bits.append(
            f"Owner-configured local start time: {owner_time.label()} "
            f"({getattr(local_tz, 'key', str(local_tz))})."
        )

    body: dict[str, Any] = {
        "summary": summary,
        "description": "\n".join(description_bits),
    }
    if url:
        body["source"] = {"title": "Kalshi", "url": url}
    attendees = [{"email": addr} for addr in (invite_emails or []) if str(addr).strip()]
    if attendees:
        body["attendees"] = attendees

    if date_only:
        day = local_start.date()
        body["start"] = {"date": day.isoformat()}
        body["end"] = {"date": (day + timedelta(days=1)).isoformat()}
    else:
        end_local = local_start + timedelta(minutes=duration_minutes)
        body["start"] = {
            "dateTime": local_start.isoformat(),
            "timeZone": getattr(local_tz, "key", str(local_tz)),
        }
        body["end"] = {
            "dateTime": end_local.isoformat(),
            "timeZone": getattr(local_tz, "key", str(local_tz)),
        }
    return body


def format_calendar_error_email(
    *,
    operation: str,
    error: str,
    detected_at: datetime,
    local_tz: ZoneInfo,
    event: dict[str, Any] | None = None,
    matched_phrases: list[str] | None = None,
    paths: dict[str, Path | str] | None = None,
) -> tuple[str, str]:
    """Build subject/body for a calendar failure notification (no secrets)."""
    event = event or {}
    ticker = clean_display_text(event.get("event_ticker")) or "watch"
    title = clean_display_text(event.get("title"))
    subject = f"[Kalshi] calendar error | {ticker}"
    err_text = " ".join(str(error).split())
    if len(err_text) > CALENDAR_ERROR_BODY_LIMIT:
        err_text = err_text[: CALENDAR_ERROR_BODY_LIMIT - 3] + "..."

    lines = [
        "Kalshi mention-scout Google Calendar error",
        "",
        f"Detected: {format_local_time(detected_at, local_tz)}",
        f"Operation: {operation}",
        f"Event ticker: {ticker}",
    ]
    if title:
        lines.append(f"Title: {title}")
    if matched_phrases:
        lines.append(f"Matched phrase(s): {', '.join(matched_phrases)}")
    lines.extend(["", f"Error: {err_text}", ""])
    if paths:
        lines.append("Expected paths (contents never emailed):")
        for label, path in paths.items():
            lines.append(f"  - {label}: {path}")
        lines.append("")
    lines.extend(
        [
            "Remediation ideas:",
            "  - Fix/create ~/.config/mention-scout/calendar-matches.json (see deploy/config example)",
            "  - Ensure client_secret.json exists and run: ./mention_scout.py --calendar-auth",
            "  - chmod 600 client_secret.json token.json",
            "  - Enable the Google Calendar API for the OAuth desktop client project",
            "",
            "This alert is generated by mention-scout --calendar-add-new.",
        ]
    )
    return subject, "\n".join(lines)


def _path_mode_too_open(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o077)
    except OSError:
        return False


def load_google_calendar_credentials(
    *,
    client_secret_path: Path,
    token_path: Path,
    allow_interactive: bool = False,
) -> Any:
    """Load OAuth credentials; optionally run installed-app consent once."""
    Credentials, InstalledAppFlow, _build, GoogleAuthRequest = _require_google_calendar_libs()
    secret = client_secret_path.expanduser()
    token = token_path.expanduser()

    if not secret.is_file():
        raise RuntimeError(
            f"Google OAuth client secret is missing: {secret}. "
            "Download a Desktop OAuth client JSON from Google Cloud Console into that path."
        )
    if _path_mode_too_open(secret):
        raise RuntimeError(
            f"Google OAuth client secret permissions are too broad: {secret} "
            "(run: chmod 600 ~/.config/mention-scout/client_secret.json)"
        )

    creds = None
    if token.exists():
        if not token.is_file():
            raise RuntimeError(f"Google OAuth token path is not a regular file: {token}")
        if _path_mode_too_open(token):
            raise RuntimeError(
                f"Google OAuth token permissions are too broad: {token} "
                "(run: chmod 600 ~/.config/mention-scout/token.json)"
            )
        try:
            creds = Credentials.from_authorized_user_file(str(token), list(CALENDAR_OAUTH_SCOPES))
        except Exception as exc:  # noqa: BLE001 - surface any token parse failure cleanly
            raise RuntimeError(
                f"could not load Google OAuth token from {token}: {exc}. "
                "Re-run ./mention_scout.py --calendar-auth"
            ) from exc

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Google OAuth token refresh failed: {exc}. "
                "Re-run ./mention_scout.py --calendar-auth"
            ) from exc
        _write_authorized_user_token(token, creds)
        return creds

    if not allow_interactive:
        raise RuntimeError(
            f"Google OAuth token is missing or unusable: {token}. "
            "Run ./mention_scout.py --calendar-auth once on a machine with a browser, "
            "then copy token.json into place for headless watch."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), list(CALENDAR_OAUTH_SCOPES))
        creds = flow.run_local_server(port=0)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Google OAuth interactive auth failed: {exc}") from exc

    _write_authorized_user_token(token, creds)
    return creds


def _write_authorized_user_token(token_path: Path, creds: Any) -> None:
    """Persist refreshed/new user credentials with restrictive permissions."""
    path = token_path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = creds.to_json() if hasattr(creds, "to_json") else json.dumps({
        "token": getattr(creds, "token", None),
        "refresh_token": getattr(creds, "refresh_token", None),
        "token_uri": getattr(creds, "token_uri", None),
        "client_id": getattr(creds, "client_id", None),
        "client_secret": getattr(creds, "client_secret", None),
        "scopes": list(getattr(creds, "scopes", []) or []),
    })
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload))
            handle.write("\n")
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


class GoogleCalendarApiClient:
    """Thin wrapper around googleapiclient Calendar events.insert."""

    def __init__(self, service: Any, *, timeout_seconds: float = 20.0) -> None:
        self._service = service
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_credentials(cls, credentials: Any, *, timeout_seconds: float = 20.0) -> "GoogleCalendarApiClient":
        _Credentials, _Flow, build, _Request = _require_google_calendar_libs()
        # cache_discovery=False avoids writing discovery docs into homedir unexpectedly.
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return cls(service, timeout_seconds=timeout_seconds)

    def insert_event(
        self,
        calendar_id: str,
        body: dict[str, Any],
        *,
        send_updates: str | None = None,
    ) -> dict[str, Any]:
        try:
            kwargs: dict[str, Any] = {"calendarId": calendar_id, "body": body}
            if send_updates:
                kwargs["sendUpdates"] = send_updates
            request = self._service.events().insert(**kwargs)
            # google-api-python-client supports num_retries on execute.
            result = request.execute(num_retries=2)
        except Exception as exc:  # noqa: BLE001 - normalize all API failures
            raise RuntimeError(f"Google Calendar API insert failed: {exc}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Google Calendar API insert returned a non-object response")
        return result


def run_calendar_auth(args: argparse.Namespace) -> int:
    """One-shot interactive OAuth; write token.json and exit."""
    try:
        load_google_calendar_credentials(
            client_secret_path=args.calendar_client_secret,
            token_path=args.calendar_token,
            allow_interactive=True,
        )
    except RuntimeError as exc:
        raise SystemExit(f"calendar auth failed: {exc}") from exc
    token_path = args.calendar_token.expanduser()
    print(f"calendar auth ok; token written to {token_path}", flush=True)
    return 0


def verify_calendar_configuration(args: argparse.Namespace) -> tuple[CalendarMatchCache, Any, dict[str, Any]]:
    """Fail-fast preflight for --calendar-add-new (secret/token/match/state/deps)."""
    # Import / secret / token checks first so missing optional deps fail loudly.
    credentials = load_google_calendar_credentials(
        client_secret_path=args.calendar_client_secret,
        token_path=args.calendar_token,
        allow_interactive=False,
    )
    match_cache = CalendarMatchCache(args.calendar_matches)
    # Validate match file immediately (and populate mtime cache).
    match_cache.get_phrases()
    state = load_calendar_added_state(args.calendar_state)
    return match_cache, credentials, state


def send_calendar_error_email(
    args: argparse.Namespace,
    *,
    password: str,
    operation: str,
    error: str,
    detected_at: datetime,
    local_tz: ZoneInfo,
    event: dict[str, Any] | None = None,
    matched_phrases: list[str] | None = None,
    verbose: bool = False,
) -> None:
    """Email a calendar failure through the existing swaks path."""
    subject, body = format_calendar_error_email(
        operation=operation,
        error=error,
        detected_at=detected_at,
        local_tz=local_tz,
        event=event,
        matched_phrases=matched_phrases,
        paths={
            "matches": args.calendar_matches.expanduser(),
            "client_secret": args.calendar_client_secret.expanduser(),
            "token": args.calendar_token.expanduser(),
            "state": args.calendar_state.expanduser(),
        },
    )
    run_swaks_email(
        recipient=args.email_to,
        sender=args.email_from,
        smtp_server=args.smtp_server,
        auth_user=args.smtp_auth_user,
        password=password,
        subject=subject,
        body=body,
    )
    if verbose:
        ticker = clean_display_text((event or {}).get("event_ticker")) or "watch"
        print(f"calendar error email sent for {ticker} to {args.email_to}", file=sys.stderr, flush=True)


def maybe_add_calendar_event_for_new_market(
    *,
    args: argparse.Namespace,
    event: dict[str, Any],
    records: list[dict[str, Any]],
    detected_at: datetime,
    local_tz: ZoneInfo,
    match_cache: CalendarMatchCache,
    calendar_client: CalendarClient,
    state: dict[str, Any],
    email_password: str,
    colors: bool,
) -> dict[str, Any]:
    """Phrase-match a new parent event and insert one calendar row when eligible.

    Returns the (possibly updated) dedupe state. Never raises for per-event
    failures: errors go to stderr + optional error email, then watch continues.
    """
    ticker = clean_display_text(event.get("event_ticker")) or ""
    calendar_id = str(args.calendar_id or DEFAULT_CALENDAR_ID)

    def _fail(operation: str, exc: Exception, matched: list[str] | None = None, dedupe_error: bool = False) -> dict[str, Any]:
        message = str(exc)
        print(
            color(f"calendar alert failed for {ticker or 'event'}: {message}", "red", colors),
            file=sys.stderr,
            flush=True,
        )
        try:
            send_calendar_error_email(
                args,
                password=email_password,
                operation=operation,
                error=message,
                detected_at=detected_at,
                local_tz=local_tz,
                event=event,
                matched_phrases=matched,
                verbose=bool(args.verbose),
            )
        except RuntimeError as mail_exc:
            print(
                color(f"calendar error email failed for {ticker or 'event'}: {mail_exc}", "red", colors),
                file=sys.stderr,
                flush=True,
            )
        if dedupe_error and ticker:
            mark_calendar_added(
                state,
                event_ticker=ticker,
                calendar_id=calendar_id,
                added_at_utc=iso_utc(detected_at),
                matched_phrase=(matched[0] if matched else None),
                kind="error",
            )
            try:
                save_calendar_added_state(args.calendar_state, state)
            except OSError as save_exc:
                print(
                    color(f"calendar state save failed for {ticker}: {save_exc}", "red", colors),
                    file=sys.stderr,
                    flush=True,
                )
        return state

    if not ticker:
        return _fail("calendar-match", RuntimeError("new event is missing event_ticker"))

    if calendar_already_added(state, ticker, calendar_id):
        if args.verbose:
            print(f"calendar skip (already added): {ticker}", file=sys.stderr, flush=True)
        return state

    try:
        match_config = match_cache.get_config()
    except RuntimeError as exc:
        return _fail("match-file", exc)

    phrases = match_config.phrase_matches()
    haystack = event_calendar_haystack(event, records)
    matched = matching_calendar_phrases(haystack, phrases)
    if not matched:
        if args.verbose:
            print(f"calendar skip (no phrase match): {ticker}", file=sys.stderr, flush=True)
        return state

    owner_time, duration_override, owner_time_source = resolve_calendar_match_options(
        matched, match_config
    )
    effective_duration = (
        int(duration_override)
        if duration_override is not None
        else int(args.calendar_duration_minutes)
    )
    invite_emails = list(getattr(args, "invite_emails", None) or [])
    try:
        body = build_calendar_event_body(
            event,
            matched_phrases=matched,
            local_tz=local_tz,
            duration_minutes=effective_duration,
            detected_at=detected_at,
            records=records,
            owner_time=owner_time,
            owner_time_source=owner_time_source,
            invite_emails=invite_emails,
        )
    except RuntimeError as exc:
        # Missing schedule: email once per ticker via error-kind dedupe entry.
        return _fail("schedule", exc, matched=matched, dedupe_error=True)

    try:
        result = calendar_client.insert_event(
            calendar_id,
            body,
            send_updates=("all" if invite_emails else None),
        )
    except RuntimeError as exc:
        return _fail("insert", exc, matched=matched)

    mark_calendar_added(
        state,
        event_ticker=ticker,
        calendar_id=calendar_id,
        added_at_utc=iso_utc(detected_at),
        calendar_event_id=str(result.get("id") or "") or None,
        html_link=str(result.get("htmlLink") or "") or None,
        matched_phrase=matched[0],
        kind="event",
    )
    try:
        save_calendar_added_state(args.calendar_state, state)
    except OSError as exc:
        print(
            color(f"calendar state save failed after insert for {ticker}: {exc}", "red", colors),
            file=sys.stderr,
            flush=True,
        )
    else:
        if invite_emails:
            guest_note = f"; attendees: {', '.join(invite_emails)}"
        else:
            guest_note = ""
        print(
            color(
                f"calendar event added for {ticker} (matched {matched[0]!r}{guest_note})",
                "green",
                colors,
            ),
            flush=True,
        )
    return state


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
        subject=format_new_market_email_subject(event),
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

    calendar_match_cache = None
    calendar_client = None
    calendar_state: dict[str, Any] | None = None
    if args.calendar_add_new:
        try:
            # Calendar error emails use the same swaks/Gmail path even when
            # --email-new is off, so SMTP credentials are required up front.
            if not getattr(args, "_google_password", None):
                args._google_password = verify_email_configuration(args)
            calendar_match_cache, calendar_credentials, calendar_state = verify_calendar_configuration(args)
            calendar_client = GoogleCalendarApiClient.from_credentials(
                calendar_credentials,
                timeout_seconds=float(args.timeout),
            )
        except RuntimeError as exc:
            raise SystemExit(f"calendar configuration error: {exc}") from exc

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
                if args.calendar_add_new and calendar_client is not None and calendar_match_cache is not None:
                    calendar_state = maybe_add_calendar_event_for_new_market(
                        args=args,
                        event=event,
                        records=_watch_records_for_event(snapshot, ticker),
                        detected_at=detected_at,
                        local_tz=local_tz,
                        match_cache=calendar_match_cache,
                        calendar_client=calendar_client,
                        state=calendar_state if calendar_state is not None else {
                            "version": CALENDAR_STATE_FILE_VERSION,
                            "entries": {},
                        },
                        email_password=args._google_password,
                        colors=colors,
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
    parser.add_argument(
        "--type",
        dest="mention_types",
        metavar="TYPE",
        help=(
            "Keep only mention events of these types (comma-separated, any-of). "
            f"Known: {', '.join(KNOWN_MENTION_TYPE_IDS)}. "
            "Aliases: ftn, wnt, world-news. Default: all types."
        ),
    )
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
    parser.add_argument(
        "--calendar-add-new",
        action="store_true",
        help=(
            "With --watch-new, create one Google Calendar event for each newly discovered "
            "parent mention event whose overview/child text matches a phrase in "
            "--calendar-matches. Requires OAuth client secret + token and SMTP for error mail."
        ),
    )
    parser.add_argument(
        "--calendar-auth",
        action="store_true",
        help=(
            "One-shot interactive Google OAuth using --calendar-client-secret; "
            "write --calendar-token and exit. Never used by headless --watch-new."
        ),
    )
    parser.add_argument(
        "--calendar-matches",
        type=Path,
        default=DEFAULT_CALENDAR_MATCHES_FILE,
        help="JSON phrase list gating --calendar-add-new (version 1; strings or {match,time,duration_minutes}; optional default_time)",
    )
    parser.add_argument(
        "--calendar-client-secret",
        type=Path,
        default=DEFAULT_CALENDAR_CLIENT_SECRET_FILE,
        help="Google OAuth desktop client secret JSON for calendar access",
    )
    parser.add_argument(
        "--calendar-token",
        type=Path,
        default=DEFAULT_CALENDAR_TOKEN_FILE,
        help="Stored Google OAuth user token written by --calendar-auth",
    )
    parser.add_argument(
        "--calendar-id",
        default=DEFAULT_CALENDAR_ID,
        help="Target Google Calendar id for --calendar-add-new",
    )
    parser.add_argument(
        "--calendar-state",
        type=Path,
        default=DEFAULT_CALENDAR_STATE_FILE,
        help="Local JSON dedupe state for successful calendar inserts / schedule errors",
    )
    parser.add_argument(
        "--calendar-duration-minutes",
        type=int,
        default=DEFAULT_CALENDAR_DURATION_MINUTES,
        metavar="MINUTES",
        help="Timed calendar event length when a precise start datetime is known",
    )
    parser.add_argument(
        "--invite-email",
        action="append",
        default=None,
        metavar="ADDRESS",
        dest="invite_email",
        help=(
            "With --calendar-add-new, add ADDRESS as a Google Calendar attendee on each "
            "newly created event (repeatable). Google is asked to notify guests "
            "(sendUpdates=all). Does not send scout SMTP mail to invitees."
        ),
    )
    parser.add_argument(
        "--audit-calendar-matches",
        action="store_true",
        help=(
            "One-shot: validate --calendar-matches with the same rules as watch/calendar "
            "preflight. On success print a short OK summary (no email). On failure exit "
            "non-zero and, by default, email a FAIL report when SMTP is loadable."
        ),
    )
    parser.add_argument(
        "--add-calendar-match",
        action="store_true",
        help=(
            "One-shot: safely create/update one phrase in --calendar-matches (requires "
            "--match). Optional is atomic; invalid existing files are refused (not clobbered)."
        ),
    )
    parser.add_argument(
        "--match",
        default=None,
        metavar="TEXT",
        help="Phrase text for --add-calendar-match (case-insensitive identity for updates)",
    )
    parser.add_argument(
        "--time",
        default=None,
        metavar="HH:MM",
        dest="match_time",
        help=(
            "Optional 24-hour local time (HH:MM / H:MM) for --add-calendar-match; "
            "writes object form when set"
        ),
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=None,
        metavar="N",
        dest="match_duration_minutes",
        help=(
            "Optional positive whole-minute duration override for --add-calendar-match; "
            "writes object form when set"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --add-calendar-match: validate and print the plan without writing",
    )
    email_on_fail_group = parser.add_mutually_exclusive_group()
    email_on_fail_group.add_argument(
        "--email-on-fail",
        dest="email_on_fail",
        action="store_true",
        default=None,
        help=(
            "With --audit-calendar-matches: attempt FAIL email on invalid match file "
            "(default when audit runs)"
        ),
    )
    email_on_fail_group.add_argument(
        "--no-email-on-fail",
        dest="email_on_fail",
        action="store_false",
        help="With --audit-calendar-matches: validate locally only (no SMTP attempt)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show pagination, cache, and retry diagnostics on stderr")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main() -> int:
    original_argv = sys.argv[1:]
    args = build_parser().parse_args()
    # Fail fast on invalid --type before any network/cache work (including watch).
    selected_types = parse_type_filter(getattr(args, "mention_types", None))
    args.selected_mention_types = selected_types
    try:
        args.invite_emails = normalize_invite_emails(getattr(args, "invite_email", None))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.invite_emails and not args.calendar_add_new:
        raise SystemExit(
            "--invite-email requires --calendar-add-new "
            "(calendar attendees only; scout does not SMTP-mail invitees)"
        )

    # MS-0014: audit/add are one-shots; default email-on-fail ON for audit only.
    if getattr(args, "email_on_fail", None) is None:
        args.email_on_fail = True

    audit_mode = bool(getattr(args, "audit_calendar_matches", False))
    add_mode = bool(getattr(args, "add_calendar_match", False))
    match_flag_set = getattr(args, "match", None) is not None
    time_flag_set = getattr(args, "match_time", None) is not None
    duration_flag_set = getattr(args, "match_duration_minutes", None) is not None
    dry_run_set = bool(getattr(args, "dry_run", False))
    # Detect whether the operator explicitly passed email-on-fail toggles.
    email_on_fail_explicit = any(
        token == "--email-on-fail"
        or token == "--no-email-on-fail"
        or token.startswith("--email-on-fail=")
        or token.startswith("--no-email-on-fail=")
        for token in original_argv
    )

    if audit_mode and add_mode:
        raise SystemExit(
            "--audit-calendar-matches and --add-calendar-match cannot be combined"
        )
    if match_flag_set and not add_mode:
        raise SystemExit("--match is only valid together with --add-calendar-match")
    if time_flag_set and not add_mode:
        raise SystemExit("--time is only valid together with --add-calendar-match")
    if duration_flag_set and not add_mode:
        raise SystemExit(
            "--duration-minutes is only valid together with --add-calendar-match"
        )
    if dry_run_set and not add_mode:
        raise SystemExit("--dry-run is only valid together with --add-calendar-match")
    if email_on_fail_explicit and not audit_mode:
        raise SystemExit(
            "--email-on-fail/--no-email-on-fail are only valid together with "
            "--audit-calendar-matches"
        )
    if add_mode and not match_flag_set:
        raise SystemExit("--add-calendar-match requires --match")
    if duration_flag_set and int(args.match_duration_minutes) <= 0:
        raise SystemExit("--duration-minutes must be greater than zero")

    oneshot_conflicts = [
        flag
        for flag, enabled in (
            ("--watch-new", args.watch_new),
            ("--email-new", args.email_new),
            ("--queue-initialized", args.queue_initialized),
            ("--test-email", args.test_email),
            ("--calendar-add-new", args.calendar_add_new),
            ("--calendar-auth", args.calendar_auth),
            ("--invite-email", bool(args.invite_emails)),
        )
        if enabled
    ]

    if audit_mode:
        if oneshot_conflicts:
            raise SystemExit(
                "--audit-calendar-matches is a one-shot command and cannot be combined with "
                + ", ".join(oneshot_conflicts)
            )
        return run_audit_calendar_matches(args)

    if add_mode:
        if oneshot_conflicts:
            raise SystemExit(
                "--add-calendar-match is a one-shot command and cannot be combined with "
                + ", ".join(oneshot_conflicts)
            )
        return run_add_calendar_match(args)

    if args.calendar_auth:
        conflict = [
            flag
            for flag, enabled in (
                ("--watch-new", args.watch_new),
                ("--email-new", args.email_new),
                ("--queue-initialized", args.queue_initialized),
                ("--test-email", args.test_email),
                ("--calendar-add-new", args.calendar_add_new),
            )
            if enabled
        ]
        if conflict:
            raise SystemExit(
                "--calendar-auth is a one-shot auth command and cannot be combined with "
                + ", ".join(conflict)
            )
        if int(args.calendar_duration_minutes) <= 0:
            raise SystemExit("--calendar-duration-minutes must be greater than zero")
        return run_calendar_auth(args)
    if args.test_email:
        if args.watch_new or args.email_new or args.queue_initialized or args.calendar_add_new:
            raise SystemExit(
                "--test-email sends once and cannot be combined with --watch-new, "
                "--email-new, --queue-initialized, or --calendar-add-new"
            )
        try:
            return send_test_email(args)
        except RuntimeError as exc:
            raise SystemExit(f"email test failed: {exc}") from exc
    if args.email_new and not args.watch_new:
        raise SystemExit("--email-new is only valid together with --watch-new")
    if args.queue_initialized and not args.watch_new:
        raise SystemExit("--queue-initialized is only valid together with --watch-new")
    if args.calendar_add_new and not args.watch_new:
        raise SystemExit("--calendar-add-new is only valid together with --watch-new")
    if args.calendar_add_new and int(args.calendar_duration_minutes) <= 0:
        raise SystemExit("--calendar-duration-minutes must be greater than zero")
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
    # Type filter is applied after parent metadata is available (below) so series
    # tickers can drive the deterministic taxonomy.
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

    # AND with --contains (already applied): any-of type filter at parent/event level.
    if selected_types is not None:
        mention_markets = [
            market
            for market in mention_markets
            if market_matches_types(market, selected_types, event_for(market))
        ]

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
    if selected_types is not None:
        print(f"type: {', '.join(sorted(selected_types))}")
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
