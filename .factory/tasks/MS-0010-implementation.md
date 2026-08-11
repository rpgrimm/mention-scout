# MS-0010 implementation

Branch: `openclaw/ms-0010`  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0010`  
Spec: `.factory/specs/MS-0010-approved.md`  
GitHub: https://github.com/rpgrimm/mention-scout/issues/15

## Summary

Implemented opt-in Google Calendar auto-add for `--watch-new` when a newly discovered parent event matches owner phrases in a JSON match file.

### Behavior (owner defaults)

- Gate: `~/.config/mention-scout/calendar-matches.json` (`version: 1`, `phrases: [...]`)
- Match: case-insensitive substring, OR across phrases
- Haystack: parent overview fields + child titles/tickers from the watch snapshot (not rules boilerplate)
- Reload match file on mtime change without watch restart
- `--calendar-add-new` only with `--watch-new`
- `--calendar-auth` one-shot browser OAuth; watch never opens a browser
- Fail fast at watch start if secret/token/match file missing/invalid (and SMTP required for calendar error mail)
- Date-only schedule → all-day event; missing schedule → no insert + error email once per ticker
- Timed duration default 60m; calendar id `primary`
- Dedupe state: `~/.config/mention-scout/calendar-added.json`
- Calendar error emails even if `--email-new` is off (existing swaks path)
- Optional Google API libs with actionable import error
- No `--calendar-types` gate
- All `--calendar-*` stripped from `_watch_child_arguments`
- Existing CLI defaults unchanged when calendar flags absent
- No trading; no real email/Google in tests; secrets not committed

### Code touchpoints

- `kalshi_mention_scout.py`
  - Match load/validate/cache, haystack, phrase match
  - Event body builder (timed + all-day)
  - Local dedupe state load/save
  - OAuth load/refresh + `GoogleCalendarApiClient`
  - Error email formatter + send helper
  - Hook in `watch_new_events` new-ticker loop
  - CLI flags + `main()` coupling / `--calendar-auth`
- `deploy/config/calendar-matches.example.json` (seed phrase)
- `tests/test_calendar_add.py` (offline unit tests + fake calendar client)
- `README.md`, `.gitignore`
- Factory docs: this file + task checklist update

### Tests run

```bash
./scripts/factory-test.sh
# (worktree venv lacked pip/ensurepip; used sibling worktree interpreter with pytest)
PYTHON_BIN=/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0006/.venv/bin/python \
  ./scripts/factory-test.sh
```

Results: compile + CLI smoke + full pytest suite green (see PR / commit notes for counts).

### Explicit non-actions

- No PR merge
- No ship/release
- No real SMTP or Google API calls in automated tests
- No live writes under owner `~/.config/mention-scout/` during implementation
- No VERSION bump / symlink retarget (ship policy after independent verification)

### Deviations from approved defaults

None.
