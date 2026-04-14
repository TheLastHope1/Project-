'use client';

import { useState } from 'react';
import { useArbitrage } from '@/hooks/use-arbitrage';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { StatCard } from '@/components/dashboard/stat-card';
import { PLATFORMS } from '@/lib/utils/constants';
import { formatUSD, formatPercent, formatTimeAgo } from '@/lib/utils/format';
import { Zap, TrendingUp, Target, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

export default function ArbitragePage() {
  const [minSpread, setMinSpread] = useState(0.02);
  const query = useArbitrage({ minSpread });
  const opportunities = query.data?.opportunities ?? [];

  const maxSpread = opportunities[0]?.spreadPercent ?? 0;
  const avgSpread =
    opportunities.length > 0
      ? opportunities.reduce((sum, op) => sum + op.spreadPercent, 0) / opportunities.length
      : 0;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">Arbitrage</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Cross-platform arbitrage opportunities detected in real-time
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard
          title="Active Opportunities"
          value={opportunities.length}
          icon={Zap}
          variant={opportunities.length > 0 ? 'warning' : 'default'}
        />
        <StatCard
          title="Biggest Spread"
          value={`${maxSpread.toFixed(2)}%`}
          icon={TrendingUp}
          variant={maxSpread > 5 ? 'success' : 'default'}
        />
        <StatCard
          title="Average Spread"
          value={`${avgSpread.toFixed(2)}%`}
          icon={Target}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <span>Min spread:</span>
          <input
            type="range"
            min="0"
            max="0.1"
            step="0.005"
            value={minSpread}
            onChange={(e) => setMinSpread(parseFloat(e.target.value))}
            className="w-32"
          />
          <span className="font-mono text-xs text-zinc-100">
            {formatPercent(minSpread)}
          </span>
        </label>
        {query.isFetching && !query.isLoading && (
          <span className="ml-auto text-xs text-zinc-400">Refreshing...</span>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Opportunities</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {query.isLoading ? (
            <div className="p-8 text-center text-sm text-zinc-500">Loading...</div>
          ) : opportunities.length === 0 ? (
            <div className="p-8 text-center text-sm text-zinc-500">
              No arbitrage opportunities above {formatPercent(minSpread)} spread.
              <br />
              <span className="text-xs">Market matching runs every 5 minutes.</span>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-zinc-900/60 text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-4 py-2.5 text-left font-medium">Market</th>
                    <th className="px-3 py-2.5 text-left font-medium">Buy YES</th>
                    <th className="px-3 py-2.5 text-left font-medium">Buy NO</th>
                    <th className="px-3 py-2.5 text-right font-medium">Spread</th>
                    <th className="px-3 py-2.5 text-right font-medium">Profit/$100</th>
                    <th className="px-3 py-2.5 text-left font-medium">Detected</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {opportunities.map((op) => {
                    const pa = PLATFORMS[op.marketA.platform];
                    const pb = PLATFORMS[op.marketB.platform];
                    const highlight = op.spreadPercent > 5;
                    return (
                      <tr
                        key={op.id}
                        className={cn(
                          'transition-colors hover:bg-zinc-900/60',
                          highlight && 'bg-emerald-950/20'
                        )}
                      >
                        <td className="max-w-md truncate px-4 py-2.5 text-zinc-100">
                          {op.marketA.title}
                        </td>
                        <td className="px-3 py-2.5">
                          <a
                            href={op.marketA.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs hover:underline"
                            style={{ color: pa.color }}
                          >
                            {pa.shortName} @ {(op.marketA.yesPrice * 100).toFixed(1)}¢
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        </td>
                        <td className="px-3 py-2.5">
                          <a
                            href={op.marketB.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs hover:underline"
                            style={{ color: pb.color }}
                          >
                            {pb.shortName} @ {(op.marketB.noPrice * 100).toFixed(1)}¢
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        </td>
                        <td
                          className={cn(
                            'px-3 py-2.5 text-right font-mono font-semibold',
                            op.spreadPercent > 5 ? 'text-emerald-400' : 'text-zinc-100'
                          )}
                        >
                          +{op.spreadPercent.toFixed(2)}%
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-emerald-400">
                          {formatUSD(op.estimatedProfit)}
                        </td>
                        <td className="px-3 py-2.5 text-xs text-zinc-400">
                          {formatTimeAgo(new Date(op.detectedAt))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
