import os
import sys
import logging
import joblib
from sklearn.ensemble import IsolationForest
import pandas as pd

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.db import SessionLocal, get_active_coins, get_recent_features_df

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("train_model")

def train_all():
    """
    Trains an Isolation Forest model for each active coin that has enough historical data.
    Saves a dictionary of the trained models to disk.
    """
    db = SessionLocal()
    try:
        active_coins = get_active_coins(db)
        if not active_coins:
            logger.warning("No active coins found in the database. Skipping training.")
            return

        models_dict = {}

        # If a model file already exists, we load it first to retain models of coins that we might
        # skip training for in this run (e.g. if they don't have enough recent data, but had a model before).
        if os.path.exists(settings.MODEL_PATH):
            try:
                models_dict = joblib.load(settings.MODEL_PATH)
                if not isinstance(models_dict, dict):
                    models_dict = {}
            except Exception as e:
                logger.warning(f"Could not load existing model file: {e}. Starting fresh.")
                models_dict = {}

        trained_count = 0

        for coin in active_coins:
            coin_id = coin["id"]
            coingecko_id = coin["coingecko_id"]
            symbol = coin["symbol"]

            logger.info(f"Checking features for {name_or_symbol(coin)} (id={coin_id}) to train model...")

            # Retrieve up to 2000 feature records for this coin to train the model
            df = get_recent_features_df(db, coin_id, limit=2000)
            
            if df.empty or len(df) < settings.MIN_SAMPLES_TRAIN:
                logger.warning(
                    f"Coin {name_or_symbol(coin)} has insufficient data for training: "
                    f"{len(df)}/{settings.MIN_SAMPLES_TRAIN} records. Skipping."
                )
                continue

            # Convert columns to numeric float (from Decimal) and drop rows where critical features are missing
            required_cols = ["pct_change_1h", "volatility_24h", "current_price", "ema_24h"]
            df_clean = df.copy()
            for col in required_cols:
                df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce")
            df_clean = df_clean.dropna(subset=required_cols).copy()

            if len(df_clean) < settings.MIN_SAMPLES_TRAIN:
                logger.warning(
                    f"Coin {name_or_symbol(coin)} has insufficient clean data after dropping NaNs: "
                    f"{len(df_clean)}/{settings.MIN_SAMPLES_TRAIN}. Skipping."
                )
                continue

            # Compute price_norm: percent deviation of the price from its 24h EMA
            df_clean["price_norm"] = (df_clean["current_price"] / df_clean["ema_24h"]) - 1.0

            # Features to fit
            feature_cols = ["pct_change_1h", "volatility_24h", "price_norm"]
            X = df_clean[feature_cols]

            logger.info(f"Training Isolation Forest model for {name_or_symbol(coin)} with {len(df_clean)} samples...")
            
            # Train Isolation Forest
            model = IsolationForest(
                contamination=settings.ANOMALY_CONTAMINATION,
                random_state=42,
                n_jobs=-1
            )
            model.fit(X)

            # Store the trained model
            models_dict[coingecko_id] = model
            trained_count += 1
            logger.info(f"Model successfully trained for {name_or_symbol(coin)}.")

        # Ensure the output directory and model file exist on disk
        os.makedirs(os.path.dirname(settings.MODEL_PATH), exist_ok=True)
        joblib.dump(models_dict, settings.MODEL_PATH)

        if trained_count > 0:
            logger.info(f"All done! Saved {trained_count} trained models to {settings.MODEL_PATH}")
        else:
            logger.info(f"No models were trained/updated in this run. Saved cache (empty/existing) to {settings.MODEL_PATH}")

    finally:
        db.close()

def name_or_symbol(coin: dict) -> str:
    return f"{coin['name']} ({coin['symbol']})"

if __name__ == "__main__":
    train_all()
