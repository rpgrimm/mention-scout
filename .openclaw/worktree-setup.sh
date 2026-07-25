#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
python_bin="${PYTHON_BIN:-python3}"
[[ -d .venv ]] || "$python_bin" -m venv .venv
if [[ "${FACTORY_INSTALL_DEPS:-1}" == "1" ]]; then
    export PIP_DISABLE_PIP_VERSION_CHECK=1
    if [[ -f requirements-dev.txt ]]; then
        .venv/bin/python -m pip install -r requirements-dev.txt
    elif [[ -f requirements.txt ]]; then
        .venv/bin/python -m pip install -r requirements.txt
    elif [[ -f pyproject.toml ]]; then
        .venv/bin/python -m pip install -e '.[dev]' ||         .venv/bin/python -m pip install -e . ||         echo "NOTE: pyproject.toml is not installable; continuing."
    fi
fi
echo "Worktree ready: $root"
