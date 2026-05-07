"""
╔══════════════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO v5.0 — signals_pocket.py                  ║
║         Motor de analise tecnica PROFISSIONAL                        ║
║                                                                      ║
║  INDICADORES BASE (10):                                              ║
║  • RSI, EMA 9/21/50/200, MACD, Bollinger, Estocastico               ║
║  • ADX/DI+/DI-, VWAP, Williams %R, CCI                              ║
║  • SuperTrend (NOVO) — sinal de tendencia de alta precisao          ║
║                                                                      ║
║  ESTRATEGIAS (5):                                                    ║
║  • Reversao confirmada (multi-indicador)                             ║
║  • Retracao Fibonacci (38.2% / 50% / 61.8%)                         ║
║  • LTA / LTB (Linha de Tendencia)                                    ║
║  • Falso Rompimento (Fakeout)                                        ║
║  • Pullback para EMA                                                 ║
║                                                                      ║
║  SCORE MAX: 25 pontos                                                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import pytz
from pocket_ws import get_candles, TODOS_ATIVOS, hora_corretora

TZ_CORRETORA = pytz.timezone("Africa/Luanda")  # GMT+1

EXPIRACOES = {
    "5s":   {"label": "5 Segundos",    "minutos": 0,   "segundos": 5,    "turbo": True},
    "10s":  {"label": "10 Segundos",   "minutos": 0,   "segundos": 10,   "turbo": True},
    "1m":   {"label": "1 Minuto",      "minutos": 1,   "segundos": 60,   "turbo": False},
    "5m":   {"label": "5 Minutos",     "minutos": 5,   "segundos": 300,  "turbo": False},
    "15m":  {"label": "15 Minutos",    "minutos": 15,  "segundos": 900,  "turbo": False},
    "1h45": {"label": "1h 45 Minutos", "minutos": 105, "segundos": 6300, "turbo": False},
}

# Emojis por categoria
CATEGORIA_EMOJI = {
    "forex":       "💱",
    "crypto":      "🪙",
    "acoes":       "📈",
    "indices":     "📊",
    "commodities": "🏅",
    "otc":         "🌙",
}

CATEGORIA_LABEL = {
    "forex":       "FOREX",
    "crypto":      "CRYPTO",
    "acoes":       "ACOES USA",
    "indices":     "INDICE",
    "commodities": "COMMODITY",
    "otc":         "OTC",
}


# ══════════════════════════════════════════════════════════════
#  INDICADORES TECNICOS
# ══════════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period=14) -> pd.Series:
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0)
    loss  = -delta.where(delta < 0, 0.0)
    ag    = gain.ewm(com=period - 1, min_periods=period).mean()
    al    = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = ag / al.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()

def calc_macd(close: pd.Series):
    ema12  = calc_ema(close, 12)
    ema26  = calc_ema(close, 26)
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal

def calc_bollinger(close: pd.Series, period=20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma + 2*std, sma, sma - 2*std

def calc_stoch(high, low, close, k=14, d=3):
    low_min  = low.rolling(k).min()
    high_max = high.rolling(k).max()
    stk      = 100 * (close - low_min) / (high_max - low_min + 1e-10)
    std      = stk.rolling(d).mean()
    return stk, std

def calc_adx(high, low, close, period=14):
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

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    return (tp * vol).cumsum() / vol.cumsum().fillna(tp)

def calc_williams_r(high, low, close, period=14):
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    return -100 * (hh - close) / (hh - ll + 1e-10)

def calc_cci(high, low, close, period=20):
    tp  = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * mad + 1e-10)

def calc_atr(high, low, close, period=14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def calc_supertrend(high, low, close, period=10, multiplier=3.0):
    """
    SuperTrend — indicador de tendencia de alta precisao.
    Retorna (supertrend_series, direction_series)
    direction: 1 = bullish (CALL), -1 = bearish (PUT)
    """
    atr    = calc_atr(high, low, close, period)
    hl2    = (high + low) / 2
    upper  = hl2 + multiplier * atr
    lower  = hl2 - multiplier * atr

    supertrend = pd.Series(index=close.index, dtype=float)
    direction  = pd.Series(1, index=close.index, dtype=int)

    for i in range(1, len(close)):
        prev_close = close.iloc[i - 1]
        prev_st    = supertrend.iloc[i - 1] if i > 1 else lower.iloc[i]
        prev_dir   = direction.iloc[i - 1]

        # Upper band
        ub = upper.iloc[i]
        if prev_dir == 1:
            ub = min(ub, upper.iloc[i - 1]) if i > 1 else ub

        # Lower band
        lb = lower.iloc[i]
        if prev_dir == -1:
            lb = max(lb, lower.iloc[i - 1]) if i > 1 else lb

        if prev_dir == 1:
            if close.iloc[i] < lb:
                direction.iloc[i] = -1
                supertrend.iloc[i] = ub
            else:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lb
        else:
            if close.iloc[i] > ub:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lb
            else:
                direction.iloc[i] = -1
                supertrend.iloc[i] = ub

    supertrend.iloc[0] = lower.iloc[0]
    return supertrend, direction


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 1 — REVERSAO
# ══════════════════════════════════════════════════════════════

def estrategia_reversao(close, high, low, rsi_s, stk_s, bb_up, bb_dn) -> tuple[int, list]:
    score  = 0
    razoes = []
    p      = close.iloc[-1]
    p_prev = close.iloc[-2]
    rsi_v  = rsi_s.iloc[-1]
    stk_v  = stk_s.iloc[-1]
    bb_u   = bb_up.iloc[-1]
    bb_d   = bb_dn.iloc[-1]

    conf_bull = sum([rsi_v < 30, stk_v < 20, p <= bb_d, p > p_prev])
    conf_bear = sum([rsi_v > 70, stk_v > 80, p >= bb_u, p < p_prev])

    if conf_bull >= 3:
        score += 3
        razoes.append(f"[REVERSAO BULLISH] {conf_bull}/4 confirmacoes — RSI:{rsi_v:.1f} Stoch:{stk_v:.1f}")
    elif conf_bull == 2:
        score += 1
        razoes.append(f"[REVERSAO BULLISH parcial] {conf_bull}/4 sinais")
    elif conf_bear >= 3:
        score -= 3
        razoes.append(f"[REVERSAO BEARISH] {conf_bear}/4 confirmacoes — RSI:{rsi_v:.1f} Stoch:{stk_v:.1f}")
    elif conf_bear == 2:
        score -= 1
        razoes.append(f"[REVERSAO BEARISH parcial] {conf_bear}/4 sinais")
    else:
        razoes.append("[REVERSAO] Sem sinal claro")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 2 — FIBONACCI
# ══════════════════════════════════════════════════════════════

def estrategia_retracao(close, high, low) -> tuple[int, list]:
    score  = 0
    razoes = []
    n      = min(30, len(close))
    c      = close.iloc[-n:]
    h      = high.iloc[-n:]
    l      = low.iloc[-n:]
    p      = close.iloc[-1]

    swing_high = float(h.max())
    swing_low  = float(l.min())
    diff       = swing_high - swing_low

    if diff < 1e-6:
        razoes.append("[FIBONACCI] Amplitude insuficiente")
        return 0, razoes

    fib382 = swing_high - 0.382 * diff
    fib500 = swing_high - 0.500 * diff
    fib618 = swing_high - 0.618 * diff
    tol    = diff * 0.04

    idx_high      = int(h.values.argmax())
    idx_low       = int(l.values.argmin())
    tendencia_up  = idx_low < idx_high

    zona = None
    for nivel, nome in [(fib382, "38.2%"), (fib500, "50%"), (fib618, "61.8%")]:
        if abs(p - nivel) <= tol:
            zona = nome
            break

    if zona:
        if tendencia_up:
            score += 2
            razoes.append(f"[FIBONACCI] Retracao {zona} em tendencia UP — CALL")
        else:
            score -= 2
            razoes.append(f"[FIBONACCI] Retracao {zona} em tendencia DOWN — PUT")
    else:
        razoes.append(f"[FIBONACCI] Fora de zona ({fib382:.5f}/{fib500:.5f}/{fib618:.5f})")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 3 — LTA / LTB
# ══════════════════════════════════════════════════════════════

def estrategia_lta_ltb(close, high, low) -> tuple[int, list, str]:
    score  = 0
    razoes = []
    n      = min(40, len(close))
    x      = np.arange(n)
    c      = close.iloc[-n:].values
    h      = high.iloc[-n:].values
    l      = low.iloc[-n:].values
    p      = float(close.iloc[-1])

    def reg(y):
        m = np.polyfit(x, y, 1)
        return m[0], np.polyval(m, x)

    slope_close, _  = reg(c)
    _, fitted_high  = reg(h)
    _, fitted_low   = reg(l)

    lta_val = fitted_low[-1]
    ltb_val = fitted_high[-1]
    tol     = float(calc_atr(pd.Series(h), pd.Series(l), pd.Series(c)).iloc[-1]) * 0.5
    tipo    = "NEUTRO"

    if slope_close > 0:
        tipo = "LTA"
        if abs(p - lta_val) <= tol:
            score += 2
            razoes.append(f"[LTA] Toque na LTA ({lta_val:.5f}) — CALL")
        elif p > lta_val:
            score += 1
            razoes.append(f"[LTA] Acima da LTA — tendencia altista")
        else:
            score -= 1
            razoes.append(f"[LTA] Abaixo da LTA — quebra de suporte")
    elif slope_close < 0:
        tipo = "LTB"
        if abs(p - ltb_val) <= tol:
            score -= 2
            razoes.append(f"[LTB] Toque na LTB ({ltb_val:.5f}) — PUT")
        elif p < ltb_val:
            score -= 1
            razoes.append(f"[LTB] Abaixo da LTB — tendencia baixista")
        else:
            score += 1
            razoes.append(f"[LTB] Acima da LTB — possivel reversao")
    else:
        razoes.append("[LTA/LTB] Mercado lateral")

    return score, razoes, tipo


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 4 — FALSO ROMPIMENTO (FAKEOUT)
# ══════════════════════════════════════════════════════════════

def estrategia_falso_rompimento(open_, high, low, close, bb_up, bb_dn) -> tuple[int, list]:
    score  = 0
    razoes = []

    o  = float(open_.iloc[-1])
    h  = float(high.iloc[-1])
    l  = float(low.iloc[-1])
    c  = float(close.iloc[-1])
    bu = float(bb_up.iloc[-1])
    bd = float(bb_dn.iloc[-1])

    amplitude = h - l + 1e-10
    pavio_sup = h - max(o, c)
    pavio_inf = min(o, c) - l

    if pavio_inf > amplitude * 0.55 and c > o and l < bd:
        score += 2
        razoes.append(f"[FAKEOUT BULLISH] Pavio inf {pavio_inf/amplitude*100:.0f}% abaixo BB — CALL")
    elif pavio_sup > amplitude * 0.55 and c < o and h > bu:
        score -= 2
        razoes.append(f"[FAKEOUT BEARISH] Pavio sup {pavio_sup/amplitude*100:.0f}% acima BB — PUT")
    elif pavio_inf > amplitude * 0.65 and c > o:
        score += 1
        razoes.append(f"[FAKEOUT] Pavio inf dominante — pressao compradora")
    elif pavio_sup > amplitude * 0.65 and c < o:
        score -= 1
        razoes.append(f"[FAKEOUT] Pavio sup dominante — pressao vendedora")
    else:
        razoes.append("[FAKEOUT] Sem falso rompimento")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 5 — PULLBACK
# ══════════════════════════════════════════════════════════════

def estrategia_pullback(close, high, low, ema9_s, ema21_s, adx_s) -> tuple[int, list]:
    score  = 0
    razoes = []
    p      = float(close.iloc[-1])
    ema9   = float(ema9_s.iloc[-1])
    ema21  = float(ema21_s.iloc[-1])
    adx_v  = float(adx_s.iloc[-1])
    atr    = float(calc_atr(high, low, close).iloc[-1])
    tol    = atr * 0.4

    if adx_v < 20:
        razoes.append(f"[PULLBACK] ADX fraco ({adx_v:.1f}) — sem pullback fiavel")
        return 0, razoes

    if ema9 > ema21:
        if abs(p - ema9) <= tol:
            score += 2
            razoes.append(f"[PULLBACK BULLISH] Toque EMA9 ({ema9:.5f}) em alta — CALL")
        elif abs(p - ema21) <= tol:
            score += 2
            razoes.append(f"[PULLBACK BULLISH] Toque EMA21 ({ema21:.5f}) em alta — CALL")
        elif p > ema9:
            score += 1
            razoes.append(f"[PULLBACK] Alta activa — aguarda pullback")
        else:
            razoes.append(f"[PULLBACK] Abaixo EMAs em alta — cuidado")
    else:
        if abs(p - ema9) <= tol:
            score -= 2
            razoes.append(f"[PULLBACK BEARISH] Toque EMA9 ({ema9:.5f}) em baixa — PUT")
        elif abs(p - ema21) <= tol:
            score -= 2
            razoes.append(f"[PULLBACK BEARISH] Toque EMA21 ({ema21:.5f}) em baixa — PUT")
        elif p < ema9:
            score -= 1
            razoes.append(f"[PULLBACK] Baixa activa — aguarda pullback")
        else:
            razoes.append(f"[PULLBACK] Acima EMAs em baixa — cuidado")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  SUPERTREND — Contribuicao ao score
# ══════════════════════════════════════════════════════════════

def estrategia_supertrend(close, high, low) -> tuple[int, list]:
    score  = 0
    razoes = []

    try:
        st_s, dir_s = calc_supertrend(high, low, close, period=10, multiplier=3.0)
        st_dir      = int(dir_s.iloc[-1])
        st_val      = float(st_s.iloc[-1])
        p           = float(close.iloc[-1])

        # Detectar cruzamento recente (mudanca de direcao nas ultimas 3 velas)
        recent_dirs = dir_s.iloc[-3:].values
        crossover   = len(set(recent_dirs)) > 1  # houve mudanca

        if st_dir == 1:
            if crossover:
                score += 3
                razoes.append(f"[SUPERTREND] CRUZAMENTO BULLISH recente — sinal forte CALL (ST={st_val:.5f})")
            else:
                score += 1
                razoes.append(f"[SUPERTREND] Tendencia BULLISH activa (ST={st_val:.5f})")
        else:
            if crossover:
                score -= 3
                razoes.append(f"[SUPERTREND] CRUZAMENTO BEARISH recente — sinal forte PUT (ST={st_val:.5f})")
            else:
                score -= 1
                razoes.append(f"[SUPERTREND] Tendencia BEARISH activa (ST={st_val:.5f})")

    except Exception as e:
        razoes.append(f"[SUPERTREND] Erro no calculo: {e}")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  TIMEFRAME IDEAL
# ══════════════════════════════════════════════════════════════

def detectar_timeframe_ideal(close, high, low, adx_s) -> tuple[str, str]:
    atr_v    = float(calc_atr(high, low, close).iloc[-1])
    adx_v    = float(adx_s.iloc[-1])
    p        = float(close.iloc[-1])
    atr_pct  = atr_v / p * 100

    if adx_v >= 30 and atr_pct >= 0.08:
        return "M15", f"ADX {adx_v:.1f} forte + vol alta ({atr_pct:.3f}%) — M15 recomendado"
    elif adx_v >= 25 and atr_pct >= 0.05:
        return "M5",  f"ADX {adx_v:.1f} moderado + vol media ({atr_pct:.3f}%) — M5 ideal"
    elif adx_v >= 20:
        return "M1",  f"ADX {adx_v:.1f} + baixa vol ({atr_pct:.3f}%) — M1 aceitavel"
    else:
        return "AGUARDA", f"ADX {adx_v:.1f} fraco + mercado lateral — NAO OPERAR"


# ══════════════════════════════════════════════════════════════
#  HORAS DE ENTRADA / EXPIRACAO
# ══════════════════════════════════════════════════════════════

def hora_proxima_vela(intervalo_segundos: int = 60) -> datetime:
    agora = datetime.now(TZ_CORRETORA)
    if intervalo_segundos < 60:
        ts_prox = (int(agora.timestamp()) // intervalo_segundos + 1) * intervalo_segundos
        return datetime.fromtimestamp(ts_prox, tz=TZ_CORRETORA)
    else:
        intervalo_minutos = intervalo_segundos // 60
        minuto = agora.minute
        prox   = ((minuto // intervalo_minutos) + 1) * intervalo_minutos
        base   = agora.replace(second=0, microsecond=0)
        return base + timedelta(minutes=(prox - minuto))

def hora_expiracao_str(entrada: datetime, segundos: int) -> str:
    resultado = entrada + timedelta(seconds=segundos)
    return resultado.strftime("%H:%M:%S" if segundos < 60 else "%H:%M")


# ══════════════════════════════════════════════════════════════
#  GERAR SINAL COMPLETO
# ══════════════════════════════════════════════════════════════

def gerar_sinal(ativo: str, expiracao: str = "1m") -> dict:
    """
    Gera sinal completo com 10 indicadores + 6 estrategias avancadas.
    Score maximo = 25 pontos.
    """
    candles = get_candles(ativo, 200)
    if len(candles) < 40:
        raise ValueError(f"Dados insuficientes para {ativo} ({len(candles)} velas)")

    df = pd.DataFrame(candles)
    df.columns = [c.lower() for c in df.columns]

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    # ── Indicadores base ──────────────────────────────────────
    rsi_s                  = calc_rsi(close)
    ema9_s                 = calc_ema(close, 9)
    ema21_s                = calc_ema(close, 21)
    ema50_s                = calc_ema(close, 50)
    ema200_s               = calc_ema(close, 200)
    macd_s, sig_s, hist_s  = calc_macd(close)
    bb_up, bb_mid, bb_dn   = calc_bollinger(close)
    stk_s, std_s           = calc_stoch(high, low, close)
    adx_s, pdi_s, mdi_s    = calc_adx(high, low, close)
    vwap_s                 = calc_vwap(df)
    wr_s                   = calc_williams_r(high, low, close)
    cci_s                  = calc_cci(high, low, close)

    # Valores actuais
    p       = close.iloc[-1]
    rsi_v   = rsi_s.iloc[-1]
    ema9_v  = ema9_s.iloc[-1]
    ema21_v = ema21_s.iloc[-1]
    ema50_v = ema50_s.iloc[-1]
    ema200_v= ema200_s.iloc[-1]
    macd_v  = macd_s.iloc[-1]
    sig_v   = sig_s.iloc[-1]
    hist_v  = hist_s.iloc[-1]
    bb_u    = bb_up.iloc[-1]
    bb_d    = bb_dn.iloc[-1]
    stk_v   = stk_s.iloc[-1]
    std_v   = std_s.iloc[-1]
    adx_v   = adx_s.iloc[-1]
    pdi_v   = pdi_s.iloc[-1]
    mdi_v   = mdi_s.iloc[-1]
    vwap_v  = vwap_s.iloc[-1]
    wr_v    = wr_s.iloc[-1]
    cci_v   = cci_s.iloc[-1]

    score   = 0
    reasons = []

    # ── 1. RSI ───────────────────────────────────────────────
    if rsi_v < 20:
        score += 3; reasons.append(f"RSI extremamente sobrevendido ({rsi_v:.1f}) — reversao bullish iminente")
    elif rsi_v < 30:
        score += 2; reasons.append(f"RSI sobrevendido ({rsi_v:.1f}) — pressao compradora")
    elif rsi_v < 40:
        score += 1; reasons.append(f"RSI em zona de compra ({rsi_v:.1f})")
    elif rsi_v > 80:
        score -= 3; reasons.append(f"RSI extremamente sobrecomprado ({rsi_v:.1f}) — reversao bearish iminente")
    elif rsi_v > 70:
        score -= 2; reasons.append(f"RSI sobrecomprado ({rsi_v:.1f}) — pressao vendedora")
    elif rsi_v > 60:
        score -= 1; reasons.append(f"RSI em zona de venda ({rsi_v:.1f})")
    else:
        reasons.append(f"RSI neutro ({rsi_v:.1f})")

    # ── 2. EMA (incluindo EMA200) ─────────────────────────────
    if ema9_v > ema21_v > ema50_v and p > ema9_v and ema50_v > ema200_v:
        score += 3; reasons.append("EMA alinhadas bullish perfeito (9>21>50>200) — tendencia forte")
    elif ema9_v > ema21_v > ema50_v and p > ema9_v:
        score += 2; reasons.append("EMA alinhadas bullish (9>21>50) + preco acima")
    elif ema9_v < ema21_v < ema50_v and p < ema9_v and ema50_v < ema200_v:
        score -= 3; reasons.append("EMA alinhadas bearish perfeito (9<21<50<200) — tendencia forte")
    elif ema9_v < ema21_v < ema50_v and p < ema9_v:
        score -= 2; reasons.append("EMA alinhadas bearish (9<21<50) + preco abaixo")
    elif ema9_v > ema21_v:
        score += 1; reasons.append("EMA9 acima EMA21 — momentum bullish")
    elif ema9_v < ema21_v:
        score -= 1; reasons.append("EMA9 abaixo EMA21 — momentum bearish")
    else:
        reasons.append("EMAs sem tendencia")

    # ── 3. MACD ───────────────────────────────────────────────
    if macd_v > sig_v and hist_v > 0 and hist_v > hist_s.iloc[-2]:
        score += 2; reasons.append(f"MACD bullish acelerando (hist={hist_v:.5f})")
    elif macd_v > sig_v and hist_v > 0:
        score += 1; reasons.append(f"MACD bullish (hist={hist_v:.5f})")
    elif macd_v < sig_v and hist_v < 0 and hist_v < hist_s.iloc[-2]:
        score -= 2; reasons.append(f"MACD bearish acelerando (hist={hist_v:.5f})")
    elif macd_v < sig_v and hist_v < 0:
        score -= 1; reasons.append(f"MACD bearish (hist={hist_v:.5f})")
    else:
        reasons.append("MACD neutro")

    # ── 4. Bollinger Bands ───────────────────────────────────
    pct_b = (p - bb_d) / (bb_u - bb_d + 1e-10)
    if pct_b < 0.02:
        score += 2; reasons.append("Preco na banda inferior extrema — suporte forte")
    elif pct_b < 0.08:
        score += 1; reasons.append("Preco na banda inferior — suporte")
    elif pct_b > 0.98:
        score -= 2; reasons.append("Preco na banda superior extrema — resistencia forte")
    elif pct_b > 0.92:
        score -= 1; reasons.append("Preco na banda superior — resistencia")
    else:
        reasons.append(f"Preco dentro das Bollinger ({pct_b*100:.0f}%)")

    # ── 5. Estocastico ───────────────────────────────────────
    if stk_v < 10:
        score += 2; reasons.append(f"Estocastico muito sobrevendido ({stk_v:.1f})")
    elif stk_v < 20:
        score += 1; reasons.append(f"Estocastico sobrevendido ({stk_v:.1f})")
    elif stk_v > 90:
        score -= 2; reasons.append(f"Estocastico muito sobrecomprado ({stk_v:.1f})")
    elif stk_v > 80:
        score -= 1; reasons.append(f"Estocastico sobrecomprado ({stk_v:.1f})")
    elif stk_v > 60 and stk_v > std_v:
        score += 1; reasons.append(f"Estocastico cruzamento bullish ({stk_v:.1f})")
    elif stk_v < 40 and stk_v < std_v:
        score -= 1; reasons.append(f"Estocastico cruzamento bearish ({stk_v:.1f})")
    else:
        reasons.append(f"Estocastico neutro ({stk_v:.1f})")

    # ── 6. ADX ───────────────────────────────────────────────
    if adx_v > 35:
        if pdi_v > mdi_v:
            score += 2; reasons.append(f"ADX muito forte ({adx_v:.1f}) — DI+ domina CALL")
        else:
            score -= 2; reasons.append(f"ADX muito forte ({adx_v:.1f}) — DI- domina PUT")
    elif adx_v > 25:
        if pdi_v > mdi_v:
            score += 1; reasons.append(f"ADX forte ({adx_v:.1f}) — tendencia bullish")
        else:
            score -= 1; reasons.append(f"ADX forte ({adx_v:.1f}) — tendencia bearish")
    else:
        reasons.append(f"ADX fraco ({adx_v:.1f}) — mercado sem tendencia")

    # ── 7. VWAP ──────────────────────────────────────────────
    if p > vwap_v * 1.0010:
        score += 1; reasons.append("Preco acima do VWAP — compradores dominam")
    elif p < vwap_v * 0.9990:
        score -= 1; reasons.append("Preco abaixo do VWAP — vendedores dominam")
    else:
        reasons.append("Preco proximo do VWAP — equilibrio")

    # ── 8. Williams %R ───────────────────────────────────────
    if wr_v < -85:
        score += 2; reasons.append(f"Williams %R extremamente sobrevendido ({wr_v:.1f})")
    elif wr_v < -70:
        score += 1; reasons.append(f"Williams %R sobrevendido ({wr_v:.1f})")
    elif wr_v > -15:
        score -= 2; reasons.append(f"Williams %R extremamente sobrecomprado ({wr_v:.1f})")
    elif wr_v > -30:
        score -= 1; reasons.append(f"Williams %R sobrecomprado ({wr_v:.1f})")
    else:
        reasons.append(f"Williams %R neutro ({wr_v:.1f})")

    # ── 9. CCI ───────────────────────────────────────────────
    if cci_v < -150:
        score += 2; reasons.append(f"CCI extremamente sobrevendido ({cci_v:.0f})")
    elif cci_v < -100:
        score += 1; reasons.append(f"CCI sobrevendido ({cci_v:.0f}) — reversao bullish")
    elif cci_v > 150:
        score -= 2; reasons.append(f"CCI extremamente sobrecomprado ({cci_v:.0f})")
    elif cci_v > 100:
        score -= 1; reasons.append(f"CCI sobrecomprado ({cci_v:.0f}) — reversao bearish")
    else:
        reasons.append(f"CCI neutro ({cci_v:.0f})")

    # ── ESTRATEGIAS AVANCADAS ─────────────────────────────────

    reasons.append("\n─── ESTRATEGIAS ─────────────────")

    s1, r1 = estrategia_reversao(close, high, low, rsi_s, stk_s, bb_up, bb_dn)
    score += s1; reasons.extend(r1)

    s2, r2 = estrategia_retracao(close, high, low)
    score += s2; reasons.extend(r2)

    s3, r3, tipo_tendencia = estrategia_lta_ltb(close, high, low)
    score += s3; reasons.extend(r3)

    s4, r4 = estrategia_falso_rompimento(open_, high, low, close, bb_up, bb_dn)
    score += s4; reasons.extend(r4)

    s5, r5 = estrategia_pullback(close, high, low, ema9_s, ema21_s, adx_s)
    score += s5; reasons.extend(r5)

    s6, r6 = estrategia_supertrend(close, high, low)
    score += s6; reasons.extend(r6)

    tf_ideal, tf_razao = detectar_timeframe_ideal(close, high, low, adx_s)

    # ── Score maximo: 9 indicadores (max ~20) + 6 estrategias (max ~15) = 25 ──
    MAX_SCORE = 25

    # ── Classificacao final ───────────────────────────────────
    if score >= 15:
        direction = "CALL"; emoji = "🟢"; confianca = "MAXIMA ⭐⭐⭐⭐⭐+"
    elif score >= 10:
        direction = "CALL"; emoji = "🟢"; confianca = "MUITO ALTA ⭐⭐⭐⭐⭐"
    elif score >= 7:
        direction = "CALL"; emoji = "🟢"; confianca = "ALTA ⭐⭐⭐⭐"
    elif score >= 4:
        direction = "CALL"; emoji = "🟢"; confianca = "MEDIA ⭐⭐⭐"
    elif score <= -15:
        direction = "PUT";  emoji = "🔴"; confianca = "MAXIMA ⭐⭐⭐⭐⭐+"
    elif score <= -10:
        direction = "PUT";  emoji = "🔴"; confianca = "MUITO ALTA ⭐⭐⭐⭐⭐"
    elif score <= -7:
        direction = "PUT";  emoji = "🔴"; confianca = "ALTA ⭐⭐⭐⭐"
    elif score <= -4:
        direction = "PUT";  emoji = "🔴"; confianca = "MEDIA ⭐⭐⭐"
    else:
        direction = "NEUTRO"; emoji = "⚪"; confianca = "BAIXA ⭐⭐"

    return {
        "direction":        direction,
        "emoji":            emoji,
        "confianca":        confianca,
        "score":            score,
        "max_score":        MAX_SCORE,
        "rsi":              round(rsi_v,    2),
        "ema9":             round(ema9_v,   5),
        "ema21":            round(ema21_v,  5),
        "ema50":            round(ema50_v,  5),
        "ema200":           round(ema200_v, 5),
        "macd":             round(macd_v,   6),
        "stoch":            round(stk_v,    2),
        "adx":              round(adx_v,    2),
        "vwap":             round(vwap_v,   5),
        "wr":               round(wr_v,     2),
        "cci":              round(cci_v,    2),
        "price":            round(p,        5),
        "reasons":          reasons,
        "hora_corretora":   hora_corretora(),
        "expiracao":        expiracao,
        "candles":          len(candles),
        "tipo_tendencia":   tipo_tendencia,
        "timeframe_ideal":  tf_ideal,
        "timeframe_razao":  tf_razao,
        "score_reversao":   s1,
        "score_fibonacci":  s2,
        "score_lta_ltb":    s3,
        "score_fakeout":    s4,
        "score_pullback":   s5,
        "score_supertrend": s6,
    }


# ══════════════════════════════════════════════════════════════
#  FORMATAR MENSAGEM TELEGRAM — v5.0
# ══════════════════════════════════════════════════════════════

def formatar_sinal(nome: str, result: dict, tipo: str = "mercado", categoria: str = "forex") -> str:
    exp_key  = result.get("expiracao", "1m")
    exp_cfg  = EXPIRACOES.get(exp_key, EXPIRACOES["1m"])
    exp_lbl  = exp_cfg["label"]
    exp_seg  = exp_cfg.get("segundos", exp_cfg.get("minutos", 1) * 60)
    turbo    = exp_cfg.get("turbo", False)

    intervalo_seg = exp_seg if turbo else max(exp_seg, 60)
    entrada       = hora_proxima_vela(intervalo_seg)
    fmt_hora      = "%H:%M:%S" if turbo else "%H:%M"
    h_entrada     = entrada.strftime(fmt_hora)
    h_expira      = hora_expiracao_str(entrada, exp_seg)

    max_s  = result["max_score"]
    pct    = abs(result["score"]) / max_s * 100
    razoes = "\n".join(f"  • {r}" for r in result["reasons"])

    if result["direction"] == "CALL":
        header = "▲  CALL — COMPRAR"
        barra  = "🟩🟩🟩🟩🟩🟩🟩"
        acao   = "COMPRA"
    elif result["direction"] == "PUT":
        header = "▼  PUT — VENDER"
        barra  = "🟥🟥🟥🟥🟥🟥🟥"
        acao   = "VENDA"
    else:
        header = "⏸  AGUARDAR SINAL"
        barra  = "⬜⬜⬜⬜⬜⬜⬜"
        acao   = "Aguarda"

    cat_emoji = CATEGORIA_EMOJI.get(categoria, "📊")
    cat_label = CATEGORIA_LABEL.get(categoria, "MERCADO")
    tipo_label = "🌙 OTC" if tipo == "otc" else f"{cat_emoji} {cat_label}"

    tf        = result.get("timeframe_ideal", "M1")
    tf_icons  = {"M1": "⚡", "M5": "🕐", "M15": "🕒", "AGUARDA": "⏸"}
    tf_icon   = tf_icons.get(tf, "⚡")

    tend      = result.get("tipo_tendencia", "NEUTRO")
    tend_icon = {"LTA": "📈", "LTB": "📉", "NEUTRO": "➡"}.get(tend, "➡")

    # Barra de progresso do score
    barras_score = min(int(pct / 14.3), 7)
    barra_score  = "█" * barras_score + "░" * (7 - barras_score)

    s_st = result.get("score_supertrend", 0)

    msg = (
        f"╔═══════════════════════════════╗\n"
        f"║   POCKET SIGNAL PRO  v5.0     ║\n"
        f"╚═══════════════════════════════╝\n"
        f"{barra}\n"
        f"  {header}\n"
        f"{barra}\n\n"
        f"{tipo_label}  |  {tend_icon} {tend}\n"
        f"Ativo:       {nome}\n"
        f"Hora:        {result['hora_corretora']}\n\n"
        f"ENTRADA:     {h_entrada} ({acao})\n"
        f"EXPIRACAO:   {exp_lbl} (ate {h_expira})\n\n"
        f"Confianca:   {result['confianca']}\n"
        f"Score:       {result['score']}/{max_s}  [{barra_score}] {pct:.0f}%\n\n"
        f"{tf_icon} TIMEFRAME: {tf}\n"
        f"  {result.get('timeframe_razao','')}\n\n"
        f"─── ESTRATEGIAS ────────────────\n"
        f"  Reversao:    {'+' if result['score_reversao']  >= 0 else ''}{result['score_reversao']}\n"
        f"  Fibonacci:   {'+' if result['score_fibonacci'] >= 0 else ''}{result['score_fibonacci']}\n"
        f"  LTA/LTB:     {'+' if result['score_lta_ltb']  >= 0 else ''}{result['score_lta_ltb']}\n"
        f"  Fakeout:     {'+' if result['score_fakeout']   >= 0 else ''}{result['score_fakeout']}\n"
        f"  Pullback:    {'+' if result['score_pullback']  >= 0 else ''}{result['score_pullback']}\n"
        f"  SuperTrend:  {'+' if s_st                      >= 0 else ''}{s_st} ★\n\n"
        f"─── INDICADORES ────────────────\n"
        f"RSI:         {result['rsi']}\n"
        f"EMA 9/21/50: {result['ema9']} / {result['ema21']} / {result['ema50']}\n"
        f"EMA 200:     {result['ema200']}\n"
        f"MACD:        {result['macd']}\n"
        f"Estocastico: {result['stoch']}\n"
        f"ADX:         {result['adx']}\n"
        f"VWAP:        {result['vwap']}\n"
        f"Williams R:  {result['wr']}\n"
        f"CCI:         {result['cci']}\n"
        f"Preco:       {result['price']}\n\n"
        f"─── ANALISE DETALHADA ──────────\n"
        f"{razoes}\n\n"
        f"═══════════════════════════════\n"
        f"⚠ SEMPRE testa na DEMO primeiro!\n"
        f"⚠ Risco max 2% do saldo por trade\n"
        f"⚠ Nunca investe o que nao podes perder"
    )
    return msg.strip()


