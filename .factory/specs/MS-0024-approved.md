# MS-0024 — `mention_markets.py target` Kalshi fallback

Status: **APPROVED** by owner 2026-10-30 (chat: ticker exists on Kalshi but not in local calendar-added.json because local mention-scout is not running; fetch from Kalshi as needed).
Type: feature
Related: MS-0016, MS-0017, MS-0019

## Behavior

- `list` still requires `calendar-added.json`.
- `target EVENT_TICKER` still prefers the local catalog when present.
- If the ticker is missing from the JSON, or the JSON file is missing, `target` fetches public Kalshi `/markets?event_ticker=` and continues.
- Does not write `calendar-added.json`.
- If Kalshi returns no markets, exit 1 with an actionable message.
- Discovery/notification only. No trading.
