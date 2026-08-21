# MS-0014 — Audit calendar-matches + safe add helper

Status: **APPROVED**  
Approved: 2026-08-21 by owner (chat: “approve MS-0014 with defaults”).  
Type: feature (calendar config UX / reliability)  
Priority: P2 (owner-requested after hand-editing match JSON)  
Related: MS-0011 (rich `calendar-matches.json` schema; on main), MS-0012 (watch startup FAIL email; **approved, not implemented** — complementary), MS-0010 (calendar auto-add + match load), MS-0013 (`--invite-email`; orthogonal), MS-0004 (email dry-run seam; complementary), MS-0008 (systemd user watch)  
Repository: `/home/candr/src/mention_scout`  
Implementation target: `kalshi_mention_scout.py` (current `VERSION 16.1.0` on main; bump on ship per release policy)  
Stable command: `./mention_scout.py`  
GitHub: https://github.com/rpgrimm/mention-scout/issues/23  
Review publication: **feature branch `openclaw/ms-0014` + pull request into `main`** (do not push straight to `main`)  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0014`

## Owner decisions (frozen)

1. **CLI home:** both audit and add modes inside `./mention_scout.py` (no separate script in v1).
2. **Audit flag:** `--audit-calendar-matches`.
3. **Add flags:** `--add-calendar-match` + required `--match`; optional `--time`, `--duration-minutes`, `--dry-run`.
4. **Audit email default:** attempt FAIL email on audit failure; opt out with `--no-email-on-fail`. Support `--email-on-fail` as explicit on (default on).
5. **Audit success email:** never (stdout only).
6. **Add when file missing:** create valid v1 file (mkdir parent as needed); do not invent `default_time`.
7. **Duplicate match (case-insensitive):** update in place when `--time` and/or `--duration-minutes` provided; `already-present` no-op when only `--match` matches existing.
8. **Plain string vs object:** string when neither time nor duration set; object when either set. Do not force-convert unrelated existing strings.
9. **`--time` / `--duration-minutes`:** both optional.
10. **`--dry-run`:** supported for add; never writes.
11. **CLI change `default_time`:** out of scope v1.
12. **Add mode email on failure:** no (stderr only; point at audit for mailed report).
13. **Canonical rewrite:** write known schema from `CalendarMatchConfig` only; preserve `default_time` + phrases; unknown top-level keys may drop; document.
14. **Exit codes:** 0 success; 1 validation/config/flag errors.
15. **Priority / ordering vs MS-0012:** P2; independent — may implement either order; do not block MS-0012.
16. **GitHub issue:** #23.
17. **VERSION bump on ship:** yes, per release policy.
18. **Docs:** README yes; example file already sufficient unless a tiny tweak helps.
19. **Cron docs:** one optional README example for daily audit; no unit install change.
20. **Audit FAIL subject:** `[Kalshi] FAIL | calendar-matches audit`.
21. **Mutual exclusion:** audit/add are one-shots; conflict with each other and with `--watch-new`, `--email-new`, `--calendar-add-new`, `--queue-initialized`, `--test-email`, `--calendar-auth`, `--invite-email`.
22. **Invalid existing file on add:** refuse write (no clobber); local error only.
23. **Reuse** `load_calendar_match_config` / parse helpers; atomic write (`write_cache_atomic` spirit / shared helper); mock SMTP in tests; no trading; no secrets in mail.
24. **Ship path:** implement on `openclaw/ms-0014`, open PR for owner test; no merge/ship without independent verification PASS + later explicit owner ship approval.
25. **Stable symlink:** do not retarget; preserve `./mention_scout.py`.

Proposed-spec “Open owner questions” section is superseded by this freeze; remaining body is normative except where it still says “recommend” — treat frozen decisions above as authoritative.

---

## Problem

The owner now relies on hand-edited `~/.config/mention-scout/calendar-matches.json` (MS-0010/MS-0011 schema) to gate Google Calendar auto-add. Two real pain points:

1. **Invalid JSON / schema is easy to introduce by hand**, and today the failure mode is primarily **local/terminal** (and, once MS-0012 ships, **only at `--watch-new` startup** when email/calendar side-effects are on). There is **no dedicated one-shot** to validate the file after an edit, from cron, or without starting a full watch. The owner wants an **audit** path that emails actionable details when the file is bad.

2. **Adding a phrase (with optional time/duration) by hand-editing JSON is footgun-prone** (trailing commas, missing quotes, accidental wipe of other phrases, wrong field names). The owner wants a **safe add** helper that reads → validates → merges → atomically writes, using the same schema rules as the loader.

### Authoritative owner intent (2026-08-21)

- Audit calendar-matches JSON; if malformed/invalid schema, **email** the owner with actionable details (not just fail silently / terminal only).
- Safe add-to-calendar-matches helper with flags roughly:
  - `--match` (phrase text)
  - `--time` (HH:MM local, MS-0011 semantics)
  - `--duration-minutes`
- Prefer coherent UX **inside** `./mention_scout.py` unless there is a strong reason for a separate script.
- Must safely read/modify/write with validation, preserve existing entries, atomic write, sensible defaults, clear errors.
- Support MS-0011 object form; keep plain-string backward compatibility where appropriate.
- Design cleanly vs **MS-0012**: reuse validators/formatters; avoid duplicate mail storms; clarify when audit emails vs when MS-0012 covers it.

### Why MS-0012 alone is not enough

MS-0012 (approved, not yet implemented) emails on **`--watch-new` startup/preflight failure** when `--email-new` and/or `--calendar-add-new` is set, including invalid `calendar-matches.json`. That covers the systemd “watch won’t start” incident.

It does **not**:

- validate the file **without** starting watch,
- give a scheduled-friendly one-shot after hand-edits,
- help when the owner is not currently launching watch,
- or provide a safe **write** path for new phrases.

MS-0014 is the **config hygiene** surface; MS-0012 is the **unattended watch start** surface. Both may report bad match JSON, but under different triggers and subjects.

---

## Current behavior (verified in code / docs)

| Area | Behavior |
|------|----------|
| Match path default | `~/.config/mention-scout/calendar-matches.json` (`DEFAULT_CALENDAR_MATCHES_FILE`) |
| Schema (MS-0011, on main) | `version: 1`, optional `default_time`, `phrases[]` of strings or `{match, time?, duration_minutes?}` |
| Load | `load_calendar_match_config(path)` — full validate; `load_calendar_match_phrases` thin wrapper; `CalendarMatchCache` mtime reload |
| Parse helpers | `parse_calendar_local_time`, `parse_calendar_duration_minutes`; casefold dedupe (first wins) |
| Invalid JSON / schema | `RuntimeError` with path + detail (e.g. JSON line/col); watch preflight wraps as `calendar configuration error: …` and **exits** (terminal/journal only today) |
| Write path for match file | **None** — owner hand-edits; only related atomic writers are cache/state (`write_cache_atomic`, `save_calendar_added_state`) |
| One-shots today | `--calendar-auth`, `--test-email` — mutually exclusive with watch/email/calendar-add |
| Email transport | `run_swaks_email` + `load_google_password` / `~/.config/.google-password`; subjects use `[Kalshi] …` |
| MS-0012 (approved, not shipped) | FAIL mail on watch startup only; **one-shots explicitly out of scope** there |
| Atomic write primitive | `write_cache_atomic` already does temp + fsync + `os.replace` + mode `600` — reuse spirit/helper for match file saves |
| Example | `deploy/config/calendar-matches.example.json` shows object form + `default_time` |
| Trading | Never; discovery + notification only |

Illustrative valid file (README / example):

```json
{
  "version": 1,
  "default_time": "18:30",
  "phrases": [
    "simple string",
    {"match": "abc world news tonight", "time": "18:30", "duration_minutes": 30}
  ]
}
```

---

## Goals

1. **Audit one-shot:** `./mention_scout.py --audit-calendar-matches` validates the match file with the **same** loader rules as watch/calendar preflight. On failure, print actionable error and (by default when SMTP is configured) **email** the owner. On success, print a short OK summary (counts, path, optional default_time) and exit 0 — **no email on success** (v1).
2. **Add one-shot:** `./mention_scout.py --add-calendar-match --match "…"` safely appends (or updates, per policy) a phrase with optional `--time` / `--duration-minutes`, preserving other entries and top-level fields, validating before write, atomic replace, clear stdout summary.
3. **Single binary UX:** both modes live in `./mention_scout.py` / `kalshi_mention_scout.py` alongside `--test-email` / `--calendar-auth` (no separate script in v1).
4. **Share code** with existing load/parse path and, where cheap, with MS-0012 formatters (error text, path listings, truncation). Do **not** invent a second schema.
5. **No trading; no real email in tests; no secret contents in mail/logs.**

---

## Scope

### In scope

1. CLI one-shot **`--audit-calendar-matches`** (name recommended below).
2. CLI one-shot **`--add-calendar-match`** plus **`--match`**, optional **`--time`**, optional **`--duration-minutes`**, optional **`--dry-run`**, path via existing **`--calendar-matches`**.
3. Pure helpers:
   - reuse `load_calendar_match_config` for audit and as pre-write validation input,
   - `save_calendar_match_config` / serialize + atomic write,
   - `add_calendar_match_phrase(...)` merge logic,
   - `format_calendar_matches_audit_fail_email` (or shared FAIL-style formatter) — no secrets.
4. Mutually exclusive one-shot rules vs `--watch-new`, `--test-email`, `--calendar-auth`, and each other.
5. Email on **audit failure** (and optional explicit `--email-on-fail` semantics — see defaults).
6. Offline unit tests (load/save/add/audit/email mocked); README short section; example unchanged unless a tiny comment/README only.
7. Docs: relationship to MS-0012 (when which email fires).
8. Preserve CLI defaults when new flags absent; no cache/queue format bumps; no symlink retarget in this MS.

### Out of scope (v1 recommended)

- Separate `scripts/add-calendar-match.py` (prefer in-process CLI).
- Editing / deleting / reordering arbitrary phrases via full CRUD CLI (`--remove-calendar-match`, TUI, etc.).
- Changing `default_time` via CLI (stretch; see open questions — **default out** unless cheap flag wanted).
- Rewriting all plain-string phrases into object form on every save (preserve representation — see design).
- MS-0012 watch-startup FAIL mail implementation (separate approved MS; may land before/after).
- Runtime match reload behavior changes (already mtime-based).
- Google Calendar API calls, OAuth, attendees, trading.
- Cross-process file locking beyond atomic replace (document “don’t concurrent-write” only).
- Success-path “audit OK” email (noise).
- Auto-fix of broken JSON (audit reports; human or add-helper only writes valid docs).
- systemd unit changes (owner may cron audit separately; document example only).

### Optional stretch (off unless owner opts in)

- `--set-default-time HH:MM` / `--clear-default-time`.
- `--list-calendar-matches` pretty print.
- `--remove-calendar-match --match …`.
- Audit success email with `--email-on-success` (not recommended).
- `flock`-style lock file for concurrent add.
- JSONC / comments support (rejected for v1 — stick to stdlib JSON).

---

## Relationship to MS-0012 (normative design boundary)

| Concern | MS-0012 | MS-0014 |
|---------|---------|---------|
| Trigger | `--watch-new` startup/preflight abort when `--email-new` and/or `--calendar-add-new` | Explicit `--audit-calendar-matches` one-shot (and add-helper validation errors — local; email only if audit mode emails) |
| Operator present? | Often no (systemd) | Often yes after hand-edit; also cron-friendly |
| Subject (recommended) | `[Kalshi] FAIL \| mention-scout start` (+ optional class) | `[Kalshi] FAIL \| calendar-matches audit` |
| Body focus | Full startup context (flags, host, many config paths) | Match-file validation only (path, error, schema hints) |
| Invalid match JSON during watch start | **MS-0012 sends** (once shipped) | Not involved unless owner also ran audit |
| Invalid match JSON during audit only | Not involved | **MS-0014 sends** (per email policy) |
| Shared code | `load_calendar_match_config`, password/swaks, truncation, path hygiene | Same loaders; **do not** call MS-0012 `abort_watch_startup` from audit |
| Mail storms | One FAIL per failed watch start (systemd StartLimit) | One email per audit process invocation on failure; **no** loop |

**Avoid double email in one process:** audit and watch-startup are different process starts. Running audit then starting watch with still-bad JSON can yield two emails (audit FAIL + MS-0012 start FAIL) — **accepted and useful** (different subjects/remediation). Do not add cross-process dedupe in v1.

**Implementation order note:** MS-0014 may ship before or after MS-0012. Audit must not depend on MS-0012 helpers existing; if both land, prefer extracting shared “no secrets + truncate error” utilities rather than coupling one-shot audit to watch abort.

---

## Recommended design

### 1. Stay inside `./mention_scout.py`

**Recommend:** two one-shot flags on the existing entrypoint (same pattern as `--test-email` / `--calendar-auth`).

Rationale:

- One mental model and one binary on PATH/systemd docs.
- Reuses argparse, path defaults, SMTP flags, timezone, password file.
- Avoids a second script to package, chmod, and document.
- Factory entry policy already centers `./mention_scout.py`.

Separate script only if owner later wants a tiny dependency-free tool without importing the scout module — **not needed for v1**.

### 2. CLI shapes (recommended)

#### Audit

```bash
# Validate default path; email on failure if SMTP password loadable
./mention_scout.py --audit-calendar-matches

