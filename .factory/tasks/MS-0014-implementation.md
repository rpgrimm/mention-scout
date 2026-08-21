# MS-0014 — Implementation report

Status: **implemented on branch; PR open; not verified/shipped**  
Date: 2026-08-21  
Branch: `openclaw/ms-0014`  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0014`  
PR: https://github.com/rpgrimm/mention-scout/pull/24  
Issue: https://github.com/rpgrimm/mention-scout/issues/23  
VERSION: **16.2.0** (from 16.1.0; minor bump for new one-shot CLI modes)

## What changed

### CLI (`kalshi_mention_scout.py`)

- `--audit-calendar-matches` one-shot:
  - loads via existing `load_calendar_match_config`
  - success → stdout summary (`path`, `version`, `phrases`, `default_time`), exit 0, no email
  - failure → stderr + exit 1; default FAIL email via `run_swaks_email` when SMTP password loadable
  - `--email-on-fail` / `--no-email-on-fail` (default on for audit)
  - subject: `[Kalshi] FAIL | calendar-matches audit`
- `--add-calendar-match` + required `--match`; optional `--time`, `--duration-minutes`, `--dry-run`
  - create missing v1 file (no invented `default_time`)
  - refuse write if existing invalid (no clobber)
  - atomic write via `write_cache_atomic` / `save_calendar_match_config`
  - preserve existing phrases + `default_time`; casefold duplicate → update when time/duration provided else `already-present`
  - plain string if no time/duration else object form
- Mutual exclusion with watch/email/calendar-add/queue/test-email/calendar-auth/invite-email/each other and orphan flag combos
- New parent-only flags stripped in `_watch_child_arguments`
- Stable symlink `./mention_scout.py` unchanged (still → `kalshi_mention_scout.py`)

### Helpers added

- `calendar_phrase_to_payload`, `calendar_match_config_to_payload`
- `save_calendar_match_config`, `add_calendar_match`
- `format_calendar_matches_audit_fail_email`
- `run_audit_calendar_matches`, `run_add_calendar_match`
- `format_calendar_phrase_entry`

### Docs / factory

- README: validate + add subsections, MS-0012 boundary, optional cron example
- `.factory/specs/MS-0014-approved.md`, proposed, task tracker, github index row

### Not done (by design)

- MS-0012 watch-startup FAIL mail
- Symlink retarget
- Merge to main / ship / real SMTP owner proof

## Tests

```text
./scripts/factory-test.sh
# compile + --help/--version smoke
# pytest: 139 passed in 0.29s
```

New file: `tests/test_calendar_matches_cli.py` (audit ok/bad/email/no-email/mail-skip; add create/update/preserve/invalid/dry-run/conflicts; help; child argv strip; main routing).

Existing calendar / invite / type / installer tests remain green.

Note: worktree `.venv` lacked pip/pytest initially; installed pytest into `.venv` via get-pip for the run. Host system python had no pip/ensurepip.

## Deviations from approved spec

None material.

- Canonical rewrite is known-keys-only from `CalendarMatchConfig` (as preferred in freeze).
- `--duration-minutes` argparse `type=int` plus `> 0` check; loader parser reused inside `add_calendar_match` for consistency.
- Add mode prints `calendar-matches dry-run` header when `--dry-run` (still includes action/entry/total + `dry-run: not written`).
- VERSION minor bump **16.2.0** documented in commit (new user-facing modes).

## Files touched

- `kalshi_mention_scout.py`
- `README.md`
- `tests/test_calendar_matches_cli.py`
- `.factory/specs/MS-0014-approved.md`
- `.factory/specs/MS-0014-proposed.md`
- `.factory/tasks/MS-0014.md`
- `.factory/tasks/MS-0014-implementation.md` (this file)
- `.factory/github.md`

## Next pipeline steps

1. Independent verification PASS
2. Owner manual proof (break/fix audit email; add phrase; watch load)
3. Explicit owner ship approval
4. Merge + release packaging (not this implementation agent)
