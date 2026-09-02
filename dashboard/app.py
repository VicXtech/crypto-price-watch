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

# Custom Styling (Dark Glassmorphic Theme with Uniform Height Cards & Interactive Reload Button)
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    
    /* 1. Metric Cards: Exact Same Height, Centered & Normal Default Cursor */
    [data-testid="stMetric"] {
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        text-align: center !important;
        background: #161922 !important;
        height: 145px !important;
        min-height: 145px !important;
        max-height: 145px !important;
        padding: 16px 12px !important;
        border-radius: 12px !important;
        border: 1px solid #262b38 !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3) !important;
        width: 100% !important;
        cursor: default !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }
    [data-testid="stMetric"]:hover {
        border-color: #00c0f2 !important;
        box-shadow: 0 4px 20px rgba(0, 192, 242, 0.2) !important;
        cursor: default !important;
    }
    [data-testid="stMetric"] * {
        cursor: default !important;
        user-select: none !important;
    }
    [data-testid="stMetricLabel"] {
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
        text-align: center !important;
        cursor: default !important;
    }
    [data-testid="stMetricLabel"] p {
        text-align: center !important;
        width: 100% !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        color: #94a3b8 !important;
        margin: 0 !important;
        cursor: default !important;
    }
    [data-testid="stMetricValue"] {
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
        text-align: center !important;
        margin: 4px 0 !important;
        cursor: default !important;
    }
    [data-testid="stMetricValue"] div {
        text-align: center !important;
        font-size: 26px !important;
        font-weight: 700 !important;
        color: #ffffff !important;
        cursor: default !important;
    }
    [data-testid="stMetricDelta"] {
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
        text-align: center !important;
        cursor: default !important;
    }
    [data-testid="stMetricDelta"] div {
        text-align: center !important;
        cursor: default !important;
    }

    /* 2. Sidebar: Centering for Radio Buttons & Selectable Options */
    [data-testid="stSidebar"] [data-testid="stRadio"],
    [data-testid="stSidebar"] [data-testid="stRadio"] > div,
    [data-testid="stSidebar"] div[role="radiogroup"],
    div[data-testid="stRadio"] div[role="radiogroup"] {
        display: flex !important;
        flex-direction: row !important;
        justify-content: center !important;
        align-items: center !important;
        text-align: center !important;
        width: 100% !important;
        margin-left: auto !important;
        margin-right: auto !important;
        gap: 28px !important;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label,
    div[data-testid="stRadio"] div[role="radiogroup"] label {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label p,
    div[data-testid="stRadio"] div[role="radiogroup"] label p {
        font-size: 16px !important;
        font-weight: 600 !important;
        color: #ffffff !important;
        text-align: center !important;
    }

    /* 3. Reload Button: Dark Card Styling, Balanced Size (17px bold), Turns Solid Blue on Hover! */
    [data-testid="stSidebar"] div[data-testid="stButton"],
    div[data-testid="stButton"] {
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
        margin-top: 14px !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button,
    div[data-testid="stButton"] > button {
        width: 100% !important;
        min-height: 50px !important;
        background: #161922 !important;
        color: #00c0f2 !important;
        font-size: 17px !important;
        font-weight: 700 !important;
        padding: 12px 18px !important;
        border: 1px solid #262b38 !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3) !important;
        letter-spacing: 0.3px !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button p,
    div[data-testid="stButton"] > button p {
        font-size: 17px !important;
        font-weight: 700 !important;
        color: inherit !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button:hover,
    div[data-testid="stButton"] > button:hover {
        background: linear-gradient(135deg, #0284c7 0%, #00c0f2 100%) !important;
        border: 1px solid #00c0f2 !important;
        color: #ffffff !important;
        box-shadow: 0 6px 26px rgba(0, 192, 242, 0.7) !important;
        transform: translateY(-2px) !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button:hover p,
    div[data-testid="stButton"] > button:hover p {
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button:active,
    div[data-testid="stButton"] > button:active {
        transform: translateY(0px) !important;
        box-shadow: 0 2px 10px rgba(0, 192, 242, 0.5) !important;
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
def fetch_recent_anomalies(limit=30):
    query = """
        SELECT a.id, c.name, c.symbol, a.current_price, a.anomaly_score, a.detected_at, a.alert_sent
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

    # Currency Conversion Selector (Larger Centered Title, No Subtitle, Centered Radios)
    st.sidebar.markdown("---")
    st.sidebar.markdown("<h3 style='text-align: center; font-size: 20px; font-weight: 700; margin-bottom: 12px; color: #ffffff;'>Moeda de Exibição</h3>", unsafe_allow_html=True)
    _, col_radio, _ = st.sidebar.columns([1, 4.5, 1])
    with col_radio:
        currency_mode = st.radio(
            label="Moeda de Exibição",
            options=["USD ($)", "BRL (R$)"],
            index=0,
            horizontal=True,
            label_visibility="collapsed"
        )

    
    is_brl = currency_mode == "BRL (R$)"
    curr_prefix = "R$" if is_brl else "$"
    usd_brl_rate = get_usd_brl_rate() if is_brl else 1.0
    
    if is_brl:
        st.sidebar.info(f"💵 Cotação Comercial: **R$ {usd_brl_rate:.4f}** / USD")

    # Refresh Button (Card-like styling, larger text, full solid blue on hover)
    st.sidebar.markdown("---")
    if st.sidebar.button("Atualizar Dados", use_container_width=True):
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
        
        # Display 4 Metrics columns (All equal height, centered, normal cursor)
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
    
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader("Últimas Anomalias Detectadas (Geral)")
    with col_header2:
        filter_coin = st.selectbox(
            "Filtrar por Cripto:",
            ["Todas"] + list(coins_df["name"].unique()),
            key="table_coin_filter"
        )
    
    anomalies_table_df = fetch_recent_anomalies(limit=30)
    
    if anomalies_table_df.empty:
        st.info("Nenhuma anomalia registrada no banco de dados até o momento.")
    else:
        multiplier = usd_brl_rate if is_brl else 1.0
        anomalies_display = anomalies_table_df.copy()
        
        # Apply interactive filter if selected
        if filter_coin != "Todas":
            anomalies_display = anomalies_display[anomalies_display["name"] == filter_coin]

        # Convert and format current price in selected currency
        anomalies_display["current_price"] = (anomalies_display["current_price"] * multiplier).apply(
            lambda val: format_crypto_price(val, curr_prefix)
        )
        anomalies_display["detected_at"] = to_brasilia_tz(anomalies_display["detected_at"]).dt.strftime('%d/%m/%Y %H:%M:%S')
        anomalies_display["anomaly_score"] = anomalies_display["anomaly_score"].round(4)
        
        # Responsive, real dynamic status
        anomalies_display["alert_sent"] = anomalies_display["alert_sent"].apply(
            lambda x: "🟢 WhatsApp Enviado" if x else "🟡 Em Fila / Pendente"
        )
        
        # Select and rename columns for display
        display_cols = ["name", "symbol", "current_price", "anomaly_score", "detected_at", "alert_sent"]
        anomalies_final = anomalies_display[display_cols].copy()
        anomalies_final.columns = [
            "Moeda", "Símbolo", f"Preço no Alerta ({curr_prefix})", "Score ML", "Data/Hora (Brasília)", "Status do Alerta"
        ]
        
        # Render clean, responsive table without row index numbers
        st.dataframe(
            anomalies_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Status do Alerta": st.column_config.TextColumn(
                    "Status do Alerta",
                    help="Status de envio do alerta via n8n / WhatsApp",
                ),
                "Score ML": st.column_config.NumberColumn(
                    "Score ML",
                    format="%.4f"
                )
            }
        )

except Exception as e:
    st.error(f"Erro ao carregar dados do dashboard: {e}")
