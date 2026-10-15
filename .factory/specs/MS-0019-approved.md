# MS-0019 — open Kalshi event page in Chrome on target

Status: **APPROVED** by owner 2026-10-15 (chat: `./mention_markets.py target KXWORLDNEWSMENTION-26OCT15` should also open the market on kalshi.com in Chrome).
Type: feature
Related: MS-0016, MS-0017
Branch: `openclaw/ms-0019` + PR into `main`. Do not merge until owner desktop-tests.

## Behavior

- `target` opens the parent event on `https://kalshi.com/markets/{series}/{title-slug}/{event_ticker}` **first**.
- Browser is **Google Chrome** (`google-chrome --new-tab`, then chromium aliases, then default browser).
- Existing Google word tabs still open after that, 2s apart.
- `--dry-run` prints the Kalshi URL and does not open a browser.
- Discovery only. No trading.
