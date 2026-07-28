# mention-scout

Find active/upcoming **Kalshi mention markets** and optionally watch for new ones (with email alerts).

Read-only w.r.t. trading — discovery and notification only. Never places or cancels orders.

## Quick start

```bash
git clone https://github.com/rpgrimm/mention-scout.git && cd mention-scout && ./mention_scout.py --overview
```

That one-liner clones the repo and prints an overview of open/unopened mention events in the next 7 days (default window).

If you already have the repo checked out:

```bash
./mention_scout.py --overview
```

Requirements: **Python 3** (stdlib only). No `pip install` for basic discovery.

## Common commands

```bash
# Overview of upcoming mention events (next 7 calendar days)
./mention_scout.py --overview

# Filter by type (earnings, shows, etc.)
./mention_scout.py --overview --type earnings
./mention_scout.py --overview --type face-the-nation,world-news-tonight

# Type aliases: ftn, wnt, world-news
./mention_scout.py --overview --type ftn

# Substring filter (AND with --type)
./mention_scout.py --overview --type earnings --contains carnival

# Full contract list (grouped) or machine-readable JSON
./mention_scout.py
./mention_scout.py --json

# Force a fresh API pull (ignore disk cache)
./mention_scout.py --overview --refresh

# Watch for newly created parent events (Ctrl-C to stop)
./mention_scout.py --watch-new

# Watch + email on each new parent event (needs swaks + Gmail app password)
./mention_scout.py --watch-new --email-new
```

## Mention types

| Filter id (`--type`) | Label in UI / email subject |
|----------------------|-----------------------------|
| `earnings` | earnings |
| `face-the-nation` | Face the Nation |
| `world-news-tonight` | World News Tonight |
| `trump` | Trump |
| `say` | say |
| `other` | other |

New-market email subjects look like:

```text
[Kalshi] earnings | NEW: KXEARNINGSMENTIONCCL-26JUN23
[Kalshi] Face the Nation | NEW: KXFTNMENTION-26JUL05
```

## Email setup (optional)

Used only by `--email-new` / `--test-email`.

1. Install [swaks](https://www.jetmore.org/john/code/swaks/) and put it on `PATH`.
2. Create `~/.config/.google-password` (mode `600`) with a Gmail app password:

```bash
# ~/.config/.google-password
GOOGLE_PASSWORD='your-app-password'
chmod 600 ~/.config/.google-password
```

3. Prove SMTP:

```bash
./mention_scout.py --test-email
```

The password file is sourced, never printed or cached by the scout.

## Defaults worth knowing

| Flag | Default |
|------|---------|
| `--days` | `7` |
| `--window` | `event` (filter by event date, not trading close) |
| `--status` | `both` (open + unopened) |
| `--env` | `prod` |
| `--timezone` | `America/New_York` |
| `--type` | all types |
| cache | compact mention cache, 300s TTL |

```bash
./mention_scout.py --help
./mention_scout.py --version
```

## Project layout

| Path | Role |
|------|------|
| `./mention_scout.py` | Stable entry (symlink) |
| `kalshi_mention_scout.py` | Implementation (v16) |
| `tests/` | Offline unit tests |
| `scripts/factory-test.sh` | Compile + CLI smoke (+ pytest) |
| `.factory/` | Specs, tasks, architecture (agent factory) |

```bash
./scripts/factory-test.sh
```

## Safety

- **No trading** — market data + optional notifications only.
- Do not commit `.env`, password files, OAuth tokens, or private cache JSON.
- Local caches (gitignored): `.kalshi_mention_scout_*cache*.json`

## License / access

Private repository: https://github.com/rpgrimm/mention-scout
