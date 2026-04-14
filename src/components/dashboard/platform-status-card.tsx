'use client';

import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PLATFORMS } from '@/lib/utils/constants';
import { cn } from '@/lib/utils/cn';
import { Activity } from 'lucide-react';

export interface PlatformStatusInfo {
  isConnected: boolean;
  marketCount: number;
  lastFetch: string | null;
  error?: string;
}

interface PlatformStatusCardProps {
  statuses?: Record<string, PlatformStatusInfo>;
}

export function PlatformStatusCard({ statuses }: PlatformStatusCardProps) {
  const entries = Object.entries(PLATFORMS) as Array<
    [keyof typeof PLATFORMS, (typeof PLATFORMS)[keyof typeof PLATFORMS]]
  >;

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Platform Status
          </CardTitle>
          <Activity className="h-4 w-4 text-zinc-500" />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.map(([key, meta]) => {
          const status = statuses?.[key];
          const isConnected = status?.isConnected ?? false;
          return (
            <div
              key={key}
              className="flex items-center justify-between rounded-md border border-zinc-800/60 bg-zinc-950/40 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    'relative flex h-2 w-2 shrink-0',
                    isConnected && 'animate-pulse-dot'
                  )}
                >
                  <span
                    className={cn(
                      'absolute inline-flex h-full w-full rounded-full opacity-75',
                      isConnected ? 'bg-emerald-400' : 'bg-red-500'
                    )}
                  />
                  <span
                    className={cn(
                      'relative inline-flex h-2 w-2 rounded-full',
                      isConnected ? 'bg-emerald-500' : 'bg-red-600'
                    )}
                  />
                </span>
                <span
                  className="text-xs font-semibold tracking-wide"
                  style={{ color: meta.color }}
                >
                  {meta.name}
                </span>
              </div>
              <div className="flex items-center gap-3 font-mono text-xs text-zinc-400">
                <span>{status?.marketCount ?? 0} mkts</span>
                <span
                  className={cn(
                    'rounded px-1.5 py-0.5',
                    isConnected
                      ? 'bg-emerald-500/10 text-emerald-400'
                      : 'bg-red-500/10 text-red-400'
                  )}
                >
                  {isConnected ? 'ONLINE' : 'OFFLINE'}
                </span>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
