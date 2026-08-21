# MS-0013 implementation notes

Branch: `openclaw/ms-0013`
Issue: https://github.com/rpgrimm/mention-scout/issues/20

## Delivered

- Repeatable `--invite-email ADDRESS` (calendar attendees only).
- `normalize_invite_emails` / `validate_email_address` with max 20.
- `build_calendar_event_body(..., invite_emails=)` adds `attendees`.
- `CalendarClient.insert_event(..., send_updates=)` → `sendUpdates=all` when invites present.
- Fail fast if invites without `--calendar-add-new`.
- No SMTP fan-out to invitees.
- VERSION 16.1.0; README note; offline tests in `tests/test_invite_email.py`.
- factory-test: 107 passed.

## Not done

- Merge/ship (owner test + later explicit approval).
- Independent verification agent (not requested).
