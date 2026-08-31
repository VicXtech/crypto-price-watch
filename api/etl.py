from datetime import datetime, timezone
import logging
from typing import Any, Union

logger = logging.getLogger(__name__)

# Default metadata fallback map for known CoinGecko IDs
COIN_METADATA_MAP = {
    "bitcoin": {"symbol": "BTC", "name": "Bitcoin"},
    "ethereum": {"symbol": "ETH", "name": "Ethereum"},
    "solana": {"symbol": "SOL", "name": "Solana"},
    "pepe": {"symbol": "PEPE", "name": "Pepe"},
    "sui": {"symbol": "SUI", "name": "Sui"},
}

def _parse_timestamp(raw_timestamp: Any) -> datetime:
    """
    Parses various timestamp formats (ISO 8601 string, UNIX timestamp number, datetime)
    into a timezone-aware UTC datetime. Defaults to now(timezone.utc) on failure.
    """
    if raw_timestamp is None:
        return datetime.now(timezone.utc)

    if isinstance(raw_timestamp, datetime):
        return raw_timestamp.astimezone(timezone.utc) if raw_timestamp.tzinfo else raw_timestamp.replace(tzinfo=timezone.utc)

    if isinstance(raw_timestamp, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return datetime.now(timezone.utc)

    if isinstance(raw_timestamp, str):
        cleaned = raw_timestamp.strip()
        if not cleaned:
            return datetime.now(timezone.utc)
        # Handle ISO strings like "2026-08-31T10:15:24.669-03:00", "2026-08-31T10:15:24Z", "2026-08-31T10:15:24"
        try:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except (ValueError, TypeError):
            # Fallback: check if string is numeric timestamp
            try:
                return datetime.fromtimestamp(float(cleaned), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                logger.warning(f"Could not parse timestamp '{cleaned}'. Defaulting to current UTC time.")
                return datetime.now(timezone.utc)

    return datetime.now(timezone.utc)


def _normalize_single_item(item: dict) -> dict | None:
    """
    Normalizes a single coin dictionary matching the /coins/markets + n8n edit node structure:
    {
        "id": "bitcoin",
        "symbol": "BTC",
        "name": "Bitcoin",
        "current_price": 403855,
        "market_cap": 8107918324532,
        "total_volume": 140248026097,
        "collected_at": "2026-08-31T10:15:24"
    }
    """
    if not isinstance(item, dict):
        return None

    # coingecko_id from "id" or "coingecko_id"
    raw_id = item.get("id") or item.get("coingecko_id")
    if not raw_id:
        logger.warning("Skipping item: missing 'id' / 'coingecko_id'.")
        return None
    coingecko_id = str(raw_id).strip().lower()

    # current_price from "current_price" (or fallback "price", "usd")
    raw_price = item.get("current_price")
    if raw_price is None:
        raw_price = item.get("price") if item.get("price") is not None else item.get("usd")

    if raw_price is None:
        logger.warning(f"Skipping '{coingecko_id}': missing 'current_price'.")
        return None

    try:
        current_price = float(raw_price)
    except (ValueError, TypeError):
        logger.warning(f"Skipping '{coingecko_id}': invalid current_price '{raw_price}'.")
        return None

    # market_cap
    raw_market_cap = item.get("market_cap") if item.get("market_cap") is not None else item.get("usd_market_cap")
    market_cap = None
    if raw_market_cap is not None:
        try:
            market_cap = float(raw_market_cap)
        except (ValueError, TypeError):
            market_cap = None

    # total_volume
    raw_volume = item.get("total_volume")
    if raw_volume is None:
        raw_volume = item.get("usd_24h_vol") if item.get("usd_24h_vol") is not None else item.get("volume_24h")
    total_volume = None
    if raw_volume is not None:
        try:
            total_volume = float(raw_volume)
        except (ValueError, TypeError):
            total_volume = None

    # symbol and name (from payload or fallback to COIN_METADATA_MAP)
    symbol = item.get("symbol")
    if not symbol:
        symbol = COIN_METADATA_MAP.get(coingecko_id, {}).get("symbol", coingecko_id.upper())
    symbol = str(symbol).strip().upper()

    name = item.get("name")
    if not name:
        name = COIN_METADATA_MAP.get(coingecko_id, {}).get("name", coingecko_id.capitalize())
    name = str(name).strip()

    # collected_at
    raw_collected_at = item.get("collected_at")
    if raw_collected_at is None:
        raw_collected_at = item.get("last_updated") if item.get("last_updated") is not None else item.get("last_updated_at")
    collected_at = _parse_timestamp(raw_collected_at)

    return {
        "coingecko_id": coingecko_id,
        "symbol": symbol,
        "name": name,
        "current_price": current_price,
        "market_cap": market_cap,
        "total_volume": total_volume,
        "collected_at": collected_at
    }


def normalize_prices(raw_payload: Union[list, dict]) -> list[dict]:
    """
    Normalizes price payloads from CoinGecko.
    
    Supports:
    1. List of items from /coins/markets (filtered by n8n Edit Fields node):
       [
           {
               "id": "bitcoin",
               "symbol": "BTC",
               "name": "Bitcoin",
               "current_price": 403855,
               "market_cap": 8107918324532,
               "total_volume": 140248026097,
               "collected_at": "2026-08-31T10:15:24"
           }, ...
       ]
    2. Single item dict (when n8n executes per item):
       {
           "id": "bitcoin",
           "symbol": "BTC",
           "name": "Bitcoin",
           "current_price": 403855,
           ...
       }
    3. Dict wrapping list: {"items": [...]} or {"data": [...]}
    4. Legacy /simple/price dict format:
       {
           "bitcoin": {
               "usd": 64320.50,
               "usd_market_cap": 1260000000000.0,
               "usd_24h_vol": 25000000000.0,
               "last_updated_at": 1718928374
           }
       }
    """
    normalized_data = []

    if isinstance(raw_payload, list):
        for item in raw_payload:
            normalized = _normalize_single_item(item)
            if normalized:
                normalized_data.append(normalized)
        return normalized_data

    if isinstance(raw_payload, dict):
        # Case A: {"items": [...]} or {"data": [...]}
        if "items" in raw_payload and isinstance(raw_payload["items"], list):
            return normalize_prices(raw_payload["items"])
        if "data" in raw_payload and isinstance(raw_payload["data"], list):
            return normalize_prices(raw_payload["data"])

        # Case B: Single item directly with "id" / "coingecko_id"
        if "id" in raw_payload or "coingecko_id" in raw_payload:
            normalized = _normalize_single_item(raw_payload)
            if normalized:
                normalized_data.append(normalized)
            return normalized_data

        # Case C: Legacy /simple/price dictionary: { "bitcoin": { "usd": ... } }
        for coingecko_id, metrics in raw_payload.items():
            if not isinstance(metrics, dict):
                logger.warning(f"Skipping key '{coingecko_id}': metrics is not a dictionary.")
                continue

            metadata = COIN_METADATA_MAP.get(coingecko_id, {
                "symbol": coingecko_id.upper(),
                "name": coingecko_id.capitalize()
            })

            legacy_item = {
                "id": coingecko_id,
                "symbol": metadata["symbol"],
                "name": metadata["name"],
                "current_price": metrics.get("usd"),
                "market_cap": metrics.get("usd_market_cap"),
                "total_volume": metrics.get("usd_24h_vol"),
                "collected_at": metrics.get("last_updated_at")
            }

            normalized = _normalize_single_item(legacy_item)
            if normalized:
                normalized_data.append(normalized)

        return normalized_data

    logger.error(f"Invalid raw_payload type: {type(raw_payload)}")
    return []

