"""Offline unit tests for MS-0007 binary mention gate (rules excluded)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402

FIXTURE_PATH = ROOT / ".factory" / "tasks" / "MS-0007-fixture-KXGENERICTARIFF-26JUL.json"


def _load_tariff_fixture() -> tuple[dict, dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    event = payload["event"]
    nested = event.get("markets") or []
    assert nested, "fixture must embed nested markets"
    market = nested[0]
    return event, market


def test_ms0007_fixture_rejected_by_binary_gates() -> None:
    event, market = _load_tariff_fixture()

    assert scout.is_mention_event(event) is False
    assert scout.is_mention_market(market) is False
    assert scout.event_qualifies_as_mention(event, [market]) is False

    # Document the poison channel: rules still contain bare "mention".
    rules_secondary = str(market.get("rules_secondary") or "")
    assert "mention" in rules_secondary.casefold()
    assert scout.MENTION_RE.search(rules_secondary)

    # Full contains/display text still includes rules (and would match regex).
    full_text = scout.text_for_market(market)
    assert "mention" in full_text.casefold()
    assert scout.MENTION_RE.search(full_text)

    # Gate text must exclude rules and not match.
    gate_text = scout.mention_gate_text_for_market(market)
    assert "incidentally" not in gate_text.casefold()
    assert "rules_secondary" not in gate_text  # field name never appears
    assert market.get("rules_secondary") not in gate_text
    assert market.get("rules_primary") not in gate_text
    assert not scout.MENTION_RE.search(gate_text)
    assert not scout.SAY_EVENT_RE.search(gate_text)


@pytest.mark.parametrize(
    "market",
    [
        {
            "ticker": "KXFTNMENTION-26JUL05-YES",
            "event_ticker": "KXFTNMENTION-26JUL05",
            "title": "",
            "subtitle": "",
            "yes_sub_title": "",
            "no_sub_title": "",
            "rules_primary": "",
            "rules_secondary": "",
        },
        {
            "ticker": "KXEARNINGSMENTIONCCL-26JUN23-YES",
            "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
            "title": "",
            "rules_primary": "",
            "rules_secondary": "",
        },
    ],
)
def test_true_positive_ticker_mention_without_rules(market: dict) -> None:
    assert scout.is_mention_market(market) is True


def test_true_positive_title_say_language_without_rules() -> None:
    market = {
        "ticker": "KXCUSTOM-26AUG01-YES",
        "event_ticker": "KXCUSTOM-26AUG01",
        "title": "What will Jane say about inflation tomorrow?",
        "subtitle": "",
        "yes_sub_title": "",
        "no_sub_title": "",
        "rules_primary": "",
        "rules_secondary": "",
    }
    assert scout.is_mention_market(market) is True
    assert scout.SAY_EVENT_RE.search(scout.mention_gate_text_for_market(market))


def test_true_positive_title_mention_language_without_rules() -> None:
    market = {
        "ticker": "KXCUSTOM-26AUG02-YES",
        "event_ticker": "KXCUSTOM-26AUG02",
        "title": "How many times will the host mention inflation tonight?",
        "subtitle": "",
        "rules_primary": "",
        "rules_secondary": "settlement prose without the poison word",
    }
    assert scout.is_mention_market(market) is True
    assert scout.MENTION_RE.search(scout.mention_gate_text_for_market(market))


def test_contains_still_searches_rules_while_gate_rejects() -> None:
    market = {
        # Avoid substring "MENTION" in tickers (fast-path would admit).
        "ticker": "KXTARIFFONLY-26AUG01-YES",
        "event_ticker": "KXTARIFFONLY-26AUG01",
        "title": "Will tariffs rise before November?",
        "subtitle": "",
        "yes_sub_title": "Yes",
        "no_sub_title": "No",
        "rules_primary": "Ordinary settlement text.",
        "rules_secondary": "Unique token ZYXCONTAINSRULES appears only here.",
    }
    assert scout.is_mention_market(market) is False
    assert scout.contains_filter(market, "zyxcontainsrules") is True
    assert scout.contains_filter(market, "not-in-this-market-xyz") is False


def test_parent_mention_series_still_qualifies_with_quiet_children() -> None:
    event = {
        "event_ticker": "KXFTNMENTION-26JUL05",
        "series_ticker": "KXFTNMENTION",
        "title": "Face the Nation Mentions — Jul 5",
        "sub_title": "",
        "category": "Politics",
    }
    quiet_child = {
        "ticker": "KXFTNMENTION-26JUL05-WORD",
        "event_ticker": "KXFTNMENTION-26JUL05",
        "title": "inflation",
        "rules_primary": "",
        "rules_secondary": "",
    }
    assert scout.is_mention_event(event) is True
    # Child title alone is not a mention product phrase, but parent qualifies.
    assert scout.is_mention_market(quiet_child) is True  # ticker contains MENTION
    assert scout.event_qualifies_as_mention(event, [quiet_child]) is True

    non_mention_child = {
        "ticker": "KXOTHER-1-YES",
        "event_ticker": "KXOTHER-1",
        "title": "plain outcome",
        "rules_primary": "",
        "rules_secondary": "",
    }
    assert scout.is_mention_market(non_mention_child) is False
    # Parent MENTION series still admits the event even if a sibling is quiet.
    assert scout.event_qualifies_as_mention(event, [non_mention_child]) is True


def test_missing_fields_do_not_raise() -> None:
    assert scout.is_mention_market({}) is False
    assert scout.mention_gate_text_for_market({}) == "\n".join([""] * 6)
    assert scout.event_qualifies_as_mention({}, []) is False
    assert scout.event_qualifies_as_mention({}) is False
