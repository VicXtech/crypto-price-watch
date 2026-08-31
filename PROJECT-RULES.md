# Crypto Price Watch

**Pipeline de Dados + Automação + IA** — monitoramento inteligente de preços de criptomoedas, com detecção de anomalias e alertas automáticos.

> Projeto de portfólio (Projeto 3) — Victor
> Stack: n8n · Python · PostgreSQL · Scikit-learn · Streamlit

---

## 1. Visão geral

O sistema coleta preços de criptomoedas periodicamente, armazena o histórico, calcula indicadores (médias móveis, volatilidade, variação percentual), treina um modelo de detecção de anomalias e dispara alertas automáticos quando um preço foge do padrão esperado. Um dashboard mostra o histórico, as anomalias detectadas e as previsões de tendência.

**Por que esse projeto é forte pro portfólio:**
- Cobre o ciclo completo: ingestão → transformação → armazenamento → modelagem → ação → visualização
- Não depende de scraping frágil (usa API pública estável)
- Tem um "produto final" fácil de demonstrar em vídeo curto (alerta chegando no Whatsapp)
- Reaproveita sua experiência em n8n sem ser "só mais um workflow"

---

## 2. Arquitetura

```
CoinGecko API (preços)
        │
        ▼
     n8n (Schedule Trigger, a cada 1h)
        │
        ▼
  Python — ETL (limpeza, normalização)
        │
        ▼
   PostgreSQL (price_history)
        │
        ▼
  Feature engineering (SMA, EMA, % variação, volatilidade)
        │
        ▼
  ML — Isolation Forest (detecção de anomalia)
        │
        ├──► anomalia detectada → n8n dispara alerta (Whatsapp)
        │
        ▼
  Dashboard (Streamlit) — histórico + anomalias + tendência
```

---

## 3. Fonte de dados

**API escolhida: [CoinGecko API](https://www.coingecko.com/en/api)**
- Gratuita, sem necessidade de chave para o plano básico
- Endpoint principal: `/coins/markets` (preço atual, volume e dados de mercado) e `/coins/{id}/market_chart` (histórico)
- Rate limit generoso o suficiente pra coleta horária de ~10-15 moedas

**Moedas monitoradas pelo projeto:** Bitcoin (BTC), Ethereum (ETH), Solana (SOL), Pepe (PEPE) e Sui (SUI).

---

## 4. Schema do banco (PostgreSQL)

```sql
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
```

**Por que esse schema é bom de mostrar em entrevista:** separa dado bruto (`price_history`) de dado derivado (`price_features`), o que é uma prática real de engenharia de dados (staging vs. mart), e tem uma tabela de eventos (`anomalies`) que serve tanto pro alerta quanto pro dashboard.

---

## 5. Workflow n8n

**Fluxo 1 — Coleta (roda a cada 1h)**
1. `Schedule Trigger` (a cada 1h)
2. `HTTP Request` → CoinGecko `/coins/markets` (com parâmetros `vs_currency=usd` e `ids=bitcoin,ethereum,solana,pepe,sui`)
3. `Edit Fields (Set)` → filtra apenas os campos necessários (`id`, `symbol`, `name`, `current_price`, `market_cap`, `total_volume`, `collected_at`)
4. `HTTP Request` (POST) → chama o serviço Python (FastAPI `/ingest`) passando os dados filtrados
5. O serviço Python faz o ETL e grava no Postgres (ver seção 6)
6. `IF` node → se o Python retornar `anomalies_detected` com itens, segue pro Fluxo 2

**Fluxo 2 — Alerta**
1. Recebe o payload de anomalia (moeda, `current_price`, score, timestamp)
2. `Set` node → formata a mensagem
3. `Whatsapp` node (ou Email/WhatsApp via WAHA, já que você já tem isso configurado) → envia o alerta

**Por que dividir a lógica pesada pro Python e deixar o n8n só orquestrando:** você já aprendeu essa lição no Projeto 2 (Gemini via HTTP Request por limitação de node) — aqui o motivo é o mesmo: n8n não é bom pra rodar modelo de ML, então ele só dispara e reage, a lógica pesada fica no Python.

---

## 6. ETL em Python

Serviço simples (FastAPI, já que você tem experiência) com um endpoint `/ingest` que:
1. Recebe o JSON bruto do n8n
2. Normaliza (trata nulos, converte tipos)
3. Insere em `price_history`
4. Calcula as features (SMA, EMA, % variação, volatilidade) e insere em `price_features`
5. Roda o modelo de anomalia sobre o dado mais recente
6. Se for anomalia, grava em `anomalies` e retorna `anomaly_detected: true` pro n8n

```
project/
├── api/
│   ├── main.py              # FastAPI app
│   ├── db.py                 # conexão + queries SQLAlchemy
│   ├── etl.py                 # limpeza e normalização
│   ├── features.py            # cálculo de SMA/EMA/volatilidade
│   └── model.py                # carrega e roda o Isolation Forest
├── ml/
│   ├── train_model.py          # script de treino (roda periodicamente)
│   └── isolation_forest.pkl     # modelo serializado
├── dashboard/
│   └── app.py                    # Streamlit
├── sql/
│   └── schema.sql
├── docker-compose.yml              # Postgres + API
├── requirements.txt
└── README.md
```

---

## 7. Modelo de Machine Learning

**Fase 1 (MVP) — Detecção de anomalia com Isolation Forest**
- Não-supervisionado: não precisa de dado rotulado, ideal pra começar rápido
- Features de entrada: `pct_change_1h`, `volatility_24h`, `current_price` normalizado (`price_norm`)
- Retreina periodicamente (ex: 1x por dia) com os últimos N dias de dados
- Biblioteca: `scikit-learn` (`IsolationForest`)

```python
from sklearn.ensemble import IsolationForest

model = IsolationForest(contamination=0.02, random_state=42)
model.fit(features_df[["pct_change_1h", "volatility_24h", "price_norm"]])

# score < 0 => anomalia
score = model.decision_function(new_point)
is_anomaly = model.predict(new_point) == -1
```

**Fase 2 (extensão, opcional) — Previsão de tendência**
- Regressão simples ou Prophet pra prever o preço nas próximas horas
- Serve pra enriquecer o dashboard com uma "faixa esperada", tornando a anomalia mais visual (preço saiu da faixa prevista)

---

## 8. Dashboard (Streamlit)

- Gráfico de linha do histórico de preço por moeda
- Marcadores nos pontos de anomalia detectada
- Tabela com as últimas anomalias e o score
- Filtro por moeda e por período
- (Fase 2) Faixa de previsão sobreposta ao gráfico

---

## 9. Estrutura de entrega no GitHub

- `README.md` com o diagrama de arquitetura (pode reusar o desta spec), prints do dashboard e um GIF curto do alerta chegando no Whatsapp
- Pasta `n8n/` com o JSON exportado dos workflows
- `docker-compose.yml` pra subir Postgres + API com um comando só
- Seção "Decisões técnicas" no README explicando por que Isolation Forest, por que separar ETL do n8n, etc. — isso é o que mais impressiona recrutador técnico

---

## 10. Ideias de expansão (pós-MVP, não fazer agora)

- Trocar Isolation Forest por um modelo supervisionado quando tiver rótulos suficientes (anomalias confirmadas manualmente)
- Adicionar sentimento de notícias como feature extra
- Deploy do dashboard (Streamlit Community Cloud) pra ter link público no portfólio
