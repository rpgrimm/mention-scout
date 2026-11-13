#!/usr/bin/env python3
"""Poll a Kalshi event until markets open, then dump public order books.

Discovery only. Never places, modifies, or cancels orders. Public GET only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO
from urllib.parse import urlencode

import mention_markets as mm

VERSION = "1.2.0"
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


def append_jsonl(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")


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
    opened = False
    wait_polls = 0
    dump_polls = 0
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
    log_path = args.log if args.log is not None else Path(f"orderbook-{ticker}.jsonl")
    try:
        return run_watch(
            ticker,
            interval=float(args.interval),
            log_path=log_path.expanduser(),
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
