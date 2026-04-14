import { NextRequest, NextResponse } from 'next/server';
import { getFetcher, type Platform } from '@/lib/platforms';

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

    if (!marketId) {
      return NextResponse.json(
        { error: 'Missing required query parameter: marketId' },
        { status: 400 },
      );
    }

    if (!platform || !VALID_PLATFORMS.has(platform.toLowerCase())) {
      return NextResponse.json(
        { error: 'Missing or invalid query parameter: platform' },
        { status: 400 },
      );
    }

    const fetcher = getFetcher(platform.toLowerCase() as Platform);
    if (!fetcher) {
      return NextResponse.json(
        { error: `Unknown platform: ${platform}` },
        { status: 400 },
      );
    }

    if (typeof fetcher.fetchOrderBook !== 'function') {
      return NextResponse.json(
        { error: 'not supported', platform, marketId },
        { status: 200 },
      );
    }

    const orderbook = await fetcher.fetchOrderBook(marketId);

    if (!orderbook) {
      return NextResponse.json(
        { error: 'Order book unavailable', platform, marketId },
        { status: 404 },
      );
    }

    return NextResponse.json({
      platform,
      marketId,
      orderbook,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/orderbook] Failed:', error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
