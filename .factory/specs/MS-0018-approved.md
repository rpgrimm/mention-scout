# MS-0018 — persist --watch-new seen tickers for catch-up

Status: **APPROVED** by owner 2026-09-25 (chat: save seen tickers on the filesystem, preferably `~/.local/state`, so dual-boot / other-OS gaps never miss NEW email/calendar).
Type: feature
Related: MS-0010 calendar-add, MS-0008 user watch unit
Branch: `openclaw/ms-0018` + PR into `main`. Do not merge until owner says so.

## Behavior

- Persist **parent event tickers only** (JSON array + version).
- Default path: `$XDG_STATE_HOME/mention-scout/seen-event-tickers.json`, else `~/.local/state/mention-scout/seen-event-tickers.json`.
- Override: `--watch-seen-file PATH` (watch-only).
- **First run** (missing file): baseline current inventory, write the file, **no** catch-up alerts.
- **Later startups**: `new = current − saved`; announce those (print + `--email-new` + `--calendar-add-new`) then enter the poll loop.
- Known set only grows (disappeared tickers stay saved so reappearance is not NEW).
- Atomic write, mode `0600`. Invalid JSON fails watch start.
- No trading.
