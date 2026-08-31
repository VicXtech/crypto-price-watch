# Estrutura Inicial — Crypto Price Watch

Criação de toda a estrutura de arquivos e pastas necessária para dar início ao projeto conforme especificado no `PROJECT-RULES.md`. O repositório já possui `.gitignore`, `LICENSE`, `docker-compose.yml` e `README.md` mínimo.

> **Changelog desta revisão:** upsert automático de moedas, idempotência nos inserts, endpoint `/train`, cache de modelo em memória, treino por moeda (não um modelo único pro mercado), tratamento de dado insuficiente, escopo do `.env.example`, config centralizada.

---

## Proposed Changes

### 1 — SQL

#### [NEW] `sql/schema.sql`
Schema completo do banco: tabelas `coins`, `price_history`, `price_features`, `anomalies` e índices. Mantém as constraints `UNIQUE (coin_id, collected_at)` em `price_history` e `price_features` — elas são a base da idempotência (ver seção API abaixo).

---

### 2 — API (FastAPI + ETL + ML)

#### [NEW] `api/Dockerfile`
Imagem Python 3.12-slim, instala dependências e sobe Uvicorn na porta 8000.

#### [NEW] `api/config.py`
Constantes centralizadas, lidas de variáveis de ambiente com fallback sensato:
- `DATABASE_URL`
- `MIN_SAMPLES_FEATURES` (ex: 6) — mínimo de registros em `price_history` pra calcular SMA/EMA/volatilidade
- `MIN_SAMPLES_TRAIN` (ex: 50) — mínimo de linhas em `price_features` pra treinar o modelo de uma moeda
- `SMA_WINDOW` (6), `EMA_WINDOW` (24)
- `ANOMALY_CONTAMINATION` (0.02)

Evita números mágicos espalhados pelo `features.py`, `model.py` e `train_model.py`.

#### [NEW] `api/main.py`
App FastAPI com três endpoints:
- `GET /health` → `{"status": "ok"}`
- `POST /ingest` → recebe o JSON do n8n, chama ETL → features → model, insere no banco, retorna `{"anomaly_detected": bool, "score": float | null}`. Todo o corpo do endpoint em `try/except`, retornando HTTP 500 com mensagem clara em caso de falha (o n8n precisa saber diferenciar "sem anomalia" de "erro no pipeline").
- `POST /train` → dispara o `ml/train_model.py` (via subprocess ou import direto da função) e recarrega os modelos em memória depois de treinar. Chamado pelo novo workflow agendado do n8n (ver seção 5).

#### [NEW] `api/db.py`
Engine SQLAlchemy (síncrono, via `psycopg2-binary`) + `SessionLocal`. Funções:
- `ensure_coin_exists(coingecko_id, symbol, name)` — `INSERT ... ON CONFLICT (coingecko_id) DO NOTHING`, depois `SELECT` pra devolver o `id`. Resolve automaticamente moeda nova sem precisar de seed manual.
- `insert_price_history(...)` — `INSERT ... ON CONFLICT (coin_id, collected_at) DO NOTHING`. Evita erro se o n8n reenviar a mesma coleta (retry, execução manual duplicada).
- `insert_features(...)` — mesmo padrão de `ON CONFLICT DO NOTHING`.
- `insert_anomaly(...)`
- `get_recent_features(coin_id, days)` — usado tanto pelo `/ingest` (janela curta) quanto pelo `train_model.py` (janela de treino, maior).

#### [NEW] `api/etl.py`
Função `normalize_prices(raw_json)` — valida campos obrigatórios, converte tipos, remove nulos. Retorna lista de dicts limpos.

#### [NEW] `api/features.py`
Funções `calc_sma`, `calc_ema`, `calc_pct_change`, `calc_volatility` — operam sobre DataFrames Pandas com dados de `price_history`. **Cada função checa `len(df) < MIN_SAMPLES_FEATURES` e retorna `None`** se não houver histórico suficiente, em vez de estourar exceção. Isso é esperado e normal nas primeiras ~24h de coleta de uma moeda nova.

