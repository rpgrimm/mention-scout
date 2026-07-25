#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
python_bin="${PYTHON_BIN:-python3}"
[[ -x .venv/bin/python ]] && python_bin=.venv/bin/python
entry=kalshi_mention_scout.py
[[ -e "$entry" || -L "$entry" ]] || { echo "Entry not found: $entry" >&2; exit 2; }
resolved="$(readlink -f "$entry")"
echo "Compile: $resolved"
"$python_bin" -m py_compile "$resolved"
echo "CLI smoke test: ./$entry --help"
"$python_bin" "$entry" --help >/dev/null
if [[ -d tests ]]; then
    "$python_bin" -c 'import pytest' >/dev/null 2>&1 || { echo "pytest is not installed" >&2; exit 2; }
    "$python_bin" -m pytest -q
else
    echo "NOTE: no tests/ directory yet."
fi
echo "Factory checks passed."
