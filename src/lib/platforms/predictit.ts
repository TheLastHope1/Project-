import type {
  Platform,
  PlatformFetcher,
  NormalizedMarket,
  NormalizedTrade,
} from './types';

const API_BASE = 'https://www.predictit.org/api/marketdata';

interface PredictItContract {
  id: number;
  name: string;
  shortName?: string;
  image?: string;
  lastTradePrice: number | null;
  bestBuyYesCost: number | null;
  bestBuyNoCost: number | null;
  bestSellYesCost: number | null;
  bestSellNoCost: number | null;
  lastClosePrice: number | null;
  status: string;
}

interface PredictItMarketRaw {
  id: number;
  name: string;
  shortName?: string;
  image?: string;
  url: string;
  contracts: PredictItContract[];
}

function normalizeContract(
  parentMarket: PredictItMarketRaw,
  contract: PredictItContract,
  isSingleContract: boolean,
): NormalizedMarket {
  const title = isSingleContract
    ? parentMarket.name
    : `${parentMarket.name} - ${contract.name}`;

  const yesPrice = contract.bestBuyYesCost;
  const noPrice = contract.bestBuyNoCost;
  const lastTradePrice = contract.lastTradePrice;

  const isOpen = (contract.status ?? '').toLowerCase() === 'open';

  return {
    platformMarketId: `${parentMarket.id}-${contract.id}`,
    platform: 'predictit' as Platform,
    title,
    url: parentMarket.url,
    imageUrl: contract.image ?? parentMarket.image ?? undefined,
    yesPrice,
    noPrice,
    lastTradePrice,
    volume: null, // PredictIt does not expose volume
    volume24h: null,
    liquidity: null,
    status: isOpen ? 'active' : 'closed',
    outcomes: ['Yes', 'No'],
    outcomePrices: yesPrice != null && noPrice != null ? [yesPrice, noPrice] : [],
  };
}

class PredictItFetcher implements PlatformFetcher {
  platform: Platform = 'predictit';

  // Cache the full market dump for single-market lookups
  private cachedMarkets: NormalizedMarket[] | null = null;
  private cacheTimestamp: number = 0;
  private readonly cacheTtlMs = 60_000; // 1 minute

  async fetchMarkets(params?: { limit?: number; cursor?: string }): Promise<NormalizedMarket[]> {
    try {
      const url = `${API_BASE}/all/`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`PredictIt API returned ${response.status}: ${response.statusText}`);
      }

      const data = await response.json() as { markets?: PredictItMarketRaw[] };
      const rawMarkets = data.markets ?? [];
      const normalized: NormalizedMarket[] = [];

      for (const market of rawMarkets) {
        const contracts = market.contracts ?? [];
        if (contracts.length === 0) continue;

        const isSingle = contracts.length === 1;
        for (const contract of contracts) {
          normalized.push(normalizeContract(market, contract, isSingle));
        }
      }

      // Update cache
      this.cachedMarkets = normalized;
      this.cacheTimestamp = Date.now();

      // Apply pagination
      const offset = params?.cursor ? parseInt(params.cursor, 10) : 0;
      const limit = params?.limit ?? 100;
      return normalized.slice(offset, offset + limit);
    } catch (error) {
      console.error('[PredictIt] Failed to fetch markets:', error);
      return [];
    }
  }

  async fetchMarket(id: string): Promise<NormalizedMarket | null> {
    try {
      // Try using cache first
      const isCacheValid = this.cachedMarkets && (Date.now() - this.cacheTimestamp) < this.cacheTtlMs;
      if (!isCacheValid) {
        await this.fetchMarkets();
      }

      const market = this.cachedMarkets?.find((m) => m.platformMarketId === id) ?? null;
      return market;
    } catch (error) {
      console.error(`[PredictIt] Failed to fetch market ${id}:`, error);
      return null;
    }
  }

  async fetchTrades(
    _marketId: string,
    _params?: { limit?: number; after?: Date },
  ): Promise<NormalizedTrade[]> {
    // PredictIt does not provide a public trade API
    return [];
  }
}

export const predictitFetcher = new PredictItFetcher();
