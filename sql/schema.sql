CREATE TABLE IF NOT EXISTS coins (
    id SERIAL PRIMARY KEY,
    coingecko_id VARCHAR(50) UNIQUE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    name VARCHAR(100) NOT NULL,
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS price_history (
    id SERIAL PRIMARY KEY,
    coin_id INTEGER REFERENCES coins (id) ON DELETE CASCADE,
    current_price NUMERIC(18, 8) NOT NULL,
    market_cap NUMERIC(20, 2),
    total_volume NUMERIC(20, 2),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now (),
    UNIQUE (coin_id, collected_at)
);

CREATE TABLE IF NOT EXISTS price_features (
    id SERIAL PRIMARY KEY,
    coin_id INTEGER REFERENCES coins (id) ON DELETE CASCADE,
    collected_at TIMESTAMPTZ NOT NULL,
    sma_6h NUMERIC(18, 8), -- SMA 6h
    ema_24h NUMERIC(18, 8), -- EMA 24h
    pct_change_1h NUMERIC(8, 4),
    volatility_24h NUMERIC(8, 4),
    UNIQUE (coin_id, collected_at)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id SERIAL PRIMARY KEY,
    coin_id INTEGER REFERENCES coins (id) ON DELETE CASCADE,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now (),
    current_price NUMERIC(18, 8) NOT NULL,
    anomaly_score NUMERIC(6, 4), -- Isolation Forest anomaly score
    alert_sent BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_price_history_coin_time ON price_history (coin_id, collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_features_coin_time ON price_features (coin_id, collected_at DESC);