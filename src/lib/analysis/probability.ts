import { and, desc, eq, gte, isNotNull } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, matchGroups, priceSnapshots } from '@/lib/db/schema';

export interface CalibrationPoint {
  bucket: string; // "0-10%", "10-20%", etc.
  predictedRange: [number, number];
  actualResolutionRate: number;
  sampleSize: number;
  platform: string;
}

export interface ProbabilityComparison {
  matchGroupId: string;
  canonicalTitle: string;
  prices: Record<string, number>; // platform -> yesPrice
  disagreement: number; // max - min
}

export interface ProbabilityTrend {
  marketId: string;
  title: string;
  platform: string;
  snapshots: Array<{ timestamp: number; yesPrice: number }>;
}

/**
 * Compute calibration curves per platform. For each resolved market, we
 * bucket its final predicted YES probability into deciles (0-10, 10-20,
 * ..., 90-100). For each bucket we compute the actual resolution rate
 * (fraction of markets in that bucket that resolved YES).
 */
export async function computeCalibration(): Promise<CalibrationPoint[]> {
  const db = getDb();

  try {
    const resolved = await db
      .select({
        platform: markets.platform,
        lastTradePrice: markets.lastTradePrice,
        yesPrice: markets.yesPrice,
        resolution: markets.resolution,
      })
      .from(markets)
      .where(
        and(
          eq(markets.status, 'resolved'),
          isNotNull(markets.resolution)
        )
      );

    const byPlatformBucket = new Map<
      string,
      { yes: number; total: number }
    >();

    for (const m of resolved) {
      const price = m.lastTradePrice ?? m.yesPrice;
      if (price == null) continue;
      if (!m.resolution) continue;

      const lower = m.resolution.toLowerCase();
      const resolvedYes =
        lower === 'yes' || lower === '1' || lower === 'true';
      const resolvedNo =
        lower === 'no' || lower === '0' || lower === 'false';
      if (!resolvedYes && !resolvedNo) continue;

      const bucketIdx = Math.min(9, Math.floor(price * 10));
      const key = `${m.platform}::${bucketIdx}`;
      const stats = byPlatformBucket.get(key) ?? { yes: 0, total: 0 };
      stats.total += 1;
      if (resolvedYes) stats.yes += 1;
      byPlatformBucket.set(key, stats);
    }

    const points: CalibrationPoint[] = [];
    for (const [key, { yes, total }] of byPlatformBucket) {
      const [platform, idxStr] = key.split('::');
      const idx = Number(idxStr);
      const low = idx * 10;
      const high = (idx + 1) * 10;
      points.push({
        bucket: `${low}-${high}%`,
        predictedRange: [low / 100, high / 100],
        actualResolutionRate: total > 0 ? yes / total : 0,
        sampleSize: total,
        platform,
      });
    }

    points.sort((a, b) => {
      if (a.platform !== b.platform) {
        return a.platform.localeCompare(b.platform);
      }
      return a.predictedRange[0] - b.predictedRange[0];
    });

    return points;
  } catch (err) {
    console.error('[probability] computeCalibration failed:', err);
    throw err;
  }
}

/**
 * Return the current YES price for each market in each matchGroup with
 * 2+ markets, plus the disagreement (max - min) across platforms.
 */
export async function computeCrossPlatformComparison(): Promise<
  ProbabilityComparison[]
> {
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

    const groups = await db.select().from(matchGroups);
    const groupById = new Map<string, (typeof groups)[number]>();
    for (const g of groups) groupById.set(g.id, g);

    const byGroup = new Map<string, typeof rows>();
    for (const r of rows) {
      if (!r.matchGroupId || r.yesPrice == null) continue;
      const arr = byGroup.get(r.matchGroupId) ?? [];
      arr.push(r);
      byGroup.set(r.matchGroupId, arr);
    }

    const results: ProbabilityComparison[] = [];
    for (const [groupId, members] of byGroup) {
      if (members.length < 2) continue;

      const prices: Record<string, number> = {};
      for (const m of members) {
        // If multiple markets share a platform in a group, prefer the one
        // whose price is closest to the group mean (last write wins otherwise).
        prices[m.platform] = m.yesPrice as number;
      }

      const values = Object.values(prices);
      if (values.length < 2) continue;
      const min = Math.min(...values);
      const max = Math.max(...values);

      const canonicalTitle =
        groupById.get(groupId)?.canonicalTitle ?? members[0].title;

      results.push({
        matchGroupId: groupId,
        canonicalTitle,
        prices,
        disagreement: max - min,
      });
    }

    results.sort((a, b) => b.disagreement - a.disagreement);
    return results;
  } catch (err) {
    console.error(
      '[probability] computeCrossPlatformComparison failed:',
      err
    );
    throw err;
  }
}

/**
 * Return a histogram of current YES prices across all active markets,
 * bucketed in 5% increments.
 */
export async function computeProbabilityDistribution(): Promise<
  { bucket: string; count: number }[]
> {
  const db = getDb();

  try {
    const rows = await db
      .select({ yesPrice: markets.yesPrice })
      .from(markets)
      .where(eq(markets.status, 'active'));

    const buckets: { bucket: string; count: number }[] = [];
    for (let i = 0; i < 20; i++) {
      const low = i * 5;
      const high = (i + 1) * 5;
      buckets.push({ bucket: `${low}-${high}%`, count: 0 });
    }

    for (const r of rows) {
      if (r.yesPrice == null) continue;
      const p = Math.max(0, Math.min(1, r.yesPrice));
      const idx = Math.min(19, Math.floor(p * 20));
      buckets[idx].count += 1;
    }

    return buckets;
  } catch (err) {
    console.error(
      '[probability] computeProbabilityDistribution failed:',
      err
    );
    throw err;
  }
}

/**
 * Return price snapshots for a market in the last `hours` hours.
 */
export async function getMarketPriceHistory(
  marketId: string,
  hours = 168
): Promise<ProbabilityTrend> {
  const db = getDb();

  try {
    const since = Date.now() - hours * 60 * 60 * 1000;

    const marketRows = await db
      .select({
        id: markets.id,
        title: markets.title,
        platform: markets.platform,
      })
      .from(markets)
      .where(eq(markets.id, marketId))
      .limit(1);

    if (marketRows.length === 0) {
      throw new Error(`Market not found: ${marketId}`);
    }
    const market = marketRows[0];

    const snaps = await db
      .select({
        timestamp: priceSnapshots.timestamp,
        yesPrice: priceSnapshots.yesPrice,
      })
      .from(priceSnapshots)
      .where(
        and(
          eq(priceSnapshots.marketId, marketId),
          gte(priceSnapshots.timestamp, since)
        )
      )
      .orderBy(desc(priceSnapshots.timestamp));

    const snapshots = snaps
      .filter((s) => s.yesPrice != null)
      .map((s) => ({
        timestamp: s.timestamp,
        yesPrice: s.yesPrice as number,
      }))
      .sort((a, b) => a.timestamp - b.timestamp);

    return {
      marketId: market.id,
      title: market.title,
      platform: market.platform,
      snapshots,
    };
  } catch (err) {
    console.error(
      `[probability] getMarketPriceHistory failed for ${marketId}:`,
      err
    );
    throw err;
  }
}
