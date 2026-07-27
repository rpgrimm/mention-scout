#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
python_bin="${PYTHON_BIN:-python3}"
[[ -x .venv/bin/python ]] && python_bin=.venv/bin/python

stable_entry=mention_scout.py
resolved_entry=kalshi_mention_scout.py

[[ -e "$stable_entry" || -L "$stable_entry" ]] || {
    echo "Stable entry not found: $stable_entry" >&2
    exit 2
}
[[ -e "$resolved_entry" || -L "$resolved_entry" ]] || {
    echo "Resolved entry not found: $resolved_entry" >&2
    exit 2
}

resolved="$(readlink -f "$resolved_entry")"
echo "Compile: $resolved"
"$python_bin" -m py_compile "$resolved"

for entry in "$stable_entry" "$resolved_entry"; do
    echo "CLI smoke test: ./$entry --help"
    "$python_bin" "$entry" --help >/dev/null
    echo "CLI smoke test: ./$entry --version"
    "$python_bin" "$entry" --version >/dev/null
done

if [[ -d tests ]]; then
    "$python_bin" -c 'import pytest' >/dev/null 2>&1 || {
        echo "pytest is not installed" >&2
        exit 2
    }
    "$python_bin" -m pytest -q
else
    echo "NOTE: no tests/ directory yet."
fi
echo "Factory checks passed."
