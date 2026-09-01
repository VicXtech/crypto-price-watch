import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta, timezone
import urllib.request
import json

def to_brasilia_tz(series: pd.Series) -> pd.Series:
    """Converts a pandas datetime Series to America/Sao_Paulo timezone."""
    dt = pd.to_datetime(series)
    if dt.dt.tz is None:
        return dt.dt.tz_localize("UTC").dt.tz_convert("America/Sao_Paulo")
    return dt.dt.tz_convert("America/Sao_Paulo")

def format_crypto_price(val: float, currency_prefix: str = "$") -> str:
    """
    Formats crypto prices gracefully for both large assets (BTC/ETH)
    and micro-cap tokens (PEPE) without truncation to 0.0000.
    """
    if val is None or pd.isna(val):
        return "-"
    val = float(val)
    if abs(val) >= 1.0:
        return f"{currency_prefix} {val:,.2f}"
    elif abs(val) >= 0.01:
        return f"{currency_prefix} {val:,.4f}"
    elif abs(val) >= 0.0001:
        return f"{currency_prefix} {val:,.6f}"
    else:
        # For micro tokens like PEPE (e.g. 0.00000356)
        formatted = f"{val:.8f}".rstrip("0")
        if formatted == "0.":
            formatted = f"{val:.10f}"
        return f"{currency_prefix} {formatted}"

