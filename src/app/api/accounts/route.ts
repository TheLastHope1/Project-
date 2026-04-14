import { NextRequest, NextResponse } from 'next/server';
import { and, desc, eq, gte, type SQL } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { trackedAccounts } from '@/lib/db/schema';
import { addManualAccount } from '@/lib/analysis/insider';

const VALID_PLATFORMS: ReadonlySet<string> = new Set([
  'polymarket',
  'manifold',
  'kalshi',
  'predictit',
]);

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;

    const platform = searchParams.get('platform');
    const minSuspicionParam = searchParams.get('minSuspicion');
    const limitParam = searchParams.get('limit');

    let limit = 50;
    if (limitParam) {
      const parsed = parseInt(limitParam, 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        limit = Math.min(parsed, 500);
      }
    }

    const conditions: SQL[] = [];

    if (platform && VALID_PLATFORMS.has(platform.toLowerCase())) {
      conditions.push(eq(trackedAccounts.platform, platform.toLowerCase()));
    }

    if (minSuspicionParam) {
      const parsed = parseFloat(minSuspicionParam);
      if (!Number.isNaN(parsed)) {
        conditions.push(gte(trackedAccounts.suspicionScore, parsed));
      }
    }

    const whereExpr =
      conditions.length === 0
        ? undefined
        : conditions.length === 1
          ? conditions[0]
          : and(...conditions);

    const db = getDb();

    const rows = whereExpr
      ? await db
          .select()
          .from(trackedAccounts)
          .where(whereExpr)
          .orderBy(desc(trackedAccounts.suspicionScore))
          .limit(limit)
      : await db
          .select()
          .from(trackedAccounts)
          .orderBy(desc(trackedAccounts.suspicionScore))
          .limit(limit);

    return NextResponse.json({
      accounts: rows,
      total: rows.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/accounts] Failed:', error);
    return NextResponse.json(
      { error: message, accounts: [], total: 0 },
      { status: 500 },
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json().catch(() => null)) as {
      platform?: string;
      accountId?: string;
      username?: string;
    } | null;

    if (!body || typeof body !== 'object') {
      return NextResponse.json(
        { error: 'Invalid request body' },
        { status: 400 },
      );
    }

    const { platform, accountId, username } = body;

    if (!platform || typeof platform !== 'string') {
      return NextResponse.json(
        { error: 'Missing or invalid "platform"' },
        { status: 400 },
      );
    }

    if (!VALID_PLATFORMS.has(platform.toLowerCase())) {
      return NextResponse.json(
        { error: `Unsupported platform: ${platform}` },
        { status: 400 },
      );
    }

    if (!accountId || typeof accountId !== 'string') {
      return NextResponse.json(
        { error: 'Missing or invalid "accountId"' },
        { status: 400 },
      );
    }

    await addManualAccount(
      platform.toLowerCase(),
      accountId,
      typeof username === 'string' && username.length > 0 ? username : undefined,
    );

    return NextResponse.json({ success: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[POST /api/accounts] Failed:', error);
    return NextResponse.json(
      { error: message, success: false },
      { status: 500 },
    );
  }
}
