# MS-0009 — Move StartLimit* keys to [Unit] in user service template

Status: **APPROVED**  
Approved: 2026-08-01 by owner (bug report with journal warning; fix is systemd-mandated placement)  
GitHub issue: (MS-0009 / filed with this change)  
Type: bug (packaging)  
Priority: P3  

## Problem

`StartLimitIntervalSec` / `StartLimitBurst` were placed under `[Service]`. systemd only accepts them under `[Unit]`, so it logs:

`Unknown key 'StartLimitIntervalSec' in section [Service], ignoring.`

The service still starts; rate-limit on restart loops is not applied.

## Fix
\nIn `deploy/systemd/mention-scout-watch.service`, move:

```ini
StartLimitIntervalSec=300
StartLimitBurst=5
```

from `[Service]` into `[Unit]`. Leave `Restart=` / `RestartSec=` in `[Service]`.

## Scope

- Template + any tests/docs that assert section placement
- Reinstall remains the owner path to refresh `~/.config/systemd/user/`

## Out of scope

- Product/classification code
- Installer feature work
- system-wide units

## Acceptance

- Template validates: StartLimit* in `[Unit]` only
- `./scripts/factory-test.sh` passes
- No secrets; no trading; no real email
