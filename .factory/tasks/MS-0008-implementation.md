# MS-0008 — Implementation notes

Status: **IMPLEMENTED** (pending independent verification)  
Branch: `openclaw/ms-0008`  
Worktree: `/home/candr/.openclaw/factory-worktrees/mention-scout/ms-0008`  
Spec: `.factory/specs/MS-0008-approved.md`  
Issue: https://github.com/rpgrimm/mention-scout/issues/10

## What shipped

Packaging / docs / helper only — **no** discovery, classification, cache, or email-runtime logic changes.

| Artifact | Path | Role |
|----------|------|------|
| Unit template | `deploy/systemd/mention-scout-watch.service` | Placeholders `@REPO_ROOT@`, `@PYTHON@`, `@ENTRY@`; restart-on-failure / journal / no secrets |
| Installer | `scripts/install-user-service.sh` | Substitute abs paths; install/update; daemon-reload; enable/start/disable/uninstall/dry-run |
| Docs | `README.md` § “Run as a systemd user service” | Prereqs, linger (manual), journalctl, WorkingDirectory/cache, uninstall, MS-0007 caution |
| Tests | `tests/test_install_user_service.py` | Offline dry-run + temp `XDG_CONFIG_HOME` install/uninstall with stub `systemctl` |

## Owner defaults honored

1. Script-first — **no** CLI `--install-user-service`
2. Template at `deploy/systemd/mention-scout-watch.service`
3. Installer at `scripts/install-user-service.sh` with full lifecycle flags
4. Default ExecStart: `python + mention_scout.py --watch-new --email-new` (absolute paths)
5. `--no-email` → watch-only
6. `WorkingDirectory` = absolute checkout root (overridable)
7. `Restart=on-failure`, `RestartSec=30`, start limits 5 / 300s
8. stdout/stderr → journal
9. No secrets in unit; app default password path referenced in comments only
10. Linger documented + optional hint; auto linger only with explicit `--enable-linger`
11. README ops section
12. User systemd only (`$XDG_CONFIG_HOME/systemd/user` or `~/.config/systemd/user`)
13. No trading; no real email in tests
14. Interactive CLI defaults and `./mention_scout.py` preserved

## Installer behavior (summary)

```bash
./scripts/install-user-service.sh --enable-now          # default: watch + email
./scripts/install-user-service.sh --no-email --enable-now
./scripts/install-user-service.sh --dry-run
./scripts/install-user-service.sh --disable
./scripts/install-user-service.sh --uninstall
```

- Resolves absolute `REPO_ROOT`, `PYTHON` (`command -v python3` or `--python`), stable `ENTRY` (`mention_scout.py`, symlink kept — not resolved to implementation filename).
- Renders template; replaces `ExecStart` for email/poll/extra-args variants.
- Email preflight (when email on): warn if `swaks` missing or password file missing/unsafe mode; `--strict` fails. **Never reads/prints password contents.**
- Idempotent re-install rewrites the unit file safely.
- Does not delete caches, password file, repo, or linger on uninstall.

## Tests / verification (implementer)

```text
./scripts/factory-test.sh   # compile + help/version + pytest
# 54 passed (prior MS-0006 tests + new installer tests)
./scripts/install-user-service.sh --dry-run
./scripts/install-user-service.sh --dry-run --no-email
```

No real SMTP. No live Kalshi watch. No linger enablement in automated checks. Stub `systemctl` used for write/uninstall unit tests under temp `XDG_CONFIG_HOME`.

## Non-goals honored

- No `kalshi_mention_scout.py` / classification / MS-0007 changes
- No system-wide units
- No CLI install flag
- No secrets or host-only absolute paths in committed template
- No trading paths

## Ready for

Independent verification on a clean worktree (file presence, dry-run, hygiene, `factory-test.sh`). Do **not** merge or ship from this report alone.
