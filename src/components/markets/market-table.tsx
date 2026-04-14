'use client';

import { useRouter } from 'next/navigation';
import type { MarketData } from '@/hooks/use-markets';
import { PLATFORMS } from '@/lib/utils/constants';
import { formatUSD, formatDate } from '@/lib/utils/format';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils/cn';

interface MarketTableProps {
  markets: MarketData[];
  isLoading?: boolean;
}

export function MarketTable({ markets, isLoading }: MarketTableProps) {
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-12 text-center text-sm text-zinc-500">
        Loading markets...
      </div>
    );
  }

  if (markets.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-900/20 p-12 text-center text-sm text-zinc-500">
        No markets found. The background scheduler is fetching data from platforms — refresh in a few seconds.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/30">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900/60 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Market</th>
              <th className="px-3 py-2.5 text-left font-medium">Platform</th>
              <th className="px-3 py-2.5 text-right font-medium">YES</th>
              <th className="px-3 py-2.5 text-right font-medium">NO</th>
              <th className="px-3 py-2.5 text-right font-medium">Volume</th>
              <th className="px-3 py-2.5 text-right font-medium">Close Date</th>
              <th className="px-3 py-2.5 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {markets.map((m) => {
              const platformMeta = PLATFORMS[m.platform];
              return (
                <tr
                  key={m.id}
                  onClick={() => router.push(`/markets/${encodeURIComponent(m.id)}`)}
                  className="cursor-pointer transition-colors hover:bg-zinc-900/60"
                >
                  <td className="max-w-md truncate px-4 py-2.5 text-zinc-100">
                    {m.title}
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className="inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium"
                      style={{
                        background: `${platformMeta.color}20`,
                        color: platformMeta.color,
                      }}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ background: platformMeta.color }}
                      />
                      {platformMeta.shortName}
                    </span>
                  </td>
                  <td
                    className={cn(
                      'px-3 py-2.5 text-right font-mono',
                      m.yesPrice !== null && m.yesPrice >= 0.5 ? 'text-emerald-400' : 'text-zinc-100'
                    )}
                  >
                    {m.yesPrice !== null ? `${(m.yesPrice * 100).toFixed(0)}¢` : '—'}
                  </td>
                  <td
                    className={cn(
                      'px-3 py-2.5 text-right font-mono',
                      m.noPrice !== null && m.noPrice >= 0.5 ? 'text-red-400' : 'text-zinc-100'
                    )}
                  >
                    {m.noPrice !== null ? `${(m.noPrice * 100).toFixed(0)}¢` : '—'}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-zinc-300">
                    {formatUSD(m.volume)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-400">
                    {m.closeDate ? formatDate(new Date(m.closeDate)) : '—'}
                  </td>
                  <td className="px-3 py-2.5">
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
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
