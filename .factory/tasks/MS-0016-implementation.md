# MS-0016 — Implementation report

Status: **implemented on branch; PR for owner desktop test; not merged**  
Date: 2026-09-25  
Branch: `openclaw/ms-0016`  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0016`  
PR: https://github.com/rpgrimm/mention-scout/pull/25  
Util version: **1.0.1** (new file; `mention_scout.py` unchanged). Default tab delay is **2s** after owner desktop test (Google disliked 0.15s bursts).

## What changed

New stdlib CLI `./mention_markets.py`:

- `list [--json PATH]` prints unique event tickers from calendar-added JSON, newest `added_at_utc` first (`EVENT_TICKER<TAB>added_at_utc<TAB>matched_phrase`). Duplicate `EVENT_TICKER::calendar_id` keys keep the latest timestamp.
- `target EVENT_TICKER [--action google-news] [--dry-run] [--json PATH] [--sleep N]` looks up the ticker in that JSON (case-insensitive; `::suffix` stripped), fetches `/trade-api/v2/markets?event_ticker=…&limit=1000` with cursor pagination (max 20 pages; fail on repeated cursor), keeps `active`/`open` markets, and runs the action.
- Default action `google-news`: one Google `{cleaned} news` tab per unique market ticker via `webbrowser.open_new_tab`. Slash phrases drop slashes (`OpenAI / Anthropic` → `OpenAI Anthropic news`); trailing `(N times)` / `(N+ times)` is stripped.
- `--dry-run` prints `word<TAB>url` and a stderr count; never opens a browser.
- Missing/invalid JSON, unknown ticker, unknown action, empty usable market list, and HTTP errors: non-zero exit, stderr, no browser.
- Headless warning when `DISPLAY`/`WAYLAND_DISPLAY` are unset (still attempts open unless `--dry-run`). One failed tab open warns and continues.

Public unauthenticated GET only. No trading, WebSockets, API keys, or import of `kalshi_broadcast_word_trader.py`.

### Docs / factory

- README: “Mention markets util” section + layout row
- `.factory/specs/MS-0016-approved.md`
- `.factory/tasks/MS-0016.md` (this tracker)
- `scripts/factory-test.sh`: compile + `--help`/`--version` smoke for `mention_markets.py`; existing pytest hook runs the new tests

### Not done (by design)

- Extra actions beyond `google-news`
- Direct Kalshi-only target when the ticker is absent from JSON
- Changes to `mention_scout.py` / `kalshi_mention_scout.py`
- Merge to `main` / release / email / systemd

## Tests

```text
./scripts/factory-test.sh
# compile + --help/--version smoke (mention_scout + mention_markets)
# pytest: 167 passed in 0.32s
```

New file: `tests/test_mention_markets.py` (JSON parse/latest-wins; list format/missing/invalid; unknown ticker; query cleaning table; slash subtitle word; paginated markets + opener; `--dry-run` never opens; inactive/unopened skipped; empty open list; unknown action; HTTP 404; help/version). Mock HTTP + fake opener only.

Manual smoke on this headless host (not in CI):  
`./mention_markets.py target KXWORLDNEWSMENTION-26SEP25 --dry-run` against the owner calendar-added JSON printed `OpenAI / Anthropic` → `q=OpenAI+Anthropic+news` (15 tabs). No browser opened.

## Deviations from approved spec

None material.

- `--timeout` / `--retries` are internal constants (20s / 3), matching mention-scout spirit, not extra CLI flags.
- `target` always prints `word<TAB>url` (including when opening tabs) so the desktop run is inspectable.
- Word extraction and public GET pagination follow the trader *ideas* (`market_word`, cursor loop) without copying that file.

## Files touched

- `mention_markets.py` (new, executable)
- `tests/test_mention_markets.py` (new)
- `README.md`
- `scripts/factory-test.sh`
- `.factory/specs/MS-0016-approved.md`
- `.factory/tasks/MS-0016.md`
- `.factory/tasks/MS-0016-implementation.md` (this file)

## Next pipeline steps

1. Owner desktop test: `list`, then `target … --dry-run`, then `target` without `--dry-run`
2. Independent verification PASS
3. Explicit owner ship approval
4. Merge + release packaging (not this implementation agent)
