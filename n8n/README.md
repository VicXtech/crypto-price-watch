# Workflows n8n — Configuração

Este diretório contém a especificação e instruções detalhadas para configurar os três fluxos de automação no n8n.

---

## 1. Fluxo de Coleta Horária (Data Pipeline)

Este fluxo é responsável por coletar dados em tempo real da CoinGecko via `/coins/markets`, filtrar apenas os campos necessários através de um nó Edit Fields (Set), enviá-los ao nosso serviço Python de ETL/Inference e, se houver anomalias, prosseguir para o fluxo de alerta.

### Configuração dos Nós:
1. **Schedule Trigger**:
   - Intervalo: **A cada 1 hora** (Every 1 Hour).
2. **HTTP Request (CoinGecko API - /coins/markets)**:
   - **Método**: `GET`
   - **URL**: `https://api.coingecko.com/api/v3/coins/markets`
   - **Query Parameters**:
     - `vs_currency`: `usd`
     - `ids`: `bitcoin,ethereum,solana,pepe,sui`
3. **Edit Fields (Set - Filtragem dos Dados)**:
   - Configurar os campos mapeados a partir do retorno da CoinGecko:
     - `id`: `{{ $json.id }}` (Texto)
     - `symbol`: `{{ $json.symbol.toUpperCase() }}` (Texto)
     - `name`: `{{ $json.name }}` (Texto)
     - `current_price`: `{{ $json.current_price }}` (Número)
     - `market_cap`: `{{ $json.market_cap }}` (Número)
     - `total_volume`: `{{ $json.total_volume }}` (Número)
     - `collected_at`: `{{ $now.toISO() }}` (Texto / ISO 8601)
4. **HTTP Request (FastAPI /ingest)**:
   - **Método**: `POST`
   - **URL**: `http://crypto_api:8000/ingest`
   - **Content-Type**: `JSON`
   - **Body**: Enviar os dados filtrados do nó Edit Fields (Set).
5. **IF (Detecção de Anomalias)**:
   - **Condição**: Boolean ou Expressão JavaScript
   - **Expressão**: `{{ $json.anomalies_detected.length > 0 }}`
   - **Caminho TRUE**: Encaminha os dados da anomalia (lista `anomalies_detected`) para o **Fluxo de Alerta**.
   - **Caminho FALSE**: Fim do fluxo.

---

## 2. Fluxo de Alerta (WhatsApp via WAHA)

Este fluxo recebe os dados de anomalia do Fluxo 1, formata a mensagem e envia uma notificação instantânea para o WhatsApp usando o container **WAHA (WhatsApp HTTP API)**.

### Configuração dos Nós:
1. **Webhook (ou Item Input)**:
   - Recebe a lista de anomalias com: `coingecko_id`, `symbol`, `current_price`, `anomaly_score`, `detected_at`.
2. **Set (Formatar Mensagem)**:
   - Crie uma variável `mensagem` contendo o texto formatado. Exemplo de template Markdown:
     ```text
     ⚠️ *ALERTA DE ANOMALIA DE PREÇO* ⚠️

     A criptomoeda *{{ $json.symbol }}* ({{ $json.coingecko_id }}) apresentou um comportamento de preço fora do comum!

     💵 *Preço no Alerta:* ${{ ($json.current_price || $json.price_usd).toFixed(4) }}
     📊 *Score do Isolation Forest:* {{ $json.anomaly_score.toFixed(4) }}
     🕒 *Horário (Brasília):* {{ new Date($json.detected_at).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' }) }}

     _Verifique o painel do Streamlit para mais detalhes._
     ```
3. **HTTP Request (Disparo WAHA)**:
   - **Método**: `POST`
   - **URL**: `http://waha:3000/api/sendText` (ajuste a URL se o container WAHA rodar em outra rede ou porta)
   - **Headers**:
     - `Content-Type`: `application/json`
     - `X-Api-Key`: `sua_chave_se_configurada`
   - **Body (JSON)**:
     ```json
     {
       "chatId": "5511999999999@c.us", // Substitua pelo seu telefone com DDI e DDD
       "text": "{{ $json.mensagem }}"
     }
     ```

---

## 3. Fluxo de Retreino Diário (Model Maintenance)

Para garantir que o modelo `IsolationForest` se adapte às novas condições do mercado, ele deve ser retreinado periodicamente com os dados mais recentes.

### Configuração dos Nós:
1. **Schedule Trigger**:
   - Intervalo: **Diariamente**
   - Horário: **03:00 AM** (Horário de menor volatilidade/uso de servidor)
2. **HTTP Request (FastAPI /train)**:
   - **Método**: `POST`
   - **URL**: `http://crypto_api:8000/train`
   - **Nota**: Este endpoint roda em background de forma assíncrona, respondendo instantaneamente enquanto o script treina as moedas no banco de dados e recarrega os arquivos de peso `.pkl`.

---

## Como Exportar/Importar no n8n

Uma vez criados os fluxos no painel web do seu n8n:
1. Clique no menu de opções do workflow.
2. Selecione **Export** (Exportar como arquivo JSON).
3. Salve os arquivos dentro desta pasta `/n8n` para versionar e documentar o projeto de portfólio (ex: `n8n/workflow_coleta.json`, `n8n/workflow_retreino.json`).
