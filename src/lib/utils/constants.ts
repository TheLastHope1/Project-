export const PLATFORMS = {
  polymarket: { name: 'Polymarket', color: '#6366f1', shortName: 'PM' },
  manifold: { name: 'Manifold', color: '#8b5cf6', shortName: 'MF' },
  kalshi: { name: 'Kalshi', color: '#06b6d4', shortName: 'KL' },
  predictit: { name: 'PredictIt', color: '#f59e0b', shortName: 'PI' },
} as const;

export const POLLING_INTERVALS = {
  prices: 30_000,
  trades: 120_000,
  fullRefresh: 300_000,
  news: 600_000,
  insider: 900_000,
} as const;

export const ANOMALY_THRESHOLDS = {
  volumeSpikeMultiplier: 3,
  priceImpactThreshold: 0.05,
  whalePercentile: 95,
  burstTradeCount: 10,
  burstWindowSeconds: 60,
  minArbitrageSpread: 0.02,
} as const;

export const SEVERITY_COLORS = {
  low: '#22c55e',
  medium: '#f59e0b',
  high: '#ef4444',
  critical: '#dc2626',
} as const;
