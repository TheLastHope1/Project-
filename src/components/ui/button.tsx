import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cn } from '@/lib/utils/cn';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
  size?: 'default' | 'sm' | 'lg' | 'icon';
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        className={cn(
          'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-400 disabled:pointer-events-none disabled:opacity-50',
          variant === 'default' && 'bg-zinc-50 text-zinc-900 shadow hover:bg-zinc-200',
          variant === 'destructive' && 'bg-red-600 text-zinc-50 shadow-sm hover:bg-red-700',
          variant === 'outline' && 'border border-zinc-700 bg-transparent text-zinc-300 shadow-sm hover:bg-zinc-800',
          variant === 'secondary' && 'bg-zinc-800 text-zinc-300 shadow-sm hover:bg-zinc-700',
          variant === 'ghost' && 'text-zinc-300 hover:bg-zinc-800',
          variant === 'link' && 'text-zinc-300 underline-offset-4 hover:underline',
          size === 'default' && 'h-9 px-4 py-2',
          size === 'sm' && 'h-8 rounded-md px-3 text-xs',
          size === 'lg' && 'h-10 rounded-md px-8',
          size === 'icon' && 'h-9 w-9',
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';

export { Button };
export type { ButtonProps };
