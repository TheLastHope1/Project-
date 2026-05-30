# Feasibility Analysis: Polymarket Forfeit-Edge Strategy

## Executive Summary

The strategy exploits Polymarket's rule that forfeited events resolve at
50/50 instead of refunding bets. Buying the underdog below $0.50 creates
a guaranteed profit if a forfeit occurs. **After fees, the math works.**
The real questions are: how often do forfeits happen, and can you get
enough size on?

**Bottom line:** Profitable per-trade, but likely a small side-income
(~$50–300/month) rather than a full-time edge, constrained by opportunity
frequency and market liquidity.

---

## 1. Fee Analysis

### Polymarket's Fee Formula

```
fee_per_share = feeRate × price × (1 - price)
```

For **Sports/Esports** markets:
- feeRate = **0.75%** (lowest category rate)
- Exponent = 1 (fees scale linearly with p × (1-p))
- Fees peak at price $0.50 and drop toward zero at extremes
- No fee on resolution/payout — only on buying

### Fee Impact at Various Underdog Prices

| Underdog Price | Fee/Share | Total Cost/Share | Payout (Forfeit) | Profit/Share | ROI |
|:-:|:-:|:-:|:-:|:-:|:-:|
| $0.05 | $0.0004 | $0.0504 | $0.50 | $0.4496 | **+893%** |
| $0.10 | $0.0007 | $0.1007 | $0.50 | $0.3993 | **+396%** |
| $0.15 | $0.0010 | $0.1510 | $0.50 | $0.3490 | **+231%** |
| $0.20 | $0.0012 | $0.2012 | $0.50 | $0.2988 | **+148%** |
| $0.25 | $0.0014 | $0.2514 | $0.50 | $0.2486 | **+99%** |
| $0.30 | $0.0016 | $0.3016 | $0.50 | $0.1984 | **+66%** |
| $0.35 | $0.0017 | $0.3517 | $0.50 | $0.1483 | **+42%** |
| $0.40 | $0.0018 | $0.4018 | $0.50 | $0.0982 | **+24%** |
| $0.45 | $0.0019 | $0.4519 | $0.50 | $0.0481 | **+11%** |
| $0.498 | $0.0019 | $0.4999 | $0.50 | ~$0.00 | **Breakeven** |

**Conclusion: Fees are negligible.** At P=0.20, the fee is $0.0012/share —
less than 1% of the trade. The breakeven is P ≈ $0.498, meaning any
underdog below $0.498 is profitable after fees in a forfeit scenario.

### Bid-Ask Spread (The Real Cost)

Fees are trivial but spread matters more. A typical esports market has a
2–5 cent spread. If the "fair" underdog price is $0.20 but the best ask
is $0.23, you enter at $0.23.

| Fair Price | Ask Price (3¢ spread) | Forfeit Profit | ROI |
|:-:|:-:|:-:|:-:|
| $0.10 | $0.13 | $0.37 | +285% |
| $0.20 | $0.23 | $0.27 | +117% |
| $0.30 | $0.33 | $0.17 | +52% |
| $0.40 | $0.43 | $0.07 | +16% |

Even with spread, the edge remains large at low underdog prices.

---

## 2. Risk Analysis

### The Core Risk: Forfeit Doesn't Happen

If the match plays out normally and the favorite wins, your underdog shares
go to $0.00. **You lose 100% of that trade.**

Three possible outcomes after buying underdog at price P:

| Outcome | Payout | P&L per share | Probability (estimated) |
|---------|--------|--------------|------------------------|
| Match forfeited | $0.50 | +$(0.50 - P) | Depends on signal strength |
| Underdog wins | $1.00 | +$(1.00 - P) | Market-implied ~P |
| Favorite wins | $0.00 | -$P | Market-implied ~(1-P) |

### Expected Value by Forfeit Probability

For an underdog at P = $0.20 (where the market implies 20% underdog win rate):

