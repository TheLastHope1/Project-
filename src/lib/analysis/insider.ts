import { and, eq } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, trades, trackedAccounts } from '@/lib/db/schema';
import { clamp, mean } from '@/lib/utils/math';

export interface AccountMetrics {
  platform: string;
  accountId: string;
  username?: string;
  totalTrades: number;
  profitableTrades: number;
  accuracy: number;
  totalPnl: number;
  avgTimingAdvantage: number;
  earlyMoverCount: number;
  suspicionScore: number;
  isWhale: boolean;
}

const MIN_TRADES = 10;
const WHALE_THRESHOLD_USD = 10_000;
const EARLY_MOVER_FRACTION = 0.05; // first 5%
const PRICE_MOVE_THRESHOLD = 0.10; // 10% move used for timing advantage

interface TradeRow {
  id: string;
  platform: string;
  marketId: string;
  side: string;
  outcome: string;
  price: number;
  size: number;
  amount: number;
  traderAddress: string | null;
  traderUsername: string | null;
  timestamp: number;
}

interface MarketRow {
  id: string;
  status: 'active' | 'closed' | 'resolved';
  resolution: string | null;
  yesPrice: number | null;
  lastTradePrice: number | null;
}

/**
 * Decide whether a given trade was profitable based on the market's
 * resolution. Returns { decided, profitable, pnl } where `decided` is
 * false for unresolved/ambiguous markets.
 */
function evaluateTradePnl(
  trade: TradeRow,
  market: MarketRow | undefined
): { decided: boolean; profitable: boolean; pnl: number } {
  if (!market || market.status !== 'resolved' || !market.resolution) {
    return { decided: false, profitable: false, pnl: 0 };
  }

  const resolvedYes =
    market.resolution.toLowerCase() === 'yes' ||
    market.resolution === '1' ||
    market.resolution.toLowerCase() === 'true';
  const resolvedNo =
    market.resolution.toLowerCase() === 'no' ||
    market.resolution === '0' ||
    market.resolution.toLowerCase() === 'false';

  if (!resolvedYes && !resolvedNo) {
    return { decided: false, profitable: false, pnl: 0 };
  }

  const outcome = trade.outcome.toLowerCase();
  const side = trade.side.toUpperCase();
  const bettingYes =
    (outcome === 'yes' && side === 'BUY') ||
    (outcome === 'no' && side === 'SELL');
  const bettingNo =
    (outcome === 'no' && side === 'BUY') ||
    (outcome === 'yes' && side === 'SELL');

  const won =
    (resolvedYes && bettingYes) || (resolvedNo && bettingNo);

  // Simple PnL: payout ($1 per share) * size - cost, or -cost if lost.
  const cost = trade.amount;
  const pnl = won ? trade.size - cost : -cost;

  return { decided: true, profitable: won, pnl };
}

/**
 * Analyze all accounts across all platforms. Returns metrics sorted by
 * suspicionScore descending.
 */
