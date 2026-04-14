'use client';

import { useQuery } from '@tanstack/react-query';

export interface AnomalyData {
  id: number;
  marketId: string;
  marketTitle?: string;
  type: string;
  severity: string;
  score: number;
  description: string;
  details?: Record<string, unknown>;
  relatedTradeIds?: string[];
  relatedAccountId?: string;
  detectedAt: string;
  acknowledged: boolean;
}

export function useAnomalies(params?: {
  type?: string;
  severity?: string;
  limit?: number;
}) {
  return useQuery<{ anomalies: AnomalyData[]; total: number }>({
    queryKey: ['anomalies', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.type) searchParams.set('type', params.type);
      if (params?.severity) searchParams.set('severity', params.severity);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const res = await fetch(`/api/unusual?${searchParams}`);
      if (!res.ok) throw new Error('Failed to fetch anomalies');
      return res.json();
    },
    refetchInterval: 60_000,
  });
}
