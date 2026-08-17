# MS-0013 — Calendar attendees via `--invite-email`

Status: **APPROVED**  
Approved: 2026-08-17 by owner (chat: “approve and make pull request so i can test”) with **defaults**, after confirming calendar attendees only and **no SMTP fan-out**.  
Type: feature (calendar / notification side-effect)  
Priority: P2 (owner-requested UX)  
Related: MS-0010 (calendar auto-add; this MS extends the created event), MS-0011 (date-only timed events; orthogonal), MS-0006 (email subjects; unchanged), MS-0012 (startup FAIL email; orthogonal), MS-0004 (email dry-run; complementary), MS-0008 (systemd extra-args)  
Repository: `/home/candr/src/mention_scout`  
Implementation target: `kalshi_mention_scout.py`  
Stable command: `./mention_scout.py`  
GitHub: https://github.com/rpgrimm/mention-scout/issues/20  
Review publication: **feature branch `openclaw/ms-0013` + pull request into `main`** (do not push straight to `main`)

## Owner decisions (frozen)

1. **Product meaning:** `--invite-email` adds **Google Calendar attendees** on MS-0010-created events only.
2. **No SMTP fan-out:** mention-scout must **not** swaks-email invite addresses (new-market / error / test / FAIL). Google may still notify guests via Calendar when `sendUpdates=all`.
3. Flag name: repeatable `--invite-email`.
4. `sendUpdates="all"` when attendees present; omit/none otherwise.
5. Do **not** auto-inject owner `--email-to` as an attendee.
6. `--invite-email` without `--calendar-add-new`: **fail fast**.
7. `--test-email --invite-email`: **fail fast** (calendar-only flag).
8. Max **20** invites; light address validation; any well-formed email domain.
9. No attendee list in event description (API attendees only).
10. No `calendar-added.json` schema change in v1.
11. Installer: `--extra-args` only (no first-class install flag).
12. Priority P2; ship via branch + PR for owner test; no merge without later explicit approval after verification.
13. VERSION bump on implement/ship.
14. Zero invites → MS-0010 insert behavior unchanged.

Proposed-spec “Owner questions” section is superseded by this freeze; remaining body is normative except where it still says “recommend” — treat frozen decisions above as authoritative.

---

## Problem

MS-0010 already creates a **Google Calendar event** on the owner’s calendar when a new parent mention market matches phrases in `calendar-matches.json`. That insert is organizer-only today: the API body has summary/description/start/end (and optional source URL) but **no `attendees`**, and `events.insert` is called without `sendUpdates`.

Owner request evolution:

1. (2026-08-17 earlier) Want a CLI way to invite another Gmail, git send-email style, one or more `--invite-email`.
2. (2026-08-17 clarification) **“calendar attendees to the invite created”** — meaning: when mention-scout creates the calendar event, attach those addresses as **Google Calendar attendees** so Google sends the normal calendar invite.
3. (2026-08-17 confirmed) **No SMTP fan-out for now** — do **not** have mention-scout email invitees via swaks; `--invite-email` is **calendar entry attendees only**.

So this MS is **not** “fan out scout SMTP overview mail to friends.” It is **attendee list on the MS-0010 calendar row.** Google may still email guests through Calendar when `sendUpdates=all`; that is not scout SMTP.

### Non-goals (frozen out for v1)

- Changing phrase matching, schedule resolution, or dedupe state schema beyond optional attendee bookkeeping.
- **SMTP fan-out** of new-market / calendar-error / FAIL / test mail to `--invite-email` addresses (owner: not for now).
- Product onboarding / “install mention-scout” email.
- Trading or sharing OAuth secrets.
- Updating/deleting attendees on already-created events when invites change mid-watch (v1: affects **new** inserts only).

---

## Goal

Let the owner pass one or more `--invite-email ADDRESS` flags so that each **new** calendar event created by `--calendar-add-new` includes those addresses as Google Calendar **attendees**, and Google is asked to send invitation updates.

Illustrative CLI:

```bash
# Watch + calendar; invite a partner onto each newly created event
./mention_scout.py --watch-new --calendar-add-new \
  --invite-email partner@gmail.com

# Multiple attendees (git send-email style: flag repeated)
./mention_scout.py --watch-new --calendar-add-new \
  --invite-email alice@gmail.com \
  --invite-email bob@example.com

# With email-new still independent for the *owner* SMTP overview
./mention_scout.py --watch-new --email-new --calendar-add-new \
  --invite-email partner@gmail.com
```

