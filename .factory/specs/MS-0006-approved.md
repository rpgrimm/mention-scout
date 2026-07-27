# MS-0006 — Mention type labels, filter, and email subject prefix

Status: **APPROVED**
Approved: 2026-07-27 by owner (GitHub issue #7 comment: “approve MS-0006 with defaults”).  
GitHub issue: https://github.com/rpgrimm/mention-scout/issues/7  
Type: feature (classification + CLI filter + notification UX)  
Related: MS-0002 (stable entry; in flight), MS-0003 (tests suite), MS-0004 (email dry-run)  
Repository: `/home/candr/src/mention_scout`  
Implementation target (after approval): `kalshi_mention_scout.py` (v16 / `VERSION 16.0.0`)  
Stable command: `./mention_scout.py` when present (MS-0002); behavior must match either entry.

---

## Problem

Mention markets span several human-meaningful **families** (earnings calls, Face the Nation, World News Tonight, political “say/mention” series, etc.). Today the scout only answers a binary question: *is this a mention-style market?* It does not label the family, cannot filter discovery/watch output by family, and email subjects for new markets are a single hard-coded shape that buries that context.

On a phone lock screen, subjects like:

```text
[Kalshi] NEW mention market: KXEARNINGSMENTIONCCL-26JUN23
```

are hard to scan. The owner wants the **type early** in the subject (e.g. `earnings`, `Face the Nation`, `World News Tonight`) and a way to **filter** by type.

## Current behavior (verified in v16)

| Area | Behavior |
|------|----------|
| Mention classification | Binary only: `is_mention_event` / `is_mention_market` via `"MENTION"` in ticker/series **or** `MENTION_RE` / `SAY_EVENT_RE` on text fields |
| Substring filter | `--contains` case-insensitive substring on **market** text fields only (`contains_filter` → `text_for_market`) |
| Overview records | Carry `event_ticker`, `title`, `description`, `category`, `series_ticker`, times, statuses, contract count — **no type field** |
| Human one-shot | Grouped/flat/overview prints do **not** show a type label |
| JSON one-shot | Markets + optional `event_overview` — **no type field** |
| Watch new alerts | Terminal banner + `render_overview`; email via `send_new_market_email` |
| Email subject | Hard-coded: `f"[Kalshi] NEW mention market: {ticker}"` in `send_new_market_email` |
| Email body | `format_overview_email` — title, optional category/url/description; **no type line** |
| Sample evidence in tree | Test-email body URL uses `kxearningsmentionccl-…` / Carnival earnings title; comments cite `KXTRUMPMENTION`, `KXTRUMPSAY` |
| Public series evidence (external, for taxonomy seeds) | Face the Nation ≈ `kxftnmention`; World News Tonight ≈ `kxworldnewsmention` |

Filtering today cannot express “only earnings” or “only Face the Nation” without brittle `--contains` guesses that also miss series-ticker structure.

## Goal

Add a small, **deterministic** mention-**type** layer that:

1. **Classifies** each parent mention event (and, where needed, child markets) into a human-meaningful type label.
2. **Filters** one-shot and watch discovery by one or more types via a new CLI flag (default = all types → backward compatible inventory).
3. Puts the type **early** in `--watch-new --email-new` subjects so mobile notifications are scannable.
4. Surfaces the same type in human/JSON one-shot (and watch baseline/new prints) for consistency.

No trading. No SMTP rewrite. Prefer pure helpers + offline unit tests over LLM classification.

## Scope

### In scope

1. **Type derivation helper(s)** (pure functions), e.g.:
   - `mention_type_for_event(event_like: dict) -> str` (and/or structured result)
   - optional thin wrapper for market-level records that delegates to parent series/event fields when present
   - `format_new_market_email_subject(event_like: dict) -> str` (or equivalent pure subject builder)
2. **Deterministic taxonomy** seeded from series/event ticker patterns + title keywords; documented map; fallback type for unmatched mention events.
3. **CLI type filter** (name TBD by owner; recommendation below): default off/absent = no type restriction.
4. **Apply filter** in the same post-cache selection path as `--contains` (and therefore in watch child snapshots, which reuse one-shot JSON with forwarded argv).
5. **Email subject** uses type prefix convention below for `--email-new` new-market mail.
6. **Display type** in:
   - human overview / grouped headers (at least overview and watch new overview)
   - JSON `event_overview[]` (and optionally each market record — recommendation below)
   - email body one-line `Type: …` (cheap consistency; not a substitute for subject)
7. **Regression tests** for classifier, filter match semantics, and subject builder (offline fixtures; no real SMTP).
8. **Watch argv forwarding**: ensure new flag is **not** stripped by `_watch_child_arguments` (today only watch/email/queue/poll/smtp options are stripped; `--contains` already forwards — same pattern).

### Out of scope

- Trading, order placement, or portfolio logic.
- LLM / remote classification services.
- Full taxonomy admin UI, config file editor, or user-defined plugins (a small in-code map is enough for this MS).
- Rewriting SMTP/`swaks` infrastructure (MS-0004 dry-run is complementary, not required to ship pure subject/classifier tests).
- Changing binary mention detection rules (`is_mention_*`) except calling type labeling **after** an event/market is already a mention candidate.
- Cache format version bump (type is derived at display/filter time from existing fields; do **not** require persisting type in cache for v1).
- Changing default email addresses, credential paths, poll interval, window/status defaults.
- Filtering non-mention inventory or expanding product beyond mention scout.
- Localization of type labels beyond a single English display form per type id.

### Optional stretch (off unless owner opts in)

- `--list-types` printing the known type ids + display labels and exiting.
- Persist `mention_type` into queue job JSON for opener consumers.
- Multiple types per event (v1 is **single primary type**).

## Type taxonomy design

### Principles

1. **Deterministic and testable** — ordered rules, no network, no randomness.
2. **Stable machine id + human display label** — filter uses machine ids; subjects/UI use display labels.
3. **Series/event ticker first** — Kalshi families are usually encoded in `series_ticker` / `event_ticker` (e.g. `KXEARNINGSMENTIONCCL`, `KXFTNMENTION`, `KXWORLDNEWSMENTION`).
4. **Title/description keywords second** — for families with messy tickers or missing `series_ticker`.
5. **Category last / weak signal only** — overview already has free-text `category`; use only if it clearly maps and does not override a stronger ticker hit.
6. **Single primary type** per event for v1 (first match wins in documented priority order).
7. **Fallback** — every mention event gets a type; unmatched → `other` (display: `other`).

### Recommended type registry (v1 seed)

| Type id (filter key) | Display label (subject/UI) | Primary match signals (case-insensitive) | Example tickers / titles |
|----------------------|----------------------------|------------------------------------------|---------------------------|
| `earnings` | `earnings` | series/event ticker contains `EARNINGSMENTION` or `\bEARNINGS?\b` + `MENTION`; title/description match earnings-call phrasing (“earnings call”, “during their next earnings”) | `kxearningsmentionccl-26jun23` — “What will Carnival Cruise say during their next earnings call?” |
| `face-the-nation` | `Face the Nation` | series/event ticker matches `FTNMENTION` / `FACETHENATION` / `FACE_THE_NATION`; title contains “Face the Nation” | `kxftnmention-26jul05` |
| `world-news-tonight` | `World News Tonight` | series/event ticker matches `WORLDNEWSMENTION` / `WORLDNEWS`; title contains “World News Tonight” (or “World News Mention” series naming) | `kxworldnewsmention-26jul25` |
| `trump` | `Trump` | series/event ticker matches `TRUMPMENTION` / `TRUMPSAY` (code comments); title clearly Trump mention/say family **without** a more specific show rule winning first | `KXTRUMPMENTION…`, `KXTRUMPSAY…` |
| `say` | `say` | residual “what will X say” / `SAY` series that is mention-classified but not a more specific family (optional bucket — see owner Q) | generic `…SAY…` series |
| `other` | `other` | no rule matched | any other mention event |

> **Note:** `trump` and `say` are **plausible** families evidenced by in-code comments (`KXTRUMPMENTION`, `KXTRUMPSAY`). They are proposed so the map is not only the three owner examples. Owner may drop/rename them or require a closed list of only the three named shows + earnings + `other`.

### Matching algorithm (normative sketch)

Inputs for an overview/event-like dict (preferred):  
`series_ticker`, `event_ticker`, `title`, `description` (and `sub_title` if present on raw event), optional `category`.

For a child market without parent fields: use `ticker`, `event_ticker`, `title`, `subtitle`, rules text only as weak fallback; prefer parent overview fields when classifying watch/email events.

```text
text_ticker = upper(series_ticker + " " + event_ticker [+ market ticker if needed])
text_title  = title + " " + description + " " + sub_title   # original case for display; casefold for match

1. Apply ordered RULES (specific → general). First hit wins.
2. Each rule: if any of (ticker_regex, title_regex) matches → return that type id.
3. Else return type id `other`.
```

**Priority order (recommended):**  
`face-the-nation` → `world-news-tonight` → `earnings` → `trump` → `say` → `other`

Rationale: show-specific series should not collapse into generic `say`/`other`; earnings before residual political buckets.

### Display vs filter keys

- CLI filter accepts **type ids** (`earnings`, `face-the-nation`, …), case-insensitive.
- Recommend also accepting common aliases: `ftn` → `face-the-nation`, `wnt` / `world-news` → `world-news-tonight`.
- Subjects and human UI print **display labels** (`Face the Nation`, not `face-the-nation`).
- Unknown filter tokens → clear non-zero exit / `SystemExit` with list of known ids (fail fast), not silent ignore.

### Extensibility

Keep the rule table in one obvious module-level structure (list of dataclasses/tuples) so adding a series is a data change + tests, not a new code path. Document in code comment that owner-requested families should be added here.

## Concrete examples

| Scenario | series / event (illustrative) | Type id | Display | Email subject (see format) |
|----------|-------------------------------|---------|---------|----------------------------|
| Carnival earnings | `KXEARNINGSMENTIONCCL` / `kxearningsmentionccl-26jun23` | `earnings` | `earnings` | `[Kalshi] earnings \| NEW: KXEARNINGSMENTIONCCL-26JUN23` |
| Face the Nation episode | `KXFTNMENTION` / `kxftnmention-26jul05` | `face-the-nation` | `Face the Nation` | `[Kalshi] Face the Nation \| NEW: KXFTNMENTION-26JUL05` |
| World News Tonight | `KXWORLDNEWSMENTION` / `kxworldnewsmention-26jul25` | `world-news-tonight` | `World News Tonight` | `[Kalshi] World News Tonight \| NEW: KXWORLDNEWSMENTION-26JUL25` |
| Trump mention series | `KXTRUMPMENTION…` | `trump` | `Trump` | `[Kalshi] Trump \| NEW: KXTRUMPMENTION-…` |
| Unmapped mention | e.g. novel `KXSOMETHINGMENTION…` with no rule | `other` | `other` | `[Kalshi] other \| NEW: KXSOMETHINGMENTION-…` **or** legacy-style if owner chooses “prefix only when known” (Q below) |
| Title-only FTN (missing series) | series empty; title “Face the Nation Mentions — Jul 5” | `face-the-nation` | `Face the Nation` | same FTN subject shape |

## CLI design

### Recommended flag

```text
--type TYPE
```

- Repeatable **or** comma-separated values (pick one in implementation; **recommend comma-separated single flag** for simpler argv forwarding:  
  `--type earnings,face-the-nation`).
- Alternate long name `--types` as an alias is fine if low-cost.
- **Default:** omit flag → **no type filter** (all types). Inventory matches today aside from intentional subject/display additions.
- Match semantics: **any-of** (OR) across the provided type ids.
- Combine with `--contains` using **AND**:
  - keep market/event if `(passes type filter) ∧ (passes contains filter) ∧ (existing mention/status/window filters)`.
- Type filter applies at **event level** for overview/watch/email (drop entire parent if its type ∉ selected set). For flat/grouped contract views, drop contracts whose resolved parent/event type ∉ selected set (same classification source as overview when parent metadata exists).
- Invalid type token: exit non-zero with actionable message listing known type ids (and aliases if any).
- Empty `--type` value: treat as usage error.

### Help text (sketch)

```text
--type TYPE   Keep only mention events of these types (comma-separated).
              Known: earnings, face-the-nation, world-news-tonight, trump, say, other.
              Default: all types.
```

### Interaction matrix

| Flags | Result |
|-------|--------|
| _(neither)_ | All mention events (today’s inventory); subjects/display may still show type |
| `--contains ftn` | Substring on market text only (unchanged semantics) |
| `--type face-the-nation` | Only FTN-typed events |
| `--type earnings,world-news-tonight` | Either type |
| `--type earnings --contains carnival` | Earnings family **and** market text contains “carnival” |
| `--type nope` | Error, no scan required after parse |

### Watch mode

Because watch builds a child one-shot with `--overview --json --refresh` and forwards unknown flags, `--type` must remain on the child argv so baseline + new-event detection only see the filtered inventory. Document that baseline `known_event_tickers` is computed **after** type filter (same as `--contains` today). Changing type mid-process requires restart (acceptable; same as other filters).

## Email subject format (normative)

### Recommended always-on typed subject

For every `--email-new` new-market message:

```text
[Kalshi] {display_label} | NEW: {event_ticker}
```

Examples:

```text
[Kalshi] earnings | NEW: KXEARNINGSMENTIONCCL-26JUN23
[Kalshi] Face the Nation | NEW: KXFTNMENTION-26JUL05
[Kalshi] World News Tonight | NEW: KXWORLDNEWSMENTION-26JUL25
[Kalshi] other | NEW: KXSOMETHINGMENTION-26AUG01
```

### Formatting rules

- Prefix remains `[Kalshi]` for continuity with test mail and existing mental model.
- Display label immediately after the bracket tag (early / lock-screen visible).
- ASCII separator ` | ` between label and `NEW:`.
- `NEW:` shortens today’s `NEW mention market:` to keep mobile subject length reasonable once type is added.
- `{event_ticker}` is the parent event ticker (same identity as today).
- Do **not** put secrets, recipient, or body excerpts in the subject.
- `--test-email` subject may remain `[Kalshi] mention scout SMTP test` (out of scope to restyle) unless owner wants a sample typed subject there too.

### Deliberate compatibility note (call-out)

**Today’s subject string changes for all `--email-new` alerts if this ships with the recommended always-on format.** That is a deliberate notification UX change, not an invisible refactor.

Owner must choose (see questions):

1. **Always** use typed subject (including `other`), or  
2. Use typed subject only when type ≠ `other`, else keep legacy  
   `[Kalshi] NEW mention market: {ticker}`, or  
3. Gate new subjects behind a flag (not recommended — extra surface).

**Spec default recommendation:** option 1 (always typed), simple and scannable.

### Email body

Add after title (or after ticker):

```text
Type: Face the Nation
```

No other body redesign in this MS.

## One-shot / watch human + JSON output

**Recommendation: yes, show type for consistency.**

| Surface | Change |
|---------|--------|
| `event_overviews()` records | Add `mention_type` (id) and optionally `mention_type_label` (display). Minimum: one field; if only one, store **id** and derive label at render/subject time from registry. |
| Human `render_overview` | Print `type: {display_label}` near category. |
| Watch new banner path | Inherits overview render. |
| Grouped/flat human | Optional one-line type on event header; **recommend at least overview**; grouped header is nice-to-have in same MS if cheap. |
| JSON root | No schema version field required; additive keys only. |
| Market records in JSON | **Recommend** additive `mention_type` on each market record *or* rely on `event_overview` only. Prefer setting on **event_overview** always; add per-market only if flat JSON users need it without joining — owner call; default **event_overview + overview human**, per-market optional same MS if tests stay small. |

Without `--type`, output count/order matches pre-change filtering; only additive fields/lines appear (plus subject change for email).

## Compatibility

| Surface | Expectation |
|---------|-------------|
| CLI defaults (days/window/status/cache/email addresses) | Unchanged when new flag omitted |
| `--contains` | Unchanged semantics; AND with `--type` |
| Cache file names / `CACHE_FORMAT_VERSION` | Unchanged (derive type at runtime) |
| Queue format | Unchanged unless stretch opted in |
| Binary mention detection | Unchanged predicates; type is additional labeling |
| JSON | Additive fields only; old keys remain |
| `kalshi_mention_scout.py` / stable symlink entry | Both must behave identically |
| Trading posture | Still discovery/notification only |
| Real email in tests | Forbidden; unit-test pure subject builder |

**Backward compatible inventory:** omitting `--type` does not drop events.

**Not fully subject-backward-compatible:** email subjects change under recommended default — requires explicit owner acceptance.

## Failure behavior

| Failure | Handling |
|---------|----------|
| Unknown `--type` token | `SystemExit` / argparse error with known ids; no partial filter |
| Missing series/title fields | Classifier still returns `other` (or keyword hit); never throws on empty strings |
| Type filter excludes all | Same empty-result UX as other filters (yellow message / empty JSON arrays); watch baseline may be 0 events — valid |
| Email send failure | Unchanged: log error, continue watch loop |
| Subject builder given empty ticker | Fallback stable string (e.g. `new mention market`) as today |

No new network calls. No new secret handling.

## Test plan

All offline. **No real SMTP.** No live Kalshi requirement for unit tests.

### Unit tests (pure)

1. **Classifier fixtures** (table-driven):
   - earnings ticker/title → `earnings`
   - FTN ticker/title → `face-the-nation`
   - WNT ticker/title → `world-news-tonight`
   - trump/say comment-shaped tickers if those types kept
   - empty metadata → `other`
   - priority: title “earnings” must not override FTN series if both somehow present (construct adversarial fixture)
2. **Subject builder**:
   - each display label produces exact normative string
   - special characters in ticker preserved
3. **Filter helper**:
   - any-of multi-type
   - case-insensitive ids / aliases
   - AND composition with a mocked contains predicate or integration through `contains_filter` + type check
4. **Invalid type token** parsing/validation.

### Integration / smoke (lightweight)

- `py_compile` + `--help` shows `--type`.
- If `tests/` exists (MS-0003) or is introduced here minimally: `pytest` on new tests.
- Do **not** require MS-0004 to merge; note MS-0004 makes end-to-end email body/subject capture easier later. Until then, pure subject function coverage is sufficient for this MS.

### Explicit non-tests

- No `--test-email` against real Gmail in CI/factory verification.
- No trading API calls.

Independent verification repeats unit tests on a clean worktree and confirms help/defaults.

## Acceptance criteria

- [ ] Deterministic `mention_type` (id) derived for mention events from series/event ticker and title/description rules with documented priority.
- [ ] Seed types include at least: `earnings`, `face-the-nation`, `world-news-tonight`, and fallback `other` (plus any owner-approved extras).
- [ ] CLI `--type` (or approved name) filters inventory with **any-of** semantics; default omitted = all types.
- [ ] `--type` combines with `--contains` using **AND**.
- [ ] Invalid type tokens fail fast with actionable error.
- [ ] `--watch-new --email-new` subjects follow the approved normative format with type early (owner-approved always vs legacy-for-other).
- [ ] Email body includes a `Type:` line.
- [ ] One-shot overview human output shows type; JSON `event_overview` includes type id (additive).
- [ ] Watch child argv still applies `--type` (flag not stripped).
- [ ] Offline unit tests cover classifier, filter match, and subject builder; no real email; no secrets committed.
- [ ] No trading paths; no CLI default/cache format regressions when `--type` omitted.
- [ ] Independent verification PASS + explicit owner ship approval before release.

## Implementation notes (non-normative)

Suggested shape (implementer freedom within requirements):

```python
@dataclass(frozen=True)
class MentionType:
    id: str
    label: str

MENTION_TYPES: dict[str, MentionType] = {...}
TYPE_RULES: list[tuple[MentionType, re.Pattern, re.Pattern | None]] = [...]

def classify_mention_type(*, series_ticker, event_ticker, title, description, category=None) -> MentionType: ...
def format_new_market_email_subject(event: dict[str, Any]) -> str: ...
def event_matches_types(event: dict[str, Any], selected: set[str] | None) -> bool: ...
```

Wire `send_new_market_email` to call `format_new_market_email_subject`.  
Populate type on `event_overviews` output.  
Parse `--type` once in `main` / watch path into a frozenset of ids.

Keep diff focused; avoid drive-by refactors.

## Owner questions

1. **Closed list vs open-ended map:** Approve the v1 seed table (earnings / Face the Nation / World News Tonight / trump / say / other), only the three named families + `other`, or a different closed list? Should `trump` and `say` ship in v1?
2. **Subject when type is `other`:** Always `[Kalshi] other | NEW: …`, or keep legacy `[Kalshi] NEW mention market: …` when unknown?
3. **Subject change scope:** Confirm always-on subject redesign for all `--email-new` mail (recommended), vs opt-in flag.
4. **Case / punctuation in subjects:** Approve display labels as given (`Face the Nation`, `World News Tonight`, lowercase `earnings` / `other`)? Or force Title Case for all?
5. **Filter flag spelling:** `--type` with comma-separated ids (recommended) vs repeatable `--type` / `--types` only?
6. **Filter match semantics:** Confirm **any-of** (OR) for multiple types (recommended).
7. **Baseline watch print:** Should watch baseline overview show type lines (recommended yes)?
8. **JSON per-market field:** Require `mention_type` on every market object, or event_overview only for v1?
9. **Aliases:** Allow `ftn`, `wnt` shortcuts in `--type`?
10. **`say` vs `other`:** Prefer a residual `say` bucket for SAY-series, or fold those into `other` until requested?

## Risks

| Risk | Mitigation |
|------|------------|
| Misclassification of new Kalshi series | Fallback `other`; easy rule-table extension; tests for known seeds |
| Over-filtering with wrong type id | Fail fast on unknown ids; default no filter |
| Subject change surprises mail filters/habits | Explicit owner approval; document examples in issue/spec |
| Scope creep into huge taxonomy | v1 seed only; no LLM; single primary type |
| Watch baseline vs alert inconsistency | Same classifier + filter on child JSON path |
| Coupling to MS-0003/0004 | Pure functions testable standalone; dry-run optional follow-on |

## Non-goals (restated)

- Not a trading bot.
- Not a general Kalshi category browser.
- Not ML/LLM labeling.
- Not an SMTP stack rewrite.
- Not a cache migration.

## Dependencies / sequencing

- **Does not block on** MS-0002 (can implement against `kalshi_mention_scout.py`; stable name should keep parity once present).
- **Benefits from** MS-0003 (`tests/` layout) but may add minimal tests path if 0003 not merged.
- **Benefits from** MS-0004 (email dry-run) for manual/E2E subject checks; **not a hard blocker** if subject builder is unit-tested.
- Issues 0003–0005 remain separate reserved work.

## Exit criteria for this specification

- Owner approves or requests revision of this PROPOSED spec (answers to owner questions recorded).
- Only after approval may an implementation worktree implement MS-0006.
- No product-code implementation is authorized by this proposal alone.

---

## Recommended defaults (for owner approval)

| Topic | Recommendation |
|-------|----------------|
| Taxonomy | Deterministic rule table; seed: `earnings`, `face-the-nation`, `world-news-tonight`, `trump`, `say`, `other` |
| Filter flag | `--type` comma-separated ids; default all; any-of; AND with `--contains` |
| Subject | Always `[Kalshi] {label} \| NEW: {event_ticker}` including `other` |
| Labels | Mixed natural display (`Face the Nation`, `earnings`) |
| Output | Show type on overview human + JSON event_overview; email body `Type:` line |
| Aliases | `ftn`, `wnt` optional yes |
| Tests | Pure unit tests; no real SMTP; MS-0004 helpful later |

---

*End of MS-0006 proposed specification.*


## Owner decisions (approved)

Approved with recommended defaults (2026-07-27):

1. Taxonomy seed: `earnings`, `face-the-nation`, `world-news-tonight`, `trump`, `say`, `other`
2. Filter: `--type` comma-separated; default all types; any-of (OR); AND with `--contains`
3. Subject always: `[Kalshi] {display_label} | NEW: {event_ticker}` including `other`
4. Display labels as specified (e.g. `Face the Nation`, `World News Tonight`, `earnings`)
5. Type on human overview + JSON `event_overview`; email body `Type:` line
6. Watch baseline overview shows type: yes
7. Aliases: `ftn` → `face-the-nation`, `wnt`/`world-news` → `world-news-tonight`
8. Keep residual `say` and `trump` buckets
9. JSON: type on `event_overview` (and market records if low-cost / recommended in spec body)
10. No LLM; pure deterministic rules + offline unit tests; no real email in verification

