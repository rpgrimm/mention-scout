# MS-0001 — Initial read-only factory audit

Status: READY
Assigned coordinator: `mention-scout-factory`

## Objective

Inspect `kalshi_mention_scout.py`, its resolved versioned implementation, and the repository.
Produce an improvement audit and a specification for the first small,
high-value improvement. Do not modify code in this task.

## Deliverables

1. Update `.factory/architecture.md` with observed modules and data flow.
2. Write `.factory/improvements/MS-0001-candidates.md` with three to five
   candidates ranked by user value, effort, regression risk, and testability.
3. Write `.factory/specs/MS-0002-proposed.md` for the best first change,
   including scope, requirements, compatibility, failure behavior, test plan,
   acceptance criteria, and owner questions.
4. Report the proposed specification and wait for owner approval.

## Guardrails

- Read-only inspection.
- No production email.
- No trading or order actions.
- Do not print secrets or private cache contents.
- Do not change `kalshi_mention_scout.py` or its symlink target.
- Do not begin implementation until the owner approves a specification.

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
