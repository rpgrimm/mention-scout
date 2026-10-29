"""Offline tests for MS-0020 email provider + SMTP2GO credentials."""

from __future__ import annotations

import json
import os
import stat
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402


def _write_creds(path: Path, body: str, mode: int = 0o600) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def _write_provider(path: Path, provider: str) -> Path:
    path.write_text(json.dumps({"provider": provider}) + "\n", encoding="utf-8")
    return path


def _args(tmp_path: Path, **kwargs: object) -> Namespace:
    defaults = dict(
        email_config=tmp_path / "missing-email.json",
        email_provider="",
        smtp_credentials=tmp_path / "smtp",
        google_password_file=tmp_path / "missing-google",
        smtp_auth_user="",
        smtp_server="",
        email_to="ryan.grimm@gmail.com",
        email_from="",
        timezone="America/New_York",
    )
    defaults.update(kwargs)
    return Namespace(**defaults)


def test_load_smtp_credentials_username_and_password(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='smtp2go-user'\nSMTP_PASSWORD='smtp2go-secret'\n",
    )
    creds = scout.load_smtp_credentials(path, provider="smtp2go")
    assert creds.username == "smtp2go-user"
    assert creds.password == "smtp2go-secret"


def test_load_smtp_credentials_accepts_google_password_alias(tmp_path: Path) -> None:
    path = _write_creds(tmp_path / ".google-password", "GOOGLE_PASSWORD='gmail-app-pass'\n")
    creds = scout.load_smtp_credentials(path, provider="google")
    assert creds.username == ""
    assert creds.password == "gmail-app-pass"


def test_google_missing_file_keeps_old_error(tmp_path: Path) -> None:
    missing = tmp_path / ".google-password"
    with pytest.raises(RuntimeError, match="Google password file is missing"):
        scout.load_smtp_credentials(missing, provider="google")


def test_smtp2go_missing_file_mentions_smtp_credentials(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="SMTP credentials file is missing"):
        scout.load_smtp_credentials(tmp_path / "smtp", provider="smtp2go")


def test_load_smtp_credentials_rejects_broad_permissions(tmp_path: Path) -> None:
    path = _write_creds(tmp_path / "smtp", "SMTP_PASSWORD='x'\n", mode=0o644)
    with pytest.raises(RuntimeError, match="permissions are too broad"):
        scout.load_smtp_credentials(path)


def test_missing_email_config_defaults_to_google(tmp_path: Path) -> None:
    assert scout.load_email_provider_config(tmp_path / "nope.json") == "google"


def test_email_config_selects_smtp2go(tmp_path: Path) -> None:
    path = _write_provider(tmp_path / "email.json", "smtp2go")
    assert scout.load_email_provider_config(path) == "smtp2go"


def test_apply_no_config_uses_gmail_server(tmp_path: Path) -> None:
    args = _args(tmp_path)
    profile = scout.apply_email_provider(args)
    assert profile.id == "google"
    assert args.smtp_server == "smtp.gmail.com:587"
    assert args.email_from == "ryan.grimm@gmail.com"


def test_apply_smtp2go_config_uses_smtp2go_server_and_ryangrimm_from(tmp_path: Path) -> None:
    config = _write_provider(tmp_path / "email.json", "smtp2go")
    args = _args(tmp_path, email_config=config)
    profile = scout.apply_email_provider(args)
    assert profile.id == "smtp2go"
    assert args.smtp_server == "mail.smtp2go.com:2525"
    assert args.email_from == "vern@ryangrimm.net"


def test_email_json_from_overrides_smtp2go_default(tmp_path: Path) -> None:
    path = tmp_path / "email.json"
    path.write_text(
        json.dumps({"provider": "smtp2go", "from": "alerts@ryangrimm.net"}) + "\n",
        encoding="utf-8",
    )
    args = _args(tmp_path, email_config=path)
    scout.apply_email_provider(args)
    assert args.email_from == "alerts@ryangrimm.net"


