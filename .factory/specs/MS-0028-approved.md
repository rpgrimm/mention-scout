# MS-0028 — `mm-orderbook-watch` public order-book dump

Status: **APPROVED** by owner 2026-11-13 (chat: markets not open yet; poll every second; as soon as they open print orderbook every second and log to a file; maybe limit orders later but for now dump only; new script).
Type: feature
Related: MS-0016, MS-0027

## Behavior

- New root CLI `./mm-orderbook-watch` (optional `EVENT_TICKER`; default today's `KXWORLDNEWSMENTION-YYMONDD`).
- Poll public `/markets?event_ticker=` every `--interval` seconds (default 1).
- When any market is `active` or `open`, GET `/markets/{ticker}/orderbook` for each market every interval.
- Print a compact snapshot and append JSONL to `--log` (default `./orderbook-EVENT.jsonl`).
- Discovery only. No order placement, modification, or cancel. No auth.
