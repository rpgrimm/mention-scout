# MS-0023 — user unit default ExecStart + invite-emails.json

Status: **APPROVED** by owner 2026-10-29 (chat: default ExecStart to `%h/code/dev/mention-scout/venv/bin/python` + `mention_scout.py --watch-new --email-new --calendar-add-new --invite-email cherylr125@gmail.com`, and make invite-email configurable under `~/.config/mention-scout/`).
Type: packaging + config
Related: MS-0008, MS-0013

## Behavior

- Installer default ExecStart:
  `%h/code/dev/mention-scout/venv/bin/python %h/code/dev/mention-scout/mention_scout.py --watch-new --email-new --calendar-add-new --invite-email cherylr125@gmail.com`
- WorkingDirectory default: `%h/code/dev/mention-scout`
- `--python`, `--repo-root`, `--working-directory` still override.
- `--no-calendar` / `--no-invite` / extra `--invite-email ADDR` for the unit.
- App reads `~/.config/mention-scout/invite-emails.json` (`{"invite_emails":[...]}` or a JSON array) when `--calendar-add-new` is on, merged with CLI `--invite-email`.
- Installer copies the example invite file if missing.
- Discovery/notification only. No trading.
