import { and, eq, gte, inArray, isNotNull } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, trades, anomalies } from '@/lib/db/schema';
import { percentile, clamp } from '@/lib/utils/math';
import { ANOMALY_THRESHOLDS } from '@/lib/utils/constants';

export type AnomalyType =
  | 'volume_spike'
  | 'price_impact'
  | 'whale_trade'
  | 'burst_trading'
  | 'price_divergence';

export type AnomalySeverity = 'low' | 'medium' | 'high' | 'critical';

export interface DetectedAnomaly {
  marketId: string;
  type: AnomalyType;
  severity: AnomalySeverity;
  score: number; // 0-1
  description: string;
  details: Record<string, unknown>;
  relatedTradeIds?: string[];
  relatedAccountId?: string;
}

/**
 * Map a numeric score (0-1) to a severity bucket.
 */
export function severityFromScore(score: number): AnomalySeverity {
  const s = clamp(score, 0, 1);
  if (s >= 0.85) return 'critical';
  if (s >= 0.6) return 'high';
  if (s >= 0.3) return 'medium';
  return 'low';
}

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Detect sudden volume spikes. For each market: compare the trade volume
 * in the last 5 minutes to the 24h rolling average (per 5-min window). If
 * the recent volume is > volumeSpikeMultiplier * avg, flag as anomaly.
 */
export async function detectVolumeSpikes(): Promise<DetectedAnomaly[]> {
  const db = getDb();
  const results: DetectedAnomaly[] = [];

  try {
    const now = Date.now();
    const since24h = now - DAY;
    const since5m = now - 5 * MINUTE;

    const recent = await db
      .select({
        id: trades.id,
        marketId: trades.marketId,
        amount: trades.amount,
        timestamp: trades.timestamp,
      })
      .from(trades)
      .where(gte(trades.timestamp, since24h));

    const byMarket = new Map<
      string,
      { last5m: number; last5mIds: string[]; total24h: number }
    >();
    for (const t of recent) {
      const bucket = byMarket.get(t.marketId) ?? {
        last5m: 0,
        last5mIds: [],
        total24h: 0,
      };
      bucket.total24h += t.amount ?? 0;
      if (t.timestamp >= since5m) {
        bucket.last5m += t.amount ?? 0;
        bucket.last5mIds.push(t.id);
      }
      byMarket.set(t.marketId, bucket);
    }

    const windowsPerDay = (24 * 60) / 5; // 288
    const multiplier = ANOMALY_THRESHOLDS.volumeSpikeMultiplier;

    for (const [marketId, { last5m, last5mIds, total24h }] of byMarket) {
      if (last5m <= 0) continue;
      const avg5m = total24h / windowsPerDay;
      if (avg5m <= 0) continue;
      const ratio = last5m / avg5m;
      if (ratio < multiplier) continue;

      // Score scales with how many multiples above the threshold we are.
      const rawScore = (ratio - multiplier) / (multiplier * 3);
      const score = clamp(0.4 + rawScore, 0, 1);

      results.push({
        marketId,
        type: 'volume_spike',
        severity: severityFromScore(score),
        score,
        description: `Volume spike: last 5m volume $${last5m.toFixed(
          0
        )} vs 24h avg $${avg5m.toFixed(0)} (${ratio.toFixed(1)}x)`,
        details: { last5m, avg5m, ratio, windowMinutes: 5 },
        relatedTradeIds: last5mIds.slice(0, 50),
      });
    }
  } catch (err) {
    console.error('[anomaly] detectVolumeSpikes failed:', err);
  }

  return results;
}

/**
 * Detect whale trades. For each market: flag trades above the 95th
 * percentile of recent trades on that market. Additionally, any trade
 * over $10k USD is flagged regardless of percentile.
 */
export async function detectWhaleTrades(): Promise<DetectedAnomaly[]> {
  const db = getDb();
  const results: DetectedAnomaly[] = [];

  try {
    const since = Date.now() - DAY;
    const recent = await db
      .select({
        id: trades.id,
        marketId: trades.marketId,
        amount: trades.amount,
        traderAddress: trades.traderAddress,
        timestamp: trades.timestamp,
      })
      .from(trades)
      .where(gte(trades.timestamp, since));

    const byMarket = new Map<string, typeof recent>();
    for (const t of recent) {
      const arr = byMarket.get(t.marketId) ?? [];
      arr.push(t);
      byMarket.set(t.marketId, arr);
    }

    const p = ANOMALY_THRESHOLDS.whalePercentile;

    for (const [marketId, marketTrades] of byMarket) {
      const amounts = marketTrades
        .map((t) => t.amount ?? 0)
        .filter((a) => a > 0);
      if (amounts.length === 0) continue;

      const threshold =
        amounts.length >= 20 ? percentile(amounts, p) : Infinity;

      for (const t of marketTrades) {
        const amt = t.amount ?? 0;
        const isPercentileWhale = amt >= threshold && amt > 0;
        const isAbsoluteWhale = amt >= 10_000;
        if (!isPercentileWhale && !isAbsoluteWhale) continue;

        // Larger trade -> higher score. Anchor: $10k -> ~0.6, $100k -> ~0.9.
        const logScaled = Math.log10(Math.max(amt, 1)) / 6; // 1 -> 0, 1e6 -> 1
        const score = clamp(logScaled, 0.3, 1);

        results.push({
          marketId,
          type: 'whale_trade',
          severity: severityFromScore(score),
          score,
          description: `Whale trade: $${amt.toFixed(0)}${
            isAbsoluteWhale ? ' (over $10k threshold)' : ` (>P${p})`
          }`,
          details: {
            amount: amt,
            percentileThreshold:
              threshold === Infinity ? null : threshold,
            isAbsoluteWhale,
          },
          relatedTradeIds: [t.id],
          relatedAccountId: t.traderAddress ?? undefined,
        });
      }
    }
  } catch (err) {
    console.error('[anomaly] detectWhaleTrades failed:', err);
  }

  return results;
}

