# Architecture Notes — mention-scout

Status: observed from MS-0001 read-only audit (2026-07-25)  
Product: find Kalshi mention markets and notify the owner; **read-only w.r.t. trading**

## Repository layout

| Path | Role |
|------|------|
| `kalshi_mention_scout.py` | Sole product implementation (~2058 lines). Docstring self-identifies as `kalshi_mention_scout_v16.py`. `VERSION = "16.0.0"`. |
| `mention_scout.py` | **Not present** in repo root (no file, no symlink). Factory/AGENTS guardrails still name this as the user-facing stable command. |
| `AGENTS.md`, `.factory/*` | Factory contracts, standards, release policy |
| `scripts/factory-worktree.sh` | Create/list/remove task git worktrees |
| `scripts/factory-test.sh` | `py_compile` + `--help` smoke on `kalshi_mention_scout.py`; runs `pytest` only if `tests/` exists |
| `scripts/factory-package.sh` | Clean-tree `git archive` tarball + sha256 under `dist/` |
| `.gitignore` | Ignores `.venv/`, `dist/`, `.env*`, `.factory/runtime/`, and local cache globs `.kalshi_mention_scout_*cache*.json` |
| `tests/` | **Absent** — no automated unit/regression suite yet |
| `dist/`, `.factory/{improvements,specs,tasks,verification,releases,runtime}/` | Packaging and factory lifecycle dirs (empty at audit time except contracts/inbox) |

### File naming / version situation (current)

- Single on-disk implementation: `kalshi_mention_scout.py` (executable UTF-8 Python 3).
- Internal identity: docstring `kalshi_mention_scout_v16.py`, `VERSION = "16.0.0"`, `CACHE_FORMAT_VERSION = 5`, `QUEUE_FORMAT_VERSION = 1`.
- **No** separate versioned filename (e.g. `kalshi_mention_scout_v16.py`).
- **No** `mention_scout.py` stable symlink/wrapper.
- `.factory/project.yaml` `entry_script` / `resolved_entry_script`: both `kalshi_mention_scout.py`.
- Factory test/package scripts target `kalshi_mention_scout.py` only.

Intended long-term model (from AGENTS/standards, not yet realized on disk): versioned implementation files + stable user command (`./mention_scout.py`) updated only after independent verification PASS and explicit owner approval.

## Runtime shape

Monolithic single module, **no classes** (~62 top-level functions). Standard library only (`urllib`, `argparse`, `subprocess`, `zoneinfo`, etc.). External runtime dependency for email: **`swaks`** on `PATH`. Credential file default: `~/.config/.google-password` (sourced via zsh/`sh`; never printed or cached by the scout).

## Logical modules (within `kalshi_mention_scout.py`)

1. **Constants / classification patterns** — API base URLs, cache/queue defaults, mention/say regexes, ticker-date regexes, ANSI colors.
2. **HTTP client** — `http_get_json` (timeouts, retries with backoff for 429/5xx, actionable `RuntimeError`s).
3. **Kalshi discovery** — `iter_markets`, `iter_events_with_nested_markets`, `scan_mention_events`, `scan_paused_mention_markets`, `merge_market_lists`, `fetch_event_metadata`.
4. **Mention classification** — `is_mention_event`, `is_mention_market`, `contains_filter`, ticker `MENTION` shortcut + text rules.
5. **Cache** — load/usability/atomic write/payload build; compact vs full modes.
6. **Schedule / window selection** — event-date resolver vs trading close; local calendar window.
7. **Normalization / display** — `market_record`, overview grouping, human renderers, Kalshi public URL builder.
8. **Watch mode** — child-process JSON refresh, new-parent-ticker detection, optional queue + email.
9. **Email** — password load, `swaks` send, test-email path.
10. **CLI** — `build_parser`, `main`.

## Entry points and CLI

Primary process entry: `main()` via `if __name__ == "__main__"`.

### Control flow branches

1. `--test-email` → one SMTP test via swaks, then exit (incompatible with watch/email-new/queue flags).
2. `--watch-new` → `watch_new_events` long-running loop (`--email-new` / `--queue-initialized` only valid with watch).
3. Default one-shot discovery → cache/fetch → filter → render human or `--json`.

### Notable flags and defaults

