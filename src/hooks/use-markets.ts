'use client';

import { useQuery } from '@tanstack/react-query';
import type { Platform } from '@/lib/platforms/types';

export interface MarketData {
  id: string;
  platform: Platform;
  platformMarketId: string;
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
  status: string;
  resolution?: string;
  closeDate?: string;
  outcomes: string[];
  outcomePrices: number[];
  matchGroupId?: string;
  updatedAt: string;
}

interface MarketsResponse {
  markets: MarketData[];
  total: number;
  platformStatuses: Record<string, { isConnected: boolean; marketCount: number; lastFetch: string | null; error?: string }>;
}

export function useMarkets(params?: {
  platforms?: string[];
  status?: string;
  search?: string;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  limit?: number;
}) {
  return useQuery<MarketsResponse>({
    queryKey: ['markets', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.platforms?.length) searchParams.set('platforms', params.platforms.join(','));
      if (params?.status) searchParams.set('status', params.status);
      if (params?.search) searchParams.set('search', params.search);
      if (params?.sortBy) searchParams.set('sortBy', params.sortBy);
      if (params?.sortOrder) searchParams.set('sortOrder', params.sortOrder);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const res = await fetch(`/api/markets?${searchParams}`);
      if (!res.ok) throw new Error('Failed to fetch markets');
      return res.json();
    },
    refetchInterval: 30_000,
  });
}

export function useMarket(id: string) {
  return useQuery<{ market: MarketData; priceHistory: Array<{ timestamp: number; yesPrice: number }> }>({
    queryKey: ['market', id],
    queryFn: async () => {
      const res = await fetch(`/api/markets/${id}`);
      if (!res.ok) throw new Error('Failed to fetch market');
      return res.json();
    },
    refetchInterval: 30_000,
    enabled: !!id,
  });
}