/**
 * Detect trades that moved the price by > priceImpactThreshold (5%) in a
 * single trade, measured against the prior trade on the same market.
 */
export async function detectPriceImpact(): Promise<DetectedAnomaly[]> {
  const db = getDb();
  const results: DetectedAnomaly[] = [];

  try {
    const since = Date.now() - DAY;
    const recent = await db
      .select({
        id: trades.id,
        marketId: trades.marketId,
        price: trades.price,
        timestamp: trades.timestamp,
        traderAddress: trades.traderAddress,
      })
      .from(trades)
      .where(gte(trades.timestamp, since));

    const byMarket = new Map<string, typeof recent>();
    for (const t of recent) {
      const arr = byMarket.get(t.marketId) ?? [];
      arr.push(t);
      byMarket.set(t.marketId, arr);
    }

    const threshold = ANOMALY_THRESHOLDS.priceImpactThreshold;

    for (const [marketId, marketTrades] of byMarket) {
      marketTrades.sort((a, b) => a.timestamp - b.timestamp);
      for (let i = 1; i < marketTrades.length; i++) {
        const prev = marketTrades[i - 1];
        const curr = marketTrades[i];
        if (prev.price == null || curr.price == null) continue;
        const delta = Math.abs(curr.price - prev.price);
        if (delta < threshold) continue;

        // Score scales with how much bigger than threshold the move is.
        const score = clamp(delta * 5, 0.3, 1);

        results.push({
          marketId,
          type: 'price_impact',
          severity: severityFromScore(score),
          score,
          description: `Price moved ${(delta * 100).toFixed(
            1
          )}% in a single trade (${(prev.price * 100).toFixed(
            1
          )}% -> ${(curr.price * 100).toFixed(1)}%)`,
          details: {
            previousPrice: prev.price,
            newPrice: curr.price,
            delta,
            previousTradeId: prev.id,
          },
          relatedTradeIds: [curr.id],
          relatedAccountId: curr.traderAddress ?? undefined,
        });
      }
    }
  } catch (err) {
    console.error('[anomaly] detectPriceImpact failed:', err);
  }

  return results;
}

/**
 * Detect burst trading: >=10 trades in 60 seconds on the same market,
 * all on the same side (BUY YES or SELL YES/NO etc.).
 */
export async function detectBurstTrading(): Promise<DetectedAnomaly[]> {
  const db = getDb();
  const results: DetectedAnomaly[] = [];

  try {
    const since = Date.now() - DAY;
    const recent = await db
      .select({
        id: trades.id,
        marketId: trades.marketId,
        side: trades.side,
        outcome: trades.outcome,
        timestamp: trades.timestamp,
        traderAddress: trades.traderAddress,
      })
      .from(trades)
      .where(gte(trades.timestamp, since));

    const byMarketSide = new Map<string, typeof recent>();
    for (const t of recent) {
      const key = `${t.marketId}::${t.side}::${t.outcome}`;
      const arr = byMarketSide.get(key) ?? [];
      arr.push(t);
      byMarketSide.set(key, arr);
    }

    const minCount = ANOMALY_THRESHOLDS.burstTradeCount;
    const windowMs = ANOMALY_THRESHOLDS.burstWindowSeconds * 1000;

    const reportedKeys = new Set<string>();

    for (const [key, list] of byMarketSide) {
      if (list.length < minCount) continue;
      list.sort((a, b) => a.timestamp - b.timestamp);

      // Sliding window: find any window of `windowMs` containing >= minCount.
      let l = 0;
      for (let r = 0; r < list.length; r++) {
        while (list[r].timestamp - list[l].timestamp > windowMs) l++;
        const count = r - l + 1;
        if (count >= minCount) {
          const bucketKey = `${key}::${Math.floor(
            list[l].timestamp / windowMs
          )}`;
          if (reportedKeys.has(bucketKey)) continue;
          reportedKeys.add(bucketKey);

          const window = list.slice(l, r + 1);
          const score = clamp(0.4 + (count - minCount) / 30, 0.4, 1);
          const accounts = new Set(
            window.map((t) => t.traderAddress).filter(Boolean)
          );

          results.push({
            marketId: window[0].marketId,
            type: 'burst_trading',
            severity: severityFromScore(score),
            score,
            description: `Burst trading: ${count} ${window[0].side} ${window[0].outcome} trades in ${ANOMALY_THRESHOLDS.burstWindowSeconds}s`,
            details: {
              count,
              side: window[0].side,
              outcome: window[0].outcome,
              windowSeconds: ANOMALY_THRESHOLDS.burstWindowSeconds,
              startTimestamp: window[0].timestamp,
              endTimestamp: window[window.length - 1].timestamp,
              uniqueAccounts: accounts.size,
            },
            relatedTradeIds: window.map((t) => t.id).slice(0, 50),
            relatedAccountId:
              accounts.size === 1
                ? (window.find((t) => t.traderAddress)?.traderAddress ??
                  undefined)
                : undefined,
          });
        }
      }
    }
  } catch (err) {
    console.error('[anomaly] detectBurstTrading failed:', err);
  }

  return results;
}

