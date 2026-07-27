#!/usr/bin/env bash
# Bootstrap GitHub labels and seed issues for mention-scout.
# Requires: gh auth (GH_TOKEN), repo rpgrimm/mention-scout must exist.
set -euo pipefail
export PATH="${HOME}/.local/bin:${PATH}"
if [[ -z "${GH_TOKEN:-}" && -f "${HOME}/.config/openclaw/github_token" ]]; then
  GH_TOKEN="$(tr -d '\r\n' < "${HOME}/.config/openclaw/github_token")"
  export GH_TOKEN
fi

REPO="${GITHUB_REPO:-rpgrimm/mention-scout}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Bootstrapping GitHub for ${REPO}"
gh repo view "${REPO}" >/dev/null

create_label() {
  local name="$1" color="$2" desc="$3"
  if gh label list --repo "${REPO}" --json name --jq '.[].name' | grep -Fxq "${name}"; then
    gh label edit "${name}" --repo "${REPO}" --color "${color}" --description "${desc}" >/dev/null || true
  else
    gh label create "${name}" --repo "${REPO}" --color "${color}" --description "${desc}" >/dev/null
  fi
  echo "label: ${name}"
}

create_label "P0" "b60205" "Immediate / unusable / data loss / security critical"
create_label "P1" "d93f0b" "High / major blocker"
create_label "P2" "fbca04" "Normal priority"
create_label "P3" "0e8a16" "Backlog"
create_label "type:bug" "d73a4a" "Bug"
create_label "type:feature" "a2eeef" "Feature"
create_label "type:chore" "fef2c0" "Chore / plumbing"
create_label "type:question" "d876e3" "Question"
create_label "type:security" "ee0701" "Security"
create_label "status:needs-triage" "ededed" "Needs triage"
create_label "status:ready" "0e8a16" "Ready for implementation"
create_label "status:blocked" "b60205" "Blocked"
create_label "status:wontfix" "ffffff" "Won't fix"

issue_exists() {
  local title="$1"
  gh issue list --repo "${REPO}" --state all --limit 100 --json title --jq '.[].title' | grep -Fxq "${title}"
}

create_issue() {
  local title="$1"; shift
  local labels_csv="$1"; shift
  local body="$1"
  if issue_exists "${title}"; then
    echo "skip existing issue: ${title}"
    return 0
  fi
  # shellcheck disable=SC2086
  local args=(issue create --repo "${REPO}" --title "${title}" --body "${body}")
  IFS=',' read -ra ls <<< "${labels_csv}"
  for l in "${ls[@]}"; do
    args+=(--label "${l}")
  done
  gh "${args[@]}"
}

create_issue "MS-0001: Initial factory audit (complete)" \
  "type:chore,P3,status:ready" \
  "$(cat <<'BODY'
## Summary
Read-only factory audit of `kalshi_mention_scout.py` and `.factory/` contracts.

## Status
**COMPLETE** locally (2026-07-25). Mirrored to GitHub for history.

## Deliverables
- `.factory/architecture.md`
- `.factory/improvements/MS-0001-candidates.md`
- `.factory/specs/MS-0002-proposed.md`
- `.factory/tasks/MS-0001.md`

## Outcome
Recommended first change: **MS-0002** stable `./mention_scout.py` entrypoint.

No product code changes in this task.
BODY
)"

create_issue "MS-0002: Stable ./mention_scout.py entrypoint" \
  "type:feature,P1,status:blocked" \
  "$(cat <<'BODY'
## Problem
Factory contracts require a user-facing `./mention_scout.py` stable command. It is missing from the repo root (only `kalshi_mention_scout.py` exists).

## Goal
Add durable `./mention_scout.py` that delegates to the current v16 implementation without changing CLI defaults, cache formats, watch/email logic, or trading boundaries.

## Spec
See `.factory/specs/MS-0002-proposed.md` (status: PROPOSED — awaiting owner approval).

## Preferred approach
Relative symlink: `mention_scout.py` → `kalshi_mention_scout.py`, plus factory-test smoke on both entry paths.

## Out of scope
Discovery logic, cache format, email sending, versioned rename stretch (unless owner expands).

## Acceptance (summary)
- [ ] `./mention_scout.py --help` / `--version` match implementation
- [ ] `scripts/factory-test.sh` covers both entries
- [ ] No behavior/default/cache changes
- [ ] Independent verification PASS + explicit owner ship approval

## Blockers
Owner approval of MS-0002 proposed spec (mechanism, stretch versioning, project.yaml fields).
BODY
)"

create_issue "MS-0003: Minimal deterministic tests/ suite" \
  "type:chore,P2,status:needs-triage" \
  "$(cat <<'BODY'
## Goal
Seed a minimal `tests/` suite for pure helpers (date/status/cache usability/mention classification/URL builders) so `factory-test.sh` runs pytest when present.

## Why
Standards require regression tests for date parsing, status filtering, cache behavior, duplicate suppression, watch loops, and email delivery changes. No suite exists yet.

## Constraints
- Offline fixtures only; no real network/SMTP/secrets
- Prefer testing existing functions without large refactors
- Follow-up after MS-0002 unless owner reprioritizes

## Source
`.factory/improvements/MS-0001-candidates.md` candidate #2
BODY
)"

create_issue "MS-0004: Email dry-run / injectable send seam" \
  "type:feature,P2,status:needs-triage" \
  "$(cat <<'BODY'
## Goal
Add a first-class email dry-run or injectable send path so watch/email wiring can be verified without real SMTP.

## Constraints
- Default behavior unchanged (real send only when explicitly configured as today)
- Never log/print password material
- No real email during automated implementation/verification
- Factory policy: mocks / dry-run only in automated testing

## Source
`.factory/improvements/MS-0001-candidates.md` candidate #3
BODY
)"

create_issue "MS-0005: Versioned implementation filename layout" \
  "type:chore,P3,status:needs-triage" \
  "$(cat <<'BODY'
## Goal
Align on-disk layout with factory release model: versioned implementation file (e.g. `kalshi_mention_scout_v16.py`) with stable names as symlinks, updated only after independent verification PASS and explicit owner approval.

## Notes
May be folded into MS-0002 if owner opts into the stretch; otherwise a later MS.

## Source
`.factory/improvements/MS-0001-candidates.md` candidate #5
BODY
)"

echo "Done. Open issues:"
gh issue list --repo "${REPO}" --state open
