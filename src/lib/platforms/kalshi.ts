import type {
  Platform,
  PlatformFetcher,
  NormalizedMarket,
  NormalizedTrade,
  NormalizedOrderBook,
} from './types';

const API_BASE = 'https://api.elections.kalshi.com/trade-api/v2';

interface KalshiMarketRaw {
  ticker: string;
  title: string;
  subtitle?: string;
  event_ticker: string;
  yes_bid: number;
  yes_ask: number;
  no_bid: number;
  no_ask: number;
  last_price: number;
  volume: number;
  open_interest?: number;
  status: string;
  result?: string;
  close_time?: string;
  category?: string;
}

function centsToDecimal(cents: number | null | undefined): number | null {
  if (cents == null) return null;
  return cents / 100;
}

function normalizeMarket(raw: KalshiMarketRaw): NormalizedMarket {
  const yesPrice = centsToDecimal(raw.yes_bid) ?? centsToDecimal(raw.yes_ask);
  const noPrice = centsToDecimal(raw.no_bid) ?? centsToDecimal(raw.no_ask);
  const lastTradePrice = centsToDecimal(raw.last_price);

  let status: 'active' | 'closed' | 'resolved';
  const rawStatus = (raw.status ?? '').toLowerCase();
  if (rawStatus === 'finalized' || rawStatus === 'settled' || raw.result) {
    status = 'resolved';
  } else if (rawStatus === 'closed' || rawStatus === 'ceased_trading') {
    status = 'closed';
  } else {
    status = 'active';
  }

  const yesBid = raw.yes_bid / 100;
  const yesAsk = raw.yes_ask / 100;
  const midpoint = (yesBid + yesAsk) / 2;

  return {
    platformMarketId: raw.ticker,
    platform: 'kalshi' as Platform,
    title: raw.title + (raw.subtitle ? ` - ${raw.subtitle}` : ''),
    category: raw.category,
    url: `https://kalshi.com/markets/${raw.ticker}`,
    yesPrice: yesPrice ?? (midpoint > 0 ? midpoint : null),
    noPrice: noPrice ?? (midpoint > 0 ? 1 - midpoint : null),
    lastTradePrice,
    volume: raw.volume != null ? raw.volume : null,
    volume24h: null,
    liquidity: raw.open_interest != null ? raw.open_interest : null,
    status,
    resolution: raw.result,
    closeDate: raw.close_time ? new Date(raw.close_time) : undefined,
    outcomes: ['Yes', 'No'],
    outcomePrices: midpoint > 0 ? [midpoint, 1 - midpoint] : [],
  };
}

class KalshiFetcher implements PlatformFetcher {
  platform: Platform = 'kalshi';

  async fetchMarkets(params?: { limit?: number; cursor?: string }): Promise<NormalizedMarket[]> {
    try {
      const limit = params?.limit ?? 200;
      let url = `${API_BASE}/markets?limit=${limit}&status=open`;
      if (params?.cursor) {
        url += `&cursor=${params.cursor}`;
      }

      const response = await fetch(url);
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          console.warn('[Kalshi] Authentication required or access denied');
          return [];
        }
        throw new Error(`Kalshi API returned ${response.status}: ${response.statusText}`);
      }

      const data = await response.json() as { markets?: KalshiMarketRaw[] };
      const rawMarkets = data.markets ?? [];
      return rawMarkets.map(normalizeMarket);
    } catch (error) {
      console.error('[Kalshi] Failed to fetch markets:', error);
      return [];
    }
  }

  async fetchMarket(ticker: string): Promise<NormalizedMarket | null> {
    try {
      const url = `${API_BASE}/markets/${ticker}`;
      const response = await fetch(url);
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          console.warn(`[Kalshi] Authentication required for market ${ticker}`);
          return null;
        }
        throw new Error(`Kalshi API returned ${response.status}: ${response.statusText}`);
      }

      const data = await response.json() as { market?: KalshiMarketRaw };
      const raw = data.market;
      if (!raw) return null;
      return normalizeMarket(raw);
    } catch (error) {
      console.error(`[Kalshi] Failed to fetch market ${ticker}:`, error);
      return null;
    }
  }

  async fetchTrades(
    _marketId: string,
    _params?: { limit?: number; after?: Date },
  ): Promise<NormalizedTrade[]> {
    // Kalshi trade data requires authentication
    return [];
  }

  async fetchOrderBook(ticker: string): Promise<NormalizedOrderBook | null> {
    try {
      const market = await this.fetchMarket(ticker);
      if (!market) return null;

      // Kalshi provides bid/ask in the market data itself.
      // We fetch the raw market to reconstruct the order book.
      const url = `${API_BASE}/markets/${ticker}`;
      const response = await fetch(url);
      if (!response.ok) return null;

      const data = await response.json() as { market?: KalshiMarketRaw };
      const raw = data.market;
      if (!raw) return null;

      const yesBid = raw.yes_bid / 100;
      const yesAsk = raw.yes_ask / 100;
      const noBid = raw.no_bid / 100;
      const noAsk = raw.no_ask / 100;

      // Construct a simple order book from the top-of-book data
      const bids = yesBid > 0 ? [{ price: yesBid, size: 1 }] : [];
      const asks = yesAsk > 0 ? [{ price: yesAsk, size: 1 }] : [];

      // Also include no-side as inverted yes prices
      if (noAsk > 0) bids.push({ price: 1 - noAsk, size: 1 });
      if (noBid > 0) asks.push({ price: 1 - noBid, size: 1 });

      // Sort bids descending, asks ascending
      bids.sort((a, b) => b.price - a.price);
      asks.sort((a, b) => a.price - b.price);

      const bestBid = bids.length > 0 ? bids[0].price : 0;
      const bestAsk = asks.length > 0 ? asks[0].price : 1;
      const spread = bestAsk - bestBid;
      const midpoint = (bestBid + bestAsk) / 2;

      return { bids, asks, spread, midpoint };
    } catch (error) {
      console.error(`[Kalshi] Failed to fetch order book for ${ticker}:`, error);
      return null;
    }
  }
}

export const kalshiFetcher = new KalshiFetcher();
