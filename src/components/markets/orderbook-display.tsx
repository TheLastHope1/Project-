'use client';

import type { NormalizedOrderBook } from '@/lib/platforms/types';

interface OrderBookDisplayProps {
  orderBook: NormalizedOrderBook | null;
  loading?: boolean;
}

export function OrderBookDisplay({ orderBook, loading }: OrderBookDisplayProps) {
  if (loading) {
    return (
      <div className="rounded-md border border-zinc-800 bg-zinc-900/30 p-4 text-center text-sm text-zinc-500">
        Loading order book...
      </div>
    );
  }

  if (!orderBook) {
    return (
      <div className="rounded-md border border-dashed border-zinc-800 bg-zinc-900/20 p-4 text-center text-sm text-zinc-500">
        Order book not available for this market
      </div>
    );
  }

  const asks = [...orderBook.asks].slice(0, 5).reverse();
  const bids = [...orderBook.bids].slice(0, 5);
  const maxSize = Math.max(
    ...asks.map((a) => a.size),
    ...bids.map((b) => b.size),
    1,
  );

  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/30">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2 text-xs uppercase tracking-wider text-zinc-500">
        <span>Order Book</span>
        <span className="font-mono text-zinc-300">
          Spread: {(orderBook.spread * 100).toFixed(2)}¢
        </span>
      </div>
      <div className="divide-y divide-zinc-800">
        {asks.map((a, i) => (
          <div key={`ask-${i}`} className="relative flex items-center justify-between px-3 py-1.5">
            <div
              className="absolute right-0 top-0 bottom-0 bg-red-500/5"
              style={{ width: `${(a.size / maxSize) * 100}%` }}
            />
            <span className="relative font-mono text-xs text-red-400">
              {(a.price * 100).toFixed(1)}¢
            </span>
            <span className="relative font-mono text-xs text-zinc-400">
              {a.size.toFixed(0)}
            </span>
          </div>
        ))}
        <div className="flex items-center justify-center bg-zinc-800/50 px-3 py-1.5 font-mono text-xs text-zinc-400">
          Mid: {(orderBook.midpoint * 100).toFixed(2)}¢
        </div>
        {bids.map((b, i) => (
          <div key={`bid-${i}`} className="relative flex items-center justify-between px-3 py-1.5">
            <div
              className="absolute right-0 top-0 bottom-0 bg-emerald-500/5"
              style={{ width: `${(b.size / maxSize) * 100}%` }}
            />
            <span className="relative font-mono text-xs text-emerald-400">
              {(b.price * 100).toFixed(1)}¢
            </span>
            <span className="relative font-mono text-xs text-zinc-400">
              {b.size.toFixed(0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
