import { create } from 'zustand';

interface SettingsState {
  pollingIntervals: {
    prices: number;
    trades: number;
    fullRefresh: number;
    news: number;
    insider: number;
  };
  enabledPlatforms: {
    polymarket: boolean;
    manifold: boolean;
    kalshi: boolean;
    predictit: boolean;
  };
  anomalyThresholds: {
    minArbitrageSpread: number;
    volumeSpikeMultiplier: number;
    priceImpactThreshold: number;
  };
  updatePollingInterval: (key: string, value: number) => void;
  togglePlatform: (platform: string) => void;
  updateThreshold: (key: string, value: number) => void;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  pollingIntervals: {
    prices: 30_000,
    trades: 120_000,
    fullRefresh: 300_000,
    news: 600_000,
    insider: 900_000,
  },
  enabledPlatforms: {
    polymarket: true,
    manifold: true,
    kalshi: true,
    predictit: true,
  },
  anomalyThresholds: {
    minArbitrageSpread: 0.02,
    volumeSpikeMultiplier: 3,
    priceImpactThreshold: 0.05,
  },
  updatePollingInterval: (key, value) =>
    set((state) => ({
      pollingIntervals: { ...state.pollingIntervals, [key]: value },
    })),
  togglePlatform: (platform) =>
    set((state) => ({
      enabledPlatforms: {
        ...state.enabledPlatforms,
        [platform]: !state.enabledPlatforms[platform as keyof typeof state.enabledPlatforms],
      },
    })),
  updateThreshold: (key, value) =>
    set((state) => ({
      anomalyThresholds: { ...state.anomalyThresholds, [key]: value },
    })),
}));
