# MS-0006 — Implementation notes

Status: **IMPLEMENTED** (pending independent verification)  
Branch: `openclaw/ms-0006`  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0006`  
Spec: `.factory/specs/MS-0006-approved.md`  
Issue: https://github.com/rpgrimm/mention-scout/issues/7

## What shipped

Deterministic mention-type layer in `kalshi_mention_scout.py` (monolith kept):

| Piece | Detail |
|-------|--------|
| Registry | `MentionType` + `MENTION_TYPE_REGISTRY` / `MENTION_TYPES` |
| Rules | Ordered `_TYPE_RULES` (ticker then title); priority FTN → WNT → earnings → trump → say → other |
| Classify | `classify_mention_type`, `mention_type_for_event`, `mention_type_for_market`, `mention_type_label` |
| Subject | `format_new_market_email_subject` → `[Kalshi] {label} \| NEW: {event_ticker}` |
| Filter | `parse_type_filter`, `normalize_type_token`, `event_matches_types`, `market_matches_types` |
| CLI | `--type TYPE` (comma-separated); aliases `ftn`, `wnt`, `world-news`; invalid → `SystemExit` |
| Overview | `mention_type` + `mention_type_label` on `event_overviews`; human `type:` line |
| Markets JSON | Same additive fields on `market_record` (low-cost) |
| Email body | `Type: {label}` after title |
| Watch | `_watch_child_arguments` does not strip `--type` (forwards like `--contains`) |
| Cache | No format bump; type derived at runtime |

## Selection path

1. Status + binary mention + `--contains` (unchanged order for contains).
2. Ensure parent `event_details` available.
3. Apply `--type` any-of using parent-aware `market_matches_types`.
4. Window filter as before.

Omitting `--type` leaves inventory filtering identical aside from additive display fields and intentional email subject change.

## Tests

- `tests/test_mention_types.py` — table-driven classifier, subject builder, aliases/invalid tokens, any-of filter, AND-with-contains composition, watch argv preservation, help text.
- `./scripts/factory-test.sh` already runs pytest when `tests/` exists (unchanged).

## Verification (implementer)

```text
./scripts/factory-test.sh   # compile + help/version + 44 passed
python3 -m pytest -q        # 44 passed
```

No real email. No live Kalshi required for unit tests.

## Non-goals honored

- No trading paths
- No MS-0004 dry-run
- No `CACHE_FORMAT_VERSION` bump
- No secrets committed
