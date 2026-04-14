'use client';

import * as React from 'react';
import { cn } from '@/lib/utils/cn';

interface PlatformStatus {
  name: string;
  connected: boolean;
}

interface StatusBarProps {
  lastRefresh: Date | null;
  platforms: PlatformStatus[];
  activeAnomalyCount: number;
  activeArbitrageCount: number;
}

export function StatusBar({
  lastRefresh,
  platforms,
  activeAnomalyCount,
  activeArbitrageCount,
}: StatusBarProps) {
  const [secondsAgo, setSecondsAgo] = React.useState<number | null>(null);

  React.useEffect(() => {
    if (!lastRefresh) return;

    const update = () => {
      const diff = Math.floor((Date.now() - lastRefresh.getTime()) / 1000);
      setSecondsAgo(diff);
    };

    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [lastRefresh]);

  return (
    <footer className="flex h-7 items-center justify-between border-t border-zinc-800 bg-zinc-950 px-4 text-xs text-zinc-500">
      {/* Last refresh */}
      <div>
        {lastRefresh && secondsAgo !== null
          ? `Last refresh: ${secondsAgo}s ago`
          : 'No data yet'}
      </div>

      {/* Platform statuses */}
      <div className="flex items-center gap-3">
        {platforms.map((platform) => (
          <div key={platform.name} className="flex items-center gap-1.5">
            <span
              className={cn(
                'inline-block h-1.5 w-1.5 rounded-full',
                platform.connected ? 'bg-emerald-500' : 'bg-red-500'
              )}
            />
            <span>{platform.name}</span>
          </div>
        ))}
      </div>

      {/* Counts */}
      <div className="flex items-center gap-4">
        <span>
          Anomalies:{' '}
          <span
            className={cn(
              'font-medium',
              activeAnomalyCount > 0 ? 'text-amber-400' : 'text-zinc-500'
            )}
          >
            {activeAnomalyCount}
          </span>
        </span>
        <span>
          Arbitrage:{' '}
          <span
            className={cn(
              'font-medium',
              activeArbitrageCount > 0 ? 'text-emerald-400' : 'text-zinc-500'
            )}
          >
            {activeArbitrageCount}
          </span>
        </span>
      </div>
    </footer>
  );
}
