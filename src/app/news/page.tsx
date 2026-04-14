'use client';

import { useNews } from '@/hooks/use-news';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatTimeAgo } from '@/lib/utils/format';
import { Newspaper, ExternalLink } from 'lucide-react';

export default function NewsPage() {
  const { data, isLoading } = useNews({ limit: 100 });
  const news = data?.news ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">News & Data</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Aggregated news from Google News and Reddit, scored for relevance to tracked markets
        </p>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-sm text-zinc-500">Loading news...</div>
      ) : news.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Newspaper className="mx-auto mb-3 h-8 w-8 text-zinc-600" />
            <p className="text-sm text-zinc-500">
              No news aggregated yet. News is fetched every 10 minutes in the background.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {news.map((n) => (
            <a
              key={n.id}
              href={n.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group block rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 transition-colors hover:border-zinc-700 hover:bg-zinc-900/70"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs text-zinc-500">
                    <span className="font-medium text-zinc-400">{n.source}</span>
                    <span>•</span>
                    <span>{formatTimeAgo(new Date(n.publishedAt))}</span>
                    {typeof n.relevanceScore === 'number' && n.relevanceScore > 0 && (
                      <Badge variant="outline" className="ml-auto text-[10px]">
                        {(n.relevanceScore * 100).toFixed(0)}% relevant
                      </Badge>
                    )}
                  </div>
                  <h3 className="mt-2 text-sm font-medium text-zinc-100 group-hover:text-white">
                    {n.title}
                  </h3>
                  {n.summary && (
                    <p className="mt-1 line-clamp-2 text-xs text-zinc-400">{n.summary}</p>
                  )}
                </div>
                <ExternalLink className="h-4 w-4 shrink-0 text-zinc-600 group-hover:text-zinc-400" />
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
