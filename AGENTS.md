You are building `polymarket-edge`.

Rules:
1. Public market data must work without credentials.
2. Live trading must be disabled by default.
3. Do not search the computer for private keys, seed phrases, cookies, wallet files, browser-extension data, saved passwords, or secrets.
4. All secrets must be provided explicitly by the user through `.env.local` or an interactive prompt.
5. `.env.local` must be in `.gitignore`.
6. Never commit secrets.
7. Never print secrets.
8. Never log secrets.
9. Never place market orders.
10. Only use limit orders.
11. Do not place real orders unless:
    - LIVE_TRADING_ENABLED=true
    - REAL_MONEY_ACKNOWLEDGED=true
    - TRADING_MODE=live_tiny
    - live-preflight passes
    - risk manager approves
    - manual confirmation is given unless explicitly disabled
12. Paper trading must work before live trading.
13. Tests must be written for all core formulas and risk controls.
14. Every module should be typed, small, and testable.
15. All network calls need retries, timeouts, and structured logging.

