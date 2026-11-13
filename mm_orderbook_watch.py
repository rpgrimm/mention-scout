#!/usr/bin/env python3
"""Poll a Kalshi event until markets open, then dump public order books.

Discovery only. Never places, modifies, or cancels orders. Public GET only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO
from urllib.parse import urlencode

import mention_markets as mm

VERSION = "1.0.0"
DEFAULT_INTERVAL = 1.0
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


def best_level(levels: Any) -> tuple[str, str] | None:
    """Kalshi books are ascending; the best bid is the last [price, size] pair."""
    if not isinstance(levels, list) or not levels:
        return None
    last = levels[-1]
    if isinstance(last, (list, tuple)) and len(last) >= 2:
        return str(last[0]), str(last[1])
    return None


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


def summarize_market(market: Mapping[str, Any], book: Mapping[str, Any]) -> dict[str, Any]:
    fp = book.get("orderbook_fp") if isinstance(book.get("orderbook_fp"), dict) else {}
    yes_levels = fp.get("yes_dollars") if isinstance(fp, dict) else None
    no_levels = fp.get("no_dollars") if isinstance(fp, dict) else None
    ticker = str(market.get("ticker") or "").strip()
    return {
        "ticker": ticker,
        "status": str(market.get("status") or ""),
        "word": mm.market_word(dict(market)).strip(),
        "yes_best": best_level(yes_levels),
        "no_best": best_level(no_levels),
        "orderbook": book,
    }


def format_best(pair: tuple[str, str] | None) -> str:
    if pair is None:
        return "-"
    return f"{pair[0]} x {pair[1]}"


def print_snapshot(snapshot: Mapping[str, Any], *, file: TextIO | None = None) -> None:
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
            f"  {item.get('word') or '?'}  {item.get('ticker')}  "
            f"status={item.get('status')}  yes={format_best(item.get('yes_best'))}  "
            f"no={format_best(item.get('no_best'))}",
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
        print_snapshot(snapshot, file=out)
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
