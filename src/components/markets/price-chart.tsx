'use client';

import * as React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
} from 'recharts';
import { formatPrice } from '@/lib/utils/format';

interface PricePoint {
  timestamp: number;
  yesPrice: number;
}

interface PriceChartProps {
  data: PricePoint[];
  height?: number;
  color?: string;
  showGrid?: boolean;
}

export function PriceChart({
  data,
  height = 300,
  color = '#6366f1',
  showGrid = true,
}: PriceChartProps) {
  if (!data || data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-md border border-dashed border-zinc-800 bg-zinc-950/40 text-sm text-zinc-500"
        style={{ height }}
      >
        No price history available
      </div>
    );
  }

  const gradientId = React.useId();

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={data}
        margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.4} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {showGrid && (
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#27272a"
            vertical={false}
          />
        )}
        <XAxis
          dataKey="timestamp"
          tickFormatter={(ts) =>
            new Date(ts).toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
            })
          }
          stroke="#52525b"
          tick={{ fill: '#a1a1aa', fontSize: 11 }}
          axisLine={{ stroke: '#27272a' }}
          tickLine={{ stroke: '#27272a' }}
        />
        <YAxis
          domain={[0, 1]}
          tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
          stroke="#52525b"
          tick={{ fill: '#a1a1aa', fontSize: 11 }}
          axisLine={{ stroke: '#27272a' }}
          tickLine={{ stroke: '#27272a' }}
          width={42}
        />
        <RechartsTooltip
          contentStyle={{
            backgroundColor: '#18181b',
            border: '1px solid #3f3f46',
            borderRadius: 6,
            fontSize: 12,
            color: '#fafafa',
          }}
          labelFormatter={(label) =>
            new Date(label).toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: 'numeric',
              minute: '2-digit',
            })
          }
          formatter={(value: number) => [formatPrice(value), 'YES Price']}
        />
        <Area
          type="monotone"
          dataKey="yesPrice"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
