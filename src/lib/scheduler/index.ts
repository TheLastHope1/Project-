import cron, { type ScheduledTask } from 'node-cron';
import { getDb } from '@/lib/db';
import { markets, priceSnapshots, trades } from '@/lib/db/schema';
import { eq, desc } from 'drizzle-orm';
import { fetchAllMarkets, fetchAllTrades } from '@/lib/platforms';
import type { Platform, NormalizedTrade } from '@/lib/platforms/types';
import { runMarketMatching } from '@/lib/matching/market-matcher';
import {
  findArbitrageOpportunities,
  persistArbitrageOpportunities,
} from '@/lib/analysis/arbitrage';
import { detectAnomalies, persistAnomalies } from '@/lib/analysis/anomaly';
import { analyzeAccounts, persistAccountMetrics } from '@/lib/analysis/insider';
import { aggregateNews } from '@/lib/news/aggregator';

type FetchTimes = {
  prices: Date | null;
  trades: Date | null;
  fullRefresh: Date | null;
  news: Date | null;
  insider: Date | null;
};

const lastFetch: FetchTimes = {
  prices: null,
  trades: null,
  fullRefresh: null,
  news: null,
  insider: null,
};

const tasks: ScheduledTask[] = [];
let started = false;

function unixSeconds(date: Date | null | undefined): number | null {
  if (!date) return null;
  return Math.floor(date.getTime() / 1000);
}

function toTradeRecord(trade: NormalizedTrade, marketId: string) {
  return {
    id: `${trade.platform}_${trade.platformTradeId}`,
    platform: trade.platform,
    marketId,
    platformTradeId: trade.platformTradeId,
    side: trade.side,
    outcome: trade.outcome,
    price: trade.price,
    size: trade.size,
    amount: trade.amount,
    traderAddress: trade.traderAddress ?? null,
    traderUsername: trade.traderUsername ?? null,
    timestamp: Math.floor(trade.timestamp.getTime() / 1000),
    transactionHash: trade.transactionHash ?? null,
    isAnomalous: false,
    anomalyType: null,
    anomalyScore: null,
  };
}

export async function refreshMarkets(): Promise<void> {
  try {
    console.log('[scheduler] Refreshing markets...');
    const db = getDb();
    const nowSec = Math.floor(Date.now() / 1000);
    const fetched = await fetchAllMarkets();
    console.log(`[scheduler] Fetched ${fetched.length} markets`);

    for (const m of fetched) {
      const id = `${m.platform}_${m.platformMarketId}`;
      try {
        const updateSet = {
          title: m.title,
          description: m.description ?? null,
          category: m.category ?? null,
          yesPrice: m.yesPrice,
          noPrice: m.noPrice,
          lastTradePrice: m.lastTradePrice,
          volume: m.volume,
          volume24h: m.volume24h,
          liquidity: m.liquidity,
          status: m.status,
          resolution: m.resolution ?? null,
          closeDate: unixSeconds(m.closeDate),
          outcomes: (m.outcomes ?? []) as unknown as string,
          outcomePrices: (m.outcomePrices ?? []) as unknown as string,
          tokenIds: (m.tokenIds ?? null) as unknown as string | null,
          updatedAt: nowSec,
        };

        await db
          .insert(markets)
          .values({
            id,
            platform: m.platform,
            platformMarketId: m.platformMarketId,
            url: m.url,
            imageUrl: m.imageUrl ?? null,
            createdAt: nowSec,
            ...updateSet,
          })
          .onConflictDoUpdate({
            target: markets.id,
            set: updateSet,
          });

        if (m.yesPrice !== null) {
          await db.insert(priceSnapshots).values({
            marketId: id,
            yesPrice: m.yesPrice,
            volume: m.volume,
            timestamp: nowSec,
          });
        }
      } catch (err) {
        console.error(`[scheduler] Failed to upsert ${id}:`, err);
      }
    }

    lastFetch.prices = new Date();
    console.log('[scheduler] Markets refreshed');
  } catch (err) {
    console.error('[scheduler] refreshMarkets failed:', err);
  }
}

