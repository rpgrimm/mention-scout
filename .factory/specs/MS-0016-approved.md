# MS-0016 — mention-markets util (list / target / google-news tabs)

Status: **APPROVED** by owner 2026-09-25 (chat: new util on JSON events; first action is Google `{word} news` tabs; “make a PR and I’ll test it on my desktop”).
Type: feature (desktop util; discovery only)
Priority: P2 (owner-requested)
Related: MS-0010 calendar-added.json, kalshi_broadcast_word_trader.py (word/API reference only)
Repository: `rpgrimm/mention-scout`
Stable command (existing): `./mention_scout.py` (do not retarget)
New command: `./mention_markets.py`
Review publication: branch `openclaw/ms-0016` + pull request into `main`. Do **not** merge. Do **not** push to `main`.

## Owner intent (frozen)

1. New util operates on mention **events already recorded in JSON** under `~/.config/mention-scout/`.
2. **List** those events.
3. **Target** one event ticker (example: `KXWORLDNEWSMENTION-26SEP25`).
4. Targeted events support **actions**. First action: fetch that event’s mention markets from **Kalshi public REST**, then open a browser tab per market word searching Google for `"<word> news"`.
5. Slash phrases become a single query with slashes removed: `OpenAI / Anthropic` → Google `OpenAI Anthropic news`.
6. Reference for fetch + word extraction: `/home/candr/code/dev/kalshi-multiplex-orderbook/kalshi_broadcast_word_trader.py` (`public_json_get`, `fetch_markets_rest_paginated`, `market_word`). **Copy the read-only idea, not trading.**
7. Open a PR for desktop testing. No merge, no release, no systemd, no email.

## Non-goals

- No trading, orders, WebSockets, API keys, or kalshi-python-sync.
- Do not import or vendor `kalshi_broadcast_word_trader.py`.
- Do not change watch/email/calendar-add behavior or CLI defaults of `mention_scout.py`.
- Do not read or print `~/.config/.google-password`, OAuth tokens, or client secrets.
- Do not write calendar JSON.
- No extra actions beyond `google-news` in this MS (keep the action registry easy to extend).

## JSON source

Default file:

```text
~/.config/mention-scout/calendar-added.json
```

Shipped schema (MS-0010): `{ "version": 1, "entries": { "<EVENT_TICKER>::<calendar_id>": { added_at_utc, kind, calendar_event_id, html_link, matched_phrase } } }`.

Event ticker for list/target = the key before `::`. Duplicate keys for the same ticker: keep the latest `added_at_utc`.

Override with `--json PATH`. Missing/unreadable/invalid file: non-zero exit, stderr message, no browser.

## CLI

```text
./mention_markets.py list [--json PATH]
./mention_markets.py target EVENT_TICKER [--action google-news] [--dry-run] [--json PATH]
```

- `list`: print one event per line, newest `added_at_utc` first:
  `EVENT_TICKER<TAB>added_at_utc<TAB>matched_phrase`
- `target EVENT_TICKER`: case-insensitive; accept a raw `::primary` key and strip the suffix.
- If the ticker is **not** in the JSON: exit 1, tell the user to `list`. (Direct Kalshi-only target is out of scope for v1.)
- Default `--action` for `target` is `google-news`.
- `--dry-run`: fetch and print `word<TAB>url` (stderr: count); **do not** open a browser.
- Unknown action: exit 1 with the known action names.
- `--help` / `-h` works. `--version` prints a util version string (start at `1.0.0`).

## Kalshi fetch (target)

- Unauthenticated GET `https://api.elections.kalshi.com/trade-api/v2/markets`
- Query: `event_ticker=<TICKER>&limit=1000` plus `cursor` pagination (cap 20 pages; fail if cursor repeats).
- Timeouts, retries on 429/5xx (same spirit as mention-scout: timeout default 20s, a few retries).
- Keep markets whose status is `active` or `open` (Kalshi uses both).
- Empty market list: exit 1, no browser.
- Network/HTTP errors: actionable stderr, non-zero, no browser.

### Word extraction

Match trader `market_word`:

1. If `yes_sub_title` or `subtitle` contains `/` or `\`, use that field.
2. Else `custom_strike["Word"]` or `yes_sub_title` or `subtitle` or `ticker`.

Skip UNKNOWN/empty. Deduplicate markets by ticker. Sort words case-insensitive for stable output.

### Google query

One tab per **market**, not per slash-alias.

```text
raw word  ->  replace / and \ with spaces  ->  collapse whitespace
          ->  strip a trailing "(N+ times)" / "(N times)" parenthetical
          ->  query "{cleaned} news"
URL: https://www.google.com/search?q=<url-encoded query>
```

Examples:

| word | query |
|------|-------|
| Starbucks | Starbucks news |
| OpenAI / Anthropic | OpenAI Anthropic news |
| AI / Artificial Intelligence | AI Artificial Intelligence news |
| Iran (3+ times) | Iran news |

## Browser

- Use stdlib `webbrowser.open_new_tab`. Inject an opener in tests.
- Small delay between tabs (default ~0.15s, `--sleep` optional) so the desktop browser keeps up.
- If `DISPLAY`/`WAYLAND_DISPLAY` is unset and not `--dry-run`, print a warning that this looks headless, still attempt open (owner’s desktop will have a display).
- Never fail the whole run after a successful fetch just because one tab open returned false; warn and continue.

## Tests (offline)

`tests/test_mention_markets.py` with mocked HTTP (no live Kalshi, no real browser):

1. Parse `calendar-added.json` keys → unique event tickers, latest entry wins.
2. `list` formatting / missing file.
3. `target` unknown ticker exits 1.
4. Query cleaning table including slash and `(3+ times)`.
5. Paginated `/markets` mock → words + URLs; opener called once per market unless `--dry-run`.
6. `--dry-run` never calls opener.
7. Inactive/unopened markets are not opened.

`./scripts/factory-test.sh` must run these via existing pytest hook.

## Docs

README: short “Mention markets util” section with `list` / `target` / `--dry-run` examples. State: discovery only, no trading.

`.factory/specs/MS-0016-approved.md` (this spec) and `.factory/tasks/MS-0016.md` in the PR.

## Acceptance

1. `list` shows `KXWORLDNEWSMENTION-26SEP25` from the owner’s calendar-added JSON.
2. `target KXWORLDNEWSMENTION-26SEP25 --dry-run` prints a Google URL for OpenAI/Anthropic as `OpenAI Anthropic news` when that market is in the API payload.
3. `target … --action google-news` opens one tab per active/open market word (desktop).
4. No secrets, no trading, `mention_scout.py` unchanged in behavior.
5. PR opened against `main` for owner desktop test; not merged.

## Implementation notes

- New file `mention_markets.py` at repo root (executable, Python 3 stdlib). Optional tiny helpers in the same file; do not grow `kalshi_mention_scout.py` unless a shared HTTP helper is truly identical and tested — prefer standalone to keep the watch binary untouched.
- Git author if committing: use the repo/host default (Ryan Grimm).
- Auth: `GH_TOKEN` from `/home/candr/.config/openclaw/github_token` (never print).
- Clone if needed; this host has no `/home/candr/src/mention_scout`.
