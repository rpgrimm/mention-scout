# MS-0015 implementation

Branch: `openclaw/ms-0014` (stacked on MS-0014 PR #24)
VERSION: 16.3.0

## Changes

- `where_to_watch` optional string on calendar-matches phrase objects
- CLI `--where-to-watch` with `--add-calendar-match` (create + casefold update)
- Calendar event description line `Where to watch: …` on new inserts (first hit)
- Example JSON + README + audit schema reminder
- Tests for load/serialize/update/body/child-argv strip

## Tests

`./scripts/factory-test.sh` — 147 passed