export async function analyzeAccounts(): Promise<AccountMetrics[]> {
  const db = getDb();

  try {
    const allTrades = (await db
      .select({
        id: trades.id,
        platform: trades.platform,
        marketId: trades.marketId,
        side: trades.side,
        outcome: trades.outcome,
        price: trades.price,
        size: trades.size,
        amount: trades.amount,
        traderAddress: trades.traderAddress,
        traderUsername: trades.traderUsername,
        timestamp: trades.timestamp,
      })
      .from(trades)) as TradeRow[];

    const allMarkets = (await db
      .select({
        id: markets.id,
        status: markets.status,
        resolution: markets.resolution,
        yesPrice: markets.yesPrice,
        lastTradePrice: markets.lastTradePrice,
      })
      .from(markets)) as MarketRow[];

    const marketById = new Map<string, MarketRow>();
    for (const m of allMarkets) marketById.set(m.id, m);

    // Group trades by market (sorted by timestamp) for early-mover detection
    // and timing-advantage computation.
    const tradesByMarket = new Map<string, TradeRow[]>();
    for (const t of allTrades) {
      const arr = tradesByMarket.get(t.marketId) ?? [];
      arr.push(t);
      tradesByMarket.set(t.marketId, arr);
    }
    for (const arr of tradesByMarket.values()) {
      arr.sort((a, b) => a.timestamp - b.timestamp);
    }

    // Group by (platform, accountId).
    const byAccount = new Map<string, TradeRow[]>();
    const keyOf = (platform: string, accountId: string) =>
      `${platform}::${accountId}`;

    for (const t of allTrades) {
      if (!t.traderAddress) continue;
      const k = keyOf(t.platform, t.traderAddress);
      const arr = byAccount.get(k) ?? [];
      arr.push(t);
      byAccount.set(k, arr);
    }

    const metrics: AccountMetrics[] = [];

    for (const [, accountTrades] of byAccount) {
      if (accountTrades.length < MIN_TRADES) continue;
      const first = accountTrades[0];
      const platform = first.platform;
      const accountId = first.traderAddress!;
      const username =
        accountTrades.find((t) => t.traderUsername)?.traderUsername ??
        undefined;

      let resolvedTrades = 0;
      let profitableTrades = 0;
      let totalPnl = 0;
      let earlyMoverCount = 0;
      const timingAdvantages: number[] = [];
      const tradePnls: number[] = [];
      let isWhale = false;

      for (const t of accountTrades) {
        if ((t.amount ?? 0) >= WHALE_THRESHOLD_USD) {
          isWhale = true;
        }

        const market = marketById.get(t.marketId);
        const evalResult = evaluateTradePnl(t, market);
        if (!evalResult.decided) continue;

        resolvedTrades++;
        totalPnl += evalResult.pnl;
        tradePnls.push(evalResult.pnl);

        if (evalResult.profitable) {
          profitableTrades++;

          // Early-mover: position within the first 5% of trades on this market.
          const marketTrades = tradesByMarket.get(t.marketId) ?? [];
          if (marketTrades.length > 0) {
            const idx = marketTrades.findIndex((x) => x.id === t.id);
            if (
              idx >= 0 &&
              idx < Math.max(1, Math.floor(marketTrades.length * EARLY_MOVER_FRACTION))
            ) {
              earlyMoverCount++;
            }
          }

          // Timing advantage: time between this trade and the first subsequent
          // >=10% price move in the direction of this trade.
          const direction =
            (t.outcome.toLowerCase() === 'yes' && t.side.toUpperCase() === 'BUY') ||
            (t.outcome.toLowerCase() === 'no' && t.side.toUpperCase() === 'SELL')
              ? 'up'
              : 'down';

          const subsequent = marketTrades.filter(
            (x) => x.timestamp > t.timestamp
          );
          const basePrice = t.price;
          let advantage: number | null = null;
          for (const s of subsequent) {
            const moved =
              direction === 'up'
                ? s.price - basePrice
                : basePrice - s.price;
            if (moved >= PRICE_MOVE_THRESHOLD) {
              advantage = (s.timestamp - t.timestamp) / 1000; // seconds
              break;
            }
          }
          if (advantage != null) timingAdvantages.push(advantage);
        }
      }

      const accuracy =
        resolvedTrades > 0 ? profitableTrades / resolvedTrades : 0;
      const avgTimingAdvantage =
        timingAdvantages.length > 0 ? mean(timingAdvantages) : 0;

      // Normalize timing: faster (lower seconds) is better. Map to [0,1]
      // using a reference window of 1 hour (3600s). Lower is more suspicious.
      const normalizedTiming =
        timingAdvantages.length > 0
          ? clamp(avgTimingAdvantage / 3600, 0, 1)
          : 1;

      const earlyMoverRatio =
        resolvedTrades > 0 ? earlyMoverCount / resolvedTrades : 0;

      // Profit consistency: fraction of resolved trades that were profitable
      // weighted by how positive total pnl is. Use a simple positive-ratio.
      const positivePnlTrades = tradePnls.filter((p) => p > 0).length;
      const profitConsistency =
        tradePnls.length > 0 ? positivePnlTrades / tradePnls.length : 0;

      const suspicionScore = clamp(
        0.3 * accuracy +
          0.3 * (1 - normalizedTiming) +
          0.25 * earlyMoverRatio +
          0.15 * profitConsistency,
        0,
        1
      );

      metrics.push({
        platform,
        accountId,
        username,
        totalTrades: accountTrades.length,
        profitableTrades,
        accuracy,
        totalPnl,
        avgTimingAdvantage,
        earlyMoverCount,
        suspicionScore,
        isWhale,
      });
    }

    metrics.sort((a, b) => b.suspicionScore - a.suspicionScore);
    return metrics;
  } catch (err) {
    console.error('[insider] analyzeAccounts failed:', err);
    throw err;
  }
}

