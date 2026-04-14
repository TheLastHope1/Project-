import type {
  Platform,
  PlatformFetcher,
  NormalizedMarket,
  NormalizedTrade,
} from './types';

const API_BASE = 'https://api.manifold.markets/v0';

interface ManifoldAnswer {
  text: string;
  probability: number;
}

interface ManifoldMarketRaw {
  id: string;
  question: string;
  description?: string;
  url?: string;
  slug?: string;
  creatorUsername?: string;
  probability?: number;
  volume: number;
  totalLiquidity?: number;
  isResolved: boolean;
  resolution?: string;
  closeTime?: number;
  createdTime?: number;
  mechanism: string;
  outcomeType: string;
  answers?: ManifoldAnswer[];
  coverImageUrl?: string;
  category?: string;
}

interface ManifoldBetRaw {
  id: string;
  contractId: string;
  amount: number;
  shares: number;
  outcome: string;
  probBefore: number;
  probAfter: number;
  createdTime: number;
  userId: string;
  userUsername?: string;
}

function normalizeMarket(raw: ManifoldMarketRaw): NormalizedMarket {
  const isBinary = raw.outcomeType === 'BINARY';
  const isMultiChoice = raw.outcomeType === 'MULTIPLE_CHOICE';

  let outcomes: string[];
  let outcomePrices: number[];

  if (isBinary) {
    const prob = raw.probability ?? 0.5;
    outcomes = ['Yes', 'No'];
    outcomePrices = [prob, 1 - prob];
  } else if (isMultiChoice && Array.isArray(raw.answers)) {
    outcomes = raw.answers.map((a) => a.text);
    outcomePrices = raw.answers.map((a) => a.probability);
  } else {
    outcomes = ['Yes', 'No'];
    outcomePrices = [];
  }

  const yesPrice = outcomePrices.length > 0 ? outcomePrices[0] : null;
  const noPrice = isBinary && outcomePrices.length > 1 ? outcomePrices[1] : null;

  let status: 'active' | 'closed' | 'resolved';
  if (raw.isResolved) {
    status = 'resolved';
  } else if (raw.closeTime && raw.closeTime < Date.now()) {
    status = 'closed';
  } else {
    status = 'active';
  }

  const url = raw.url ?? `https://manifold.markets/market/${raw.id}`;

  return {
    platformMarketId: raw.id,
    platform: 'manifold' as Platform,
    title: raw.question,
    description: typeof raw.description === 'string' ? raw.description : undefined,
    category: raw.category,
    url,
    imageUrl: raw.coverImageUrl,
    yesPrice,
    noPrice,
    lastTradePrice: yesPrice,
    volume: raw.volume ?? null,
    volume24h: null,
    liquidity: raw.totalLiquidity ?? null,
    status,
    resolution: raw.resolution,
    closeDate: raw.closeTime ? new Date(raw.closeTime) : undefined,
    outcomes,
    outcomePrices,
  };
}

function normalizeTrade(bet: ManifoldBetRaw): NormalizedTrade {
  return {
    platformTradeId: bet.id,
    platform: 'manifold' as Platform,
    platformMarketId: bet.contractId,
    side: bet.amount >= 0 ? 'BUY' : 'SELL',
    outcome: bet.outcome,
    price: bet.probAfter,
    size: Math.abs(bet.shares),
    amount: Math.abs(bet.amount),
    traderUsername: bet.userUsername,
    timestamp: new Date(bet.createdTime),
  };
}

class ManifoldFetcher implements PlatformFetcher {
  platform: Platform = 'manifold';

  async fetchMarkets(params?: { limit?: number; cursor?: string }): Promise<NormalizedMarket[]> {
    try {
      const limit = params?.limit ?? 100;
      let url = `${API_BASE}/markets?limit=${limit}&sort=newest`;
      if (params?.cursor) {
        url += `&before=${params.cursor}`;
      }

      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Manifold API returned ${response.status}: ${response.statusText}`);
      }

      const rawMarkets: ManifoldMarketRaw[] = await response.json();

      return rawMarkets
        .filter((m) => m.outcomeType === 'BINARY' || m.outcomeType === 'MULTIPLE_CHOICE')
        .map(normalizeMarket);
    } catch (error) {
      console.error('[Manifold] Failed to fetch markets:', error);
      return [];
    }
  }

  async fetchMarket(id: string): Promise<NormalizedMarket | null> {
    try {
      const url = `${API_BASE}/market/${id}`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Manifold API returned ${response.status}: ${response.statusText}`);
      }

      const raw: ManifoldMarketRaw = await response.json();
      return normalizeMarket(raw);
    } catch (error) {
      console.error(`[Manifold] Failed to fetch market ${id}:`, error);
      return null;
    }
  }

  async fetchTrades(
    marketId: string,
    params?: { limit?: number; after?: Date },
  ): Promise<NormalizedTrade[]> {
    try {
      const limit = params?.limit ?? 100;
      let url = `${API_BASE}/bets?contractId=${marketId}&limit=${limit}&order=desc`;
      if (params?.after) {
        url += `&after=${params.after.getTime()}`;
      }

      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Manifold API returned ${response.status}: ${response.statusText}`);
      }

      const bets: ManifoldBetRaw[] = await response.json();
      return bets.map(normalizeTrade);
    } catch (error) {
      console.error(`[Manifold] Failed to fetch trades for ${marketId}:`, error);
      return [];
    }
  }

  async searchMarkets(query: string): Promise<NormalizedMarket[]> {
    try {
      const url = `${API_BASE}/search-markets?term=${encodeURIComponent(query)}&limit=20`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Manifold API returned ${response.status}: ${response.statusText}`);
      }

      const rawMarkets: ManifoldMarketRaw[] = await response.json();
      return rawMarkets
        .filter((m) => m.outcomeType === 'BINARY' || m.outcomeType === 'MULTIPLE_CHOICE')
        .map(normalizeMarket);
    } catch (error) {
      console.error(`[Manifold] Failed to search markets for "${query}":`, error);
      return [];
    }
  }
}

export const manifoldFetcher = new ManifoldFetcher();
