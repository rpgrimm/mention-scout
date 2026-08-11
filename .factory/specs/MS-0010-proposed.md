# MS-0010 — Auto-add matched mention markets to Google Calendar

Status: **PROPOSED** (awaiting owner approval)  
Type: feature (notification / side-effect on discovery)  
Priority: P2 (owner-requested)  
Related: MS-0006 (mention types; display only here), MS-0004 (email dry-run; complementary), MS-0008 (long-running watch)  
Repository: `/home/candr/src/mention_scout`  
Implementation target (after approval): `kalshi_mention_scout.py` (current v16 / `VERSION 16.0.0`)  
Stable command: `./mention_scout.py`  
GitHub: *create issue on approval / triage*

---

## Problem

When mention-scout discovers certain markets the owner cares about (first example: **ABC World News Tonight**), those airings should land on the owner’s personal Google Calendar automatically—without manual copy/paste from email or the terminal.

The set of “care about” markets will grow. The owner wants a **human-readable file on disk** listing match phrases (starting with `abc world news tonight`) that they can edit anytime—not a code change and not only hard-coded MS-0006 type ids.

Today the scout can:

- classify families such as `world-news-tonight` (MS-0006)
- watch for **new parent event tickers** (`--watch-new`)
- email a parent-event overview (`--email-new` + `swaks` + `~/.config/.google-password`)

It does **not** write calendar events, load an owner match list, handle `client_secret.json`, or email calendar-specific failures.

Owner credential path:

- OAuth desktop client secret: **`~/.config/mention-scout/client_secret.json`**
- Must never be committed, printed, or packaged

If calendar integration is broken (missing secret, auth failure, API error, unusable schedule, unreadable match file when required), the owner wants an **email containing the error message** so a headless/systemd watch stays observable.

---

## Current behavior (verified)

| Area | Behavior |
|------|----------|
| Types | MS-0006 labels include `world-news-tonight` (ticker/title rules); useful for display, **not** the owner’s preferred calendar gate |
| Substring filter | `--contains` is a single CLI needle on market text (`contains_filter` / `text_for_market`); not a multi-entry editable file |
| New detection | `--watch-new` baselines parent `event_ticker`s; only **new** parents alert |
| Schedule | `event_schedule_for_market` may be timed, **date-only**, or missing |
| Email | `run_swaks_email` + `~/.config/.google-password`; new-market mail failures are stderr-only; watch continues |
| Deps | stdlib + external `swaks`; no Google API client |
| Config dir | `~/.config/mention-scout/` not present yet (owner/docs create it; nothing secret committed) |

---

## Goal

When watch mode discovers a **new** parent mention event whose **haystack text matches any phrase** in an owner-edited match list file, **create one Google Calendar event** using OAuth from:

```text
~/.config/mention-scout/client_secret.json
```

plus a stored refresh token under the same config directory.

Match list default location (recommended):

```text
~/.config/mention-scout/calendar-matches.json
```

First seed phrase: **`abc world news tonight`**. Owner appends more phrases over time without code changes.

If calendar create/auth/config/match-file load fails for a candidate (or at preflight), **email a clear error** via the existing swaks/Gmail path and continue watching when appropriate. Never place trades. No third-party attendees in v1.

---

## Format recommendation — match list file

### Decision: JSON (stdlib) with a tiny schema

**Recommend JSON over YAML or ad-hoc text** for v1:

| Option | Pros | Cons |
|--------|------|------|
| **JSON object + `phrases` array (recommended)** | stdlib only; easy to extend (`version`, notes later); validates structure; good enough to edit by hand for small lists | No comments in strict JSON |
| Line-oriented `.txt` (`#` comments, one phrase/line) | Maximum “just a list” UX | Weaker structure; easy silent blank/encoding footguns; harder to add per-entry options later |
| YAML | Comments + structure | Extra dependency or fragile subset parser |

**Recommended default file:** `~/.config/mention-scout/calendar-matches.json`

**Recommended schema (v1):**

```json
{
  "version": 1,
  "phrases": [
    "abc world news tonight"
  ]
}
```

**Editing rules (documented in README + file-adjacent example):**

