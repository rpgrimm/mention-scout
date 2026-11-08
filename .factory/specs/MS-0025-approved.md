# MS-0025 — uppercase Kalshi event ticker on `target`

Status: **APPROVED** by owner 2026-11-08 (chat: lowercase `kxmamdanimention-26nov08` returned no markets; uppercase worked; convert lowercase to upper for Kalshi fetch).
Type: tweak
Related: MS-0024

## Behavior

- `mention_markets.py target` folds the event ticker to uppercase before the public Kalshi `/markets?event_ticker=` GET.
- `kxmamdanimention-26nov08` and `KXMAMDANIMENTION-26NOV08` hit the same Kalshi event.
- Still does not write `calendar-added.json`.
- Discovery/notification only. No trading.
