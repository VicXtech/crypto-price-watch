# Automações n8n — Documentação dos Workflows ⚙️

Este diretório contém a especificação técnica completa e os templates prontos para importação dos fluxos de automação no **n8n**. 

O n8n atua como o **orquestrador central de eventos**, coordenando a coleta periódica de preços de mercado, o acionamento da API analítica em FastAPI, a entrega dos alertas via WhatsApp e a manutenção programada dos modelos de Machine Learning.

---

## 📂 Arquivos Disponíveis

- [`workflow_main.json`](./workflow_main.json): Template do fluxo principal pronto para importar no n8n (coleta, ingestão, inferência, envio de alerta WhatsApp e fechamento de ciclo via acknowledge).
- [`workflow_train.json`](./workflow_train.json): Template do fluxo agendado diário para retreino em segundo plano dos modelos de Isolation Forest e notificação.

---

## 🔄 1. Workflow Principal (`Main`) — Coleta, Ingestão & Alertas

Este fluxo roda em intervalos regulares (padrão de **15 minutos** ou a cada **1 hora**, customizável), coleta os dados atualizados das criptomoedas na CoinGecko, envia para a API e, caso desvios estatísticos sejam detectados, despacha as mensagens via WhatsApp e confirma a entrega.

### Diagrama do Fluxo

```text
[Schedule Trigger (15 min)]
            │
            ▼
[Coins Markets (CoinGecko API)]
            │
            ▼
[Edit Fields (Mapeamento & Timestamp)]
            │
            ▼
[HTTP Request (POST /ingest na API)]
            │
            ▼
[IF (anomalies_detected > 0?)]
      │                     │
   (NÃO)                  (SIM)
      │                     │
      ▼                     ▼
   [NoOp]             [Split Out (separa anomalias)]
                            │
                            ▼
                      [Aviso WAHA (Disparo WhatsApp)]
                            │
                            ▼
                      [Acknowledge (POST /anomalies/{id}/acknowledge)]
```

### Detalhamento dos Nós:

1. **Schedule Trigger**:
   - **Regra**: Intervalo de tempo (padrão: a cada 15 minutos).
   - Fornece o timestamp sincronizado da coleta em `$item.json.timestamp`.

2. **Coins Markets (HTTP Request - CoinGecko)**:
   - **Método**: `GET`
   - **URL**: `https://api.coingecko.com/api/v3/coins/markets`
   - **Query Parameters**:
     - `ids`: `bitcoin,ethereum,solana,pepe,sui`
     - `vs_currency`: `usd`
   - **Autenticação**: Opcional. Permite adicionar credencial `Header Auth` (ex: `x-cg-demo-api-key`) caso possua uma chave de desenvolvedor CoinGecko.

3. **Edit Fields (Set - Normalização de Saída)**:
   - Filtra estritamente os campos necessários para consumo da API:
     - `id`: `={{ $json.id }}`
     - `symbol`: `={{ $json.symbol.toUpperCase() }}`
     - `name`: `={{ $json.name }}`
     - `current_price`: `={{ $json.current_price }}`
     - `market_cap`: `={{ $json.market_cap }}`
     - `total_volume`: `={{ $json.total_volume }}`
     - `collected_at`: `={{ $('Schedule Trigger').item.json.timestamp }}`

4. **HTTP Request (Ingestão FastAPI)**:
   - **Método**: `POST`
   - **URL**: `http://crypto_api:8000/ingest` *(dentro da rede Docker compartilhada `automation`)*
   - **Headers**: `Content-Type: application/json`
   - **Body**: `={{ $json }}`
   - **Resposta**: Retorna o status de processamento e o array `anomalies_detected`.

5. **If (Validação de Anomalias)**:
   - **Condição**: `{{ $json.anomalies_detected.length }} > 0`
   - **False**: Conduz ao nó **No Operation (do nothing)** e encerra sem ruído.
   - **True**: Direciona para o pipeline de alerta.

