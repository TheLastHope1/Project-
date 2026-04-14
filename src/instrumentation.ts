export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    try {
      // Ensure DB schema exists by creating tables if they don't
      const { getDb } = await import('@/lib/db');
      const db = getDb();
      // Run migrations/push
      const Database = (await import('better-sqlite3')).default;
      const path = (await import('path')).default;
      const fs = (await import('fs')).default;

      const dataDir = path.join(process.cwd(), 'data');
      if (!fs.existsSync(dataDir)) {
        fs.mkdirSync(dataDir, { recursive: true });
      }

      const sqlite = new Database(path.join(dataDir, 'markets.db'));
      sqlite.exec(`
        CREATE TABLE IF NOT EXISTS markets (
          id TEXT PRIMARY KEY,
          platform TEXT NOT NULL,
          platform_market_id TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT,
          category TEXT,
          url TEXT NOT NULL,
          image_url TEXT,
          yes_price REAL,
          no_price REAL,
          last_trade_price REAL,
          volume REAL,
          volume_24h REAL,
          liquidity REAL,
          status TEXT NOT NULL,
          resolution TEXT,
          close_date INTEGER,
          resolved_at INTEGER,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          outcomes TEXT,
          outcome_prices TEXT,
          token_ids TEXT,
          match_group_id TEXT
        );

        CREATE TABLE IF NOT EXISTS price_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_id TEXT NOT NULL REFERENCES markets(id),
          yes_price REAL NOT NULL,
          volume REAL,
          timestamp INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS price_market_ts_idx ON price_snapshots(market_id, timestamp);

        CREATE TABLE IF NOT EXISTS trades (
          id TEXT PRIMARY KEY,
          platform TEXT NOT NULL,
          market_id TEXT NOT NULL REFERENCES markets(id),
          platform_trade_id TEXT NOT NULL,
          side TEXT NOT NULL,
          outcome TEXT NOT NULL,
          price REAL NOT NULL,
          size REAL NOT NULL,
          amount REAL NOT NULL,
          trader_address TEXT,
          trader_username TEXT,
          timestamp INTEGER NOT NULL,
          transaction_hash TEXT,
          is_anomalous INTEGER DEFAULT 0,
          anomaly_type TEXT,
          anomaly_score REAL
        );
        CREATE INDEX IF NOT EXISTS trades_market_idx ON trades(market_id);
        CREATE INDEX IF NOT EXISTS trades_timestamp_idx ON trades(timestamp);
        CREATE INDEX IF NOT EXISTS trades_trader_idx ON trades(trader_address);
        CREATE INDEX IF NOT EXISTS trades_anomaly_idx ON trades(is_anomalous);

        CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          match_group_id TEXT NOT NULL,
          market_a_id TEXT NOT NULL REFERENCES markets(id),
          market_b_id TEXT NOT NULL REFERENCES markets(id),
          market_a_yes_price REAL NOT NULL,
          market_b_no_price REAL NOT NULL,
          spread REAL NOT NULL,
          spread_percent REAL NOT NULL,
          estimated_profit REAL,
          type TEXT NOT NULL,
          status TEXT NOT NULL,
          detected_at INTEGER NOT NULL,
          expired_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS tracked_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          platform TEXT NOT NULL,
          account_id TEXT NOT NULL,
          username TEXT,
          total_trades INTEGER DEFAULT 0,
          profitable_trades INTEGER DEFAULT 0,
          accuracy REAL,
          total_pnl REAL,
          avg_timing_advantage REAL,
          suspicion_score REAL,
          early_mover_count INTEGER DEFAULT 0,
          is_whale INTEGER DEFAULT 0,
          is_tracked INTEGER DEFAULT 1,
          first_seen INTEGER,
          last_seen INTEGER,
          updated_at INTEGER
        );
        CREATE UNIQUE INDEX IF NOT EXISTS tracked_platform_account_idx ON tracked_accounts(platform, account_id);
        CREATE INDEX IF NOT EXISTS tracked_suspicion_idx ON tracked_accounts(suspicion_score);

        CREATE TABLE IF NOT EXISTS anomalies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_id TEXT NOT NULL REFERENCES markets(id),
          type TEXT NOT NULL,
          severity TEXT NOT NULL,
          score REAL NOT NULL,
          description TEXT NOT NULL,
          details TEXT,
          related_trade_ids TEXT,
          related_account_id TEXT,
          detected_at INTEGER NOT NULL,
          acknowledged INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS anomaly_market_idx ON anomalies(market_id);
        CREATE INDEX IF NOT EXISTS anomaly_type_idx ON anomalies(type);
        CREATE INDEX IF NOT EXISTS anomaly_severity_idx ON anomalies(severity);

        CREATE TABLE IF NOT EXISTS news_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          summary TEXT,
          url TEXT NOT NULL,
          source TEXT NOT NULL,
          image_url TEXT,
          published_at INTEGER NOT NULL,
          fetched_at INTEGER NOT NULL,
          related_market_ids TEXT,
          relevance_score REAL,
          keywords TEXT
        );

        CREATE TABLE IF NOT EXISTS match_groups (
          id TEXT PRIMARY KEY,
          canonical_title TEXT NOT NULL,
          category TEXT,
          market_count INTEGER DEFAULT 0,
          created_at INTEGER NOT NULL
        );
      `);
      sqlite.close();

      console.log('[instrumentation] Database ready');

      const { startScheduler } = await import('@/lib/scheduler');
      startScheduler();
    } catch (err) {
      console.error('[instrumentation] Failed to initialize:', err);
    }
  }
}