| Flag | Default | Notes |
|------|---------|--------|
| `--days` | `7` | Calendar days for `--window event`; 24h days for `--window closing` |
| `--window` | `event` | `event` \| `all` \| `closing` |
| `--sort` | `auto` | `event` when window=event, else `close` |
| `--env` | `prod` | `prod` / `external` / `demo` → `BASE_URLS` |
| `--status` | `both` | `open`, `unopened`, `paused`, `both`=(open+unopened), `upcoming`=(+paused) |
| `--include-inactive` | off | Appends `paused` if not already selected |
| `--timezone` | `America/New_York` | Display + date-only fallbacks |
| `--timeout` | `20.0` s | Per HTTP request |
| `--retries` | `3` | Transient failures |
| `--full-cache` | off | Complete `/markets` scan vs compact mention-only |
| `--cache-ttl` | `300` s | |
| `--refresh` / `--no-cache` | off | Bypass / disable disk cache |
| `--watch-new` | off | New parent-event watcher |
| `--poll-seconds` | `300` (min 30) | Watch interval |
| `--queue-initialized` | off | Write opener jobs under `--queue-dir` (default `mention_open_queue`) |
| `--email-new` | off | Email on new parent events (requires watch) |
| `--test-email` | off | One-shot SMTP proof |
| `--google-password-file` | `~/.config/.google-password` | |
| `--email-to` / `--email-from` / `--smtp-auth-user` | hard-coded owner Gmail defaults | |
| `--smtp-server` | `smtp.gmail.com:587` | |
| Output | grouped human | `--overview`, `--flat`, `--json`, `--show-rules`, `--no-color`, `--contains`, `--verbose` |

Guardrail: preserve these CLI defaults and cache compatibility unless a deliberate approved spec changes them.

## Data flow (one-shot)

```
CLI args
  → resolve base_url, status tuple, cache_mode (mention|full), cache_path
  → optional load_cache + cache_usable (format version, mode, base URL, status subset, TTL, snapshot_scope)
  → on miss/refresh:
       compact: scan_mention_events(/events + nested markets for open/unopened)
                + optional scan_paused_mention_markets(/markets?status=paused)
       full:    iter_markets(/markets per status)
  → optional write_cache_atomic (mode 0600, temp+replace)
  → filter: _scan_status in requested statuses ∧ is_mention_market ∧ --contains
  → fill missing parent event_details via /events?event_tickers=… (batch)
  → window:
       event   → local calendar date of resolved event schedule in [today, today+days-1]
       closing → close_time in [now, now+days]
       all     → no time horizon
  → market_record + sort
  → render grouped | flat | overview | JSON snapshot
```

JSON snapshot (used by watch child) includes: `generated_at_utc`, `timezone`, `api_base_url`, `status_filter`, `cache`, `summary`, `markets` (normalized records), `event_overview` (when `--overview`).

## Kalshi API flow

- **Bases:** prod `https://api.elections.kalshi.com/trade-api/v2`, plus `external` and `demo`.
- **Auth:** none for public market/event GETs observed here.
- **Endpoints used:**
  - `GET /events?status={open|unopened}&with_nested_markets=true&limit=200&cursor=…` — compact discovery.
  - `GET /markets?status={…}&limit=1000&mve_filter=exclude&cursor=…` — full cache and paused supplement (`status=paused`).
  - `GET /events?event_tickers=…&limit=…` — parent schedule/metadata backfill (chunked).
- **Timeouts / errors:** per-request timeout; retries with exponential backoff capped at 8s for 429 and 5xx; other HTTP codes fail fast with truncated body; network/JSON errors wrapped as `RuntimeError`.
- **No trading endpoints.** Discovery and notification only.

### Status handling

- Query statuses: `open`, `unopened`, `paused`.
- Nested market payloads may show lifecycle `active` while parent came from `status=open`; scout stores `_scan_status` = requested query status for filtering and keeps raw API `status` for display.
- `cached_market_status` normalizes aliases: `active`/`opened`→`open`, `initialized`→`unopened`, `inactive`→`paused`.
- Compact mode cannot get paused from `/events`; adds targeted `/markets?status=paused` pass when paused is in the status set.

## Date / time selection

Two intentionally separate concepts:

1. **Event date/time** (scheduling / default `--window event`) — never uses trading close.
2. **Trading close** (`close_time`) — `--window closing` and secondary display/sort.

### Event schedule resolver (`event_schedule_for_market`) priority

1. Parent event datetime-ish fields: `occurrence_datetime`, `occurrence_time`, `scheduled_datetime`, `event_datetime`, `start_datetime`, `start_time`, `start_ts`
2. Parent date-only: `strike_date`, `event_date`, `scheduled_date`, `date` (local calendar interpretation)
3. Parent `sub_title` human date (e.g. `On Jun 23, 2026`)
4. Market subtitle fields with same human-date parse
5. Date embedded in event ticker (`-26JUN23` pattern)
6. Last resort: market `expected_expiration_time` (labelled as schedule fallback)
7. Else no event date → excluded from `--window event`

Sources are labelled in human output. Default event window: local today through today+(days−1) inclusive.

## Cache formats

| | Compact (default) | Full (`--full-cache`) |
|--|-------------------|------------------------|
| Default file | `.kalshi_mention_scout_mentions_cache.json` | `.kalshi_mention_scout_full_cache.json` |
| `cache_mode` | `mention` | `full` |
| `snapshot_scope` | `mention_events_scan` | `complete_markets_scan` |
| Contents | Mention-matching markets only + `event_details` from discovery | All non-MVE live markets; event_details filled lazily |
| Format version | `cache_format_version: 5` | same |
| Usability | Same base URL, mode, scope; cached status set must be **superset** of requested; age ≤ TTL | same rules |

