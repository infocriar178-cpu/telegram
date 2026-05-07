"""
╔══════════════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO v5.0 — pocket_ws.py                       ║
║         Precos em tempo real via WebSocket + Yahoo Finance           ║
║                                                                      ║
║  ATIVOS v5.0 (65+ pares):                                           ║
║  • Forex Major / Minor / Exotico (20 pares)                         ║
║  • Crypto (BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC...)             ║
║  • Acoes USA (AAPL, TSLA, AMZN, NVDA, MSFT, GOOGL, META...)        ║
║  • Indices (S&P500, NASDAQ, DOW, DAX, FTSE, Nikkei...)              ║
║  • Commodities (Ouro, Prata, Petroleo WTI/Brent, Gas Natural...)    ║
║  • OTC Pocket Option (10 pares forex OTC)                           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import time
import logging
import ssl
import websockets
import requests
import yfinance as yf
import pandas as pd
from collections import deque
from datetime import datetime
import pytz
import threading

logger       = logging.getLogger(__name__)
TZ_CORRETORA = pytz.timezone("Africa/Luanda")  # GMT+1

# ══════════════════════════════════════════════════════════════
#  FOREX MAJOR & MINOR
# ══════════════════════════════════════════════════════════════
ATIVOS_FOREX = {
    "EURUSD=X":  {"nome": "EUR/USD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "EURUSD=X"},
    "GBPUSD=X":  {"nome": "GBP/USD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "GBPUSD=X"},
    "USDJPY=X":  {"nome": "USD/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "USDJPY=X"},
    "AUDUSD=X":  {"nome": "AUD/USD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "AUDUSD=X"},
    "USDCAD=X":  {"nome": "USD/CAD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "USDCAD=X"},
    "EURJPY=X":  {"nome": "EUR/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "EURJPY=X"},
    "GBPJPY=X":  {"nome": "GBP/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "GBPJPY=X"},
    "USDCHF=X":  {"nome": "USD/CHF",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "USDCHF=X"},
    "EURGBP=X":  {"nome": "EUR/GBP",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "EURGBP=X"},
    "NZDUSD=X":  {"nome": "NZD/USD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "NZDUSD=X"},
    "AUDJPY=X":  {"nome": "AUD/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "AUDJPY=X"},
    "CADJPY=X":  {"nome": "CAD/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "CADJPY=X"},
    "CHFJPY=X":  {"nome": "CHF/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "CHFJPY=X"},
    "EURAUD=X":  {"nome": "EUR/AUD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "EURAUD=X"},
    "EURCAD=X":  {"nome": "EUR/CAD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "EURCAD=X"},
    "GBPAUD=X":  {"nome": "GBP/AUD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "GBPAUD=X"},
    "GBPCAD=X":  {"nome": "GBP/CAD",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "GBPCAD=X"},
    "NZDJPY=X":  {"nome": "NZD/JPY",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "NZDJPY=X"},
    "USDZAR=X":  {"nome": "USD/ZAR",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "USDZAR=X"},
    "USDMXN=X":  {"nome": "USD/MXN",  "tipo": "mercado", "categoria": "forex", "emoji": "💱", "yahoo": "USDMXN=X"},
}

# ══════════════════════════════════════════════════════════════
#  CRYPTO
# ══════════════════════════════════════════════════════════════
ATIVOS_CRYPTO = {
    "BTC-USD":   {"nome": "BTC/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "₿",  "yahoo": "BTC-USD"},
    "ETH-USD":   {"nome": "ETH/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "⟠",  "yahoo": "ETH-USD"},
    "BNB-USD":   {"nome": "BNB/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "🔶", "yahoo": "BNB-USD"},
    "SOL-USD":   {"nome": "SOL/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "◎",  "yahoo": "SOL-USD"},
    "XRP-USD":   {"nome": "XRP/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "✕",  "yahoo": "XRP-USD"},
    "ADA-USD":   {"nome": "ADA/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "🔵", "yahoo": "ADA-USD"},
    "DOGE-USD":  {"nome": "DOGE/USD", "tipo": "mercado", "categoria": "crypto", "emoji": "🐕", "yahoo": "DOGE-USD"},
    "LTC-USD":   {"nome": "LTC/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "Ł",  "yahoo": "LTC-USD"},
    "AVAX-USD":  {"nome": "AVAX/USD", "tipo": "mercado", "categoria": "crypto", "emoji": "🔺", "yahoo": "AVAX-USD"},
    "LINK-USD":  {"nome": "LINK/USD", "tipo": "mercado", "categoria": "crypto", "emoji": "🔗", "yahoo": "LINK-USD"},
    "DOT-USD":   {"nome": "DOT/USD",  "tipo": "mercado", "categoria": "crypto", "emoji": "🟣", "yahoo": "DOT-USD"},
    "MATIC-USD": {"nome": "MATIC/USD","tipo": "mercado", "categoria": "crypto", "emoji": "🔷", "yahoo": "MATIC-USD"},
}

# ══════════════════════════════════════════════════════════════
#  ACOES USA (via Yahoo Finance)
# ══════════════════════════════════════════════════════════════
ATIVOS_ACOES = {
    "AAPL":   {"nome": "Apple",      "tipo": "mercado", "categoria": "acoes", "emoji": "🍎", "yahoo": "AAPL"},
    "TSLA":   {"nome": "Tesla",      "tipo": "mercado", "categoria": "acoes", "emoji": "🚗", "yahoo": "TSLA"},
    "AMZN":   {"nome": "Amazon",     "tipo": "mercado", "categoria": "acoes", "emoji": "📦", "yahoo": "AMZN"},
    "NVDA":   {"nome": "Nvidia",     "tipo": "mercado", "categoria": "acoes", "emoji": "🎮", "yahoo": "NVDA"},
    "MSFT":   {"nome": "Microsoft",  "tipo": "mercado", "categoria": "acoes", "emoji": "🪟", "yahoo": "MSFT"},
    "GOOGL":  {"nome": "Google",     "tipo": "mercado", "categoria": "acoes", "emoji": "🔍", "yahoo": "GOOGL"},
    "META":   {"nome": "Meta",       "tipo": "mercado", "categoria": "acoes", "emoji": "👤", "yahoo": "META"},
    "NFLX":   {"nome": "Netflix",    "tipo": "mercado", "categoria": "acoes", "emoji": "🎬", "yahoo": "NFLX"},
    "COIN":   {"nome": "Coinbase",   "tipo": "mercado", "categoria": "acoes", "emoji": "🏦", "yahoo": "COIN"},
    "BABA":   {"nome": "Alibaba",    "tipo": "mercado", "categoria": "acoes", "emoji": "🛒", "yahoo": "BABA"},
}

# ══════════════════════════════════════════════════════════════
#  INDICES GLOBAIS
# ══════════════════════════════════════════════════════════════
ATIVOS_INDICES = {
    "^GSPC":  {"nome": "S&P 500",      "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^GSPC"},
    "^NDX":   {"nome": "NASDAQ 100",   "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^NDX"},
    "^DJI":   {"nome": "Dow Jones",    "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^DJI"},
    "^GDAXI": {"nome": "DAX 40",       "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^GDAXI"},
    "^FTSE":  {"nome": "FTSE 100",     "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^FTSE"},
    "^N225":  {"nome": "Nikkei 225",   "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^N225"},
    "^IBEX":  {"nome": "IBEX 35",      "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^IBEX"},
    "^CAC40": {"nome": "CAC 40",       "tipo": "mercado", "categoria": "indices", "emoji": "📊", "yahoo": "^FCHI"},
}

# ══════════════════════════════════════════════════════════════
#  COMMODITIES
# ══════════════════════════════════════════════════════════════
ATIVOS_COMMODITIES = {
    "GC=F":   {"nome": "Ouro (XAU)",   "tipo": "mercado", "categoria": "commodities", "emoji": "🥇", "yahoo": "GC=F"},
    "SI=F":   {"nome": "Prata (XAG)",  "tipo": "mercado", "categoria": "commodities", "emoji": "🥈", "yahoo": "SI=F"},
    "CL=F":   {"nome": "Petroleo WTI", "tipo": "mercado", "categoria": "commodities", "emoji": "🛢", "yahoo": "CL=F"},
    "BZ=F":   {"nome": "Petroleo Brent","tipo": "mercado","categoria": "commodities", "emoji": "🛢", "yahoo": "BZ=F"},
    "NG=F":   {"nome": "Gas Natural",  "tipo": "mercado", "categoria": "commodities", "emoji": "🔥", "yahoo": "NG=F"},
    "HG=F":   {"nome": "Cobre",        "tipo": "mercado", "categoria": "commodities", "emoji": "🟤", "yahoo": "HG=F"},
}

# ══════════════════════════════════════════════════════════════
#  OTC (Pocket Option WebSocket — mercado fechado)
# ══════════════════════════════════════════════════════════════
ATIVOS_OTC = {
    "#EURUSD_otc":  {"nome": "EUR/USD OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#GBPUSD_otc":  {"nome": "GBP/USD OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#USDJPY_otc":  {"nome": "USD/JPY OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#AUDUSD_otc":  {"nome": "AUD/USD OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#USDCAD_otc":  {"nome": "USD/CAD OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#EURJPY_otc":  {"nome": "EUR/JPY OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#GBPJPY_otc":  {"nome": "GBP/JPY OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#EURGBP_otc":  {"nome": "EUR/GBP OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#NZDUSD_otc":  {"nome": "NZD/USD OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
    "#USDCHF_otc":  {"nome": "USD/CHF OTC",  "tipo": "otc", "categoria": "otc", "emoji": "🌙"},
}

# Mercado aberto = tudo exceto OTC
ATIVOS_MERCADO = {**ATIVOS_FOREX, **ATIVOS_CRYPTO, **ATIVOS_ACOES, **ATIVOS_INDICES, **ATIVOS_COMMODITIES}

# Todos juntos
TODOS_ATIVOS = {**ATIVOS_MERCADO, **ATIVOS_OTC}

# Buffers de preco (500 velas por ativo)
price_buffers: dict = {k: deque(maxlen=500) for k in TODOS_ATIVOS}
last_prices:   dict = {}


# ══════════════════════════════════════════════════════════════
#  YAHOO FINANCE — Mercado Aberto
# ══════════════════════════════════════════════════════════════
def carregar_yahoo(ticker: str, ativo_key: str, periodo: str = "5d", intervalo: str = "1m"):
    """Carrega velas do Yahoo Finance para ativos de mercado aberto."""
    try:
        # Crypto e indices precisam de periodos diferentes
        _periodo   = periodo
        _intervalo = intervalo

        # Yahoo limita intervalos para periodos curtos
        if intervalo == "1m" and periodo in ("5d",):
            _periodo = "5d"

        df = yf.download(ticker, period=_periodo, interval=_intervalo,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            logger.warning(f"Yahoo Finance: sem dados para {ticker}")
            return

        # Flatten colunas se MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()
        for _, row in df.iterrows():
            ts = int(row.name.timestamp()) if hasattr(row.name, "timestamp") else int(time.time())
            candle = {
                "time":   ts,
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  float(row["Close"]),
                "volume": float(row.get("Volume", 1) or 1),
            }
            price_buffers[ativo_key].append(candle)

        last_row = df.iloc[-1]
        last_prices[ativo_key] = float(last_row["Close"])
        logger.info(f"Yahoo Finance: {ticker} — {len(df)} velas OK")

    except Exception as e:
        logger.error(f"Erro Yahoo Finance {ticker}: {e}")


def iniciar_yahoo_mercado():
    """Carrega dados Yahoo Finance para todos os ativos de mercado aberto em background."""
    def _carregar_todos():
        for key, info in ATIVOS_MERCADO.items():
            ticker = info.get("yahoo", key)
            # Crypto: periodo 7d, intervalo 5m para ter mais dados
            if info.get("categoria") == "crypto":
                carregar_yahoo(ticker, key, periodo="5d", intervalo="5m")
            elif info.get("categoria") == "indices":
                carregar_yahoo(ticker, key, periodo="5d", intervalo="5m")
            elif info.get("categoria") in ("acoes",):
                carregar_yahoo(ticker, key, periodo="5d", intervalo="5m")
            elif info.get("categoria") == "commodities":
                carregar_yahoo(ticker, key, periodo="5d", intervalo="5m")
            else:
                carregar_yahoo(ticker, key, periodo="5d", intervalo="1m")
            time.sleep(0.3)  # respeitar rate limit Yahoo
        logger.info(f"Yahoo Finance: {len(ATIVOS_MERCADO)} ativos carregados!")

    t = threading.Thread(target=_carregar_todos, daemon=True)
    t.start()

    def _loop_actualizacao():
        while True:
            time.sleep(300)  # actualizar a cada 5 minutos
            for key, info in ATIVOS_MERCADO.items():
                ticker = info.get("yahoo", key)
                cat    = info.get("categoria", "forex")
                if cat in ("crypto", "indices", "acoes", "commodities"):
                    carregar_yahoo(ticker, key, periodo="1d", intervalo="5m")
                else:
                    carregar_yahoo(ticker, key, periodo="1d", intervalo="1m")
                time.sleep(0.2)

    t2 = threading.Thread(target=_loop_actualizacao, daemon=True)
    t2.start()


# ══════════════════════════════════════════════════════════════
#  LOGIN POCKET OPTION
# ══════════════════════════════════════════════════════════════
def fazer_login(email: str, password: str) -> dict:
    """Faz login na Pocket Option e retorna sessao com cookies."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "pt-PT,pt;q=0.9",
        "Origin":          "https://pocketoption.com",
        "Referer":         "https://pocketoption.com/pt/login/",
    })

    try:
        r = session.get("https://pocketoption.com/pt/login/", timeout=20)
        logger.info(f"Pagina login: {r.status_code}")
    except Exception as e:
        raise ConnectionError(f"Nao foi possivel aceder a Pocket Option: {e}")

    csrf = session.cookies.get("csrftoken", "") or session.cookies.get("_csrf", "")
    if csrf:
        session.headers["X-CSRFToken"] = csrf

    try:
        r = session.post(
            "https://pocketoption.com/pt/login/",
            data={"login": email, "password": password, "remember": "on"},
            timeout=20,
            allow_redirects=True,
        )
        logger.info(f"Login: {r.status_code} -> {r.url}")
    except Exception as e:
        raise ConnectionError(f"Erro no login: {e}")

    cookies = dict(session.cookies)
    if not cookies:
        raise ConnectionError(
            "Login falhou — sem cookies de sessao.\n"
            "Verifica o email e password."
        )

    logger.info(f"Login OK! Cookies: {list(cookies.keys())}")
    return {"session": session, "cookies": cookies}


