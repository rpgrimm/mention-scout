# MS-0008 — systemd --user unit install for boot-time watch

Status: **APPROVED**  
Approved: 2026-08-01 by owner (chat: “approve ms-0008 as well”) with recommended defaults.  
GitHub issue: https://github.com/rpgrimm/mention-scout/issues/10  
Factory id: MS-0008  
Type: feature (packaging / ops install UX)  
Priority: P2  
Related: MS-0007 / #9 (false-positive watch alerts — risk for unattended email; do not block install UX)  
Repository: `/home/candr/src/mention_scout`  
Implementation target: packaging, docs, and helper script(s) under repo; **no discovery-logic change** (CLI install flag deferred)  
Stable command: `./mention_scout.py` (symlink → `kalshi_mention_scout.py`; behavior must match either entry)

---

## Problem

Owner wants mention-scout to start automatically on boot via a **systemd user**
unit, without leaving a terminal open for `--watch-new`.

Today the only long-running path is an interactive process:

```bash
./mention_scout.py --watch-new
# optional:
./mention_scout.py --watch-new --email-new
```

There is no checked-in unit template, no install/uninstall helper, and no README
guidance for user-session linger, journal logs, working directory/cache paths,
or `swaks`/password prerequisites under systemd.

## Current behavior (verified in v16)

| Area | Behavior |
|------|----------|
| Long-running mode | `--watch-new` loop in-process; child one-shot JSON refresh via `subprocess` |
| Default poll | `--poll-seconds` default `300` (min `30`) |
| Email alerts | Opt-in `--email-new` (requires watch); fail-fast on bad/missing `~/.config/.google-password`; needs `swaks` on `PATH` |
| Credential default | `~/.config/.google-password` (mode not group/other-readable); never printed/cached |
| Cache default path | CWD-relative `.kalshi_mention_scout_mentions_cache.json` (compact) |
| Queue default | CWD-relative `mention_open_queue/` when `--queue-initialized` |
| Stable entry | `./mention_scout.py` → `kalshi_mention_scout.py` |
| systemd / deploy | **None** in tree (`deploy/`, `systemd/` absent) |
| README | Covers watch/email interactive use; no user-unit / linger docs |

Without packaging, the owner must hand-write a unit, guess `WorkingDirectory`,
and remember linger/`journalctl --user` details.

## Goal

Ship an **owner-friendly, idempotent install path** for a long-running
mention-scout watch under:

- `systemctl --user`
- unit file installed to `~/.config/systemd/user/`
- enable so it starts on user login (and, with documented linger, at boot without interactive login)

Defaults must be safe, documented, free of committed secrets, and compatible
with existing CLI defaults for interactive use. Installer may emit a unit with
**explicit** flags without changing global argparse defaults.

No trading. No real email during automated implementation/verification.

## Scope

### In scope

1. **Checked-in systemd user unit template** (placeholders; no machine-local absolute paths committed as hard-coded host facts).
2. **Install helper script** that:
   - resolves absolute paths to Python + stable entry (or equivalent)
   - installs/updates the unit under `~/.config/systemd/user/`
   - runs `systemctl --user daemon-reload`
   - optional enable and/or start
   - supports disable/uninstall
3. **README section** covering prerequisites, linger, logs, cache/`WorkingDirectory`, email opt-in, and common `systemctl --user` operations.
4. **Sensible unit policy**: restart-on-failure with delay; stdout/stderr to journal; no secrets in unit file.
5. **Offline verification** of template shape + installer dry-run / path substitution where practical (no live SMTP; no requirement to start a real long watch against Kalshi in CI).
6. Optional **thin** CLI delegate only if it stays a pass-through to the script (see recommended design — default **off / script-first**).

### Out of scope

- system-wide units (`systemctl` without `--user` / files under `/etc/systemd/system`)
- containers, k8s, launchd, cron, or supervisord
- multi-instance `template@.service` / per-filter instance farms (stretch only)
- fixing MS-0007 false-positive classification (separate P1; note ordering risk)
- SMTP/`swaks` rewrite, email dry-run (MS-0004), trading, discovery/filter/cache format changes
- changing interactive CLI defaults when flags are omitted
- auto-enabling `loginctl enable-linger` unless owner explicitly opts in
- committing password files, `.env`, tokens, or host-specific absolute paths in git
- bundling/installing `swaks` or Python via the helper
- `--queue-initialized` as default service behavior (may be documented as override)

### Optional stretch (off unless owner opts in)

