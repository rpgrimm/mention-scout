# MS-0020 — SMTP2GO credentials from ~/.config/mention-scout/

Status: **APPROVED** by owner 2026-10-27 (chat: new server uses `mail.smtp2go.com` port 2525; username and password from `~/.config/mention-scout/`; PR to test; remind/implement `--test-email`).
Type: feature
Related: MS-0004 (email dry-run still open/separate), existing `--test-email`
Branch: `openclaw/ms-0020` + PR into `main`. Do not merge until owner desktop/server-tests.

## Behavior

- Default SMTP: `mail.smtp2go.com:2525` (swaks `--tls` STARTTLS, same as previous Gmail 587).
- Credentials file: `~/.config/mention-scout/smtp` (mode `600`), sourced like the old Google file:
  - `SMTP_USERNAME` (aliases: `SMTP_USER`, `SMTP_AUTH_USER`)
  - `SMTP_PASSWORD` (alias: `GOOGLE_PASSWORD`)
- `--smtp-auth-user` overrides the file username when set.
- Missing smtp file falls back to `~/.config/.google-password`.
- `--test-email` sends one message and exits (already existed; docs/help updated).
- Discovery only. No trading. Never print the password.
