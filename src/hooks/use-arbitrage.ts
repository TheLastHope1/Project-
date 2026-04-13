'use client';

import { useQuery } from '@tanstack/react-query';
import type { Platform } from '@/lib/platforms/types';

export interface ArbitrageOpportunity {
  id: number;
  matchGroupId: string;
  marketA: {
    id: string;
    title: string;
    platform: Platform;
    yesPrice: number;
    url: string;
  };
  marketB: {
    id: string;
    title: string;
    platform: Platform;
    noPrice: number;
    url: string;
  };
  spread: number;
  spreadPercent: number;
  estimatedProfit: number;
  type: string;
  status: string;
  detectedAt: string;
}

interface ArbitrageResponse {
  opportunities: ArbitrageOpportunity[];
  total: number;
}

export function useArbitrage(params?: {
  minSpread?: number;
  platforms?: string[];
  status?: string;
}) {
  return useQuery<ArbitrageResponse>({
    queryKey: ['arbitrage', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.minSpread) searchParams.set('minSpread', String(params.minSpread));
      if (params?.platforms?.length) searchParams.set('platforms', params.platforms.join(','));
      if (params?.status) searchParams.set('status', params.status);
      const res = await fetch(`/api/arbitrage?${searchParams}`);
      if (!res.ok) throw new Error('Failed to fetch arbitrage');
      return res.json();
    },
    refetchInterval: 15_000,
  });
}
