# MS-0027 — target includes created-but-not-open markets

Status: **APPROVED** by owner 2026-11-13 (chat: `KXWORLDNEWSMENTION-26NOV13` exists as Launching soon / not active-open; still want Google tabs).
Type: tweak
Related: MS-0016, MS-0024

## Behavior

- `mention_markets.py target` uses markets Kalshi has created, including `initialized`, `unopened`, and `inactive`.
- Still skips terminal statuses: `closed`, `determined`, `settled`, `finalized`.
- Skip-words `unknown` and `event does not qualify` unchanged.
- Discovery/notification only. No trading.
