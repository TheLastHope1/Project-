'use client';

import * as React from 'react';
import { Search } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

export function Header() {
  return (
    <header className="flex h-12 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-4">
      {/* App title */}
      <div className="flex items-center gap-2">
        <h1 className="text-sm font-semibold tracking-wide text-zinc-100">
          Prediction Market Tracker
        </h1>
      </div>

      {/* Search */}
      <div className="flex max-w-md flex-1 items-center justify-center px-8">
        <div className="relative w-full">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            placeholder="Search markets..."
            className={cn(
              'h-8 w-full rounded-md border border-zinc-700 bg-zinc-900 pl-8 pr-3 text-sm text-zinc-100',
              'placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-400'
            )}
          />
        </div>
      </div>

      {/* Live status */}
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
        </span>
        <span className="text-xs font-medium text-zinc-400">Live</span>
      </div>
    </header>
  );
}
