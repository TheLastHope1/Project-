'use client';

import { useState } from 'react';
import { useAccounts } from '@/hooks/use-accounts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/dashboard/stat-card';
import { Badge } from '@/components/ui/badge';
import { PLATFORMS } from '@/lib/utils/constants';
import { formatUSD, formatPercent, formatTimeAgo } from '@/lib/utils/format';
import { Eye, TrendingUp, AlertTriangle, Users } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

function SuspicionGauge({ score }: { score: number }) {
  const color = score > 0.7 ? '#ef4444' : score > 0.4 ? '#f59e0b' : '#22c55e';
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-24 overflow-hidden rounded-full bg-zinc-800">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${score * 100}%`, background: color }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums" style={{ color }}>
        {(score * 100).toFixed(0)}
      </span>
    </div>
  );
}

export default function InsiderTrackingPage() {
  const [platform, setPlatform] = useState('');
  const [minSuspicion, setMinSuspicion] = useState(0);
  const query = useAccounts({
    platform: platform || undefined,
    minSuspicion: minSuspicion || undefined,
    limit: 100,
  });
  const accounts = query.data?.accounts ?? [];

  const whales = accounts.filter((a) => a.isWhale).length;
  const highSuspicion = accounts.filter((a) => (a.suspicionScore ?? 0) > 0.7).length;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">Insider Tracking</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Accounts with suspicious timing, high accuracy, or whale trade activity
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <StatCard title="Tracked Accounts" value={accounts.length} icon={Eye} />
        <StatCard title="Whales" value={whales} icon={Users} variant={whales > 0 ? 'warning' : 'default'} />
        <StatCard
          title="High Suspicion"
          value={highSuspicion}
          icon={AlertTriangle}
          variant={highSuspicion > 0 ? 'danger' : 'default'}
        />
        <StatCard
          title="Avg Accuracy"
          value={
            accounts.length > 0
              ? formatPercent(
                  accounts.reduce((sum, a) => sum + (a.accuracy ?? 0), 0) / accounts.length
                )
              : '—'
          }
          icon={TrendingUp}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          className="h-9 rounded-md border border-zinc-700 bg-zinc-900 px-3 text-sm text-zinc-100"
        >
          <option value="">All Platforms</option>
          {Object.entries(PLATFORMS).map(([key, meta]) => (
            <option key={key} value={key}>
              {meta.name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <span>Min suspicion:</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={minSuspicion}
            onChange={(e) => setMinSuspicion(parseFloat(e.target.value))}
            className="w-32"
          />
          <span className="font-mono text-xs text-zinc-100">
            {(minSuspicion * 100).toFixed(0)}
          </span>
        </label>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tracked Accounts</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {query.isLoading ? (
            <div className="p-8 text-center text-sm text-zinc-500">Loading...</div>
          ) : accounts.length === 0 ? (
            <div className="p-8 text-center text-sm text-zinc-500">
              No tracked accounts yet. Insider analysis runs every 15 minutes after trade data is available.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-zinc-900/60 text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-4 py-2.5 text-left font-medium">Account</th>
                    <th className="px-3 py-2.5 text-left font-medium">Platform</th>
                    <th className="px-3 py-2.5 text-right font-medium">Trades</th>
                    <th className="px-3 py-2.5 text-right font-medium">Accuracy</th>
                    <th className="px-3 py-2.5 text-right font-medium">P&amp;L</th>
                    <th className="px-3 py-2.5 text-right font-medium">Early Moves</th>
                    <th className="px-3 py-2.5 text-left font-medium">Suspicion</th>
                    <th className="px-3 py-2.5 text-right font-medium">Last Active</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {accounts.map((a) => {
                    const pm = PLATFORMS[a.platform];
                    return (
                      <tr key={a.id} className="hover:bg-zinc-900/60">
                        <td className="max-w-xs truncate px-4 py-2.5 font-mono text-xs text-zinc-100">
                          {a.username ?? a.accountId}
                          {a.isWhale && (
                            <Badge variant="warning" className="ml-2 text-[10px]">
                              WHALE
                            </Badge>
                          )}
                        </td>
                        <td className="px-3 py-2.5">
                          <span
                            className="rounded px-2 py-0.5 text-xs"
                            style={{ background: `${pm.color}20`, color: pm.color }}
                          >
                            {pm.shortName}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-zinc-200">
                          {a.totalTrades}
                        </td>
                        <td
                          className={cn(
                            'px-3 py-2.5 text-right font-mono',
                            (a.accuracy ?? 0) > 0.6 ? 'text-emerald-400' : 'text-zinc-200'
                          )}
                        >
                          {a.accuracy !== null ? formatPercent(a.accuracy) : '—'}
                        </td>
                        <td
                          className={cn(
                            'px-3 py-2.5 text-right font-mono',
                            (a.totalPnl ?? 0) > 0 ? 'text-emerald-400' : 'text-red-400'
                          )}
                        >
                          {formatUSD(a.totalPnl)}
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-zinc-200">
                          {a.earlyMoverCount}
                        </td>
                        <td className="px-3 py-2.5">
                          <SuspicionGauge score={a.suspicionScore ?? 0} />
                        </td>
                        <td className="px-3 py-2.5 text-right text-xs text-zinc-400">
                          {a.lastSeen ? formatTimeAgo(new Date(a.lastSeen)) : '—'}
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