systemd:

```bash
./scripts/install-user-service.sh --enable-now \
  --extra-args '--calendar-add-new --invite-email partner@gmail.com'
```

Expected Google-side result for a successful phrase-matched insert:

- Event appears on owner’s `--calendar-id` (default `primary`) as today.
- Event has `attendees: [{email: partner@gmail.com}, ...]`.
- Partner receives Google’s calendar invitation email (not mention-scout’s swaks overview), subject to Google/workspace policies.

---

## Current behavior (verified in code)

| Area | Behavior |
|------|----------|
| Flag surface | No `--invite-email`; single `--email-to` for SMTP only |
| `build_calendar_event_body` | summary, description, start/end, optional `source`; **no attendees** |
| `GoogleCalendarApiClient.insert_event` | `events().insert(calendarId=..., body=...)` — **no `sendUpdates`** |
| OAuth scope | `https://www.googleapis.com/auth/calendar.events` |
| MS-0010 approved non-goal | “Multi-calendar UI, attendees, conference links” was out of MS-0010 v1 — this MS deliberately adds attendees |
| Dedupe | `calendar-added.json` by ticker+calendar id; no attendee list stored |
| SMTP | Independent `--email-new` / calendar **error** mail via swaks to `--email-to` only |

---

## Scope

### In scope

1. **Repeatable CLI flag** `--invite-email ADDRESS` (`action="append"`).
2. **Light address validation** (same spirit as prior draft: strip, one `@`, no header-injection chars, optional max count).
3. **Attendee list on calendar insert body** when invites are present and an event is actually created.
4. **`sendUpdates` on insert** so Google notifies attendees (recommended value below).
5. **Eligibility / fail-fast rules** when `--invite-email` is used without `--calendar-add-new`.
6. **Wire through** `build_calendar_event_body` (or adjacent pure helper) + `insert_event` API wrapper.
7. **Parent-only argv:** strip `--invite-email` from watch child argument lists with other parent-only flags.
8. **Offline unit tests** with fake calendar client asserting body attendees + insert kwargs; no real Google/SMTP.
9. **README** short note under calendar section: inviting attendees; Google sends the invite mail.
10. Preserve CLI defaults when flag absent (MS-0010 behavior unchanged).
11. No trading; no secret commits; never put OAuth token/password in event description.

### Out of scope (v1 recommended)

- SMTP notification fan-out to invite addresses (owner clarified calendar attendees).
- Adding `--email-to` primary owner as an attendee (organizer already owns the event on primary).
- Patching historical events when invite list changes.
- Optional/required attendee roles, per-attendee messages, or conference links.
- Domain-wide delegation / Workspace admin APIs.
- Changing OAuth scope unless insert-with-attendees proves insufficient (see risks).
- Durable invite address book file (stretch).
- MS-0011 timed date-only behavior (orthogonal; attendees attach regardless of all-day vs timed).

### Optional stretch (off unless owner opts in later)

- SMTP fan-out of scout swaks mail to invite emails (**explicitly declined for now** — do not implement in this MS).
- Durable `~/.config/mention-scout/invite-emails.txt`.
- Store attendee list snapshot in `calendar-added.json` for debugging.
- `--invite-optional` / responseStatus defaults.
- Re-auth helper text if existing token lacks needed capability.
- Installer first-class `--invite-email` passthrough (vs `--extra-args` only).

---

## Recommended design

### Flag surface

```text
--invite-email ADDRESS   (repeatable; optional)
```

- argparse `action="append"`, default none → normalize to `list[str]`.
- **Semantic (v1): calendar attendees only.**
- Does **not** by itself enable `--calendar-add-new` or `--email-new`.

### When the flag is legal

| Invocation | Recommended behavior |
|------------|----------------------|
| `--watch-new --calendar-add-new --invite-email …` | **Valid** — attendees on successful creates |
| `--watch-new --email-new --calendar-add-new --invite-email …` | **Valid** — attendees on creates; SMTP overview still owner-only (`--email-to`) |
| `--invite-email` without `--calendar-add-new` | **Fail fast** — actionable: invites apply to calendar events; pass `--calendar-add-new` |
| `--calendar-auth --invite-email` | **Fail fast** or ignore with error — auth one-shot does not create events |
| `--test-email --invite-email` | **Fail fast** under calendar-only reading (test-email is SMTP). Alt: allow no-op warning — **prefer fail fast** for clarity |
| Invites present, calendar on, but event not phrase-matched | No insert → **no** Google invite (unchanged match gate) |