| Est. Forfeit Prob. | EV/Share | EV on $100 Bet | Interpretation |
|:-:|:-:|:-:|---|
| 10% | +$0.03 | +$15 | Marginal — only trade if very confident |
| 20% | +$0.06 | +$30 | Decent edge, but high variance |
| 50% | +$0.15 | +$75 | Strong — the double-booking scenario |
| 80% | +$0.24 | +$120 | Near-certainty — event already past end |
| 95% | +$0.285 | +$142 | Almost guaranteed (stale_open signal) |

**Key insight:** Even at a modest 20% estimated forfeit probability, the
trade is +EV because the payout asymmetry is enormous ($0.50 return on a
$0.20 investment = 150% gross if it hits).

### Signal Strength → Forfeit Probability Mapping

| Scanner Signal | Estimated Forfeit Prob. | Confidence |
|---|:-:|---|
| `past_end:Nm_still_open` (event over, market open) | 70–95% | Very high — this is the FaZe pattern |
| `starts_in:0m` + watchlist team double-booked | 40–70% | High — you know the conflict |
| `price_anomaly` (20%+ price move) | 20–50% | Medium — something happened, unclear what |
| Category match + imminent only | 5–15% | Low — speculative |

**Only trade on strong signals.** The `past_end` signal (event time passed,
market still accepting trades) is the highest-conviction setup — it means
the match almost certainly didn't happen.

---

## 3. Liquidity Constraints

### How Much Can You Actually Trade?

Even with a profitable edge, the orderbook limits position size.

Typical esports H2H market on Polymarket:
- Liquidity: $2,000–$20,000
- Underdog side depth: often only $500–$2,000 at the displayed price
- Your buy moves the price — a $500 market buy might fill at $0.20–$0.28
  instead of a flat $0.20

**Realistic trade size per opportunity: $100–$500**

Larger bets (>$500) will suffer significant slippage and may not be worth
executing unless the market is unusually liquid.

### Slippage Example

Buying $300 of underdog shares at P=$0.20 in a market with $5,000 liquidity:

| Tranche | Fill Price | Shares | Cost |
|---------|:-:|:-:|:-:|
| First $100 | $0.20 | 500 | $100 |
| Next $100 | $0.22 | 455 | $100 |
| Last $100 | $0.25 | 400 | $100 |
| **Total** | **$0.222 avg** | **1,355** | **$300** |

Payout if forfeit: 1,355 × $0.50 = $677.50 → **Profit: $377.50 (126%)**

Still very profitable, but the effective price is higher than the displayed
bid.

---

## 4. Opportunity Frequency

### How Often Do Forfeits Happen?

This is the hardest variable. Based on available data:

- Polymarket lists **~750 active esports markets** at any time
- Major esports tournaments (IEM, BLAST, LCK, LPL) run weekly
- Scheduling conflicts (the original FaZe insight) happen when teams
  qualify for overlapping events — perhaps **2–5 times per week** across
  all esports titles
- Combat sports (UFC, boxing) cancellations due to injury/weight miss:
  perhaps **1–3 per month**
- Tennis walkovers (injury mid-match): **several per week** during Grand
  Slam seasons

**Conservative estimate:** 2–4 tradeable opportunities per week where the
scanner fires a high-conviction alert.

**Not all opportunities are equal.** Only `past_end` and strong watchlist
signals are high-conviction. Category-only matches are too speculative.

---

## 5. Projected Returns

### Conservative Scenario

| Parameter | Value |
|-----------|-------|
| Opportunities per week | 2 |
| Average trade size | $200 |
| Average underdog price | $0.25 |
| Average forfeit probability | 60% |
| Win rate (forfeit happens) | 60% |

Per trade:
- If forfeit (60%): profit = $200 × (0.50/0.25 - 1) = **+$200**
- If no forfeit, underdog loses (32%): loss = **-$200**
- If no forfeit, underdog wins (8%): profit = **+$600**

**EV per trade: 0.60 × $200 + 0.08 × $600 + 0.32 × (-$200) = +$104**

Weekly: 2 trades × $104 = **$208/week**
Monthly: **~$830/month**

