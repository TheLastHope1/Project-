import { NextRequest, NextResponse } from 'next/server';
import { desc, eq, type SQL } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { newsItems } from '@/lib/db/schema';

type NewsRow = typeof newsItems.$inferSelect;

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

    const source = searchParams.get('source');
    const limitParam = searchParams.get('limit');

    let limit = 50;
    if (limitParam) {
      const parsed = parseInt(limitParam, 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        limit = Math.min(parsed, 500);
      }
    }

    const conditions: SQL[] = [];
    if (source && source.trim().length > 0) {
      conditions.push(eq(newsItems.source, source.trim()));
    }

    const db = getDb();

    const rows =
      conditions.length > 0
        ? await db
            .select()
            .from(newsItems)
            .where(conditions[0])
            .orderBy(desc(newsItems.publishedAt))
            .limit(limit)
        : await db
            .select()
            .from(newsItems)
            .orderBy(desc(newsItems.publishedAt))
            .limit(limit);

    const serialized = rows.map((r: NewsRow) => ({
      ...r,
      relatedMarketIds: safeParseJson<string[]>(r.relatedMarketIds),
      keywords: safeParseJson<string[]>(r.keywords),
    }));

    return NextResponse.json({
      news: serialized,
      total: serialized.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/news] Failed:', error);
    return NextResponse.json(
      { error: message, news: [], total: 0 },
      { status: 500 },
    );
  }
}