export async function refreshTrades(): Promise<void> {
  try {
    console.log('[scheduler] Refreshing trades...');
    const db = getDb();

    const activeMarkets = await db
      .select({
        id: markets.id,
        platform: markets.platform,
        platformMarketId: markets.platformMarketId,
      })
      .from(markets)
      .where(eq(markets.platform, 'manifold'))
      .orderBy(desc(markets.volume24h))
      .limit(30);

    let totalInserted = 0;
    for (const m of activeMarkets) {
      try {
        const fetched = await fetchAllTrades(m.platformMarketId, m.platform as Platform);
        for (const t of fetched) {
          try {
            await db
              .insert(trades)
              .values(toTradeRecord(t, m.id))
              .onConflictDoNothing();
            totalInserted++;
          } catch {
            // duplicate
          }
        }
      } catch {
        // per-market errors
      }
    }

    lastFetch.trades = new Date();
    console.log(`[scheduler] Trades refreshed (${totalInserted} new)`);
  } catch (err) {
    console.error('[scheduler] refreshTrades failed:', err);
  }
}

export async function runAnalysis(): Promise<void> {
  try {
    console.log('[scheduler] Running anomaly detection...');
    const anomalies = await detectAnomalies();
    await persistAnomalies(anomalies);
    console.log(`[scheduler] Found ${anomalies.length} anomalies`);

    console.log('[scheduler] Running arbitrage detection...');
    const opps = await findArbitrageOpportunities(0.02);
    await persistArbitrageOpportunities(opps);
    console.log(`[scheduler] Found ${opps.length} arbitrage opportunities`);
  } catch (err) {
    console.error('[scheduler] runAnalysis failed:', err);
  }
}

export async function runFullRefresh(): Promise<void> {
  try {
    console.log('[scheduler] Running full refresh + matching...');
    await refreshMarkets();
    const result = await runMarketMatching();
    console.log(
      `[scheduler] Matching complete: ${result.groupsCreated} groups, ${result.marketsMatched} markets matched`,
    );
    lastFetch.fullRefresh = new Date();
  } catch (err) {
    console.error('[scheduler] runFullRefresh failed:', err);
  }
}

export async function refreshNews(): Promise<void> {
  try {
    console.log('[scheduler] Aggregating news...');
    const result = await aggregateNews();
    console.log(`[scheduler] News: ${result.fetched} fetched, ${result.stored} stored`);
    lastFetch.news = new Date();
  } catch (err) {
    console.error('[scheduler] refreshNews failed:', err);
  }
}

export async function refreshInsider(): Promise<void> {
  try {
    console.log('[scheduler] Analyzing accounts...');
    const metrics = await analyzeAccounts();
    await persistAccountMetrics(metrics);
    console.log(`[scheduler] Analyzed ${metrics.length} accounts`);
    lastFetch.insider = new Date();
  } catch (err) {
    console.error('[scheduler] refreshInsider failed:', err);
  }
}

export function startScheduler() {
  if (started) return;
  started = true;

  console.log('[scheduler] Starting background scheduler...');

  tasks.push(
    cron.schedule('* * * * *', async () => {
      await refreshMarkets();
    }),
  );

  tasks.push(
    cron.schedule('*/2 * * * *', async () => {
      await refreshTrades();
      await runAnalysis();
    }),
  );

  tasks.push(
    cron.schedule('*/5 * * * *', async () => {
      await runFullRefresh();
    }),
  );

  tasks.push(
    cron.schedule('*/10 * * * *', async () => {
      await refreshNews();
    }),
  );

  tasks.push(
    cron.schedule('*/15 * * * *', async () => {
      await refreshInsider();
    }),
  );

  // Initial kickoff
  void (async () => {
    try {
      await refreshMarkets();
      await runMarketMatching();
      lastFetch.fullRefresh = new Date();
      await refreshNews();
    } catch (err) {
      console.error('[scheduler] Initial kickoff failed:', err);
    }
  })();
}

export function stopScheduler() {
  tasks.forEach((t) => t.stop());
  tasks.length = 0;
  started = false;
}

export function getLastFetchTimes(): FetchTimes {
  return { ...lastFetch };
}
