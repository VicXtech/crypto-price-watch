# Crypto Price Watch 📈

**Pipeline de Dados + Automação + IA** — Monitoramento inteligente de preços de criptomoedas, detecção de anomalias com Machine Learning e alertas automáticos via WhatsApp.

Este projeto implementa um ciclo completo de engenharia de dados e inteligência artificial: ingestão horária automática de dados de preços de mercado, transformação e modelagem de features, inferência não-supervisionada para detectar desvios de comportamento nos preços e visualização interativa em um dashboard analítico.

---

## 🏗️ Arquitetura do Sistema

O sistema é composto por componentes integrados via Docker Compose, permitindo orquestração local robusta e comunicação fluida entre os serviços:

```
                  CoinGecko API (Preços de Mercado)
                                 │
                                 ▼
                     n8n (Orquestrador / Schedule)
                                 │
                                 ▼
                      FastAPI (ETL & Inference)
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
     PostgreSQL (Database) ◄─────────── Streamlit (Dashboard)
                 │
                 ▼
         Isolation Forest
      (Detecção de Anomalias)
                 │
                 └─────► Anomalia Detectada? ─────► n8n (Alerta WhatsApp)
```

---

## 🛠️ Tecnologias Utilizadas

- **Orquestração e Integração**: [n8n](https://n8n.io/)
- **Linguagem Principal**: Python 3.12
- **Backend / API**: FastAPI, Uvicorn, SQLAlchemy
- **Banco de Dados**: PostgreSQL 16
- **Machine Learning**: Scikit-Learn (`IsolationForest`), Joblib
- **Engenharia de Features**: Pandas, Numpy
- **Interface Gráfica**: Streamlit, Plotly
- **Containers**: Docker & Docker Compose
- **Notificação**: WhatsApp HTTP API (WAHA)

---

## 🗃️ Modelagem do Banco de Dados

O banco de dados armazena os dados crus separadamente das métricas calculadas e dos alertas gerados para garantir a separação de responsabilidades (Staging vs. Analytics Mart):

1. **`coins`**: Catálogo de criptomoedas monitoradas no sistema.
2. **`price_history`**: Registro histórico bruto de preço, capitalização de mercado e volume.
3. **`price_features`**: Indicadores calculados (SMA de 6h, EMA de 24h, variação de 1h e volatilidade de 24h).
4. **`anomalies`**: Registro de anomalias detectadas pelo Isolation Forest com flags de controle para envio de alertas.

---

## 🚀 Como Rodar o Projeto Localmente

### Pré-requisitos
- Docker e Docker Compose instalados na máquina.
- Uma rede Docker compartilhada chamada `automation` (opcional, pode ser criada caso use n8n ou waha locais):
  ```bash
  docker network create automation
  ```

### Passo a Passo

1. **Clonar o Repositório**:
   ```bash
   git clone https://github.com/VicXtech/crypto-price-watch.git
   cd crypto-price-watch
   ```

2. **Configurar as Variáveis de Ambiente**:
   Copie o arquivo `.env.example` para `.env` e ajuste se necessário:
   ```bash
   cp .env.example .env
   ```

3. **Subir os Serviços com Docker Compose**:
   ```bash
   docker compose up --build -d
   ```
   Isso iniciará:
   - **PostgreSQL**: Porta `5432`
   - **FastAPI API**: Porta `8000`
   - **Streamlit Dashboard**: Porta `8501`

4. **Verificar os Serviços**:
   - Healthcheck da API: [http://localhost:8000/health](http://localhost:8000/health)
   - Dashboard Streamlit: [http://localhost:8501](http://localhost:8501)

---

## 🧬 Endpoints da API (FastAPI)

### 1. Ingestão de Preços
- **Endpoint**: `POST /ingest`
- **Payload**: JSON enviado pelo n8n (formato do endpoint `/coins/markets` da CoinGecko filtrado via nó Edit Fields, ou o legado `/simple/price`).
- **Processamento**: Executa o ETL, grava o histórico bruto em `price_history`, calcula indicadores em `price_features`, realiza inferência de Machine Learning e registra desvios em `anomalies`.
- **Resposta**:
  ```json
  {
    "status": "success",
    "processed_coins": 1,
    "anomalies_detected": [
      {
        "anomaly_id": 1,
        "coingecko_id": "bitcoin",
        "symbol": "BTC",
        "current_price": 68520.10,
        "price_usd": 68520.10,
        "anomaly_score": -0.0425,
        "detected_at": "2026-08-25T20:20:00Z"
      }
    ]
  }
  ```

### 2. Retreino de Modelos
- **Endpoint**: `POST /train`
- **Processamento**: Dispara o script de retreino em segundo plano (`BackgroundTasks`) que analisa a série histórica de cada moeda ativa, filtra moedas com volume de histórico suficiente (`MIN_SAMPLES_TRAIN`) e treina um Isolation Forest exclusivo por moeda. Ao final, atualiza os pesos carregados em memória na API.

---

## 🧠 Decisões Técnicas e Arquitetura do ML

### 1. Separação entre Orquestração (n8n) e Lógica (Python)
Utilizamos o n8n para orquestrar cronogramas, conexões de APIs de terceiros (CoinGecko) e disparos de mensageria (WAHA/WhatsApp). Toda a computação analítica, processamento estatístico do Pandas e o modelo de ML rodam isolados no microserviço Python. Isso mantém o n8n leve e evita falhas por sobrecarga ou indisponibilidade de bibliotecas matemáticas pesadas no container do n8n.

### 2. Um Modelo por Criptomoeda (Isolation Forest Individual)
Moedas como o Bitcoin possuem escalas de preço e volatilidade de mercado completamente diferentes de altcoins de baixa capitalização. Treinar um único modelo de detecção de anomalias para todo o mercado geraria distorções severas. A API treina e avalia modelos `IsolationForest` **individuais** para cada moeda monitorada.

### 3. Garantia de Idempotência
A pipeline suporta repetições de execuções sem duplicar dados. A tabela `price_history` e `price_features` possuem chaves únicas compostas `(coin_id, collected_at)`. No Python, os comandos de inserção utilizam instruções SQL parametrizadas com cláusulas `ON CONFLICT DO NOTHING`, evitando crashes na pipeline em caso de chamadas manuais duplicadas ou retentativas automáticas de rede.

### 4. Normalização Escalar-Independente de Preço
Para detectar anomalias no preço sem sofrer com tendências inflacionárias de longo prazo (onde o Bitcoin custava $10k e hoje custa $60k), normalizamos o preço dividindo-o pela Média Móvel Exponencial (EMA 24h):
$$\text{price\_norm} = \frac{\text{current\_price}}{\text{ema\_24h}} - 1.0$$
Isso avalia a anomalia do preço em relação ao seu comportamento recente, e não ao valor nominal bruto.