6. **Split Out (Desdobramento)**:
   - **Campo desdobrado**: `anomalies_detected`
   - **Motivo**: Caso mais de uma moeda apresente anomalia simultaneamente, o `Split Out` cria uma execução individual para cada registro, garantindo que nenhum alerta se perca.

7. **Aviso de Anomalia Detectada (Nó Comunitário WAHA)**:
   - **Pacote**: `@devlikeapro/n8n-nodes-waha`
   - **Operação**: `Chatting` → `Send Text`
   - **Sessão**: Nome da sessão autenticada no WAHA (ex: `default`)
   - **Chat ID**: `{{ seu_numero }}@c.us` (ex: `5511999999999@c.us`)
   - **Template da Mensagem**:
     ```text
     ⚠️ *ALERTA DE ANOMALIA DE PREÇO* ⚠️

     A criptomoeda *{{ $json.symbol }}* ({{ $json.coingecko_id }}) apresentou um comportamento de preço fora do comum!

     💵 *Preço no Alerta:* ${{ $json.current_price >= 1 ? $json.current_price.toFixed(2) : $json.current_price }}
     📊 *Score do Isolation Forest:* {{ $json.anomaly_score.toFixed(4) }}
     🕒 *Horário (Brasília):* {{ $json.detected_at_brasilia }}

     _Verifique o painel do Streamlit para mais detalhes._
     ```

8. **Acknowledge Anomaly (HTTP Request)**:
   - **Método**: `POST`
   - **URL**: `=http://crypto_api:8000/anomalies/{{ $('Split Out').item.json.anomaly_id }}/acknowledge`
   - **Finalidade**: Marca `alert_sent = TRUE` na tabela `anomalies` do PostgreSQL. Isso fecha o ciclo de vida do alerta e permite auditar com precisão quais anomalias foram efetivamente notificadas.

---

## 🛠️ 2. Workflow de Retreino Diário (`Train`)

Mantém os modelos de Machine Learning (`IsolationForest`) calibrados com o comportamento mais recente do mercado.

### Diagrama do Fluxo

```text
[Schedule Trigger (Diário às 23:00)]
                 │
                 ▼
[HTTP Request (POST /train na API)]
                 │
                 ▼
[Aviso WAHA (Confirmação no WhatsApp)]
```

### Detalhamento dos Nós:

1. **Schedule Trigger**:
   - **Frequência**: Diária às `23:00` (ou horário de menor volatilidade).
2. **HTTP Request (Disparo /train)**:
   - **Método**: `POST`
   - **URL**: `http://crypto_api:8000/train`
   - O endpoint responde imediatamente enquanto uma `BackgroundTask` no FastAPI processa as séries temporais, recalibra os modelos por moeda e atualiza os pesos em memória.
3. **Aviso de Treino Disparado (WAHA)**:
   - Envia uma notificação rápida no WhatsApp confirmando o agendamento do retreino:
     ```text
     🚨 *TREINO DISPARADO COM SUCESSO* 🚨

     Projeto: crypto-price-watch 💸
     ```

---

## 📥 Como Importar os Workflows no seu n8n

1. No n8n, clique em **Workflows** → **Add Workflow** (ou ícone de `+`).
2. No menu superior direito (três pontinhos `...`), selecione **Import from File**.
3. Escolha o arquivo [`workflow_main.json`](./workflow_main.json) ou [`workflow_train.json`](./workflow_train.json).
4. **Configurações a ajustar**:
   - No nó **Aviso de Anomalia Detectada**:
     - Selecione a sua credencial do WAHA conectada.
     - Altere o `chatId` para o seu número com DDI e DDD (formato `55XXXXXXXXXXX@c.us`).
     - Certifique-se de que a sessão do WAHA corresponde à sua (ex: `default`).
   - Ative o switch **Active** do workflow para habilitar os agendamentos automáticos.

---

> [!TIP]
> Caso utilize outro provedor de mensagens (Telegram, Discord, Slack ou e-mail), basta substituir o nó do WAHA pelo nó correspondente do n8n mantendo os mesmos campos de entrada do `Split Out`.
