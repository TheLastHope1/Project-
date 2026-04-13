'use client';

import { useQuery } from '@tanstack/react-query';
import type { Platform } from '@/lib/platforms/types';

export interface TrackedAccount {
  id: number;
  platform: Platform;
  accountId: string;
  username?: string;
  totalTrades: number;
  profitableTrades: number;
  accuracy: number | null;
  totalPnl: number | null;
  avgTimingAdvantage: number | null;
  suspicionScore: number | null;
  earlyMoverCount: number;
  isWhale: boolean;
  isTracked: boolean;
  firstSeen?: string;
  lastSeen?: string;
}

export function useAccounts(params?: {
  platform?: string;
  minSuspicion?: number;
  limit?: number;
}) {
  return useQuery<{ accounts: TrackedAccount[]; total: number }>({
    queryKey: ['accounts', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.platform) searchParams.set('platform', params.platform);
      if (params?.minSuspicion) searchParams.set('minSuspicion', String(params.minSuspicion));
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const res = await fetch(`/api/accounts?${searchParams}`);
      if (!res.ok) throw new Error('Failed to fetch accounts');
      return res.json();
    },
    refetchInterval: 900_000,
  });
}
