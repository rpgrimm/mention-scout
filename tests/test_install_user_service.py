"""Offline tests for MS-0008 systemd user-unit installer (dry-run only)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install-user-service.sh"
TEMPLATE = REPO_ROOT / "deploy" / "systemd" / "mention-scout-watch.service"
STABLE_ENTRY = REPO_ROOT / "mention_scout.py"


def _run_installer(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(INSTALLER), *args],
        cwd=str(REPO_ROOT),
        env=full_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_template_exists_with_placeholders_only() -> None:
    assert TEMPLATE.is_file()
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "@REPO_ROOT@" in text
    assert "@PYTHON@" in text
    assert "@ENTRY@" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=30" in text
    assert "StandardOutput=journal" in text
    assert "StandardError=journal" in text
    assert "WantedBy=default.target" in text
    assert "--watch-new" in text
    assert "--email-new" in text
    # No host-only home paths or secrets in committed template
    assert "/home/" not in text
    assert "GOOGLE_PASSWORD" not in text
    assert ".google-password" not in text or "Do not embed secrets" in text


def test_installer_is_executable() -> None:
    assert INSTALLER.is_file()
    mode = INSTALLER.stat().st_mode
    assert mode & stat.S_IXUSR, "install-user-service.sh must be executable"


def test_dry_run_default_includes_email_and_absolute_paths() -> None:
    proc = _run_installer("--dry-run")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout
    assert "----- rendered unit (dry-run) -----" in out
    assert f"WorkingDirectory={REPO_ROOT}" in out
    assert "--watch-new" in out
    assert "--email-new" in out
    # ExecStart should use absolute python + entry
    assert "ExecStart=" in out
    exec_lines = [ln for ln in out.splitlines() if ln.startswith("ExecStart=")]
    assert exec_lines, out
    exec_line = exec_lines[0]
    assert exec_line.startswith("ExecStart=/"), exec_line
    assert str(STABLE_ENTRY.resolve()) in exec_line or "mention_scout.py" in exec_line
    assert "@REPO_ROOT@" not in out
    assert "@PYTHON@" not in out
    assert "@ENTRY@" not in out
    # dry-run must not claim a real write completed without dry-run marker
    assert f"would write" in out
    assert "daemon-reload" in out


def test_dry_run_no_email_omits_email_flag() -> None:
    proc = _run_installer("--dry-run", "--no-email")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout
    assert "--watch-new" in out
    # ExecStart line must not include --email-new
    exec_lines = [ln for ln in out.splitlines() if ln.startswith("ExecStart=")]
    assert exec_lines
    assert "--email-new" not in exec_lines[0]
    assert "Email in unit:      off" in out


def test_dry_run_poll_seconds_baked_in() -> None:
    proc = _run_installer("--dry-run", "--no-email", "--poll-seconds", "120")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    exec_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("ExecStart=")]
    assert exec_lines
    assert "--poll-seconds" in exec_lines[0]
    assert "120" in exec_lines[0]


def test_dry_run_does_not_create_unit_file(tmp_path: Path) -> None:
    xdg = tmp_path / "xdg-config"
    unit_path = xdg / "systemd" / "user" / "mention-scout-watch.service"
    proc = _run_installer("--dry-run", env={"XDG_CONFIG_HOME": str(xdg)})
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert not unit_path.exists()


def test_install_to_temp_xdg_without_systemctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write unit under temp XDG; skip systemctl by putting a stub that succeeds."""
    xdg = tmp_path / "cfg"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "systemctl"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "# record args for assertions\n"
        "echo \"$*\" >>\"${STUB_LOG}\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    log = tmp_path / "systemctl.log"
    env = {
        "XDG_CONFIG_HOME": str(xdg),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "STUB_LOG": str(log),
    }
    proc = _run_installer("--no-email", env=env)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    unit_path = xdg / "systemd" / "user" / "mention-scout-watch.service"
    assert unit_path.is_file()
    text = unit_path.read_text(encoding="utf-8")
    assert f"WorkingDirectory={REPO_ROOT}" in text
    assert "--watch-new" in text
    assert "--email-new" not in text.split("ExecStart=", 1)[1].splitlines()[0]
    assert "Restart=on-failure" in text
    assert "RestartSec=30" in text
    assert log.is_file()
    assert "daemon-reload" in log.read_text(encoding="utf-8")


def test_uninstall_removes_unit(tmp_path: Path) -> None:
    xdg = tmp_path / "cfg"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "systemctl"
    stub.write_text(
        "#!/usr/bin/env bash\necho \"$*\" >>\"${STUB_LOG}\"\nexit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    log = tmp_path / "systemctl.log"
    env = {
        "XDG_CONFIG_HOME": str(xdg),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "STUB_LOG": str(log),
    }
    install = _run_installer("--no-email", env=env)
    assert install.returncode == 0, install.stderr or install.stdout
    unit_path = xdg / "systemd" / "user" / "mention-scout-watch.service"
    assert unit_path.is_file()
    uninstall = _run_installer("--uninstall", env=env)
    assert uninstall.returncode == 0, uninstall.stderr or uninstall.stdout
    assert not unit_path.exists()


def test_help_exits_zero() -> None:
    proc = _run_installer("--help")
    assert proc.returncode == 0
    assert "install-user-service" in proc.stdout or "systemd" in proc.stdout


def test_missing_entry_fails(tmp_path: Path) -> None:
    fake_root = tmp_path / "empty-root"
    fake_root.mkdir()
    # Minimal template path so failure is about entry, not template — still missing entry
    proc = _run_installer("--dry-run", "--repo-root", str(fake_root))
    assert proc.returncode != 0
    assert "Stable entry not found" in (proc.stderr + proc.stdout)
