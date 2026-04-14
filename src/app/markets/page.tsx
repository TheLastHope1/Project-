'use client';

import { useState } from 'react';
import { useMarkets } from '@/hooks/use-markets';
import { MarketFilters } from '@/components/markets/market-filters';
import { MarketTable } from '@/components/markets/market-table';

export default function MarketsPage() {
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([
    'polymarket',
    'manifold',
    'kalshi',
    'predictit',
  ]);
  const [status, setStatus] = useState('active');
  const [search, setSearch] = useState('');

  const query = useMarkets({
    platforms: selectedPlatforms,
    status: status || undefined,
    search: search || undefined,
    sortBy: 'volume',
    sortOrder: 'desc',
    limit: 500,
  });

  const markets = query.data?.markets ?? [];

  const togglePlatform = (platform: string) => {
    setSelectedPlatforms((prev) =>
      prev.includes(platform)
        ? prev.filter((p) => p !== platform)
        : [...prev, platform],
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">Markets</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Browse all prediction markets across platforms
        </p>
      </div>

      <MarketFilters
        selectedPlatforms={selectedPlatforms}
        onTogglePlatform={togglePlatform}
        status={status}
        onStatusChange={setStatus}
        search={search}
        onSearchChange={setSearch}
      />

      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>{markets.length} markets shown</span>
        {query.isFetching && !query.isLoading && (
          <span className="text-zinc-400">Refreshing...</span>
        )}
      </div>

      <MarketTable markets={markets} isLoading={query.isLoading} />
    </div>
  );
}