- `version` must be `1` for this MS (unknown version → actionable error).
- `phrases` is a JSON array of non-empty strings.
- Matching is **case-insensitive substring** (same spirit as `--contains`).
- Surrounding whitespace in each phrase is trimmed; empty strings after trim are ignored (or rejected—see questions; **recommend reject file with a clear error** if any element is empty after trim).
- Duplicate phrases are allowed but harmless (dedupe when loading).
- **Any** phrase hit → calendar candidate (OR semantics).
- Owner may add entries anytime; **reload policy** below.

**Optional later fields (out of v1 unless owner wants them now):**

```json
{
  "version": 1,
  "phrases": [
    {
      "match": "abc world news tonight",
      "enabled": true,
      "note": "WNT"
    }
  ]
}
```

v1 stays **string array only** to keep the file obvious.

**Repo example (not the live config):** e.g. `deploy/config/calendar-matches.example.json` with the seed phrase, copied by the owner into `~/.config/mention-scout/`. Live file stays outside git.

**Alternative if you strongly prefer comments-in-file:** support a `.txt` format instead or in addition—say so in approval. Default below remains JSON.

### Match haystack (what phrases search)

Build one casefolded string from the **parent event** (overview) fields, in order, joined by spaces:

- `title`, `sub_title` / subtitle-like fields if present on overview
- `description`
- `category`
- `event_ticker`, `series_ticker`
- child market titles/tickers for that parent **only if cheaply available** from the watch snapshot records for that event (recommended: **yes**, include child titles/tickers so a phrase that appears only on a contract still matches)

Do **not** use trading rules text for matching if it is not already part of overview display fields (align with MS-0007 caution: rules boilerplate is a false-positive magnet). Prefer overview + tickers + child titles already in the snapshot.

### Reload policy

**Default recommendation:** load the match file:

1. Once at watch start (preflight), and  
2. Again on each new-ticker handling **or** each successful refresh before processing new tickers  

so edits to `calendar-matches.json` apply **without restarting** the watch. Cache mtime/size to avoid re-parsing every poll when unchanged.

If the file goes missing or becomes invalid after start → error email (rate-limited / deduped) + skip calendar inserts until fixed; **do not** kill the whole watch unless owner chooses fail-fast (see questions).

---

## Scope

### In scope

1. **Opt-in calendar integration** for `--watch-new` only (v1).
2. **Human-edited match list file** (JSON schema above) controlling which new parent events get a calendar entry.
3. **Seed / example** with `"abc world news tonight"`.
4. **Google OAuth installed-app flow** using `client_secret.json`.
5. **Persistent token store** under `~/.config/mention-scout/`; auto-refresh access tokens.
6. **Calendar event builder** from overview/schedule fields.
7. **Idempotency / duplicate suppression** per `event_ticker` (+ calendar id).
8. **Failure email** on calendar/match-file/auth/API/schedule errors via existing SMTP stack.
9. **Startup preflight** when calendar enabled (secret/token/match file/deps)—policy in owner questions.
10. **CLI flags** with defaults that preserve today’s behavior when calendar flags are absent.
11. **Offline unit tests** for: JSON load/validate, phrase match, haystack builder, event body, schedule mapping, error mail, dedupe, argv strip. No real Google/SMTP in CI.
12. **README** setup: match file, Google Cloud, auth, systemd, failures.
13. **`.gitignore`** defense-in-depth for secrets/tokens if paths could appear in-repo.

### Out of scope

- Trading / Kalshi orders.
- One-shot (non-watch) auto-add in v1.
- Update/delete of calendar events when markets resolve.
- Multi-calendar UI, attendees, conference links.
- Replacing swaks with Gmail API send.
- Full MS-0004 email dry-run (share seams if cheap).
- Changing binary mention detection or MS-0006 taxonomy (labels may still appear on calendar summary).
- Committing live `client_secret.json`, tokens, or the owner’s match file with local-only notes you do not want public (example file in repo is fine).
- Auto-provisioning Google Cloud projects.
- Interactive browser OAuth inside systemd by default.
- Regex/glob match engine in v1 (literal casefold substring only).
- Per-phrase calendar overrides in v1.

### Optional stretch (off unless owner opts in)

