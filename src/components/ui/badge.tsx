import * as React from 'react';
import { cn } from '@/lib/utils/cn';

interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning';
}

function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors',
        variant === 'default' && 'border-transparent bg-zinc-50 text-zinc-900',
        variant === 'secondary' && 'border-transparent bg-zinc-800 text-zinc-300',
        variant === 'destructive' && 'border-transparent bg-red-600/20 text-red-400',
        variant === 'outline' && 'border-zinc-700 text-zinc-300',
        variant === 'success' && 'border-transparent bg-emerald-600/20 text-emerald-400',
        variant === 'warning' && 'border-transparent bg-amber-600/20 text-amber-400',
        className
      )}
      {...props}
    />
  );
}

export { Badge };
export type { BadgeProps };
