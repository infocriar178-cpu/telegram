"""
╔══════════════════════════════════════════════════════════════════════╗
║         POCKET SIGNAL PRO v4.0 — bot_pocket.py                      ║
║         OTC: dados Pocket Option (WebSocket)                         ║
║         Mercado Aberto: dados Yahoo Finance (real)                   ║
║         Graficos com LTA/LTB + Fibonacci + Pullback + Fakeout       ║
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

from pocket_ws   import (fazer_login, PocketOptionWS, ATIVOS_MERCADO, ATIVOS_OTC,
                          TODOS_ATIVOS, ativos_prontos, hora_corretora, iniciar_yahoo_mercado)
from signals_pocket import gerar_sinal, formatar_sinal, EXPIRACOES
from chart_pocket   import gerar_grafico

# ══════════════════════════════════════════════════════════════
#  CONFIGURACAO — altera aqui os teus dados
# ══════════════════════════════════════════════════════════════
TELEGRAM_TOKEN      = "8789789689:AAFKLjgHZAaXsyVuxJEXmSpIwdi2JFj3aLo"
POCKET_EMAIL        = "r31017043@gmail.com"
POCKET_PASSWORD     = "196411aa@"

INTERVALO_ALERTAS   = 5     # minutos entre alertas automaticos
INTERVALO_TURBO_SEG = 30    # segundos (modo turbo)
MIN_SCORE_ALERTA    = 5     # score minimo para alertas (era 4, agora 5 pois max=20)

# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("pocket_signal_pro_v4.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Estado global
usuarios_ativos:   set  = set()
jobs_ativos:       dict = {}
expiracao_usuario: dict = {}
ws_client:         PocketOptionWS = None


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
        logger.error(f"Erro envio foto {chat_id}: {e}")


# ══════════════════════════════════════════════════════════════
#  TECLADOS
# ══════════════════════════════════════════════════════════════
def teclado_principal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Mercado Aberto",    callback_data="lista_mercado"),
         InlineKeyboardButton("🌙 OTC",               callback_data="lista_otc")],
        [InlineKeyboardButton("⚡ Top Sinais",         callback_data="top"),
         InlineKeyboardButton("🔍 Scan Completo",     callback_data="scan")],
        [InlineKeyboardButton("📈 LTA/LTB",           callback_data="scan_tendencia"),
         InlineKeyboardButton("🔄 Reversoes",         callback_data="scan_reversao")],
        [InlineKeyboardButton("📐 Fibonacci",         callback_data="scan_fibonacci"),
         InlineKeyboardButton("↩ Pullback",           callback_data="scan_pullback")],
        [InlineKeyboardButton("⏱ Expiracao",          callback_data="expiracao"),
         InlineKeyboardButton("📡 Alertas Auto",      callback_data="auto")],
        [InlineKeyboardButton("📶 Estado Ligacao",    callback_data="status"),
         InlineKeyboardButton("ℹ️ Ajuda",              callback_data="help")],
    ])

def teclado_expiracao() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ 5 Seg (Turbo OTC)",  callback_data="exp_5s"),
         InlineKeyboardButton("⚡ 10 Seg (Turbo OTC)", callback_data="exp_10s")],
        [InlineKeyboardButton("🟢 1 Minuto",           callback_data="exp_1m"),
         InlineKeyboardButton("🕐 5 Minutos",          callback_data="exp_5m")],
        [InlineKeyboardButton("🕒 15 Minutos",         callback_data="exp_15m"),
         InlineKeyboardButton("🕑 1h 45 Minutos",      callback_data="exp_1h45")],
        [InlineKeyboardButton("◀ Menu",                callback_data="menu")],
    ])

def teclado_ativos(grupo: str) -> InlineKeyboardMarkup:
    ativos = ATIVOS_MERCADO if grupo == "mercado" else ATIVOS_OTC
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
#  PROCESSAR SINAL + GRAFICO (v4.0 — passa dados de estrategia)
# ══════════════════════════════════════════════════════════════
async def processar_sinal(bot, chat_id: int, ativo: str, via_callback=False):
    info  = TODOS_ATIVOS.get(ativo, {})
    nome  = info.get("nome", ativo)
    tipo  = info.get("tipo", "mercado")
    exp   = get_exp(chat_id)

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
        texto  = formatar_sinal(nome, result, tipo)

        # Gerar grafico com dados das estrategias
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

        tf  = result.get("timeframe_ideal", "M1")
        tend= result.get("tipo_tendencia",  "NEUTRO")

        if buf:
            caption = (
                f"{result['emoji']} {result['direction']} — {nome}\n"
                f"Score: {result['score']}/20 | {result['confianca']}\n"
                f"Preco: {result['price']} | TF: {tf} | {tend}\n"
                f"Estrategias: Rev{result['score_reversao']:+d} "
                f"Fib{result['score_fibonacci']:+d} "
                f"LTA/B{result['score_lta_ltb']:+d} "
                f"FakeOut{result['score_fakeout']:+d} "
                f"PB{result['score_pullback']:+d}"
            )
            await enviar_foto(bot, chat_id, buf, caption=caption, teclado=teclado_voltar())
            await enviar(bot, chat_id, texto, teclado=teclado_voltar())
        else:
            await enviar(bot, chat_id, texto, teclado=teclado_voltar())

        logger.info(f"Sinal v4: {nome} | {result['direction']} | score={result['score']}/20 | TF={tf}")

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
        await enviar(context.bot, chat_id, "⏳ A aguardar dados...\nVerifica a ligacao ao WebSocket.")
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
            f"⚪ Sem sinais fortes agora (score min: {MIN_SCORE_ALERTA}/20)\n"
            f"Hora: {hora_corretora()}"
        )
        return

    for ativo, r in top:
        await processar_sinal(context.bot, chat_id, ativo)
        await asyncio.sleep(1)


# ══════════════════════════════════════════════════════════════
#  SCAN ESPECIAL — filtra por estrategia
# ══════════════════════════════════════════════════════════════
async def scan_por_estrategia(bot, chat_id: int, estrategia: str):
    """
    Faz scan de todos os ativos e filtra pelo score de uma estrategia especifica.
    estrategia: 'tendencia' | 'reversao' | 'fibonacci' | 'pullback'
    """
    prontos = ativos_prontos()
    if not prontos:
        await enviar(bot, chat_id, "⏳ Sem dados suficientes ainda.")
        return

    campo_map = {
        "tendencia":  "score_lta_ltb",
        "reversao":   "score_reversao",
        "fibonacci":  "score_fibonacci",
        "pullback":   "score_pullback",
    }
    campo = campo_map.get(estrategia, "score")

    nomes_map = {
        "tendencia": "📈 LTA / LTB",
        "reversao":  "🔄 Reversao",
        "fibonacci": "📐 Fibonacci",
        "pullback":  "↩ Pullback",
    }
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
            f"{nome_est}\n\nSem sinais de {estrategia} neste momento.",
            teclado=teclado_voltar()
        )
        return

    resultados.sort(key=lambda x: abs(x[2]), reverse=True)
    linhas = [f"🔎 SCAN — {nome_est}\n{'='*28}"]
    for ativo, r, v in resultados[:8]:
        info = TODOS_ATIVOS.get(ativo, {})
        nome = info.get("nome", ativo)
        dir_icon = "🟢" if r["direction"] == "CALL" else ("🔴" if r["direction"] == "PUT" else "⚪")
        tf = r.get("timeframe_ideal", "M1")
        linhas.append(
            f"{dir_icon} {nome}  |  {r['direction']}  |  Score: {v:+d}  |  TF: {tf}"
        )

    linhas.append(f"\n{'='*28}\nHora: {hora_corretora()}")
    await enviar(bot, chat_id, "\n".join(linhas), teclado=teclado_voltar())


# ══════════════════════════════════════════════════════════════
#  COMANDOS /start /menu /top /scan /status
# ══════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuarios_ativos.add(chat_id)
    texto = (
        "🚀 POCKET SIGNAL PRO v4.0\n\n"
        "Bem-vindo! Agora com:\n"
        "  📈 LTA / LTB\n"
        "  🔄 Reversao confirmada\n"
        "  📐 Retracao Fibonacci\n"
        "  ⚡ Falso Rompimento (Fakeout)\n"
        "  ↩ Pullback para EMA\n"
        "  🕐 Timeframe ideal: M1/M5/M15\n\n"
        "Score maximo: 20 pontos\n\n"
        "Escolhe uma opcao:"
    )
    await update.message.reply_text(texto, reply_markup=teclado_principal())

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    usuarios_ativos.add(chat_id)
    texto   = f"POCKET SIGNAL PRO v4.0\nHora: {hora_corretora()}\n\nMenu principal:"
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
        msg = "⏳ Sem dados suficientes ainda.\nAguarda 30-60 seg e tenta novamente."
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
    top5 = resultados[:5]

    linhas = [f"⚡ TOP SINAIS AGORA\n{'='*28}"]
    for ativo, r in top5:
        info = TODOS_ATIVOS.get(ativo, {})
        nome = info.get("nome", ativo)
        dir_icon = "🟢" if r["direction"] == "CALL" else ("🔴" if r["direction"] == "PUT" else "⚪")
        tf   = r.get("timeframe_ideal", "M1")
        tend = r.get("tipo_tendencia", "")
        linhas.append(
            f"{dir_icon} {nome}\n"
            f"   Score: {r['score']}/20 | TF: {tf} | {tend}\n"
            f"   {r['confianca']}"
        )
    linhas.append(f"\n{'='*28}\nHora: {hora_corretora()}")

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
        msg = "⏳ Sem dados suficientes ainda."
        if update.message:
            await update.message.reply_text(msg, reply_markup=teclado_voltar())
        else:
            await enviar(context.bot, chat_id, msg, teclado_voltar())
        return

    calls, puts, neutros = [], [], []
    for ativo in prontos:
        try:
            r = gerar_sinal(ativo, exp)
            info = TODOS_ATIVOS.get(ativo, {})
            nome = info.get("nome", ativo)
            tf   = r.get("timeframe_ideal", "M1")
            tend = r.get("tipo_tendencia", "")
            linha = f"  {nome} | {r['score']:+d}/20 | TF:{tf} | {tend}"
            if r["direction"] == "CALL":
                calls.append((r["score"], linha))
            elif r["direction"] == "PUT":
                puts.append((r["score"], linha))
            else:
                neutros.append(linha)
        except Exception:
            pass

    calls.sort(reverse=True)
    puts.sort()

    linhas = [f"🔍 SCAN COMPLETO — {len(prontos)} ativos\n{'='*28}"]
    if calls:
        linhas.append(f"\n🟢 CALL ({len(calls)})")
        linhas.extend(l for _, l in calls)
    if puts:
        linhas.append(f"\n🔴 PUT ({len(puts)})")
        linhas.extend(l for _, l in puts)
    if neutros:
        linhas.append(f"\n⚪ NEUTRO ({len(neutros)})")
        linhas.extend(neutros[:5])
    linhas.append(f"\n{'='*28}\nHora: {hora_corretora()}")

    texto = "\n".join(linhas)
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_voltar())
    else:
        await enviar(context.bot, chat_id, texto, teclado_voltar())

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ws_client
    prontos     = ativos_prontos()
    ws_ok       = ws_client.connected if ws_client else False
    alerta_ativo= update.effective_chat.id in jobs_ativos
    exp_lbl     = EXPIRACOES[get_exp(update.effective_chat.id)]["label"]

    texto = (
        f"📶 ESTADO DO BOT v4.0\n{'='*28}\n\n"
        f"WebSocket OTC:    {'✅ Ligado' if ws_ok else '❌ Desligado'}\n"
        f"Ativos prontos:   {len(prontos)}/{len(TODOS_ATIVOS)}\n"
        f"Alertas auto:     {'✅ Activos' if alerta_ativo else '❌ Inactivos'}\n"
        f"Expiracao:        {exp_lbl}\n"
        f"Score minimo:     {MIN_SCORE_ALERTA}/20\n"
        f"Hora (GMT+1):     {hora_corretora()}\n\n"
        f"Estrategias:      v4.0\n"
        f"  • Reversao\n"
        f"  • Fibonacci\n"
        f"  • LTA / LTB\n"
        f"  • Falso Rompimento\n"
        f"  • Pullback\n"
        f"  • Timeframe M1/M5/M15"
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
            f"Score minimo: {MIN_SCORE_ALERTA}/20\n\n"
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
            f"Hora (GMT+1): {hora_corretora()}\n"
            f"Intervalo: {_label_int}\n"
            f"Expiracao: {exp_lbl}\n"
            f"Score minimo: {MIN_SCORE_ALERTA}/20\n\n"
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
        "POCKET SIGNAL PRO v4.0 — AJUDA\n"
        "================================\n\n"
        "ESTRATEGIAS:\n"
        "  📈 LTA/LTB  — Linha de Tendencia\n"
        "  🔄 Reversao — Sobrecompra/Sobrevenda\n"
        "  📐 Fibonacci — Retracao 38/50/61%\n"
        "  ⚡ Fakeout  — Falso Rompimento\n"
        "  ↩ Pullback  — Recuo para EMA\n\n"
        "TIMEFRAME:\n"
        "  ⚡M1  — baixa volatilidade\n"
        "  🕐M5  — volatilidade media\n"
        "  🕒M15 — alta volatilidade\n"
        "  ⏸ AGUARDA — mercado lateral\n\n"
        "SCORE: maximo 20 pontos\n"
        "  >= 5  — sinal emitido\n"
        "  >= 8  — confianca alta\n"
        "  >= 12 — confianca maxima\n\n"
        "COMANDOS:\n"
        "/start     — Iniciar\n"
        "/menu      — Menu principal\n"
        "/top       — Top sinais agora\n"
        "/scan      — Scan completo\n"
        "/auto      — Alertas + graficos\n"
        "/parar     — Parar alertas\n"
        "/status    — Estado do bot\n"
        "/expiracao — Mudar expiracao\n\n"
        "⚠ Testa SEMPRE na DEMO primeiro!"
    )
    if update.message:
        await update.message.reply_text(texto, reply_markup=teclado_principal())
    else:
        await enviar(context.bot, update.effective_chat.id, texto, teclado_principal())


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

    elif data == "lista_mercado":
        texto = f"📊 MERCADO ABERTO\n{len(ATIVOS_MERCADO)} ativos disponiveis\n\nEscolhe:"
        try:
            await query.edit_message_text(texto, reply_markup=teclado_ativos("mercado"))
        except Exception:
            await enviar(context.bot, chat_id, texto, teclado_ativos("mercado"))

    elif data == "lista_otc":
        texto = f"🌙 OTC (Pocket Option)\n{len(ATIVOS_OTC)} ativos disponiveis\n\nEscolhe:"
        try:
            await query.edit_message_text(texto, reply_markup=teclado_ativos("otc"))
        except Exception:
            await enviar(context.bot, chat_id, texto, teclado_ativos("otc"))

    elif data.startswith("exp_"):
        exp_key = data.replace("exp_", "")
        if exp_key in EXPIRACOES:
            expiracao_usuario[chat_id] = exp_key
            exp_lbl = EXPIRACOES[exp_key]["label"]
            texto = f"✅ Expiracao alterada: {exp_lbl}\n\nEscolhe uma opcao:"
            try:
                await query.edit_message_text(texto, reply_markup=teclado_principal())
            except Exception:
                await enviar(context.bot, chat_id, texto, teclado_principal())

    elif data == "scan_tendencia":
        await scan_por_estrategia(context.bot, chat_id, "tendencia")
    elif data == "scan_reversao":
        await scan_por_estrategia(context.bot, chat_id, "reversao")
    elif data == "scan_fibonacci":
        await scan_por_estrategia(context.bot, chat_id, "fibonacci")
    elif data == "scan_pullback":
        await scan_por_estrategia(context.bot, chat_id, "pullback")

    elif data == "top":       await top_cmd(update, context)
    elif data == "scan":      await scan_cmd(update, context)
    elif data == "auto":      await auto_cmd(update, context)
    elif data == "status":    await status_cmd(update, context)
    elif data == "expiracao": await expiracao_cmd(update, context)
    elif data == "help":      await help_cmd(update, context)
    elif data == "menu":      await menu_cmd(update, context)


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
def main():
    global ws_client

    print("=" * 56)
    print("   POCKET SIGNAL PRO v4.0 — A INICIAR...")
    print("=" * 56)

    # 1. Login Pocket Option (OTC)
    print(f"\n Passo 1: Login na Pocket Option...")
    try:
        sessao    = fazer_login(POCKET_EMAIL, POCKET_PASSWORD)
        ws_client = PocketOptionWS(sessao)
        print(f" ✅ Login bem-sucedido!")
    except Exception as e:
        print(f" ❌ ERRO no login: {e}")
        sys.exit(1)

    # 2. Yahoo Finance (mercado)
    print(f"\n Passo 2: A carregar dados Yahoo Finance...")
    iniciar_yahoo_mercado()
    print(f" ✅ Yahoo Finance iniciado em background!")

    # 3. Bot Telegram
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("menu",       menu_cmd))
    app.add_handler(CommandHandler("top",        top_cmd))
    app.add_handler(CommandHandler("scan",       scan_cmd))
    app.add_handler(CommandHandler("auto",       auto_cmd))
    app.add_handler(CommandHandler("parar",      parar_cmd))
    app.add_handler(CommandHandler("status",     status_cmd))
    app.add_handler(CommandHandler("expiracao",  expiracao_cmd))
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    hora = hora_corretora()
    print(f"\n Passo 3: Bot Telegram iniciado!")
    print(f"\n Hora (GMT+1)     : {hora}")
    print(f" Mercado (Yahoo)  : {len(ATIVOS_MERCADO)} ativos")
    print(f" OTC (Pocket)     : {len(ATIVOS_OTC)} ativos")
    print(f" Alertas cada     : {INTERVALO_ALERTAS} minutos")
    print(f" Score minimo     : {MIN_SCORE_ALERTA}/20")
    print(f" Estrategias      : Reversao | Fibonacci | LTA/LTB | Fakeout | Pullback")
    print(f" Timeframes       : M1 / M5 / M15 (deteccao automatica)")
    print(f" Graficos         : ACTIVOS (com overlays)")
    print("=" * 56)

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
