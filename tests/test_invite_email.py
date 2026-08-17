"""Offline unit tests for MS-0013 calendar --invite-email attendees."""

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
        self.calls: list[tuple[str, dict, str | None]] = []
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
        self.calls.append((calendar_id, body, send_updates))
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


def test_validate_email_address_accepts_normal() -> None:
    assert scout.validate_email_address("  partner@gmail.com ") == "partner@gmail.com"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "no-at", "a@b", "a b@c.com", "a@b.com,x", "a@b..com", "@x.com", "a@"],
)
def test_validate_email_address_rejects(bad: str) -> None:
    with pytest.raises(RuntimeError, match="invalid --invite-email"):
        scout.validate_email_address(bad)


def test_normalize_invite_emails_dedupes_casefold_order() -> None:
    assert scout.normalize_invite_emails(
        [" Alice@Gmail.com ", "bob@example.com", "alice@gmail.com", "Carol@X.org"]
    ) == ["Alice@Gmail.com", "bob@example.com", "Carol@X.org"]


def test_normalize_invite_emails_empty() -> None:
    assert scout.normalize_invite_emails(None) == []
    assert scout.normalize_invite_emails([]) == []


def test_normalize_invite_emails_max_cap() -> None:
    addrs = [f"u{i}@example.com" for i in range(scout.MAX_INVITE_EMAILS + 1)]
    with pytest.raises(RuntimeError, match="at most"):
        scout.normalize_invite_emails(addrs)


def test_build_calendar_event_body_with_attendees() -> None:
    event = {
        "event_ticker": "KXWNT-26AUG11",
        "title": "ABC World News Tonight",
        "mention_type_label": "World News Tonight",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    body = scout.build_calendar_event_body(
        event,
        matched_phrases=["abc world news tonight"],
        local_tz=NY,
        duration_minutes=60,
        detected_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        invite_emails=["partner@gmail.com", "other@example.com"],
    )
    assert body["attendees"] == [
        {"email": "partner@gmail.com"},
        {"email": "other@example.com"},
    ]
    # Description must not auto-list invite roster (API attendees only).
    assert "partner@gmail.com" not in body["description"]


def test_build_calendar_event_body_without_invites_omits_attendees() -> None:
    event = {
        "event_ticker": "KXWNT-26AUG11",
        "title": "ABC World News Tonight",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    body = scout.build_calendar_event_body(
        event,
        matched_phrases=["abc world news tonight"],
        local_tz=NY,
        duration_minutes=60,
        detected_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
    )
    assert "attendees" not in body


def test_maybe_add_passes_attendees_and_send_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matches = _write_matches(tmp_path / "matches.json", ["abc world news tonight"])
    monkeypatch.setattr(
        scout,
        "run_swaks_email",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("no SMTP fan-out")),
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
        invite_emails=["partner@gmail.com", "friend@example.com"],
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
    scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        local_tz=NY,
        match_cache=scout.CalendarMatchCache(matches),
        calendar_client=client,
        state={"version": 1, "entries": {}},
        email_password="not-a-real-password",
        colors=False,
    )
    assert len(client.calls) == 1
    cal_id, body, send_updates = client.calls[0]
    assert cal_id == "primary"
    assert send_updates == "all"
    assert body["attendees"] == [
        {"email": "partner@gmail.com"},
        {"email": "friend@example.com"},
    ]


def test_maybe_add_without_invites_no_send_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matches = _write_matches(tmp_path / "matches.json", ["abc world news tonight"])
    monkeypatch.setattr(scout, "run_swaks_email", lambda **kwargs: None)
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
        "event_ticker": "KXWNT-26AUG11",
        "title": "ABC World News Tonight mentions",
        "first_event_time_utc": "2026-08-11T23:30:00Z",
        "event_time_sources": ["Kalshi event occurrence_datetime"],
    }
    scout.maybe_add_calendar_event_for_new_market(
        args=args,
        event=event,
        records=[],
        detected_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
        local_tz=NY,
        match_cache=scout.CalendarMatchCache(matches),
        calendar_client=client,
        state={"version": 1, "entries": {}},
        email_password="x",
        colors=False,
    )
    assert client.calls[0][2] is None
    assert "attendees" not in client.calls[0][1]


def test_watch_child_arguments_strips_invite_email() -> None:
    child = scout._watch_child_arguments(
        [
            "--watch-new",
            "--calendar-add-new",
            "--invite-email",
            "partner@gmail.com",
            "--invite-email=friend@example.com",
            "--type",
            "wnt",
        ]
    )
    assert "--invite-email" not in child
    assert "partner@gmail.com" not in child
    assert "friend@example.com" not in child
    assert "--type" in child


def test_cli_help_lists_invite_email() -> None:
    help_text = scout.build_parser().format_help()
    assert "--invite-email" in help_text
    assert "attendee" in help_text.casefold()


def test_main_invite_without_calendar_add_new_fails() -> None:
    old = sys.argv
    try:
        sys.argv = ["mention_scout.py", "--invite-email", "a@b.com"]
        with pytest.raises(SystemExit, match="requires --calendar-add-new"):
            scout.main()
    finally:
        sys.argv = old


def test_main_invalid_invite_fails() -> None:
    old = sys.argv
    try:
        sys.argv = [
            "mention_scout.py",
            "--calendar-add-new",
            "--watch-new",
            "--invite-email",
            "not-an-email",
        ]
        with pytest.raises(SystemExit, match="invalid --invite-email"):
            scout.main()
    finally:
        sys.argv = old
