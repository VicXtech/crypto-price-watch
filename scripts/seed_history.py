"""
Script de apoio para popular price_history com dados fake, chamando o /ingest
repetidamente com timestamps espaçados de hora em hora para trás.

Uso:
    python scripts/seed_history.py --hours 30

Não faz parte da imagem Docker da API — roda direto na sua máquina (fora do
container), por isso usa a porta do host (8001), não a porta interna (8000).
"""

import argparse
import random
from datetime import datetime, timedelta, timezone

import httpx

API_URL = "http://localhost:8001/ingest"

# Preço-base e variação percentual máxima por hora, só para gerar uma série
# que pareça razoável (não é para ser realista, é só para ter volume de dados)
BASE_PRICE = 65000.0
MAX_PCT_MOVE = 0.03  # até 3% de variação entre um ponto e o anterior


def generate_series(hours: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    price = BASE_PRICE
    records = []

    # gera do mais antigo para o mais recente, para a série de preço parecer
    # uma caminhada aleatória coerente, não pontos soltos
    for i in range(hours, 0, -1):
        collected_at = now - timedelta(hours=i)
        pct_move = random.uniform(-MAX_PCT_MOVE, MAX_PCT_MOVE)
        price = round(price * (1 + pct_move), 2)

        records.append({
            "id": "bitcoin",
            "symbol": "BTC",
            "name": "Bitcoin",
            "current_price": price,
            "market_cap": round(price * 19_700_000, 2),  # aproximação grosseira
            "total_volume": round(price * 500_000, 2),    # idem
            "collected_at": collected_at.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=30,
        help="Quantos pontos horários gerar para trás (padrão: 30)"
    )
    args = parser.parse_args()

    records = generate_series(args.hours)

    print(f"Enviando {len(records)} registros para {API_URL} (um por vez)...")

    for record in records:
        response = httpx.post(API_URL, json=[record], timeout=10)
        status = "OK" if response.status_code == 200 else f"ERRO {response.status_code}"
        print(f"  {record['collected_at']}  price={record['current_price']:<12}  {status}")

        if response.status_code != 200:
            print(f"    -> {response.text}")

    print("Concluído.")


if __name__ == "__main__":
    main()