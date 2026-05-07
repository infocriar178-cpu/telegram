"""
╔══════════════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO v5.0 — bot_pocket.py                      ║
║                                                                      ║
║  NOVO v5.0:                                                          ║
║  • 65+ ativos: Forex, Crypto, Acoes, Indices, Commodities, OTC      ║
║  • Menus por categoria (💱 Forex / 🪙 Crypto / 📈 Acoes / etc.)    ║
║  • Comandos /forex /crypto /acoes /indices /commodities /otc        ║
║  • SuperTrend adicionado ao score (6 estrategias)                   ║
║  • Score maximo: 25 pontos                                           ║
║  • Mensagem profissional com barra de progresso                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import logging
import asyncio
import sys
import pytz
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

from pocket_ws import (
    fazer_login, PocketOptionWS,
    ATIVOS_FOREX, ATIVOS_CRYPTO, ATIVOS_ACOES, ATIVOS_INDICES,
    ATIVOS_COMMODITIES, ATIVOS_OTC, ATIVOS_MERCADO, TODOS_ATIVOS,
    ativos_prontos, ativos_prontos_por_categoria,
    hora_corretora, iniciar_yahoo_mercado,
)
from signals_pocket import gerar_sinal, formatar_sinal, EXPIRACOES
from chart_pocket   import gerar_grafico

# ══════════════════════════════════════════════════════════════
#  CONFIGURACAO
# ══════════════════════════════════════════════════════════════
TELEGRAM_TOKEN      = "8789789689:AAFKLjgHZAaXsyVuxJEXmSpIwdi2JFj3aLo"
POCKET_EMAIL        = "r31017043@gmail.com"
POCKET_PASSWORD     = "196411aa@"

INTERVALO_ALERTAS   = 5      # minutos
INTERVALO_TURBO_SEG = 30     # segundos (turbo)
MIN_SCORE_ALERTA    = 7      # score minimo para alertas (aumentado para 7/25)

# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("pocket_signal_pro_v5.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Estado global
usuarios_ativos:   set              = set()
jobs_ativos:       dict             = {}
expiracao_usuario: dict             = {}
ws_client:         PocketOptionWS   = None

# Mapa categorias
CATEGORIAS = {
    "forex":       {"label": "💱 FOREX",          "ativos": ATIVOS_FOREX},
    "crypto":      {"label": "🪙 CRYPTO",          "ativos": ATIVOS_CRYPTO},
    "acoes":       {"label": "📈 ACOES USA",       "ativos": ATIVOS_ACOES},
    "indices":     {"label": "📊 INDICES",         "ativos": ATIVOS_INDICES},
    "commodities": {"label": "🏅 COMMODITIES",     "ativos": ATIVOS_COMMODITIES},
    "otc":         {"label": "🌙 OTC",             "ativos": ATIVOS_OTC},
}


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════
def get_exp(chat_id: int) -> str:
    return expiracao_usuario.get(chat_id, "1m")

def truncar(texto: str, limite: int = 4096) -> str:
    if len(texto.encode("utf-8")) <= limite:
        return texto
    linhas = texto.split("\n")
    out, total = [], 0
    for l in linhas:
        t = len((l + "\n").encode("utf-8"))
        if total + t > limite - 20:
            break
        out.append(l); total += t
    return "\n".join(out)

async def enviar(bot, chat_id: int, texto: str, teclado=None):
    try:
        await bot.send_message(chat_id=chat_id, text=truncar(texto), reply_markup=teclado)
    except Exception as e:
        logger.error(f"Erro envio {chat_id}: {e}")

async def enviar_foto(bot, chat_id: int, buf, caption: str = "", teclado=None):
    try:
        await bot.send_photo(
            chat_id=chat_id, photo=buf,
            caption=truncar(caption, 1024), reply_markup=teclado,
        )
    except Exception as e:
        logger.error(f"Erro foto {chat_id}: {e}")


# ══════════════════════════════════════════════════════════════
#  TECLADOS
# ══════════════════════════════════════════════════════════════
def teclado_principal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        # Linha 1 — categorias de ativos
        [InlineKeyboardButton("💱 Forex",          callback_data="cat_forex"),
         InlineKeyboardButton("🪙 Crypto",         callback_data="cat_crypto")],
        [InlineKeyboardButton("📈 Acoes",          callback_data="cat_acoes"),
         InlineKeyboardButton("📊 Indices",        callback_data="cat_indices")],
        [InlineKeyboardButton("🏅 Commodities",    callback_data="cat_commodities"),
         InlineKeyboardButton("🌙 OTC",            callback_data="cat_otc")],
        # Linha 2 — scans
        [InlineKeyboardButton("⚡ Top Sinais",      callback_data="top"),
         InlineKeyboardButton("🔍 Scan Completo",  callback_data="scan")],
        # Linha 3 — estrategias
        [InlineKeyboardButton("📈 LTA/LTB",        callback_data="scan_tendencia"),
         InlineKeyboardButton("🔄 Reversoes",      callback_data="scan_reversao")],
        [InlineKeyboardButton("📐 Fibonacci",      callback_data="scan_fibonacci"),
         InlineKeyboardButton("↩ Pullback",        callback_data="scan_pullback")],
        [InlineKeyboardButton("🌀 SuperTrend",     callback_data="scan_supertrend"),
         InlineKeyboardButton("⚡ Fakeout",         callback_data="scan_fakeout")],
        # Linha 4 — controlo
        [InlineKeyboardButton("⏱ Expiracao",       callback_data="expiracao"),
         InlineKeyboardButton("📡 Alertas Auto",   callback_data="auto")],
        [InlineKeyboardButton("📶 Estado",         callback_data="status"),
         InlineKeyboardButton("ℹ️ Ajuda",           callback_data="help")],
    ])

def teclado_expiracao() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ 5 Seg (Turbo)",   callback_data="exp_5s"),
         InlineKeyboardButton("⚡ 10 Seg (Turbo)",  callback_data="exp_10s")],
        [InlineKeyboardButton("🟢 1 Minuto",        callback_data="exp_1m"),
         InlineKeyboardButton("🕐 5 Minutos",       callback_data="exp_5m")],
        [InlineKeyboardButton("🕒 15 Minutos",      callback_data="exp_15m"),
         InlineKeyboardButton("🕑 1h 45 Minutos",   callback_data="exp_1h45")],
        [InlineKeyboardButton("◀ Menu",             callback_data="menu")],
    ])

def teclado_categoria(categoria: str) -> InlineKeyboardMarkup:
    """Teclado com os ativos de uma categoria."""
    ativos = CATEGORIAS.get(categoria, {}).get("ativos", {})
    botoes = []
    items  = list(ativos.items())
    for i in range(0, len(items), 2):
        linha = []
        for ativo, info in items[i:i+2]:
            linha.append(InlineKeyboardButton(
                f"{info['emoji']} {info['nome']}",
                callback_data=f"sinal_{ativo}"
            ))
        botoes.append(linha)
    botoes.append([InlineKeyboardButton("◀ Menu", callback_data="menu")])
    return InlineKeyboardMarkup(botoes)

def teclado_voltar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀ Menu", callback_data="menu")]])


# ══════════════════════════════════════════════════════════════
#  PROCESSAR SINAL + GRAFICO
# ══════════════════════════════════════════════════════════════
async def processar_sinal(bot, chat_id: int, ativo: str, via_callback=False):
    info      = TODOS_ATIVOS.get(ativo, {})
    nome      = info.get("nome", ativo)
    tipo      = info.get("tipo", "mercado")
    categoria = info.get("categoria", "forex")
    exp       = get_exp(chat_id)

    prontos = ativos_prontos()
    if ativo not in prontos:
        from pocket_ws import price_buffers
        aguarda = 30 - len(list(price_buffers.get(ativo, [])))
        await enviar(bot, chat_id,
            f"⏳ A recolher dados para {nome}...\n"
            f"Ainda preciso de ~{max(aguarda, 0)} velas.\n"
            f"Aguarda 30-60 segundos e tenta de novo.",
            teclado=teclado_voltar()
        )
        return

    try:
        result = gerar_sinal(ativo, exp)
        texto  = formatar_sinal(nome, result, tipo, categoria)

        loop = asyncio.get_event_loop()
        buf  = await loop.run_in_executor(
            None,
            lambda: gerar_grafico(
                ativo,
                direction       = result["direction"],
                score           = result["score"],
                tipo_tendencia  = result.get("tipo_tendencia",  "NEUTRO"),
                timeframe_ideal = result.get("timeframe_ideal", "M1"),
                score_fibonacci = result.get("score_fibonacci", 0),
                score_pullback  = result.get("score_pullback",  0),
            )
        )

        tf   = result.get("timeframe_ideal", "M1")
        tend = result.get("tipo_tendencia",  "NEUTRO")
        s_st = result.get("score_supertrend", 0)

        if buf:
            caption = (
                f"{result['emoji']} {result['direction']} — {nome}\n"
                f"Score: {result['score']}/25 | {result['confianca']}\n"
                f"Preco: {result['price']} | TF: {tf} | {tend}\n"
                f"Rev{result['score_reversao']:+d} "
                f"Fib{result['score_fibonacci']:+d} "
                f"LTA{result['score_lta_ltb']:+d} "
                f"FK{result['score_fakeout']:+d} "
                f"PB{result['score_pullback']:+d} "
                f"ST{s_st:+d}"
            )
            await enviar_foto(bot, chat_id, buf, caption=caption, teclado=teclado_voltar())

        await enviar(bot, chat_id, texto, teclado=teclado_voltar())
        logger.info(f"Sinal v5: {nome} | {result['direction']} | score={result['score']}/25 | TF={tf}")

    except Exception as e:
        await enviar(bot, chat_id,
            f"❌ Erro ao gerar sinal para {nome}:\n{e}",
            teclado=teclado_voltar()
        )
        logger.error(f"Erro sinal {ativo}: {e}")


# ══════════════════════════════════════════════════════════════
#  ALERTAS AUTOMATICOS
# ══════════════════════════════════════════════════════════════
async def enviar_alertas(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    exp     = get_exp(chat_id)
    prontos = ativos_prontos()

    if not prontos:
        await enviar(context.bot, chat_id, "⏳ A aguardar dados...")
        return

    calls, puts = [], []

    for ativo in prontos:
        try:
            r = gerar_sinal(ativo, exp)
            if r["direction"] == "CALL" and r["score"] >= MIN_SCORE_ALERTA:
                calls.append((ativo, r))
            elif r["direction"] == "PUT" and r["score"] <= -MIN_SCORE_ALERTA:
                puts.append((ativo, r))
        except Exception as e:
            logger.debug(f"Erro alerta {ativo}: {e}")

    calls.sort(key=lambda x: x[1]["score"], reverse=True)
    puts.sort(key=lambda x: x[1]["score"])

    top = (calls[:2] + puts[:2])[:3]

    if not top:
        await enviar(context.bot, chat_id,
            f"⚪ Sem sinais fortes agora (score min: {MIN_SCORE_ALERTA}/25)\n"
            f"Hora: {hora_corretora()}"
        )
        return

    for ativo, r in top:
        await processar_sinal(context.bot, chat_id, ativo)
        await asyncio.sleep(1.5)


# ══════════════════════════════════════════════════════════════
#  SCAN POR ESTRATEGIA
# ══════════════════════════════════════════════════════════════
async def scan_por_estrategia(bot, chat_id: int, estrategia: str):
    prontos = ativos_prontos()
    if not prontos:
        await enviar(bot, chat_id, "⏳ Sem dados suficientes ainda.")
        return

    campo_map = {
        "tendencia":   "score_lta_ltb",
        "reversao":    "score_reversao",
        "fibonacci":   "score_fibonacci",
        "pullback":    "score_pullback",
        "supertrend":  "score_supertrend",
        "fakeout":     "score_fakeout",
    }
    nomes_map = {
        "tendencia":   "📈 LTA / LTB",
        "reversao":    "🔄 Reversao",
        "fibonacci":   "📐 Fibonacci",
        "pullback":    "↩ Pullback",
        "supertrend":  "🌀 SuperTrend",
        "fakeout":     "⚡ Fakeout",
    }
    campo    = campo_map.get(estrategia, "score")
    nome_est = nomes_map.get(estrategia, estrategia)

    resultados = []
    for ativo in prontos:
        try:
            r = gerar_sinal(ativo, get_exp(chat_id))
            v = r.get(campo, 0)
            if abs(v) >= 1:
                resultados.append((ativo, r, v))
        except Exception:
            pass

    if not resultados:
        await enviar(bot, chat_id,
            f"{nome_est}\n\nSem sinais desta estrategia agora.",
            teclado=teclado_voltar()
        )
        return

    resultados.sort(key=lambda x: abs(x[2]), reverse=True)
    linhas = [f"🔎 SCAN — {nome_est}\n{'═'*30}"]
    for ativo, r, v in resultados[:10]:
        info = TODOS_ATIVOS.get(ativo, {})
        nome = info.get("nome", ativo)
        cat  = info.get("categoria", "")
        cat_e= info.get("emoji", "📊")
        dir_icon = "🟢" if r["direction"] == "CALL" else ("🔴" if r["direction"] == "PUT" else "⚪")
        tf   = r.get("timeframe_ideal", "M1")
        linhas.append(
            f"{dir_icon} {cat_e} {nome}\n"
            f"   {r['direction']} | Score: {v:+d} | TF: {tf} | {r['confianca']}"
        )

    linhas.append(f"\n{'═'*30}\nHora: {hora_corretora()}")
    await enviar(bot, chat_id, "\n".join(linhas), teclado=teclado_voltar())


# ══════════════════════════════════════════════════════════════
#  SCAN POR CATEGORIA
# ══════════════════════════════════════════════════════════════
async def scan_categoria(bot, chat_id: int, categoria: str):
    """Faz scan de todos os ativos de uma categoria."""
    info_cat = CATEGORIAS.get(categoria, {})
    label    = info_cat.get("label", categoria)
    prontos  = ativos_prontos_por_categoria(categoria)

    if not prontos:
        await enviar(bot, chat_id,
            f"{label}\n\n⏳ Sem dados suficientes nesta categoria.\nAguarda 30-60s.",
            teclado=teclado_voltar()
        )
        return

    exp  = get_exp(chat_id)
    calls, puts, neutros = [], [], []

    for ativo in prontos:
        try:
            r    = gerar_sinal(ativo, exp)
            info = TODOS_ATIVOS.get(ativo, {})
            nome = info.get("nome", ativo)
            tf   = r.get("timeframe_ideal", "M1")
            linha= f"  {nome} | {r['score']:+d}/25 | TF:{tf}"
            if r["direction"] == "CALL":
                calls.append((r["score"], linha))
            elif r["direction"] == "PUT":
                puts.append((r["score"], linha))
            else:
                neutros.append(linha)
        except Exception:
            pass

    calls.sort(reverse=True); puts.sort()
    linhas = [f"🔍 {label} — {len(prontos)} ativos\n{'═'*30}"]
    if calls:
        linhas.append(f"\n🟢 CALL ({len(calls)})")
        linhas.extend(l for _, l in calls)
    if puts:
        linhas.append(f"\n🔴 PUT ({len(puts)})")
        linhas.extend(l for _, l in puts)
    if neutros:
        linhas.append(f"\n⚪ NEUTRO ({len(neutros)})")
        linhas.extend(neutros[:4])
    linhas.append(f"\n{'═'*30}\nHora: {hora_corretora()}")
    await enviar(bot, chat_id, "\n".join(linhas), teclado=teclado_categoria(categoria))


# ══════════════════════════════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuarios_ativos.add(chat_id)
    texto = (
        "🚀 POCKET SIGNAL PRO v5.0\n\n"
        "Motor de analise tecnica profissional\n"
        "com 65+ ativos e 6 estrategias!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  💱 Forex  (20 pares)\n"
        "  🪙 Crypto (12 moedas)\n"
        "  📈 Acoes  (10 tickers USA)\n"
        "  📊 Indices (8 globais)\n"
        "  🏅 Commodities (6 mercados)\n"
        "  🌙 OTC    (10 pares Pocket)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "ESTRATEGIAS (6):\n"
        "  📈 LTA/LTB  |  🔄 Reversao\n"
        "  📐 Fibonacci |  ⚡ Fakeout\n"
        "  ↩ Pullback  |  🌀 SuperTrend ★\n\n"
        "Score maximo: 25 pontos\n\n"
        "Escolhe uma opcao:"
    )
    await update.message.reply_text(texto, reply_markup=teclado_principal())

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuarios_ativos.add(chat_id)
    texto   = f"POCKET SIGNAL PRO v5.0\nHora: {hora_corretora()}\n\nMenu principal:"
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_principal())
    else:
        try:
            await update.callback_query.edit_message_text(texto, reply_markup=teclado_principal())
        except Exception:
            await enviar(context.bot, chat_id, texto, teclado_principal())

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prontos = ativos_prontos()
    exp     = get_exp(chat_id)

    if not prontos:
        msg = "⏳ Sem dados suficientes.\nAguarda 30-60s."
        if update.message:
            await update.message.reply_text(msg, reply_markup=teclado_voltar())
        else:
            await enviar(context.bot, chat_id, msg, teclado_voltar())
        return

    resultados = []
    for ativo in prontos:
        try:
            r = gerar_sinal(ativo, exp)
            resultados.append((ativo, r))
        except Exception:
            pass

    resultados.sort(key=lambda x: abs(x[1]["score"]), reverse=True)
    top8 = resultados[:8]

    linhas = [f"⚡ TOP SINAIS AGORA\n{'═'*32}"]
    for ativo, r in top8:
        info = TODOS_ATIVOS.get(ativo, {})
        nome = info.get("nome", ativo)
        cat  = info.get("emoji", "📊")
        dir_icon = "🟢" if r["direction"] == "CALL" else ("🔴" if r["direction"] == "PUT" else "⚪")
        tf   = r.get("timeframe_ideal", "M1")
        tend = r.get("tipo_tendencia", "")
        linhas.append(
            f"{dir_icon} {cat} {nome}\n"
            f"   Score: {r['score']}/25 | TF: {tf} | {tend}\n"
            f"   {r['confianca']}"
        )
    linhas.append(f"\n{'═'*32}\nHora: {hora_corretora()}")

    texto = "\n".join(linhas)
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_voltar())
    else:
        await enviar(context.bot, chat_id, texto, teclado_voltar())

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prontos = ativos_prontos()
    exp     = get_exp(chat_id)

    if not prontos:
        msg = "⏳ Sem dados suficientes."
        if update.message:
            await update.message.reply_text(msg, reply_markup=teclado_voltar())
        else:
            await enviar(context.bot, chat_id, msg, teclado_voltar())
        return

    calls, puts, neutros = [], [], []
    for ativo in prontos:
        try:
            r    = gerar_sinal(ativo, exp)
            info = TODOS_ATIVOS.get(ativo, {})
            nome = info.get("nome", ativo)
            cat  = info.get("emoji", "")
            tf   = r.get("timeframe_ideal", "M1")
            tend = r.get("tipo_tendencia", "")
            linha = f"  {cat} {nome} | {r['score']:+d}/25 | TF:{tf} | {tend}"
            if r["direction"] == "CALL":
                calls.append((r["score"], linha))
            elif r["direction"] == "PUT":
                puts.append((r["score"], linha))
            else:
                neutros.append(linha)
        except Exception:
            pass

    calls.sort(reverse=True); puts.sort()
    linhas = [f"🔍 SCAN COMPLETO — {len(prontos)} ativos\n{'═'*32}"]
    if calls:
        linhas.append(f"\n🟢 CALL ({len(calls)})")
        linhas.extend(l for _, l in calls)
    if puts:
        linhas.append(f"\n🔴 PUT ({len(puts)})")
        linhas.extend(l for _, l in puts)
    if neutros:
        linhas.append(f"\n⚪ NEUTRO ({len(neutros)})")
        linhas.extend(neutros[:5])
    linhas.append(f"\n{'═'*32}\nHora: {hora_corretora()}")

    texto = "\n".join(linhas)
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_voltar())
    else:
        await enviar(context.bot, chat_id, texto, teclado_voltar())

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ws_client
    prontos      = ativos_prontos()
    ws_ok        = ws_client.connected if ws_client else False
    alerta_ativo = update.effective_chat.id in jobs_ativos
    exp_lbl      = EXPIRACOES[get_exp(update.effective_chat.id)]["label"]

    # Contar por categoria
    def count_cat(cat):
        return sum(1 for k, v in prontos.items() if v.get("categoria") == cat)

    texto = (
        f"📶 ESTADO — POCKET SIGNAL PRO v5.0\n{'═'*34}\n\n"
        f"WebSocket OTC:    {'✅ Ligado' if ws_ok else '❌ Desligado'}\n"
        f"Alertas auto:     {'✅ Activos' if alerta_ativo else '❌ Inactivos'}\n"
        f"Expiracao:        {exp_lbl}\n"
        f"Score minimo:     {MIN_SCORE_ALERTA}/25\n"
        f"Hora (GMT+1):     {hora_corretora()}\n\n"
        f"ATIVOS PRONTOS: {len(prontos)}/{len(TODOS_ATIVOS)}\n"
        f"  💱 Forex:       {count_cat('forex')}/{len(ATIVOS_FOREX)}\n"
        f"  🪙 Crypto:      {count_cat('crypto')}/{len(ATIVOS_CRYPTO)}\n"
        f"  📈 Acoes:       {count_cat('acoes')}/{len(ATIVOS_ACOES)}\n"
        f"  📊 Indices:     {count_cat('indices')}/{len(ATIVOS_INDICES)}\n"
        f"  🏅 Commodities: {count_cat('commodities')}/{len(ATIVOS_COMMODITIES)}\n"
        f"  🌙 OTC:         {count_cat('otc')}/{len(ATIVOS_OTC)}\n\n"
        f"ESTRATEGIAS v5.0:\n"
        f"  📈 LTA/LTB  |  🔄 Reversao\n"
        f"  📐 Fibonacci |  ⚡ Fakeout\n"
        f"  ↩ Pullback  |  🌀 SuperTrend ★\n"
        f"  ⏱ Timeframe: M1 / M5 / M15"
    )
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_voltar())
    else:
        await enviar(context.bot, update.effective_chat.id, texto, teclado_voltar())

async def auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    exp_lbl = EXPIRACOES[get_exp(chat_id)]["label"]

    if chat_id in jobs_ativos:
        texto = (
            f"📡 Alertas ja estao activos!\n\n"
            f"Intervalo: {INTERVALO_ALERTAS} minutos\n"
            f"Expiracao: {exp_lbl}\n"
            f"Score minimo: {MIN_SCORE_ALERTA}/25\n\n"
            f"Usa /parar para desactivar."
        )
    else:
        exp_atual  = get_exp(chat_id)
        _turbo     = EXPIRACOES.get(exp_atual, {}).get("turbo", False)
        _intervalo = INTERVALO_TURBO_SEG if _turbo else INTERVALO_ALERTAS * 60
        _label_int = f"{INTERVALO_TURBO_SEG}s (Turbo)" if _turbo else f"{INTERVALO_ALERTAS} min"

        job = context.job_queue.run_repeating(
            enviar_alertas, interval=_intervalo, first=5,
            data=chat_id, name=str(chat_id)
        )
        jobs_ativos[chat_id] = job
        modo  = "⚡ TURBO" if _turbo else "🔔 Normal"
        texto = (
            f"📡 Alertas automaticos activados! {modo}\n\n"
            f"Hora: {hora_corretora()}\n"
            f"Intervalo: {_label_int}\n"
            f"Expiracao: {exp_lbl}\n"
            f"Score minimo: {MIN_SCORE_ALERTA}/25\n\n"
            f"Envio grafico + sinal automaticamente!\n"
            f"Usa /parar para desactivar."
        )

    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_voltar())
    else:
        await enviar(context.bot, chat_id, texto, teclado_voltar())

async def parar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in jobs_ativos:
        jobs_ativos[chat_id].schedule_removal()
        del jobs_ativos[chat_id]
        texto = "⏹ Alertas desactivados.\n\nUsa /auto para reactivar."
    else:
        texto = "Nao tens alertas activos.\n\nUsa /auto para activar."
    await update.message.reply_text(texto, reply_markup=teclado_principal())

async def expiracao_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    exp_lbl = EXPIRACOES[get_exp(chat_id)]["label"]
    texto   = f"Expiracao actual: {exp_lbl}\n\nEscolhe nova expiracao:"
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_expiracao())
    else:
        try:
            await update.callback_query.edit_message_text(texto, reply_markup=teclado_expiracao())
        except Exception:
            await enviar(context.bot, chat_id, texto, teclado_expiracao())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "POCKET SIGNAL PRO v5.0 — AJUDA\n"
        "══════════════════════════════════\n\n"
        "ATIVOS (65+):\n"
        "  💱 /forex     — 20 pares Forex\n"
        "  🪙 /crypto    — 12 criptomoedas\n"
        "  📈 /acoes     — 10 acoes USA\n"
        "  📊 /indices   — 8 indices globais\n"
        "  🏅 /commodities — 6 mercadorias\n"
        "  🌙 /otc       — 10 pares OTC\n\n"
        "ESTRATEGIAS (6):\n"
        "  📈 LTA/LTB  — Linha de Tendencia\n"
        "  🔄 Reversao — Sobrecompra/Sobrevenda\n"
        "  📐 Fibonacci — Retracao 38/50/61%\n"
        "  ⚡ Fakeout  — Falso Rompimento\n"
        "  ↩ Pullback  — Recuo para EMA\n"
        "  🌀 SuperTrend — Cruzamento de sinal ★\n\n"
        "TIMEFRAME:\n"
        "  ⚡M1  — baixa volatilidade\n"
        "  🕐M5  — volatilidade media\n"
        "  🕒M15 — alta volatilidade\n"
        "  ⏸ AGUARDA — mercado lateral\n\n"
        "SCORE: maximo 25 pontos\n"
        "  >= 7  — sinal emitido\n"
        "  >= 10 — confianca alta\n"
        "  >= 15 — confianca maxima\n\n"
        "COMANDOS:\n"
        "/start /menu /top /scan /auto\n"
        "/parar /status /expiracao /help\n"
        "/forex /crypto /acoes\n"
        "/indices /commodities /otc\n\n"
        "⚠ SEMPRE testa na DEMO primeiro!\n"
        "⚠ Max 2% do saldo por operacao"
    )
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_principal())
    else:
        await enviar(context.bot, update.effective_chat.id, texto, teclado_principal())

# Comandos directos por categoria
async def forex_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await scan_categoria(context.bot, chat_id, "forex")

async def crypto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await scan_categoria(context.bot, chat_id, "crypto")

async def acoes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await scan_categoria(context.bot, chat_id, "acoes")

async def indices_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await scan_categoria(context.bot, chat_id, "indices")

async def commodities_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await scan_categoria(context.bot, chat_id, "commodities")

async def otc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await scan_categoria(context.bot, chat_id, "otc")


# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = update.effective_chat.id

    if data.startswith("sinal_"):
        ativo = data.replace("sinal_", "")
        await processar_sinal(context.bot, chat_id, ativo, via_callback=True)

    elif data.startswith("cat_"):
        categoria = data.replace("cat_", "")
        info_cat  = CATEGORIAS.get(categoria, {})
        label     = info_cat.get("label", categoria)
        n_ativos  = len(info_cat.get("ativos", {}))
        texto     = f"{label}\n{n_ativos} ativos disponiveis\n\nEscolhe ou usa o scan:"
        # Botoes: scan da categoria + lista de ativos
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔍 Scan {label}", callback_data=f"scancat_{categoria}")],
            *teclado_categoria(categoria).inline_keyboard
        ])
        try:
            await query.edit_message_text(texto, reply_markup=kb)
        except Exception:
            await enviar(context.bot, chat_id, texto, kb)

    elif data.startswith("scancat_"):
        categoria = data.replace("scancat_", "")
        await scan_categoria(context.bot, chat_id, categoria)

    elif data.startswith("exp_"):
        exp_key = data.replace("exp_", "")
        if exp_key in EXPIRACOES:
            expiracao_usuario[chat_id] = exp_key
            exp_lbl = EXPIRACOES[exp_key]["label"]
            texto   = f"✅ Expiracao alterada: {exp_lbl}\n\nEscolhe uma opcao:"
            try:
                await query.edit_message_text(texto, reply_markup=teclado_principal())
            except Exception:
                await enviar(context.bot, chat_id, texto, teclado_principal())

    elif data == "scan_tendencia":   await scan_por_estrategia(context.bot, chat_id, "tendencia")
    elif data == "scan_reversao":    await scan_por_estrategia(context.bot, chat_id, "reversao")
    elif data == "scan_fibonacci":   await scan_por_estrategia(context.bot, chat_id, "fibonacci")
    elif data == "scan_pullback":    await scan_por_estrategia(context.bot, chat_id, "pullback")
    elif data == "scan_supertrend":  await scan_por_estrategia(context.bot, chat_id, "supertrend")
    elif data == "scan_fakeout":     await scan_por_estrategia(context.bot, chat_id, "fakeout")

    elif data == "top":        await top_cmd(update, context)
    elif data == "scan":       await scan_cmd(update, context)
    elif data == "auto":       await auto_cmd(update, context)
    elif data == "status":     await status_cmd(update, context)
    elif data == "expiracao":  await expiracao_cmd(update, context)
    elif data == "help":       await help_cmd(update, context)
    elif data == "menu":       await menu_cmd(update, context)


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
def main():
    global ws_client

    print("=" * 60)
    print("   POCKET SIGNAL PRO v5.0 — A INICIAR...")
    print("=" * 60)

    print(f"\n Passo 1: Login na Pocket Option...")
    try:
        sessao    = fazer_login(POCKET_EMAIL, POCKET_PASSWORD)
        ws_client = PocketOptionWS(sessao)
        print(f" ✅ Login bem-sucedido!")
    except Exception as e:
        print(f" ❌ ERRO no login: {e}")
        sys.exit(1)

    print(f"\n Passo 2: A carregar Yahoo Finance ({len(ATIVOS_MERCADO)} ativos)...")
    iniciar_yahoo_mercado()
    print(f" ✅ Yahoo Finance iniciado em background!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandos principais
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("menu",        menu_cmd))
    app.add_handler(CommandHandler("top",         top_cmd))
    app.add_handler(CommandHandler("scan",        scan_cmd))
    app.add_handler(CommandHandler("auto",        auto_cmd))
    app.add_handler(CommandHandler("parar",       parar_cmd))
    app.add_handler(CommandHandler("status",      status_cmd))
    app.add_handler(CommandHandler("expiracao",   expiracao_cmd))
    app.add_handler(CommandHandler("help",        help_cmd))

    # Comandos por categoria
    app.add_handler(CommandHandler("forex",       forex_cmd))
    app.add_handler(CommandHandler("crypto",      crypto_cmd))
    app.add_handler(CommandHandler("acoes",       acoes_cmd))
    app.add_handler(CommandHandler("indices",     indices_cmd))
    app.add_handler(CommandHandler("commodities", commodities_cmd))
    app.add_handler(CommandHandler("otc",         otc_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))

    hora = hora_corretora()
    print(f"\n Passo 3: Bot Telegram iniciado!")
    print(f"\n Hora (GMT+1)      : {hora}")
    print(f" Forex             : {len(ATIVOS_FOREX)} pares")
    print(f" Crypto            : {len(ATIVOS_CRYPTO)} moedas")
    print(f" Acoes             : {len(ATIVOS_ACOES)} tickers")
    print(f" Indices           : {len(ATIVOS_INDICES)} mercados")
    print(f" Commodities       : {len(ATIVOS_COMMODITIES)} mercados")
    print(f" OTC               : {len(ATIVOS_OTC)} pares")
    print(f" TOTAL             : {len(TODOS_ATIVOS)} ativos")
    print(f" Alertas cada      : {INTERVALO_ALERTAS} minutos")
    print(f" Score minimo      : {MIN_SCORE_ALERTA}/25")
    print(f" Estrategias       : Reversao | Fibonacci | LTA/LTB | Fakeout | Pullback | SuperTrend")
    print(f" Timeframes        : M1 / M5 / M15 (deteccao automatica)")
    print("=" * 60)

    async def iniciar():
        asyncio.create_task(ws_client.manter_ligado())
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

    asyncio.run(iniciar())


if __name__ == "__main__":
    if sys.platform == "win32":
        import sys as _sys
        if tuple(int(x) for x in _sys.version.split()[0].split(".")[:2]) < (3, 12):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()