### Attendee construction

Pure helper (name non-binding):

```python
def normalize_invite_emails(raw: list[str] | None) -> list[str]:
    """Strip, validate, dedupe casefold, preserve order."""

def calendar_attendees_body(invite_emails: list[str]) -> list[dict[str, str]]:
    return [{"email": addr} for addr in invite_emails]
```

Rules:

1. Dedupe case-insensitively; preserve first-seen order.
2. Do **not** auto-inject `--email-to` / `--email-from` / `--smtp-auth-user` as attendees.
3. If after dedupe the list is empty, omit `attendees` key entirely (identical to MS-0010).
4. Max invites **default 20**; over cap → fail fast at startup.
5. Validation: non-empty local@domain, domain with a dot, reject whitespace and raw `,;<>\"\\\r\n`.
6. Not Gmail-only (Google will deliver to whatever addresses the calendar allows).

### `build_calendar_event_body`

Add optional kw-only `attendees: list[dict[str, Any]] | None = None` (or `invite_emails: list[str] | None`).

When non-empty, set:

```python
body["attendees"] = [{"email": addr} for addr in invite_emails]
```

Do not set `attendees[].responseStatus` unless tests show Google requires it (usually omitted → needsAction).

Do **not** put invite addresses into `description` unless owner wants a visible roster (default: **API attendees only**).

### `insert_event` / sendUpdates

Google only emails guests if the insert/patch asks for updates. Recommended:

```python
def insert_event(
    self,
    calendar_id: str,
    body: dict[str, Any],
    *,
    send_updates: str | None = None,
) -> dict[str, Any]:
    kwargs = {"calendarId": calendar_id, "body": body}
    if send_updates:
        kwargs["sendUpdates"] = send_updates  # "all" | "externalOnly" | "none"
    request = self._service.events().insert(**kwargs)
    ...
```

| Situation | `sendUpdates` |
|-----------|----------------|
| Insert with ≥1 attendee | **`"all"`** (recommended) — notify attendees |
| Insert with no attendees | omit or `"none"` (today’s quiet create) |

**Alt:** `"externalOnly"` if owner’s Workspace wants quieter internal behavior — usually unnecessary on personal Gmail primary.

Protocol `CalendarClient` should gain the optional kwarg with default `None` so tests/fakes stay simple.

### Watch path wiring

In `maybe_add_calendar_event_for_new_market` (conceptual):

1. Resolve `invite_emails = normalize_invite_emails(args.invite_emails)` once (or cached on args at preflight).
2. Pass into `build_calendar_event_body(..., invite_emails=invite_emails)`.
3. Call `calendar_client.insert_event(calendar_id, body, send_updates=("all" if invite_emails else None))`.
4. On insert failure (including attendee/permission errors): existing calendar error email path (SMTP to `--email-to` only); watch continues.
5. Success log (verbose or always, match existing style): include attendee count or addresses, e.g.  
   `calendar event added for TICKER (matched '…'; attendees: a@x, b@y)`.

### Preflight

When `--calendar-add-new` and invites non-empty:

- Validate all invite addresses before loop (fail fast).
- Existing calendar preflight unchanged (secret/token/match/SMTP for errors).
- **No** need to load Google password solely because of invites (attendee mail is Google’s, not swaks) — unless `--email-new` or calendar error SMTP path already requires it (MS-0010: calendar still requires SMTP for error mail).

### OAuth / token notes

- Scope today: `calendar.events` — sufficient for creating events with attendees on calendars the user owns in normal Google accounts.
- Existing tokens should keep working; attendees are part of the event resource, not a separate scope.
- If Google returns a permission error in the field, surface it via existing `calendar error email` with actionable text (and README: re-run `--calendar-auth` if ever required).
- **Do not** broaden scopes in v1 unless implementation proves necessary; if required, that is a **spec amendment + re-auth** note before ship.

### Interaction with other MS items