Atomic write: temp file in same dir, `0o600`, fsync, `os.replace`. Incompatible/malformed caches ignored (rebuild). Private caches gitignored.

## Duplicate suppression / “new market” detection

### Within a scan

- Compact scan de-dupes child markets by contract `ticker`, preferring `open` over other statuses when duplicated across status pages.
- `merge_market_lists` merges open/unopened + paused with status rank preference.

### Watch mode (`--watch-new`)

- A “new market” is a **new parent Kalshi `event_ticker`**, not a quote/status change on an existing event.
- Baseline snapshot: print overview; baseline tickers are **not** announced as new.
- Each refresh: `new_tickers = current_event_tickers − known_event_tickers`.
- `known_event_tickers` only grows (union); temporary disappearance then reappearance does **not** re-alert.
- Loud terminal banner + full overview + grouped contracts (rules on) for each new ticker.
- Optional one email per new parent event; email failures are logged and do not stop the watch loop.

## Watch loop details

- Builds child argv from original argv, stripping watch/email/queue/smtp-only flags.
- If user did not pass `--status` / `--window`, child forces `--status upcoming` and `--window all` (so overnight listings without event dates are not missed).
- Child always adds `--overview --json --refresh --no-color`.
- Refresh mechanism: **`subprocess.run([sys.executable, this_script, *child_argv])`** and parse stdout JSON — one-shot path is source of truth for cache/date/status logic.
- Default poll 300s (5 min); minimum 30s; Ctrl-C clean exit.
- Incompatible with `--flat` and `--json` on the parent watch process.

### Queue handoff (`--queue-initialized`)

- For events with any initialized/unopened child contracts, write `queue_dir/pending/{event_ticker}.json` once (never overwrite existing).
- Payload: `queue_format_version`, state, tickers, event overview blob, empty progress fields for a separate opener watcher.
- Uses same atomic write helper as cache.

## Email path

- **Config check:** `load_google_password` — file must exist, be a regular file, mode not group/other-accessible; sourced with `zsh -f` (preferred) or `/bin/sh`; requires non-empty `GOOGLE_PASSWORD`; value kept in memory only (`args._google_password` during watch).
- **Send:** `run_swaks_email` → `swaks --to/--from/--server --auth LOGIN --auth-user/--auth-password --tls --header Subject --body`.
- **New-market body:** plain-text overview including statuses, times, and clickable Kalshi event URL (`kalshi_event_url`: prefer API URL fields, else construct `https://kalshi.com/markets/{series}/{title-slug}/{event}`).
- **`--test-email`:** fail-fast config + one fixed subject/body sample link; does not enter watch.
- **Factory rule:** never send real email during implementation/verification; no DI/dry-run flag exists yet — tests must mock `subprocess` / inject a fake sender if email logic is covered.

## Test seams (current)

| Seam | Notes |
|------|--------|
| Pure helpers | Date parse, status normalize, mention classify, cache_usable, URL slug, schedule resolver, watch event map — unit-testable without network |
| `--json` | Machine-readable one-shot output for fixtures/golden tests |
| Watch child subprocess | Integration-heavy; can stub `fetch_watch_snapshot` if extracted/patched |
| Email | No dry-run; depends on `swaks` + credential file + real SMTP unless mocked at `subprocess.run` / `run_swaks_email` |
| HTTP | `http_get_json` / iterators are concrete; no injected transport yet |
| `tests/` | Missing; `factory-test.sh` only compile + `--help` until tests appear |

## Packaging and factory scripts

- **Test:** compile resolved entry + `--help`; optional pytest.
- **Package:** refuse dirty tree; `git archive` → `dist/mention-scout-<version>.tar.gz` + `.sha256`.
- **Worktree:** branch `openclaw/<task-id>` under `~/.openclaw/factory-worktrees/mention-scout/` (or `FACTORY_WORKTREE_ROOT`); runs `.openclaw/worktree-setup.sh` (venv + optional deps files if present).

## Security / safety boundaries

- No order placement, modification, or cancellation code paths observed.
- Secrets: password file outside repo; gitignore for env and caches; cache files mode 0600.
- Network: public GETs only with timeouts and bounded error bodies.
- Email password never written to cache or intentionally printed.

## Gaps relevant to factory work

1. Stable `./mention_scout.py` command named in guardrails but missing on disk.
2. Versioned implementation filename + symlink model not materialized (v16 lives inside `kalshi_mention_scout.py`).
3. No `tests/` directory despite standards requiring regression tests for date/status/cache/dup/watch/email changes.
4. Email path not mock-friendly without patching subprocess.
5. Hard-coded default notification addresses in argparse (functional for owner machine; less ideal for shared/package use).
