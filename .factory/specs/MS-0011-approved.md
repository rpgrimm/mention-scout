# MS-0011 — Owner-configured local time for date-only calendar events

Status: **APPROVED**  
Approved: 2026-08-13 by owner (chat: calendar event lands on correct day but has no time; add time to JSON + code so owner can set a certain time; spec → implement → PR → pause for owner test)  
Type: feature (calendar schedule refinement)  
Priority: P2 (owner-requested follow-on to MS-0010)  
Related: MS-0010 (#15), GitHub #17  
Repository: `/home/candr/src/mention_scout`  
Implementation target: `kalshi_mention_scout.py`  
Stable command: `./mention_scout.py`  
Review publication: **feature branch `openclaw/ms-0011` + pull request into `main`** (do not push straight to `main`)  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0011`

## Owner decisions (frozen)

1. **Problem:** MS-0010 date-only schedules create **all-day** Google Calendar events. Owner wants optional clock times from config so shows land at a real local time.
2. **Config surface:** extend `calendar-matches.json` (same path defaults as MS-0010). No new CLI flag required for the time itself.
3. **Backward compatible phrases:** plain string entries in `phrases` still work exactly as today (match-only; no default time from that entry).
4. **Rich phrase entries allowed:** object form with required `match` string and optional `time` / `duration_minutes`.
5. **File-level default time:** optional top-level `default_time` applies when a matched phrase has no own `time`.
6. **Time format:** 24-hour `HH:MM` or `H:MM` local wall clock in `--timezone` (default `America/New_York`). Leading zero optional. Reject invalid times at match-file load with actionable error.
7. **When to apply owner time:** only when the resolved Kalshi/overview schedule is **date-only** (existing `_schedule_is_date_only` true). Do **not** override a real timed Kalshi datetime.
8. **Which time wins when multiple phrases match:** first matched phrase (same order as today’s `matching_calendar_phrases` hit list) that yields a usable time after phrase-level then file-level default. If none, keep all-day.
9. **Duration:** phrase optional `duration_minutes` > 0 overrides `--calendar-duration-minutes` for that timed insert; else CLI default (60).
10. **Missing schedule:** unchanged — no calendar row; failure email once per ticker.
11. **Invalid JSON shape:** fail fast at load/preflight (same spirit as MS-0010) with clear path + field error.
12. **Example + README** updated; seed can show object form with a sensible World News Tonight example time **or** document both string and object forms. Prefer example that demonstrates `time` so owner copy/paste works.
13. **Tests:** offline only; no real Google/SMTP.
14. **Ship path:** implement on branch, open PR; pause for owner manual test. No merge/ship without independent verification PASS + later explicit owner ship approval.
15. **VERSION / symlink:** do not retarget stable symlink; VERSION bump only if release policy requires on ship — not required in this PR.

Proposed optional fields beyond the freeze are out of scope unless cheap and already listed below.

---

## Problem

After MS-0010, phrase-matched new parents get a Google Calendar row. Many Kalshi mention markets only expose a **date** (ticker date / strike_date / “exact time unavailable”). MS-0010 maps those to **all-day** events.

The owner confirmed: the event appears on the **correct day** but **without a time**. They want to put a preferred airing time in the match JSON so the calendar entry is timed.

---

## Current behavior (MS-0010)

| Case | Calendar result |
|------|-----------------|
| Timed Kalshi schedule | Timed event; end = start + `--calendar-duration-minutes` (default 60) |
| Date-only schedule | All-day on that local date |
| Missing schedule | No insert; error email once per ticker (deduped) |
| Match file | `{ "version": 1, "phrases": ["abc world news tonight", ...] }` strings only |

Relevant helpers: `load_calendar_match_phrases`, `matching_calendar_phrases`, `resolve_calendar_schedule`, `_schedule_is_date_only`, `build_calendar_event_body`, `maybe_add_calendar_event_for_new_market`, `CalendarMatchCache`.

---

## Goal

Owner can configure a local wall-clock time (and optional duration) in `calendar-matches.json`. When a new matched parent would otherwise be all-day, mention-scout creates a **timed** event on that date at the configured local time.

---

## Match file schema (v1 extended, still `version: 1`)

```json
{
  "version": 1,
  "default_time": "18:30",
  "phrases": [
    "simple string still works",
    {
      "match": "abc world news tonight",
      "time": "18:30",
      "duration_minutes": 30
    }
  ]
}
```

### Rules

- `version` must remain `1`.
- `phrases` is a non-empty JSON array after validation (same empty-after-trim rejection).
- Each phrase element is either:
  - a **string** (trimmed non-empty) → match text only; or
  - an **object** with:
    - `match` (required string, trimmed non-empty)
    - `time` (optional string `HH:MM` / `H:MM` 24h)
    - `duration_minutes` (optional int/float that is a whole number of minutes > 0)
- Unknown object keys: **ignore** (forward compatible) unless they make required fields invalid.
- Top-level `default_time` optional; same time format as phrase `time`.
- Top-level unknown keys: ignore.
- Dedupe phrases by casefolded `match` text (first wins), same spirit as MS-0010 string dedupe.
- Matching remains **case-insensitive substring OR** on the same haystack as MS-0010.
- Invalid time / duration / types → **RuntimeError** at load with path + index/field.

### Time parsing

- Accept `H:MM` or `HH:MM`, hours 0–23, minutes 0–59.
- No seconds, no AM/PM in v1 (keep parsing strict and obvious).
- Interpreted in `args.timezone` / `local_tz` used by calendar body builder.

---

## Schedule application

Inside calendar body construction (or immediately before), after `resolve_calendar_schedule`:

1. If no start → raise missing schedule (unchanged).
2. If schedule is **not** date-only → build timed event from Kalshi datetime + effective duration (phrase duration if set on chosen match else CLI). Prefer: duration override may apply to timed Kalshi events too when the chosen matched phrase sets `duration_minutes`; if ambiguous, **apply phrase duration only when owner time is applied or phrase explicitly sets duration** — frozen choice: **phrase `duration_minutes` applies whenever that phrase is the chosen match for duration**, including pure timed Kalshi rows; if multiple matches, use first matched phrase that defines `duration_minutes`, else CLI default.
3. If schedule **is** date-only:
   - Resolve owner local time: first matched phrase with `time`, else file `default_time`, else none.
   - If owner time present: start = that local date + time in `local_tz`; end = start + effective duration; **timed** body (`dateTime` + `timeZone`). Annotate schedule source string to include owner time, e.g. append `; owner time 18:30 from calendar-matches`.
   - If no owner time: keep **all-day** (MS-0010).

**Chosen match for time:** walk `matched` phrases in order; map back to loaded phrase records; first with `time` wins; else `default_time`.

**Chosen duration:** walk matched phrases in order; first with `duration_minutes` wins; else `args.calendar_duration_minutes`.

---

## API / code shape (normative intent)

Replace string-only load with structured records while preserving a simple phrase list for matching:

- `CalendarPhrase` (dataclass or TypedDict): `match: str`, `time: str | None`, `duration_minutes: int | None`, plus parsed `time_hour`/`time_minute` or a small parsed time tuple.
- `load_calendar_match_file(path) -> CalendarMatchConfig` with `phrases: list[CalendarPhrase]`, `default_time: parsed | None`.
- Keep or adapt:
  - `load_calendar_match_phrases` → can become thin wrapper returning `[p.match for p in config.phrases]` for compatibility **or** update all call sites to structured config (preferred: structured end-to-end).
- `CalendarMatchCache` caches full config (mtime), exposes `get_config()` and/or `get_phrases()`.
- `matching_calendar_phrases` may stay string-based; add helper `select_calendar_phrase_options(matched_strings, config) -> ...` for time/duration.
- `build_calendar_event_body(...)` gains optional `owner_time` / `duration_minutes` already passed; caller `maybe_add_calendar_event_for_new_market` resolves options from config + matched list.
- Description should mention owner-applied time when used.

No cache format bump. No trading. No real email/Google in tests.

---

## CLI

No new required flags. Existing:

| Flag | Role |
|------|------|
| `--calendar-matches` | Path to JSON (schema extended) |
| `--calendar-duration-minutes` | Default duration when phrase omits override |
| `--timezone` | Local zone for owner wall-clock time |

---

## Docs

- Update `deploy/config/calendar-matches.example.json` to show object entry with `time` (and optional `default_time` comment via README, not JSON comments).
- README Google Calendar section: document string vs object phrases, `default_time`, date-only + owner time behavior, and that real Kalshi datetimes are not overridden.

---

## Test plan (offline required)

1. Load string-only file (MS-0010 fixture) unchanged.
2. Load mixed strings + objects; default_time; dedupe.
3. Reject bad time (`25:00`, `18:60`, `6pm`, `18:30:00`), bad duration (`0`, `-5`, `3.5` if not whole — reject non-integers), missing `match`, empty match.
4. Date-only + phrase time → timed start on correct local date/time; duration from phrase or default.
5. Date-only + only `default_time` → timed.
6. Date-only + no times → all-day.
7. Timed Kalshi schedule → still uses Kalshi clock (not owner time).
8. Phrase duration overrides CLI duration.
9. `maybe_add` integration: date-only match inserts timed body when config has time.
10. Existing MS-0010 tests updated for any signature changes; factory-test green.

### Manual owner proof (not CI)

1. Set phrase time in `~/.config/mention-scout/calendar-matches.json`.
2. Trigger/wait for matching date-only market (or temporary test path if owner prefers).
3. Confirm Google Calendar shows correct date **and** time.
4. Pause after PR for this proof before ship.

---

## Acceptance criteria

1. String-only match files keep working.
2. Owner can set `time` on a phrase object and/or `default_time`.
3. Date-only + configured time → timed calendar event at that local time.
4. Date-only + no time config → all-day (regression-safe).
5. Real timed Kalshi schedules are not replaced by owner time.
6. Invalid time/duration fails at match load with actionable error.
7. Example JSON + README document the feature.
8. Offline tests cover the matrix; no secrets/real APIs.
9. PR opened from `openclaw/ms-0011`; no merge without verification PASS + explicit ship approval.

---

## Out of scope

- Per-phrase timezone different from `--timezone`.
- RRULE / multi-day spans / reminders customization.
- Updating or deleting existing calendar rows when JSON times change.
- AM/PM parsing, seconds, `HHMM` without colon.
- Overriding timed Kalshi datetimes.
- Trading, real SMTP/Google in CI.

---

## Implementation notes

- Smallest change set: match load + cache + body/schedule apply + tests + example + README.
- Preserve fail-fast preflight by loading full config at watch start.
- Never commit live owner config, tokens, or secrets.
