"""Offline unit tests for MS-0016 mention_markets.py (no live Kalshi, no real browser)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mention_markets as mm  # noqa: E402


class FakeResponse:
    def __init__(self, body: str | bytes, status: int = 200) -> None:
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class FakeUrlOpen:
    def __init__(self, pages: dict[str, dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, request: Request, timeout: float | None = None) -> FakeResponse:
        url = request.full_url
        self.calls.append(url)
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.elections.kalshi.com"
        assert parsed.path == "/trade-api/v2/markets"
        qs = parse_qs(parsed.query)
        cursor = (qs.get("cursor") or [""])[0]
        if cursor not in self.pages:
            raise AssertionError(f"unexpected cursor {cursor!r} for {url}")
        return FakeResponse(json.dumps(self.pages[cursor]))


class RecordingOpener:
    def __init__(self, accepted: bool = True) -> None:
        self.urls: list[str] = []
        self.accepted = accepted

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        return self.accepted


def _write_calendar(path: Path, entries: dict[str, Any], *, version: int = 1) -> Path:
    payload: dict[str, Any] = {"version": version, "entries": entries}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _entry(added_at_utc: str, phrase: str = "abc world news tonight") -> dict[str, str]:
    return {
        "added_at_utc": added_at_utc,
        "kind": "event",
        "calendar_event_id": "evt",
        "html_link": "https://calendar.example/event",
        "matched_phrase": phrase,
    }


SAMPLE_ENTRIES = {
    "KXWORLDNEWSMENTION-26SEP25::primary": _entry("2026-09-25T17:29:37.185609Z"),
    "KXWORLDNEWSMENTION-26SEP24::primary": _entry("2026-09-24T17:29:42.571986Z"),
    "KXMTPMENTION-26SEP20::primary": _entry("2026-09-18T15:42:56.475973Z", "meet the press"),
}


def test_parse_calendar_keys_unique_latest_wins(tmp_path: Path) -> None:
    path = _write_calendar(
        tmp_path / "calendar-added.json",
        {
            "KXFOO-1::primary": _entry("2026-09-01T00:00:00Z", "old"),
            "KXFOO-1::other": _entry("2026-09-10T00:00:00Z", "new"),
            "KXBAR-1::primary": _entry("2026-09-05T00:00:00Z", "bar"),
        },
    )
    events = mm.load_listed_events(path)
    assert [e.ticker for e in events] == ["KXFOO-1", "KXBAR-1"]
    assert events[0].matched_phrase == "new"
    assert events[0].added_at_utc == "2026-09-10T00:00:00Z"


def test_ticker_from_key_strips_suffix() -> None:
    assert mm.ticker_from_key("KXWORLDNEWSMENTION-26SEP25::primary") == "KXWORLDNEWSMENTION-26SEP25"
    assert mm.ticker_from_key("  KXWORLDNEWSMENTION-26SEP25  ") == "KXWORLDNEWSMENTION-26SEP25"


def test_list_formatting_newest_first(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    assert mm.main(["list", "--json", str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("KXWORLDNEWSMENTION-26SEP25\t2026-09-25T17:29:37.185609Z\t")
    assert lines[1].startswith("KXWORLDNEWSMENTION-26SEP24\t")
    assert lines[2].startswith("KXMTPMENTION-26SEP20\t")
    assert all("\t" in line for line in lines)
    assert "KXWORLDNEWSMENTION-26SEP25" in lines[0]


def test_list_missing_file_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.json"
    assert mm.main(["list", "--json", str(missing)]) == 1
    err = capsys.readouterr().err
    assert "not found" in err
    assert str(missing) in err


def test_list_invalid_json_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert mm.main(["list", "--json", str(path)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_target_unknown_ticker_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()
    code = mm.main(
        ["target", "KXDOESNOTEXIST-26SEP25", "--json", str(path)],
        opener=opener,
        urlopen_fn=FakeUrlOpen({}),
        sleep_fn=lambda _s: None,
        environ={"DISPLAY": ":0"},
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "not found" in err
    assert "mention_markets.py list" in err
    assert opener.urls == []


@pytest.mark.parametrize(
    ("word", "query"),
    [
        ("Starbucks", "Starbucks news"),
        ("OpenAI / Anthropic", "OpenAI Anthropic news"),
        ("AI / Artificial Intelligence", "AI Artificial Intelligence news"),
        ("Iran (3+ times)", "Iran news"),
        ("Iran (3 times)", "Iran news"),
        (r"Foo \ Bar", "Foo Bar news"),
    ],
)
def test_google_news_query_cleaning(word: str, query: str) -> None:
    assert mm.google_news_query(word) == query


def test_market_word_prefers_slash_subtitle() -> None:
    market = {
        "ticker": "KXWORLDNEWSMENTION-26SEP25-OPENAI",
        "custom_strike": {"Word": "OpenAI"},
        "yes_sub_title": "OpenAI / Anthropic",
        "status": "active",
    }
    assert mm.market_word(market) == "OpenAI / Anthropic"


def _openai_pages() -> dict[str, dict[str, Any]]:
    return {
        "": {
            "markets": [
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-OPENAI",
                    "status": "active",
                    "yes_sub_title": "OpenAI / Anthropic",
                    "custom_strike": {"Word": "OpenAI"},
                },
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-STARBUCKS",
                    "status": "open",
                    "custom_strike": {"Word": "Starbucks"},
                },
            ],
            "cursor": "page2",
        },
        "page2": {
            "markets": [
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-IRAN",
                    "status": "active",
                    "yes_sub_title": "Iran (3+ times)",
                }
            ],
            "cursor": "",
        },
    }


def test_paginated_markets_open_one_tab_per_market(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()
    sleeps: list[float] = []
    fake_http = FakeUrlOpen(_openai_pages())
    code = mm.main(
        [
            "target",
            "kxworldnewsmention-26sep25::primary",
            "--action",
            "google-news",
            "--json",
            str(path),
            "--sleep",
            "0.15",
        ],
        opener=opener,
        urlopen_fn=fake_http,
        sleep_fn=sleeps.append,
        environ={"DISPLAY": ":0"},
    )
    assert code == 0
    assert len(fake_http.calls) == 2
    assert "event_ticker=KXWORLDNEWSMENTION-26SEP25" in fake_http.calls[0]
    assert "cursor=page2" in fake_http.calls[1]
    out_lines = capsys.readouterr().out.splitlines()
    words = [line.split("\t", 1)[0] for line in out_lines]
    assert words == ["Iran (3+ times)", "OpenAI / Anthropic", "Starbucks"]
    assert any("q=OpenAI+Anthropic+news" in line or "q=OpenAI%20Anthropic%20news" in line for line in out_lines)
    assert any("q=Starbucks+news" in line or "q=Starbucks%20news" in line for line in out_lines)
    assert any("q=Iran+news" in line or "q=Iran%20news" in line for line in out_lines)
    assert len(opener.urls) == 3
    assert opener.urls == [line.split("\t", 1)[1] for line in out_lines]
    assert sleeps == [0.15, 0.15]


def test_default_sleep_is_two_seconds(tmp_path: Path) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()
    sleeps: list[float] = []
    code = mm.main(
        ["target", "KXWORLDNEWSMENTION-26SEP25", "--json", str(path)],
        opener=opener,
        urlopen_fn=FakeUrlOpen(_openai_pages()),
        sleep_fn=sleeps.append,
        environ={"DISPLAY": ":0"},
    )
    assert code == 0
    assert mm.DEFAULT_SLEEP == 2.0
    assert sleeps == [2.0, 2.0]
    assert len(opener.urls) == 3


def test_dry_run_never_calls_opener(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()
    code = mm.main(
        [
            "target",
            "KXWORLDNEWSMENTION-26SEP25",
            "--dry-run",
            "--json",
            str(path),
        ],
        opener=opener,
        urlopen_fn=FakeUrlOpen(_openai_pages()),
        sleep_fn=lambda _s: None,
        environ={},
    )
    assert code == 0
    captured = capsys.readouterr()
    assert opener.urls == []
    assert "OpenAI / Anthropic" in captured.out
    assert "dry-run: 3 tabs" in captured.err
    assert "headless" not in captured.err


def test_inactive_unopened_markets_are_not_opened(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    pages = {
        "": {
            "markets": [
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-OPENAI",
                    "status": "active",
                    "yes_sub_title": "OpenAI / Anthropic",
                },
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-CLOSED",
                    "status": "closed",
                    "custom_strike": {"Word": "ClosedWord"},
                },
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-UNOPENED",
                    "status": "unopened",
                    "custom_strike": {"Word": "SoonWord"},
                },
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-INACTIVE",
                    "status": "inactive",
                    "custom_strike": {"Word": "InactiveWord"},
                },
            ],
            "cursor": "",
        }
    }
    opener = RecordingOpener()
    code = mm.main(
        ["target", "KXWORLDNEWSMENTION-26SEP25", "--json", str(path)],
        opener=opener,
        urlopen_fn=FakeUrlOpen(pages),
        sleep_fn=lambda _s: None,
        environ={"WAYLAND_DISPLAY": "wayland-0"},
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "OpenAI / Anthropic" in out
    assert "ClosedWord" not in out
    assert "SoonWord" not in out
    assert "InactiveWord" not in out
    assert len(opener.urls) == 1


def test_empty_open_markets_exits_1_without_opening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()
    pages = {
        "": {
            "markets": [
                {
                    "ticker": "KXWORLDNEWSMENTION-26SEP25-CLOSED",
                    "status": "closed",
                    "custom_strike": {"Word": "ClosedWord"},
                }
            ],
            "cursor": "",
        }
    }
    code = mm.main(
        ["target", "KXWORLDNEWSMENTION-26SEP25", "--json", str(path)],
        opener=opener,
        urlopen_fn=FakeUrlOpen(pages),
        sleep_fn=lambda _s: None,
        environ={"DISPLAY": ":0"},
    )
    assert code == 1
    assert opener.urls == []
    assert "No active/open mention markets" in capsys.readouterr().err


def test_unknown_action_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()
    code = mm.main(
        ["target", "KXWORLDNEWSMENTION-26SEP25", "--action", "trade", "--json", str(path)],
        opener=opener,
        urlopen_fn=FakeUrlOpen(_openai_pages()),
        sleep_fn=lambda _s: None,
        environ={"DISPLAY": ":0"},
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "Unknown action 'trade'" in err
    assert "google-news" in err
    assert opener.urls == []


def test_http_error_no_browser(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_calendar(tmp_path / "calendar-added.json", SAMPLE_ENTRIES)
    opener = RecordingOpener()

    def boom(request: Request, timeout: float | None = None) -> FakeResponse:
        raise HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b"missing"))

    code = mm.main(
        ["target", "KXWORLDNEWSMENTION-26SEP25", "--json", str(path)],
        opener=opener,
        urlopen_fn=boom,
        sleep_fn=lambda _s: None,
        environ={"DISPLAY": ":0"},
    )
    assert code == 1
    assert opener.urls == []
    assert "HTTP 404" in capsys.readouterr().err


def test_help_and_version() -> None:
    with pytest.raises(SystemExit) as help_exc:
        mm.main(["--help"])
    assert help_exc.value.code == 0
    with pytest.raises(SystemExit) as version_exc:
        mm.main(["--version"])
    assert version_exc.value.code == 0
