'use client';

import { useMarkets } from '@/hooks/use-markets';
import { useArbitrage } from '@/hooks/use-arbitrage';
import { useAnomalies } from '@/hooks/use-anomalies';
import { useNews } from '@/hooks/use-news';
import { StatCard } from '@/components/dashboard/stat-card';
import { PlatformStatusCard } from '@/components/dashboard/platform-status-card';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatUSD, formatPercent, formatTimeAgo } from '@/lib/utils/format';
import { PLATFORMS, SEVERITY_COLORS } from '@/lib/utils/constants';
import {
  TrendingUp,
  AlertTriangle,
  Activity,
  DollarSign,
  BarChart3,
  Zap,
  Newspaper,
  ArrowRight,
} from 'lucide-react';
import Link from 'next/link';

export default function DashboardPage() {
  const marketsQuery = useMarkets({ status: 'active', limit: 500 });
  const arbitrageQuery = useArbitrage({ minSpread: 0.02 });
  const anomaliesQuery = useAnomalies({ limit: 10 });
  const newsQuery = useNews({ limit: 5 });

  const markets = marketsQuery.data?.markets ?? [];
  const opportunities = arbitrageQuery.data?.opportunities ?? [];
  const anomalies = anomaliesQuery.data?.anomalies ?? [];
  const news = newsQuery.data?.news ?? [];

  const totalVolume = markets.reduce((sum, m) => sum + (m.volume ?? 0), 0);
  const totalMarkets = markets.length;
  const biggestSpread = opportunities[0]?.spreadPercent ?? 0;

  const topMovers = [...markets]
    .filter((m) => m.yesPrice !== null)
    .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">Dashboard</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Live overview of prediction markets across platforms
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Active Markets"
          value={totalMarkets.toLocaleString()}
          icon={BarChart3}
          subtitle="Across all platforms"
        />
        <StatCard
          title="Total Volume"
          value={formatUSD(totalVolume)}
          icon={DollarSign}
          variant="success"
          subtitle="Aggregated liquidity"
        />
        <StatCard
          title="Arbitrage Opps"
          value={opportunities.length}
          icon={Zap}
          variant={opportunities.length > 0 ? 'warning' : 'default'}
          subtitle={
            biggestSpread > 0 ? `Max spread: ${formatPercent(biggestSpread / 100)}` : 'No opportunities'
          }
        />
        <StatCard
          title="Active Anomalies"
          value={anomalies.length}
          icon={AlertTriangle}
          variant={anomalies.length > 3 ? 'danger' : anomalies.length > 0 ? 'warning' : 'default'}
          subtitle="Unusual trading activity"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" />
              Top Markets by Volume
            </CardTitle>
            <Link
              href="/markets"
              className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1"
            >
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {marketsQuery.isLoading ? (
              <div className="py-8 text-center text-sm text-zinc-500">Loading markets...</div>
            ) : topMovers.length === 0 ? (
              <div className="py-8 text-center text-sm text-zinc-500">
                No markets yet. Data is being fetched in the background.
              </div>
            ) : (
              <div className="divide-y divide-zinc-800">
                {topMovers.map((m) => (
                  <Link
                    key={m.id}
                    href={`/markets/${encodeURIComponent(m.id)}`}
                    className="flex items-center justify-between gap-3 py-3 hover:bg-zinc-900/40 -mx-2 px-2 rounded transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className="h-2 w-2 rounded-full shrink-0"
                        style={{ background: PLATFORMS[m.platform].color }}
                      />
                      <div className="min-w-0">
                        <p className="truncate text-sm text-zinc-100">{m.title}</p>
                        <p className="text-xs text-zinc-500">
                          {PLATFORMS[m.platform].name} · {formatUSD(m.volume)}
                        </p>
                      </div>
                    </div>
                    <div className="font-mono text-sm text-zinc-100 shrink-0">
                      {m.yesPrice !== null ? `${(m.yesPrice * 100).toFixed(0)}¢` : '—'}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <PlatformStatusCard statuses={marketsQuery.data?.platformStatuses} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Unusual Activity
            </CardTitle>
            <Link
              href="/unusual-trades"
              className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1"
            >
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {anomalies.length === 0 ? (
              <div className="py-8 text-center text-sm text-zinc-500">
                No anomalies detected.
              </div>
            ) : (
              <div className="space-y-2">
                {anomalies.slice(0, 5).map((a) => (
                  <div
                    key={a.id}
                    className="flex items-start gap-2 rounded-md border border-zinc-800 p-2.5 text-sm"
                  >
                    <div
                      className="h-2 w-2 mt-1.5 rounded-full shrink-0"
                      style={{ background: SEVERITY_COLORS[a.severity as keyof typeof SEVERITY_COLORS] ?? '#6b7280' }}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-xs">
                        <Badge variant="outline" className="text-[10px]">
                          {a.type.replace('_', ' ')}
                        </Badge>
                        <span className="text-zinc-500">
                          {formatTimeAgo(new Date(a.detectedAt))}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-zinc-300">{a.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-4 w-4" />
              Top Arbitrage
            </CardTitle>
            <Link
              href="/arbitrage"
              className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1"
            >
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {opportunities.length === 0 ? (
              <div className="py-8 text-center text-sm text-zinc-500">
                No arbitrage opportunities right now.
              </div>
            ) : (
              <div className="space-y-2">
                {opportunities.slice(0, 5).map((op) => (
                  <div
                    key={op.id}
                    className="rounded-md border border-zinc-800 p-2.5"
                  >
                    <p className="truncate text-sm text-zinc-100">
                      {op.marketA.title}
                    </p>
                    <div className="mt-1 flex items-center justify-between text-xs">
                      <span className="text-zinc-500">
                        {PLATFORMS[op.marketA.platform].shortName} → {PLATFORMS[op.marketB.platform].shortName}
                      </span>
                      <span className="font-mono font-semibold text-emerald-400">
                        +{op.spreadPercent.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Newspaper className="h-4 w-4" />
            Recent News
          </CardTitle>
          <Link
            href="/news"
            className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1"
          >
            View all <ArrowRight className="h-3 w-3" />
          </Link>
        </CardHeader>
        <CardContent>
          {news.length === 0 ? (
            <div className="py-6 text-center text-sm text-zinc-500">
              News feed is being aggregated.
            </div>
          ) : (
            <div className="divide-y divide-zinc-800">
              {news.map((n) => (
                <a
                  key={n.id}
                  href={n.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block py-3 hover:bg-zinc-900/40 -mx-2 px-2 rounded transition-colors"
                >
                  <p className="truncate text-sm text-zinc-100">{n.title}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {n.source} · {formatTimeAgo(new Date(n.publishedAt))}
                  </p>
                </a>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
