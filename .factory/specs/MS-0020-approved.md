# MS-0020 — SMTP2GO credentials from ~/.config/mention-scout/

Status: **APPROVED** by owner 2026-10-27 (chat: new server uses `mail.smtp2go.com` port 2525; username and password from `~/.config/mention-scout/`; PR to test; remind/implement `--test-email`).
Type: feature
Related: MS-0004 (email dry-run still open/separate), existing `--test-email`
Branch: `openclaw/ms-0020` + PR into `main`. Do not merge until owner desktop/server-tests.

## Behavior

- Provider file: `~/.config/mention-scout/email.json` with `{"provider": "google"|"smtp2go"}`.
- **Missing file defaults to `google`** so RIP / existing Gmail hosts keep working (`smtp.gmail.com:587` + `~/.config/.google-password`).
- `smtp2go`: `mail.smtp2go.com:2525` + `~/.config/mention-scout/smtp` (`SMTP_USERNAME` / `SMTP_PASSWORD`, mode `600`).
- `--email-provider` overrides the JSON. `--smtp-server` / `--smtp-auth-user` still override host/user.
- `--test-email` sends one message and exits.
- Discovery only. No trading. Never print the password.
