import { NextRequest, NextResponse } from 'next/server';
import { findArbitrageOpportunities } from '@/lib/analysis/arbitrage';
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

    const minSpreadParam = searchParams.get('minSpread');
    const platformsParam = searchParams.get('platforms');
    const status = searchParams.get('status');

    let minSpread = 0.02;
    if (minSpreadParam) {
      const parsed = parseFloat(minSpreadParam);
      if (!Number.isNaN(parsed) && parsed >= 0) {
        minSpread = parsed;
      }
    }

    const requestedPlatforms: Platform[] = platformsParam
      ? (platformsParam
          .split(',')
          .map((p) => p.trim().toLowerCase())
          .filter((p) => VALID_PLATFORMS.has(p)) as Platform[])
      : [];

    let opportunities = await findArbitrageOpportunities(minSpread);

    if (requestedPlatforms.length > 0) {
      const allowed = new Set(requestedPlatforms);
      opportunities = opportunities.filter(
        (o) =>
          allowed.has(o.platformA as Platform) ||
          allowed.has(o.platformB as Platform),
      );
    }

    if (status && status !== 'all') {
      // The in-memory results are all currently-active opportunities.
      // Treat any non-"active" filter as a filter that returns nothing
      // unless status === 'active'.
      if (status !== 'active') {
        opportunities = [];
      }
    }

    return NextResponse.json({
      opportunities,
      total: opportunities.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/arbitrage] Failed:', error);
    return NextResponse.json(
      { error: message, opportunities: [], total: 0 },
      { status: 500 },
    );
  }
}