#### [NEW] `api/model.py`
- No import do módulo, carrega `ml/isolation_forest.pkl` **uma vez** (se existir) para um dicionário em memória: `{"bitcoin": modelo, "ethereum": modelo, ...}`. Não lê do disco a cada request.
- `reload_models()` — recarrega o dicionário do disco; chamada pelo endpoint `/train` depois que o retreino termina.
- `run_inference(coingecko_id, features_row)` — busca o modelo daquela moeda no dicionário. Retorna `(False, None)` se a moeda não tem modelo treinado ainda ou se alguma feature necessária veio `None`.

---

### 3 — ML

#### [NEW] `ml/train_model.py`
Script que, **para cada moeda ativa**, busca as últimas features em `price_features`, pula moedas com menos de `MIN_SAMPLES_TRAIN` registros, treina um `IsolationForest` (`contamination=ANOMALY_CONTAMINATION`) individual, e salva tudo num único dicionário serializado em `ml/isolation_forest.pkl`. **Um modelo por moeda — não um modelo único pro mercado inteiro**, porque escala de preço e volatilidade típica variam demais entre moedas para um modelo genérico ser sensível o bastante. Exposto também como função importável (`train_all()`) para ser chamado pelo endpoint `/train`, além de rodar standalone via CLI.

#### [NEW] `ml/.gitkeep`
Garante que a pasta `ml/` seja rastreada pelo Git (o `.pkl` está no `.gitignore`).

---

### 4 — Dashboard

#### [NEW] `dashboard/app.py`
App Streamlit: seletor de moeda, seletor de período, gráfico de linha do histórico com marcadores de anomalia e tabela das últimas anomalias. Lê o Postgres diretamente via SQL — não passa pelo FastAPI.

---

### 5 — n8n

#### [NEW] `n8n/README.md`
Instruções de como importar os workflows. Os arquivos JSON dos workflows serão exportados manualmente pelo n8n após a configuração. Documenta três fluxos:
1. **Coleta** (a cada 1h) — CoinGecko → FastAPI `/ingest` → branch condicional pra alerta
2. **Alerta** — dispara mensagem via WAHA quando `anomaly_detected: true`
3. **Retreino** (1x/dia, ex: 3h da manhã) — chama `POST /train` no FastAPI. Novo fluxo, necessário porque sem ele o modelo nunca se atualiza sozinho.

---

### 6 — Raiz do projeto

#### [MODIFY] `docker-compose.yml`
Adicionar serviço `dashboard` (Streamlit na porta 8501). Confirmar que `api` e `dashboard` recebem `DATABASE_URL` via variável de ambiente (não hardcoded), e que ambos estão na rede `automation` já existente (a `api` para ser chamada pelo n8n; o `dashboard` não precisa, mas não custa manter consistência se algum dia precisar).

#### [NEW] `requirements.txt`
Dependências Python do projeto (FastAPI, Uvicorn, SQLAlchemy, psycopg2-binary, pandas, scikit-learn, joblib, streamlit, httpx).

#### [NEW] `.env.example`
Apenas variáveis que a aplicação Python realmente usa: `DATABASE_URL`, porta da API, `LOG_LEVEL`. **Não incluir a chave da CoinGecko** — ela fica armazenada como credential dentro do próprio n8n, já que é o n8n quem chama a CoinGecko diretamente, não o FastAPI.

#### [MODIFY] `README.md`
README completo com diagrama de arquitetura, instruções de setup, comandos principais e seção de decisões técnicas (incluindo a decisão de modelo por moeda e a estratégia de idempotência).

---

## Verification Plan

### Manual Verification
- `docker compose up --build` deve subir Postgres + API + Dashboard sem erros.
- `GET http://localhost:8000/health` deve retornar `{"status": "ok"}`.
- `POST http://localhost:8000/ingest` com payload de exemplo deve inserir registros no banco.
- **Reenviar o mesmo payload de `/ingest` duas vezes seguidas não deve gerar erro** (testa a idempotência do `ON CONFLICT DO NOTHING`).
- Com menos de `MIN_SAMPLES_FEATURES` registros para uma moeda nova, `/ingest` deve retornar `anomaly_detected: false` sem estourar exceção (testa o tratamento de dado insuficiente).
- `POST http://localhost:8000/train` deve rodar sem erro mesmo com zero moedas elegíveis (nenhuma com `MIN_SAMPLES_TRAIN` ainda) — deve simplesmente não gerar modelos, sem quebrar.
- `streamlit run dashboard/app.py` deve abrir o dashboard sem erros de importação.
