"""Offline tests for MS-0018 --watch-new seen-ticker persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402


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
    assert payload["version"] == 1
    assert payload["tickers"] == ["KXMTPMENTION-26SEP20", "KXWORLDNEWSMENTION-26SEP25"]
    assert path.stat().st_mode & 0o777 == 0o600


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