### Pessimistic Scenario

| Parameter | Value |
|-----------|-------|
| Opportunities per week | 1 |
| Average trade size | $150 |
| Average underdog price | $0.30 |
| Win rate (forfeit happens) | 40% |

**EV per trade: 0.40 × $100 + 0.06 × $350 + 0.54 × (-$150) = +$0**

Roughly breakeven if your signal accuracy drops to 40%. Below that,
the strategy loses money.

### Optimistic Scenario (Active Watchlist + Multiple Titles)

| Parameter | Value |
|-----------|-------|
| Opportunities per week | 5 |
| Average trade size | $300 |
| Average underdog price | $0.20 |
| Win rate (forfeit happens) | 70% |

**EV per trade: 0.70 × $150 + 0.06 × $240 + 0.24 × (-$300) = +$47.40**

Wait — let me recalculate properly:
- Forfeit (70%): 0.70 × $300 × (0.50/0.20 - 1) = 0.70 × $450 = +$315
- Underdog wins normally (6%): 0.06 × $300 × (1.00/0.20 - 1) = 0.06 × $1200 = +$72
- Favorite wins (24%): 0.24 × (-$300) = -$72

**EV per trade: +$315/week → ~$1,260/month**

---

## 6. Startup Capital Requirements

| Component | Cost | Notes |
|-----------|------|-------|
| Azure VM (B1s) | **$0/mo** | GitHub Student Pack |
| Scanner software | **$0** | Already built |
| Polymarket account funding | **$200–$500** | USDC on Polygon |
| Polygon gas fees | **<$1/mo** | ~$0.001 per transaction |
| **Total startup** | **$200–$500** | |

### Bankroll Management

With a $500 bankroll and $200 average trade size:
- Keep 40% as reserve ($200) to cover losing streaks
- Never bet more than $300 on a single market
- A 3-trade losing streak (possible even at 60% win rate) costs $600 —
  make sure you can handle that drawdown

**Recommended starting bankroll: $500**
**Maximum single trade: 30% of bankroll**

---

## 7. Risks and Limitations

### Polymarket Can Change the Rules
The 50/50 forfeit resolution is a T&C choice, not a law. Polymarket could
switch to refunds at any time. **Check resolution rules before every trade.**

### Datacenter IP Blocking
Polymarket's API uses Cloudflare. Azure datacenter IPs may get 403'd.
Mitigation: increase scan interval, or route through a residential proxy.

### This Edge Will Shrink
As more people discover the forfeit-edge opportunity, the underdog price
will be bid up toward $0.50 (which is the "correct" price if forfeit is
certain). The edge exists because most users don't know the rules.

### UMA Dispute Risk
Anyone can dispute a 50/50 resolution by posting a $750 PUSD bond. If
enough UMA token holders vote against the 50/50, the resolution changes.
This is rare but not impossible for high-profile markets.

### Regulatory Risk
Polymarket faces regulatory pressure (Tennessee cease-and-desist in 2026).
Sports prediction markets specifically are under scrutiny.

---

## 8. Verdict

| Question | Answer |
|----------|--------|
| Does the math work after fees? | **Yes.** Fees are <1% of trade value. |
| Is it risk-free? | **No.** You lose 100% if the match plays out normally. |
| Is it +EV? | **Yes, if signal accuracy is >30%.** |
| Realistic monthly income? | **$50–$300** conservatively, $500–$1,000 if active. |
| Required capital? | **$500** recommended starting bankroll. |
| Time commitment? | **5 min/day** — check dashboard, place trades on alerts. |
| Will the edge last? | **Months, not years.** It shrinks as more people discover it. |

### Recommendation

Start with $500 on Polymarket. Only trade on **`past_end`** and
**watchlist-confirmed** signals initially — these are the highest-conviction
setups. Track every trade in a spreadsheet. After 20 trades, evaluate your
actual win rate. If it's above 40%, scale up. If below, tighten the scanner
thresholds or add stronger signals (UMA oracle monitoring).
