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
| `deploy/systemd/` | User unit template (placeholders) |
| `scripts/install-user-service.sh` | Install/update/disable user watch unit |
| `tests/` | Offline unit tests |
| `scripts/factory-test.sh` | Compile + CLI smoke (+ pytest) |
| `.factory/` | Specs, tasks, architecture (agent factory) |

```bash
./scripts/factory-test.sh
```

## Run as a systemd user service

For unattended `--watch-new` (optionally with email) under **user** systemd — no system-wide unit, no trading.

### Prerequisites

- Python 3 on `PATH` (installer records an absolute interpreter path)
- A git checkout that contains `./mention_scout.py`
- For email alerts (default in the generated unit): `swaks` on `PATH` and `~/.config/.google-password` (mode `600`) — same as interactive `--email-new`
- A working user systemd session (`systemctl --user`)

### Install (one-liner)

From the repo root:

```bash
./scripts/install-user-service.sh --enable-now
```

Defaults bake **watch + email** into the unit (`--watch-new --email-new`). Interactive CLI defaults are unchanged: bare `./mention_scout.py --watch-new` stays watch-only unless you pass `--email-new`.

Safer bring-up while tuning filters (watch only):

```bash
./scripts/install-user-service.sh --no-email --enable-now
```

Dry-run (no writes, no `systemctl` side effects):

```bash
./scripts/install-user-service.sh --dry-run
./scripts/install-user-service.sh --dry-run --no-email
```

Other useful flags: `--disable`, `--uninstall`, `--poll-seconds N`, `--working-directory PATH`, `--python PATH`, `--unit-name NAME`, `--extra-args "..."`, `--strict` (fail email preflight instead of warning).

### Boot without interactive login (linger)

User units normally start at login. For start-at-boot **without** a GUI/SSH login:

```bash
loginctl enable-linger "$USER"
```

The installer may **hint** if linger is off; it does **not** enable linger unless you pass `--enable-linger` explicitly. Do not enable linger on shared machines without understanding the implications.

### WorkingDirectory, cache, and queue

The unit sets `WorkingDirectory` to the **absolute checkout root** resolved at install time. Default cache (`.kalshi_mention_scout_mentions_cache.json`) and optional queue dir are CWD-relative, so they land next to the code you installed from.

Re-run the installer after moving the checkout (or fix paths in the unit). Multiple checkouts need distinct `--unit-name` / paths.

### Logs and status

```bash
systemctl --user status mention-scout-watch.service
journalctl --user -u mention-scout-watch.service -f
```

Stdout/stderr go to the user journal (`SyslogIdentifier=mention-scout-watch`).

### Disable / uninstall

```bash
./scripts/install-user-service.sh --disable
./scripts/install-user-service.sh --uninstall
```

Uninstall disables the unit, removes `~/.config/systemd/user/mention-scout-watch.service` (or `$XDG_CONFIG_HOME/...`), and runs `daemon-reload`. It does **not** delete the repo, caches, password file, or linger setting.

### Ops caution (email noise)

Unattended `--email-new` can mail on every newly seen parent event. If classification is noisy, prefer `--no-email` until you are happy with interactive watch output. No secrets are written into the unit file; the app still loads `~/.config/.google-password` at runtime.

### Template location

Checked-in template (placeholders only): `deploy/systemd/mention-scout-watch.service`  
Installer: `scripts/install-user-service.sh`

## Safety

- **No trading** — market data + optional notifications only.
- Do not commit `.env`, password files, OAuth tokens, or private cache JSON.
- Local caches (gitignored): `.kalshi_mention_scout_*cache*.json`

## License / access

Private repository: https://github.com/rpgrimm/mention-scout
