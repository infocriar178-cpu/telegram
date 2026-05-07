"""
╔══════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO — pocket_ws.py  (CORRIGIDO)        ║
║         Precos em tempo real via WebSocket                   ║
║         OTC (Pocket) + Mercado Aberto (Yahoo Finance)        ║
╚══════════════════════════════════════════════════════════════╝
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
#  ATIVOS
#  - OTC: dados da Pocket Option (WebSocket)
#  - Mercado Aberto: dados do Yahoo Finance (real)
# ══════════════════════════════════════════════════════════════
ATIVOS_MERCADO = {
    "EURUSD=X":  {"nome": "EUR/USD",  "tipo": "mercado", "emoji": "💱", "yahoo": "EURUSD=X"},
    "GBPUSD=X":  {"nome": "GBP/USD",  "tipo": "mercado", "emoji": "💱", "yahoo": "GBPUSD=X"},
    "USDJPY=X":  {"nome": "USD/JPY",  "tipo": "mercado", "emoji": "💱", "yahoo": "USDJPY=X"},
    "AUDUSD=X":  {"nome": "AUD/USD",  "tipo": "mercado", "emoji": "💱", "yahoo": "AUDUSD=X"},
    "USDCAD=X":  {"nome": "USD/CAD",  "tipo": "mercado", "emoji": "💱", "yahoo": "USDCAD=X"},
    "EURJPY=X":  {"nome": "EUR/JPY",  "tipo": "mercado", "emoji": "💱", "yahoo": "EURJPY=X"},
    "GBPJPY=X":  {"nome": "GBP/JPY",  "tipo": "mercado", "emoji": "💱", "yahoo": "GBPJPY=X"},
    "USDCHF=X":  {"nome": "USD/CHF",  "tipo": "mercado", "emoji": "💱", "yahoo": "USDCHF=X"},
    "EURGBP=X":  {"nome": "EUR/GBP",  "tipo": "mercado", "emoji": "💱", "yahoo": "EURGBP=X"},
    "NZDUSD=X":  {"nome": "NZD/USD",  "tipo": "mercado", "emoji": "💱", "yahoo": "NZDUSD=X"},
}

ATIVOS_OTC = {
    "#EURUSD_otc":  {"nome": "EUR/USD OTC",  "tipo": "otc", "emoji": "🌙"},
    "#GBPUSD_otc":  {"nome": "GBP/USD OTC",  "tipo": "otc", "emoji": "🌙"},
    "#USDJPY_otc":  {"nome": "USD/JPY OTC",  "tipo": "otc", "emoji": "🌙"},
    "#AUDUSD_otc":  {"nome": "AUD/USD OTC",  "tipo": "otc", "emoji": "🌙"},
    "#USDCAD_otc":  {"nome": "USD/CAD OTC",  "tipo": "otc", "emoji": "🌙"},
    "#EURJPY_otc":  {"nome": "EUR/JPY OTC",  "tipo": "otc", "emoji": "🌙"},
    "#GBPJPY_otc":  {"nome": "GBP/JPY OTC",  "tipo": "otc", "emoji": "🌙"},
    "#EURGBP_otc":  {"nome": "EUR/GBP OTC",  "tipo": "otc", "emoji": "🌙"},
    "#NZDUSD_otc":  {"nome": "NZD/USD OTC",  "tipo": "otc", "emoji": "🌙"},
    "#USDCHF_otc":  {"nome": "USD/CHF OTC",  "tipo": "otc", "emoji": "🌙"},
}

TODOS_ATIVOS = {**ATIVOS_MERCADO, **ATIVOS_OTC}

# Buffers de preco
price_buffers: dict = {k: deque(maxlen=500) for k in TODOS_ATIVOS}
last_prices:   dict = {}


# ══════════════════════════════════════════════════════════════
#  YAHOO FINANCE — Mercado Aberto
# ══════════════════════════════════════════════════════════════
def carregar_yahoo(ticker: str, ativo_key: str, periodo: str = "5d", intervalo: str = "1m"):
    """Carrega velas do Yahoo Finance para ativos de mercado aberto."""
    try:
        df = yf.download(ticker, period=periodo, interval=intervalo,
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            logger.warning(f"Yahoo Finance: sem dados para {ticker}")
            return

        # Flatten colunas se necessario
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()
        for _, row in df.iterrows():
            ts = int(row.name.timestamp()) if hasattr(row.name, 'timestamp') else int(time.time())
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
        logger.info(f"Yahoo Finance: {ticker} — {len(df)} velas carregadas")

    except Exception as e:
        logger.error(f"Erro Yahoo Finance {ticker}: {e}")


def iniciar_yahoo_mercado():
    """Carrega dados Yahoo Finance para todos os ativos de mercado aberto."""
    def _carregar_todos():
        for key, info in ATIVOS_MERCADO.items():
            ticker = info.get("yahoo", key)
            carregar_yahoo(ticker, key)
        logger.info("Yahoo Finance: todos os ativos de mercado carregados!")

    t = threading.Thread(target=_carregar_todos, daemon=True)
    t.start()

    # Actualizar a cada 5 minutos em background
    def _loop_actualizacao():
        while True:
            time.sleep(300)
            for key, info in ATIVOS_MERCADO.items():
                ticker = info.get("yahoo", key)
                carregar_yahoo(ticker, key, periodo="1d", intervalo="1m")

    t2 = threading.Thread(target=_loop_actualizacao, daemon=True)
    t2.start()


# ══════════════════════════════════════════════════════════════
#  LOGIN
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
        # CORRIGIDO: usar o cookie correto para SSID
        self._ssid        = self._extrair_ssid()

    def _extrair_ssid(self) -> str:
        """Extrai o SSID correto dos cookies."""
        cookies = self.session_info.get("cookies", {})
        # Ordem de prioridade correta para Pocket Option
        for chave in ("PHPSESSID", "ci_session", "ssid", "po_uuid", "session"):
            val = cookies.get(chave, "")
            if val:
                logger.info(f"SSID encontrado no cookie: {chave}")
                return val
        logger.warning("Nenhum SSID encontrado nos cookies!")
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
        cookies = self.session_info.get("cookies", {})
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
                logger.info(f"A ligar ao WebSocket: {url.split('?')[0]}...")
                headers = self._headers()

                try:
                    ws_conn = websockets.connect(
                        url,
                        ssl=ssl_ctx,
                        additional_headers=headers,
                        ping_interval=20,
                        ping_timeout=15,
                        max_size=10_000_000,
                        open_timeout=10,
                    )
                except TypeError:
                    ws_conn = websockets.connect(
                        url,
                        ssl=ssl_ctx,
                        extra_headers=headers,
                        ping_interval=20,
                        ping_timeout=15,
                        max_size=10_000_000,
                    )

                async with ws_conn as ws:
                    self.ws        = ws
                    self.connected = True
                    logger.info(f"WebSocket LIGADO! SSID={'presente' if self._ssid else 'ausente'}")

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
                        logger.info("Autenticacao enviada")

                    # Subscrever apenas OTC
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
        """Subscreve apenas ativos OTC."""
        count = 0
        for ativo in ATIVOS_OTC:
            payload = json.dumps(["subfor", json.dumps({
                "asset":  ativo,
                "period": 60,
            })])
            await ws.send(f"42{payload}")
            await asyncio.sleep(0.08)
            count += 1
        logger.info(f"Subscrito: {count} ativos OTC")

    async def _processar(self, ws, msg: str):
        try:
            if msg == "2":
                await ws.send("3")
                return
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

            ativo = (
                payload.get("asset") or
                payload.get("symbol") or
                payload.get("pair") or ""
            )
            preco = float(
                payload.get("close") or
                payload.get("price") or
                payload.get("value") or
                payload.get("ask") or 0
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
            logger.debug(f"Erro guardar preco: {e}")

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
                logger.info("Reconectando em 10 segundos...")
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

def hora_corretora() -> str:
    return datetime.now(TZ_CORRETORA).strftime("%d/%m/%Y %H:%M:%S")
