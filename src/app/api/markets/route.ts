import { NextRequest, NextResponse } from 'next/server';
import { and, asc, desc, eq, inArray, like, or, type SQL } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets } from '@/lib/db/schema';
import { getPlatformStatuses, type Platform } from '@/lib/platforms';

type MarketRow = typeof markets.$inferSelect;

const VALID_PLATFORMS: ReadonlySet<string> = new Set([
  'polymarket',
  'manifold',
  'kalshi',
  'predictit',
]);

const VALID_STATUSES: ReadonlySet<string> = new Set([
  'active',
  'closed',
  'resolved',
]);

const SORTABLE_COLUMNS = {
  volume: markets.volume,
  volume24h: markets.volume24h,
  liquidity: markets.liquidity,
  yesPrice: markets.yesPrice,
  updatedAt: markets.updatedAt,
  createdAt: markets.createdAt,
  closeDate: markets.closeDate,
  title: markets.title,
} as const;

type SortableKey = keyof typeof SORTABLE_COLUMNS;

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

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;

    const platformsParam = searchParams.get('platforms');
    const status = searchParams.get('status');
    const search = searchParams.get('search');
    const sortByParam = searchParams.get('sortBy') ?? 'volume';
    const sortOrder = (searchParams.get('sortOrder') ?? 'desc').toLowerCase();
    const limitParam = searchParams.get('limit');

    const sortBy = (sortByParam in SORTABLE_COLUMNS ? sortByParam : 'volume') as SortableKey;

    let limit = 500;
    if (limitParam) {
      const parsed = parseInt(limitParam, 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        limit = Math.min(parsed, 5000);
      }
    }

    const conditions: SQL[] = [];

    if (platformsParam) {
      const requested = platformsParam
        .split(',')
        .map((p) => p.trim().toLowerCase())
        .filter((p) => VALID_PLATFORMS.has(p)) as Platform[];
      if (requested.length > 0) {
        conditions.push(inArray(markets.platform, requested));
      }
    }

    if (status && VALID_STATUSES.has(status)) {
      conditions.push(
        eq(markets.status, status as 'active' | 'closed' | 'resolved'),
      );
    }

    if (search && search.trim().length > 0) {
      const needle = `%${search.trim()}%`;
      conditions.push(
        or(like(markets.title, needle), like(markets.description, needle))!,
      );
    }

    const sortColumn = SORTABLE_COLUMNS[sortBy];
    const orderExpr =
      sortOrder === 'asc' ? asc(sortColumn) : desc(sortColumn);

    const db = getDb();

    const whereExpr =
      conditions.length === 0
        ? undefined
        : conditions.length === 1
          ? conditions[0]
          : and(...conditions);

    const rows = whereExpr
      ? await db
          .select()
          .from(markets)
          .where(whereExpr)
          .orderBy(orderExpr)
          .limit(limit)
      : await db.select().from(markets).orderBy(orderExpr).limit(limit);

    const platformStatuses = getPlatformStatuses();

    return NextResponse.json({
      markets: rows.map(serializeMarket),
      total: rows.length,
      platformStatuses,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/markets] Failed:', error);
    return NextResponse.json(
      { error: message, markets: [], total: 0 },
      { status: 500 },
    );
  }
}
