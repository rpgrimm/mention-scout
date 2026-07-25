#!/usr/bin/env bash
set -euo pipefail
project=mention-scout
default_branch=main
root="$(git rev-parse --show-toplevel)"
state_dir="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
worktree_root="${FACTORY_WORKTREE_ROOT:-$state_dir/factory-worktrees/$project}"
normalize() { printf '%s' "$1" | tr '[:upper:]_' '[:lower:]-' | sed -E 's/[^a-z0-9-]+/-/g; s/-+/-/g; s/^-//; s/-$//'; }
usage() { echo "Usage: $0 create|path|list|remove <task-id> [base-ref]" >&2; }
case "${1:-}" in
  create)
    [[ $# -ge 2 ]] || { usage; exit 2; }
    name="$(normalize "$2")"; base="${3:-$default_branch}"; path="$worktree_root/$name"; branch="openclaw/$name"
    [[ -n "$name" ]] || { echo "Invalid task id" >&2; exit 2; }
    mkdir -p "$worktree_root"
    [[ ! -e "$path" ]] || { echo "Worktree exists: $path" >&2; exit 2; }
    if git show-ref --verify --quiet "refs/heads/$branch"; then git worktree add "$path" "$branch"; else git worktree add -b "$branch" "$path" "$base"; fi
    if [[ -x "$path/.openclaw/worktree-setup.sh" ]]; then (cd "$path"; OPENCLAW_SOURCE_TREE_PATH="$root" OPENCLAW_WORKTREE_PATH="$path" ./.openclaw/worktree-setup.sh); fi
    printf '%s
' "$path"
    ;;
  path) [[ $# -eq 2 ]] || { usage; exit 2; }; printf '%s
' "$worktree_root/$(normalize "$2")" ;;
  list) git -C "$root" worktree list ;;
  remove) [[ $# -eq 2 ]] || { usage; exit 2; }; git -C "$root" worktree remove "$worktree_root/$(normalize "$2")" ;;
  *) usage; exit 2 ;;
esac
