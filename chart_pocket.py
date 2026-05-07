"""
╔══════════════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO v4.0 — chart_pocket.py                    ║
║         Graficos de velas profissionais + overlays de estrategias    ║
║                                                                      ║
║  NOVIDADES v4.0:                                                     ║
║  • Linhas LTA/LTB desenhadas no grafico                              ║
║  • Niveis Fibonacci sobrepostos                                      ║
║  • Zona de pullback destacada                                        ║
║  • Indicador de timeframe ideal no canto                             ║
║  • Painel extra: ADX com DI+/DI-                                     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import io
import logging
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import numpy as np
import pandas as pd
from datetime import datetime
import pytz

from pocket_ws import get_candles, TODOS_ATIVOS

logger       = logging.getLogger(__name__)
TZ_CORRETORA = pytz.timezone("Africa/Luanda")

# ══════════════════════════════════════════════════════════════
#  TEMA ESCURO PROFISSIONAL
# ══════════════════════════════════════════════════════════════
TEMA = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    marketcolors=mpf.make_marketcolors(
        up="#26a641", down="#da3633",
        edge="inherit", wick="inherit",
        volume={"up": "#26a641", "down": "#da3633"},
    ),
    facecolor="#0d1117", edgecolor="#30363d",
    figcolor="#0d1117", gridcolor="#21262d",
    gridstyle="--", gridaxis="both",
    y_on_right=True,
    rc={
        "axes.labelcolor":  "#8b949e",
        "axes.titlecolor":  "#e6edf3",
        "xtick.color":      "#8b949e",
        "ytick.color":      "#8b949e",
        "text.color":       "#e6edf3",
        "figure.facecolor": "#0d1117",
        "axes.facecolor":   "#161b22",
        "font.family":      "monospace",
    }
)

COR_CALL   = "#26a641"
COR_PUT    = "#da3633"
COR_NEUTRO = "#388bfd"
COR_EMA9   = "#f0b429"
COR_EMA21  = "#a371f7"
COR_VWAP   = "#3fb950"
COR_BB     = "#58a6ff"
COR_RSI    = "#f0b429"
COR_ADX    = "#ff9f43"
COR_DI_P   = "#26a641"
COR_DI_M   = "#da3633"
COR_FIB    = "#e3b341"
COR_LTA    = "#26a641"
COR_LTB    = "#da3633"
COR_PB     = "#a371f7"
COR_TEXTO2 = "#8b949e"
COR_FUNDO  = "#0d1117"
COR_LINHA  = "#30363d"


# ══════════════════════════════════════════════════════════════
#  INDICADORES
# ══════════════════════════════════════════════════════════════
def _calc_ema(close, period):
    return close.ewm(span=period, adjust=False).mean()

def _calc_rsi(close, period=14):
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0)
    loss  = -delta.where(delta < 0, 0.0)
    ag    = gain.ewm(com=period - 1, min_periods=period).mean()
    al    = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = ag / al.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

def _calc_bollinger(close, period=20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma + 2 * std, sma, sma - 2 * std

def _calc_vwap(df):
    tp  = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"].replace(0, np.nan)
    return (tp * vol).cumsum() / vol.cumsum().fillna(tp)

def _calc_adx(high, low, close, period=14):
    tr   = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    pdi  = (high - high.shift()).clip(lower=0)
    mdi  = (low.shift() - low).clip(lower=0)
    atr  = tr.ewm(span=period, adjust=False).mean()
    pdi  = (pdi.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)) * 100
    mdi  = (mdi.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)) * 100
    dx   = ((pdi - mdi).abs() / (pdi + mdi + 1e-10)) * 100
    adx  = dx.ewm(span=period, adjust=False).mean()
    return adx, pdi, mdi

def _calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ══════════════════════════════════════════════════════════════
#  CONVERTER BUFFER -> DATAFRAME
# ══════════════════════════════════════════════════════════════
def _candles_para_df(ativo: str, n: int = 80) -> pd.DataFrame:
    candles = get_candles(ativo, n)
    if not candles or len(candles) < 10:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df.columns = [c.lower() for c in df.columns]
    df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["datetime"] = df["datetime"].dt.tz_convert(TZ_CORRETORA)
    df = df.set_index("datetime")

    df = df.rename(columns={
        "open": "Open", "high": "High",
        "low":  "Low",  "close": "Close", "volume": "Volume",
    })
    df["Volume"] = df["Volume"].replace(0, 1).fillna(1)
    return df[["Open", "High", "Low", "Close", "Volume"]]


# ══════════════════════════════════════════════════════════════
#  CALCULAR NIVEIS FIBONACCI PARA O GRAFICO
# ══════════════════════════════════════════════════════════════
def _fibonacci_levels(high_s: pd.Series, low_s: pd.Series, n=30):
    h = high_s.iloc[-n:]
    l = low_s.iloc[-n:]
    swing_high = float(h.max())
    swing_low  = float(l.min())
    diff = swing_high - swing_low
    return {
        "100%": swing_high,
        "61.8%": swing_high - 0.382 * diff,
        "50%":   swing_high - 0.500 * diff,
        "38.2%": swing_high - 0.618 * diff,
        "0%":    swing_low,
    }


# ══════════════════════════════════════════════════════════════
#  CALCULAR LTA / LTB PARA O GRAFICO
# ══════════════════════════════════════════════════════════════
def _regressao_tendencia(series: pd.Series, n=40):
    """Retorna (slope, intercept, fitted_values[-n:])"""
    vals = series.iloc[-n:].values
    x    = np.arange(len(vals))
    m, b = np.polyfit(x, vals, 1)
    return m, b, np.polyval([m, b], x)


# ══════════════════════════════════════════════════════════════
#  GERAR GRAFICO PRINCIPAL
# ══════════════════════════════════════════════════════════════
def gerar_grafico(
    ativo: str,
    direction: str = "NEUTRO",
    score: int = 0,
    tipo_tendencia: str = "NEUTRO",
    timeframe_ideal: str = "M1",
    score_fibonacci: int = 0,
    score_pullback:  int = 0,
) -> io.BytesIO | None:
    """
    Gera grafico de velas profissional com todos os overlays.
    Retorna BytesIO com PNG para enviar no Telegram.
    """
    df = _candles_para_df(ativo, 80)
    if df.empty or len(df) < 15:
        logger.warning(f"Dados insuficientes para grafico: {ativo}")
        return None

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    # ── Indicadores ──────────────────────────────────────────
    ema9               = _calc_ema(close, 9)
    ema21              = _calc_ema(close, 21)
    bb_up, bb_mid, bb_dn = _calc_bollinger(close)
    vwap               = _calc_vwap(df)
    rsi                = _calc_rsi(close)
    adx, pdi, mdi      = _calc_adx(high, low, close)
    preco              = round(float(close.iloc[-1]), 5)

    # ── Cor e label do sinal ──────────────────────────────────
    if direction == "CALL":
        cor_sinal = COR_CALL
        lbl_sinal = f"▲ CALL   Score: {score}/20"
    elif direction == "PUT":
        cor_sinal = COR_PUT
        lbl_sinal = f"▼ PUT    Score: {score}/20"
    else:
        cor_sinal = COR_NEUTRO
        lbl_sinal = f"◆ NEUTRO Score: {score}/20"

    info   = TODOS_ATIVOS.get(ativo, {})
    nome   = info.get("nome", ativo)
    tipo   = info.get("tipo", "mercado")
    tipo_l = "OTC — Pocket Option" if tipo == "otc" else "Mercado — Yahoo Finance"
    hora   = datetime.now(TZ_CORRETORA).strftime("%d/%m/%Y %H:%M")

    # Icone do timeframe
    tf_icons = {"M1": "⚡M1", "M5": "🕐M5", "M15": "🕒M15", "AGUARDA": "⏸"}
    tf_lbl   = tf_icons.get(timeframe_ideal, timeframe_ideal)

    titulo = f"  {nome}  |  {tipo_l}  |  {hora}  |  {tf_lbl}"

    # ── Linhas adicionais (addplots) ──────────────────────────
    ap = [
        mpf.make_addplot(ema9,   color=COR_EMA9,  width=1.3),
        mpf.make_addplot(ema21,  color=COR_EMA21, width=1.3),
        mpf.make_addplot(bb_up,  color=COR_BB,    width=0.9, linestyle="--", alpha=0.55),
        mpf.make_addplot(bb_mid, color=COR_BB,    width=0.6, linestyle=":",  alpha=0.4),
        mpf.make_addplot(bb_dn,  color=COR_BB,    width=0.9, linestyle="--", alpha=0.55),
        mpf.make_addplot(vwap,   color=COR_VWAP,  width=1.1, linestyle="-."),
        # RSI panel
        mpf.make_addplot(rsi,    color=COR_RSI,   width=1.1,
                         panel=2, ylabel="RSI", ylim=(0, 100)),
        # ADX panel
        mpf.make_addplot(adx,    color=COR_ADX,   width=1.2,
                         panel=3, ylabel="ADX"),
        mpf.make_addplot(pdi,    color=COR_DI_P,  width=0.8, linestyle="--",
                         panel=3),
        mpf.make_addplot(mdi,    color=COR_DI_M,  width=0.8, linestyle="--",
                         panel=3),
    ]

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=TEMA,
        addplot=ap,
        volume=True,
        panel_ratios=(5, 1.2, 1.2, 1.2),
        figsize=(14, 10),
        title=titulo,
        returnfig=True,
        warn_too_much_data=200,
        tight_layout=True,
        show_nontrading=False,
    )

    ax_velas = axes[0]
    n_bars   = len(df)

    # ── Linha horizontal no preco actual ─────────────────────
    ax_velas.axhline(y=preco, color=cor_sinal, linewidth=1.1, linestyle="--", alpha=0.85)
    ax_velas.text(
        n_bars - 1, preco, f"  {preco}",
        color=cor_sinal, fontsize=8.5, fontweight="bold", va="center"
    )

    # ── Caixa do sinal ────────────────────────────────────────
    ax_velas.text(
        0.99, 0.97, lbl_sinal,
        transform=ax_velas.transAxes,
        color=cor_sinal, fontsize=11, fontweight="bold",
        va="top", ha="right",
        bbox=dict(boxstyle="round,pad=0.5", facecolor=COR_FUNDO,
                  edgecolor=cor_sinal, linewidth=2.0, alpha=0.93)
    )

    # ── OVERLAY: LTA / LTB ───────────────────────────────────
    n_reg = min(40, n_bars)
    if tipo_tendencia == "LTA":
        _, _, fitted_low = _regressao_tendencia(low, n_reg)
        xs = np.arange(n_bars - n_reg, n_bars)
        ax_velas.plot(xs, fitted_low, color=COR_LTA, linewidth=1.6,
                      linestyle="-", alpha=0.85, label="LTA")
        ax_velas.text(
            n_bars - 1, fitted_low[-1], "  LTA",
            color=COR_LTA, fontsize=8, fontweight="bold", va="bottom"
        )
    elif tipo_tendencia == "LTB":
        _, _, fitted_high = _regressao_tendencia(high, n_reg)
        xs = np.arange(n_bars - n_reg, n_bars)
        ax_velas.plot(xs, fitted_high, color=COR_LTB, linewidth=1.6,
                      linestyle="-", alpha=0.85, label="LTB")
        ax_velas.text(
            n_bars - 1, fitted_high[-1], "  LTB",
            color=COR_LTB, fontsize=8, fontweight="bold", va="top"
        )

    # ── OVERLAY: FIBONACCI ────────────────────────────────────
    if abs(score_fibonacci) >= 1:
        fibs = _fibonacci_levels(high, low)
        fib_alphas = {"100%": 0.25, "61.8%": 0.60, "50%": 0.50, "38.2%": 0.60, "0%": 0.25}
        for lbl, nivel in fibs.items():
            a = fib_alphas.get(lbl, 0.4)
            ax_velas.axhline(y=nivel, color=COR_FIB, linewidth=0.7,
                              linestyle=":", alpha=a)
            ax_velas.text(
                0.01, nivel, f" Fib {lbl}",
                transform=ax_velas.get_yaxis_transform(),
                color=COR_FIB, fontsize=6.5, alpha=a + 0.1, va="bottom"
            )

    # ── OVERLAY: PULLBACK zona ────────────────────────────────
    if abs(score_pullback) >= 1:
        ema9_v  = float(ema9.iloc[-1])
        ema21_v = float(ema21.iloc[-1])
        atr_v   = float(_calc_atr(high, low, close).iloc[-1]) * 0.4
        zona_low  = min(ema9_v, ema21_v) - atr_v
        zona_high = max(ema9_v, ema21_v) + atr_v
        ax_velas.axhspan(
            zona_low, zona_high,
            alpha=0.07, color=COR_PB, label="Zona Pullback"
        )
        ax_velas.text(
            0.01, (zona_low + zona_high) / 2, " PULLBACK",
            transform=ax_velas.get_yaxis_transform(),
            color=COR_PB, fontsize=6.5, alpha=0.7, va="center"
        )

    # ── RSI: linhas de referencia ─────────────────────────────
    try:
        ax_rsi = axes[4] if len(axes) > 4 else axes[-2]
        ax_rsi.axhline(70, color=COR_PUT,    linewidth=0.8, linestyle="--", alpha=0.7)
        ax_rsi.axhline(30, color=COR_CALL,   linewidth=0.8, linestyle="--", alpha=0.7)
        ax_rsi.axhline(50, color=COR_TEXTO2, linewidth=0.5, linestyle=":",  alpha=0.4)
    except Exception:
        pass

    # ── ADX: linha de referencia (25) ────────────────────────
    try:
        ax_adx = axes[6] if len(axes) > 6 else axes[-1]
        ax_adx.axhline(25, color=COR_ADX, linewidth=0.8, linestyle="--", alpha=0.6)
        ax_adx.text(0, 25.5, " 25", color=COR_ADX, fontsize=6, alpha=0.7)
    except Exception:
        pass

    # ── Legenda ───────────────────────────────────────────────
    handles = [
        plt.Line2D([0],[0], color=COR_EMA9,  linewidth=1.5, label="EMA 9"),
        plt.Line2D([0],[0], color=COR_EMA21, linewidth=1.5, label="EMA 21"),
        plt.Line2D([0],[0], color=COR_BB,    linewidth=1.0, linestyle="--", label="Bollinger"),
        plt.Line2D([0],[0], color=COR_VWAP,  linewidth=1.0, linestyle="-.", label="VWAP"),
        plt.Line2D([0],[0], color=COR_FIB,   linewidth=1.0, linestyle=":",  label="Fibonacci"),
    ]
    if tipo_tendencia == "LTA":
        handles.append(plt.Line2D([0],[0], color=COR_LTA, linewidth=1.5, label="LTA"))
    elif tipo_tendencia == "LTB":
        handles.append(plt.Line2D([0],[0], color=COR_LTB, linewidth=1.5, label="LTB"))
    if abs(score_pullback) >= 1:
        handles.append(mpatches.Patch(color=COR_PB, alpha=0.3, label="Pullback"))

    ax_velas.legend(
        handles=handles, loc="upper left", fontsize=7,
        facecolor=COR_FUNDO, edgecolor=COR_LINHA,
        labelcolor=COR_TEXTO2, framealpha=0.85,
    )

    # ── Rodape ────────────────────────────────────────────────
    fig.text(
        0.5, 0.003,
        "Testa SEMPRE na conta DEMO primeiro!  |  Max 2% do saldo por operacao  |  v4.0",
        ha="center", fontsize=6.5, color=COR_TEXTO2, alpha=0.65
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130,
                bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    buf.seek(0)
    return buf
