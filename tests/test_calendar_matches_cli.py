"""Offline unit tests for MS-0014 calendar-matches audit + add helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402

NY = ZoneInfo("America/New_York")


def _write_matches(
    path: Path,
    phrases: list,
    *,
    version: int = 1,
    default_time: str | None = None,
) -> Path:
    payload: dict = {"version": version, "phrases": phrases}
    if default_time is not None:
        payload["default_time"] = default_time
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _args(**overrides):
    base = {
        "calendar_matches": Path("matches.json"),
        "timezone": "America/New_York",
        "email_on_fail": True,
        "email_to": "owner@example.com",
        "email_from": "owner@example.com",
        "smtp_server": "smtp.example.com:587",
        "smtp_auth_user": "owner@example.com",
        "google_password_file": Path("/tmp/fake-google-password"),
        "verbose": False,
        "match": None,
        "match_time": None,
        "match_duration_minutes": None,
        "dry_run": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_audit_ok_no_email(tmp_path: Path, capsys) -> None:
    path = _write_matches(
        tmp_path / "m.json",
        ["plain show", {"match": "abc world news tonight", "time": "18:30", "duration_minutes": 30}],
        default_time="19:00",
    )
    swaks = []
    with patch.object(scout, "run_swaks_email", side_effect=lambda **kw: swaks.append(kw)):
        code = scout.run_audit_calendar_matches(_args(calendar_matches=path))
    assert code == 0
    out = capsys.readouterr().out
    assert "calendar-matches audit ok" in out
    assert "phrases: 2" in out
    assert "default_time: 19:00" in out
    assert str(path.resolve()) in out or str(path) in out
    assert swaks == []


def test_audit_bad_json_emails_once(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"version": 1, "phrases": ["a",]}\n', encoding="utf-8")
    swaks = []

    def _swaks(**kwargs):
        swaks.append(kwargs)

    with (
        patch.object(scout, "verify_email_configuration", return_value="secret-password-value"),
        patch.object(scout, "run_swaks_email", side_effect=_swaks),
    ):
        code = scout.run_audit_calendar_matches(_args(calendar_matches=path, email_on_fail=True))
    assert code == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert len(swaks) == 1
    assert swaks[0]["subject"] == "[Kalshi] FAIL | calendar-matches audit"
    assert "calendar-matches audit" in swaks[0]["subject"]
    assert "FAIL" in swaks[0]["subject"]
    body = swaks[0]["body"]
    assert "AUDIT FAILURE" in body
    assert "not valid JSON" in body
    assert "secret-password-value" not in body
    assert str(path) in body or path.name in body


def test_audit_bad_schema_no_email_flag(tmp_path: Path) -> None:
    path = _write_matches(
        tmp_path / "m.json",
        [{"match": "x", "time": "25:00"}],
    )
    swaks = []
    with patch.object(scout, "run_swaks_email", side_effect=lambda **kw: swaks.append(kw)):
        code = scout.run_audit_calendar_matches(_args(calendar_matches=path, email_on_fail=False))
    assert code == 1
    assert swaks == []


def test_audit_missing_file(tmp_path: Path, capsys) -> None:
    path = tmp_path / "missing.json"
    swaks = []
    with (
        patch.object(scout, "verify_email_configuration", return_value="pw"),
        patch.object(scout, "run_swaks_email", side_effect=lambda **kw: swaks.append(kw)),
    ):
        code = scout.run_audit_calendar_matches(_args(calendar_matches=path, email_on_fail=True))
    assert code == 1
    assert "missing" in capsys.readouterr().err.casefold()
    assert len(swaks) == 1


def test_audit_mail_skip_when_password_missing(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    swaks = []
    with (
        patch.object(
            scout,
            "verify_email_configuration",
            side_effect=RuntimeError("GOOGLE_PASSWORD was not set"),
        ),
        patch.object(scout, "run_swaks_email", side_effect=lambda **kw: swaks.append(kw)),
    ):
        code = scout.run_audit_calendar_matches(_args(calendar_matches=path, email_on_fail=True))
    assert code == 1
    err = capsys.readouterr().err
    assert "audit FAIL email skipped" in err
    assert swaks == []


def test_add_creates_string_phrase_file(tmp_path: Path) -> None:
    path = tmp_path / "cfg" / "calendar-matches.json"
    config, action, phrase = scout.add_calendar_match(path, match="cnn this morning")
    assert action == "created-file"
    assert phrase.match == "cnn this morning"
    assert phrase.time is None
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"version": 1, "phrases": ["cnn this morning"]}
    assert "default_time" not in payload
    loaded = scout.load_calendar_match_config(path)
    assert loaded.phrase_matches() == ["cnn this morning"]
    assert config.phrases == loaded.phrases


def test_add_object_phrase_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    _write_matches(path, ["keep me"], default_time="18:30")
    config, action, phrase = scout.add_calendar_match(
        path,
        match="abc world news tonight",
        time="18:30",
        duration_minutes=30,
    )
    assert action == "added"
    assert phrase.time is not None and phrase.time.label() == "18:30"
    assert phrase.duration_minutes == 30
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["default_time"] == "18:30"
    assert payload["phrases"][0] == "keep me"
    assert payload["phrases"][1] == {
        "match": "abc world news tonight",
        "time": "18:30",
        "duration_minutes": 30,
    }
    loaded = scout.load_calendar_match_config(path)
    assert [p.match for p in loaded.phrases] == ["keep me", "abc world news tonight"]
    assert config.default_time is not None


def test_add_preserves_order_and_default_time(tmp_path: Path) -> None:
    path = _write_matches(
        tmp_path / "m.json",
        ["alpha", {"match": "beta", "time": "10:00"}, "gamma"],
        default_time="07:15",
    )
    scout.add_calendar_match(path, match="delta")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["default_time"] == "07:15"
    assert payload["phrases"] == [
        "alpha",
        {"match": "beta", "time": "10:00"},
        "gamma",
        "delta",
    ]


def test_add_duplicate_casefold_update(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["ABC"])
    config, action, phrase = scout.add_calendar_match(
        path,
        match="abc",
        time="19:00",
    )
    assert action == "updated"
    assert phrase.match == "ABC"
    assert phrase.time is not None and phrase.time.label() == "19:00"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["phrases"] == [{"match": "ABC", "time": "19:00"}]
    assert len(config.phrases) == 1


def test_add_already_present_no_write(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["Same Phrase"])
    before = path.read_text(encoding="utf-8")
    mtime_before = path.stat().st_mtime_ns
    config, action, phrase = scout.add_calendar_match(path, match="same phrase")
    assert action == "already-present"
    assert phrase.match == "Same Phrase"
    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime_ns == mtime_before
    assert len(config.phrases) == 1


def test_add_refuses_invalid_existing(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    original = '{"version": 1, "phrases": [}\n'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to modify invalid"):
        scout.add_calendar_match(path, match="new")
    assert path.read_text(encoding="utf-8") == original


def test_add_dry_run_no_write(tmp_path: Path) -> None:
    path = tmp_path / "new.json"
    config, action, phrase = scout.add_calendar_match(
        path,
        match="preview only",
        time="12:00",
        dry_run=True,
    )
    assert action == "created-file"
    assert phrase.match == "preview only"
    assert not path.exists()
    assert len(config.phrases) == 1


def test_add_update_preserves_unspecified_duration(tmp_path: Path) -> None:
    path = _write_matches(
        tmp_path / "m.json",
        [{"match": "show", "time": "18:00", "duration_minutes": 45}],
    )
    _, action, phrase = scout.add_calendar_match(path, match="show", time="19:30")
    assert action == "updated"
    assert phrase.time is not None and phrase.time.label() == "19:30"
    assert phrase.duration_minutes == 45


def test_format_audit_fail_email_no_secrets() -> None:
    subject, body = scout.format_calendar_matches_audit_fail_email(
        path=Path("/tmp/calendar-matches.json"),
        error="boom secret-token-should-not-matter",
        detected_at=scout.datetime.now(scout.timezone.utc),
        local_tz=NY,
    )
    assert subject == "[Kalshi] FAIL | calendar-matches audit"
    assert "AUDIT FAILURE" in body
    assert "Schema reminder" in body
    assert "MS-0014" in body
    assert "MS-0012" in body
    assert scout.VERSION in body


def test_cli_help_lists_audit_and_add() -> None:
    help_text = scout.build_parser().format_help()
    assert "--audit-calendar-matches" in help_text
    assert "--add-calendar-match" in help_text
    assert "--match" in help_text
    assert "--email-on-fail" in help_text
    assert "--no-email-on-fail" in help_text
    assert "--dry-run" in help_text


def test_watch_child_strips_audit_add_flags() -> None:
    child = scout._watch_child_arguments(
        [
            "--watch-new",
            "--audit-calendar-matches",
            "--add-calendar-match",
            "--match",
            "foo",
            "--time",
            "18:30",
            "--duration-minutes",
            "30",
            "--dry-run",
            "--email-on-fail",
            "--no-email-on-fail",
            "--type",
            "wnt",
        ]
    )
    joined = " ".join(child)
    assert "--audit-calendar-matches" not in child
    assert "--add-calendar-match" not in child
    assert "--match" not in child
    assert "foo" not in child
    assert "--time" not in child
    assert "18:30" not in child
    assert "--duration-minutes" not in child
    assert "30" not in joined.split()
    assert "--dry-run" not in child
    assert "--email-on-fail" not in child
    assert "--no-email-on-fail" not in child
    assert "--type" in child
    assert "wnt" in child


def test_main_audit_ok(tmp_path: Path, capsys) -> None:
    path = _write_matches(tmp_path / "m.json", ["ok phrase"])
    old = sys.argv
    try:
        sys.argv = [
            "mention_scout.py",
            "--audit-calendar-matches",
            "--calendar-matches",
            str(path),
            "--no-email-on-fail",
        ]
        with patch.object(scout, "run_swaks_email") as swaks:
            code = scout.main()
        assert code == 0
        assert swaks.call_count == 0
    finally:
        sys.argv = old
    assert "audit ok" in capsys.readouterr().out


def test_main_add_conflict_with_watch() -> None:
    old = sys.argv
    try:
        sys.argv = [
            "mention_scout.py",
            "--add-calendar-match",
            "--match",
            "x",
            "--watch-new",
        ]
        with pytest.raises(SystemExit, match="one-shot"):
            scout.main()
    finally:
        sys.argv = old


def test_main_audit_conflict_with_add() -> None:
    old = sys.argv
    try:
        sys.argv = [
            "mention_scout.py",
            "--audit-calendar-matches",
            "--add-calendar-match",
            "--match",
            "x",
        ]
        with pytest.raises(SystemExit, match="cannot be combined"):
            scout.main()
    finally:
        sys.argv = old


def test_main_add_requires_match() -> None:
    old = sys.argv
    try:
        sys.argv = ["mention_scout.py", "--add-calendar-match"]
        with pytest.raises(SystemExit, match="requires --match"):
            scout.main()
    finally:
        sys.argv = old


def test_main_match_without_add_fails() -> None:
    old = sys.argv
    try:
        sys.argv = ["mention_scout.py", "--match", "solo"]
        with pytest.raises(SystemExit, match="only valid together with --add-calendar-match"):
            scout.main()
    finally:
        sys.argv = old


def test_main_email_on_fail_without_audit_fails() -> None:
    old = sys.argv
    try:
        sys.argv = ["mention_scout.py", "--email-on-fail"]
        with pytest.raises(SystemExit, match="only valid together with --audit-calendar-matches"):
            scout.main()
    finally:
        sys.argv = old


def test_main_add_dry_run(tmp_path: Path, capsys) -> None:
    path = tmp_path / "m.json"
    old = sys.argv
    try:
        sys.argv = [
            "mention_scout.py",
            "--add-calendar-match",
            "--match",
            "preview",
            "--time",
            "09:15",
            "--calendar-matches",
            str(path),
            "--dry-run",
        ]
        code = scout.main()
        assert code == 0
    finally:
        sys.argv = old
    out = capsys.readouterr().out
    assert "dry-run: not written" in out
    assert not path.exists()


def test_save_round_trip_atomic(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    config = scout.CalendarMatchConfig(
        phrases=(
            scout.CalendarPhrase(match="a"),
            scout.CalendarPhrase(
                match="b",
                time=scout.CalendarLocalTime(hour=1, minute=2),
                duration_minutes=15,
            ),
        ),
        default_time=scout.CalendarLocalTime(hour=8, minute=0),
    )
    scout.save_calendar_match_config(path, config)
    loaded = scout.load_calendar_match_config(path)
    assert loaded.default_time is not None and loaded.default_time.label() == "08:00"
    assert loaded.phrases[0].match == "a"
    assert loaded.phrases[1].duration_minutes == 15
    assert path.stat().st_mode & 0o777 == 0o600