- `--calendar-auth` one-shot browser consent → `token.json` (**recommended in-scope**, listed again under questions).
- Line-oriented `.txt` match file as alternate reader.
- Richer JSON entries (`enabled`, `note`, per-phrase duration).
- All-day vs fixed-clock policy already under schedule questions.
- Google extended property / iCalUID keyed by `event_ticker`.
- Injectable calendar client for tests (recommended internally).

---

## Recommended design

### Trigger path

Inside `watch_new_events`, after a ticker is classified as **new** (same moment as terminal render / optional `--email-new`):

```
new parent event_ticker
  → load/refresh calendar match phrases (mtime cache)
  → build event haystack from overview (+ child titles/tickers)
  → any phrase substring-hit?
       no  → skip calendar (email-new unchanged)
       yes → build calendar payload from schedule + overview
            → insert (or skip if deduped)
            → on failure: email calendar error; stderr; continue loop
```

Baseline inventory at watch start is **never** calendar-added.

MS-0006 type labels may still be used in the **calendar summary/description** for readability; they are **not** the eligibility gate.

### Credentials and paths (defaults)

| Artifact | Default path | Notes |
|----------|--------------|-------|
| Match phrases | `~/.config/mention-scout/calendar-matches.json` | Owner-edited; seed phrase below |
| Example match file (repo) | `deploy/config/calendar-matches.example.json` | Documentation only |
| OAuth client secret | `~/.config/mention-scout/client_secret.json` | Desktop OAuth client; prefer mode `0600` |
| User token | `~/.config/mention-scout/token.json` | After consent; mode `0600` |
| Dedupe state | `~/.config/mention-scout/calendar-added.json` | Not secret, still local |
| Gmail app password | `~/.config/.google-password` | Unchanged |
| Calendar ID | `primary` | Override via flag |

**Never** print client secret, refresh/access tokens, or Gmail password. Error emails may include ticker, title, matched phrase, API status text—not credential material.

### Seed match file content

```json
{
  "version": 1,
  "phrases": [
    "abc world news tonight"
  ]
}
```

Why this phrase (not only `world news tonight`): owner-specified; includes network disambiguation; still matches typical titles/tickers that contain that wording (case-insensitive).

### OAuth / API approach

When calendar feature enabled, use official libraries:

- `google-auth`, `google-auth-oauthlib`, `google-api-python-client`

**Dependency policy (recommended):** optional extras; calendar flags fail with install hint if imports missing; core scout works without them.

Scope: `https://www.googleapis.com/auth/calendar.events`

### First-time auth UX (headless-friendly)

1. **`--calendar-auth`**: terminal once → browser / `run_local_server` → write `token.json` → exit 0.  
2. **`--calendar-add-new`**: requires valid `token.json` (refresh as needed). Never block headless watch on a browser.

### Calendar event content (draft)

| Field | Source / rule |
|-------|----------------|
| `summary` | `"[Kalshi] {title}"` or `"[Kalshi] {type_label}: {title}"` if type known; fallback ticker |
| `description` | Ticker, matched phrase(s), type label if any, Kalshi URL, short description, schedule source, “created by mention-scout --watch-new”, detected time |
| `start` / `end` | Resolved schedule in `--timezone` (default `America/New_York`) |
| Duration | Default **60 minutes** when start datetime known |
| Date-only | Owner decision (recommend **all-day** on that local date) |
| Missing schedule | No inventing a day; failure email |
| `source` | Kalshi URL when available |
| reminders | Google defaults (v1) |

### Duplicate suppression

- State file: `~/.config/mention-scout/calendar-added.json`
- Key: `event_ticker` + `calendar_id`
- Value: `{ added_at_utc, calendar_event_id?, html_link?, matched_phrase? }`
- Skip insert if key exists; record after success
- Independent of `--email-new`

### Failure email

- Subject (draft): `[Kalshi] calendar error | {event_ticker or "watch"}`
- Body: time, ticker/title, matched phrase if any, operation (match-file, auth, insert, schedule), error string (truncated), expected paths **without** contents, remediation (`--calendar-auth`, `chmod 600`, fix JSON, enable Calendar API)
- SMTP required for error delivery whenever calendar is on (**recommended**), even if `--email-new` is off
- If SMTP also fails: stderr both errors; watch continues (unless preflight fail-fast)

### CLI (proposed)

