"""Offline tests for MS-0020 SMTP2GO credentials (~/.config/mention-scout/smtp)."""

from __future__ import annotations

import os
import stat
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402


def _write_creds(path: Path, body: str, mode: int = 0o600) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def test_load_smtp_credentials_username_and_password(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='smtp2go-user'\nSMTP_PASSWORD='smtp2go-secret'\n",
    )
    creds = scout.load_smtp_credentials(path)
    assert creds.username == "smtp2go-user"
    assert creds.password == "smtp2go-secret"


def test_load_smtp_credentials_accepts_google_password_alias(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / ".google-password",
        "GOOGLE_PASSWORD='gmail-app-pass'\n",
    )
    creds = scout.load_smtp_credentials(path)
    assert creds.username == ""
    assert creds.password == "gmail-app-pass"


def test_load_smtp_credentials_rejects_broad_permissions(tmp_path: Path) -> None:
    path = _write_creds(tmp_path / "smtp", "SMTP_PASSWORD='x'\n", mode=0o644)
    with pytest.raises(RuntimeError, match="permissions are too broad"):
        scout.load_smtp_credentials(path)


def test_load_smtp_credentials_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing"):
        scout.load_smtp_credentials(tmp_path / "nope")


def test_verify_fills_username_from_file(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='from-file'\nSMTP_PASSWORD='pw'\n",
    )
    args = Namespace(
        smtp_credentials=path,
        google_password_file=tmp_path / "missing-google",
        smtp_auth_user="",
    )
    password = scout.verify_email_configuration(args)
    assert password == "pw"
    assert args.smtp_auth_user == "from-file"


def test_verify_cli_username_overrides_file(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='from-file'\nSMTP_PASSWORD='pw'\n",
    )
    args = Namespace(
        smtp_credentials=path,
        google_password_file=tmp_path / "missing-google",
        smtp_auth_user="cli-user",
    )
    scout.verify_email_configuration(args)
    assert args.smtp_auth_user == "cli-user"


def test_resolve_prefers_smtp_file_over_google(tmp_path: Path) -> None:
    smtp = _write_creds(tmp_path / "smtp", "SMTP_PASSWORD='a'\nSMTP_USERNAME='u'\n")
    google = _write_creds(tmp_path / "google", "GOOGLE_PASSWORD='b'\n")
    args = SimpleNamespace(smtp_credentials=smtp, google_password_file=google)
    assert scout.resolve_smtp_credentials_path(args) == smtp


def test_resolve_falls_back_to_google_password(tmp_path: Path) -> None:
    google = _write_creds(tmp_path / "google", "GOOGLE_PASSWORD='b'\n")
    args = SimpleNamespace(
        smtp_credentials=tmp_path / "missing-smtp",
        google_password_file=google,
    )
    assert scout.resolve_smtp_credentials_path(args) == google


def test_parser_defaults_smtp2go() -> None:
    parser = scout.build_parser()
    args = parser.parse_args(["--test-email"])
    assert args.smtp_server == "mail.smtp2go.com:2525"
    assert args.smtp_credentials == scout.DEFAULT_SMTP_CREDENTIALS_FILE
    assert args.smtp_auth_user == ""
    assert args.test_email is True


def test_test_email_uses_loaded_username(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='smtp2go-user'\nSMTP_PASSWORD='smtp2go-secret'\n",
    )
    sent: dict[str, str] = {}

    def fake_swaks(**kwargs: str) -> None:
        sent.update(kwargs)

    monkeypatch.setattr(scout, "run_swaks_email", fake_swaks)
    args = Namespace(
        smtp_credentials=path,
        google_password_file=tmp_path / "missing-google",
        smtp_auth_user="",
        smtp_server="mail.smtp2go.com:2525",
        email_to="ryan.grimm@gmail.com",
        email_from="ryan.grimm@gmail.com",
        timezone="America/New_York",
    )
    assert scout.send_test_email(args) == 0
    assert sent["auth_user"] == "smtp2go-user"
    assert sent["password"] == "smtp2go-secret"
    assert sent["smtp_server"] == "mail.smtp2go.com:2525"
    assert sent["subject"] == "[Kalshi] mention scout SMTP test"


def test_password_file_mode_is_600(tmp_path: Path) -> None:
    path = _write_creds(tmp_path / "smtp", "SMTP_USERNAME='u'\nSMTP_PASSWORD='p'\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.environ.get("SMTP_PASSWORD") != "p"