| MS | Interaction |
|----|-------------|
| MS-0010 | Extends create path only; match/dedupe/schedule/reminders defaults unchanged |
| MS-0011 | Attendees apply to timed and all-day bodies equally |
| MS-0012 | No change; FAIL mail remains owner SMTP |
| MS-0006 / `--email-new` | Unchanged single `--email-to` unless stretch fan-out approved |
| MS-0008 | Document `--extra-args` quoting for repeated flags |

### CLI / defaults

- No new required flags.
- Zero `--invite-email` → bit-compatible with MS-0010 inserts (no attendees, no sendUpdates).
- Do not change hard-coded `--email-to` default.
- `_watch_child_arguments` parent-only list gains `--invite-email`.

### Security / guardrails

- Discovery/notification/calendar side-effects only; **no trading**.
- Invites are explicit owner CLI/unit input — not scraped contacts.
- Never commit live third-party addresses; docs use fictional examples.
- Never email/write password, refresh token, or client_secret contents.
- Tests: fake calendar client only; no real Google invite spam in CI.
- Be mindful: each matched new market **will email external people via Google** — README ops caution (similar to email noise note).

### Versioning / compatibility

- No match-file schema bump.
- No required calendar-state schema bump in v1 (optional stretch to record attendees).
- No behavior change without `--invite-email`.
- `VERSION` bump on ship per release policy.
- README + help text updated in implementation.

---

## Requirements (normative once approved)

1. Provide repeatable `--invite-email ADDRESS`.
2. With `--watch-new --calendar-add-new` and one or more valid invites, each **successful new** calendar insert includes those attendees and requests Google notification (`sendUpdates=all`).
3. With zero invites, insert behavior matches pre-MS-0013 (no attendees key; no sendUpdates required).
4. `--invite-email` without `--calendar-add-new` fails fast with an actionable message.
5. Invalid addresses fail fast before the watch loop.
6. Phrase non-match or missing schedule: no insert → no Google attendee invite (existing rules).
7. Insert failures still use calendar error email to owner SMTP path; watch continues.
8. Parent-only flag stripping includes `--invite-email`.
9. Offline tests assert attendees on body + sendUpdates on insert; no real Google/SMTP.
10. README documents calendar attendee invites and noise caution.
11. No trading; no secrets in git; CLI defaults preserved when idle.

---

## Failure behavior

| Situation | Behavior |
|-----------|----------|
| No invites | MS-0010 unchanged |
| Valid invites + successful match/insert | Event created with attendees; Google notifies |
| Valid invites + no phrase match | No event; no invite |
| Valid invites + missing schedule | No event; owner calendar error email (no attendees involved) |
| Google rejects attendee / sendUpdates | Insert fails → owner calendar error email; no state mark as success |
| Bad invite syntax | Exit before watch; name bad value |
| Too many invites | Exit with cap message |
| Invites without `--calendar-add-new` | Exit; explain flag pairing |
| Token/API permission error | Actionable calendar error path; README re-auth if needed |

---

## Test plan

### Offline automated (required)

1. **normalize/validate invites:** order, casefold dedupe, reject bad strings, enforce max.
2. **`build_calendar_event_body`:** with invites → `attendees` list of `{email}`; without → key absent; description still free of secrets.
3. **`insert_event` fake:** when attendees present, client receives `send_updates="all"` (or equivalent kw); when absent, no sendUpdates / None.
4. **`maybe_add_calendar_event_for_new_market`:** matched event → insert called once with attendees; non-match → no insert.
5. **main/argparse:** `--invite-email` repeatable; without `--calendar-add-new` → SystemExit; child argv drops flag+values.
6. **Regression:** existing calendar tests still pass with no invites.
7. Factory compile/help/version smoke green.

### Manual owner proof (not CI)

1. `--calendar-auth` if needed; then:
   ```bash
   ./mention_scout.py --watch-new --calendar-add-new \
     --invite-email FRIEND@gmail.com
   ```
2. On a matched new (or carefully staged) market: friend receives Google Calendar invite; event shows guest on owner’s calendar.
3. Restart without `--invite-email`: new events have no guests.
4. Confirm `--email-new` still only SMTP-mails `--email-to` (unless stretch fan-out later).

### Explicit non-tests

- No real Google Calendar invites in pytest.
- No real SMTP.
- No live Kalshi required for unit tests (fixtures/fakes).

---

## Acceptance criteria

