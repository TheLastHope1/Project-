'use client';

import { useQuery } from '@tanstack/react-query';

export interface NewsItem {
  id: number;
  title: string;
  summary?: string;
  url: string;
  source: string;
  imageUrl?: string;
  publishedAt: string;
  relatedMarketIds?: string[];
  relevanceScore?: number;
  keywords?: string[];
}

export function useNews(params?: {
  limit?: number;
  source?: string;
}) {
  return useQuery<{ news: NewsItem[]; total: number }>({
    queryKey: ['news', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.source) searchParams.set('source', params.source);
      const res = await fetch(`/api/news?${searchParams}`);
      if (!res.ok) throw new Error('Failed to fetch news');
      return res.json();
    },
    refetchInterval: 600_000,
  });
}
