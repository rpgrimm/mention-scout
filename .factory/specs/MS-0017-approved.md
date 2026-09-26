# MS-0017 — world-news vs interview Google search modes

Status: **APPROVED** by owner 2026-09-25 (chat: WNT searches words by themselves; interview shows use `{guest} {word}` and never the program name; CLI should take a mode and pick smartly).
Type: feature
Related: MS-0016
Branch: `openclaw/ms-0017` + PR into `main`. Do not merge until owner desktop-tests.

## Behavior

`--mode auto` (default):

- Tickers starting `KXWORLDNEWSMENTION` → `world-news` (`abc` / `wnt` aliases).
- Everything else → `interview`.

Queries:

- world-news: `{cleaned word} news` (word by itself; no guest, no show name).
- interview: `{guest} {cleaned word}` — no `news` suffix, no show name.

Guest extraction (interview):

1. `--guest "First Last"` wins.
2. Else Kalshi market `title`: `What will Jamie Raskin say during Meet the Press?`
3. Else `Name - Show` (left of ` - `).
4. Never treat `any host or reporter` as a guest.
5. If still missing: exit 1, tell the user to pass `--guest`.

`--mode world-news|abc|wnt` and `--mode interview` override auto.
