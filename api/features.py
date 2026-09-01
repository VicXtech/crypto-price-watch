import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from api.config import settings

def calculate_features_for_latest(price_df: pd.DataFrame) -> dict:
    """
    Computes technical indicators for the latest price point in price_df.
    price_df MUST be sorted by collected_at in ASCENDING order.
    Returns a dictionary of features for the latest timestamp, or values as None 
    if there are insufficient samples.
    """
    default_result = {
        "sma_6h": None,
        "ema_24h": None,
        "pct_change_1h": None,
        "volatility_24h": None,
        "collected_at": None
    }

    if price_df.empty:
        return default_result

    # Latest record's timestamp
    latest_row = price_df.iloc[-1]
    default_result["collected_at"] = latest_row["collected_at"]

    # Check minimum samples threshold
    if len(price_df) < settings.MIN_SAMPLES_FEATURES:
        return default_result

    # Detect if there was a downtime gap (>2h) between this coleta and the previous one
    time_gap_detected = False
    if len(price_df) >= 2:
        try:
            prev_row = price_df.iloc[-2]
            t_latest = pd.to_datetime(latest_row["collected_at"])
            t_prev = pd.to_datetime(prev_row["collected_at"])
            if (t_latest - t_prev) > timedelta(hours=2):
                time_gap_detected = True
        except Exception:
            pass

    try:
        # Convert prices to numeric
        prices = pd.to_numeric(price_df["current_price"])

        # 1. Simple Moving Average 6h (SMA)
        sma_series = prices.rolling(window=settings.SMA_WINDOW, min_periods=settings.SMA_WINDOW).mean()
        
        # 2. Exponential Moving Average 24h (EMA)
        ema_series = prices.ewm(span=settings.EMA_WINDOW, min_periods=settings.EMA_WINDOW, adjust=False).mean()

        # 3. Percent Change 1h (1 period)
        # Note: fillna or simple pct_change. If prices are sorted hourly, periods=1 is 1h change.
        pct_change_series = prices.pct_change(periods=1)

        # 4. Volatility 24h
        # Standard deviation of 1h percent changes over the last 24 periods
        volatility_series = pct_change_series.rolling(window=settings.EMA_WINDOW, min_periods=settings.EMA_WINDOW).std()

        # Extract latest values
        latest_sma = sma_series.iloc[-1]
        latest_ema = ema_series.iloc[-1]
        latest_pct = pct_change_series.iloc[-1]
        latest_vol = volatility_series.iloc[-1]

        # Replace NaN/inf with None for DB inserting
        result = {
            "sma_6h": float(latest_sma) if not pd.isna(latest_sma) else None,
            "ema_24h": float(latest_ema) if not pd.isna(latest_ema) else None,
            "pct_change_1h": float(latest_pct) if not pd.isna(latest_pct) and not np.isinf(latest_pct) else None,
            "volatility_24h": float(latest_vol) if not pd.isna(latest_vol) else None,
            "collected_at": latest_row["collected_at"],
            "time_gap_detected": time_gap_detected
        }
        return result

    except Exception as e:
        # Avoid crashing features pipeline, fallback to defaults
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error calculating features: {e}")
        return default_result

def compute_all_features_df(price_df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes features for a whole historical DataFrame.
    Used for batch feature calculation (e.g. initial setup or backfilling).
    price_df MUST be sorted by collected_at in ASCENDING order.
    """
    if len(price_df) < settings.MIN_SAMPLES_FEATURES:
        empty_df = price_df.copy()
        for col in ["sma_6h", "ema_24h", "pct_change_1h", "volatility_24h"]:
            empty_df[col] = None
        return empty_df

    df = price_df.copy()
    prices = pd.to_numeric(df["current_price"])

    df["sma_6h"] = prices.rolling(window=settings.SMA_WINDOW, min_periods=settings.SMA_WINDOW).mean()
    df["ema_24h"] = prices.ewm(span=settings.EMA_WINDOW, min_periods=settings.EMA_WINDOW, adjust=False).mean()
    df["pct_change_1h"] = prices.pct_change(periods=1)
    df["volatility_24h"] = df["pct_change_1h"].rolling(window=settings.EMA_WINDOW, min_periods=settings.EMA_WINDOW).std()

    # Replace NaNs/Infs with None/NaN so it plays nice with SQL database insertion
    df = df.replace([np.inf, -np.inf], np.nan)
    return df
