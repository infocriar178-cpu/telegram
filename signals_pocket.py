"""
╔══════════════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO v4.0 — signals_pocket.py                  ║
║         Analise tecnica AVANCADA com dados reais da Pocket Option    ║
║                                                                      ║
║  ESTRATEGIAS NOVAS:                                                  ║
║  • Reversao (sobrecompra/sobrevenda confirmada)                      ║
║  • Retracao (Fibonacci 38.2% / 50% / 61.8%)                         ║
║  • LTA / LTB (Linha de Tendencia Ascendente / Descendente)          ║
║  • Falso Rompimento (fakeout com rejeicao de pavio)                  ║
║  • Pullback (recuo para suporte/resistencia antes de retomar)        ║
║  • Deteccao automatica de timeframe ideal (M1 / M5 / M15)           ║
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

# ══════════════════════════════════════════════════════════════
#  INDICADORES BASICOS
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
    stk = 100 * (close - low_min) / (high_max - low_min + 1e-10)
    std = stk.rolling(d).mean()
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
    ll  = low.rolling(period).min()
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


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 1 — REVERSAO
#  Detecta reversao de tendencia com multipla confirmacao
# ══════════════════════════════════════════════════════════════

def estrategia_reversao(close, high, low, rsi_s, stk_s, bb_up, bb_dn) -> tuple[int, list]:
    """
    Reversao ocorre quando o preco atinge extremo + confirmacao de pelo menos 2 indicadores.
    Retorna (score, razoes)
    """
    score   = 0
    razoes  = []
    p       = close.iloc[-1]
    p_prev  = close.iloc[-2]
    rsi_v   = rsi_s.iloc[-1]
    stk_v   = stk_s.iloc[-1]
    bb_u    = bb_up.iloc[-1]
    bb_d    = bb_dn.iloc[-1]

    # Reversao bullish
    confirmacoes_bull = 0
    if rsi_v < 30:     confirmacoes_bull += 1
    if stk_v < 20:     confirmacoes_bull += 1
    if p <= bb_d:      confirmacoes_bull += 1
    if p > p_prev:     confirmacoes_bull += 1  # vela actual verde

    # Reversao bearish
    confirmacoes_bear = 0
    if rsi_v > 70:     confirmacoes_bear += 1
    if stk_v > 80:     confirmacoes_bear += 1
    if p >= bb_u:      confirmacoes_bear += 1
    if p < p_prev:     confirmacoes_bear += 1  # vela actual vermelha

    if confirmacoes_bull >= 3:
        score += 3
        razoes.append(f"[REVERSAO BULLISH] {confirmacoes_bull}/4 confirmacoes — RSI:{rsi_v:.1f}, Stoch:{stk_v:.1f}")
    elif confirmacoes_bull == 2:
        score += 1
        razoes.append(f"[REVERSAO BULLISH parcial] {confirmacoes_bull}/4 sinais detectados")
    elif confirmacoes_bear >= 3:
        score -= 3
        razoes.append(f"[REVERSAO BEARISH] {confirmacoes_bear}/4 confirmacoes — RSI:{rsi_v:.1f}, Stoch:{stk_v:.1f}")
    elif confirmacoes_bear == 2:
        score -= 1
        razoes.append(f"[REVERSAO BEARISH parcial] {confirmacoes_bear}/4 sinais detectados")
    else:
        razoes.append("[REVERSAO] Sem sinal de reversao claro")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 2 — RETRACAO FIBONACCI
#  38.2%, 50%, 61.8% — zonas de entrada apos impulso
# ══════════════════════════════════════════════════════════════

def estrategia_retracao(close, high, low) -> tuple[int, list]:
    """
    Calcula niveis Fibonacci do swing anterior e verifica se o preco
    esta em zona de retracao valida (retomada de tendencia esperada).
    """
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
        razoes.append("[FIBONACCI] Amplitude insuficiente para calcular niveis")
        return 0, razoes

    fib382 = swing_high - 0.382 * diff
    fib500 = swing_high - 0.500 * diff
    fib618 = swing_high - 0.618 * diff

    tolerance = diff * 0.04  # 4% de tolerancia

    # Tendencia do swing (onde terminou o swing)
    idx_high = int(h.values.argmax())
    idx_low  = int(l.values.argmin())
    tendencia_up = idx_low < idx_high  # subiu depois de cair

    zona = None
    for nivel, nome in [(fib382, "38.2%"), (fib500, "50%"), (fib618, "61.8%")]:
        if abs(p - nivel) <= tolerance:
            zona = nome
            break

    if zona:
        if tendencia_up:
            score += 2
            razoes.append(f"[FIBONACCI] Preco em retracao {zona} em tendencia UP — entrada CALL")
        else:
            score -= 2
            razoes.append(f"[FIBONACCI] Preco em retracao {zona} em tendencia DOWN — entrada PUT")
    else:
        razoes.append(f"[FIBONACCI] Preco fora de zona (niveis: {fib382:.5f} / {fib500:.5f} / {fib618:.5f})")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 3 — LTA / LTB
#  Linha de Tendencia Ascendente / Descendente
#  Detecta toque na linha de tendencia como entrada de continuidade
# ══════════════════════════════════════════════════════════════

def estrategia_lta_ltb(close, high, low) -> tuple[int, list, str]:
    """
    Usa regressao linear sobre minimos (LTA) e maximos (LTB) para
    identificar a tendencia vigente e se o preco esta a tocar a linha.
    Retorna (score, razoes, tipo_tendencia)
    """
    score  = 0
    razoes = []
    n      = min(40, len(close))
    x      = np.arange(n)
    c      = close.iloc[-n:].values
    h      = high.iloc[-n:].values
    l      = low.iloc[-n:].values
    p      = float(close.iloc[-1])

    # Regressao linear simples
    def reg(y):
        m = np.polyfit(x, y, 1)
        return m[0], np.polyval(m, x)  # (slope, fitted)

    slope_close, fitted_close = reg(c)
    _, fitted_high             = reg(h)
    _, fitted_low              = reg(l)

    lta_val = fitted_low[-1]   # valor actual da LTA
    ltb_val = fitted_high[-1]  # valor actual da LTB
    tol     = float(calc_atr(
        pd.Series(h), pd.Series(l), pd.Series(c)
    ).iloc[-1]) * 0.5

    tipo = "NEUTRO"

    if slope_close > 0:
        tipo = "LTA"
        if abs(p - lta_val) <= tol:
            score += 2
            razoes.append(f"[LTA] Preco tocou a Linha de Tendencia ASCENDENTE ({lta_val:.5f}) — CALL esperado")
        elif p > lta_val:
            score += 1
            razoes.append(f"[LTA] Tendencia ascendente activa, preco acima da LTA")
        else:
            score -= 1
            razoes.append(f"[LTA] Preco ABAIXO da LTA — possivel quebra de tendencia")
    elif slope_close < 0:
        tipo = "LTB"
        if abs(p - ltb_val) <= tol:
            score -= 2
            razoes.append(f"[LTB] Preco tocou a Linha de Tendencia DESCENDENTE ({ltb_val:.5f}) — PUT esperado")
        elif p < ltb_val:
            score -= 1
            razoes.append(f"[LTB] Tendencia descendente activa, preco abaixo da LTB")
        else:
            score += 1
            razoes.append(f"[LTB] Preco ACIMA da LTB — possivel quebra de tendencia descendente")
    else:
        razoes.append("[LTA/LTB] Mercado lateral — sem tendencia definida")

    return score, razoes, tipo


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 4 — FALSO ROMPIMENTO (FAKEOUT)
#  Preco rompe nivel mas rejeita rapidamente (pavio longo)
# ══════════════════════════════════════════════════════════════

def estrategia_falso_rompimento(open_, high, low, close, bb_up, bb_dn) -> tuple[int, list]:
    """
    Detecta quando o preco rompe uma resistencia/suporte mas fecha de volta.
    Pavio longo = rejeicao = falso rompimento.
    """
    score  = 0
    razoes = []

    o  = float(open_.iloc[-1])
    h  = float(high.iloc[-1])
    l  = float(low.iloc[-1])
    c  = float(close.iloc[-1])
    bu = float(bb_up.iloc[-1])
    bd = float(bb_dn.iloc[-1])

    corpo      = abs(c - o)
    amplitude  = h - l + 1e-10
    pavio_sup  = h - max(o, c)  # pavio superior
    pavio_inf  = min(o, c) - l  # pavio inferior

    # Falso rompimento bullish: pavio inferior longo + fechou acima
    # (tentou cair mas rejeitou — entrada CALL)
    if pavio_inf > amplitude * 0.55 and c > o and l < bd:
        score += 2
        razoes.append(
            f"[FAKEOUT BULLISH] Pavio inferior longo ({pavio_inf/amplitude*100:.0f}%) "
            f"abaixo da BB inferior — rejeicao de queda — CALL"
        )
    # Falso rompimento bearish: pavio superior longo + fechou abaixo
    elif pavio_sup > amplitude * 0.55 and c < o and h > bu:
        score -= 2
        razoes.append(
            f"[FAKEOUT BEARISH] Pavio superior longo ({pavio_sup/amplitude*100:.0f}%) "
            f"acima da BB superior — rejeicao de subida — PUT"
        )
    # Fakeout interno (sem BB)
    elif pavio_inf > amplitude * 0.65 and c > o:
        score += 1
        razoes.append(f"[FAKEOUT] Pavio inferior dominante ({pavio_inf/amplitude*100:.0f}%) — pressao compradora")
    elif pavio_sup > amplitude * 0.65 and c < o:
        score -= 1
        razoes.append(f"[FAKEOUT] Pavio superior dominante ({pavio_sup/amplitude*100:.0f}%) — pressao vendedora")
    else:
        razoes.append("[FAKEOUT] Sem falso rompimento identificado")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  ESTRATEGIA 5 — PULLBACK
#  Recuo para suporte/resistencia antes de continuar tendencia
# ══════════════════════════════════════════════════════════════

def estrategia_pullback(close, high, low, ema9_s, ema21_s, adx_s) -> tuple[int, list]:
    """
    Em tendencia forte (ADX>25), detecta pullback para EMA como entrada.
    """
    score  = 0
    razoes = []

    p      = float(close.iloc[-1])
    ema9   = float(ema9_s.iloc[-1])
    ema21  = float(ema21_s.iloc[-1])
    adx_v  = float(adx_s.iloc[-1])
    atr    = float(calc_atr(high, low, close).iloc[-1])
    tol    = atr * 0.4

    if adx_v < 20:
        razoes.append(f"[PULLBACK] ADX fraco ({adx_v:.1f}) — pullback nao confiavel")
        return 0, razoes

    # Tendencia de alta: pullback para EMA9 ou EMA21
    if ema9 > ema21:  # alta
        if abs(p - ema9) <= tol:
            score += 2
            razoes.append(f"[PULLBACK BULLISH] Preco recuou para EMA9 ({ema9:.5f}) em tendencia alta — CALL")
        elif abs(p - ema21) <= tol:
            score += 2
            razoes.append(f"[PULLBACK BULLISH] Preco recuou para EMA21 ({ema21:.5f}) em tendencia alta — CALL")
        elif p > ema9:
            score += 1
            razoes.append(f"[PULLBACK] Tendencia alta activa, sem pullback imediato")
        else:
            razoes.append(f"[PULLBACK] Preco abaixo das EMAs em tendencia alta — cuidado")
    else:  # baixa
        if abs(p - ema9) <= tol:
            score -= 2
            razoes.append(f"[PULLBACK BEARISH] Preco recuou para EMA9 ({ema9:.5f}) em tendencia baixa — PUT")
        elif abs(p - ema21) <= tol:
            score -= 2
            razoes.append(f"[PULLBACK BEARISH] Preco recuou para EMA21 ({ema21:.5f}) em tendencia baixa — PUT")
        elif p < ema9:
            score -= 1
            razoes.append(f"[PULLBACK] Tendencia baixa activa, sem pullback imediato")
        else:
            razoes.append(f"[PULLBACK] Preco acima das EMAs em tendencia baixa — cuidado")

    return score, razoes


# ══════════════════════════════════════════════════════════════
#  TIMEFRAME IDEAL — M1 / M5 / M15
#  Baseado em volatilidade (ATR) e forca da tendencia (ADX)
# ══════════════════════════════════════════════════════════════

def detectar_timeframe_ideal(close, high, low, adx_s) -> tuple[str, str]:
    """
    Recomenda o melhor timeframe para operar com base nas condicoes do mercado.
    Retorna (timeframe_str, justificativa)
    """
    atr_v  = float(calc_atr(high, low, close).iloc[-1])
    adx_v  = float(adx_s.iloc[-1])
    p      = float(close.iloc[-1])
    atr_pct = atr_v / p * 100  # volatilidade relativa

    # Alta volatilidade + tendencia forte => M5 ou M15
    if adx_v >= 30 and atr_pct >= 0.08:
        return "M15", f"ADX {adx_v:.1f} forte + alta volatilidade ({atr_pct:.3f}%) — opere em M15 para mais seguranca"
    elif adx_v >= 25 and atr_pct >= 0.05:
        return "M5",  f"ADX {adx_v:.1f} moderado + volatilidade media ({atr_pct:.3f}%) — M5 e o ideal"
    elif adx_v >= 20:
        return "M1",  f"ADX {adx_v:.1f} + baixa volatilidade ({atr_pct:.3f}%) — M1 aceitavel, cuidado com ruido"
    else:
        return "AGUARDA", f"ADX {adx_v:.1f} fraco + mercado lateral ({atr_pct:.3f}%) — NAO OPERAR agora"


# ══════════════════════════════════════════════════════════════
#  HORA DE ENTRADA
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

def hora_entrada_str(intervalo_segundos: int = 60) -> str:
    p = hora_proxima_vela(intervalo_segundos)
    return p.strftime("%H:%M:%S" if intervalo_segundos < 60 else "%H:%M")

def hora_expiracao_str(entrada: datetime, segundos: int) -> str:
    resultado = entrada + timedelta(seconds=segundos)
    return resultado.strftime("%H:%M:%S" if segundos < 60 else "%H:%M")


# ══════════════════════════════════════════════════════════════
#  GERAR SINAL COMPLETO
# ══════════════════════════════════════════════════════════════

def gerar_sinal(ativo: str, expiracao: str = "1m") -> dict:
    """
    Gera sinal completo com todos os indicadores + 5 estrategias avancadas.
    """
    candles = get_candles(ativo, 150)
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
    rsi_s               = calc_rsi(close)
    ema9_s              = calc_ema(close, 9)
    ema21_s             = calc_ema(close, 21)
    ema50_s             = calc_ema(close, 50)
    macd_s, sig_s, hist_s = calc_macd(close)
    bb_up, bb_mid, bb_dn  = calc_bollinger(close)
    stk_s, std_s        = calc_stoch(high, low, close)
    adx_s, pdi_s, mdi_s = calc_adx(high, low, close)
    vwap_s              = calc_vwap(df)
    wr_s                = calc_williams_r(high, low, close)
    cci_s               = calc_cci(high, low, close)

    # Valores actuais
    p       = close.iloc[-1]
    rsi_v   = rsi_s.iloc[-1]
    ema9_v  = ema9_s.iloc[-1]
    ema21_v = ema21_s.iloc[-1]
    ema50_v = ema50_s.iloc[-1]
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

    # ── Score base (indicadores classicos) ───────────────────

    # 1. RSI
    if rsi_v < 25:
        score += 2; reasons.append(f"RSI muito sobrevendido ({rsi_v:.1f}) — reversao bullish forte")
    elif rsi_v < 35:
        score += 1; reasons.append(f"RSI sobrevendido ({rsi_v:.1f}) — pressao de compra")
    elif rsi_v > 75:
        score -= 2; reasons.append(f"RSI muito sobrecomprado ({rsi_v:.1f}) — reversao bearish forte")
    elif rsi_v > 65:
        score -= 1; reasons.append(f"RSI sobrecomprado ({rsi_v:.1f}) — pressao de venda")
    else:
        reasons.append(f"RSI neutro ({rsi_v:.1f})")

    # 2. EMA
    if ema9_v > ema21_v > ema50_v and p > ema9_v:
        score += 2; reasons.append("EMA alinhadas bullish (9>21>50) + preco acima")
    elif ema9_v < ema21_v < ema50_v and p < ema9_v:
        score -= 2; reasons.append("EMA alinhadas bearish (9<21<50) + preco abaixo")
    elif ema9_v > ema21_v:
        score += 1; reasons.append("EMA9 acima EMA21 — tendencia bullish")
    elif ema9_v < ema21_v:
        score -= 1; reasons.append("EMA9 abaixo EMA21 — tendencia bearish")
    else:
        reasons.append("EMAs sem tendencia clara")

    # 3. MACD
    if macd_v > sig_v and hist_v > 0:
        score += 1; reasons.append(f"MACD bullish (hist={hist_v:.5f})")
    elif macd_v < sig_v and hist_v < 0:
        score -= 1; reasons.append(f"MACD bearish (hist={hist_v:.5f})")
    else:
        reasons.append("MACD neutro")

    # 4. Bollinger Bands
    pct_b = (p - bb_d) / (bb_u - bb_d + 1e-10)
    if pct_b < 0.05:
        score += 1; reasons.append("Preco na banda inferior — suporte bullish")
    elif pct_b > 0.95:
        score -= 1; reasons.append("Preco na banda superior — resistencia bearish")
    else:
        reasons.append(f"Preco dentro das Bollinger Bands ({pct_b*100:.0f}%)")

    # 5. Estocastico
    if stk_v < 15:
        score += 1; reasons.append(f"Estocastico muito sobrevendido ({stk_v:.1f})")
    elif stk_v > 85:
        score -= 1; reasons.append(f"Estocastico muito sobrecomprado ({stk_v:.1f})")
    elif stk_v > 60 and stk_v > std_v:
        score += 1; reasons.append(f"Estocastico cruzamento bullish ({stk_v:.1f})")
    elif stk_v < 40 and stk_v < std_v:
        score -= 1; reasons.append(f"Estocastico cruzamento bearish ({stk_v:.1f})")
    else:
        reasons.append(f"Estocastico neutro ({stk_v:.1f})")

    # 6. ADX
    if adx_v > 25:
        if pdi_v > mdi_v:
            score += 1; reasons.append(f"ADX forte ({adx_v:.1f}) — DI+ domina bullish")
        else:
            score -= 1; reasons.append(f"ADX forte ({adx_v:.1f}) — DI- domina bearish")
    else:
        reasons.append(f"ADX fraco ({adx_v:.1f}) — sem tendencia")

    # 7. VWAP
    if p > vwap_v * 1.0008:
        score += 1; reasons.append("Preco acima do VWAP — compradores dominam")
    elif p < vwap_v * 0.9992:
        score -= 1; reasons.append("Preco abaixo do VWAP — vendedores dominam")
    else:
        reasons.append("Preco proximo do VWAP — equilibrio")

    # 8. Williams %R
    if wr_v < -80:
        score += 1; reasons.append(f"Williams %R sobrevendido ({wr_v:.1f})")
    elif wr_v > -20:
        score -= 1; reasons.append(f"Williams %R sobrecomprado ({wr_v:.1f})")
    else:
        reasons.append(f"Williams %R neutro ({wr_v:.1f})")

    # 9. CCI
    if cci_v < -100:
        score += 1; reasons.append(f"CCI sobrevendido ({cci_v:.0f}) — reversao bullish")
    elif cci_v > 100:
        score -= 1; reasons.append(f"CCI sobrecomprado ({cci_v:.0f}) — reversao bearish")
    else:
        reasons.append(f"CCI neutro ({cci_v:.0f})")

    # ── ESTRATEGIAS AVANCADAS ─────────────────────────────────

    reasons.append("\n--- ESTRATEGIAS AVANCADAS ---")

    # Estrategia 1: Reversao
    s1, r1 = estrategia_reversao(close, high, low, rsi_s, stk_s, bb_up, bb_dn)
    score += s1; reasons.extend(r1)

    # Estrategia 2: Retracao Fibonacci
    s2, r2 = estrategia_retracao(close, high, low)
    score += s2; reasons.extend(r2)

    # Estrategia 3: LTA / LTB
    s3, r3, tipo_tendencia = estrategia_lta_ltb(close, high, low)
    score += s3; reasons.extend(r3)

    # Estrategia 4: Falso Rompimento
    s4, r4 = estrategia_falso_rompimento(open_, high, low, close, bb_up, bb_dn)
    score += s4; reasons.extend(r4)

    # Estrategia 5: Pullback
    s5, r5 = estrategia_pullback(close, high, low, ema9_s, ema21_s, adx_s)
    score += s5; reasons.extend(r5)

    # ── Timeframe ideal ───────────────────────────────────────
    tf_ideal, tf_razao = detectar_timeframe_ideal(close, high, low, adx_s)

    # ── Score maximo agora = 9 (base) + 3+2+2+2+2 (estrategias) = 20 ──
    MAX_SCORE = 20

    # ── Classificacao final ───────────────────────────────────
    if score >= 12:
        direction = "CALL"; emoji = "🟢"; confianca = "MAXIMA ⭐⭐⭐⭐⭐+"
    elif score >= 8:
        direction = "CALL"; emoji = "🟢"; confianca = "MUITO ALTA ⭐⭐⭐⭐⭐"
    elif score >= 5:
        direction = "CALL"; emoji = "🟢"; confianca = "ALTA ⭐⭐⭐⭐"
    elif score >= 3:
        direction = "CALL"; emoji = "🟢"; confianca = "MEDIA ⭐⭐⭐"
    elif score <= -12:
        direction = "PUT";  emoji = "🔴"; confianca = "MAXIMA ⭐⭐⭐⭐⭐+"
    elif score <= -8:
        direction = "PUT";  emoji = "🔴"; confianca = "MUITO ALTA ⭐⭐⭐⭐⭐"
    elif score <= -5:
        direction = "PUT";  emoji = "🔴"; confianca = "ALTA ⭐⭐⭐⭐"
    elif score <= -3:
        direction = "PUT";  emoji = "🔴"; confianca = "MEDIA ⭐⭐⭐"
    else:
        direction = "NEUTRO"; emoji = "⚪"; confianca = "BAIXA ⭐⭐"

    return {
        "direction":       direction,
        "emoji":           emoji,
        "confianca":       confianca,
        "score":           score,
        "max_score":       MAX_SCORE,
        "rsi":             round(rsi_v,    2),
        "ema9":            round(ema9_v,   5),
        "ema21":           round(ema21_v,  5),
        "ema50":           round(ema50_v,  5),
        "macd":            round(macd_v,   6),
        "stoch":           round(stk_v,    2),
        "adx":             round(adx_v,    2),
        "vwap":            round(vwap_v,   5),
        "wr":              round(wr_v,     2),
        "cci":             round(cci_v,    2),
        "price":           round(p,        5),
        "reasons":         reasons,
        "hora_corretora":  hora_corretora(),
        "expiracao":       expiracao,
        "candles":         len(candles),
        "tipo_tendencia":  tipo_tendencia,  # LTA / LTB / NEUTRO
        "timeframe_ideal": tf_ideal,        # M1 / M5 / M15 / AGUARDA
        "timeframe_razao": tf_razao,
        # scores por estrategia
        "score_reversao":  s1,
        "score_fibonacci": s2,
        "score_lta_ltb":   s3,
        "score_fakeout":   s4,
        "score_pullback":  s5,
    }


# ══════════════════════════════════════════════════════════════
#  FORMATAR MENSAGEM TELEGRAM
# ══════════════════════════════════════════════════════════════

def formatar_sinal(nome: str, result: dict, tipo: str = "mercado") -> str:
    exp_key = result.get("expiracao", "1m")
    exp_cfg = EXPIRACOES.get(exp_key, EXPIRACOES["1m"])
    exp_lbl = exp_cfg["label"]
    exp_seg = exp_cfg.get("segundos", exp_cfg.get("minutos", 1) * 60)
    turbo   = exp_cfg.get("turbo", False)

    intervalo_seg = exp_seg if turbo else max(exp_seg, 60)
    entrada       = hora_proxima_vela(intervalo_seg)
    fmt_hora      = "%H:%M:%S" if turbo else "%H:%M"
    h_entrada     = entrada.strftime(fmt_hora)
    h_expira      = hora_expiracao_str(entrada, exp_seg)

    max_s = result["max_score"]
    pct   = abs(result["score"]) / max_s * 100
    razoes = "\n".join(f"  • {r}" for r in result["reasons"])

    if result["direction"] == "CALL":
        header = "CALL — COMPRAR"
        barra  = "🟩🟩🟩🟩🟩"
        acao   = "COMPRA"
    elif result["direction"] == "PUT":
        header = "PUT — VENDER"
        barra  = "🟥🟥🟥🟥🟥"
        acao   = "VENDA"
    else:
        header = "AGUARDAR"
        barra  = "⬜⬜⬜⬜⬜"
        acao   = "Aguarda"

    tipo_label = "🌙 OTC" if tipo == "otc" else "📊 MERCADO"

    # Icone do timeframe
    tf = result.get("timeframe_ideal", "M1")
    tf_icons = {"M1": "⚡", "M5": "🕐", "M15": "🕒", "AGUARDA": "⏸"}
    tf_icon = tf_icons.get(tf, "⚡")

    # Icone da tendencia
    tend = result.get("tipo_tendencia", "NEUTRO")
    tend_icon = {"LTA": "📈", "LTB": "📉", "NEUTRO": "➡"}.get(tend, "➡")

    msg = (
        f"╔══════════════════════════╗\n"
        f"║  POCKET SIGNAL PRO v4.0  ║\n"
        f"╚══════════════════════════╝\n"
        f"{barra}\n"
        f"  {header}\n"
        f"{barra}\n\n"
        f"{tipo_label}  |  {tend_icon} {tend}\n"
        f"Ativo:      {nome}\n"
        f"Hora:       {result['hora_corretora']}\n\n"
        f"ENTRADA:    {h_entrada} ({acao})\n"
        f"EXPIRACAO:  {exp_lbl} (ate {h_expira})\n\n"
        f"Confianca:  {result['confianca']}\n"
        f"Score:      {result['score']}/{max_s} ({pct:.0f}%)\n\n"
        f"{tf_icon} TIMEFRAME IDEAL: {tf}\n"
        f"  {result.get('timeframe_razao','')}\n\n"
        f"─── ESTRATEGIAS ────────────\n"
        f"  Reversao:   {'+' if result['score_reversao'] >= 0 else ''}{result['score_reversao']}\n"
        f"  Fibonacci:  {'+' if result['score_fibonacci'] >= 0 else ''}{result['score_fibonacci']}\n"
        f"  LTA/LTB:    {'+' if result['score_lta_ltb'] >= 0 else ''}{result['score_lta_ltb']}\n"
        f"  Fakeout:    {'+' if result['score_fakeout'] >= 0 else ''}{result['score_fakeout']}\n"
        f"  Pullback:   {'+' if result['score_pullback'] >= 0 else ''}{result['score_pullback']}\n\n"
        f"─── INDICADORES ────────────\n"
        f"RSI:        {result['rsi']}\n"
        f"EMA 9/21/50:{result['ema9']} / {result['ema21']} / {result['ema50']}\n"
        f"MACD:       {result['macd']}\n"
        f"Estocastico:{result['stoch']}\n"
        f"ADX:        {result['adx']}\n"
        f"VWAP:       {result['vwap']}\n"
        f"Williams R: {result['wr']}\n"
        f"CCI:        {result['cci']}\n"
        f"Preco:      {result['price']}\n\n"
        f"─── ANALISE ────────────────\n"
        f"{razoes}\n\n"
        f"══════════════════════════\n"
        f"⚠ Testa sempre na DEMO primeiro!\n"
        f"⚠ Max 2% do saldo por operacao"
    )
    return msg.strip()
