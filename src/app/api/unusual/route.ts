import { NextRequest, NextResponse } from 'next/server';
import { and, desc, eq, type SQL } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { anomalies, markets } from '@/lib/db/schema';

type AnomalyRow = typeof anomalies.$inferSelect;

const VALID_TYPES: ReadonlySet<string> = new Set([
  'volume_spike',
  'price_impact',
  'whale_trade',
  'burst_trading',
  'price_divergence',
]);

const VALID_SEVERITIES: ReadonlySet<string> = new Set([
  'low',
  'medium',
  'high',
  'critical',
]);

function safeParseJson<T>(value: unknown): T | null {
  if (value == null) return null;
  if (typeof value !== 'string') return value as T;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;

    const type = searchParams.get('type');
    const severity = searchParams.get('severity');
    const limitParam = searchParams.get('limit');

    let limit = 50;
    if (limitParam) {
      const parsed = parseInt(limitParam, 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        limit = Math.min(parsed, 500);
      }
    }

    const conditions: SQL[] = [];

    if (type && VALID_TYPES.has(type)) {
      conditions.push(eq(anomalies.type, type));
    }

    if (severity && VALID_SEVERITIES.has(severity)) {
      conditions.push(eq(anomalies.severity, severity));
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
        id: anomalies.id,
        marketId: anomalies.marketId,
        type: anomalies.type,
        severity: anomalies.severity,
        score: anomalies.score,
        description: anomalies.description,
        details: anomalies.details,
        relatedTradeIds: anomalies.relatedTradeIds,
        relatedAccountId: anomalies.relatedAccountId,
        detectedAt: anomalies.detectedAt,
        acknowledged: anomalies.acknowledged,
        marketTitle: markets.title,
        marketPlatform: markets.platform,
      })
      .from(anomalies)
      .leftJoin(markets, eq(anomalies.marketId, markets.id));

    const rows = whereExpr
      ? await baseQuery
          .where(whereExpr)
          .orderBy(desc(anomalies.detectedAt))
          .limit(limit)
      : await baseQuery.orderBy(desc(anomalies.detectedAt)).limit(limit);

    const serialized = rows.map((r) => ({
      ...r,
      details: safeParseJson<Record<string, unknown>>(
        r.details as AnomalyRow['details'],
      ),
      relatedTradeIds: safeParseJson<string[]>(
        r.relatedTradeIds as AnomalyRow['relatedTradeIds'],
      ),
    }));

    return NextResponse.json({
      anomalies: serialized,
      total: serialized.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/unusual] Failed:', error);
    return NextResponse.json(
      { error: message, anomalies: [], total: 0 },
      { status: 500 },
    );
  }
}
