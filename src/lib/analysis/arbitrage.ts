import { and, eq, isNotNull, inArray } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, arbitrageOpportunities } from '@/lib/db/schema';

export interface ArbitrageResult {
  matchGroupId: string;
  marketAId: string;
  marketBId: string;
  marketATitle: string;
  marketBTitle: string;
  platformA: string;
  platformB: string;
  marketAYesPrice: number;
  marketBYesPrice: number;
  spread: number;
  spreadPercent: number;
  estimatedProfit: number; // for $100 stake
  type: 'cross_platform' | 'within_platform';
}

const PLATFORM_FEES: Record<string, number> = {
  polymarket: 0.02,
  manifold: 0,
  kalshi: 0.01,
  predictit: 0.10,
};

function getFee(platform: string): number {
  return PLATFORM_FEES[platform] ?? 0;
}

/**
 * Find arbitrage opportunities across matched markets.
 * minSpread is expressed as a fraction of $1 (so 0.02 = 2%).
 */
export async function findArbitrageOpportunities(
  minSpread = 0.02
): Promise<ArbitrageResult[]> {
  const db = getDb();

  try {
    const rows = await db
      .select({
        id: markets.id,
        platform: markets.platform,
        title: markets.title,
        yesPrice: markets.yesPrice,
        matchGroupId: markets.matchGroupId,
      })
      .from(markets)
      .where(
        and(eq(markets.status, 'active'), isNotNull(markets.matchGroupId))
      );

    // Group markets by matchGroupId.
    const byGroup = new Map<string, typeof rows>();
    for (const r of rows) {
      if (!r.matchGroupId) continue;
      if (r.yesPrice == null) continue;
      const list = byGroup.get(r.matchGroupId) ?? [];
      list.push(r);
      byGroup.set(r.matchGroupId, list);
    }

    const results: ArbitrageResult[] = [];

    for (const [groupId, group] of byGroup) {
      if (group.length < 2) continue;

      for (let i = 0; i < group.length; i++) {
        for (let j = 0; j < group.length; j++) {
          if (i === j) continue;
          const a = group[i];
          const b = group[j];

          if (a.platform === b.platform) continue; // cross-platform only

          const yesA = a.yesPrice as number;
          const yesB = b.yesPrice as number;

          // Strategy: Buy YES on A at price yesA, buy NO on B at price (1 - yesB).
          // Total cost to guarantee $1 payout: cost = yesA + (1 - yesB).
          const cost = yesA + (1 - yesB);
          if (cost >= 1.0) continue;
          const grossProfit = 1.0 - cost;

          const feeA = getFee(a.platform);
          const feeB = getFee(b.platform);
          // Fees are applied on the notional spent on each leg.
          const netProfit =
            grossProfit - feeA * yesA - feeB * (1 - yesB);

          if (netProfit < minSpread) continue;

          // For a $100 stake, the profit scales linearly with 1/cost since
          // cost dollars buy $1 of guaranteed payout.
          const estimatedProfit = (netProfit / cost) * 100;

          results.push({
            matchGroupId: groupId,
            marketAId: a.id,
            marketBId: b.id,
            marketATitle: a.title,
            marketBTitle: b.title,
            platformA: a.platform,
            platformB: b.platform,
            marketAYesPrice: yesA,
            marketBYesPrice: yesB,
            spread: netProfit,
            spreadPercent: netProfit * 100,
            estimatedProfit,
            type: 'cross_platform',
          });
        }
      }
    }

    results.sort((x, y) => y.spread - x.spread);
    return results;
  } catch (err) {
    console.error('[arbitrage] findArbitrageOpportunities failed:', err);
    throw err;
  }
}

/**
 * Upsert current arbitrage opportunities. Any previously active opportunity
 * that does not appear in the new set is marked as expired.
 */
export async function persistArbitrageOpportunities(
  opps: ArbitrageResult[]
): Promise<void> {
  const db = getDb();
  const now = Date.now();

  try {
    // Load existing active opportunities.
    const existing = await db
      .select()
      .from(arbitrageOpportunities)
      .where(eq(arbitrageOpportunities.status, 'active'));

    const keyOf = (marketAId: string, marketBId: string) =>
      `${marketAId}::${marketBId}`;

    const freshKeys = new Set(opps.map((o) => keyOf(o.marketAId, o.marketBId)));
    const existingByKey = new Map<string, (typeof existing)[number]>();
    for (const e of existing) {
      existingByKey.set(keyOf(e.marketAId, e.marketBId), e);
    }

    // Upsert / insert new opportunities.
    for (const opp of opps) {
      const key = keyOf(opp.marketAId, opp.marketBId);
      const prior = existingByKey.get(key);
      const values = {
        matchGroupId: opp.matchGroupId,
        marketAId: opp.marketAId,
        marketBId: opp.marketBId,
        marketAYesPrice: opp.marketAYesPrice,
        marketBNoPrice: 1 - opp.marketBYesPrice,
        spread: opp.spread,
        spreadPercent: opp.spreadPercent,
        estimatedProfit: opp.estimatedProfit,
        type: opp.type,
        status: 'active' as const,
        detectedAt: prior?.detectedAt ?? now,
        expiredAt: null as number | null,
      };

      try {
        if (prior) {
          await db
            .update(arbitrageOpportunities)
            .set(values)
            .where(eq(arbitrageOpportunities.id, prior.id));
        } else {
          await db.insert(arbitrageOpportunities).values(values);
        }
      } catch (err) {
        console.error(
          `[arbitrage] Failed to upsert opportunity ${key}:`,
          err
        );
      }
    }

    // Expire stale opportunities.
    const staleIds: number[] = [];
    for (const e of existing) {
      if (!freshKeys.has(keyOf(e.marketAId, e.marketBId))) {
        staleIds.push(e.id);
      }
    }

    if (staleIds.length > 0) {
      try {
        await db
          .update(arbitrageOpportunities)
          .set({ status: 'expired', expiredAt: now })
          .where(inArray(arbitrageOpportunities.id, staleIds));
      } catch (err) {
        console.error('[arbitrage] Failed to expire stale opportunities:', err);
      }
    }
  } catch (err) {
    console.error('[arbitrage] persistArbitrageOpportunities failed:', err);
    throw err;
  }
}
