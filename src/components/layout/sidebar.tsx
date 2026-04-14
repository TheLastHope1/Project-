'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  TrendingUp,
  ArrowLeftRight,
  AlertTriangle,
  BarChart3,
  Newspaper,
  Eye,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils/cn';

const navItems = [
  { label: 'Dashboard', href: '/', icon: LayoutDashboard },
  { label: 'Markets', href: '/markets', icon: TrendingUp },
  { label: 'Arbitrage', href: '/arbitrage', icon: ArrowLeftRight },
  { label: 'Unusual Trades', href: '/unusual-trades', icon: AlertTriangle },
  { label: 'Probability', href: '/probability', icon: BarChart3 },
  { label: 'News', href: '/news', icon: Newspaper },
  { label: 'Insider Tracking', href: '/insider-tracking', icon: Eye },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);

  return (
    <aside
      className={cn(
        'flex flex-col border-r border-zinc-800 bg-zinc-950 transition-all duration-200',
        collapsed ? 'w-16' : 'w-56'
      )}
    >
      {/* Nav links */}
      <nav className="flex-1 space-y-1 px-2 py-4">
        {navItems.map(({ label, href, icon: Icon }) => {
          const isActive =
            href === '/' ? pathname === '/' : pathname.startsWith(href);

          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200'
              )}
              title={collapsed ? label : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-zinc-800 p-2">
        <button
          onClick={() => setCollapsed((prev) => !prev)}
          className="flex w-full items-center justify-center rounded-md p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </button>
      </div>
    </aside>
  );
}