- `mention-scout-watch@.service` multi-instance template
- CLI `./mention_scout.py --install-user-service` thin wrapper
- drop-in directory examples (`*.conf`) for owner overrides without editing the generated unit
- packaging the unit into release tarball notes beyond normal git archive inclusion

## Recommended design

### Primary approach (script-first)

| Artifact | Path (recommended) | Role |
|----------|--------------------|------|
| Unit template | `deploy/systemd/mention-scout-watch.service` | Checked-in template with `@PLACEHOLDER@` tokens |
| Installer | `scripts/install-user-service.sh` | Substitute, install, reload, optional enable/start; uninstall/disable |
| Docs | `README.md` § “Run as a systemd user service” | Linger, prereqs, ops cheatsheet |
| CLI flag | **Not in v1** | Prefer script; avoid bloating scout with systemd concerns |

Rationale:

- Keeps product code free of systemd assumptions.
- Easy to review, dry-run, and test with shell + temp `XDG_CONFIG_HOME`.
- Matches packaging-only nature of MS-0002-style work.
- Owner can still hand-copy the template if they distrust the installer.

### Default service command

**Primary recommendation:** watch **with email** enabled in the generated unit:

```text
@PYTHON@ @ENTRY@ --watch-new --email-new
```

Rationale for recommending email-on by default in the *service* (not in interactive CLI):

- Owner request is unattended boot-time operation; the high-value outcome is
  notification without a terminal.
- Interactive `./mention_scout.py --watch-new` remains watch-only unless
  `--email-new` is passed (CLI defaults unchanged).
- Installer **must** support opting out of email for safer headless bring-up
  and while MS-0007 is open.

**Installer flags (recommended):**

| Flag | Effect |
|------|--------|
| (default) | Unit ExecStart includes `--watch-new --email-new` |
| `--no-email` | Unit ExecStart is `--watch-new` only |
| `--email` | Explicit email-on (same as default; useful in scripts) |
| `--enable` | `systemctl --user enable <unit>` |
| `--now` / `--start` | start after install (with or without enable) |
| `--enable-now` | enable + start |
| `--disable` | disable unit (keep file) |
| `--uninstall` | disable + remove installed unit + daemon-reload |
| `--dry-run` | print paths/actions and rendered unit to stdout; no write/start |
| `--poll-seconds N` | optional extra arg baked into ExecStart (default omit → app default 300) |
| `--working-directory PATH` | override WorkingDirectory |
| `--unit-name NAME` | default `mention-scout-watch.service` |
| `--extra-args "..."` | append trusted extra CLI args to ExecStart (documented escape hatch) |

If email is selected, installer **should** preflight (non-fatal warnings by
default; optional `--strict` to fail):

- `swaks` resolvable on `PATH` (or absolute path detection note)
- password file exists at default or overridden path
- password file mode not group/other-accessible (mirror app expectations)

Do **not** read or print password contents.

### WorkingDirectory / cache predictability

**Recommendation:** `WorkingDirectory=` = **absolute path to the git checkout
root** that contains `mention_scout.py` (resolved by installer at install time).

Rationale:

- Cache defaults are CWD-relative (`.kalshi_mention_scout_mentions_cache.json`).
- Queue default is CWD-relative (`mention_open_queue/`).
- Keeps unattended cache next to the code the owner is actually running.
- Avoids inventing a new XDG data layout in this MS (can be a later improvement).

Document clearly:

- Re-run installer after moving the checkout, **or** edit/reinstall unit.
- Multiple checkouts ⇒ multiple units only via stretch/`--unit-name` + paths;
  v1 is single default unit name.

**Not recommended for v1 default:** XDG `~/.local/share/mention-scout/` unless
owner wants cache decoupled from repo (extra flags/`--cache-file` plumbing).

### Unit template shape (normative sketch)

Checked-in template example (tokens replaced by installer):

