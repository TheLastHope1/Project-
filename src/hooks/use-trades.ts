'use client';

import { useQuery } from '@tanstack/react-query';
import type { Platform } from '@/lib/platforms/types';

export interface TradeData {
  id: string;
  platform: Platform;
  marketId: string;
  marketTitle?: string;
  side: string;
  outcome: string;
  price: number;
  size: number;
  amount: number;
  traderAddress?: string;
  traderUsername?: string;
  timestamp: string;
  isAnomalous: boolean;
  anomalyType?: string;
  anomalyScore?: number;
}

export function useTrades(params?: {
  marketId?: string;
  platform?: string;
  limit?: number;
  anomalousOnly?: boolean;
}) {
  return useQuery<{ trades: TradeData[]; total: number }>({
    queryKey: ['trades', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.marketId) searchParams.set('marketId', params.marketId);
      if (params?.platform) searchParams.set('platform', params.platform);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.anomalousOnly) searchParams.set('anomalousOnly', 'true');
      const res = await fetch(`/api/trades?${searchParams}`);
      if (!res.ok) throw new Error('Failed to fetch trades');
      return res.json();
    },
    refetchInterval: 120_000,
  });
}
