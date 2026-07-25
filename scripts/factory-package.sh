#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
[[ -z "$(git status --porcelain)" ]] || { echo "Refusing to package a dirty worktree." >&2; exit 2; }
project=mention-scout
version="${VERSION:-$(git describe --tags --always 2>/dev/null)}"
name="${project}-${version}"
mkdir -p dist
output="dist/${name}.tar.gz"
git archive --format=tar.gz --prefix="${name}/" --output="$output" HEAD
sha256sum "$output" > "$output.sha256"
printf '%s
%s
' "$output" "$output.sha256"
