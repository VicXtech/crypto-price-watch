import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://crypto:crypto_dev_password@localhost:5432/crypto_price_watch"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "info"

    # Feature engineering limits
    MIN_SAMPLES_FEATURES: int = 6
    MIN_SAMPLES_TRAIN: int = 50

    # Indicators configuration
    SMA_WINDOW: int = 6
    EMA_WINDOW: int = 24

    # ML parameters
    ANOMALY_CONTAMINATION: float = 0.02
    MODEL_PATH: str = "ml/isolation_forest.pkl"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