```ini
[Unit]
Description=Kalshi mention-scout watch (user)
Documentation=file://@REPO_ROOT@/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=@REPO_ROOT@
ExecStart=@PYTHON@ @ENTRY@ --watch-new --email-new
Restart=on-failure
RestartSec=30
# Avoid tight crash loops if configuration is broken
StartLimitIntervalSec=300
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mention-scout-watch
# Do not embed secrets. App loads ~/.config/.google-password by default.
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

Notes:

- When `--no-email`, ExecStart omits `--email-new`.
- `@PYTHON@` should be absolute (`command -v python3` or explicit `--python`).
- `@ENTRY@` should be absolute path to stable `mention_scout.py` inside repo
  (symlink OK; systemd follows). Prefer stable entry over resolved implementation
  name for user-facing consistency.
- Do **not** set `Environment=GOOGLE_PASSWORD=...`.
- Optional: `Environment=PATH=...` only if installer detects need to append
  directories for `swaks`/python; prefer documenting user PATH + linger PATH
  caveats over fragile PATH rewriting. If set, merge conservatively.
- `Restart=on-failure` + `RestartSec=30` + start limits prevent hammering Kalshi/SMTP
  when credentials or network are hard-broken.
- No `WatchdogSec` unless product grows explicit sd_notify (out of scope).

### Linger (boot without login)

True “starts when I boot” for **user** units typically requires:

```bash
loginctl enable-linger "$USER"
```

**Recommendation:**

- Document prominently in README and installer epilogue.
- Installer may **detect** linger state and print a one-line hint if disabled.
- **Do not** run `enable-linger` automatically by default.
- Optional installer flag `--enable-linger` only if owner approves that power
  (default **docs/prompt only**).

Without linger: unit starts at user login/session; may not run on headless boot.

### Logs

```bash
journalctl --user -u mention-scout-watch.service -f
systemctl --user status mention-scout-watch.service
```

Document these in README. No custom log file required in v1.

### Uninstall / disable

```bash
./scripts/install-user-service.sh --disable
# or
./scripts/install-user-service.sh --uninstall
```

`--uninstall` must:

1. `systemctl --user disable --now <unit>` (ignore if not loaded)
2. remove `~/.config/systemd/user/<unit>` if it is the managed unit
3. `daemon-reload`

Do not delete repo files, caches, password file, or linger setting.

## Normative requirements

### R1 — Template in repo

- A user unit template is committed at the approved path (default
  `deploy/systemd/mention-scout-watch.service`).
- Template contains **no** secrets and **no** irreversible host-only paths;
  placeholders only (or clearly documented substitute tokens).

### R2 — Installer script

- `scripts/install-user-service.sh` is executable and idempotent for re-install
  (re-writing the unit with same flags is OK).
- Resolves absolute `REPO_ROOT`, `PYTHON`, and `ENTRY` (`mention_scout.py`).
- Installs to `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/<unit-name>`.
- Runs `systemctl --user daemon-reload` after install/uninstall (skip or soft-warn
  under `--dry-run` / when `systemctl` missing).
- Supports enable/start/disable/uninstall/dry-run as specified in design table.
- Default generated command includes `--watch-new --email-new`; `--no-email`
  produces watch-only.
- Exit non-zero on hard failures (missing entry script, cannot write unit dir,
  `systemctl` failed when not dry-run). Actionable stderr messages.

### R3 — No secrets in unit or git

- Unit must not embed Gmail app passwords, tokens, or `.env` contents.
- Credential path remains app default (`~/.config/.google-password`) unless
  owner passes an extra/override mechanism that still only references a path.
- Never commit password files or private caches.

### R4 — Interactive CLI unchanged

- Omitting new installer/CLI surfaces leaves all existing argparse defaults
  identical (including watch without email unless `--email-new`).
- Stable `./mention_scout.py` entry preserved.
- No trading paths added.
- Network timeouts/retries in app remain as today; service restart policy must
  not create a sub-30s crash loop (`RestartSec` ≥ 15 recommended; **30** default).

### R5 — Documentation

README gains a section that covers at least:

1. Prerequisites: Python 3, checkout path, optional `swaks` + password file for email
2. Install / enable / start examples
3. `loginctl enable-linger` for boot without login (**manual** by default)
4. `journalctl --user -u …` logs
5. WorkingDirectory/cache implication (caches written under repo root by default)
6. Uninstall/disable
7. Pointer that MS-0007 false-positive risk makes early unattended `--email-new`
   noisier until #9 ships (worded as ops caution, not a hard installer block)

### R6 — Safety / factory policy

- Implementation and verification **must not** send real email.
- Verification must not require live trading endpoints beyond existing public
  GETs; prefer not to run a long live watch in automated verify.
- No `system` unit install path in v1.

### R7 — Optional CLI wrapper (only if owner opts in)

If approved: `./mention_scout.py --install-user-service …` may exec the shell
script with remaining args. Must not re-implement systemd logic in Python.
**Default for this PROPOSED spec: do not add the CLI flag.**

## Acceptance criteria

- [ ] Unit template committed under approved path with placeholders only.
- [ ] `scripts/install-user-service.sh` installs a user unit to
      `~/.config/systemd/user/` (or `XDG_CONFIG_HOME` equivalent).
- [ ] Default installed ExecStart runs stable entry with `--watch-new --email-new`
      (or owner-approved alternate default).
- [ ] `--no-email` (or approved name) installs watch-only unit.
- [ ] Installer supports dry-run, enable/start, disable, uninstall.
- [ ] Re-install is idempotent enough to update the unit file safely.
- [ ] No secrets in unit template, generated unit examples in docs, or git.
- [ ] README documents linger, journalctl, prereqs, WorkingDirectory/cache, uninstall.
- [ ] Interactive CLI defaults and discovery behavior unchanged when installer unused.
- [ ] Restart policy is on-failure with delay/start limits (no tight crash loop).
- [ ] Offline checks pass: template exists; installer `--dry-run` succeeds against
      repo checkout; `factory-test.sh` still passes; no real email sent.
- [ ] Independent verification PASS + explicit owner ship approval before release.

## Test / verification plan

All automated checks offline where possible. **No real SMTP.** No trading.

### Implementer / factory checks

1. **Files present**
   - template path exists and is non-empty
   - installer executable bit set (`chmod +x`)
2. **Dry-run installer**
   - `./scripts/install-user-service.sh --dry-run` exits 0
   - rendered output includes absolute WorkingDirectory and ExecStart
   - default render includes `--watch-new` and `--email-new`
   - `--dry-run --no-email` omits `--email-new`
3. **Placeholder hygiene**
   - committed template has no `HOME=/home/<owner>` hardcode required for others
   - no password material in template
4. **factory-test.sh**
   - still compiles entry + help/version + pytest; installer not required to hook
     unless cheap smoke added
5. **Optional local manual (owner or verify agent on a real user session; not CI-gating if systemd user bus unavailable)**
   - install to a temp `XDG_CONFIG_HOME` if supported, or document that full
     `systemctl --user` exercise is manual
   - `systemd-analyze --user verify` on generated unit when tool exists
   - **Do not** run `--test-email` or live `--email-new` against Gmail in factory verify
   - If a process start smoke is attempted: prefer `--no-email` and short
     controlled run, or mock; never require inbox delivery

### Explicit non-tests

- No live Gmail send
- No enable-linger in automated environments
- No system-wide unit install
- No MS-0007 classification fix verification (separate MS)

Independent verification repeats file/dry-run/hygiene checks on a clean worktree.

## Compatibility

| Surface | Expectation |
|---------|-------------|
| Interactive CLI defaults | Unchanged |
| `--watch-new` / `--email-new` semantics | Unchanged; service just invokes them |
| Cache file names / format version | Unchanged; location follows WorkingDirectory |
| Queue format | Unchanged |
| Stable entry symlink | Unchanged |
| Email credential path default | Unchanged |
| JSON / type filter / MS-0006 | Unchanged |
| Trading posture | Still discovery/notification only |
| Host portability | Template + installer; no committed machine-local abs paths |

Backward compatible for existing interactive users who never run the installer.

## Failure behavior

| Failure | Handling |
|---------|----------|
| `mention_scout.py` missing in repo root | Installer exits non-zero with clear message |
| Cannot create `~/.config/systemd/user` | Non-zero; actionable path/permission error |
| `systemctl --user` unavailable / bus down | Non-zero on real install/enable/start; dry-run still works |
| Email selected but `swaks` missing | Warn (default) or fail with `--strict`; do not embed alternate SMTP |
| Email selected but password file missing/unsafe | Warn or `--strict` fail; app would fail-fast at runtime anyway |
| Service crashes repeatedly | systemd restart delay + start limit; journal shows errors |
| Checkout moved after install | Service may fail until reinstall/path fix; documented |
| User disables linger | Unit may not start at pure boot; documented |

Watch/email runtime failures inside the app remain as today (e.g. email error
logged; watch continues when running with `--email-new`).

## Risks

| Risk | Mitigation |
|------|------------|
| Unattended `--email-new` before MS-0007 fix increases false-positive mail | Docs caution; installer `--no-email`; do not block packaging on #9 |
| User PATH under systemd lacks `swaks` or `python3` | Absolute python path; document swaks install; optional PATH note |
| Cache/workdir surprise (writes in repo) | Explicit README + installer summary line |
| Linger confusion (“enabled but didn’t start at boot”) | Detect/print linger hint; docs |
| Crash loop / API hammering | `RestartSec=30`, start limits; keep app poll default 300s |
| Scope creep into system units / containers | Hard out-of-scope |
| Thin CLI wrapper bloating scout | Default script-only |
| Installer accidentally enabling linger | Default docs-only; no auto linger |

## Owner decision table (approve or override)

| # | Topic | Recommendation | Owner pick |
|---|-------|----------------|------------|
| 1 | Install mechanism | Script-first: `scripts/install-user-service.sh` + template; **no** CLI flag in v1 | |
| 2 | Default service command | `--watch-new --email-new` in unit; interactive CLI still watch-only by default | |
| 3 | Email opt-out | `--no-email` installer flag | |
| 4 | WorkingDirectory | Absolute repo checkout root (cache CWD-relative stays predictable) | |
| 5 | Unit name | `mention-scout-watch.service` | |
| 6 | Template path | `deploy/systemd/mention-scout-watch.service` | |
| 7 | Restart policy | `Restart=on-failure`, `RestartSec=30`, start limit burst 5 / 300s | |
| 8 | Linger | Document + installer hint only; **do not** auto `enable-linger` | |
| 9 | Poll interval in unit | Omit (use app default 300s); optional `--poll-seconds` bake-in | |
| 10 | Queue flag in unit | Off by default (not in ExecStart) | |
| 11 | Multi-instance `@` templates | Defer | |
| 12 | system-wide units | Out of scope | |
| 13 | Ship before/after MS-0007 | Allow ship with email default **or** prefer default `--no-email` until #9 merges — **recommend allow ship + docs caution + easy `--no-email`** | |
| 14 | Optional CLI `--install-user-service` | Defer | |

## Open questions

Only real forks (defaults above are the proposed answers):

1. **Email default in the unit:** confirm `--email-new` on (recommended) vs watch-only default until MS-0007 lands.
2. **Linger:** confirm docs/hint only (recommended) vs installer `--enable-linger` support.
3. **WorkingDirectory:** confirm repo root (recommended) vs XDG data dir + explicit cache path work.
4. **CLI wrapper:** confirm deferred (recommended) vs thin flag in same MS.
5. **Unit/template names/paths:** confirm `mention-scout-watch.service` + `deploy/systemd/…`.

## Dependencies / sequencing

- **Does not require** product code changes inside discovery/watch beyond optional
  deferred CLI wrapper.
- **Related risk:** MS-0007 / #9 false-positive watch alerts — especially with
  unattended email. Spec does **not** hard-block MS-0008 on MS-0007; owner may
  choose watch-only default or delay enablement.
- Complementary later: MS-0004 email dry-run improves safe testing of notify path
  under service bring-up (not a blocker for packaging).

## Implementation notes (non-normative)

Suggested installer flow:

```bash
repo_root=$(git rev-parse --show-toplevel)  # or dirname layout fallback
entry="$repo_root/mention_scout.py"
python=$(command -v python3)
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
# render template → "$unit_dir/mention-scout-watch.service"
systemctl --user daemon-reload
# optional enable --now
```

Prefer `set -euo pipefail`, quote paths, and refuse to run uninstall against a
unit name that does not match the managed default unless `--unit-name` matches.

Keep diff reviewable: template + script + README (+ tiny test if cheap).

## Non-goals (restated)

- Not a trading service.
- Not system-wide daemon packaging.
- Not a fix for mention false positives.
- Not an SMTP stack rewrite.
- Not a new cache format.

## Exit criteria for this specification

- Owner approves or requests revision of this PROPOSED spec (decisions recorded).
- Only after approval may an implementation worktree implement MS-0008.
- No product packaging implementation is authorized by this proposal alone.

---

## Recommended defaults (summary for owner approval)

| Topic | Recommendation |
|-------|----------------|
| Mechanism | Template `deploy/systemd/mention-scout-watch.service` + `scripts/install-user-service.sh` |
| CLI install flag | Deferred (script-first) |
| Default ExecStart | `python3 mention_scout.py --watch-new --email-new` (absolute paths) |
| Email opt-out | `--no-email` |
| WorkingDirectory | Repo checkout root |
| Restart | on-failure / 30s / start limits |
| Linger | Docs + hint only (no auto) |
| Logs | journalctl --user |
| Secrets | None in unit; existing password file behavior |
| MS-0007 | Caution in docs; installer still ships; easy watch-only mode |

---

*End of MS-0008 proposed specification.*
