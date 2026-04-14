'use client';

import { use } from 'react';
import Link from 'next/link';
import { useMarket } from '@/hooks/use-markets';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { PriceChart } from '@/components/markets/price-chart';
import { PLATFORMS } from '@/lib/utils/constants';
import { formatUSD, formatDate } from '@/lib/utils/format';
import { ArrowLeft, ExternalLink } from 'lucide-react';

export default function MarketDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const decodedId = decodeURIComponent(id);
  const { data, isLoading, error } = useMarket(decodedId);

  if (isLoading) {
    return (
      <div className="py-12 text-center text-sm text-zinc-500">
        Loading market...
      </div>
    );
  }

  if (error || !data?.market) {
    return (
      <div className="flex flex-col items-center gap-4 py-12 text-center">
        <p className="text-sm text-zinc-500">Market not found.</p>
        <Link href="/markets" className="text-sm text-zinc-300 hover:text-zinc-100">
          ← Back to markets
        </Link>
      </div>
    );
  }

  const m = data.market;
  const platformMeta = PLATFORMS[m.platform];

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/markets"
        className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-200"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to markets
      </Link>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex items-center gap-2">
                <span
                  className="inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium"
                  style={{
                    background: `${platformMeta.color}20`,
                    color: platformMeta.color,
                  }}
                >
                  {platformMeta.name}
                </span>
                <Badge
                  variant={
                    m.status === 'active'
                      ? 'success'
                      : m.status === 'resolved'
                        ? 'secondary'
                        : 'warning'
                  }
                  className="text-[10px] uppercase"
                >
                  {m.status}
                </Badge>
              </div>
              <CardTitle className="text-xl">{m.title}</CardTitle>
              {m.description && (
                <p className="mt-2 text-sm text-zinc-400">{m.description}</p>
              )}
            </div>
            <a
              href={m.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              View on {platformMeta.name}
            </a>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-zinc-500">YES Price</p>
              <p className="mt-1 font-mono text-2xl text-emerald-400">
                {m.yesPrice !== null ? `${(m.yesPrice * 100).toFixed(1)}¢` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-zinc-500">NO Price</p>
              <p className="mt-1 font-mono text-2xl text-red-400">
                {m.noPrice !== null ? `${(m.noPrice * 100).toFixed(1)}¢` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-zinc-500">Volume</p>
              <p className="mt-1 font-mono text-2xl text-zinc-100">
                {formatUSD(m.volume)}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-zinc-500">Liquidity</p>
              <p className="mt-1 font-mono text-2xl text-zinc-100">
                {formatUSD(m.liquidity)}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Price History</CardTitle>
        </CardHeader>
        <CardContent>
          <PriceChart
            data={data.priceHistory ?? []}
            color={platformMeta.color}
            height={360}
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Market Info</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-zinc-500">Category</dt>
                <dd className="text-zinc-200">{m.category || '—'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Close Date</dt>
                <dd className="text-zinc-200">
                  {m.closeDate ? formatDate(new Date(m.closeDate)) : '—'}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Resolution</dt>
                <dd className="text-zinc-200">{m.resolution || 'Pending'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">24h Volume</dt>
                <dd className="font-mono text-zinc-200">{formatUSD(m.volume24h)}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Outcomes</CardTitle>
          </CardHeader>
          <CardContent>
            {m.outcomes && m.outcomes.length > 0 ? (
              <div className="space-y-2">
                {m.outcomes.map((outcome, i) => {
                  const price = m.outcomePrices?.[i];
                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2"
                    >
                      <span className="text-sm text-zinc-200">{outcome}</span>
                      <span className="font-mono text-sm text-zinc-100">
                        {price !== undefined ? `${(Number(price) * 100).toFixed(1)}¢` : '—'}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-zinc-500">Binary market (YES/NO)</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
