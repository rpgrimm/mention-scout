# MS-0018 — persist --watch-new seen tickers for catch-up

Status: **APPROVED** by owner 2026-09-25 (chat: save seen tickers on the filesystem, preferably `~/.local/state`, so dual-boot / other-OS gaps never miss NEW email/calendar).
Type: feature
Related: MS-0010 calendar-add, MS-0008 user watch unit
Branch: `openclaw/ms-0018` + PR into `main`. Do not merge until owner says so.

## Behavior

- Persist parent tickers as version-2 `entries` with `alert_sent` / `alert_sent_utc` / `skipped_past` / `baselined`. Accept version-1 `{tickers: [...]}` as baselined (no alert storm).
- Default path: `$XDG_STATE_HOME/mention-scout/seen-event-tickers.json`, else `~/.local/state/mention-scout/seen-event-tickers.json`.
- Override: `--watch-seen-file PATH` (watch-only).
- **First run** (missing file): baseline current inventory (`baselined`), write the file, **no** catch-up alerts.
- **Later startups**: unhandled current tickers are catch-up. Announce future ones (print + `--email-new` + `--calendar-add-new`). Mark `alert_sent` after a successful announce (email failure is retried).
- **Never alert past events**: timed start `<= now`, or date-only local date `< today`. Mark `skipped_past` instead. Unknown schedule is not treated as past.
- Known set only grows (disappeared tickers stay saved so reappearance is not NEW).
- Atomic write, mode `0600`. Invalid JSON fails watch start.
- No trading.
