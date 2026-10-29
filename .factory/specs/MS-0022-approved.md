# MS-0022 — SMTP2GO From `vern@ryangrimm.net`

Status: **APPROVED** by owner 2026-10-27 (chat: can you have it be from vern@ryangrimm.net?).
Type: tweak
Related: MS-0020

## Behavior

- Default SMTP2GO From is `vern@ryangrimm.net` (still `@ryangrimm.net`, verified domain).
- `email.json` `"from"` and `--email-from` still override.
- `--email-to` stays `ryan.grimm@gmail.com`.
- Missing `email.json` still defaults to Google / `ryan.grimm@gmail.com`.
