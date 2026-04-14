# Step-by-step build plan (WSB sentiment + inverse strategy)

This is the implementation sequence we will follow. Each phase has a concrete definition of done.

## Phase 0 — Strategy rules and constraints
1. Fix signal window and execution timing to avoid lookahead.
2. Define the tradable universe and shorting constraints.
3. Define costs: slippage, fees, borrow carry.

**Done when:** We have a written strategy spec and parameter grid for variants.

## Phase 1 — Data foundation
1. Set up Reddit API credentials.
2. Build post collection job.
3. Build comment collection job.
4. Save immutable raw payloads in database tables.

**Done when:** We can ingest at least 30 days of posts/comments reproducibly.

## Phase 2 — Text and ticker extraction
1. Normalize text and preserve raw source columns.
2. Extract candidate ticker mentions.
3. Filter false positives using denylist + context rules.
4. Map mentions to valid tradable symbols by date.

**Done when:** We can produce a daily ticker-mention table with quality checks.

## Phase 3 — Feature engineering
1. Mention count.
2. Mention velocity (short lookback vs long lookback z-score).
3. Upvote-weighted mention intensity.
4. Comment engagement score.
5. Basic bullish/bearish sentiment score.
6. Composite hype score.

**Done when:** We produce daily per-ticker feature vectors.

## Phase 4 — Backtest engine
1. Pull historical market data.
2. Align Reddit timestamps to market calendar.
3. Implement portfolio construction (equal-weight and constraints).
4. Add execution costs and shorting constraints.
5. Run strategy variants: normal vs inverse.

**Done when:** We can generate equity curves and trade logs from a single command.

## Phase 5 — Evaluation and validation
1. Compute return, drawdown, Sharpe, win rate.
2. Evaluate by market regime.
3. Validate against lookahead/survivorship bias.
4. Run stress tests and perturbation checks.

**Done when:** We have a reproducible report with robustness tables.

## Phase 6 — Dashboard
1. Top mentioned tickers.
2. Top hype tickers.
3. Bullish vs bearish rankings.
4. Current positions.
5. Equity curve and stats.

**Done when:** A simple dashboard renders daily outputs from pipeline artifacts.
