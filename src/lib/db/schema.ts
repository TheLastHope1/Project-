import { sqliteTable, text, integer, real, index, uniqueIndex } from 'drizzle-orm/sqlite-core';

export const markets = sqliteTable('markets', {
  id: text('id').primaryKey(), // "{platform}_{platformMarketId}"
  platform: text('platform').notNull(),
  platformMarketId: text('platform_market_id').notNull(),
  title: text('title').notNull(),
  description: text('description'),
  category: text('category'),
  url: text('url').notNull(),
  imageUrl: text('image_url'),
  yesPrice: real('yes_price'),
  noPrice: real('no_price'),
  lastTradePrice: real('last_trade_price'),
  volume: real('volume'),
  volume24h: real('volume_24h'),
  liquidity: real('liquidity'),
  status: text('status', { enum: ['active', 'closed', 'resolved'] }).notNull().default('active'),
  resolution: text('resolution'),
  closeDate: integer('close_date'),
  resolvedAt: integer('resolved_at'),
  createdAt: integer('created_at').notNull(),
  updatedAt: integer('updated_at').notNull(),
  outcomes: text('outcomes', { mode: 'json' }),
  outcomePrices: text('outcome_prices', { mode: 'json' }),
  tokenIds: text('token_ids', { mode: 'json' }),
  matchGroupId: text('match_group_id'),
});

export const priceSnapshots = sqliteTable('price_snapshots', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  marketId: text('market_id').notNull().references(() => markets.id),
  yesPrice: real('yes_price'),
  volume: real('volume'),
  timestamp: integer('timestamp').notNull(),
}, (table) => ({
  marketTimestampIdx: index('price_snapshots_market_timestamp_idx').on(table.marketId, table.timestamp),
}));

export const trades = sqliteTable('trades', {
  id: text('id').primaryKey(),
  platform: text('platform').notNull(),
  marketId: text('market_id').notNull().references(() => markets.id),
  platformTradeId: text('platform_trade_id').notNull(),
  side: text('side').notNull(),
  outcome: text('outcome').notNull(),
  price: real('price').notNull(),
  size: real('size').notNull(),
  amount: real('amount').notNull(),
  traderAddress: text('trader_address'),
  traderUsername: text('trader_username'),
  timestamp: integer('timestamp').notNull(),
  transactionHash: text('transaction_hash'),
  isAnomalous: integer('is_anomalous', { mode: 'boolean' }).default(false),
  anomalyType: text('anomaly_type'),
  anomalyScore: real('anomaly_score'),
}, (table) => ({
  marketIdIdx: index('trades_market_id_idx').on(table.marketId),
  timestampIdx: index('trades_timestamp_idx').on(table.timestamp),
  traderAddressIdx: index('trades_trader_address_idx').on(table.traderAddress),
  isAnomalousIdx: index('trades_is_anomalous_idx').on(table.isAnomalous),
}));

export const arbitrageOpportunities = sqliteTable('arbitrage_opportunities', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  matchGroupId: text('match_group_id').notNull(),
  marketAId: text('market_a_id').notNull().references(() => markets.id),
  marketBId: text('market_b_id').notNull().references(() => markets.id),
  marketAYesPrice: real('market_a_yes_price').notNull(),
  marketBNoPrice: real('market_b_no_price').notNull(),
  spread: real('spread').notNull(),
  spreadPercent: real('spread_percent').notNull(),
  estimatedProfit: real('estimated_profit'),
  type: text('type').notNull(),
  status: text('status').notNull(),
  detectedAt: integer('detected_at').notNull(),
  expiredAt: integer('expired_at'),
});

export const trackedAccounts = sqliteTable('tracked_accounts', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  platform: text('platform').notNull(),
  accountId: text('account_id').notNull(),
  username: text('username'),
  totalTrades: integer('total_trades').default(0),
  profitableTrades: integer('profitable_trades').default(0),
  accuracy: real('accuracy'),
  totalPnl: real('total_pnl'),
  avgTimingAdvantage: real('avg_timing_advantage'),
  suspicionScore: real('suspicion_score'),
  earlyMoverCount: integer('early_mover_count').default(0),
  isWhale: integer('is_whale', { mode: 'boolean' }).default(false),
  isTracked: integer('is_tracked', { mode: 'boolean' }).default(true),
  firstSeen: integer('first_seen'),
  lastSeen: integer('last_seen'),
  updatedAt: integer('updated_at'),
}, (table) => ({
  platformAccountIdx: uniqueIndex('tracked_accounts_platform_account_idx').on(table.platform, table.accountId),
  suspicionScoreIdx: index('tracked_accounts_suspicion_score_idx').on(table.suspicionScore),
}));

export const anomalies = sqliteTable('anomalies', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  marketId: text('market_id').notNull().references(() => markets.id),
  type: text('type').notNull(),
  severity: text('severity').notNull(),
  score: real('score').notNull(),
  description: text('description').notNull(),
  details: text('details', { mode: 'json' }),
  relatedTradeIds: text('related_trade_ids', { mode: 'json' }),
  relatedAccountId: text('related_account_id'),
  detectedAt: integer('detected_at').notNull(),
  acknowledged: integer('acknowledged', { mode: 'boolean' }).default(false),
}, (table) => ({
  marketIdIdx: index('anomalies_market_id_idx').on(table.marketId),
  typeIdx: index('anomalies_type_idx').on(table.type),
  severityIdx: index('anomalies_severity_idx').on(table.severity),
}));

export const newsItems = sqliteTable('news_items', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  title: text('title').notNull(),
  summary: text('summary'),
  url: text('url').notNull(),
  source: text('source').notNull(),
  imageUrl: text('image_url'),
  publishedAt: integer('published_at').notNull(),
  fetchedAt: integer('fetched_at').notNull(),
  relatedMarketIds: text('related_market_ids', { mode: 'json' }),
  relevanceScore: real('relevance_score'),
  keywords: text('keywords', { mode: 'json' }),
});

export const matchGroups = sqliteTable('match_groups', {
  id: text('id').primaryKey(),
  canonicalTitle: text('canonical_title').notNull(),
  category: text('category'),
  marketCount: integer('market_count').default(0),
  createdAt: integer('created_at').notNull(),
});
