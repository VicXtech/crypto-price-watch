import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from api.config import settings

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600
)

# Session maker
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ensure_coin_exists(db: Session, coingecko_id: str, symbol: str, name: str) -> int:
    """
    Inserts a coin if it does not exist, and returns its database ID.
    Idempotent using ON CONFLICT.
    """
    query_insert = text("""
        INSERT INTO coins (coingecko_id, symbol, name)
        VALUES (:coingecko_id, :symbol, :name)
        ON CONFLICT (coingecko_id) DO NOTHING;
    """)
    db.execute(query_insert, {
        "coingecko_id": coingecko_id,
        "symbol": symbol.upper(),
        "name": name
    })
    db.commit()

    query_select = text("""
        SELECT id FROM coins WHERE coingecko_id = :coingecko_id;
    """)
    result = db.execute(query_select, {"coingecko_id": coingecko_id}).fetchone()
    if result:
        return result[0]
    raise ValueError(f"Failed to find or insert coin: {coingecko_id}")

def insert_price_history(
    db: Session,
    coin_id: int,
    current_price: float,
    market_cap: float | None,
    total_volume: float | None,
    collected_at
) -> bool:
    """
    Inserts a raw price history point. Returns True if inserted, False if conflict.
    """
    query = text("""
        INSERT INTO price_history (coin_id, current_price, market_cap, total_volume, collected_at)
        VALUES (:coin_id, :current_price, :market_cap, :total_volume, :collected_at)
        ON CONFLICT (coin_id, collected_at) DO NOTHING;
    """)
    result = db.execute(query, {
        "coin_id": coin_id,
        "current_price": current_price,
        "market_cap": market_cap,
        "total_volume": total_volume,
        "collected_at": collected_at
    })
    db.commit()
    return result.rowcount > 0

def insert_features(
    db: Session,
    coin_id: int,
    collected_at,
    sma_6h: float | None,
    ema_24h: float | None,
    pct_change_1h: float | None,
    volatility_24h: float | None
) -> bool:
    """
    Inserts computed features. Returns True if inserted, False if conflict.
    """
    query = text("""
        INSERT INTO price_features (coin_id, collected_at, sma_6h, ema_24h, pct_change_1h, volatility_24h)
        VALUES (:coin_id, :collected_at, :sma_6h, :ema_24h, :pct_change_1h, :volatility_24h)
        ON CONFLICT (coin_id, collected_at) DO NOTHING;
    """)
    result = db.execute(query, {
        "coin_id": coin_id,
        "collected_at": collected_at,
        "sma_6h": sma_6h,
        "ema_24h": ema_24h,
        "pct_change_1h": pct_change_1h,
        "volatility_24h": volatility_24h
    })
    db.commit()
    return result.rowcount > 0

def insert_anomaly(
    db: Session,
    coin_id: int,
    detected_at,
    current_price: float,
    anomaly_score: float,
    alert_sent: bool = False
) -> int:
    """
    Inserts a detected anomaly.
    """
    query = text("""
        INSERT INTO anomalies (coin_id, detected_at, current_price, anomaly_score, alert_sent)
        VALUES (:coin_id, :detected_at, :current_price, :anomaly_score, :alert_sent)
        RETURNING id;
    """)
    result = db.execute(query, {
        "coin_id": coin_id,
        "detected_at": detected_at,
        "current_price": current_price,
        "anomaly_score": anomaly_score,
        "alert_sent": alert_sent
    })
    db.commit()
    row = result.fetchone()
    return row[0] if row else None

def get_active_coins(db: Session):
    """
    Returns all active coins.
    """
    query = text("SELECT id, coingecko_id, symbol, name FROM coins WHERE active = TRUE;")
    return [dict(row._mapping) for row in db.execute(query).fetchall()]

def get_recent_prices_df(db: Session, coin_id: int, limit: int = 100) -> pd.DataFrame:
    """
    Retrieves recent prices as a pandas DataFrame ordered by collected_at ASC.
    """
    query = text("""
        SELECT current_price, collected_at
        FROM price_history
        WHERE coin_id = :coin_id
        ORDER BY collected_at DESC
        LIMIT :limit;
    """)
    result = db.execute(query, {"coin_id": coin_id, "limit": limit}).fetchall()
    df = pd.DataFrame([dict(row._mapping) for row in result])
    if not df.empty:
        df = df.sort_values(by="collected_at").reset_index(drop=True)
    return df

def get_recent_features_df(db: Session, coin_id: int, limit: int = 500) -> pd.DataFrame:
    """
    Retrieves recent features for inference/training by joining price_features and price_history.
    """
    query = text("""
        SELECT pf.sma_6h, pf.ema_24h, pf.pct_change_1h, pf.volatility_24h, pf.collected_at, ph.current_price
        FROM price_features pf
        JOIN price_history ph ON pf.coin_id = ph.coin_id AND pf.collected_at = ph.collected_at
        WHERE pf.coin_id = :coin_id
        ORDER BY pf.collected_at DESC
        LIMIT :limit;
    """)
    result = db.execute(query, {"coin_id": coin_id, "limit": limit}).fetchall()
    df = pd.DataFrame([dict(row._mapping) for row in result])
    if not df.empty:
        df = df.sort_values(by="collected_at").reset_index(drop=True)
    return df
