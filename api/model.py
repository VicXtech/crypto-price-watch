import os
import joblib
import pandas as pd
import numpy as np
import logging
from api.config import settings

logger = logging.getLogger(__name__)

# In-memory dictionary containing serialized models per coin: {"bitcoin": IsolationForestModel, ...}
_MODELS_CACHE = {}

def load_models():
    """
    Loads models dictionary from disk into the in-memory cache.
    Handles file not found or corrupted file errors.
    """
    global _MODELS_CACHE
    path = settings.MODEL_PATH
    if os.path.exists(path):
        try:
            loaded = joblib.load(path)
            if isinstance(loaded, dict):
                _MODELS_CACHE = loaded
                logger.info(f"Successfully loaded models from {path}. Coions with models: {list(_MODELS_CACHE.keys())}")
            else:
                logger.warning(f"File {path} did not contain a dictionary. Initializing empty model cache.")
                _MODELS_CACHE = {}
        except Exception as e:
            logger.error(f"Error loading models from {path}: {e}. Initializing empty model cache.")
            _MODELS_CACHE = {}
    else:
        logger.info(f"Model file {path} not found. Starting with empty model cache.")
        _MODELS_CACHE = {}

def reload_models():
    """
    Reloads the models from disk.
    """
    load_models()

# Load models on module import
load_models()

def run_inference(
    coingecko_id: str,
    current_price: float | None,
    sma_6h: float | None,
    ema_24h: float | None,
    pct_change_1h: float | None,
    volatility_24h: float | None
) -> tuple[bool, float | None]:
    """
    Runs the isolation forest model for the given coingecko_id on the input features.
    Features:
      - pct_change_1h
      - volatility_24h
      - price_norm (computed as current_price / ema_24h - 1)

    Returns:
      (is_anomaly: bool, anomaly_score: float | None)
    """
    # 1. Check if model is cached for this coin
    model = _MODELS_CACHE.get(coingecko_id)
    if not model:
        logger.debug(f"No trained model found for coin '{coingecko_id}'")
        return False, None

    # 2. Check for missing features
    if (
        current_price is None or 
        ema_24h is None or 
        pct_change_1h is None or 
        volatility_24h is None or
        ema_24h == 0
    ):
        logger.debug(f"Missing feature values for coin '{coingecko_id}'. Inference skipped.")
        return False, None

    try:
        # Calculate price_norm (percent deviation from the 24h EMA)
        price_norm = (current_price / ema_24h) - 1.0

        # Construct input vector for scikit-learn
        # Features must be in the exact same order as training: pct_change_1h, volatility_24h, price_norm
        X = pd.DataFrame([{
            "pct_change_1h": pct_change_1h,
            "volatility_24h": volatility_24h,
            "price_norm": price_norm
        }])

        # Predict
        prediction = model.predict(X)[0]
        # decision_function score (raw anomaly score). Lower scores represent more anomalous points.
        score = float(model.decision_function(X)[0])

        is_anomaly = (prediction == -1)

        logger.info(f"Inference run for '{coingecko_id}': anomaly={is_anomaly}, score={score:.4f}")
        return is_anomaly, score

    except Exception as e:
        logger.error(f"Failed to run inference for '{coingecko_id}': {e}")
        return False, None
