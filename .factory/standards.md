# Engineering Standards

Small approved changes, backward-compatible CLI behavior, deterministic tests, actionable errors, independent verification, and human release approval.

## mention_scout.py guardrails

- This is discovery and notification software. It may read market data and send
  approved notifications, but it must never place, modify, or cancel trades.
- Preserve the user-facing `./mention_scout.py` command.
- Preserve versioned implementation filenames. Update the stable symlink only
  after independent verification PASS and explicit owner approval.
- Preserve existing CLI defaults and cache compatibility unless an approved
  specification deliberately changes them.
- Never send a real email during implementation or verification. Use mocks, a
  fake SMTP endpoint, captured output, dependency injection, or dry-run mode.
- Never commit API keys, email credentials, OAuth tokens, cookies, `.env` files,
  private caches, email contents, or account secrets.
- Network calls need timeouts and actionable errors.
- Date parsing, status filtering, cache behavior, duplicate suppression, watch
  loops, and email delivery changes require regression tests.