| Flag | Default | Meaning |
|------|---------|---------|
| `--calendar-add-new` | off | With `--watch-new`, create calendar events for phrase-matched new parents |
| `--calendar-matches` | `~/.config/mention-scout/calendar-matches.json` | Match list file |
| `--calendar-client-secret` | `~/.config/mention-scout/client_secret.json` | Desktop OAuth client JSON |
| `--calendar-token` | `~/.config/mention-scout/token.json` | Stored user token |
| `--calendar-id` | `primary` | Target calendar |
| `--calendar-state` | `~/.config/mention-scout/calendar-added.json` | Local dedupe state |
| `--calendar-duration-minutes` | `60` | Timed-event length when start datetime known |
| `--calendar-auth` | off | One-shot interactive auth; write token; exit |

**Removed vs earlier draft:** `--calendar-types` as the primary gate (owner wants a word list file). Type ids are not required for eligibility.

Rules:

- `--calendar-add-new` only with `--watch-new`.
- `--calendar-auth` incompatible with watch/email-new/queue (like `--test-email`).
- `_watch_child_arguments` strips all `--calendar-*` flags (parent owns side effects).

### Interaction with existing email-new

| `--email-new` | `--calendar-add-new` | Behavior |
|---------------|----------------------|----------|
| on | off | Today’s behavior |
| off | on | Calendar for phrase matches; errors still email via SMTP |
| on | on | NEW overview email for all new parents **and** calendar for phrase matches; independent success/failure |
| off | off | Today’s behavior |

### Versioning / compatibility

- No cache format bump.
- No behavior change when calendar flags absent.
- `VERSION` bump on ship per release policy.
- README + architecture updated in implementation.

### Security / guardrails

- Owner calendar only; **no trading**.
- Never commit secrets/tokens/password files.
- Permission checks on secret/token (and warn on overly open match/state files if desired).
- Google API timeouts + actionable errors.
- Tests: no real Google/SMTP; fakes only.
- Do not log OAuth JSON or match-file paths’ secret siblings’ contents.

---

## Test plan

### Offline automated (required)

1. Load valid match JSON; seed phrase present.
2. Reject bad version, missing `phrases`, non-array, empty phrase elements (per policy).
3. Case-insensitive substring match; trim behavior; OR across phrases.
4. Haystack includes title/ticker; child title can match; rules-only text not required.
5. Non-matching new event → no insert call.
6. Event body builder + timed schedule duration.
7. Date-only mapping per approved policy.
8. Missing schedule → error, no insert.
9. Dedupe: second insert skipped; state updated after success.
10. Failure email content has ticker/error; no secret/password/token fixtures leaking.
11. `_watch_child_arguments` strips calendar flags.
12. CLI coupling: `--calendar-add-new` without `--watch-new` fails; help lists flags.
13. Optional-deps missing → actionable error.

### Manual owner proof (not CI)

1. Copy example → `~/.config/mention-scout/calendar-matches.json`.
2. `client_secret.json` + `--calendar-auth` → `token.json`.
3. Watch with `--calendar-add-new`; force/wait for matching new parent → calendar row.
4. Add a second phrase; confirm reload without restart (if reload policy approved).
5. Break token → error email; watch continues.
6. systemd run with token present, no browser.

### Explicit non-tests

- No real Gmail in pytest.
- No real Google insert in pytest.
- No live Kalshi required for unit tests.

---

## Acceptance criteria

1. Flags off → pre-MS-0010 behavior (existing tests + factory-test).
2. Owner match file with `"abc world news tonight"` gates calendar eligibility via casefold substring.
3. Owner can add phrases by editing the file (no code change); documented path + example.
4. Valid secret+token+match + new matching parent → one calendar event.
5. Non-matching new mention parents → no calendar event.
6. Dedupe prevents duplicate rows for same ticker on same host state.
7. Calendar/match/auth failures → error email (SMTP configured) and no watch crash (unless approved fail-fast preflight).
8. Secrets never in repo, logs, or email bodies.
9. README documents match file format, paths, auth, systemd.
10. Independent verification PASS + explicit owner ship approval before release.

---

## Implementation sketch (non-binding)

