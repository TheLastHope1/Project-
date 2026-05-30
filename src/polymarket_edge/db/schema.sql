CREATE TABLE IF NOT EXISTS events (
  id SERIAL PRIMARY KEY,
  event_id TEXT UNIQUE NOT NULL,
  slug TEXT,
  title TEXT,
  category TEXT,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  closed BOOLEAN NOT NULL DEFAULT FALSE,
  end_date TIMESTAMPTZ,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS markets (
  id SERIAL PRIMARY KEY,
  market_id TEXT UNIQUE NOT NULL,
  event_id TEXT,
  condition_id TEXT,
  slug TEXT,
  question TEXT,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  closed BOOLEAN NOT NULL DEFAULT FALSE,
  volume DOUBLE PRECISION NOT NULL DEFAULT 0,
  liquidity DOUBLE PRECISION NOT NULL DEFAULT 0,
  end_date TIMESTAMPTZ,
  resolution_rules TEXT,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tokens (
  id SERIAL PRIMARY KEY,
  token_id TEXT UNIQUE NOT NULL,
  market_id TEXT NOT NULL REFERENCES markets(market_id),
  condition_id TEXT,
  outcome TEXT,
  outcome_index INTEGER,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