def test_cli_email_provider_overrides_json(tmp_path: Path) -> None:
    config = _write_provider(tmp_path / "email.json", "google")
    args = _args(tmp_path, email_config=config, email_provider="smtp2go")
    assert scout.apply_email_provider(args).id == "smtp2go"


def test_verify_smtp2go_fills_username_from_file(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='from-file'\nSMTP_PASSWORD='pw'\n",
    )
    args = _args(
        tmp_path,
        email_provider="smtp2go",
        smtp_credentials=path,
    )
    password = scout.verify_email_configuration(args)
    assert password == "pw"
    assert args.smtp_auth_user == "from-file"
    assert args.smtp_server == "mail.smtp2go.com:2525"


def test_verify_google_uses_default_auth_user(tmp_path: Path) -> None:
    google = _write_creds(tmp_path / "google", "GOOGLE_PASSWORD='gmail-app-pass'\n")
    args = _args(tmp_path, email_provider="google", google_password_file=google)
    password = scout.verify_email_configuration(args)
    assert password == "gmail-app-pass"
    assert args.smtp_auth_user == "ryan.grimm@gmail.com"
    assert args.smtp_server == "smtp.gmail.com:587"


def test_verify_cli_username_overrides_file(tmp_path: Path) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='from-file'\nSMTP_PASSWORD='pw'\n",
    )
    args = _args(
        tmp_path,
        email_provider="smtp2go",
        smtp_credentials=path,
        smtp_auth_user="cli-user",
    )
    scout.verify_email_configuration(args)
    assert args.smtp_auth_user == "cli-user"


def test_parser_defaults_do_not_force_smtp2go() -> None:
    parser = scout.build_parser()
    args = parser.parse_args(["--test-email"])
    assert args.smtp_server == ""
    assert args.email_provider == ""
    assert args.email_config == scout.DEFAULT_EMAIL_CONFIG_FILE
    assert args.test_email is True


def test_test_email_smtp2go(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_creds(
        tmp_path / "smtp",
        "SMTP_USERNAME='smtp2go-user'\nSMTP_PASSWORD='smtp2go-secret'\n",
    )
    sent: dict[str, str] = {}

    def fake_swaks(**kwargs: str) -> None:
        sent.update(kwargs)

    monkeypatch.setattr(scout, "run_swaks_email", fake_swaks)
    args = _args(tmp_path, email_provider="smtp2go", smtp_credentials=path)
    assert scout.send_test_email(args) == 0
    assert sent["auth_user"] == "smtp2go-user"
    assert sent["password"] == "smtp2go-secret"
    assert sent["smtp_server"] == "mail.smtp2go.com:2525"
    assert sent["subject"] == "[Kalshi] mention scout SMTP test"


def test_format_swaks_failure_keeps_the_end_not_the_banner() -> None:
    banner = "=== Trying mail.smtp2go.com:2525...\n" + ("<-  250-STARTTLS\n" * 80)
    detail = banner + "<-  535 Incorrect authentication data\n*** No authentication was successful"
    text = scout.format_swaks_failure(detail, sender="ryan.grimm@gmail.com")
    assert "535" in text
    assert "SMTP Users" in text
    assert text.startswith("swaks failed:")


def test_format_swaks_failure_hints_verified_sender() -> None:
    detail = "<-  550 The from address does not match a verified Sender Identity"
    text = scout.format_swaks_failure(detail, sender="ryan.grimm@gmail.com")
    assert "Verified Senders" in text
    assert "ryan.grimm@gmail.com" in text


def test_redact_swaks_auth_payloads() -> None:
    raw = " -> AUTH LOGIN\n -> dXNlcm5hbWU=\n -> cGFzc3dvcmQ=\n<-  235 OK"
    text = scout._redact_swaks_transcript(raw)
    assert "dXNlcm5hbWU=" not in text
    assert "cGFzc3dvcmQ=" not in text
    assert "[redacted]" in text


def test_password_file_mode_is_600(tmp_path: Path) -> None:
    path = _write_creds(tmp_path / "smtp", "SMTP_USERNAME='u'\nSMTP_PASSWORD='p'\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.environ.get("SMTP_PASSWORD") != "p"
