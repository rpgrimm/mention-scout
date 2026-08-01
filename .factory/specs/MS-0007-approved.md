# MS-0007 — False-positive `--watch-new` alert on non-mention market `KXGENERICTARIFF-26JUL`

Status: **APPROVED**  
Approved: 2026-08-01 by owner (GitHub issue #9 comment: “Approve.”) with recommended defaults (Option A).  
GitHub issue: https://github.com/rpgrimm/mention-scout/issues/9  
Factory id: MS-0007  
Type: bug (false-positive mention classification / inventory admission)  
Priority: P1  
Related: MS-0006 (type labels run **after** binary mention admission; must stay intact)  
Repository: `/home/candr/src/mention_scout`  
Implementation target: `kalshi_mention_scout.py`  
Stable command: `./mention_scout.py` (symlink → implementation; behavior must match either entry)

---

## Problem

`--watch-new` emitted a mention-market alert for parent event `KXGENERICTARIFF-26JUL`
(“Will Trump formalize a 100% tariff on generic drugs before the midterms?”).

Owner confirmed this is **not** a mention/say market. The alert used the normal
mention-market template (`NEW KALSHI MENTION MARKET`, `Type: other`), so the
failure is in **binary mention admission**, not the MS-0006 type layer.

False positives on the watch/email path are high-severity signal noise: they
train the owner to ignore alerts and can trigger unwanted emails/queue jobs.

## Current behavior (verified)

Live fixture (saved 2026-08-01):

`.factory/tasks/MS-0007-fixture-KXGENERICTARIFF-26JUL.json`

| Check | Result |
|-------|--------|
| `is_mention_event(parent)` | **False** — title/ticker/series/category clean |
| nested `KXGENERICTARIFF-26JUL-NOV03` via `is_mention_market` | **True** |
| Match source | `rules_secondary` text included by `text_for_market()` |
| Boilerplate fragment | “Actions that only incidentally **mention** the topic…” |
| Regex | `MENTION_RE` matches bare `\bmention\b` |
| Inventory admission | `scan_mention_events` admits parent when **any** nested market matches |
| Downstream | compact cache + one-shot filter + `--watch-new` treat parent as new mention event (`Type: other`) |

### Relevant code path (v16)

1. **`text_for_market(market)`** concatenates:
   `ticker`, `event_ticker`, `title`, `subtitle`, `yes_sub_title`, `no_sub_title`,
   **`rules_primary`**, **`rules_secondary`**.
2. **`is_mention_market(market)`**:
   - True if `"MENTION"` appears in `ticker` / `event_ticker`, else
   - True if `MENTION_RE` or `SAY_EVENT_RE` matches `text_for_market(market)`.
3. **`is_mention_event(event)`** uses `event_text_for_match` only
   (`event_ticker`, `series_ticker`, `title`, `sub_title`, `category`) — **no rules**.
   Parent alone correctly rejects the tariff event.
4. **`scan_mention_events`**:
   ```text
   matches_event = is_mention_event(event) or any(is_mention_market(child) for child in nested)
   ```
   Then keeps children when parent matched **or** the child itself matches.
5. **One-shot / watch child final filter** also requires `is_mention_market(market)`
   (and `--contains` / later `--type`). So rules-poisoned child classification both
   **admits** the parent during compact scan and **keeps** the child afterward.
6. **MS-0006 type layer** runs only after mention admission; labeling this event
   `other` is correct *given* the false admission. Do not “fix” this by special-casing type.

### Why title-only checks looked clean

Offline title/description alone do **not** match `MENTION_RE` / `SAY_EVENT_RE`.
The hit is settlement boilerplate on the nested market, not product language.

## Goal

Stop non-mention markets whose **only** “mention” signal is legal/settlement
boilerplate in `rules_primary` / `rules_secondary` from:

- entering compact mention inventory
- surviving one-shot / watch filters
- generating `--watch-new` terminal/email/queue alerts

while preserving true mention/say markets (ticker `MENTION`, title-driven say/mention
phrasing, series such as earnings/FTN/WNT/Trump mention families).

MS-0006 type behavior remains: **type classification and `--type` filtering run only
after binary mention admission.**

## Scope

### In scope

1. **Binary mention-gate text selection** for markets (and any shared helper used by
   `is_mention_market`), so settlement rules fields cannot alone admit a market.
2. Keep **`--contains`** able to search rules text if useful (explicit split below).
3. Keep **display / `--show-rules`** behavior unchanged (rules still available on records).
4. Regression tests:
   - this tariff fixture must be **rejected** by binary gates and scan-admission logic
   - at least one true-positive mention/say fixture that still matches **without**
     relying on rules boilerplate
   - ensure MS-0006 type tests remain green (no intentional type-rule changes)
5. Confirm watch path inherits the fix via existing child one-shot JSON path (no
   separate watch classifier).

### Out of scope

- Trading / order placement.
- Real SMTP in implementation or verification.
- Rewriting MS-0006 taxonomy, labels, subjects, or `--type` semantics.
- Cache format version bump (classification is derived at runtime from existing fields).
- CLI default changes (`--days`, `--window`, `--status`, cache TTL, email addresses, etc.).
- Broad NLP / LLM classification.
- Exhaustive Kalshi-wide boilerplate denylist as the primary fix.
- Changing parent-admission rule “parent match keeps all nested children of a true
  mention event” (that remains correct for real mention series).
- Queue format changes.
- Network/timeout/retry behavior.

## Root-cause analysis (confirmed)

| Layer | Finding |
|-------|---------|
| Product intent | Mention scout should alert on markets about someone **mentioning/saying** words or phrases (or conventional `*MENTION*` series), not every market whose legal rules use the English word “mention”. |
| Immediate cause | `is_mention_market` searches `text_for_market`, which includes `rules_secondary`. |
| Boilerplate | Kalshi executive-action style rules include: “Actions that only incidentally mention the topic…”. |
| Regex | `MENTION_RE` includes bare `\bmention(?:s|ed|ing)?\b` — appropriate for titles; toxic on settlement prose. |
| Amplification | `scan_mention_events` ORs child `is_mention_market` into parent admission → whole event enters mention inventory. |
| Alert path | `--watch-new` baselines/alerts on parent `event_ticker` set from filtered mention inventory → false NEW alert. |
| Why type=`other` | MS-0006 correctly finds no show/earnings/say family; fallback `other` is a symptom, not the bug. |

**Owner judgment (binding for this MS):** `KXGENERICTARIFF-26JUL` must not alert.

## Design options evaluated

### Option A — Stop using rules fields for binary mention detection (**recommended**)

Split market text roles:

| Consumer | Fields |
|----------|--------|
| **Mention gate** (`is_mention_market`) | ticker / event_ticker / title / subtitle / yes_sub_title / no_sub_title (**exclude** `rules_primary`, `rules_secondary`) |
| **Contains filter** (`contains_filter`) | keep current `text_for_market` **including rules** (owner may still search settlement text) |
| **Display / email / `--show-rules`** | unchanged; rules remain on normalized records |

Implementation sketch (non-normative):

```text
text_for_market(market)           # unchanged field set (includes rules) — display/contains
mention_gate_text_for_market(...) # same without rules_* 
is_mention_market:
  MENTION in ticker/event_ticker OR
  MENTION_RE|SAY_EVENT_RE on mention_gate_text_for_market
```

**Pros**

- Directly removes the confirmed poison channel.
- Smallest correct fix; local to classification helpers.
- Preserves ticker `MENTION` fast-path and title/subtitle say/mention language.
- No cache bump; no CLI flag churn.
- `event_text_for_match` already excludes rules — market gate becomes consistent with parent gate.

**Cons / residual**

- A hypothetical market whose **only** true product signal lived exclusively in rules
  (no ticker/title/subtitle signal) would no longer match. Owner accepts this: product
  language for mention/say markets appears in titles/tickers in practice; rules are
  settlement prose.

### Option B — Tighten `MENTION_RE` (not primary)

E.g. require “mention” near show/person context; drop bare `\bmention\b`.

**Pros:** might reduce some boilerplate hits.  
**Cons:** higher true-positive risk; still leaves other rules phrasing; fights symptoms
in a field that should not be gated on. Reject as primary.

### Option C — Require ticker/title/subtitle signals; treat rules-only hits as insufficient

Equivalent outcome to A if “signals” mean non-rules fields. Prefer A’s explicit text
split for clarity and testability rather than a post-hoc “rules-only” special case
inside one mega-string.

### Option D — Negative filters for known boilerplate phrases

E.g. ignore “incidentally mention”.

**Pros:** surgical for this sentence.  
**Cons:** whack-a-mole; other rules templates will recur; weaker than removing rules
from the gate. May be added later as defense-in-depth **only if** owner requests;
not required if A ships.

### Recommendation

**Ship Option A** as the primary and sufficient fix.

Optional micro-hardening (only if free and tested; default **off** unless owner opts in):

- Do **not** change `MENTION_RE` in this MS.
- Do **not** add boilerplate denylist in this MS.

## Normative requirements

### R1 — Rules fields must not drive binary mention admission

`is_mention_market` MUST NOT treat `rules_primary` or `rules_secondary` as mention-gate
input. A market whose sole regex hit comes from those fields MUST classify as
**not** a mention market.

### R2 — Non-rules product fields remain gate inputs

Binary market admission MUST still consider at least:

- `ticker`, `event_ticker` (including existing `"MENTION"` substring fast-path)
- `title`, `subtitle`, `yes_sub_title`, `no_sub_title`
- existing `MENTION_RE` and `SAY_EVENT_RE` on the gate text built from those fields

Parent `is_mention_event` / `event_text_for_match` field set remains as today
(no rules fields there already).

### R3 — Fixture rejection

Using `.factory/tasks/MS-0007-fixture-KXGENERICTARIFF-26JUL.json` (or an equivalent
frozen copy under `tests/fixtures/` if the implementer copies it):

- `is_mention_event(event)` → False
- `is_mention_market(nested_market)` → False
- Parent MUST NOT be admitted by the same boolean used in `scan_mention_events`:
  `is_mention_event(event) or any(is_mention_market(child)…)` → False

### R4 — True positives preserved

At least the following classes MUST still classify as mention (table-driven tests):

1. **Ticker/series `MENTION`** — e.g. `KXFTNMENTION-…` / `KXEARNINGSMENTIONCCL-…`
   even if titles were empty.
2. **Title-driven say event** — e.g. title
   `What will Carnival Cruise say during their next earnings call?` with non-MENTION
   ticker material still matching `SAY_EVENT_RE` / say phrasing as today when applicable.
3. **Title-driven bare mention language** — e.g. title contains “mentions” /
   “mentioned” product language without rules fields.
4. Existing MS-0006 classifier fixtures remain valid **after** admission (type layer
   unchanged). Binary gate tests may reuse the same event shapes.

True-positive fixtures MUST demonstrate a match with **empty/absent rules fields**
(or rules fields that do not contain mention boilerplate), so tests do not
accidentally depend on rules.

### R5 — `--contains` may still search rules

`contains_filter` SHOULD continue to use full market text including
`rules_primary` / `rules_secondary` unless a future approved spec changes substring
search. This MS deliberately **splits** gate text from contains/display text.

Document in a brief code comment near the helpers:

- gate text = discovery membership
- `text_for_market` = contains + human/rules display source

### R6 — Scan + final filter consistency

Both of the following paths MUST use the corrected `is_mention_market` semantics:

1. Compact discovery: `scan_mention_events` / `scan_paused_mention_markets`
2. Post-cache filter in `main()` (`is_mention_market` ∧ status ∧ contains ∧ type)

No alternate “rules-inclusive” admission path may remain for binary membership.

### R7 — Watch / email / queue inherit fix

No separate watch classifier. After R1–R6, `--watch-new` must not alert on the
tariff parent when the child snapshot is built through the normal one-shot path.
No real email in tests; pure unit tests on classifiers + optional pure helper that
mirrors the scan admission boolean are sufficient.

### R8 — MS-0006 intact

- Do not change type registry, priority, subjects, `--type` parsing, or aliases
  except incidental import/test wiring.
- Type continues to run only on mention-admitted inventory.
- Existing `tests/test_mention_types.py` MUST remain passing.

### R9 — Compatibility / guardrails

- No trading paths.
- No real email during implementation/verification.
- Preserve `./mention_scout.py` and versioned implementation filename policy.
- No deliberate CLI default changes.
- No `CACHE_FORMAT_VERSION` / queue format bump required or permitted solely for this bugfix.
- Network timeout/retry behavior unchanged.
- Do not commit secrets, `.env`, private caches, or live email contents.
  The checked-in MS-0007 fixture is public market metadata only (OK).

### R10 — Failure behavior

| Case | Behavior |
|------|----------|
| Missing title/rules fields | Gate uses empty strings; no exception |
| Stale compact cache still holding tariff market from before fix | Final `is_mention_market` filter MUST drop it on read (R6); user may also `--refresh` |
| True mention event, child title thin but parent ticker has MENTION | Unchanged: parent match may keep children per existing scan loop |
| `--contains incidentally` on a non-mention market | May still match substring on rules via contains **without** making it a mention market |

## Acceptance criteria

- [ ] `is_mention_market` no longer matches solely due to `rules_primary` / `rules_secondary` text.
- [ ] Fixture `KXGENERICTARIFF-26JUL` / nested `…-NOV03`: parent event false, market false, scan-admission boolean false.
- [ ] True-positive tests pass for ticker-`MENTION`, title mention language, and title say-language cases without rules boilerplate.
- [ ] `contains_filter` still searches rules text (regression assertion).
- [ ] `tests/test_mention_types.py` (MS-0006) still passes unchanged in intent.
- [ ] No cache/queue format version change; no CLI default change; no trading; no real SMTP in CI.
- [ ] `./scripts/factory-test.sh` passes (compile, help/version smokes, pytest).
- [ ] Independent verification PASS + explicit owner ship approval before release.

## Test plan

All **offline**. No live Kalshi required for unit tests. **No real SMTP.**

### New tests (recommended file)

`tests/test_mention_gate.py` (or extend a dedicated binary-gate module; do not overload
MS-0006 type tests with unrelated rules-boilerplate cases beyond a thin cross-check).

1. **Load MS-0007 fixture**
   - Parse `.factory/tasks/MS-0007-fixture-KXGENERICTARIFF-26JUL.json`
     **or** a copied `tests/fixtures/KXGENERICTARIFF-26JUL.json`.
   - Assert `is_mention_event` is False.
   - Assert nested market `is_mention_market` is False.
   - Assert admission boolean
     `is_mention_event(event) or any(is_mention_market(m) for m in nested)` is False.
   - Sanity: raw `rules_secondary` still contains the word “mention” (documents poison).
   - Sanity: gate text / pre-fix path would have matched if rules were included
     (optional characterization test via helper that builds rules-inclusive text, or
     a one-line comment + assert on rules string). Prefer testing public helpers only.

2. **True positives (rules empty or irrelevant)**
   - Market/event with `event_ticker`/`ticker` containing `MENTION` → True.
   - Title `What will Jane say about inflation tomorrow?` (or existing SAY pattern) → True
     via `SAY_EVENT_RE` without rules.
   - Title with product “mentions” language → True without rules.
   - Earnings/FTN-shaped tickers still True.

3. **Contains vs gate split**
   - Non-mention market with rules containing unique token `ZYXCONTAINSRULES` →
     `is_mention_market` False, `contains_filter(..., "zyxcontainsrules")` True.

4. **Parent-vs-child consistency**
   - Parent with MENTION series and quiet child titles: existing semantics preserved
     (`is_mention_event` True); child retention rules unchanged.

5. **MS-0006 regression**
   - Run full `tests/test_mention_types.py`.

### Explicit non-tests

- No `--test-email` against real Gmail.
- No mandatory live `--watch-new` against prod in CI (manual smoke optional for owner).
- No trading API calls.

Independent verification: clean worktree, `./scripts/factory-test.sh`, spot-check fixture assertions.

## Compatibility

| Surface | Expectation |
|---------|-------------|
| CLI defaults | Unchanged |
| `--contains` | Still searches full market text **including rules** |
| `--type` / subjects / labels | Unchanged (MS-0006) |
| Cache file names / `CACHE_FORMAT_VERSION` | Unchanged |
| Queue format | Unchanged |
| JSON schema | Unchanged (additive fields not required) |
| `text_for_market` field set | Prefer keep including rules for contains/display; gate uses separate helper or explicit field list |
| Stable `./mention_scout.py` | Same behavior as `kalshi_mention_scout.py` |
| Trading posture | Still discovery/notification only |

**Inventory compatibility note:** compact caches written *before* the fix may still
contain false-positive tickers until TTL expiry or `--refresh`. Final filter MUST
drop them via corrected `is_mention_market` even without a cache bump (R6 / R10).

**Intentional behavior change:** markets previously admitted only via rules
boilerplate will disappear from mention inventory. That is the bug fix.

## Non-goals

- Not a general Kalshi rules NLP cleaner.
- Not a type-taxonomy expansion.
- Not an SMTP or watch-loop rewrite.
- Not a cache migration.
- Not changing `"MENTION" in ticker` fast-path.

## Risks

| Risk | Mitigation |
|------|------------|
| Miss true market that only says “mention” in rules | Accepted; product signals are ticker/title; covered by owner judgment on this class of markets |
| Future boilerplate in **titles** | Separate issue; do not overfit denylist now |
| Stale compact cache noise until refresh | Final filter drops non-mentions; document `--refresh` |
| Accidental `--contains` behavior change | Explicit R5 + test that contains still sees rules |
| Scope creep into regex rewrite | Spec forbids primary Option B unless owner revises |

## Open questions for owner

Only real forks; recommended defaults in **bold**.

1. **Primary fix:** Approve **Option A** (exclude `rules_primary` / `rules_secondary` from binary mention gate; keep rules in `--contains` / display)?  
   - Alternative: also strip rules from `--contains` (not recommended).

2. **Defense-in-depth:** Keep **no** boilerplate denylist and **no** `MENTION_RE` tighten in this MS?

3. **Fixture location:** Tests may read the existing task fixture path in-repo, or implementer copies to `tests/fixtures/` — **either OK** if path is stable in CI.

4. **VERSION bump:** Bugfix only — **no marketing version bump required** unless owner wants one at ship time.

If owner approves with defaults, implementer proceeds without further design discussion.

## Recommended defaults (for owner approval)

| Topic | Recommendation |
|-------|----------------|
| Fix | Option A: mention-gate text excludes rules; `text_for_market` keeps rules for contains/display |
| Regex | Leave `MENTION_RE` / `SAY_EVENT_RE` unchanged |
| Boilerplate denylist | Not in this MS |
| MS-0006 | Untouched |
| Cache / CLI defaults | Untouched |
| Tests | Offline fixture + true positives + contains/gate split; no real email/network |

## Implementation notes (non-normative)

Suggested minimal diff surface in `kalshi_mention_scout.py`:

1. Add `mention_gate_text_for_market(market)` (name flexible) without rules fields.
2. Point `is_mention_market` at gate text; leave `contains_filter` → `text_for_market`.
3. Optional: thin pure helper `event_qualifies_as_mention(event, nested_markets) -> bool`
   matching scan boolean for easier unit tests without HTTP.
4. Add `tests/test_mention_gate.py` (+ optional fixture copy).
5. Do not retouch watch/email code paths unless a stray direct rules check appears
   (none expected beyond shared `is_mention_market`).

Keep the diff small and reviewable. No drive-by refactors.

## Dependencies / sequencing

- Does not block on other MS items.
- Builds on current MS-0006 type layer remaining post-admission.
- Spec approval required before implementation worktree.

## Exit criteria for this specification

- Owner approves or requests revision of this PROPOSED spec (answers to open questions recorded).
- Only after approval may an implementation worktree implement MS-0007.
- No product-code implementation is authorized by this proposal alone.

---

*End of MS-0007 proposed specification.*