- Pure helpers: `load_calendar_match_phrases`, `event_calendar_haystack`, `matching_calendar_phrases`, `build_calendar_event_body`, `calendar_dedupe_key`, `format_calendar_error_email`.
- `GoogleCalendarClient` protocol + fake.
- Hook in `watch_new_events` new-ticker loop beside `send_new_market_email`.
- Strip `--calendar-*` in `_watch_child_arguments`.
- Example JSON under `deploy/config/`.
- README “Google Calendar auto-add”.

No implementation until **approved** with owner decisions resolved. No agent spawn without explicit OK.

---

## Owner questions (need decisions before APPROVED)

Defaults in **bold** = coordinator recommendation for `approve MS-0010 with defaults`.

1. **Match file format?**  
   **Default: JSON** `{ "version": 1, "phrases": ["abc world news tonight", ...] }` at `~/.config/mention-scout/calendar-matches.json`.  
   Alt: line-oriented `.txt` with `#` comments.

2. **Match semantics?**  
   **Default: case-insensitive substring (OR across phrases)** on parent haystack (+ child titles/tickers from snapshot).  
   Alt: whole-word / regex (not recommended v1).

3. **Reload on edit without restart?**  
   **Default: yes** (mtime cache per refresh / before new-ticker handling).

4. **Missing or invalid match file when `--calendar-add-new`?**  
   **Default: fail fast at watch start.**  
   Alt: start watch, email error, skip calendar until fixed.

5. **Watch-only vs also one-shot?**  
   **Default: `--watch-new` only.**

6. **Date-only schedules?**  
   **Default: all-day event on that local date.**  
   Alt: skip + error email; or fixed clock (e.g. 18:30).

7. **Missing schedule entirely?**  
   **Default: no calendar row; failure email once per ticker (dedupe errors).**

8. **Timed duration?**  
   **Default: 60 minutes.**

9. **Target calendar?**  
   **Default: `primary` (`--calendar-id`).**

10. **Dependencies?**  
    **Default: optional Google client libs; install hint if missing.**

11. **First-time auth?**  
    **Default: include `--calendar-auth` one-shot; watch never opens browser.**

12. **Startup if token missing (secret present)?**  
    **Default: fail fast** with “run --calendar-auth”.

13. **Startup if client_secret missing?**  
    **Default: fail fast.**

14. **Error email when `--email-new` is off?**  
    **Default: still send calendar error emails** (SMTP required if calendar on).

15. **Reminders?**  
    **Default: Google defaults.**

16. **Summary format?**  
    **Default: `[Kalshi] {type_label}: {title}` when type known, else `[Kalshi] {title}`.**

17. **`--email-new` still fires for matched events?**  
    **Default: yes, independent.**

18. **Dedupe store?**  
    **Default: `~/.config/mention-scout/calendar-added.json`.**

19. **Also keep a `--calendar-types` filter as AND with phrases?**  
    **Default: no** — phrases file alone is the gate (simpler mental model).

20. **Priority vs MS-0003/0004/0005?**  
    **Default: MS-0010 next** (owner-requested). This MS carries its own offline tests.

21. **GitHub issue on approval?**  
    **Default: yes**, private issue linked to this spec.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Short phrases over-match | Owner chooses phrases; document that shorter = broader; start with specific seed |
| Headless OAuth hang | `--calendar-auth` separate; watch needs token |
| JSON edit mistakes | Validate + actionable errors + example file |
| Date-only wrong day | Explicit policy; schedule source in description |
| Duplicate after state loss | Document state path; optional later Google-side id |
| Secret leakage | Paths outside repo; mode checks; never log secrets |
| SMTP down on calendar error | Stderr fallback; watch continues |

---

## Explicit non-actions until approval

- No implementation worktree  
- No host dependency installs for this feature  
- No real Google API calls  
- No real email  
- No GitHub issue/PR unless you ask  
- No agent spawn  
- No writing your live `~/.config/mention-scout/` files until you want setup help after approval  

---

## Approval line (paste when ready)

Examples:

- `approve MS-0010 with defaults`
- `approve MS-0010 with defaults except: txt match file; date-only skip+email; duration 30m`

After approval: freeze `.factory/specs/MS-0010-approved.md`, optionally open GitHub issue, and **ask before** any implement/verify agent.
