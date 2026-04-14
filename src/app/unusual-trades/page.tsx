'use client';

import { useState } from 'react';
import { useAnomalies } from '@/hooks/use-anomalies';
import { AnomalyCard } from '@/components/unusual/anomaly-card';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/dashboard/stat-card';
import { AlertTriangle, TrendingUp, Users, Zap, Split } from 'lucide-react';

const TYPES = [
  { value: '', label: 'All Types' },
  { value: 'volume_spike', label: 'Volume Spike' },
  { value: 'price_impact', label: 'Price Impact' },
  { value: 'whale_trade', label: 'Whale Trade' },
  { value: 'burst_trading', label: 'Burst Trading' },
  { value: 'price_divergence', label: 'Price Divergence' },
];

const SEVERITIES = [
  { value: '', label: 'All Severities' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

export default function UnusualTradesPage() {
  const [type, setType] = useState('');
  const [severity, setSeverity] = useState('');
  const query = useAnomalies({
    type: type || undefined,
    severity: severity || undefined,
    limit: 200,
  });
  const anomalies = query.data?.anomalies ?? [];

  const byType = anomalies.reduce<Record<string, number>>((acc, a) => {
    acc[a.type] = (acc[a.type] || 0) + 1;
    return acc;
  }, {});
  const criticalCount = anomalies.filter((a) => a.severity === 'critical').length;
  const highCount = anomalies.filter((a) => a.severity === 'high').length;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">Unusual Trades</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Anomaly detection across all markets and platforms
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <StatCard
          title="Volume Spikes"
          value={byType.volume_spike ?? 0}
          icon={TrendingUp}
        />
        <StatCard
          title="Price Impact"
          value={byType.price_impact ?? 0}
          icon={Zap}
        />
        <StatCard
          title="Whale Trades"
          value={byType.whale_trade ?? 0}
          icon={Users}
        />
        <StatCard
          title="High Severity"
          value={highCount}
          icon={AlertTriangle}
          variant={highCount > 0 ? 'warning' : 'default'}
        />
        <StatCard
          title="Critical"
          value={criticalCount}
          icon={Split}
          variant={criticalCount > 0 ? 'danger' : 'default'}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="h-9 rounded-md border border-zinc-700 bg-zinc-900 px-3 text-sm text-zinc-100"
        >
          {TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className="h-9 rounded-md border border-zinc-700 bg-zinc-900 px-3 text-sm text-zinc-100"
        >
          {SEVERITIES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-zinc-500">
          {anomalies.length} anomalies
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Detected Anomalies</CardTitle>
        </CardHeader>
        <CardContent>
          {query.isLoading ? (
            <div className="py-8 text-center text-sm text-zinc-500">Loading...</div>
          ) : anomalies.length === 0 ? (
            <div className="py-8 text-center text-sm text-zinc-500">
              No anomalies detected. Analysis runs every 2 minutes.
            </div>
          ) : (
            <div className="space-y-2">
              {anomalies.map((a) => (
                <AnomalyCard key={a.id} anomaly={a} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
