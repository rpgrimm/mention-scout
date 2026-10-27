# MS-0021 — `--test-calendar` dummy insert/confirm/delete

Status: **APPROVED** by owner 2026-10-27 (chat: test `--test-calendar` that inserts a dummy event at today's date at noon and when confirmed it's there delete it).
Type: feature
Related: MS-0010, MS-0020
Ships on `openclaw/ms-0020` / PR #30 (same checkout as SMTP2GO setup). Do not merge until owner tests.

## Behavior

- One-shot: `./mention_scout.py --test-calendar`
- Inserts a dummy timed event on **today's date at 12:00** in `--timezone` (default America/New_York), duration 15 minutes.
- GET confirms the event id exists (API).
- Wait for the owner to press Enter after they see it on Google Calendar (Ctrl-C leaves it). `--yes` skips the wait.
- DELETE the dummy event (do not write `calendar-added.json`).
- GET after delete must look like 404/410.
- If GET-after-insert fails, still attempt delete.
- Requires OAuth token (`--calendar-auth` first). Does not require calendar-matches.json.
- Discovery only. No trading.
