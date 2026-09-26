"""Offline tests for MS-0018 --watch-new seen-ticker persistence."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)


def test_default_watch_seen_path_uses_xdg_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert scout.default_watch_seen_path() == tmp_path / "state" / "mention-scout" / "seen-event-tickers.json"


def test_default_watch_seen_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(scout.Path, "home", staticmethod(lambda: tmp_path))
    assert scout.default_watch_seen_path() == tmp_path / ".local" / "state" / "mention-scout" / "seen-event-tickers.json"


def test_load_missing_is_first_run(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    tickers, have_prior = scout.load_watch_seen_tickers(path)
    assert tickers == set()
    assert have_prior is False


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "seen-event-tickers.json"
    scout.save_watch_seen_tickers(path, {"KXWORLDNEWSMENTION-26SEP25", "KXMTPMENTION-26SEP20", ""})
    tickers, have_prior = scout.load_watch_seen_tickers(path)
    assert have_prior is True
    assert tickers == {"KXWORLDNEWSMENTION-26SEP25", "KXMTPMENTION-26SEP20"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert set(payload["entries"]) == {"KXMTPMENTION-26SEP20", "KXWORLDNEWSMENTION-26SEP25"}
    assert payload["entries"]["KXWORLDNEWSMENTION-26SEP25"]["baselined"] is True
    assert payload["entries"]["KXWORLDNEWSMENTION-26SEP25"]["alert_sent"] is False
    assert path.stat().st_mode & 0o777 == 0o600


def test_load_v1_tickers_become_baselined(tmp_path: Path) -> None:
    path = tmp_path / "seen-event-tickers.json"
    path.write_text(
        json.dumps({"version": 1, "tickers": ["KXWORLDNEWSMENTION-26SEP24"]}) + "\n",
        encoding="utf-8",
    )
    entries, have_prior = scout.load_watch_seen_state(path)
    assert have_prior is True
    assert entries["KXWORLDNEWSMENTION-26SEP24"].baselined is True
    assert entries["KXWORLDNEWSMENTION-26SEP24"].handled() is True
    assert entries["KXWORLDNEWSMENTION-26SEP24"].alert_sent is False


def test_load_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        scout.load_watch_seen_tickers(path)


def test_merge_first_run_baselines_without_new() -> None:
    known, new = scout.merge_watch_seen_tickers(
        ["B", "A"],
        set(),
        have_prior_state=False,
    )
    assert known == {"A", "B"}
    assert new == []


def test_merge_catch_up_only_unseen() -> None:
    known, new = scout.merge_watch_seen_tickers(
        ["A", "C", "B"],
        {"A"},
        have_prior_state=True,
    )
    assert known == {"A", "B", "C"}
    assert new == ["B", "C"]


def test_merge_keeps_disappeared_so_reappearance_is_not_new() -> None:
    known, new = scout.merge_watch_seen_tickers(
        ["B"],
        {"A", "B"},
        have_prior_state=True,
    )
    assert known == {"A", "B"}
    assert new == []
    known2, new2 = scout.merge_watch_seen_tickers(
        ["A", "B"],
        known,
        have_prior_state=True,
    )
    assert new2 == []
    assert known2 == {"A", "B"}


def test_watch_event_is_past_timed() -> None:
    future = {
        "first_event_time_utc": "2026-09-26T00:30:00Z",
        "event_time_sources": ["occurrence_datetime"],
    }
    past = {
        "first_event_time_utc": "2026-09-25T17:00:00Z",
        "event_time_sources": ["occurrence_datetime"],
    }
    assert scout.watch_event_is_past(future, [], now=NOW, local_tz=NY) is False
    assert scout.watch_event_is_past(past, [], now=NOW, local_tz=NY) is True


def test_watch_event_is_past_date_only_uses_local_date() -> None:
    today = {
        "first_event_time_utc": "2026-09-25T04:00:00Z",
        "event_time_sources": ["strike_date"],
    }
    yesterday = {
        "first_event_time_utc": "2026-09-24T04:00:00Z",
        "event_time_sources": ["strike_date"],
    }
    assert scout.watch_event_is_past(today, [], now=NOW, local_tz=NY) is False
    assert scout.watch_event_is_past(yesterday, [], now=NOW, local_tz=NY) is True


def test_watch_event_without_schedule_is_not_past() -> None:
    assert scout.watch_event_is_past({}, [], now=NOW, local_tz=NY) is False


def test_alert_sent_marks_handled() -> None:
    entry = scout.WatchSeenEntry(ticker="KXFOO", first_seen_utc="2026-09-25T00:00:00Z")
    assert entry.handled() is False
    entry.alert_sent = True
    entry.alert_sent_utc = "2026-09-25T20:00:00Z"
    assert entry.handled() is True
    skipped = scout.WatchSeenEntry(
        ticker="KXBAR",
        first_seen_utc="2026-09-25T00:00:00Z",
        skipped_past=True,
    )
    assert skipped.handled() is True
    assert skipped.alert_sent is False
