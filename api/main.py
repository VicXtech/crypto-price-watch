from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
import logging
from typing import Dict, Any, List, Union
from zoneinfo import ZoneInfo

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

from api.config import settings
from api.db import (
    get_db,
    ensure_coin_exists,
    insert_price_history,
    get_recent_prices_df,
    insert_features,
    insert_anomaly,
    mark_anomaly_alert_sent
)
from api.etl import normalize_prices
from api.features import calculate_features_for_latest
from api.model import run_inference, reload_models
from ml.train_model import train_all

# Configure logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("api_main")

app = FastAPI(title="Crypto Price Watch API", version="1.0.0")

@app.get("/health")
def health_check():
    """
    Simple health check endpoint.
    """
    return {"status": "ok"}

@app.post("/ingest")
def ingest_prices(payload: Union[List[Dict[str, Any]], Dict[str, Any]], db: Session = Depends(get_db)):
    """
    Ingests price data from CoinGecko (/coins/markets or /simple/price), computes features,
    runs ML inference to detect anomalies, and returns a summary status.
    """
    logger.info("Received price ingestion request.")
    try:
        # 1. Normalize input payload (supports list or dict from n8n / CoinGecko)
        normalized_data = normalize_prices(payload)
        if not normalized_data:
            logger.warning("No valid price data normalized from payload.")
            return {"status": "success", "processed_coins": 0, "anomalies_detected": []}

        anomalies_detected = []
        processed_coins = 0

        # 2. Process each coin in the ingestion payload
        for data in normalized_data:
            coingecko_id = data["coingecko_id"]
            symbol = data["symbol"]
            name = data["name"]
            current_price = data["current_price"]
            market_cap = data["market_cap"]
            total_volume = data["total_volume"]
            collected_at = data["collected_at"]

            # Step 2a: Ensure coin is registered in coins table
            coin_id = ensure_coin_exists(db, coingecko_id, symbol, name)

            # Step 2b: Write raw price data to price_history
            inserted = insert_price_history(db, coin_id, current_price, market_cap, total_volume, collected_at)
            
            # If this specific point is already recorded (e.g. retry / manual trigger), we still continue,
            # but log a debug message.
            if not inserted:
                logger.debug(f"Data point for {coingecko_id} at {collected_at} already exists. Skipping duplicate insert.")

            # Step 2c: Retrieve recent prices to calculate features
            # Fetch up to max of settings.EMA_WINDOW + 24 to have plenty of headroom for calculations
            fetch_limit = max(settings.SMA_WINDOW, settings.EMA_WINDOW, 24) * 2
            price_df = get_recent_prices_df(db, coin_id, limit=fetch_limit)

            # Step 2d: Compute features for the latest point
            features = calculate_features_for_latest(price_df)

            if features["sma_6h"] is not None and features["ema_24h"] is not None:
                # Step 2e: Write features to price_features table
                insert_features(
                    db,
                    coin_id,
                    collected_at,
                    features["sma_6h"],
                    features["ema_24h"],
                    features["pct_change_1h"],
                    features["volatility_24h"]
                )

                # Step 2f: Run ML inference
                if features.get("time_gap_detected"):
                    logger.info(
                        f"Downtime gap detected (>2h) for {coingecko_id}. "
                        "Skipping anomaly inference for this resumed point to prevent false positives."
                    )
                    is_anomaly, score = False, None
                else:
                    is_anomaly, score = run_inference(
                        coingecko_id,
                        current_price,
                        features["sma_6h"],
                        features["ema_24h"],
                        features["pct_change_1h"],
                        features["volatility_24h"]
                    )

                if is_anomaly:
                    # Save anomaly to the database
                    anomaly_id = insert_anomaly(
                        db,
                        coin_id,
                        collected_at,
                        current_price,
                        score,
                        alert_sent=False  # Initial state: pending delivery confirmation from n8n
                    )
                    detected_at_sp = collected_at.astimezone(BRASILIA_TZ)
                    anomalies_detected.append({
                        "anomaly_id": anomaly_id,
                        "coingecko_id": coingecko_id,
                        "symbol": symbol,
                        "current_price": current_price,
                        "anomaly_score": score,
                        "detected_at": collected_at.isoformat(),
                        "detected_at_brasilia": detected_at_sp.strftime("%d/%m/%Y %H:%M:%S")
                    })
            else:
                logger.info(
                    f"Insufficient history to compute features for {coingecko_id}. "
                    f"Required: {settings.MIN_SAMPLES_FEATURES} samples."
                )

            processed_coins += 1

        logger.info(f"Ingestion completed. Processed: {processed_coins}, Anomalies: {len(anomalies_detected)}")
        return {
            "status": "success",
            "processed_coins": processed_coins,
            "anomalies_detected": anomalies_detected
        }

    except Exception as e:
        logger.exception("Error processing ingestion pipeline:")
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline execution failed: {str(e)}"
        )

def bg_train_task():
    try:
        train_all()
        reload_models()
        logger.info("Background model training and reloading completed successfully.")
    except Exception as e:
        logger.exception("Error during background model training:")

@app.post("/train")
def train_models(background_tasks: BackgroundTasks):
    """
    Triggers the retreino script of Isolation Forest models for all active coins.
    Runs asynchronously in the background.
    """
    logger.info("Model training requested.")
    background_tasks.add_task(bg_train_task)
    return {"status": "training_started", "message": "Models training has been scheduled in the background."}

@app.post("/anomalies/{anomaly_id}/acknowledge")
def acknowledge_anomaly(anomaly_id: int, db: Session = Depends(get_db)):
    """
    Called by n8n after the WhatsApp message has been successfully sent.
    Updates alert_sent = TRUE in the anomalies table.
    """
    success = mark_anomaly_alert_sent(db, anomaly_id)
    if not success:
        raise HTTPException(status_code=404, detail="Anomaly record not found")
    logger.info(f"Anomaly {anomaly_id} successfully acknowledged as sent by n8n.")
    return {"status": "success", "anomaly_id": anomaly_id, "alert_sent": True}