# Explicit path
./mention_scout.py --audit-calendar-matches \
  --calendar-matches ~/.config/mention-scout/calendar-matches.json

# Force email attempt on failure (default recommended: email-on-fail=true)
./mention_scout.py --audit-calendar-matches --email-on-fail

# Local-only validation (cron/CI style without SMTP)
./mention_scout.py --audit-calendar-matches --no-email-on-fail
```

#### Add

```bash
# String-only phrase (no time/duration) — preserve plain-string form
./mention_scout.py --add-calendar-match --match "cnn this morning"

# Rich object phrase
./mention_scout.py --add-calendar-match \
  --match "abc world news tonight" \
  --time 18:30 \
  --duration-minutes 30

# Preview only
./mention_scout.py --add-calendar-match --match "foo" --time 19:00 --dry-run

# Custom path
./mention_scout.py --add-calendar-match --match "bar" \
  --calendar-matches /tmp/matches.json
```

#### Flag summary

| Flag | Role |
|------|------|
| `--audit-calendar-matches` | One-shot validate; exit 0/1; optional FAIL email |
| `--add-calendar-match` | One-shot add/update phrase; requires `--match` |
| `--match TEXT` | Phrase match string (required with add) |
| `--time HH:MM` | Optional 24h local time (MS-0011 parse rules) |
| `--duration-minutes N` | Optional whole minutes > 0 (phrase override) |
| `--dry-run` | With add: print resulting entry + would-write path; **no write** |
| `--email-on-fail` / `--no-email-on-fail` | Audit email policy (see defaults) |
| `--calendar-matches PATH` | Existing; default `~/.config/mention-scout/calendar-matches.json` |
| SMTP family | Existing `--email-to`, `--email-from`, `--smtp-server`, `--smtp-auth-user`, `--google-password-file` for audit fail mail |

**Do not** overload `--contains` or invent a second matches path flag.

### 3. Mutual exclusion / main() routing

Treat audit and add like other one-shots. **Recommended fail-fast conflicts:**

| Combination | Behavior |
|-------------|----------|
| `--audit-calendar-matches` + `--add-calendar-match` | Fail fast |
| Either + `--watch-new` / `--email-new` / `--calendar-add-new` / `--queue-initialized` | Fail fast |
| Either + `--test-email` / `--calendar-auth` | Fail fast |
| Either + `--invite-email` | Fail fast (invite is calendar-watch side-effect) |
| `--add-calendar-match` without `--match` | Fail fast |
| `--match` / `--time` / `--duration-minutes` / `--dry-run` without `--add-calendar-match` | Fail fast (or ignore only if never set — **prefer fail fast** if flag present) |
| `--email-on-fail` without audit | Fail fast |
| `--time` / `--duration-minutes` with audit only | Fail fast |

Watch child argv stripping: ensure new one-shot flags are **parent-only** and stripped from `_watch_child_arguments` the same way as `--test-email` / `--calendar-auth` (defense in depth even though mutually exclusive with watch).

### 4. Audit behavior (normative intent)

```
--audit-calendar-matches
  → resolve path = args.calendar_matches.expanduser()
  → try load_calendar_match_config(path)
  → on success:
        print short OK report to stdout
        exit 0
        (no email)
  → on failure (missing, unreadable, bad JSON, bad schema, empty phrases):
        print error to stderr (actionable; same text spirit as loader)
        if email-on-fail enabled:
            best-effort load password + run_swaks_email once
            on mail skip/fail: one stderr line
        exit 1 (or 2 — prefer 1 for config invalid; see questions)
