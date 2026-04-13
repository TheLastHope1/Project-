import type {
  Platform,
  PlatformFetcher,
  NormalizedMarket,
  NormalizedTrade,
  NormalizedOrderBook,
} from './types';

const GAMMA_API = 'https://gamma-api.polymarket.com';
const CLOB_API = 'https://clob.polymarket.com';

function parseJsonString<T>(value: unknown, fallback: T): T {
  if (typeof value !== 'string') return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function normalizeMarket(market: Record<string, unknown>): NormalizedMarket {
  const outcomes = parseJsonString<string[]>(market.outcomes, ['Yes', 'No']);
  const outcomePrices = parseJsonString<string[]>(market.outcomePrices, []).map(Number);
  const tokenIds = parseJsonString<string[]>(market.clobTokenIds, []);

  const yesPrice = outcomePrices.length > 0 ? outcomePrices[0] : null;
  const noPrice = outcomePrices.length > 1 ? outcomePrices[1] : null;

  const isActive = Boolean(market.active) && !Boolean(market.closed);

  return {
    platformMarketId: String(market.id ?? ''),
    platform: 'polymarket' as Platform,
    title: String(market.question ?? ''),
    description: market.description ? String(market.description) : undefined,
    category: market.category ? String(market.category) : undefined,
    url: `https://polymarket.com/event/${market.slug ?? market.id}`,
    imageUrl: market.image ? String(market.image) : undefined,
    yesPrice,
    noPrice,
    lastTradePrice: yesPrice,
    volume: market.volume != null ? Number(market.volume) : null,
    volume24h: market.volume24hr != null ? Number(market.volume24hr) : null,
    liquidity: market.liquidity != null ? Number(market.liquidity) : null,
    status: isActive ? 'active' : (market.closed ? 'closed' : 'resolved'),
    resolution: market.resolution ? String(market.resolution) : undefined,
    closeDate: market.endDate ? new Date(String(market.endDate)) : undefined,
    outcomes,
    outcomePrices,
    tokenIds: tokenIds.length > 0 ? tokenIds : undefined,
  };
}

class PolymarketFetcher implements PlatformFetcher {
  platform: Platform = 'polymarket';

  async fetchMarkets(params?: { limit?: number; cursor?: string }): Promise<NormalizedMarket[]> {
    try {
      const limit = params?.limit ?? 100;
      const offset = params?.cursor ? parseInt(params.cursor, 10) : 0;
      const url = `${GAMMA_API}/events?active=true&closed=false&limit=${limit}&offset=${offset}`;

      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Gamma API returned ${response.status}: ${response.statusText}`);
      }

      const events: Record<string, unknown>[] = await response.json();
      const markets: NormalizedMarket[] = [];

      for (const event of events) {
        const eventMarkets = event.markets as Record<string, unknown>[] | undefined;
        if (Array.isArray(eventMarkets)) {
          for (const market of eventMarkets) {
            markets.push(normalizeMarket({
              ...market,
              slug: market.slug ?? event.slug,
              image: market.image ?? event.image,
              category: market.category ?? event.category,
            }));
          }
        }
      }

      return markets;
    } catch (error) {
      console.error('[Polymarket] Failed to fetch markets:', error);
      return [];
    }
  }

  async fetchMarket(id: string): Promise<NormalizedMarket | null> {
    try {
      const url = `${GAMMA_API}/markets/${id}`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Gamma API returned ${response.status}: ${response.statusText}`);
      }

      const market: Record<string, unknown> = await response.json();
      return normalizeMarket(market);
    } catch (error) {
      console.error(`[Polymarket] Failed to fetch market ${id}:`, error);
      return null;
    }
  }

  async fetchTrades(
    _marketId: string,
    _params?: { limit?: number; after?: Date },
  ): Promise<NormalizedTrade[]> {
    // Polymarket trade data requires authentication
    return [];
  }

  async fetchOrderBook(marketId: string): Promise<NormalizedOrderBook | null> {
    try {
      // marketId here should be the condition ID or token ID.
      // We attempt to fetch the market first to get the token ID.
      const market = await this.fetchMarket(marketId);
      const tokenId = market?.tokenIds?.[0] ?? marketId;

      const url = `${CLOB_API}/book?token_id=${tokenId}`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`CLOB API returned ${response.status}: ${response.statusText}`);
      }

      const data = await response.json() as {
        bids?: Array<{ price: string; size: string }>;
        asks?: Array<{ price: string; size: string }>;
      };

      const bids = (data.bids ?? []).map((b) => ({
        price: Number(b.price),
        size: Number(b.size),
      }));
      const asks = (data.asks ?? []).map((a) => ({
        price: Number(a.price),
        size: Number(a.size),
      }));

      const bestBid = bids.length > 0 ? bids[0].price : 0;
      const bestAsk = asks.length > 0 ? asks[0].price : 1;
      const spread = bestAsk - bestBid;
      const midpoint = (bestBid + bestAsk) / 2;

      return { bids, asks, spread, midpoint };
    } catch (error) {
      console.error(`[Polymarket] Failed to fetch order book for ${marketId}:`, error);
      return null;
    }
  }
}

export const polymarketFetcher = new PolymarketFetcher();
