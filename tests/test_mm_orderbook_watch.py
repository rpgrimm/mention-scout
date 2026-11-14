"""Offline tests for mm-orderbook-watch (public GET only, no orders)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mm_orderbook_watch as watch  # noqa: E402


class FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class SequenceUrlOpen:
    def __init__(self, market_pages: list[dict], books: dict[str, dict]) -> None:
        self.market_pages = market_pages
        self.books = books
        self.calls: list[str] = []
        self.methods: list[str] = []
        self.market_i = 0

    def __call__(self, request: Request, timeout: float | None = None) -> FakeResponse:
        url = request.full_url
        method = request.get_method()
        self.calls.append(url)
        self.methods.append(method)
        assert method == "GET", method
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.elections.kalshi.com"
        if parsed.path.endswith("/orderbook"):
            ticker = parsed.path.rstrip("/").split("/")[-2]
            payload = self.books.get(
                ticker,
                {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
            )
            return FakeResponse(json.dumps(payload))
        assert parsed.path == "/trade-api/v2/markets"
        page = self.market_pages[min(self.market_i, len(self.market_pages) - 1)]
        self.market_i += 1
        return FakeResponse(json.dumps(page))


def _market(status: str, ticker: str = "KXWORLDNEWSMENTION-26NOV13-AI") -> dict:
    return {
        "ticker": ticker,
        "status": status,
        "yes_sub_title": "AI / Artificial Intelligence",
    }


def _book() -> dict:
    return {
        "orderbook_fp": {
            "yes_dollars": [["0.4000", "10.00"], ["0.4200", "100.00"]],
            "no_dollars": [["0.5500", "40.00"]],
        }
    }


def test_world_news_event_ticker_today_format() -> None:
    assert watch.world_news_event_ticker(date(2026, 11, 13)) == "KXWORLDNEWSMENTION-26NOV13"


def test_wait_then_dump_orderbook_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log_path = tmp_path / "book.jsonl"
    fake = SequenceUrlOpen(
        [
            {"markets": [_market("initialized")], "cursor": ""},
            {"markets": [_market("active")], "cursor": ""},
        ],
        {"KXWORLDNEWSMENTION-26NOV13-AI": _book()},
    )
    sleeps: list[float] = []
    code = watch.main(
        [
            "KXWORLDNEWSMENTION-26NOV13",
            "--interval",
            "0",
            "--log",
            str(log_path),
            "--max-wait",
            "5",
            "--max-dumps",
            "1",
        ],
        urlopen_fn=fake,
        sleep_fn=sleeps.append,
        clock_fn=lambda: datetime(2026, 11, 13, 18, 30, 1, tzinfo=timezone.utc),
    )
    assert code == 0
    assert fake.methods and all(method == "GET" for method in fake.methods)
    assert any(url.endswith("/orderbook") for url in fake.calls)
    assert all("/orders" not in url for url in fake.calls)
    captured = capsys.readouterr()
    assert "waiting for open" in captured.err
    assert "dumping order books" in captured.err
    assert "YES ask  tot 40.00" in captured.out
    assert "YES bid  tot 110.00" in captured.out
    assert "NO  ask  tot 110.00" in captured.out
    assert "NO  bid  tot 40.00" in captured.out
    assert "0.4500 x 40.00" in captured.out
    assert "0.4200 x 100.00  0.4000 x 10.00" in captured.out
    assert "0.5800 x 100.00  0.6000 x 10.00" in captured.out
    assert "\033[" not in captured.out
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_ticker"] == "KXWORLDNEWSMENTION-26NOV13"
    assert payload["open_count"] == 1
    market = payload["markets"][0]
    assert market["yes_bid"] == ["0.4200", "100.00"]
    assert market["yes_ask"] == ["0.4500", "40.00"]
    assert market["no_bid"] == ["0.5500", "40.00"]
    assert market["no_ask"] == ["0.5800", "100.00"]
    assert market["yes_bid_total"] == "110.00"
    assert market["yes_ask_total"] == "40.00"
    assert market["no_bid_total"] == "40.00"
    assert market["no_ask_total"] == "110.00"
    assert market["yes_spread"] == "0.0300"
    assert "spread  0.0300" in captured.out
    assert "\033" not in lines[0]
    charts = log_path.parent / f"{log_path.stem}-charts"
    svg_path = charts / "KXWORLDNEWSMENTION-26NOV13-AI.svg"
    svg = svg_path.read_text(encoding="utf-8")
    assert svg.startswith("<svg")
    assert "YES bid" in svg
    assert "YES price ($)" in svg
    assert "Spread ($)" in svg
    assert "Time (UTC)" not in svg
    assert f"Time ({watch.tz_abbrev()})" in svg
    assert "AI / Artificial Intelligence" in svg
    assert "circle" in svg or "polyline" in svg


def test_format_axis_time_uses_local_timezone() -> None:
    ny = ZoneInfo("America/New_York")
    assert watch.format_axis_time("2026-11-13T19:04:00Z", tz=ny) == "14:04"


def test_world_news_x_axis_five_minutes_until_19() -> None:
    ny = ZoneInfo("America/New_York")
    samples = [{"ts": "2026-11-13T19:04:00Z"}]
    start, end = watch.time_window(samples, "KXWORLDNEWSMENTION-26NOV13", ny)
    assert start.strftime("%H:%M") == "14:04"
    assert end.strftime("%H:%M") == "19:00"
    ticks = watch.five_minute_ticks(start, end)
    assert ticks[0].strftime("%H:%M") == "14:04"
    assert ticks[1].strftime("%H:%M") == "14:05"
    assert ticks[-1].strftime("%H:%M") == "19:00"
    other_start, other_end = watch.time_window(samples, "KXMTPMENTION-26NOV13", ny)
    assert other_start.strftime("%H:%M") == "14:04"
    assert other_end.strftime("%H:%M") == "14:05"
    odd = watch.five_minute_ticks(
        datetime(2026, 11, 14, 10, 39, 20, tzinfo=ny),
        datetime(2026, 11, 14, 19, 0, tzinfo=ny),
    )
    assert [t.strftime("%H:%M") for t in odd[:4]] == ["10:39", "10:40", "10:45", "10:50"]
    minutes = watch.minute_ticks(
        datetime(2026, 11, 14, 10, 39, tzinfo=ny),
        datetime(2026, 11, 14, 10, 45, tzinfo=ny),
    )
    assert [t.strftime("%H:%M") for t in minutes] == [
        "10:39",
        "10:40",
        "10:41",
        "10:42",
        "10:43",
        "10:44",
        "10:45",
    ]
    svg = watch.render_market_svg(
        "KXWORLDNEWSMENTION-26NOV13-AI",
        {
            "word": "AI",
            "samples": [
                {
                    "ts": "2026-11-13T19:04:00Z",
                    "yes_bid": Decimal("0.4200"),
                    "yes_ask": Decimal("0.4500"),
                    "spread": Decimal("0.0300"),
                }
            ],
        },
        "KXWORLDNEWSMENTION-26NOV13",
        tz=ny,
    )
    assert "14:04" in svg
    assert "14:05" in svg
    assert "19:00" in svg
    assert "14:00" not in svg
    assert "14:04:00" not in svg
    minute_lines = svg.count(f'stroke="{watch.CHART_MINUTE_GRID}"')
    assert minute_lines == 2 * len(watch.minute_ticks(start, end))
    assert minute_lines > 2 * len(ticks)


def test_complement_asks_are_one_minus_bid() -> None:
    bids = [(Decimal("0.4200"), "100.00"), (Decimal("0.4000"), "10.00")]
    asks = watch.complement_asks(bids)
    assert asks[0] == (Decimal("0.5800"), "100.00")
    assert asks[1] == (Decimal("0.6000"), "10.00")


def test_still_initialized_exits_after_max_wait(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = SequenceUrlOpen(
        [{"markets": [_market("initialized")], "cursor": ""}],
        {},
    )
    code = watch.main(
        [
            "kxworldnewsmention-26nov13",
            "--interval",
            "0",
            "--log",
            str(tmp_path / "x.jsonl"),
            "--max-wait",
            "2",
        ],
        urlopen_fn=fake,
        sleep_fn=lambda _s: None,
    )
    assert code == 1
    assert "still not open" in capsys.readouterr().err
    assert not any(url.endswith("/orderbook") for url in fake.calls)


def test_default_ticker_from_date(tmp_path: Path) -> None:
    fake = SequenceUrlOpen(
        [{"markets": [_market("open")], "cursor": ""}],
        {"KXWORLDNEWSMENTION-26NOV13-AI": _book()},
    )
    code = watch.main(
        [
            "--date",
            "2026-11-13",
            "--interval",
            "0",
            "--log",
            str(tmp_path / "y.jsonl"),
            "--max-dumps",
            "1",
        ],
        urlopen_fn=fake,
        sleep_fn=lambda _s: None,
    )
    assert code == 0
    assert "event_ticker=KXWORLDNEWSMENTION-26NOV13" in fake.calls[0]


def test_history_chart_polyline_over_time(tmp_path: Path) -> None:
    history: dict[str, dict] = {}
    first = {
        "ts": "2026-11-13T18:30:01Z",
        "markets": [
            {
                "ticker": "KXWORLDNEWSMENTION-26NOV13-AI",
                "word": "AI / Artificial Intelligence",
                "yes_bid": ["0.4200", "100.00"],
                "yes_ask": ["0.4500", "40.00"],
                "yes_bid_total": "110.00",
                "yes_ask_total": "40.00",
            }
        ],
    }
    second = {
        "ts": "2026-11-13T18:30:02Z",
        "markets": [
            {
                "ticker": "KXWORLDNEWSMENTION-26NOV13-AI",
                "word": "AI / Artificial Intelligence",
                "yes_bid": ["0.4300", "80.00"],
                "yes_ask": ["0.5000", "50.00"],
                "yes_bid_total": "90.00",
                "yes_ask_total": "50.00",
            }
        ],
    }
    watch.append_history(history, first)
    watch.append_history(history, second)
    ticker = "KXWORLDNEWSMENTION-26NOV13-AI"
    svg = watch.render_market_svg(ticker, history[ticker], "KXWORLDNEWSMENTION-26NOV13")
    assert "polyline" in svg
    assert "#5ce1ff" in svg
    assert "#ffd15c" in svg
    assert "#ff79c6" in svg
    assert "polygon" in svg
    assert "YES price ($)" in svg
    assert "Spread ($)" in svg
    assert history[ticker]["samples"][0]["spread"] == Decimal("0.0300")
    assert history[ticker]["samples"][1]["spread"] == Decimal("0.0700")
    assert "Time (UTC)" not in svg
    ny = ZoneInfo("America/New_York")
    svg_ny = watch.render_market_svg(ticker, history[ticker], "KXWORLDNEWSMENTION-26NOV13", tz=ny)
    assert "13:30" in svg_ny
    assert "13:35" in svg_ny
    assert "19:00" in svg_ny
    assert "13:30:01" not in svg_ny
    assert "Time (EST)" in svg_ny
    assert watch.format_axis_time("2026-11-13T18:30:01Z") in svg
    assert watch.format_axis_time("2026-11-13T18:30:02Z") in svg
    assert "bid tot 90.00" in svg
    chart_dir = tmp_path / "charts"
    written = watch.write_history_charts(chart_dir, history, "KXWORLDNEWSMENTION-26NOV13")
    assert written == [chart_dir / "KXWORLDNEWSMENTION-26NOV13-AI.svg"]
    assert written[0].read_text(encoding="utf-8") == svg
    assert not (chart_dir / "KXWORLDNEWSMENTION-26NOV13-AI.svg.tmp").exists()


def test_help_and_version() -> None:
    with pytest.raises(SystemExit) as help_exc:
        watch.main(["--help"])
    assert help_exc.value.code == 0
    with pytest.raises(SystemExit) as version_exc:
        watch.main(["--version"])
    assert version_exc.value.code == 0


def test_color_always_paints_yes_no_bid_ask(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = SequenceUrlOpen(
        [{"markets": [_market("open")], "cursor": ""}],
        {"KXWORLDNEWSMENTION-26NOV13-AI": _book()},
    )
    code = watch.main(
        [
            "KXWORLDNEWSMENTION-26NOV13",
            "--color",
            "always",
            "--interval",
            "0",
            "--log",
            str(tmp_path / "c.jsonl"),
            "--max-dumps",
            "1",
        ],
        urlopen_fn=fake,
        sleep_fn=lambda _s: None,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert watch.GREEN in out
    assert watch.RED in out
    assert watch.YELLOW in out
    assert watch.CYAN in out
    assert watch.REVERSE in out
    assert "YES" in out
    assert "tot 110.00" in out