/**
 * Upsert account metrics into the trackedAccounts table. Automatically
 * marks isTracked=true when suspicionScore > 0.7.
 */
export async function persistAccountMetrics(
  metrics: AccountMetrics[]
): Promise<void> {
  if (metrics.length === 0) return;
  const db = getDb();
  const now = Date.now();

  try {
    for (const m of metrics) {
      try {
        const existing = await db
          .select()
          .from(trackedAccounts)
          .where(
            and(
              eq(trackedAccounts.platform, m.platform),
              eq(trackedAccounts.accountId, m.accountId)
            )
          )
          .limit(1);

        const autoTrack = m.suspicionScore > 0.7;
        const values = {
          platform: m.platform,
          accountId: m.accountId,
          username: m.username ?? null,
          totalTrades: m.totalTrades,
          profitableTrades: m.profitableTrades,
          accuracy: m.accuracy,
          totalPnl: m.totalPnl,
          avgTimingAdvantage: m.avgTimingAdvantage,
          suspicionScore: m.suspicionScore,
          earlyMoverCount: m.earlyMoverCount,
          isWhale: m.isWhale,
          lastSeen: now,
          updatedAt: now,
        };

        if (existing.length > 0) {
          const prior = existing[0];
          await db
            .update(trackedAccounts)
            .set({
              ...values,
              // Preserve manual tracking flag: if already tracked manually,
              // keep it; otherwise apply automatic rule.
              isTracked: prior.isTracked || autoTrack,
            })
            .where(eq(trackedAccounts.id, prior.id));
        } else {
          await db.insert(trackedAccounts).values({
            ...values,
            isTracked: autoTrack,
            firstSeen: now,
          });
        }
      } catch (err) {
        console.error(
          `[insider] Failed to upsert account ${m.platform}:${m.accountId}:`,
          err
        );
      }
    }
  } catch (err) {
    console.error('[insider] persistAccountMetrics failed:', err);
    throw err;
  }
}

/**
 * Manually add an account to the tracked-accounts list. A no-op if the
 * account already exists (but ensures isTracked=true and updates username).
 */
export async function addManualAccount(
  platform: string,
  accountId: string,
  username?: string
): Promise<void> {
  const db = getDb();
  const now = Date.now();

  try {
    const existing = await db
      .select()
      .from(trackedAccounts)
      .where(
        and(
          eq(trackedAccounts.platform, platform),
          eq(trackedAccounts.accountId, accountId)
        )
      )
      .limit(1);

    if (existing.length > 0) {
      await db
        .update(trackedAccounts)
        .set({
          isTracked: true,
          username: username ?? existing[0].username,
          updatedAt: now,
        })
        .where(eq(trackedAccounts.id, existing[0].id));
      return;
    }

    await db.insert(trackedAccounts).values({
      platform,
      accountId,
      username: username ?? null,
      totalTrades: 0,
      profitableTrades: 0,
      accuracy: null,
      totalPnl: null,
      avgTimingAdvantage: null,
      suspicionScore: null,
      earlyMoverCount: 0,
      isWhale: false,
      isTracked: true,
      firstSeen: now,
      lastSeen: now,
      updatedAt: now,
    });
  } catch (err) {
    console.error(
      `[insider] addManualAccount failed for ${platform}:${accountId}:`,
      err
    );
    throw err;
  }
}
