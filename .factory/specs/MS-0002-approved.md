# MS-0002 — Stable `mention_scout.py` command surface

Status: **APPROVED**  
GitHub issue: https://github.com/rpgrimm/mention-scout/issues/2  
Approved: 2026-07-27 by owner (chat) with defaults below.  
Type: packaging / entrypoint alignment (no discovery-logic change)  
Related: MS-0001 audit, `.factory/improvements/MS-0001-candidates.md`  
Repository: `/home/candr/src/mention_scout`

---

## Problem

Factory contracts (`AGENTS.md`, `.factory/standards.md`, inbox/release language) require preserving a user-facing **`./mention_scout.py`** stable command, with versioned implementation files updated only after independent verification and explicit owner approval.

Observed on disk after MS-0001:

- Implementation exists only as **`kalshi_mention_scout.py`** (docstring/identity: v16, `VERSION = "16.0.0"`).
- **`mention_scout.py` is missing** (no file, no symlink).
- No separate versioned implementation filename (e.g. `kalshi_mention_scout_v16.py`).
- `.factory/project.yaml` points `entry_script` / `resolved_entry_script` at `kalshi_mention_scout.py`.
- `scripts/factory-test.sh` smokes only `kalshi_mention_scout.py`.

Users and agents following the written guardrails cannot run `./mention_scout.py`. The documented stable command surface does not match the repository.

## Current behavior

- Running `python3 kalshi_mention_scout.py …` or `./kalshi_mention_scout.py …` works (executable module).
- Running `./mention_scout.py` fails with “No such file or directory”.
- No product behavior depends on the missing name today; the gap is command-surface / contract consistency.

## Goal

Provide a durable, documented **`./mention_scout.py`** entry that invokes the same v16 implementation as `kalshi_mention_scout.py`, without changing CLI defaults, cache formats, API behavior, watch/email logic, or trading boundaries.

## Scope

### In scope

1. Add a **stable `mention_scout.py`** at the repository root that resolves to the current implementation.
   - **Preferred mechanism:** relative symlink  
     `mention_scout.py` → `kalshi_mention_scout.py`  
   - Acceptable alternative if symlink is undesirable on a target platform: a tiny executable wrapper that `exec`s the implementation with the same argv (still no logic duplication).
2. Ensure both names are executable from a normal checkout (`chmod` / symlink mode as appropriate).
3. Update factory wiring so the stable name is first-class:
   - `.factory/project.yaml`: document stable vs resolved entry (e.g. stable `mention_scout.py`, resolved still `kalshi_mention_scout.py` **or** explicit fields the coordinator already understands — keep one clear source of truth).
   - `scripts/factory-test.sh`: smoke **both** `mention_scout.py` and `kalshi_mention_scout.py` (`--help` at minimum; `--version` if cheap).
   - `AGENTS.md` / release notes only if needed for accuracy (stable command now exists).
4. Add a short note in architecture or a one-line comment in release-policy if helpful: stable name vs implementation filename.
5. Offline verification only (compile + help/version); no network, no email, no cache writes required for acceptance.

### Out of scope

- Any change to Python discovery, date/status filtering, cache format/version, watch loop semantics, email sending, or argparse defaults/flags.
- Renaming the implementation to `kalshi_mention_scout_v16.py` / multi-version layout (**optional stretch — owner must explicitly opt in**; default is **not** included).
- Creating `tests/` beyond smoke checks in `factory-test.sh` (follow-up candidate).
- Email dry-run, dependency injection, packaging tarball contents beyond what `git archive` naturally includes once the new path is committed.
- Trading features.
- Changing default email addresses or credential paths.

### Optional stretch (only if owner expands this spec before implementation)

- Add `kalshi_mention_scout_v16.py` as the real file and point **both** `mention_scout.py` and `kalshi_mention_scout.py` at it via symlinks, preserving `VERSION`/docstring consistency.
- If stretch is rejected, leave single implementation file as today and only add the stable symlink/wrapper.

## Requirements

### R1 — Stable command exists

After checkout on a clean worktree:

```bash
./mention_scout.py --help
./mention_scout.py --version
```

succeed with the same essential help text / version string as:

```bash
./kalshi_mention_scout.py --help
./kalshi_mention_scout.py --version
```

Version string must still report **16.0.0** (or whatever `VERSION` is in the implementation at ship time — no version bump required solely for this MS).

### R2 — Single implementation source of truth

- No forked copy of the ~2k-line script.
- Behavior of existing `kalshi_mention_scout.py` invocations remains identical.
- Symlink target (or wrapper exec target) is relative and valid inside git worktrees and release tarballs produced by `scripts/factory-package.sh`.

### R3 — Factory scripts

- `scripts/factory-test.sh` fails if either stable or implementation entry is missing/broken.
- `scripts/factory-package.sh` includes the new path in the archive (via normal git tracking).
- Worktree create/setup continues to work; no secret material introduced.

### R4 — Guardrails preserved

- No trading code paths added.
- No real email sent during implementation or verification.
- CLI defaults and cache file names/format versions unchanged.
- Do not print or commit secrets, `.env`, or private caches.

### R5 — Documentation consistency

- Written references to `./mention_scout.py` as the user-facing command remain valid.
- If `project.yaml` distinguishes stable vs resolved entry, both fields are accurate after the change.

