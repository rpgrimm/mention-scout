# MS-0015 — Where-to-watch on calendar matches + event description

Status: **APPROVED**  
Approved: 2026-08-21 by owner (chat: need `where to watch` in calendar-matches.json and calendar entry description via `--where-to-watch '5-1 nbc'`; ensure update of existing entries; spec + implement + stack on existing MS-0014 PR).  
Type: feature (calendar config + event body)  
Priority: P2  
Related: MS-0014 (audit/add CLI; this MS extends phrase schema + add/update + description), MS-0011 (time/duration on phrases), MS-0010 (calendar auto-add)  
Repository: `/home/candr/src/mention_scout`  
Implementation target: `kalshi_mention_scout.py` on branch `openclaw/ms-0014` (stack into PR #24)  
Stable command: `./mention_scout.py`  
GitHub: file/link issue; PR stacks on https://github.com/rpgrimm/mention-scout/pull/24  

## Owner decisions (frozen)

1. **Field name in JSON:** `where_to_watch` (string) on phrase **object** entries.
2. **CLI flag:** `--where-to-watch TEXT` (with `--add-calendar-match`).
3. **Examples:** `--where-to-watch '5-1 nbc'`, `--where-to-watch '4-1 cbs'` (free text; trim; reject empty after trim).
4. **Calendar description:** when a matched phrase supplies `where_to_watch`, include a clear line in the Google Calendar event description, e.g. `Where to watch: 5-1 nbc`.
5. **Which value wins:** first matched phrase (same order as today’s hit list) that has non-empty `where_to_watch` (parallel to time/duration first-hit).
6. **No file-level default** `where_to_watch` in v1 (phrase-only).
7. **Schema version:** remain `version: 1` (additive optional field; plain strings still valid).
8. **Object form:** any of `time`, `duration_minutes`, or `where_to_watch` forces object serialization; plain string only when none of those are set.
9. **Update existing entries:** case-insensitive match key (MS-0014). If any of `--time`, `--duration-minutes`, or `--where-to-watch` is provided → **update** that entry (preserve unspecified fields). Only `--match` with no optional fields → `already-present` no-op when exists.
10. **Add path must support update** (already does for time/duration; extend the same path for where_to_watch). No separate `--update-calendar-match` flag required.
11. **Audit:** validates `where_to_watch` is a non-empty string when present; includes field in schema reminder email/docs.
12. **Matching haystack:** do **not** use `where_to_watch` for phrase matching (config metadata only).
13. **Existing calendar events:** v1 does not patch already-created Google events; applies to **new** inserts only (same as MS-0013 attendees).
14. **Tests + README + example** updated; VERSION bump on this stacked change (16.2.0 → 16.3.0 minor additive).
15. **Ship:** stack commits on `openclaw/ms-0014` / PR #24; no merge without independent verification + owner ship approval.
16. No trading; no real SMTP in tests; preserve `./mention_scout.py` symlink target.

## Problem

Owner needs a per-show reminder of **where to watch** (channel/call letters, e.g. `5-1 nbc`, `4-1 cbs`) stored in `calendar-matches.json` and copied into the **Google Calendar event description** when mention-scout auto-creates the event. Also needs confidence that `--add-calendar-match` can **update** an existing phrase entry (not only append).

## Goal

```bash
./mention_scout.py --add-calendar-match \
  --match "abc world news tonight" \
  --time 18:30 \
  --duration-minutes 30 \
  --where-to-watch '5-1 nbc'

# Update existing entry’s where-to-watch only
./mention_scout.py --add-calendar-match \
  --match "abc world news tonight" \
  --where-to-watch '4-1 cbs'
```

JSON:

```json
{
  "version": 1,
  "default_time": "18:30",
  "phrases": [
    {
      "match": "abc world news tonight",
      "time": "18:30",
      "duration_minutes": 30,
      "where_to_watch": "5-1 nbc"
    }
  ]
}
```

Calendar description includes:

```text
Where to watch: 5-1 nbc
```

## Scope

### In
- `CalendarPhrase.where_to_watch: str | None`
- Load/parse/serialize/save/add/update
- `resolve_calendar_match_options` (or sibling) returns where_to_watch
- `build_calendar_event_body` description line
- CLI `--where-to-watch`; strip in watch child argv; mutual exclusion unchanged
- Tests, README, example JSON
- Audit schema reminder mentions the field

### Out
- Updating already-inserted Google Calendar rows
- File-level default where_to_watch
- Structured channel parse (free string only)
- Separate update subcommand name
- MS-0012

## Requirements

1. Optional `where_to_watch` string on phrase objects; trim; empty rejected.
2. CLI `--where-to-watch` only with `--add-calendar-match`.
3. Update-in-place when where/time/duration flags present on existing casefold match.
4. Description line `Where to watch: {value}` when resolved non-empty for the insert.
5. First matched phrase with where_to_watch wins.
6. Backward compatible: files without the field keep working.
7. Offline tests; mock no Google/SMTP required for unit coverage of serialize + body.

## Acceptance

- Owner can set/update where-to-watch via CLI without hand-editing JSON.
- New calendar events show where-to-watch in description when configured.
- Existing MS-0014 audit/add behavior preserved.
