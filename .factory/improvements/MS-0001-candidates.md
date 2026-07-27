# MS-0001 — Ranked improvement candidates

Audit date: 2026-07-25  
Basis: read-only inspection of `kalshi_mention_scout.py` (v16 behavior), factory contracts, scripts, and repo layout.  
No product code was modified.

## Ranking criteria

Candidates scored qualitatively on:

- **User value** — reliability of discovery/notification or day-to-day command surface
- **Effort** — small/medium relative to the ~2k-line monolith
- **Regression risk** — impact on CLI defaults, cache formats, watch/email behavior
- **Testability** — can be verified without real network, SMTP, or secrets

Guardrails applied: no trading; preserve CLI defaults and cache compatibility unless a deliberate approved spec says otherwise; email only via mocks/dry-run in automated work; prefer discovery/notification purpose.

---

## Ranked candidates

### 1. Restore stable `./mention_scout.py` command surface (recommended first)

| Dimension | Assessment |
|-----------|------------|
| User value | **High** — AGENTS/standards already document `./mention_scout.py` as the stable user command; it is missing from the repo root. Users and future factory steps that follow written guardrails get a broken entrypoint. |
| Effort | **Very low** — add a symlink (or tiny wrapper) to the current implementation; document relationship to `kalshi_mention_scout.py`. |
| Regression risk | **Very low** — no Python behavior change if the stable name only delegates; existing `kalshi_mention_scout.py` invocations unchanged. |
| Testability | **High** — `factory-test.sh` / smoke can assert both paths exist, resolve equivalently, and both `--help`/`--version` succeed. No network or email. |

**Why first:** Closes an immediate product/factory contract gap with almost no behavioral surface. Unblocks the documented “preserve versioned implementation + stable symlink” release model without rewriting the monolith. Does not require cache or CLI default changes.

**Suggested follow-on (same theme, later):** materialize true versioned filename (`kalshi_mention_scout_v16.py`) and point both stable names at it — slightly higher process risk (symlink policy), still no logic change.

---

### 2. Seed a minimal deterministic `tests/` suite for pure core logic

| Dimension | Assessment |
|-----------|------------|
| User value | **High (indirect)** — enables safe future changes to date parsing, status filtering, cache usability, duplicate/new-event detection; standards already require regression tests for those areas. |
| Effort | **Low–medium** — extract nothing at first; test pure functions already present (`cached_market_status`, `event_schedule_for_market`, `cache_usable`, `is_mention_*`, `kalshi_event_url`, `_watch_event_map` / new-ticker set math with fixtures). |
| Regression risk | **Low** — tests-only change if no production edits; medium only if light refactors for importability are needed (prefer `py_compile` + running functions via import of the module as-is). |
| Testability | **Excellent** — no network/email if fixtures are local dicts/ISO strings. |

**Why not first:** Highest long-term leverage, but does not fix a user-visible missing command. Best **immediate second** task after the stable entrypoint exists so CI/`factory-test.sh` actually runs pytest.

---

### 3. Email dry-run / injectable send seam for safe verification

| Dimension | Assessment |
|-----------|------------|
| User value | **Medium–high** — owners can validate message content and watch+email wiring without risking real SMTP; factory policy forbids real email in automated testing, but code has no first-class dry-run. |
| Effort | **Low–medium** — e.g. `--email-dry-run` printing subject/body/recipient to stderr or a sink file; optional callable injection around `run_swaks_email`. |
| Regression risk | **Low** if default remains real send when flags unset; must not log password. |
| Testability | **High** with dry-run or mocked sender. |

**Scope caution:** Keep defaults identical; never print `GOOGLE_PASSWORD`. Good companion once tests/ exist.

---

### 4. Actionable watch-refresh failure summary + optional backoff

| Dimension | Assessment |
|-----------|------------|
| User value | **Medium** — watch already continues after refresh failure; clearer structured errors (exit code, stderr excerpt already partially shown) and gentle backoff on repeated failures would improve long-run operator experience. |
| Effort | **Low–medium** |
| Regression risk | **Low–medium** — timing/backoff changes can surprise operators if default poll behavior changes; prefer additive diagnostics first. |
| Testability | **Medium** — needs stubbed `fetch_watch_snapshot` or subprocess fake. |

Useful, but less foundational than stable CLI + tests.

---

### 5. Align on-disk versioning with factory release model

| Dimension | Assessment |
|-----------|------------|
| User value | **Medium (process)** — `kalshi_mention_scout.py` currently *is* v16 content without a versioned sibling file; release-policy text assumes symlink updates after verification. |
| Effort | **Low** mechanically (copy/rename + symlink), **medium** process-wise (update `project.yaml`, factory-test entry resolution, docs). |
| Regression risk | **Medium** if packaging or habits break; **low** if done as pure rename+symlink with smoke tests. |
| Testability | **High** (path resolution checks). |

Natural extension of candidate 1; can be one combined MS if the owner wants full naming alignment immediately, or staged after the stable `mention_scout.py` name exists.

---

### Deferred / not recommended as first change

| Idea | Why defer |
|------|-----------|
| Split monolith into packages | High effort, high regression risk, weak immediate user value |
| Change CLI defaults (poll, window, status) | Violates “preserve defaults” without strong owner-driven reason |
| Cache format bump | Only with a functional need; compatibility cost |
| Real SMTP integration tests | Forbidden by factory policy without mocks |
| Trading or order helpers | Out of product scope; prohibited |

---

## Explicit recommendation — best first small high-value change

**Ship MS-0002: add the missing stable `./mention_scout.py` entrypoint** that resolves to the current v16 implementation (`kalshi_mention_scout.py`), without changing Python logic, CLI defaults, or cache formats.

Rationale:

1. Factory and AGENTS already require preserving `./mention_scout.py`; the path is simply absent.
2. Effort and regression risk are minimal compared with logic or email changes.
3. Fully testable offline (existence, symlink/resolve target, `--help` / `--version` parity).
4. Unblocks later versioned-implementation + symlink discipline and matches release-policy language.
5. Leaves behavioral work (tests suite, email dry-run) for subsequent small approved specs once the command surface matches the contracts.

Optional same-spec stretch (owner choice): also introduce `kalshi_mention_scout_v16.py` and make both stable names point at it — still no logic change. Default MS-0002 scope below keeps the stretch **out** unless the owner expands it.

---

## Proposed sequence after MS-0002

1. **MS-0002** — stable `mention_scout.py` command surface  
2. **MS-0003** — minimal `tests/` for pure helpers + wire `factory-test.sh` pytest path  
3. **MS-0004** — email dry-run / mockable send seam  
4. **MS-0005** — versioned implementation filename materialization (if not folded into 0002)  
5. Watch diagnostics / backoff as needed from production use
