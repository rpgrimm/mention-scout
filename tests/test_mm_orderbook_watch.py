"""Offline tests for mm-orderbook-watch (public GET only, no orders)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
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
    assert "YES ask  0.4500 x 40.00" in captured.out
    assert "YES bid  0.4200 x 100.00  0.4000 x 10.00" in captured.out
    assert "NO  ask  0.5800 x 100.00  0.6000 x 10.00" in captured.out
    assert "NO  bid  0.5500 x 40.00" in captured.out
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


def test_help_and_version() -> None:
    with pytest.raises(SystemExit) as help_exc:
        watch.main(["--help"])
    assert help_exc.value.code == 0
    with pytest.raises(SystemExit) as version_exc:
        watch.main(["--version"])
    assert version_exc.value.code == 0
