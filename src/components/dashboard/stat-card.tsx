'use client';

import * as React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { ArrowDown, ArrowUp, Minus } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  change?: number;
  icon?: React.ComponentType<{ className?: string }>;
  variant?: 'default' | 'warning' | 'danger' | 'success';
  subtitle?: string;
  footer?: React.ReactNode;
}

const variantStyles: Record<NonNullable<StatCardProps['variant']>, string> = {
  default: 'border-zinc-800 bg-zinc-900/50',
  warning: 'border-amber-900/50 bg-amber-950/20',
  danger: 'border-red-900/50 bg-red-950/20',
  success: 'border-emerald-900/50 bg-emerald-950/20',
};

const iconStyles: Record<NonNullable<StatCardProps['variant']>, string> = {
  default: 'bg-zinc-800 text-zinc-300',
  warning: 'bg-amber-600/20 text-amber-400',
  danger: 'bg-red-600/20 text-red-400',
  success: 'bg-emerald-600/20 text-emerald-400',
};

export function StatCard({
  title,
  value,
  change,
  icon: Icon,
  variant = 'default',
  subtitle,
  footer,
}: StatCardProps) {
  const hasChange = typeof change === 'number' && Number.isFinite(change);
  const isPositive = hasChange && change! > 0;
  const isNegative = hasChange && change! < 0;

  return (
    <Card className={cn('transition-colors', variantStyles[variant])}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
              {title}
            </p>
            <div className="mt-2 flex items-baseline gap-2">
              <p className="truncate font-mono text-2xl font-semibold text-zinc-50">
                {value}
              </p>
              {hasChange && (
                <span
                  className={cn(
                    'inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-medium',
                    isPositive && 'bg-emerald-500/10 text-emerald-400',
                    isNegative && 'bg-red-500/10 text-red-400',
                    !isPositive && !isNegative && 'bg-zinc-800 text-zinc-400'
                  )}
                >
                  {isPositive ? (
                    <ArrowUp className="h-3 w-3" />
                  ) : isNegative ? (
                    <ArrowDown className="h-3 w-3" />
                  ) : (
                    <Minus className="h-3 w-3" />
                  )}
                  {Math.abs(change!).toFixed(1)}%
                </span>
              )}
            </div>
            {subtitle && (
              <p className="mt-1 truncate text-xs text-zinc-500">{subtitle}</p>
            )}
          </div>
          {Icon && (
            <div
              className={cn(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                iconStyles[variant]
              )}
            >
              <Icon className="h-5 w-5" />
            </div>
          )}
        </div>
        {footer && <div className="mt-4 border-t border-zinc-800 pt-3">{footer}</div>}
      </CardContent>
    </Card>
  );
}
