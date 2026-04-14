import { NextRequest, NextResponse } from 'next/server';
import { and, desc, eq, type SQL } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, trades } from '@/lib/db/schema';
import type { Platform } from '@/lib/platforms';

const VALID_PLATFORMS: ReadonlySet<string> = new Set([
  'polymarket',
  'manifold',
  'kalshi',
  'predictit',
]);

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;

    const marketId = searchParams.get('marketId');
    const platform = searchParams.get('platform');
    const limitParam = searchParams.get('limit');
    const anomalousOnlyParam = searchParams.get('anomalousOnly');

    let limit = 100;
    if (limitParam) {
      const parsed = parseInt(limitParam, 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        limit = Math.min(parsed, 1000);
      }
    }

    const anomalousOnly =
      anomalousOnlyParam === 'true' || anomalousOnlyParam === '1';

    const conditions: SQL[] = [];

    if (marketId) {
      conditions.push(eq(trades.marketId, marketId));
    }

    if (platform && VALID_PLATFORMS.has(platform.toLowerCase())) {
      conditions.push(eq(trades.platform, platform.toLowerCase() as Platform));
    }

    if (anomalousOnly) {
      conditions.push(eq(trades.isAnomalous, true));
    }

    const whereExpr =
      conditions.length === 0
        ? undefined
        : conditions.length === 1
          ? conditions[0]
          : and(...conditions);

    const db = getDb();

    const baseQuery = db
      .select({
        id: trades.id,
        platform: trades.platform,
        marketId: trades.marketId,
        platformTradeId: trades.platformTradeId,
        side: trades.side,
        outcome: trades.outcome,
        price: trades.price,
        size: trades.size,
        amount: trades.amount,
        traderAddress: trades.traderAddress,
        traderUsername: trades.traderUsername,
        timestamp: trades.timestamp,
        transactionHash: trades.transactionHash,
        isAnomalous: trades.isAnomalous,
        anomalyType: trades.anomalyType,
        anomalyScore: trades.anomalyScore,
        marketTitle: markets.title,
      })
      .from(trades)
      .leftJoin(markets, eq(trades.marketId, markets.id));

    const rows = whereExpr
      ? await baseQuery
          .where(whereExpr)
          .orderBy(desc(trades.timestamp))
          .limit(limit)
      : await baseQuery.orderBy(desc(trades.timestamp)).limit(limit);

    return NextResponse.json({
      trades: rows,
      total: rows.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/trades] Failed:', error);
    return NextResponse.json(
      { error: message, trades: [], total: 0 },
      { status: 500 },
    );
  }
}
