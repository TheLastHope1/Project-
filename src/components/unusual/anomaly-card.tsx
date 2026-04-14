'use client';

import Link from 'next/link';
import type { AnomalyData } from '@/hooks/use-anomalies';
import { Badge } from '@/components/ui/badge';
import { SEVERITY_COLORS } from '@/lib/utils/constants';
import { formatTimeAgo } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { AlertTriangle, TrendingUp, Users, Zap, Split } from 'lucide-react';

const TYPE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  volume_spike: TrendingUp,
  price_impact: Zap,
  whale_trade: Users,
  burst_trading: AlertTriangle,
  price_divergence: Split,
};

const TYPE_LABELS: Record<string, string> = {
  volume_spike: 'Volume Spike',
  price_impact: 'Price Impact',
  whale_trade: 'Whale Trade',
  burst_trading: 'Burst Trading',
  price_divergence: 'Price Divergence',
};

export function AnomalyCard({ anomaly }: { anomaly: AnomalyData }) {
  const Icon = TYPE_ICONS[anomaly.type] ?? AlertTriangle;
  const color = SEVERITY_COLORS[anomaly.severity as keyof typeof SEVERITY_COLORS] ?? '#6b7280';
  const label = TYPE_LABELS[anomaly.type] ?? anomaly.type;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 transition-colors hover:bg-zinc-900/70 animate-fade-in">
      <div className="flex items-start gap-3">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
          style={{ background: `${color}20`, color }}
        >
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="text-[10px]">
              {label}
            </Badge>
            <Badge
              className="text-[10px] uppercase"
              style={{ background: `${color}20`, color, border: `1px solid ${color}40` }}
            >
              {anomaly.severity}
            </Badge>
            <span className="text-xs text-zinc-500">
              {formatTimeAgo(new Date(anomaly.detectedAt))}
            </span>
          </div>
          <p className="mt-1.5 text-sm text-zinc-100">{anomaly.description}</p>
          {anomaly.marketTitle && (
            <Link
              href={`/markets/${encodeURIComponent(anomaly.marketId)}`}
              className="mt-1 inline-block truncate text-xs text-zinc-400 hover:text-zinc-200 max-w-full"
            >
              → {anomaly.marketTitle}
            </Link>
          )}
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <div className="relative h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
            <div
              className={cn('absolute inset-y-0 left-0 rounded-full')}
              style={{
                width: `${anomaly.score * 100}%`,
                background: color,
              }}
            />
          </div>
          <span className="font-mono text-xs text-zinc-400">
            {(anomaly.score * 100).toFixed(0)}
          </span>
        </div>
      </div>
    </div>
  );
}