```

**Success stdout (recommended minimal):**

```text
calendar-matches audit ok
path: /home/…/.config/mention-scout/calendar-matches.json
version: 1
phrases: 3
default_time: 18:30
```

Optional verbose (`--verbose`): list each phrase match + time/duration one per line (no email).

**Failure email subject (recommended):**

```text
[Kalshi] FAIL | calendar-matches audit
```

**Failure email body (recommended plain text):**

```text
Kalshi mention-scout calendar-matches AUDIT FAILURE

Time: {local timestamp in --timezone}
Host: {hostname}
Version: {VERSION}
Path: {absolute path}

Error:
  {actionable loader/OS error, whitespace-normalized, truncated ~1200 chars}

Schema reminder (version 1):
  {
    "version": 1,
    "default_time": "18:30",
    "phrases": [
      "simple string",
      {"match": "phrase", "time": "18:30", "duration_minutes": 30}
    ]
  }

Remediation ideas:
  - Fix JSON syntax (commas, quotes, brackets)
  - Validate times as 24-hour HH:MM / H:MM
  - Or re-add via: ./mention_scout.py --add-calendar-match --match "…"
  - Example: deploy/config/calendar-matches.example.json
  - After fix: ./mention_scout.py --audit-calendar-matches

This alert is from --audit-calendar-matches (MS-0014).
Watch startup FAIL mail (MS-0012), when enabled, is separate.
```

Rules:

- Paths only; **never** password/token/client_secret **contents**.
- Truncate long errors (`CALENDAR_ERROR_BODY_LIMIT` spirit).
- If password missing / swaks missing: skip mail with clear stderr; still exit non-zero with **primary** audit error.
- At most **one** email attempt per audit process.

**Email-on-fail default (recommended): ON** when audit fails, i.e. attempt mail unless `--no-email-on-fail`.

Rationale: owner asked to be emailed when bad; audit is the intentional “notify me” tool. Provide `--no-email-on-fail` for local/scripted checks. Alternative: default off and require `--email-on-fail` — safer for surprise SMTP, weaker for “I forgot to pass the flag.” **Prefer default ON** with documented opt-out.

### 5. Add-helper behavior (normative intent)

#### Inputs

- `--match` required; strip; reject empty after trim.
- `--time` optional; if present, parse with **same** `parse_calendar_local_time` rules (`HH:MM` / `H:MM`, 0–23 / 0–59).
- `--duration-minutes` optional; if present, whole number > 0 (reuse `parse_calendar_duration_minutes` spirit; CLI int is fine if argparse `type=int` plus `> 0` check).
- Path: `--calendar-matches` (default as today).

#### Representation rules

| Case | Written phrase form |
|------|---------------------|
| No `--time` and no `--duration-minutes` | **Plain string** in `phrases` (backward-compatible, minimal) |
| `--time` and/or `--duration-minutes` | **Object** `{"match": "…", ...}` with only set optional fields |

Do **not** force-convert unrelated existing string entries to objects on save.

#### File create policy (recommended)

If the match file is **missing**:

- **Create** parent dir `~/.config/mention-scout` as needed (mode sensible, e.g. `0700` if creating),
- Write a new valid doc:

```json
{
  "version": 1,
  "phrases": [ …new entry… ]
}
```

- Do **not** invent a `default_time` unless owner later adds a flag (v1: omit key).
- Print that the file was created.

If file exists but is **invalid JSON/schema**:

- **Refuse to write** (do not clobber / best-effort repair).
- Exit non-zero with actionable error pointing at `--audit-calendar-matches` and the loader message.
- **No** audit-style email from add mode in v1 (operator is running an interactive write tool; local error is enough). Optional: “hint: run audit to email” on stderr only.

#### Duplicate policy (recommended default: **update in place**)

Match key = `match.casefold()` (same as loader dedupe).

| Situation | Behavior |
|-----------|----------|
| No existing case-insensitive match | Append new phrase (string or object per rules) |
| Existing match, new flags provided | **Update** that entry: apply new time/duration; preserve unspecified fields when updating an object unless flags explicitly clear (v1: no clear flags — omit means “leave existing time/duration if updating with only --match”? — see below) |
| Existing match, add with only `--match` (no time/duration flags) | **No-op success** if identical string form already present; if object exists with same match, leave as-is and print “already present” |
| Existing match, add with `--time` / `--duration-minutes` | Upgrade string→object or update object fields; print “updated” |

**Recommended field merge on update when flags present:**

- If `--time` passed → set/replace time.
- If `--duration-minutes` passed → set/replace duration_minutes.
- Fields not passed on an update that includes at least one of time/duration: **preserve** existing object fields.
- Plain-string existing + only `--match` → already present.
- To “clear” time later: out of scope v1 (or stretch `--clear-time`).

**Alt (reject duplicate):** exit non-zero if casefold match exists — safer against silent overwrite, worse UX for “set time on existing phrase.” **Prefer update** because owner’s stated goal is safe maintenance while iterating times.

#### Preserve on rewrite

When serializing an existing valid file:

1. Keep `version: 1`.
2. Keep `default_time` if present (and valid); do not drop unknown top-level keys if cheap — **recommended: preserve unknown top-level keys** by starting from loaded dict round-trip **or** only write known keys (`version`, `default_time` if set, `phrases`). **Prefer known-keys-only from structured `CalendarMatchConfig`** for determinism (unknown keys dropped on rewrite). Document that add-rewrite normalizes the file to the canonical schema (comments impossible in JSON anyway; unknown keys lost). Loader already ignores unknown keys on read.
3. Preserve relative order of existing phrases; new appends at end; updates keep index.
4. Stable pretty JSON: `indent=2`, trailing newline (match `write_cache_atomic` style). **Do not** `sort_keys` on phrases array order.
5. Phrase objects: emit keys in order `match`, `time`, `duration_minutes` (only present fields).

#### Atomic write

Reuse `write_cache_atomic` **or** extract a shared `write_json_atomic(path, payload)` used by cache/state/matches:

- mkdir parents,
- temp file in same directory,
- mode `0600`,
- fsync,
- `os.replace`.

Never leave a truncated match file as the live path.

#### Dry-run

- Perform full validation + merge in memory.
- Print resulting entry JSON and target path + “dry-run: not written”.
- Exit 0 if merge would succeed; non-zero if validation would fail.
- No email.

#### Success stdout (recommended)

```text
calendar-matches updated
path: /home/…/calendar-matches.json
action: added | updated | already-present | created-file
entry: {"match": "abc world news tonight", "time": "18:30", "duration_minutes": 30}
phrases_total: 4
```

### 6. Serialization helper (API intent)

Non-binding names:

```python
def calendar_match_config_to_payload(config: CalendarMatchConfig) -> dict[str, Any]:
    """Canonical JSON-serializable dict for version 1 files."""

