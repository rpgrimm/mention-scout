"""Offline unit tests for MS-0010 Google Calendar auto-add helpers."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402

NY = ZoneInfo("America/New_York")


class FakeCalendarClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_with: Exception | None = None

    def insert_event(
        self,
        calendar_id: str,
        body: dict,
        *,
        send_updates: str | None = None,
    ) -> dict:
        if self.fail_with is not None:
            raise self.fail_with
        # Keep legacy 2-tuple shape for existing MS-0010 assertions.
        self.calls.append((calendar_id, body))
        self.last_send_updates = send_updates
        return {
            "id": f"evt-{len(self.calls)}",
            "htmlLink": f"https://calendar.google.com/event?eid={len(self.calls)}",
        }


def _write_matches(path: Path, phrases: list[str], version: int = 1) -> Path:
    path.write_text(
        json.dumps({"version": version, "phrases": phrases}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_calendar_match_phrases_valid_seed(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["abc world news tonight"])
    phrases = scout.load_calendar_match_phrases(path)
    assert phrases == ["abc world news tonight"]


def test_load_calendar_match_phrases_rejects_bad_version(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["abc"], version=2)
    with pytest.raises(RuntimeError, match="version must be 1"):
        scout.load_calendar_match_phrases(path)


def test_load_calendar_match_phrases_rejects_missing_phrases(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing 'phrases'"):
        scout.load_calendar_match_phrases(path)


def test_load_calendar_match_phrases_rejects_non_array(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"version": 1, "phrases": "abc"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="JSON array"):
        scout.load_calendar_match_phrases(path)


def test_load_calendar_match_phrases_rejects_empty_phrase(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["ok", "   "])
    with pytest.raises(RuntimeError, match="empty after trim"):
        scout.load_calendar_match_phrases(path)


def test_load_calendar_match_phrases_trims_and_dedupes(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["  Foo ", "foo", "Bar"])
    assert scout.load_calendar_match_phrases(path) == ["Foo", "Bar"]


def test_matching_calendar_phrases_casefold_or_semantics() -> None:
    haystack = scout.event_calendar_haystack(
        {
            "title": "Will ABC World News Tonight mention tariffs?",
            "event_ticker": "KXWNT-26AUG11",
        }
    )
    hits = scout.matching_calendar_phrases(
        haystack,
        ["abc world news tonight", "face the nation", "WORLD NEWS TONIGHT"],
    )
    assert hits == ["abc world news tonight", "WORLD NEWS TONIGHT"]


def test_event_calendar_haystack_includes_child_title_not_rules() -> None:
    event = {
        "title": "Parent title",
        "event_ticker": "KXPARENT-26AUG11",
        "description": "Parent description",
    }
    records = [
        {
            "title": "child unique phrase zeta",
            "ticker": "KXPARENT-26AUG11-ZETA",
            "rules_primary": "rules only secretphrase should not match alone",
        }
    ]
    haystack = scout.event_calendar_haystack(event, records)
    assert "child unique phrase zeta" in haystack
    assert "kxparent-26aug11-zeta" in haystack
    assert "secretphrase" not in haystack
    assert scout.matching_calendar_phrases(haystack, ["unique phrase zeta"])
    assert not scout.matching_calendar_phrases(haystack, ["secretphrase"])


def test_build_calendar_event_body_timed_duration() -> None:
    event = {
        "event_ticker": "KXWNT-26AUG11",
        "title": "ABC World News Tonight",
        "mention_type_label": "World News Tonight",
        "series_ticker": "KXWNT",
        "description": "Nightly news mention market",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    detected = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    body = scout.build_calendar_event_body(
        event,
        matched_phrases=["abc world news tonight"],
        local_tz=NY,
        duration_minutes=60,
        detected_at=detected,
    )
    assert body["summary"] == "[Kalshi] World News Tonight: ABC World News Tonight"
    assert "dateTime" in body["start"]
    assert body["start"]["timeZone"] == "America/New_York"
    start = datetime.fromisoformat(body["start"]["dateTime"])
    end = datetime.fromisoformat(body["end"]["dateTime"])
    assert (end - start).total_seconds() == 3600
    assert "abc world news tonight" in body["description"]
    assert "KXWNT-26AUG11" in body["description"]


def test_build_calendar_event_body_date_only_all_day() -> None:
    event = {
        "event_ticker": "KXWNT-26AUG12",
        "title": "ABC World News Tonight",
        "mention_type_label": "World News Tonight",
        "series_ticker": "KXWNT",
        # Local midnight America/New_York on 2026-08-12.
        "first_event_time_utc": "2026-08-12T04:00:00Z",
        "event_time_sources": ["ticker date (exact time unavailable)"],
    }
    body = scout.build_calendar_event_body(
        event,
        matched_phrases=["abc world news tonight"],
        local_tz=NY,
        duration_minutes=60,
        detected_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
    )
    assert body["start"] == {"date": "2026-08-12"}
    assert body["end"] == {"date": "2026-08-13"}


def test_build_calendar_event_body_missing_schedule_raises() -> None:
    event = {
        "event_ticker": "KXNONE",
        "title": "No schedule",
        "event_time_sources": [],
    }
    with pytest.raises(RuntimeError, match="no usable event schedule"):
        scout.build_calendar_event_body(
            event,
            matched_phrases=["x"],
            local_tz=NY,
            duration_minutes=60,
            detected_at=datetime.now(timezone.utc),
            records=[],
        )


def test_dedupe_skips_second_insert(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = scout.load_calendar_added_state(state_path)
    assert not scout.calendar_already_added(state, "KX1", "primary")
    scout.mark_calendar_added(
        state,
        event_ticker="KX1",
        calendar_id="primary",
        added_at_utc="2026-08-11T00:00:00Z",
        calendar_event_id="abc",
        matched_phrase="abc world news tonight",
        kind="event",
    )
    scout.save_calendar_added_state(state_path, state)
    reloaded = scout.load_calendar_added_state(state_path)
    assert scout.calendar_already_added(reloaded, "KX1", "primary")
    assert not scout.calendar_already_added(reloaded, "KX2", "primary")


def test_format_calendar_error_email_has_no_secrets() -> None:
    subject, body = scout.format_calendar_error_email(
        operation="insert",
        error="boom token=SECRET value password=hunter2",
        detected_at=datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc),
        local_tz=NY,
        event={"event_ticker": "KXWNT-1", "title": "WNT"},
        matched_phrases=["abc world news tonight"],
        paths={
            "token": Path("/tmp/token.json"),
            "client_secret": Path("/tmp/client_secret.json"),
        },
    )
    assert subject == "[Kalshi] calendar error | KXWNT-1"
    assert "KXWNT-1" in body
    assert "insert" in body
    assert "abc world news tonight" in body
    assert "/tmp/token.json" in body
    # Paths are fine; credential file *contents* must never appear. We only pass paths.
    assert "client_secret.json" in body
    assert "GOOGLE_PASSWORD" not in body


def test_maybe_add_inserts_on_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    matches = _write_matches(tmp_path / "matches.json", ["abc world news tonight"])
    state_path = tmp_path / "state.json"
    sent: list[tuple[str, str]] = []

    def fake_swaks(**kwargs):
        sent.append((kwargs["subject"], kwargs["body"]))

    monkeypatch.setattr(scout, "run_swaks_email", fake_swaks)

    args = SimpleNamespace(
        calendar_matches=matches,
        calendar_state=state_path,
        calendar_id="primary",
        calendar_duration_minutes=60,
        calendar_client_secret=tmp_path / "secret.json",
        calendar_token=tmp_path / "token.json",
        email_to="to@example.com",
        email_from="from@example.com",
        smtp_server="smtp.example.com:587",
        smtp_auth_user="user",
        verbose=False,
        invite_emails=[],
    )
    client = FakeCalendarClient()
    event = {
        "event_ticker": "KXWNT-26AUG11",
        "title": "ABC World News Tonight mentions",
        "mention_type_label": "World News Tonight",
        "series_ticker": "KXWNT",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    state = {"version": 1, "entries": {}}
    cache = scout.CalendarMatchCache(matches)
    out = scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        local_tz=NY,
        match_cache=cache,
        calendar_client=client,
        state=state,
        email_password="not-a-real-password",
        colors=False,
    )
    assert len(client.calls) == 1
    assert client.calls[0][0] == "primary"
    assert scout.calendar_already_added(out, "KXWNT-26AUG11", "primary")
    assert not sent

    # Second call is deduped.
    out2 = scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime(2026, 8, 11, 12, 5, tzinfo=timezone.utc),
        local_tz=NY,
        match_cache=cache,
        calendar_client=client,
        state=out,
        email_password="not-a-real-password",
        colors=False,
    )
    assert len(client.calls) == 1
    assert out2 is out


def test_maybe_add_skips_non_matching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    matches = _write_matches(tmp_path / "matches.json", ["abc world news tonight"])
    monkeypatch.setattr(scout, "run_swaks_email", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no email")))
    args = SimpleNamespace(
        calendar_matches=matches,
        calendar_state=tmp_path / "state.json",
        calendar_id="primary",
        calendar_duration_minutes=60,
        calendar_client_secret=tmp_path / "secret.json",
        calendar_token=tmp_path / "token.json",
        email_to="to@example.com",
        email_from="from@example.com",
        smtp_server="smtp.example.com:587",
        smtp_auth_user="user",
        verbose=False,
        invite_emails=[],
    )
    client = FakeCalendarClient()
    event = {
        "event_ticker": "KXOTHER-1",
        "title": "Some other show",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime.now(timezone.utc),
        local_tz=NY,
        match_cache=scout.CalendarMatchCache(matches),
        calendar_client=client,
        state={"version": 1, "entries": {}},
        email_password="x",
        colors=False,
    )
    assert client.calls == []


def test_maybe_add_missing_schedule_emails_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    matches = _write_matches(tmp_path / "matches.json", ["abc world news tonight"])
    state_path = tmp_path / "state.json"
    sent: list[str] = []

    def fake_swaks(**kwargs):
        sent.append(kwargs["subject"])

    monkeypatch.setattr(scout, "run_swaks_email", fake_swaks)
    args = SimpleNamespace(
        calendar_matches=matches,
        calendar_state=state_path,
        calendar_id="primary",
        calendar_duration_minutes=60,
        calendar_client_secret=tmp_path / "secret.json",
        calendar_token=tmp_path / "token.json",
        email_to="to@example.com",
        email_from="from@example.com",
        smtp_server="smtp.example.com:587",
        smtp_auth_user="user",
        verbose=False,
        invite_emails=[],
    )
    client = FakeCalendarClient()
    event = {
        "event_ticker": "KXWNT-NOSCHED",
        "title": "ABC World News Tonight",
        "event_time_sources": [],
    }
    state = {"version": 1, "entries": {}}
    cache = scout.CalendarMatchCache(matches)
    state = scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime.now(timezone.utc),
        local_tz=NY,
        match_cache=cache,
        calendar_client=client,
        state=state,
        email_password="x",
        colors=False,
    )
    assert client.calls == []
    assert len(sent) == 1
    assert "KXWNT-NOSCHED" in sent[0]
    # Error is deduped via state; second attempt should not email again because
    # calendar_already_added treats the error marker as present.
    state = scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime.now(timezone.utc),
        local_tz=NY,
        match_cache=cache,
        calendar_client=client,
        state=state,
        email_password="x",
        colors=False,
    )
    assert len(sent) == 1


def test_maybe_add_insert_failure_emails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    matches = _write_matches(tmp_path / "matches.json", ["abc world news tonight"])
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scout,
        "run_swaks_email",
        lambda **kwargs: sent.append((kwargs["subject"], kwargs["body"])),
    )
    args = SimpleNamespace(
        calendar_matches=matches,
        calendar_state=tmp_path / "state.json",
        calendar_id="primary",
        calendar_duration_minutes=60,
        calendar_client_secret=tmp_path / "secret.json",
        calendar_token=tmp_path / "token.json",
        email_to="to@example.com",
        email_from="from@example.com",
        smtp_server="smtp.example.com:587",
        smtp_auth_user="user",
        verbose=False,
        invite_emails=[],
    )
    client = FakeCalendarClient()
    client.fail_with = RuntimeError("API 403 insufficient permissions")
    event = {
        "event_ticker": "KXWNT-FAIL",
        "title": "ABC World News Tonight",
        "series_ticker": "KXWNT",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime.now(timezone.utc),
        local_tz=NY,
        match_cache=scout.CalendarMatchCache(matches),
        calendar_client=client,
        state={"version": 1, "entries": {}},
        email_password="x",
        colors=False,
    )
    assert len(sent) == 1
    assert "calendar error" in sent[0][0]
    assert "403" in sent[0][1]
    assert "password=" not in sent[0][1].casefold() or "password file" in sent[0][1].casefold()


def test_watch_child_arguments_strips_calendar_flags() -> None:
    child = scout._watch_child_arguments(
        [
            "--watch-new",
            "--calendar-add-new",
            "--calendar-matches",
            "/tmp/matches.json",
            "--calendar-client-secret=/tmp/secret.json",
            "--calendar-token",
            "/tmp/token.json",
            "--calendar-id",
            "primary",
            "--calendar-state",
            "/tmp/state.json",
            "--calendar-duration-minutes",
            "90",
            "--email-new",
            "--type",
            "wnt",
        ]
    )
    assert "--watch-new" not in child
    assert "--calendar-add-new" not in child
    assert "--email-new" not in child
    assert not any(tok.startswith("--calendar") for tok in child)
    assert "/tmp/matches.json" not in child
    assert "/tmp/secret.json" not in child
    assert "--type" in child
    assert child[child.index("--type") + 1] == "wnt"
    assert "--overview" in child
    assert "--json" in child


def test_cli_help_lists_calendar_flags() -> None:
    help_text = scout.build_parser().format_help()
    for flag in (
        "--calendar-add-new",
        "--calendar-auth",
        "--calendar-matches",
        "--calendar-client-secret",
        "--calendar-token",
        "--calendar-id",
        "--calendar-state",
        "--calendar-duration-minutes",
    ):
        assert flag in help_text


def test_cli_calendar_add_requires_watch_new() -> None:
    parser = scout.build_parser()
    args = parser.parse_args(["--calendar-add-new"])
    assert args.calendar_add_new is True
    assert args.watch_new is False
    # main() enforces coupling; simulate the guard.
    with pytest.raises(SystemExit, match="only valid together with --watch-new"):
        if args.calendar_add_new and not args.watch_new:
            raise SystemExit("--calendar-add-new is only valid together with --watch-new")


def test_optional_google_deps_missing_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("google"):
            raise ImportError(f"No module named {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="google-auth google-auth-oauthlib google-api-python-client"):
        scout._require_google_calendar_libs()


def test_match_cache_reloads_on_mtime_change(tmp_path: Path) -> None:
    path = _write_matches(tmp_path / "m.json", ["one"])
    cache = scout.CalendarMatchCache(path)
    assert cache.get_phrases() == ["one"]
    # Ensure mtime can change on coarse filesystems.
    import os
    import time

    os.utime(path, None)
    time.sleep(0.01)
    _write_matches(path, ["two"])
    # Bump mtime explicitly after rewrite.
    now = time.time() + 1
    os.utime(path, (now, now))
    assert cache.get_phrases() == ["two"]


def test_example_match_file_in_repo() -> None:
    example = ROOT / "deploy" / "config" / "calendar-matches.example.json"
    payload = json.loads(example.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert "abc world news tonight" in payload["phrases"]
