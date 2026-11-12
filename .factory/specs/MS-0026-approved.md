# MS-0026 — `mm-world-news` weekday helper

Status: **APPROVED** by owner 2026-11-12 (chat: every weekday `./mention_markets.py target KXWORLDNEWSMENTION-26NOV12`; helper `mm-world-news` should run today's `KXWORLDNEWSMENTION-YYMONDD`).
Type: feature
Related: MS-0016, MS-0024, MS-0025

## Behavior

- `./mm-world-news` is equivalent to `./mention_markets.py target KXWORLDNEWSMENTION-YYMONDD` for the local date (`2026-11-12` → `26NOV12`; English month abbrev, zero-padded day).
- Remaining args pass through to `target` (`--dry-run`, `--sleep`, `--json`, …).
- `--date YYYY-MM-DD` overrides today (for tests / catch-up).
- Console script `mm-world-news` after `pip install -e .`.
- Discovery/notification only. No trading.