def save_calendar_match_config(path: Path, config: CalendarMatchConfig) -> None:
    """Atomic write via write_cache_atomic / write_json_atomic."""

def add_calendar_match(
    path: Path,
    *,
    match: str,
    time: str | None = None,
    duration_minutes: int | None = None,
    create_if_missing: bool = True,
) -> tuple[CalendarMatchConfig, str, CalendarPhrase]:
    """Load-or-create, merge, validate, save (unless dry-run at caller).
    Returns (new_config, action, resulting_phrase).
    """
```

Add path should:

1. Parse CLI time/duration with the same functions as file load (path label can be `"--time"` / CLI).
2. Build `CalendarPhrase`.
3. Load existing config or empty.
4. Merge.
5. Ensure `load` round-trip would succeed (either construct `CalendarMatchConfig` directly or write temp + load — prefer construct + serialize).
6. Save unless dry-run.

### 7. Email / SMTP for audit only

- Use existing `verify_email_configuration` / `load_google_password` + `run_swaks_email`.
- Default recipient/sender/server same as `--test-email` / `--email-new`.
- Do **not** require Google Calendar OAuth for audit/add (match file only).
- Do **not** send real email in tests; mock `run_swaks_email`.

### 8. Security / guardrails

- Discovery/notification/config tooling only; **no trading**.
- Never commit live owner `calendar-matches.json`, passwords, tokens, client secrets, `.env`.
- Audit email: paths + error text only.
- Atomic write mode `600`; parent dir creation must not loosen secrets elsewhere.
- Network: audit/add need **no** Kalshi/Google API; SMTP only on audit fail when enabled (timeouts via existing swaks path).

### 9. Docs

README Google Calendar section — add short subsections:

1. **Validate match file:** `--audit-calendar-matches` (+ email-on-fail note + MS-0012 distinction).
2. **Add a phrase safely:** `--add-calendar-match` examples (string vs timed object).
3. Optional cron one-liner example (comment only).

No installer change required.

### 10. Versioning / compatibility

- No match schema version bump (`version` remains `1`).
- No cache/queue bumps.
- When new flags absent: **zero behavior change**.
- Add-rewrite may normalize formatting/key order of the match file (document).
- `VERSION` bump when this MS ships per release policy.
- Stable symlink policy unchanged.

---

## Requirements (normative once approved)

1. `--audit-calendar-matches` validates via the same rules as `load_calendar_match_config`.
2. Audit success → exit 0, stdout summary, no email.
3. Audit failure → non-zero exit, stderr error; best-effort FAIL email when email-on-fail enabled and SMTP loadable.
4. Audit FAIL subject is distinct from MS-0012 start FAIL and MS-0010 runtime calendar error.
5. `--add-calendar-match --match …` creates or updates the match file atomically without dropping other valid phrases.
6. Plain-string adds remain plain strings; timed/duration adds use object form.
7. Invalid existing file → add refuses to write (no clobber).
8. Missing file → create valid v1 file when add runs (if create-if-missing default approved).
9. Duplicate case-insensitive match → update/already-present per frozen policy (recommend update).
10. `--dry-run` never writes.
11. One-shots mutually exclusive with watch/email/calendar-add/test-email/calendar-auth/each other.
12. Offline tests mock SMTP; no real Google/Kalshi required for these modes.
13. README documents both commands and MS-0012 boundary.
14. No trading; no secrets in git; preserve `./mention_scout.py` entry.

---

## Failure behavior

| Situation | Behavior |
|-----------|----------|
| Audit + valid file | exit 0; summary; no mail |
| Audit + missing file | exit non-zero; error; FAIL mail if enabled/SMTP ok |
| Audit + bad JSON/schema | exit non-zero; loader detail; FAIL mail if enabled/SMTP ok |
| Audit + mail send fails | stderr mail failure; still exit non-zero with **audit** error primary |
| Audit + no password + email-on-fail | skip mail with reason; exit non-zero |
| Add + valid new phrase | atomic write; exit 0 |
| Add + duplicate | update or already-present (policy); exit 0 |
| Add + invalid existing file | no write; exit non-zero; local error only |
| Add + invalid `--time` / duration / empty match | no write; exit non-zero before touch |
| Add + `--dry-run` | no write; print plan; exit 0 if plan valid |
| Conflicting flags | SystemExit actionable; no write; no audit mail |
| Disk full / permission on write | non-zero; original file preserved (atomic replace) |

---

## Compatibility

- Fully backward compatible when flags unused.
- Does not change watch matching, schedule application, or MS-0011 time semantics.
- Does not implement or block MS-0012; subjects remain distinct.
- Does not alter `--invite-email` / MS-0013.
- Canonical rewrite on add may change whitespace/key order of owner file — acceptable; semantic phrases preserved.

---

## Test plan

### Offline automated (required)

1. **Audit OK:** temp valid mixed string/object file → exit 0; stdout contains path + phrase count; `run_swaks_email` not called.
2. **Audit bad JSON:** broken comma → non-zero; stderr/JSON line hint; with email-on-fail and mocked password → exactly one swaks call; subject contains `calendar-matches audit` / `FAIL`; body has error + path; no password substring.
3. **Audit bad schema:** bad time `25:00`, empty phrases, wrong version → non-zero; mail optional per flag.
4. **Audit missing file:** non-zero; clear missing message.
5. **Audit `--no-email-on-fail`:** bad file → no swaks call.
6. **Audit mail skip:** email-on-fail but password load raises → no hang; skip line; non-zero.
7. **Add string phrase:** creates file if missing; payload version 1; phrases `["cnn this morning"]`.
8. **Add object phrase:** time + duration written as object; round-trip `load_calendar_match_config` succeeds.
9. **Add preserves existing:** prior phrases + default_time remain; order preserved for old entries.
10. **Add duplicate case-insensitive update:** existing `"ABC"` + add `--match abc --time 19:00` → one entry, updated time; no dup.
11. **Add already-present:** identical string add → action already-present; file mtime/content stable (or semantically equal).
12. **Add on invalid file:** refuse write; original bytes unchanged.
13. **Dry-run:** no file create/change; exit 0; output shows entry.
14. **Flag conflicts:** audit+watch, add without match, match without add → SystemExit.
15. **Atomic write:** mock/partial failure path leaves previous good file (if practical); at least unit-test serializer + save helper with tmp_path.
16. Factory compile/help still lists new flags; existing calendar tests green.

### Manual owner proof (not CI)

1. Break `calendar-matches.json` → run audit → receive FAIL email; fix → audit ok.
2. `--add-calendar-match --match "…" --time 18:30` → file updated; watch still loads; date-only events use time.
3. Confirm MS-0012 (when shipped) still uses start FAIL subject on watch preflight — distinct from audit.

### Explicit non-tests

- No real SMTP/Gmail in pytest.
- No real Google Calendar or Kalshi required for MS-0014 unit tests.

---

## Acceptance criteria

1. Owner can validate match JSON without starting `--watch-new`.
2. Invalid file audit emails actionable detail (when SMTP available and email-on-fail on) and exits non-zero.
3. Owner can add/update a phrase with optional time/duration without hand-editing JSON.
4. Existing phrases and MS-0011 semantics preserved; plain strings still work.
5. Writes are atomic; invalid source file is never clobbered by add.
6. Subjects/bodies never include secret contents; tests mock swaks.
7. Clear docs for audit vs MS-0012 startup FAIL mail.
8. CLI defaults unchanged when new flags absent; no trading; independent verification + owner ship approval before release.

---

## Implementation sketch (non-binding)

- Extend `build_parser()` with one-shot flags and add/audit options.
- Early `main()` branches after invite normalize, alongside `--calendar-auth` / `--test-email`.
- Add serialize/save/add helpers next to `load_calendar_match_config`.
- Add `format_calendar_matches_audit_fail_email` + `run_audit_calendar_matches` / `run_add_calendar_match`.
- Strip new flags in `_watch_child_arguments`.
- Tests: `tests/test_calendar_matches_cli.py` (or split audit/add).
- README calendar section bullets.
- No symlink retarget; VERSION bump on ship only.

No implementation until **approved** with owner decisions resolved. No agent spawn without explicit OK.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Double email (audit + later MS-0012 start) | Distinct subjects; document; no cross-process dedupe v1 |
| Add rewrite drops unknown keys / reformats file | Document canonical rewrite; preserve phrase semantics + default_time |
| Default email-on-fail surprises | Document; `--no-email-on-fail`; same SMTP stack as test-email |
| Concurrent add + editor | Atomic replace last-writer-wins; document; no lock v1 |
| Silent duplicate update | Print action `updated` clearly; dry-run available |
| Scope creep into full config CRUD | Hard out-of-scope list; only add + audit |
| Coupling to unshipped MS-0012 | Independent helpers; shared loaders only |

---

## Draft GitHub issue body

**Title:** `MS-0014: Audit calendar-matches JSON + safe --add-calendar-match helper`

**Labels:** `type:feature` `P2` `status:needs-triage`

**Body:**

```markdown
## Summary

Owner hand-edits `~/.config/mention-scout/calendar-matches.json`. Need:

1. One-shot **audit** of the match file with **email on invalid** schema/JSON (without starting `--watch-new`).
2. Safe **add/update** helper for phrases (`--match`, optional `--time`, optional `--duration-minutes`) with validation + atomic write.

## Factory

- ID: MS-0014
- Spec: `.factory/specs/MS-0014-proposed.md` (proposed; not approved)
- Related: MS-0011 (schema on main), MS-0012 (#19 startup FAIL email; complementary, watch-only)

## Proposed CLI

```bash
./mention_scout.py --audit-calendar-matches
./mention_scout.py --add-calendar-match --match "…" [--time HH:MM] [--duration-minutes N] [--dry-run]
```

## Notes

- Reuse `load_calendar_match_config`; no schema fork.
- Distinct email subject from MS-0012 watch start FAIL.
- No trading; no real SMTP in CI.
```

---

