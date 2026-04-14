import { NextRequest, NextResponse } from 'next/server';
import { and, asc, eq, gte } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, priceSnapshots } from '@/lib/db/schema';

type MarketRow = typeof markets.$inferSelect;

function safeParseJson<T>(value: unknown): T | null {
  if (value == null) return null;
  if (typeof value !== 'string') return value as T;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

function serializeMarket(row: MarketRow) {
  return {
    ...row,
    outcomes: safeParseJson<string[]>(row.outcomes),
    outcomePrices: safeParseJson<number[]>(row.outcomePrices),
    tokenIds: safeParseJson<string[]>(row.tokenIds),
  };
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;

    if (!id || typeof id !== 'string') {
      return NextResponse.json(
        { error: 'Invalid market id' },
        { status: 400 },
      );
    }

    const db = getDb();

    const rows = await db
      .select()
      .from(markets)
      .where(eq(markets.id, id))
      .limit(1);

    if (rows.length === 0) {
      return NextResponse.json(
        { error: 'Market not found' },
        { status: 404 },
      );
    }

    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;

    const snapshots = await db
      .select({
        timestamp: priceSnapshots.timestamp,
        yesPrice: priceSnapshots.yesPrice,
      })
      .from(priceSnapshots)
      .where(
        and(
          eq(priceSnapshots.marketId, id),
          gte(priceSnapshots.timestamp, sevenDaysAgo),
        ),
      )
      .orderBy(asc(priceSnapshots.timestamp));

    return NextResponse.json({
      market: serializeMarket(rows[0]),
      priceHistory: snapshots.map((s) => ({
        timestamp: s.timestamp,
        yesPrice: s.yesPrice,
      })),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/markets/[id]] Failed:', error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
