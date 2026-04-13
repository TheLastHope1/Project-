export type Platform = 'polymarket' | 'manifold' | 'kalshi' | 'predictit';

export interface NormalizedMarket {
  platformMarketId: string;
  platform: Platform;
  title: string;
  description?: string;
  category?: string;
  url: string;
  imageUrl?: string;
  yesPrice: number | null;
  noPrice: number | null;
  lastTradePrice: number | null;
  volume: number | null;
  volume24h: number | null;
  liquidity: number | null;
  status: 'active' | 'closed' | 'resolved';
  resolution?: string;
  closeDate?: Date;
  outcomes: string[];
  outcomePrices: number[];
  tokenIds?: string[];
}

export interface NormalizedTrade {
  platformTradeId: string;
  platform: Platform;
  platformMarketId: string;
  side: 'BUY' | 'SELL';
  outcome: string;
  price: number;
  size: number;
  amount: number;
  traderAddress?: string;
  traderUsername?: string;
  timestamp: Date;
  transactionHash?: string;
}

export interface NormalizedOrderBook {
  bids: Array<{ price: number; size: number }>;
  asks: Array<{ price: number; size: number }>;
  spread: number;
  midpoint: number;
}

export interface PlatformFetcher {
  platform: Platform;
  fetchMarkets(params?: { limit?: number; cursor?: string }): Promise<NormalizedMarket[]>;
  fetchMarket(id: string): Promise<NormalizedMarket | null>;
  fetchTrades(marketId: string, params?: { limit?: number; after?: Date }): Promise<NormalizedTrade[]>;
  fetchOrderBook?(marketId: string): Promise<NormalizedOrderBook | null>;
  searchMarkets?(query: string): Promise<NormalizedMarket[]>;
}

export interface PlatformStatus {
  platform: Platform;
  isConnected: boolean;
  lastFetch: Date | null;
  marketCount: number;
  error?: string;
}