@st.cache_data(ttl=300)
def get_usd_brl_rate() -> float:
    """
    Fetches the live USD to BRL exchange rate from AwesomeAPI with automatic fallback.
    Cached for 5 minutes.
    """
    try:
        req = urllib.request.Request(
            "https://economia.awesomeapi.com.br/last/USD-BRL",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            return float(data["USDBRL"]["bid"])
    except Exception:
        try:
            req = urllib.request.Request(
                "https://api.frankfurter.app/latest?from=USD&to=BRL",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                return float(data["rates"]["BRL"])
        except Exception:
            return 5.15

# Streamlit Page Setup
st.set_page_config(
    page_title="Crypto Price Watch",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    .metric-card {
        background-color: #1e222b;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        border-left: 5px solid #00c0f2;
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
        color: #ffffff;
    }
    .metric-label {
        font-size: 14px;
        color: #8a9ba8;
    }
</style>
""", unsafe_allow_html=True)

# Database Connection Helper
@st.cache_resource
def get_db_engine():
    db_url = os.getenv(
        "DATABASE_URL", 
        "postgresql://crypto:crypto_dev_password@localhost:5432/crypto_price_watch"
    )
    return create_engine(db_url)

engine = get_db_engine()

# Fetch active coins from DB
def fetch_coins():
    query = "SELECT id, coingecko_id, symbol, name FROM coins WHERE active = TRUE ORDER BY id ASC;"
    with engine.connect() as conn:
        return pd.read_sql(query, conn)

# Fetch price history with anomalies
def fetch_price_data(coin_id, days):
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
    query = """
        SELECT ph.current_price, ph.market_cap, ph.total_volume, ph.collected_at,
               pf.sma_6h, pf.ema_24h, pf.pct_change_1h, pf.volatility_24h,
               a.anomaly_score
        FROM price_history ph
        LEFT JOIN price_features pf ON ph.coin_id = pf.coin_id AND ph.collected_at = pf.collected_at
        LEFT JOIN anomalies a ON ph.coin_id = a.coin_id AND ph.collected_at = a.detected_at
        WHERE ph.coin_id = :coin_id AND ph.collected_at >= :cutoff
        ORDER BY ph.collected_at ASC;
    """
    with engine.connect() as conn:
        df = pd.read_sql(
            text(query), 
            conn, 
            params={"coin_id": int(coin_id), "cutoff": cutoff_time}
        )
    if not df.empty and "collected_at" in df.columns:
        df["collected_at"] = to_brasilia_tz(df["collected_at"])
    return df

# Fetch recent anomalies table
def fetch_recent_anomalies(limit=15):
    query = """
        SELECT c.name, c.symbol, a.current_price, a.anomaly_score, a.detected_at, a.alert_sent
        FROM anomalies a
        JOIN coins c ON a.coin_id = c.id
        ORDER BY a.detected_at DESC
        LIMIT :limit;
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params={"limit": limit})

# Streamlit UI Header
st.title("📈 Crypto Price Watch")
st.markdown("Monitoramento inteligente de preços e detecção de anomalias com **Machine Learning**.")

# Sidebar Filters
st.sidebar.header("Filtros e Configurações")

try:
    coins_df = fetch_coins()
    if coins_df.empty:
        st.warning("⚠️ Nenhuma moeda encontrada no banco de dados. Certifique-se de que a coleta via n8n/API está funcionando.")
        st.stop()
        
    coin_options = {f"{row['name']} ({row['symbol']})": row for idx, row in coins_df.iterrows()}
    selected_coin_name = st.sidebar.selectbox("Selecione a Criptomoeda", list(coin_options.keys()))
    selected_coin = coin_options[selected_coin_name]
    
    time_window_label = st.sidebar.selectbox(
        "Janela Temporal",
        ["Últimas 24 horas", "Últimos 7 dias", "Últimos 30 dias", "Todo o Histórico"]
    )
    
    days_map = {
        "Últimas 24 horas": 1,
        "Últimos 7 dias": 7,
        "Últimos 30 dias": 30,
        "Todo o Histórico": 365
    }
    days = days_map[time_window_label]

    # Currency Conversion Selector
    st.sidebar.markdown("---")
    st.sidebar.subheader("💱 Moeda de Exibição")
    currency_mode = st.sidebar.radio(
        "Visualizar valores em:",
        options=["USD ($)", "BRL (R$)"],
        index=0,
        horizontal=True
    )
    
    is_brl = currency_mode == "BRL (R$)"
    curr_prefix = "R$" if is_brl else "$"
    usd_brl_rate = get_usd_brl_rate() if is_brl else 1.0
    
    if is_brl:
        st.sidebar.info(f"💵 Cotação Comercial: **R$ {usd_brl_rate:.4f}** / USD")

    # Refresh button
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Atualizar Dados"):
        st.cache_data.clear()
        
    # Main Dashboard Page Content
    data_df = fetch_price_data(selected_coin["id"], days)
    
    if data_df.empty:
        st.info(f"Sem dados de preço para {selected_coin['name']} no período selecionado.")
    else:
        # Apply conversion multiplier
        multiplier = usd_brl_rate if is_brl else 1.0
        data_df["display_price"] = data_df["current_price"] * multiplier
        
        if "ema_24h" in data_df.columns and data_df["ema_24h"].notna().any():
            data_df["display_ema_24h"] = data_df["ema_24h"] * multiplier
        else:
            data_df["display_ema_24h"] = None

        if "sma_6h" in data_df.columns and data_df["sma_6h"].notna().any():
            data_df["display_sma_6h"] = data_df["sma_6h"] * multiplier
        else:
            data_df["display_sma_6h"] = None

        # Build formatted text columns for hover tooltips (prevents 0.0000 on low-value tokens)
        data_df["price_hover"] = data_df["display_price"].apply(lambda v: format_crypto_price(v, curr_prefix))
        if data_df["display_ema_24h"] is not None:
            data_df["ema_hover"] = data_df["display_ema_24h"].apply(lambda v: format_crypto_price(v, curr_prefix))
        
        # Latest data summary metrics
        latest = data_df.iloc[-1]
        
        price = latest["display_price"]
        pct_change = latest["pct_change_1h"] if pd.notna(latest["pct_change_1h"]) else 0.0
        volatility = latest["volatility_24h"] if pd.notna(latest["volatility_24h"]) else 0.0
        
        # Determine anomaly status of latest point
        is_latest_anomaly = pd.notna(latest["anomaly_score"])
        
        price_fmt = format_crypto_price(price, curr_prefix)
        pct_fmt = f"{pct_change * 100:+.2f}%"
        vol_fmt = f"{volatility * 100:.2f}%"
        
        # Display 4 Metrics columns
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label=f"Preço Atual ({curr_prefix})",
                value=price_fmt
            )
            
        with col2:
            st.metric(
                label="Variação Período",
                value=pct_fmt,
                delta=pct_fmt
            )
            
        with col3:
            st.metric(
                label="Volatilidade (24h)",
                value=vol_fmt
            )
            
        with col4:
            if is_latest_anomaly:
                st.metric(
                    label="Status do Preço",
                    value="⚠️ ANOMALIA",
                    delta=f"Score: {latest['anomaly_score']:.4f}",
                    delta_color="inverse"
                )
            else:
                st.metric(
                    label="Status do Preço",
                    value="✅ Normal",
                    delta="Preço estável"
                )

        st.markdown("---")
        
        # Graph Section
        st.subheader(f"Gráfico de Histórico de Preço e Anomalias ({curr_prefix})")
        
        # Plotly chart setup
        fig = go.Figure()
        
        # Price Line
        fig.add_trace(go.Scatter(
            x=data_df["collected_at"],
            y=data_df["display_price"],
            mode='lines',
            name=f'Preço ({curr_prefix})',
            line=dict(color='#00c0f2', width=2),
            customdata=data_df["price_hover"],
            hovertemplate='Data: %{x|%d/%m/%Y %H:%M:%S}<br>Preço: %{customdata}<extra></extra>'
        ))
        
        # EMA Line (Optional overlay)
        if data_df["display_ema_24h"] is not None and not data_df["display_ema_24h"].isna().all():
            fig.add_trace(go.Scatter(
                x=data_df["collected_at"],
                y=data_df["display_ema_24h"],
                mode='lines',
                name=f'EMA 24h ({curr_prefix})',
                line=dict(color='#ff9900', width=1.5, dash='dash'),
                customdata=data_df["ema_hover"],
                hovertemplate='Data: %{x|%d/%m/%Y %H:%M:%S}<br>EMA 24h: %{customdata}<extra></extra>'
            ))

        # Anomalies Markers
        anomaly_df = data_df[data_df["anomaly_score"].notna()]
        if not anomaly_df.empty:
            custom_anomaly = np.stack(
                (anomaly_df["price_hover"], anomaly_df["anomaly_score"]), 
                axis=-1
            )
            fig.add_trace(go.Scatter(
                x=anomaly_df["collected_at"],
                y=anomaly_df["display_price"],
                mode='markers',
                name='Anomalias Detectadas',
                marker=dict(color='#ff3333', size=10, symbol='circle-open-dot', line=dict(color='#ffffff', width=2)),
                customdata=custom_anomaly,
                # Note: <extra></extra> suppresses the secondary trace name box
                hovertemplate='<b>⚠️ ANOMALIA DETECTADA</b><br>Data: %{x|%d/%m/%Y %H:%M:%S}<br>Preço: %{customdata[0]}<br>Score: %{customdata[1]:.4f}<extra></extra>'
            ))

        # Chart Layout Customization
        fig.update_layout(
            template="plotly_dark",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=20, r=20, t=20, b=20),
            height=500,
            hoverlabel=dict(
                bgcolor="#1e222b",
                font_size=13,
                font_family="sans-serif",
                font_color="#ffffff",
                bordercolor="#00c0f2"
            ),
            xaxis=dict(showgrid=True, gridcolor='#222730'),
            yaxis=dict(showgrid=True, gridcolor='#222730', tickprefix=f"{curr_prefix} "),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig, use_container_width=True)

    # Historical Anomalies list section
    st.markdown("---")
    st.subheader("⚠️ Últimas Anomalias Detectadas (Geral)")
    
    anomalies_table_df = fetch_recent_anomalies(limit=15)
    
    if anomalies_table_df.empty:
        st.info("Nenhuma anomalia registrada no banco de dados até o momento.")
    else:
        multiplier = usd_brl_rate if is_brl else 1.0
        anomalies_display = anomalies_table_df.copy()
        
        # Convert and format current price in selected currency
        anomalies_display["current_price"] = (anomalies_display["current_price"] * multiplier).apply(
            lambda val: format_crypto_price(val, curr_prefix)
        )
        anomalies_display["detected_at"] = to_brasilia_tz(anomalies_display["detected_at"]).dt.strftime('%d/%m/%Y %H:%M:%S')
        anomalies_display["anomaly_score"] = anomalies_display["anomaly_score"].round(4)
        anomalies_display["alert_sent"] = anomalies_display["alert_sent"].apply(
            lambda x: "📱 WhatsApp Enviado" if x else "⏳ Pendente/Desabilitado"
        )
        
        # Rename columns for localized Portuguese headers
        anomalies_display.columns = [
            "Moeda", "Símbolo", f"Preço no Alerta ({curr_prefix})", "Score ML", "Data/Hora (Brasília)", "Alerta"
        ]
        
        st.dataframe(anomalies_display, use_container_width=True)

except Exception as e:
    st.error(f"Erro ao carregar dados do dashboard: {e}")