1. Repeatable `--invite-email` adds those addresses as attendees on newly created MS-0010 events.
2. Google notification is requested on those inserts (`sendUpdates=all`).
3. Omitting the flag leaves calendar creates unchanged.
4. Flag without `--calendar-add-new` fails fast.
5. Bad addresses fail fast; offline tests cover body + insert wiring.
6. Owner SMTP paths remain single-recipient unless a later MS says otherwise.
7. Docs warn that external guests get Google invites on each matched create.
8. Independent verification + explicit ship approval before release.

---

## Implementation sketch (non-binding)

1. Add `--invite-email` append flag near calendar/email args; help: “Add ADDRESS as a Google Calendar attendee on events created by --calendar-add-new (repeatable).”
2. Normalize/validate invites when calendar-add-new or when list non-empty (pairing rules above).
3. Extend `build_calendar_event_body` + `CalendarClient.insert_event` / `GoogleCalendarApiClient`.
4. Pass invites from `maybe_add_calendar_event_for_new_market`.
5. Parent-only argv update; README calendar subsection + ops caution.
6. Tests in `tests/test_calendar_invite_email.py` (or extend `test_calendar_add.py`).
7. `VERSION` bump on ship.

No implementation until **approved**. No agent spawn without explicit OK.

---

## Risks

| Risk | Mitigation |
|------|------------|
| External people get mail on every matched new market | Opt-in flag; README caution; start with one invite |
| Google suppresses notifications without sendUpdates | Always set `sendUpdates=all` when attendees non-empty |
| Some accounts block inviting external guests | Surface API error via calendar error email |
| Scope/token surprise | Stay on `calendar.events`; document re-auth only if proven |
| Confusing “invite” with SMTP fan-out | Help text + README say **calendar attendees**; SMTP unchanged |
| Accidental invite of self via copy-paste | Dedupe only; allow self if owner passes it (harmless organizer duplicate possible — Google may ignore) |
| systemd quoting of repeated flags | Document `--extra-args` examples |

---

## Explicit non-actions until approval

- No implementation worktree  
- No real email / real Google invites  
- No GitHub issue/PR unless you ask  
- No agent spawn  
- No product code edits in this proposal step  

---

## Owner questions (need decisions before APPROVED)

Defaults in **bold** = coordinator recommendation after your clarification (“calendar attendees to the invite created”).

**Already confirmed by owner (2026-08-17):**

- **Q1 / Q10 — Product meaning:** Google Calendar attendees on MS-0010-created events **only**. **No SMTP fan-out** of scout mail to invitees for now.

Still open (defaults in **bold** for `approve MS-0013 with defaults`):

2. **Flag name still `--invite-email`?**  
   **Default: yes** (matches your ask).  
   Alt: `--calendar-attendee` (clearer, less git-send-email-y).

3. **`sendUpdates` value?**  
   **Default: `"all"` when attendees present; omit/none otherwise.** (Google Calendar notifies guests — still not scout SMTP.)  
   Alt: `"externalOnly"`; or never notify (attendees on event only — usually wrong).

4. **Include owner `--email-to` as attendee automatically?**  
   **Default: no** (organizer already has the event).  
   Alt: yes always; or only when not primary calendar.

5. **Invites without `--calendar-add-new`?**  
   **Default: fail fast.**  
   Alt: warn and ignore.

6. **`--test-email --invite-email`?**  
   **Default: fail fast** (invites are calendar-only).  
   Alt: ignore invites with warning.

7. **Max invites?**  
   **Default: 20.**  
   Alt: 5 / unlimited.

8. **Attendee visibility in event description?**  
   **Default: no** (API attendees only).  
   Alt: list emails in description footer.

9. **Record attendees in `calendar-added.json`?**  
   **Default: no** schema change in v1.  
   Alt: store list on success rows.

11. **Installer first-class flag?**  
    **Default: no** — `--extra-args` only.  
    Alt: passthrough on install script.

12. **Priority / ordering?**  
    **Default: P2;** independent of MS-0012 implement go-ahead.  
    Alt: bundle after MS-0012; or P1.

13. **GitHub issue on approval?**  
    **Default: yes.**

14. **VERSION bump on ship?**  
    **Default: yes.**

---

## Approval line (paste when ready)

Examples:

- `approve MS-0013 with defaults`
- `approve MS-0013 with defaults except: also SMTP-fan-out new-market mail; flag name --calendar-attendee`

After approval: freeze `.factory/specs/MS-0013-approved.md`, optionally open GitHub issue, and **ask before** any implement/verify agent.
