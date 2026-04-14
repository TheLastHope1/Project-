'use client';

import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { PLATFORMS } from '@/lib/utils/constants';
import { cn } from '@/lib/utils/cn';
import { Search } from 'lucide-react';

interface MarketFiltersProps {
  selectedPlatforms: string[];
  onTogglePlatform: (platform: string) => void;
  status: string;
  onStatusChange: (status: string) => void;
  search: string;
  onSearchChange: (search: string) => void;
}

export function MarketFilters({
  selectedPlatforms,
  onTogglePlatform,
  status,
  onStatusChange,
  search,
  onSearchChange,
}: MarketFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <div className="relative min-w-[240px] flex-1">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <Input
          placeholder="Search markets..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {(Object.keys(PLATFORMS) as Array<keyof typeof PLATFORMS>).map((key) => {
          const isSelected = selectedPlatforms.includes(key);
          const meta = PLATFORMS[key];
          return (
            <button
              key={key}
              onClick={() => onTogglePlatform(key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                isSelected
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'bg-zinc-900 text-zinc-500 hover:text-zinc-300'
              )}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: isSelected ? meta.color : '#52525b' }}
              />
              {meta.name}
            </button>
          );
        })}
      </div>

      <select
        value={status}
        onChange={(e) => onStatusChange(e.target.value)}
        className="h-9 rounded-md border border-zinc-700 bg-zinc-900 px-3 text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-zinc-400"
      >
        <option value="active">Active</option>
        <option value="closed">Closed</option>
        <option value="resolved">Resolved</option>
        <option value="">All</option>
      </select>
    </div>
  );
}
