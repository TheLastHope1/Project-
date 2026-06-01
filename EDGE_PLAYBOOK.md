# Edge Playbook

This is the practical research workflow for turning the scanner from "interesting
alerts" into a real edge.

## The real opportunity classes

### 1. Stale-open event markets

Best pattern: event/match time has passed, the market is still accepting orders,
and the underdog is cheap. This can mean the market has not incorporated a
forfeit, cancellation, walkover, retirement, no-contest, or settlement ambiguity.

Action: verify the real event status from the official event/tournament source,
team/player social accounts, livestream pages, and bookmaker score feeds.

### 2. Display price vs executable ask mismatch

Gamma/outcome price can be a midpoint or stale display value. The scanner probes
CLOB best asks for candidates so the alert is based on what you may actually pay.

Action: compare `screen_price` with `Ask/Price`. A lower ask than screen price is
interesting. A much higher ask means the displayed edge is probably fake.

### 3. Rule ambiguity

Markets with words like forfeit, no-show, no contest, walkover, withdrawal,
retirement, cancelled, postponed, void, Unknown, refund, or 50/50 deserve manual
review. The edge is not the keyword by itself; the edge is how traders price the
ambiguity.

Action: screenshot/save the rules before trading. Rules can be interpreted in
ways the market price has not fully reflected.

### 4. Watchlist-driven situations

Teams/entities known to have double-booking, travel issues, roster drama,
walkover history, tournament conflicts, or disqualification risk should be on the
watchlist. The scanner treats watchlist hits as higher-signal than generic tags.

Action: maintain `POLY_WATCHLIST` like a trading notebook, not a random list.

## Manual review checklist per alert

Before taking any trade, answer:

1. Is this actually a head-to-head market, not an outright/season/futures market?
2. What exact event/match is this market tied to?
3. Has the scheduled start/end already passed?
4. Is the market still accepting orders?
5. What is the executable ask right now, not just the displayed price?
6. What is the spread?
7. Is there enough size available below your target price?
8. What do the market rules say about cancellation/forfeit/no-contest?
9. Could it resolve as refund/void rather than split/Unknown?
10. What is the official source of truth?
11. What are other markets/books implying?
12. Are you early, or is the price already adjusted?

## Next code upgrades

### A. Depth-aware EV

Current version probes top-of-book price. Next upgrade should fetch full books and
calculate available shares below $0.50, average fill price for a target stake, and
profit if a split/Unknown outcome happens.

### B. Price-history anomaly module

Use price-history data to detect sudden pre-resolution moves, especially when the
market moves before Polymarket front-end or casual traders notice.

### C. External source scrapers

Add pluggable sources for:

- esports match schedules and forfeit notices,
- tennis withdrawals/retirements/walkovers,
- MMA/boxing bout cancellations,
- official tournament pages,
- bookmaker odds/score feeds.

### D. Paper-trade ledger

Every alert should be stored with:

- timestamp,
- market id/slug,
- screen price,
- executable ask/bid/spread,
- score and reasons,
- final resolution,
- hypothetical fill,
- hypothetical P/L,
- false-positive reason.

After 50-100 alerts you can tell whether this is real edge or just noise.

### E. Alert tiers

Suggested tiers:

- `score >= 75`: urgent manual review now.
- `score 55-74`: check if you are already watching the team/event.
- `score < 55`: log only unless there is outside information.

## Deployment stance

Deploy the scanner, not an auto-trader. A good version of this product is a
private intelligence terminal that gets you to the right market before other
people. The dangerous version is one that blindly assumes every cancellation is a
50/50 payout and auto-buys bad asks.