/**
 * Detect price divergence between matched markets on different platforms.
 * Flag when two markets in the same matchGroup have prices that differ by
 * more than 10% and both have been updated within the last 5 minutes.
 */
export async function detectPriceDivergence(): Promise<DetectedAnomaly[]> {
  const db = getDb();
  const results: DetectedAnomaly[] = [];

  try {
    const since = Date.now() - 5 * MINUTE;
    const rows = await db
      .select({
        id: markets.id,
        platform: markets.platform,
        title: markets.title,
        yesPrice: markets.yesPrice,
        matchGroupId: markets.matchGroupId,
        updatedAt: markets.updatedAt,
      })
      .from(markets)
      .where(
        and(eq(markets.status, 'active'), isNotNull(markets.matchGroupId))
      );

    const byGroup = new Map<string, typeof rows>();
    for (const r of rows) {
      if (!r.matchGroupId || r.yesPrice == null) continue;
      if (r.updatedAt < since) continue;
      const arr = byGroup.get(r.matchGroupId) ?? [];
      arr.push(r);
      byGroup.set(r.matchGroupId, arr);
    }

    for (const [, group] of byGroup) {
      if (group.length < 2) continue;
      const prices = group.map((g) => g.yesPrice as number);
      const min = Math.min(...prices);
      const max = Math.max(...prices);
      const divergence = max - min;
      if (divergence <= 0.10) continue;

      const score = clamp(divergence * 3, 0.3, 1);
      const platformPrices: Record<string, number> = {};
      for (const g of group) {
        platformPrices[g.platform] = g.yesPrice as number;
      }

      // Report the anomaly on each market in the group so it surfaces
      // regardless of which platform the viewer browses.
      for (const g of group) {
        results.push({
          marketId: g.id,
          type: 'price_divergence',
          severity: severityFromScore(score),
          score,
          description: `Price divergence of ${(divergence * 100).toFixed(
            1
          )}% across ${group.length} matched markets`,
          details: {
            matchGroupId: g.matchGroupId,
            divergence,
            min,
            max,
            platformPrices,
          },
        });
      }
    }
  } catch (err) {
    console.error('[anomaly] detectPriceDivergence failed:', err);
  }

  return results;
}

/**
 * Run all anomaly detection rules and return a combined list.
 */
export async function detectAnomalies(): Promise<DetectedAnomaly[]> {
  const all: DetectedAnomaly[] = [];

  try {
    const [volume, whale, impact, burst, divergence] = await Promise.all([
      detectVolumeSpikes(),
      detectWhaleTrades(),
      detectPriceImpact(),
      detectBurstTrading(),
      detectPriceDivergence(),
    ]);
    all.push(...volume, ...whale, ...impact, ...burst, ...divergence);
  } catch (err) {
    console.error('[anomaly] detectAnomalies failed:', err);
  }

  return all;
}

/**
 * Persist detected anomalies into the anomalies table, and flag the
 * corresponding trades as anomalous.
 */
export async function persistAnomalies(
  detected: DetectedAnomaly[]
): Promise<void> {
  if (detected.length === 0) return;
  const db = getDb();
  const now = Date.now();

  try {
    for (const a of detected) {
      try {
        await db.insert(anomalies).values({
          marketId: a.marketId,
          type: a.type,
          severity: a.severity,
          score: a.score,
          description: a.description,
          details: a.details as unknown as Record<string, unknown>,
          relatedTradeIds: a.relatedTradeIds ?? [],
          relatedAccountId: a.relatedAccountId ?? null,
          detectedAt: now,
          acknowledged: false,
        });
      } catch (err) {
        console.error(
          `[anomaly] Failed to insert anomaly for market ${a.marketId}:`,
          err
        );
      }

      if (a.relatedTradeIds && a.relatedTradeIds.length > 0) {
        try {
          await db
            .update(trades)
            .set({
              isAnomalous: true,
              anomalyType: a.type,
              anomalyScore: a.score,
            })
            .where(inArray(trades.id, a.relatedTradeIds));
        } catch (err) {
          console.error(
            `[anomaly] Failed to flag trades anomalous for ${a.type}:`,
            err
          );
        }
      }
    }
  } catch (err) {
    console.error('[anomaly] persistAnomalies failed:', err);
    throw err;
  }
}