# ══════════════════════════════════════════════════════════════
#  WEBSOCKET — Apenas para OTC
# ══════════════════════════════════════════════════════════════
class PocketOptionWS:
    """Recebe precos OTC em tempo real da Pocket Option via WebSocket."""

    WS_URLS_BASE = [
        "wss://demo-api-eu.po.market/socket.io/",
        "wss://api-l.po.market/socket.io/",
        "wss://api.po.market/socket.io/",
        "wss://api-eu.po.market/socket.io/",
    ]

    def __init__(self, session_info: dict):
        self.session_info = session_info
        self.connected    = False
        self.ws           = None
        self._stop        = False
        self._callbacks   = []
        self._ssid        = self._extrair_ssid()

    def _extrair_ssid(self) -> str:
        cookies = self.session_info.get("cookies", {})
        for chave in ("PHPSESSID", "ci_session", "ssid", "po_uuid", "session"):
            val = cookies.get(chave, "")
            if val:
                logger.info(f"SSID encontrado: {chave}")
                return val
        logger.warning("Nenhum SSID encontrado!")
        return ""

    def _build_urls(self) -> list:
        urls = []
        for base in self.WS_URLS_BASE:
            if self._ssid:
                urls.append(f"{base}?EIO=4&transport=websocket&ssid={self._ssid}")
            urls.append(f"{base}?EIO=4&transport=websocket")
        return urls

    def on_price(self, callback):
        self._callbacks.append(callback)

    def _notificar(self, ativo: str, preco: float, ts: int):
        for cb in self._callbacks:
            try:
                cb(ativo, preco, ts)
            except Exception as e:
                logger.error(f"Erro callback: {e}")

    def _headers(self):
        cookies    = self.session_info.get("cookies", {})
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return {
            "Origin":          "https://pocketoption.com",
            "User-Agent":      (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer":         "https://pocketoption.com/pt/cabinet/",
            "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
            "Cookie":          cookie_str,
        }

    async def connect(self):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode    = ssl.CERT_NONE

        for url in self._build_urls():
            try:
                logger.info(f"A ligar: {url.split('?')[0]}...")
                headers = self._headers()

                try:
                    ws_conn = websockets.connect(
                        url, ssl=ssl_ctx, additional_headers=headers,
                        ping_interval=20, ping_timeout=15,
                        max_size=10_000_000, open_timeout=10,
                    )
                except TypeError:
                    ws_conn = websockets.connect(
                        url, ssl=ssl_ctx, extra_headers=headers,
                        ping_interval=20, ping_timeout=15, max_size=10_000_000,
                    )

                async with ws_conn as ws:
                    self.ws = ws; self.connected = True
                    logger.info(f"WebSocket LIGADO!")

                    try:
                        abertura = await asyncio.wait_for(ws.recv(), timeout=8)
                        logger.debug(f"Abertura: {str(abertura)[:120]}")
                    except asyncio.TimeoutError:
                        pass

                    await ws.send("40")
                    await asyncio.sleep(0.5)

                    if self._ssid:
                        auth = json.dumps(["auth", {"session": self._ssid, "isDemo": 1, "uid": 0}])
                        await ws.send(f"42{auth}")
                        await asyncio.sleep(0.5)

                    await self._subscrever_otc(ws)

                    async for msg in ws:
                        if self._stop:
                            return
                        await self._processar(ws, msg)

            except Exception as e:
                logger.warning(f"Falhou {url.split('?')[0]}: {e}")
                self.connected = False
                await asyncio.sleep(3)

    async def _subscrever_otc(self, ws):
        count = 0
        for ativo in ATIVOS_OTC:
            payload = json.dumps(["subfor", json.dumps({"asset": ativo, "period": 60})])
            await ws.send(f"42{payload}")
            await asyncio.sleep(0.08)
            count += 1
        logger.info(f"OTC subscrito: {count} ativos")

    async def _processar(self, ws, msg: str):
        try:
            if msg == "2":
                await ws.send("3"); return
            if not msg.startswith("42"):
                return
            dados = json.loads(msg[2:])
            if not isinstance(dados, list) or len(dados) < 2:
                return
            evento, payload = dados[0], dados[1]
            if evento in ("candle", "quote", "price", "tick", "updateStream",
                          "candles", "successcloseorder", "successopenorder"):
                self._guardar(payload)
        except Exception:
            pass

    def _guardar(self, payload):
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            if not isinstance(payload, dict):
                return

            ativo = (payload.get("asset") or payload.get("symbol") or payload.get("pair") or "")
            preco = float(
                payload.get("close") or payload.get("price") or
                payload.get("value") or payload.get("ask") or 0
            )
            ts = int(payload.get("time") or payload.get("timestamp") or time.time())

            if not ativo or preco <= 0:
                return

            if ativo in price_buffers:
                price_buffers[ativo].append({
                    "time":   ts,
                    "open":   float(payload.get("open",  preco)),
                    "high":   float(payload.get("high",  preco)),
                    "low":    float(payload.get("low",   preco)),
                    "close":  preco,
                    "volume": float(payload.get("volume", 1)),
                })
                last_prices[ativo] = preco
                self._notificar(ativo, preco, ts)

        except Exception as e:
            logger.debug(f"Erro guardar: {e}")

    async def desligar(self):
        self._stop = True
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.connected = False

    async def manter_ligado(self):
        while not self._stop:
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"Erro ligacao: {e}")
            if not self._stop:
                logger.info("Reconectando em 10s...")
                await asyncio.sleep(10)


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════
def get_candles(ativo: str, n: int = 150) -> list:
    return list(price_buffers.get(ativo, deque()))[-n:]

def get_last_price(ativo: str) -> float:
    return last_prices.get(ativo, 0.0)

def ativos_prontos(minimo: int = 30) -> dict:
    return {
        k: v for k, v in TODOS_ATIVOS.items()
        if len(price_buffers.get(k, [])) >= minimo
    }

def ativos_prontos_por_categoria(categoria: str, minimo: int = 30) -> dict:
    """Retorna ativos prontos de uma categoria especifica."""
    return {
        k: v for k, v in TODOS_ATIVOS.items()
        if v.get("categoria") == categoria and len(price_buffers.get(k, [])) >= minimo
    }

def hora_corretora() -> str:
    return datetime.now(TZ_CORRETORA).strftime("%d/%m/%Y %H:%M:%S")