## Compatibility

| Surface | Expectation |
|---------|-------------|
| CLI flags/defaults | Unchanged |
| Cache files / `CACHE_FORMAT_VERSION` | Unchanged |
| Queue format | Unchanged |
| `kalshi_mention_scout.py` path | Remains valid entry |
| JSON output schema | Unchanged |
| Watch/email semantics | Unchanged |
| Git history of implementation content | Prefer symlink/wrapper commit; avoid needless full-file rewrite |

Backward compatible: old docs/scripts using `kalshi_mention_scout.py` keep working; new/stable name becomes available.

## Failure behavior

| Failure | Expected handling |
|---------|-------------------|
| Symlink/wrapper missing after claimed implementation | `factory-test.sh` fails; do not ship |
| Broken relative link in worktree or tarball | Test fails; fix link before merge |
| Wrapper cannot find implementation | Non-zero exit with clear message to stderr (wrapper path only) |
| Accidental edit to discovery logic in same PR | Out of scope — reject or split; this MS must stay entrypoint-only |

No new runtime failure modes for normal one-shot/watch use beyond those already in the implementation.

## Test plan

All offline; no Kalshi network; no SMTP; no credential file reads required.

1. **Path checks**
   - `mention_scout.py` exists at repo root.
   - If symlink: `readlink` / `readlink -f` resolves to the implementation file under the repo.
   - If wrapper: file is executable and does not embed secrets.
2. **Smoke parity**
   - `./mention_scout.py --help` and `./kalshi_mention_scout.py --help` both exit 0.
   - `./mention_scout.py --version` and `./kalshi_mention_scout.py --version` both exit 0 and report the same version.
3. **Factory test**
   - `./scripts/factory-test.sh` passes (updated to cover both entries).
4. **Package inclusion (verification or implementer check)**
   - After commit on a clean tree, `./scripts/factory-package.sh` tarball lists `mention_scout.py` and the implementation file.
5. **Negative**
   - Do not run `--test-email`, `--watch-new`, or live API scans as part of this MS verification.

Independent verification agent should repeat 1–4 on a clean worktree.

## Acceptance criteria

- [ ] `mention_scout.py` exists at repository root and is the documented stable user command.
- [ ] It delegates to the same code as `kalshi_mention_scout.py` (symlink or exec wrapper; no duplicated logic).
- [ ] `./mention_scout.py --help` and `--version` succeed and match implementation version identity.
- [ ] `./kalshi_mention_scout.py` still works unchanged for existing users/scripts.
- [ ] `scripts/factory-test.sh` smokes both entry paths and passes.
- [ ] `.factory/project.yaml` (and any touched factory docs) accurately describe stable vs resolved entry.
- [ ] No changes to CLI defaults, cache format, API/watch/email behavior, or trading posture.
- [ ] No secrets committed; no real email sent during implementation/verification.
- [ ] Owner explicitly approves release after independent verification PASS (per release-policy).

## Implementation notes (non-normative)

Suggested minimal approach:

```bash
ln -s kalshi_mention_scout.py mention_scout.py
```

Ensure git stores the symlink as a symlink. Update `factory-test.sh` roughly as:

- require `-e`/`-L` for both `mention_scout.py` and `kalshi_mention_scout.py`
- `py_compile` on the resolved implementation once
- `--help` (and optionally `--version`) on both entry names

Keep the diff small and reviewable.

## Owner questions

1. **Mechanism preference:** Is a **relative symlink** `mention_scout.py` → `kalshi_mention_scout.py` acceptable, or do you require a small wrapper script?
2. **Stretch versioning in this MS?** Should we also introduce `kalshi_mention_scout_v16.py` and point both stable names at it now, or defer versioned filenames to a later MS?
3. **`project.yaml` fields:** Prefer stable entry = `mention_scout.py` with resolved = `kalshi_mention_scout.py`, or keep `entry_script` as today and only add documentation? (Coordinator/tooling may depend on exact keys.)
4. **factory-test scope:** Is `--help` on both paths sufficient, or must `--version` parity be asserted too?
5. **Default notification addresses** are hard-coded in argparse today; out of scope here — confirm you want **no** change to those defaults in MS-0002.

## Risks

| Risk | Mitigation |
|------|------------|
| Tarball or Windows consumers mishandle symlinks | Prefer relative symlink (git-friendly); document; wrapper fallback if owner requires |
| Factory tooling only looks at `kalshi_mention_scout.py` | Update `factory-test.sh` + `project.yaml` in the same change |
| Scope creep into version rename | Default stretch off; require explicit owner opt-in |

## Exit criteria for this specification

- Owner approves or requests revision of this PROPOSED spec.
- Only after approval may an implementation worktree implement MS-0002.
- No implementation work is authorized by MS-0001 alone.

---

*End of MS-0002 proposed specification.*


## Owner decisions (approved)

1. **Mechanism:** relative symlink `mention_scout.py` → `kalshi_mention_scout.py`
2. **Stretch versioning:** deferred (MS-0005 / issue #5)
3. **project.yaml:** stable entry = `mention_scout.py`, resolved = `kalshi_mention_scout.py`
4. **factory-test:** assert `--help` and `--version` parity on both paths
5. **Email/defaults/cache:** no changes

