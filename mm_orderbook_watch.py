#!/usr/bin/env python3
"""Poll a Kalshi event until markets open, then dump public order books.

Discovery only. Never places, modifies, or cancels orders. Public GET only.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO
from urllib.parse import urlencode

import mention_markets as mm

VERSION = "1.7.0"
CHART_TICK_MINUTES = 5
WORLD_NEWS_END_HOUR = 19
CHART_WIDTH = 1100
CHART_PAD_LEFT = 72
CHART_PAD_RIGHT = 28
CHART_PAD_TOP = 88
CHART_PAD_BOTTOM = 64
CHART_PRICE_H = 280
CHART_SPREAD_H = 150
CHART_PANEL_GAP = 42
CHART_HEIGHT = (
    CHART_PAD_TOP + CHART_PRICE_H + CHART_PANEL_GAP + CHART_SPREAD_H + CHART_PAD_BOTTOM
)
MAGENTA = "\033[95m"
ONE = Decimal("1")
PRICE_QUANT = Decimal("0.0001")
SIZE_QUANT = Decimal("0.01")
DEFAULT_INTERVAL = 1.0
TOP_HIGHLIGHT = 50
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
REVERSE = "\033[7m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
OPEN_STATUSES = frozenset({"active", "open"})
ENGLISH_MONTH_ABBREV = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)

SleepFn = Callable[[float], None]
UrlOpenFn = Callable[..., Any]
ClockFn = Callable[[], datetime]


def world_news_event_ticker(when: date | None = None) -> str:
    """Today's World News Tonight event ticker: ``KXWORLDNEWSMENTION-YYMONDD``."""
    day = when or date.today()
    return (
        f"{mm.WORLD_NEWS_TICKER_PREFIX}-"
        f"{day.strftime('%y')}{ENGLISH_MONTH_ABBREV[day.month - 1]}{day.strftime('%d')}"
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_ts(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def is_open_status(market: Mapping[str, Any]) -> bool:
    return str(market.get("status") or "").casefold() in OPEN_STATUSES


def parse_levels(levels: Any) -> list[tuple[Decimal, str]]:
    """Parse Kalshi [price, size] rows. Bids arrive ascending (best last)."""
    parsed: list[tuple[Decimal, str]] = []
    if not isinstance(levels, list):
        return parsed
    for item in levels:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            price = Decimal(str(item[0]))
        except (InvalidOperation, ValueError):
            continue
        parsed.append((price, str(item[1])))
    return parsed


def format_price(price: Decimal) -> str:
    return f"{price.quantize(PRICE_QUANT)}"


def decimal_spread(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if isinstance(bid, Decimal) and isinstance(ask, Decimal):
        return ask - bid
    return None


def as_pairs(levels: list[tuple[Decimal, str]], *, best_first: bool = False) -> list[list[str]]:
    rows = list(reversed(levels)) if best_first else list(levels)
    return [[format_price(price), size] for price, size in rows]


def complement_asks(bid_levels: list[tuple[Decimal, str]]) -> list[tuple[Decimal, str]]:
    """A bid on one side at p is an ask on the other at 1-p. Lowest ask first."""
    asks = [(ONE - price, size) for price, size in bid_levels]
    asks.sort(key=lambda item: item[0])
    return asks


def format_levels(levels: list[tuple[Decimal, str]], *, best_first: bool = False) -> str:
    rows = as_pairs(levels, best_first=best_first)
    if not rows:
        return "-"
    return "  ".join(f"{price} x {size}" for price, size in rows)


def extract_bid_levels(book: Mapping[str, Any]) -> tuple[list[tuple[Decimal, str]], list[tuple[Decimal, str]]]:
    fp = book.get("orderbook_fp") if isinstance(book.get("orderbook_fp"), dict) else {}
    if isinstance(fp, dict) and (
        fp.get("yes_dollars") is not None or fp.get("no_dollars") is not None
    ):
        return parse_levels(fp.get("yes_dollars")), parse_levels(fp.get("no_dollars"))
    raw = book.get("orderbook") if isinstance(book.get("orderbook"), dict) else {}
    if isinstance(raw, dict):
        return parse_levels(raw.get("yes")), parse_levels(raw.get("no"))
    return [], []


def orderbook_url(market_ticker: str, *, depth: int) -> str:
    ticker = mm.kalshi_event_ticker(market_ticker)
    url = f"{mm.KALSHI_MARKETS_URL}/{ticker}/orderbook"
    if depth > 0:
        url = f"{url}?{urlencode({'depth': depth})}"
    return url


def fetch_orderbook(
    market_ticker: str,
    *,
    depth: int,
    urlopen_fn: UrlOpenFn | None,
    sleep_fn: SleepFn | None,
) -> dict[str, Any]:
    return mm.public_json_get(
        orderbook_url(market_ticker, depth=depth),
        urlopen_fn=urlopen_fn,
        sleep_fn=sleep_fn,
    )


def size_total(pairs: Any) -> Decimal:
    total = Decimal("0")
    if not isinstance(pairs, list):
        return total
    for item in pairs:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            total += Decimal(str(item[1]))
        except (InvalidOperation, ValueError):
            continue
    return total


def format_size(value: Decimal) -> str:
    return f"{value.quantize(SIZE_QUANT)}"


def summarize_market(market: Mapping[str, Any], book: Mapping[str, Any]) -> dict[str, Any]:
    yes_bids, no_bids = extract_bid_levels(book)
    yes_asks = complement_asks(no_bids)
    no_asks = complement_asks(yes_bids)
    ticker = str(market.get("ticker") or "").strip()
    yes_bid_pairs = as_pairs(yes_bids, best_first=True)
    yes_ask_pairs = as_pairs(yes_asks)
    no_bid_pairs = as_pairs(no_bids, best_first=True)
    no_ask_pairs = as_pairs(no_asks)
    yes_bid_total = size_total(yes_bid_pairs)
    yes_ask_total = size_total(yes_ask_pairs)
    no_bid_total = size_total(no_bid_pairs)
    no_ask_total = size_total(no_ask_pairs)
    bid_px = parse_optional_price(yes_bid_pairs[0] if yes_bid_pairs else None)
    ask_px = parse_optional_price(yes_ask_pairs[0] if yes_ask_pairs else None)
    spread = decimal_spread(bid_px, ask_px)
    return {
        "ticker": ticker,
        "status": str(market.get("status") or ""),
        "word": mm.market_word(dict(market)).strip(),
        "yes_bids": yes_bid_pairs,
        "yes_asks": yes_ask_pairs,
        "no_bids": no_bid_pairs,
        "no_asks": no_ask_pairs,
        "yes_bid": yes_bid_pairs[0] if yes_bid_pairs else None,
        "yes_ask": yes_ask_pairs[0] if yes_ask_pairs else None,
        "no_bid": no_bid_pairs[0] if no_bid_pairs else None,
        "no_ask": no_ask_pairs[0] if no_ask_pairs else None,
        "yes_bid_total": format_size(yes_bid_total),
        "yes_ask_total": format_size(yes_ask_total),
        "no_bid_total": format_size(no_bid_total),
        "no_ask_total": format_size(no_ask_total),
        "yes_spread": format_price(spread) if spread is not None else None,
        "orderbook": book,
    }


def paint(text: str, *codes: str, enabled: bool = True) -> str:
    if not enabled or not codes:
        return text
    return f"{''.join(codes)}{text}{RESET}"


def want_color(stream: TextIO, mode: str) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def render_levels(pairs: Any, *, kind: str, enabled: bool) -> str:
    if not isinstance(pairs, list) or not pairs:
        return "-"
    rendered: list[str] = []
    for index, item in enumerate(pairs):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        text = f"{item[0]} x {item[1]}"
        if index == 0:
            accent = YELLOW if kind == "ask" else CYAN
            text = paint(text, BOLD, REVERSE, accent, enabled=enabled)
        elif index < TOP_HIGHLIGHT:
            accent = YELLOW if kind == "ask" else CYAN
            text = paint(text, accent, enabled=enabled)
        else:
            text = paint(text, DIM, enabled=enabled)
        rendered.append(text)
    return "  ".join(rendered) if rendered else "-"


def print_snapshot(
    snapshot: Mapping[str, Any],
    *,
    file: TextIO | None = None,
    color: bool = False,
) -> None:
    out = file if file is not None else sys.stdout
    print(
        f"{snapshot['ts']}  {snapshot['event_ticker']}  "
        f"open={snapshot['open_count']}/{snapshot['market_count']}",
        file=out,
    )
    for item in snapshot.get("markets") or []:
        if not isinstance(item, dict):
            continue
        err = item.get("error")
        if err:
            print(f"  {item.get('word') or '?'}  {item.get('ticker')}  ERROR {err}", file=out)
            continue
        print(
            f"  {item.get('word') or '?'}  {paint(str(item.get('ticker') or ''), DIM, enabled=color)}  "
            f"status={item.get('status')}",
            file=out,
        )
        yes = paint("YES", GREEN, BOLD, enabled=color)
        no = paint("NO ", RED, BOLD, enabled=color)
        ask = paint("ask", YELLOW, BOLD, enabled=color)
        bid = paint("bid", CYAN, BOLD, enabled=color)
        print(
            f"    {yes} {ask}  tot {item.get('yes_ask_total') or '0.00'}  "
            f"{render_levels(item.get('yes_asks'), kind='ask', enabled=color)}",
            file=out,
        )
        print(
            f"    {yes} {bid}  tot {item.get('yes_bid_total') or '0.00'}  "
            f"{render_levels(item.get('yes_bids'), kind='bid', enabled=color)}",
            file=out,
        )
        print(
            f"    {no} {ask}  tot {item.get('no_ask_total') or '0.00'}  "
            f"{render_levels(item.get('no_asks'), kind='ask', enabled=color)}",
            file=out,
        )
        print(
            f"    {no} {bid}  tot {item.get('no_bid_total') or '0.00'}  "
            f"{render_levels(item.get('no_bids'), kind='bid', enabled=color)}",
            file=out,
        )
        spread = item.get("yes_spread")
        if spread:
            print(
                f"    {paint('spread', MAGENTA, BOLD, enabled=color)}  {spread}",
                file=out,
            )


def append_jsonl(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")


def parse_optional_price(pair: Any) -> Decimal | None:
    if isinstance(pair, (list, tuple)) and pair:
        try:
            return Decimal(str(pair[0]))
        except (InvalidOperation, ValueError):
            return None
    return None


def parse_total(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def append_history(history: dict[str, dict[str, Any]], snapshot: Mapping[str, Any]) -> None:
    """Keep per-market bid/ask samples as dumps arrive."""
    for item in snapshot.get("markets") or []:
        if not isinstance(item, dict) or item.get("error"):
            continue
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        series = history.setdefault(
            ticker,
            {"word": str(item.get("word") or ticker), "samples": []},
        )
        series["word"] = str(item.get("word") or series["word"])
        bid_px = parse_optional_price(item.get("yes_bid"))
        ask_px = parse_optional_price(item.get("yes_ask"))
        series["samples"].append(
            {
                "ts": snapshot.get("ts"),
                "yes_bid": bid_px,
                "yes_ask": ask_px,
                "no_bid": parse_optional_price(item.get("no_bid")),
                "no_ask": parse_optional_price(item.get("no_ask")),
                "spread": decimal_spread(bid_px, ask_px),
                "yes_bid_total": parse_total(item.get("yes_bid_total")),
                "yes_ask_total": parse_total(item.get("yes_ask_total")),
                "no_bid_total": parse_total(item.get("no_bid_total")),
                "no_ask_total": parse_total(item.get("no_ask_total")),
            }
        )


def chart_filename(ticker: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ticker).strip("._") or "market"
    return f"{safe}.svg"


def local_timezone() -> tzinfo:
    tz = datetime.now().astimezone().tzinfo
    return tz if tz is not None else timezone.utc


def parse_iso_ts(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    text = str(ts or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def tz_abbrev(tz: tzinfo | None = None) -> str:
    zone = tz if tz is not None else local_timezone()
    name = datetime.now(zone).strftime("%Z")
    return name or "local"


def format_axis_time(ts: Any, *, tz: tzinfo | None = None) -> str:
    """Chart axis clock in local time, no seconds (JSONL stays UTC)."""
    parsed = parse_iso_ts(ts)
    if parsed is None:
        return str(ts or "?")
    zone = tz if tz is not None else local_timezone()
    return parsed.astimezone(zone).strftime("%H:%M")


def is_world_news_event(event_ticker: str) -> bool:
    return mm.kalshi_event_ticker(event_ticker).startswith(mm.WORLD_NEWS_TICKER_PREFIX)


def floor_minutes(when: datetime, minutes: int = CHART_TICK_MINUTES) -> datetime:
    when = when.replace(second=0, microsecond=0)
    return when.replace(minute=(when.minute // minutes) * minutes)


def ceil_minutes(when: datetime, minutes: int = CHART_TICK_MINUTES) -> datetime:
    floored = floor_minutes(when, minutes)
    stripped = when.replace(second=0, microsecond=0)
    if stripped == floored:
        return floored
    return floored + timedelta(minutes=minutes)


def sample_local_times(
    samples: list[Mapping[str, Any]], tz: tzinfo
) -> list[datetime]:
    times: list[datetime] = []
    for sample in samples:
        parsed = parse_iso_ts(sample.get("ts"))
        if parsed is not None:
            times.append(parsed.astimezone(tz))
    return times


def time_window(
    samples: list[Mapping[str, Any]],
    event_ticker: str,
    tz: tzinfo,
) -> tuple[datetime, datetime]:
    times = sample_local_times(samples, tz)
    if times:
        start = floor_minutes(times[0])
        end = ceil_minutes(times[-1])
        if end <= start:
            end = start + timedelta(minutes=CHART_TICK_MINUTES)
    else:
        start = floor_minutes(datetime.now(tz))
        end = start + timedelta(minutes=CHART_TICK_MINUTES)
    if is_world_news_event(event_ticker):
        day = times[0] if times else datetime.now(tz)
        wnt_end = day.replace(
            hour=WORLD_NEWS_END_HOUR, minute=0, second=0, microsecond=0
        )
        if wnt_end > start:
            end = max(end, wnt_end)
    return start, end


def five_minute_ticks(start: datetime, end: datetime) -> list[datetime]:
    ticks: list[datetime] = []
    cursor = floor_minutes(start)
    if cursor < start:
        cursor += timedelta(minutes=CHART_TICK_MINUTES)
    while cursor <= end:
        ticks.append(cursor)
        cursor += timedelta(minutes=CHART_TICK_MINUTES)
    if ticks and ticks[-1] < end:
        ticks.append(end)
    if not ticks:
        ticks = [start, end]
    return ticks


def format_axis_price(value: float, span: float) -> str:
    if span < 0.08:
        return f"{value:.4f}"
    if span < 0.25:
        return f"{value:.3f}"
    return f"{value:.2f}"


def price_window(samples: list[Mapping[str, Any]]) -> tuple[float, float]:
    prices = [
        float(sample[field])
        for sample in samples
        for field in ("yes_bid", "yes_ask")
        if isinstance(sample.get(field), Decimal)
    ]
    if not prices:
        return 0.0, 1.0
    low, high = min(prices), max(prices)
    span = high - low
    if span < 0.04:
        mid = (high + low) / 2.0
        low, high = mid - 0.02, mid + 0.02
        span = high - low
    pad = max(span * 0.15, 0.01)
    low = max(0.0, low - pad)
    high = min(1.0, high + pad)
    if high <= low:
        high = min(1.0, low + 0.05)
    return low, high


def spread_window(samples: list[Mapping[str, Any]]) -> tuple[float, float]:
    spreads = [
        float(sample["spread"])
        for sample in samples
        if isinstance(sample.get("spread"), Decimal)
    ]
    if not spreads:
        return 0.0, 0.05
    low = min(0.0, min(spreads))
    high = max(spreads)
    if high - low < 0.01:
        high = low + 0.02
    pad = max((high - low) * 0.15, 0.005)
    return low, high + pad


def _x_at(when: datetime, t_min: datetime, t_max: datetime, left: float, width: float) -> float:
    span = max((t_max - t_min).total_seconds(), 1.0)
    frac = (when - t_min).total_seconds() / span
    frac = min(max(frac, 0.0), 1.0)
    return left + frac * width


def _price_points(
    samples: list[Mapping[str, Any]],
    field: str,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    y_min: float,
    y_max: float,
    t_min: datetime,
    t_max: datetime,
    tz: tzinfo,
) -> list[tuple[float, float]]:
    span_y = max(y_max - y_min, 1e-9)
    points: list[tuple[float, float]] = []
    for sample in samples:
        price = sample.get(field)
        parsed = parse_iso_ts(sample.get("ts"))
        if not isinstance(price, Decimal) or parsed is None:
            continue
        clamped = min(max(float(price), y_min), y_max)
        x = _x_at(parsed.astimezone(tz), t_min, t_max, left, width)
        y = top + (1.0 - (clamped - y_min) / span_y) * height
        points.append((x, y))
    return points


def _svg_polyline(points: list[tuple[float, float]], color: str, width: float = 1.6) -> str:
    if not points:
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="{color}"/>'
    joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return (
        f'<polyline fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linejoin="round" points="{joined}"/>'
    )


def _svg_band(bid_pts: list[tuple[float, float]], ask_pts: list[tuple[float, float]]) -> str:
    if len(bid_pts) < 2 or len(bid_pts) != len(ask_pts):
        return ""
    points = bid_pts + list(reversed(ask_pts))
    joined = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polygon fill="#ffd15c" fill-opacity="0.18" stroke="none" points="{joined}"/>'


def _y_axis(
    parts: list[str],
    *,
    left: float,
    top: float,
    plot_w: float,
    plot_h: float,
    y_min: float,
    y_max: float,
) -> None:
    span = y_max - y_min
    for step in range(5):
        frac = step / 4
        value = y_max - frac * span
        y = top + frac * plot_h
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" '
            f'stroke="#2a2a2a"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{y + 4:.2f}" fill="#cccccc" font-size="12" '
            f'text-anchor="end">{format_axis_price(value, span)}</text>'
        )


def render_market_svg(
    ticker: str,
    payload: Mapping[str, Any],
    event_ticker: str,
    *,
    tz: tzinfo | None = None,
) -> str:
    """One market: YES bid/ask plus spread vs local time."""
    samples = list(payload.get("samples") or [])
    word = str(payload.get("word") or ticker)
    last = samples[-1] if samples else {}
    bid_tot = format_size(parse_total(last.get("yes_bid_total"))) if last else "0.00"
    ask_tot = format_size(parse_total(last.get("yes_ask_total"))) if last else "0.00"
    last_spread = last.get("spread") if last else None
    spread_label = format_price(last_spread) if isinstance(last_spread, Decimal) else "-"
    y_min, y_max = price_window(samples)
    s_min, s_max = spread_window(samples)
    width, height = CHART_WIDTH, CHART_HEIGHT
    left = CHART_PAD_LEFT
    plot_w = width - CHART_PAD_LEFT - CHART_PAD_RIGHT
    price_top = CHART_PAD_TOP
    spread_top = CHART_PAD_TOP + CHART_PRICE_H + CHART_PANEL_GAP
    zone = tz if tz is not None else local_timezone()
    t_min, t_max = time_window(samples, event_ticker, zone)
    ticks = five_minute_ticks(t_min, t_max)
    rotate_labels = len(ticks) > 14
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        "<style>text{font-family:DejaVu Sans,Liberation Sans,sans-serif;}</style>",
        f'<rect width="{width}" height="{height}" fill="#111111"/>',
        f'<text x="24" y="32" fill="#eeeeee" font-size="20" font-weight="700">'
        f"{html.escape(word)}</text>",
        f'<text x="24" y="54" fill="#888888" font-size="13">{html.escape(event_ticker)}  '
        f"{html.escape(ticker)}</text>",
        '<text x="24" y="74" fill="#5ce1ff" font-size="13">YES bid</text>',
        '<text x="110" y="74" fill="#ffd15c" font-size="13">YES ask</text>',
        '<text x="196" y="74" fill="#ff79c6" font-size="13">spread</text>',
        f'<text x="{width - 24}" y="32" fill="#aaaaaa" font-size="13" text-anchor="end">'
        f"n={len(samples)}  bid tot {bid_tot}  ask tot {ask_tot}  spread {spread_label}</text>",
        f'<rect x="{left}" y="{price_top}" width="{plot_w}" height="{CHART_PRICE_H}" '
        f'fill="#191919" stroke="#333333"/>',
        f'<rect x="{left}" y="{spread_top}" width="{plot_w}" height="{CHART_SPREAD_H}" '
        f'fill="#191919" stroke="#333333"/>',
    ]
    _y_axis(
        parts, left=left, top=price_top, plot_w=plot_w, plot_h=CHART_PRICE_H,
        y_min=y_min, y_max=y_max,
    )
    _y_axis(
        parts, left=left, top=spread_top, plot_w=plot_w, plot_h=CHART_SPREAD_H,
        y_min=s_min, y_max=s_max,
    )
    parts.append(
        f'<text x="18" y="{price_top + CHART_PRICE_H / 2:.1f}" fill="#dddddd" font-size="13" '
        f'transform="rotate(-90 18 {price_top + CHART_PRICE_H / 2:.1f})">YES price ($)</text>'
    )
    parts.append(
        f'<text x="18" y="{spread_top + CHART_SPREAD_H / 2:.1f}" fill="#ff79c6" font-size="13" '
        f'transform="rotate(-90 18 {spread_top + CHART_SPREAD_H / 2:.1f})">Spread ($)</text>'
    )
    for tick in ticks:
        x = _x_at(tick, t_min, t_max, left, plot_w)
        parts.append(
            f'<line x1="{x:.2f}" y1="{price_top}" x2="{x:.2f}" '
            f'y2="{price_top + CHART_PRICE_H}" stroke="#2a2a2a"/>'
        )
        parts.append(
            f'<line x1="{x:.2f}" y1="{spread_top}" x2="{x:.2f}" '
            f'y2="{spread_top + CHART_SPREAD_H}" stroke="#2a2a2a"/>'
        )
        label = html.escape(tick.strftime("%H:%M"))
        label_y = spread_top + CHART_SPREAD_H + 20
        if rotate_labels:
            parts.append(
                f'<text x="{x:.2f}" y="{label_y:.2f}" fill="#cccccc" font-size="10" '
                f'text-anchor="end" transform="rotate(-45 {x:.2f} {label_y:.2f})">{label}</text>'
            )
        else:
            parts.append(
                f'<text x="{x:.2f}" y="{label_y:.2f}" fill="#cccccc" font-size="12" '
                f'text-anchor="middle">{label}</text>'
            )
    parts.append(
        f'<text x="{left + plot_w / 2:.1f}" y="{height - 16}" fill="#dddddd" '
        f'font-size="13" text-anchor="middle">Time ({html.escape(tz_abbrev(zone))})</text>'
    )
    bid_pts = _price_points(
        samples, "yes_bid", left=left, top=price_top, width=plot_w, height=CHART_PRICE_H,
        y_min=y_min, y_max=y_max, t_min=t_min, t_max=t_max, tz=zone,
    )
    ask_pts = _price_points(
        samples, "yes_ask", left=left, top=price_top, width=plot_w, height=CHART_PRICE_H,
        y_min=y_min, y_max=y_max, t_min=t_min, t_max=t_max, tz=zone,
    )
    parts.append(_svg_band(bid_pts, ask_pts))
    parts.append(_svg_polyline(ask_pts, "#ffd15c", 2.2))
    parts.append(_svg_polyline(bid_pts, "#5ce1ff", 2.2))
    parts.append(_svg_polyline(
        _price_points(
            samples, "spread", left=left, top=spread_top, width=plot_w, height=CHART_SPREAD_H,
            y_min=s_min, y_max=s_max, t_min=t_min, t_max=t_max, tz=zone,
        ),
        "#ff79c6",
        2.4,
    ))
    parts.append("</svg>")
    return "\n".join(part for part in parts if part)


def write_history_charts(
    chart_dir: Path,
    history: Mapping[str, dict[str, Any]],
    event_ticker: str,
    *,
    tz: tzinfo | None = None,
) -> list[Path]:
    chart_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    zone = tz if tz is not None else local_timezone()
    for ticker, payload in history.items():
        path = chart_dir / chart_filename(str(ticker))
        svg = render_market_svg(str(ticker), payload, event_ticker, tz=zone)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(svg, encoding="utf-8")
        tmp.replace(path)
        written.append(path)
    return written


def build_snapshot(
    event_ticker: str,
    markets: list[dict[str, Any]],
    *,
    depth: int,
    now: datetime,
    urlopen_fn: UrlOpenFn | None,
    sleep_fn: SleepFn | None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    open_count = 0
    for market in markets:
        ticker = str(market.get("ticker") or "").strip()
        if not ticker:
            continue
        opened = is_open_status(market)
        if opened:
            open_count += 1
        try:
            book = fetch_orderbook(
                ticker,
                depth=depth,
                urlopen_fn=urlopen_fn,
                sleep_fn=sleep_fn,
            )
            row = summarize_market(market, book)
        except mm.MentionMarketsError as exc:
            row = {
                "ticker": ticker,
                "status": str(market.get("status") or ""),
                "word": mm.market_word(market).strip(),
                "error": str(exc),
            }
        row["open"] = opened
        rows.append(row)
    return {
        "ts": iso_ts(now),
        "event_ticker": event_ticker,
        "open_count": open_count,
        "market_count": len(rows),
        "markets": rows,
    }


def run_watch(
    event_ticker: str,
    *,
    interval: float,
    log_path: Path,
    chart_path: Path | None,
    depth: int,
    max_wait: int,
    max_dumps: int,
    color_mode: str = "auto",
    urlopen_fn: UrlOpenFn | None = None,
    sleep_fn: SleepFn | None = None,
    clock_fn: ClockFn | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    sleeper = sleep_fn or time.sleep
    clock = clock_fn or utc_now
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    ticker = mm.kalshi_event_ticker(event_ticker)
    if not ticker:
        print("event ticker is empty", file=err)
        return 1
    print(
        f"mm-orderbook-watch {ticker} interval={interval}s log={log_path} "
        "(GET only; no orders)",
        file=err,
    )
    if chart_path is not None:
        print(
            f"charts: {chart_path}/*.svg  (eog FILE.svg   or   feh --reload 1 FILE.svg)",
            file=err,
        )
    opened = False
    wait_polls = 0
    dump_polls = 0
    history: dict[str, dict[str, Any]] = {}
    while True:
        markets = mm.fetch_markets_rest_paginated(
            ticker,
            urlopen_fn=urlopen_fn,
            sleep_fn=sleeper,
        )
        open_markets = [item for item in markets if is_open_status(item)]
        if not opened:
            wait_polls += 1
            statuses: dict[str, int] = {}
            for item in markets:
                key = str(item.get("status") or "unknown")
                statuses[key] = statuses.get(key, 0) + 1
            summary = ",".join(f"{name}={count}" for name, count in sorted(statuses.items()))
            print(
                f"{iso_ts(clock())}  waiting for open  markets={len(markets)}  {summary or 'none'}",
                file=err,
            )
            if open_markets:
                opened = True
                print(
                    f"{iso_ts(clock())}  {len(open_markets)} market(s) open; dumping order books",
                    file=err,
                )
            elif max_wait and wait_polls >= max_wait:
                print(
                    f"still not open after {wait_polls} poll(s); giving up",
                    file=err,
                )
                return 1
            else:
                if interval:
                    sleeper(interval)
                continue

        snapshot = build_snapshot(
            ticker,
            markets,
            depth=depth,
            now=clock(),
            urlopen_fn=urlopen_fn,
            sleep_fn=sleeper,
        )
        print_snapshot(snapshot, file=out, color=want_color(out, color_mode))
        out.flush()
        append_jsonl(log_path, snapshot)
        append_history(history, snapshot)
        if chart_path is not None:
            write_history_charts(chart_path, history, ticker)
        dump_polls += 1
        if max_dumps and dump_polls >= max_dumps:
            return 0
        if interval:
            sleeper(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mm-orderbook-watch",
        description=(
            "Poll a Kalshi event every second until markets are active/open, "
            "then print and log the public order book every second. "
            "Discovery only — does not place orders."
        ),
    )
    parser.add_argument(
        "event_ticker",
        nargs="?",
        default="",
        help="Event ticker (default: today's KXWORLDNEWSMENTION-YYMONDD)",
    )
    parser.add_argument(
        "--date",
        default="",
        help="YYYY-MM-DD used when event_ticker is omitted (default: local today)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between polls (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="JSONL log path (default: ./orderbook-EVENT.jsonl)",
    )
    parser.add_argument(
        "--chart",
        type=Path,
        default=None,
        help="Directory of one SVG per market (default: ./orderbook-EVENT-charts)",
    )
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="Do not write SVG charts",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=0,
        help="Order-book depth per side (0 = all levels)",
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=0,
        help="Give up after N waiting polls (0 = wait forever)",
    )
    parser.add_argument(
        "--max-dumps",
        type=int,
        default=0,
        help="Stop after N order-book dumps (0 = dump forever)",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize stdout (default: auto; TTY only). JSONL stays plain.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    urlopen_fn: UrlOpenFn | None = None,
    sleep_fn: SleepFn | None = None,
    clock_fn: ClockFn | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.interval < 0:
        print("--interval cannot be negative", file=sys.stderr)
        return 1
    if args.depth < 0:
        print("--depth cannot be negative", file=sys.stderr)
        return 1
    when: date | None = None
    if args.date:
        try:
            when = date.fromisoformat(args.date)
        except ValueError:
            print("--date must be YYYY-MM-DD", file=sys.stderr)
            return 1
    ticker = mm.kalshi_event_ticker(args.event_ticker) if args.event_ticker else world_news_event_ticker(when)
    log_path = (args.log if args.log is not None else Path(f"orderbook-{ticker}.jsonl")).expanduser()
    if args.no_chart:
        chart_path: Path | None = None
    elif args.chart is not None:
        chart_path = args.chart.expanduser()
    else:
        chart_path = log_path.parent / f"{log_path.stem}-charts"
    try:
        return run_watch(
            ticker,
            interval=float(args.interval),
            log_path=log_path,
            chart_path=chart_path,
            depth=int(args.depth),
            max_wait=int(args.max_wait),
            max_dumps=int(args.max_dumps),
            color_mode=str(args.color),
            urlopen_fn=urlopen_fn,
            sleep_fn=sleep_fn,
            clock_fn=clock_fn,
        )
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 0
    except mm.MentionMarketsError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
