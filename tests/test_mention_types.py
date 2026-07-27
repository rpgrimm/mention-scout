"""Offline unit tests for MS-0006 mention type labels, filter, and subjects."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kalshi_mention_scout as scout  # noqa: E402


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected_id"),
    [
        (
            {
                "series_ticker": "KXEARNINGSMENTIONCCL",
                "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
                "title": "What will Carnival Cruise say during their next earnings call?",
            },
            "earnings",
        ),
        (
            {
                "series_ticker": "KXFTNMENTION",
                "event_ticker": "KXFTNMENTION-26JUL05",
                "title": "Face the Nation Mentions — Jul 5",
            },
            "face-the-nation",
        ),
        (
            {
                "series_ticker": "KXWORLDNEWSMENTION",
                "event_ticker": "KXWORLDNEWSMENTION-26JUL25",
                "title": "World News Tonight Mentions",
            },
            "world-news-tonight",
        ),
        (
            {
                "series_ticker": "KXTRUMPMENTION",
                "event_ticker": "KXTRUMPMENTION-26AUG01",
                "title": "Trump mention markets",
            },
            "trump",
        ),
        (
            {
                "series_ticker": "KXTRUMPSAY",
                "event_ticker": "KXTRUMPSAY-26AUG02",
                "title": "What will Trump say?",
            },
            "trump",
        ),
        (
            {
                "series_ticker": "KXSOMEONESAY",
                "event_ticker": "KXSOMEONESAY-26AUG03",
                "title": "What will Someone say on stage?",
            },
            "say",
        ),
        (
            {
                "series_ticker": "KXSOMETHINGMENTION",
                "event_ticker": "KXSOMETHINGMENTION-26AUG01",
                "title": "A novel mention market",
            },
            "other",
        ),
        (
            {
                "series_ticker": "",
                "event_ticker": "",
                "title": "",
                "description": "",
            },
            "other",
        ),
        # Title-only FTN when series is missing.
        (
            {
                "series_ticker": "",
                "event_ticker": "CUSTOM-26JUL05",
                "title": "Face the Nation Mentions — Jul 5",
            },
            "face-the-nation",
        ),
        # Priority: FTN series must win over an earnings-ish title.
        (
            {
                "series_ticker": "KXFTNMENTION",
                "event_ticker": "KXFTNMENTION-26JUL05",
                "title": "Earnings call special on Face the Nation",
            },
            "face-the-nation",
        ),
        # Priority: WNT over residual say title.
        (
            {
                "series_ticker": "KXWORLDNEWSMENTION",
                "event_ticker": "KXWORLDNEWSMENTION-26JUL25",
                "title": "What will the anchors say tonight?",
            },
            "world-news-tonight",
        ),
        # Priority: earnings ticker over generic say phrasing in title.
        (
            {
                "series_ticker": "KXEARNINGSMENTIONCCL",
                "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
                "title": "What will Carnival Cruise say during their next earnings call?",
            },
            "earnings",
        ),
    ],
)
def test_mention_type_for_event(event: dict, expected_id: str) -> None:
    assert scout.mention_type_for_event(event) == expected_id
    assert scout.classify_mention_type(
        series_ticker=event.get("series_ticker"),
        event_ticker=event.get("event_ticker"),
        title=event.get("title"),
        description=event.get("description"),
    ).id == expected_id


def test_mention_type_for_market_prefers_parent_series() -> None:
    market = {
        "ticker": "CHILD-YES",
        "event_ticker": "CHILD-EVENT",
        "title": "What will they say?",
    }
    parent = {
        "series_ticker": "KXEARNINGSMENTIONCCL",
        "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
        "title": "Carnival earnings",
    }
    assert scout.mention_type_for_market(market, parent) == "earnings"
    # Without parent, residual say title wins.
    assert scout.mention_type_for_market(market, None) == "say"


def test_precomputed_mention_type_on_event_is_respected() -> None:
    event = {
        "event_ticker": "X",
        "mention_type": "earnings",
        "title": "Face the Nation",  # would otherwise classify as FTN
    }
    assert scout.mention_type_for_event(event) == "earnings"


# ---------------------------------------------------------------------------
# Subject builder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {
                "series_ticker": "KXEARNINGSMENTIONCCL",
                "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
                "title": "Carnival earnings call",
            },
            "[Kalshi] earnings | NEW: KXEARNINGSMENTIONCCL-26JUN23",
        ),
        (
            {
                "series_ticker": "KXFTNMENTION",
                "event_ticker": "KXFTNMENTION-26JUL05",
                "title": "Face the Nation",
            },
            "[Kalshi] Face the Nation | NEW: KXFTNMENTION-26JUL05",
        ),
        (
            {
                "series_ticker": "KXWORLDNEWSMENTION",
                "event_ticker": "KXWORLDNEWSMENTION-26JUL25",
                "title": "World News Tonight",
            },
            "[Kalshi] World News Tonight | NEW: KXWORLDNEWSMENTION-26JUL25",
        ),
        (
            {
                "series_ticker": "KXTRUMPMENTION",
                "event_ticker": "KXTRUMPMENTION-26AUG01",
            },
            "[Kalshi] Trump | NEW: KXTRUMPMENTION-26AUG01",
        ),
        (
            {
                "series_ticker": "KXSOMETHINGMENTION",
                "event_ticker": "KXSOMETHINGMENTION-26AUG01",
            },
            "[Kalshi] other | NEW: KXSOMETHINGMENTION-26AUG01",
        ),
        (
            {"event_ticker": "TICKER_WITH-special.chars+"},
            "[Kalshi] other | NEW: TICKER_WITH-special.chars+",
        ),
        (
            {},
            "[Kalshi] other | NEW: new mention market",
        ),
    ],
)
def test_format_new_market_email_subject(event: dict, expected: str) -> None:
    assert scout.format_new_market_email_subject(event) == expected


def test_format_overview_email_includes_type_line() -> None:
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    event = {
        "event_ticker": "KXFTNMENTION-26JUL05",
        "title": "Face the Nation",
        "series_ticker": "KXFTNMENTION",
        "mention_type": "face-the-nation",
        "mention_type_label": "Face the Nation",
        "statuses": ["open"],
        "contract_count": 3,
    }
    body = scout.format_overview_email(
        event,
        datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        ZoneInfo("America/New_York"),
    )
    assert "Type: Face the Nation" in body
    assert body.index("Title:") < body.index("Type:")


# ---------------------------------------------------------------------------
# Filter / aliases / invalid tokens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("earnings", frozenset({"earnings"})),
        ("EARNINGS", frozenset({"earnings"})),
        ("earnings,face-the-nation", frozenset({"earnings", "face-the-nation"})),
        ("ftn", frozenset({"face-the-nation"})),
        ("WNT", frozenset({"world-news-tonight"})),
        ("world-news", frozenset({"world-news-tonight"})),
        ("ftn, wnt, trump", frozenset({"face-the-nation", "world-news-tonight", "trump"})),
        ("face_the_nation", frozenset({"face-the-nation"})),
    ],
)
def test_parse_type_filter_valid(raw: str | None, expected: frozenset[str] | None) -> None:
    assert scout.parse_type_filter(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", ",", "nope", "earnings,nope", "foo,bar"])
def test_parse_type_filter_invalid(raw: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        scout.parse_type_filter(raw)
    message = str(excinfo.value)
    assert "Known:" in message or "requires at least one" in message


def test_event_matches_types_any_of() -> None:
    earnings = {
        "series_ticker": "KXEARNINGSMENTIONCCL",
        "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
    }
    ftn = {
        "series_ticker": "KXFTNMENTION",
        "event_ticker": "KXFTNMENTION-26JUL05",
        "title": "Face the Nation",
    }
    other = {"event_ticker": "KXSOMETHINGMENTION-1", "series_ticker": "KXSOMETHINGMENTION"}

    assert scout.event_matches_types(earnings, None) is True
    selected = frozenset({"earnings", "face-the-nation"})
    assert scout.event_matches_types(earnings, selected) is True
    assert scout.event_matches_types(ftn, selected) is True
    assert scout.event_matches_types(other, selected) is False
    assert scout.event_matches_types(other, frozenset({"other"})) is True


def test_market_matches_types_and_with_contains_semantics() -> None:
    """Type filter is independent; AND with contains is composition at call site."""
    market = {
        "ticker": "KXEARNINGSMENTIONCCL-26JUN23-YES",
        "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
        "title": "What will Carnival Cruise say during their next earnings call?",
    }
    parent = {
        "series_ticker": "KXEARNINGSMENTIONCCL",
        "event_ticker": "KXEARNINGSMENTIONCCL-26JUN23",
        "title": market["title"],
    }
    selected = frozenset({"earnings"})
    assert scout.market_matches_types(market, selected, parent) is True
    assert scout.contains_filter(market, "carnival") is True
    assert scout.contains_filter(market, "nonexistent-xyz") is False
    # AND composition as used by main():
    assert (
        scout.market_matches_types(market, selected, parent)
        and scout.contains_filter(market, "carnival")
    ) is True
    assert (
        scout.market_matches_types(market, selected, parent)
        and scout.contains_filter(market, "nonexistent-xyz")
    ) is False
    assert (
        scout.market_matches_types(market, frozenset({"trump"}), parent)
        and scout.contains_filter(market, "carnival")
    ) is False


def test_watch_child_arguments_preserves_type_flag() -> None:
    child = scout._watch_child_arguments(
        ["--watch-new", "--email-new", "--type", "earnings,ftn", "--contains", "x"]
    )
    assert "--watch-new" not in child
    assert "--email-new" not in child
    assert "--type" in child
    type_idx = child.index("--type")
    assert child[type_idx + 1] == "earnings,ftn"
    assert "--contains" in child
    assert "--overview" in child
    assert "--json" in child


def test_watch_child_arguments_preserves_type_equals_form() -> None:
    child = scout._watch_child_arguments(["--watch-new", "--type=trump"])
    assert any(token == "--type=trump" or token.startswith("--type=") for token in child)


def test_cli_help_lists_type_flag() -> None:
    parser = scout.build_parser()
    help_text = parser.format_help()
    assert "--type" in help_text
    assert "earnings" in help_text
    assert "face-the-nation" in help_text


def test_registry_priority_order_matches_spec() -> None:
    expected = [
        "face-the-nation",
        "world-news-tonight",
        "earnings",
        "trump",
        "say",
        "other",
    ]
    assert list(scout.KNOWN_MENTION_TYPE_IDS) == expected
    # Rule table must not include `other` and must follow the same prefix order.
    rule_ids = [type_id for type_id, *_ in scout._TYPE_RULES]
    assert rule_ids == expected[:-1]


def test_normalize_type_token_aliases_and_case() -> None:
    assert scout.normalize_type_token("FTN") == "face-the-nation"
    assert scout.normalize_type_token("World-News") == "world-news-tonight"
    assert scout.normalize_type_token("Earnings") == "earnings"
    with pytest.raises(ValueError):
        scout.normalize_type_token("not-a-type")
