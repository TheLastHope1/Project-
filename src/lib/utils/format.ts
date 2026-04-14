export function formatPrice(price: number | null): string {
  if (price === null) return '—';
  return `${(price * 100).toFixed(1)}¢`;
}

export function formatPercent(value: number | null): string {
  if (value === null) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

export function formatUSD(amount: number | null): string {
  if (amount === null) return '—';
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `$${(amount / 1_000).toFixed(1)}K`;
  return `$${amount.toFixed(2)}`;
}

export function formatVolume(volume: number | null): string {
  if (volume === null) return '—';
  if (volume >= 1_000_000) return `${(volume / 1_000_000).toFixed(1)}M`;
  if (volume >= 1_000) return `${(volume / 1_000).toFixed(1)}K`;
  return volume.toFixed(0);
}

export function formatTimeAgo(date: Date | number): string {
  const now = Date.now();
  const ts = typeof date === 'number' ? date * 1000 : date.getTime();
  const seconds = Math.floor((now - ts) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatDate(date: Date | number): string {
  const d = typeof date === 'number' ? new Date(date * 1000) : date;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ');
}
