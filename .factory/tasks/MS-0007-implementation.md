# MS-0007 — Implementation notes

Status: **IMPLEMENTED** (pending independent verification)  
Branch: `openclaw/ms-0007`  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0007`  
Spec: `.factory/specs/MS-0007-approved.md`  
Issue: https://github.com/rpgrimm/mention-scout/issues/9  
Option: **A** (owner-approved defaults)

## What changed

Minimal Option A split in `kalshi_mention_scout.py`:

| Piece | Detail |
|-------|--------|
| `text_for_market` | Unchanged field set (still includes `rules_primary` / `rules_secondary`); docstring clarifies contains/display role |
| `mention_gate_text_for_market` | **New** — same product fields without rules |
| `is_mention_market` | Uses gate text (not full `text_for_market`); ticker `MENTION` fast-path unchanged |
| `event_qualifies_as_mention` | **New** pure helper mirroring scan admission boolean for offline tests |
| `scan_mention_events` | Admission now calls `event_qualifies_as_mention`; comment no longer claims child *rules* drive discovery |
| `contains_filter` | Still uses full `text_for_market` (rules searchable) |
| Regex | `MENTION_RE` / `SAY_EVENT_RE` untouched |
| MS-0006 | Type registry/filter/subjects untouched |
| Cache / CLI / queue | No format bump; no default changes |
| Trading / email | None |

## Selection path (unchanged order)

1. Compact scan admits via `is_mention_event` **or** any nested `is_mention_market` (now rules-free).
2. Final filter in `main()` still requires `is_mention_market` ∧ status ∧ contains ∧ type.
3. `--contains` may still hit rules without making a market a mention market.
4. Type layer (MS-0006) still runs only after binary admission.

## Tests

- `tests/test_mention_gate.py` (new)
  - MS-0007 tariff fixture: parent false, nested market false, admission false; rules still contain “mention”; gate text excludes rules
  - True positives without rules: ticker `MENTION`, title say language, title mention language
  - Contains vs gate split (`ZYXCONTAINSRULES` in rules only)
  - Parent MENTION series still qualifies with quiet/non-mention child shapes
  - Missing fields do not raise
- `tests/test_mention_types.py` (MS-0006) still green

## Verification (implementer)

Worktree `.venv` is a broken ensurepip stub (no pytest). Equivalent checks run with the healthy ms-0006 venv interpreter:

```text
MS6_PY=/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0006/.venv/bin/python
"$MS6_PY" -m py_compile kalshi_mention_scout.py
"$MS6_PY" mention_scout.py --help >/dev/null
"$MS6_PY" mention_scout.py --version
"$MS6_PY" kalshi_mention_scout.py --help >/dev/null
"$MS6_PY" kalshi_mention_scout.py --version
"$MS6_PY" -m pytest -q
# 52 passed
```

No real email. No live Kalshi required. No trading.

Note: `./scripts/factory-test.sh` prefers local `.venv/bin/python` when executable, so the broken stub makes the script report `pytest is not installed` even if `PYTHON_BIN` is set. Verifier should use system/other python with pytest, or ignore the stub venv.

## Residual risks

| Risk | Notes |
|------|--------|
| True market whose *only* product signal is in rules | Accepted by owner; product language is ticker/title in practice |
| Future boilerplate in **titles** | Out of scope; separate issue if it appears |
| Stale compact cache may still list pre-fix false positives until TTL/`--refresh` | Final `is_mention_market` filter drops them on read (R6/R10) |
| Broken worktree `.venv` | Does not affect product code; factory-test convenience only |

## Non-goals honored

- No trading paths
- No real SMTP
- No `MENTION_RE` / denylist changes
- No MS-0006 taxonomy changes
- No `CACHE_FORMAT_VERSION` / queue format bump
- No CLI default changes
- No secrets committed
- Stable `./mention_scout.py` symlink preserved → `kalshi_mention_scout.py`

## Ready for independent verification

**Yes** — do not merge/ship until independent verification PASS + explicit owner approval.
