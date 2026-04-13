import type {
  Platform,
  NormalizedMarket,
  NormalizedTrade,
  PlatformFetcher,
  PlatformStatus,
} from './types';

import { polymarketFetcher } from './polymarket';
import { manifoldFetcher } from './manifold';
import { kalshiFetcher } from './kalshi';
import { predictitFetcher } from './predictit';

// Re-export individual fetchers for direct use
export { polymarketFetcher } from './polymarket';
export { manifoldFetcher } from './manifold';
export { kalshiFetcher } from './kalshi';
export { predictitFetcher } from './predictit';
export type { Platform, NormalizedMarket, NormalizedTrade, PlatformStatus } from './types';

const fetchers: Record<Platform, PlatformFetcher> = {
  polymarket: polymarketFetcher,
  manifold: manifoldFetcher,
  kalshi: kalshiFetcher,
  predictit: predictitFetcher,
};

// Module-level platform status tracking
const platformStatuses: Record<Platform, PlatformStatus> = {
  polymarket: { platform: 'polymarket', isConnected: false, lastFetch: null, marketCount: 0 },
  manifold: { platform: 'manifold', isConnected: false, lastFetch: null, marketCount: 0 },
  kalshi: { platform: 'kalshi', isConnected: false, lastFetch: null, marketCount: 0 },
  predictit: { platform: 'predictit', isConnected: false, lastFetch: null, marketCount: 0 },
};

const FETCH_TIMEOUT_MS = 10_000;

/**
 * Wraps a promise with a timeout using AbortController.
 * When the timeout expires, the AbortController signal is aborted and the
 * promise races against the timeout rejection.
 */
function withTimeout<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  label: string,
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  return fn(controller.signal)
    .catch((err) => {
      if (controller.signal.aborted) {
        throw new Error(`[${label}] Fetch timed out after ${timeoutMs}ms`);
      }
      throw err;
    })
    .finally(() => clearTimeout(timeoutId));
}

/**
 * Convenience wrapper for fetchers that don't use the AbortSignal directly.
 * Races the fetcher promise against an AbortController-based timeout.
 */
function promiseWithTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  return withTimeout(
    () => promise,
    timeoutMs,
    label,
  );
}

/**
 * Fetch markets from all platforms concurrently.
 * Uses Promise.allSettled so one platform failure doesn't block others.
 */
export async function fetchAllMarkets(
  params?: { limit?: number },
): Promise<NormalizedMarket[]> {
  const platforms = Object.keys(fetchers) as Platform[];

  const results = await Promise.allSettled(
    platforms.map((platform) =>
      promiseWithTimeout(
        fetchers[platform].fetchMarkets({ limit: params?.limit }),
        FETCH_TIMEOUT_MS,
        platform,
      ),
    ),
  );

  const allMarkets: NormalizedMarket[] = [];

  for (let i = 0; i < platforms.length; i++) {
    const platform = platforms[i];
    const result = results[i];

    if (result.status === 'fulfilled') {
      const markets = result.value;
      allMarkets.push(...markets);

      platformStatuses[platform] = {
        platform,
        isConnected: true,
        lastFetch: new Date(),
        marketCount: markets.length,
      };
    } else {
      const errorMessage =
        result.reason instanceof Error ? result.reason.message : String(result.reason);
      console.error(`[${platform}] Failed to fetch markets:`, errorMessage);

      platformStatuses[platform] = {
        ...platformStatuses[platform],
        isConnected: false,
        error: errorMessage,
      };
    }
  }

  return allMarkets;
}

/**
 * Fetch trades for a specific market from the appropriate platform.
 */
export async function fetchAllTrades(
  marketId: string,
  platform: Platform,
  params?: { limit?: number; after?: Date },
): Promise<NormalizedTrade[]> {
  const fetcher = fetchers[platform];
  if (!fetcher) {
    console.error(`[fetchAllTrades] Unknown platform: ${platform}`);
    return [];
  }

  try {
    return await promiseWithTimeout(
      fetcher.fetchTrades(marketId, params),
      FETCH_TIMEOUT_MS,
      platform,
    );
  } catch (error) {
    console.error(`[${platform}] Failed to fetch trades for ${marketId}:`, error);
    return [];
  }
}

/**
 * Get the current connection status for all platforms.
 */
export function getPlatformStatuses(): PlatformStatus[] {
  return Object.values(platformStatuses);
}

/**
 * Get a specific platform fetcher by name.
 */
export function getFetcher(platform: Platform): PlatformFetcher {
  return fetchers[platform];
}
