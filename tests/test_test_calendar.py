"""Offline tests for --test-calendar dummy insert/confirm/delete."""

from __future__ import annotations

import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402

NY = ZoneInfo("America/New_York")


class MemoryCalendarClient:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.insert_calls = 0

    def insert_event(
        self,
        calendar_id: str,
        body: dict,
        *,
        send_updates: str | None = None,
    ) -> dict:
        self.insert_calls += 1
        event_id = f"test-{self.insert_calls}"
        payload = {
            "id": event_id,
            "htmlLink": f"https://calendar.google.com/event?eid={event_id}",
            "calendar_id": calendar_id,
            "body": body,
            "send_updates": send_updates,
        }
        self.events[event_id] = payload
        return {"id": event_id, "htmlLink": payload["htmlLink"]}

    def get_event(self, calendar_id: str, event_id: str) -> dict:
        if event_id not in self.events:
            raise RuntimeError(f"Google Calendar API get failed: <HttpError 404 when requesting {event_id}>")
        return {"id": event_id, "htmlLink": self.events[event_id]["htmlLink"]}

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        if event_id not in self.events:
            raise RuntimeError(f"Google Calendar API delete failed: 404")
        del self.events[event_id]
        self.deleted.append(event_id)


def test_build_test_calendar_event_body_is_today_noon() -> None:
    now = datetime(2026, 10, 27, 18, 45, tzinfo=NY)
    body = scout.build_test_calendar_event_body(now, NY)
    assert body["summary"] == "[Kalshi] mention scout calendar test"
    assert body["start"]["dateTime"].startswith("2026-10-27T12:00:00")
    assert body["end"]["dateTime"].startswith("2026-10-27T12:15:00")
    assert body["start"]["timeZone"] == "America/New_York"


def test_send_test_calendar_inserts_confirms_and_deletes(capsys: pytest.CaptureFixture[str]) -> None:
    client = MemoryCalendarClient()
    args = Namespace(
        timezone="America/New_York",
        calendar_id="primary",
        calendar_client_secret=Path("/tmp/unused-secret.json"),
        calendar_token=Path("/tmp/unused-token.json"),
    )
    now = datetime(2026, 10, 27, 9, 0, tzinfo=NY)
    assert scout.send_test_calendar(
        args, calendar_client=client, now=now, wait_confirm=False
    ) == 0
    assert client.deleted == ["test-1"]
    assert client.events == {}
    out = capsys.readouterr().out
    assert "calendar test inserted test-1" in out
    assert "2026-10-27T12:00:00" in out
    assert "calendar test API confirms event exists" in out
    assert "calendar test deleted dummy event" in out


def test_send_test_calendar_deletes_even_if_get_fails() -> None:
    class FlakyGet(MemoryCalendarClient):
        def get_event(self, calendar_id: str, event_id: str) -> dict:
            if event_id in self.events:
                raise RuntimeError("Google Calendar API get failed: 500 boom")
            raise RuntimeError("Google Calendar API get failed: <HttpError 404 when requesting>")

    client = FlakyGet()
    args = Namespace(timezone="America/New_York", calendar_id="primary")
    with pytest.raises(RuntimeError, match="500 boom"):
        scout.send_test_calendar(
            args, calendar_client=client, now=datetime(2026, 10, 27, tzinfo=NY), wait_confirm=False
        )
    assert client.deleted == ["test-1"]
    assert client.events == {}


def test_send_test_calendar_reports_delete_failure() -> None:
    class NoDelete(MemoryCalendarClient):
        def delete_event(self, calendar_id: str, event_id: str) -> None:
            raise RuntimeError("Google Calendar API delete failed: 403")

    client = NoDelete()
    args = Namespace(timezone="America/New_York", calendar_id="primary")
    with pytest.raises(RuntimeError, match="delete failed"):
        scout.send_test_calendar(
            args, calendar_client=client, now=datetime(2026, 10, 27, tzinfo=NY), wait_confirm=False
        )
    assert "test-1" in client.events


def test_calendar_error_is_missing() -> None:
    assert scout.calendar_error_is_missing(RuntimeError("HttpError 404 when requesting"))
    assert scout.calendar_error_is_missing(RuntimeError("410 Gone"))
    assert not scout.calendar_error_is_missing(RuntimeError("500 backendError"))


def test_parser_has_test_calendar() -> None:
    args = scout.build_parser().parse_args(["--test-calendar"])
    assert args.test_calendar is True
    assert args.test_email is False
    assert args.yes is False


def test_send_test_calendar_waits_before_delete() -> None:
    client = MemoryCalendarClient()
    seen_before_delete: list[bool] = []

    def confirm() -> None:
        seen_before_delete.append("test-1" in client.events)
        assert client.deleted == []

    args = Namespace(timezone="America/New_York", calendar_id="primary", yes=False)
    assert scout.send_test_calendar(
        args,
        calendar_client=client,
        now=datetime(2026, 10, 27, tzinfo=NY),
        wait_confirm=True,
        confirm_fn=confirm,
    ) == 0
    assert seen_before_delete == [True]
    assert client.deleted == ["test-1"]
