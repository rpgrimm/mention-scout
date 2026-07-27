# GitHub — mention-scout

## Repository

- **Remote:** `https://github.com/rpgrimm/mention-scout`
- **Visibility:** private
- **Default branch:** `main`
- **Owner:** `rpgrimm`
- **Local path:** `/home/candr/src/mention_scout`

Factory and owner work treat **GitHub Issues** as the source of truth for open
work (bugs, features, chores, proposed MS tasks). Local `.factory/tasks`,
`.factory/specs`, and `.factory/improvements` remain working artifacts and must
link to issue numbers once filed.

## Auth (host only — never commit)

```bash
export PATH="$HOME/.local/bin:$PATH"
export GH_TOKEN="$(tr -d '\r\n' < ~/.config/openclaw/github_token)"
gh auth status
```

Never print, commit, or paste the token. Do not embed it in git remotes.

## Labels

Priority: `P0` `P1` `P2` `P3`  
Type: `type:bug` `type:feature` `type:chore` `type:question` `type:security`  
Status: `status:needs-triage` `status:ready` `status:blocked` `status:wontfix`

## Issue conventions

- One shippable slice per issue when possible.
- Reference factory IDs in titles/bodies: `MS-0002: …`
- Implementation PRs use `Fixes #N` / `Refs #N`.
- No secrets, credential paths with values, private cache contents, or email bodies in issues.

## Initial backlog seed (from MS-0001)

| Local ID | GitHub | Intent | Labels |
|----------|--------|--------|--------|
| MS-0001 | #1 (closed) | Initial audit (complete) | `type:chore` `P3` |
| MS-0002 | #2 | Stable `./mention_scout.py` entrypoint | `type:feature` `P1` `status:blocked` |
| MS-0003 | #3 | Minimal deterministic `tests/` suite | `type:chore` `P2` `status:needs-triage` |
| MS-0004 | #4 | Email dry-run / injectable send seam | `type:feature` `P2` `status:needs-triage` |
| MS-0005 | #5 | Versioned implementation filename layout | `type:chore` `P3` `status:needs-triage` |
