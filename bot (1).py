#!/usr/bin/env python3
"""
Bot de Telegram para gestión de apuestas deportivas.
Versión: 2.0.0 — Añadido Sistema Rico / Sistema Capi
"""

import json
import os
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── Configuración ────────────────────────────────────────────────────────────
TOKEN = "7940549617:AAHNpPvqTwqB-1qb823P8z99o85F7qcp5T8"
DATA_FILE = "data.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SEPARATOR = "━━━━━━━━━━━━━━━━━━━"

# Clave para guardar apuesta pendiente en context.user_data
PENDING_KEY = "apuesta_pendiente"


# ─── Persistencia JSON ────────────────────────────────────────────────────────

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"bank": None, "apuestas": []}


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def migrar_sistema(data: dict) -> dict:
    """
    Migración silenciosa: asigna 'sistema': 'Rico' a todas las apuestas
    que no tengan ese campo. Se ejecuta al arrancar el bot.
    """
    modificado = False
    for ap in data.get("apuestas", []):
        if "sistema" not in ap:
            ap["sistema"] = "Rico"
            modificado = True
    if modificado:
        save_data(data)
        logger.info("Migración completada: apuestas antiguas asignadas a Sistema Rico.")
    return data


# ─── Helpers de formato ───────────────────────────────────────────────────────

def fmt_eur(valor: float) -> str:
    signo = "+" if valor >= 0 else ""
    return f"{signo}{valor:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_bank(valor: float) -> str:
    return f"{valor:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(valor: float) -> str:
    signo = "+" if valor >= 0 else ""
    return f"{signo}{valor:.1f}%"


# ─── Cálculo de estadísticas ──────────────────────────────────────────────────

def calcular_stats_sistema(apuestas: list, sistema: str | None = None) -> dict:
    """
    Calcula estadísticas para un sistema concreto ('Rico' o 'Capi')
    o para el total si sistema=None.
    """
    hoy = date.today()
    mes_actual = (hoy.year, hoy.month)

    filtradas = [ap for ap in apuestas if sistema is None or ap.get("sistema") == sistema]

    balance_hoy = 0.0
    balance_mes = 0.0
    ganadas = 0
    total = len(filtradas)
    total_apostado = 0.0
    beneficio_neto = 0.0
    racha_actual = 0
    racha_tipo = None

    for ap in filtradas:
        ts = datetime.fromisoformat(ap["timestamp"])
        beneficio = ap["beneficio"]

        if ts.date() == hoy:
            balance_hoy += beneficio
        if (ts.year, ts.month) == mes_actual:
            balance_mes += beneficio

        if ap["resultado"] == "ganada":
            ganadas += 1
        total_apostado += ap["cantidad"]
        beneficio_neto += beneficio

    if filtradas:
        ultimo = filtradas[-1]["resultado"]
        racha_tipo = ultimo
        for ap in reversed(filtradas):
            if ap["resultado"] == ultimo:
                racha_actual += 1
            else:
                break

    pct_acierto = (ganadas / total * 100) if total > 0 else 0.0
    roi = (beneficio_neto / total_apostado * 100) if total_apostado > 0 else 0.0

    return {
        "balance_hoy": balance_hoy,
        "balance_mes": balance_mes,
        "racha_actual": racha_actual,
        "racha_tipo": racha_tipo,
        "pct_acierto": pct_acierto,
        "roi": roi,
        "total": total,
        "ganadas": ganadas,
        "beneficio_neto": beneficio_neto,
    }


def racha_str(s: dict) -> str:
    if s["racha_tipo"] == "ganada":
        n = s["racha_actual"]
        return f"🔥 {n} victoria{'s' if n != 1 else ''} seguida{'s' if n != 1 else ''}"
    elif s["racha_tipo"] == "perdida":
        n = s["racha_actual"]
        return f"❄️ {n} derrota{'s' if n != 1 else ''} seguida{'s' if n != 1 else ''}"
    return "Sin apuestas aún"


def bloque_sistema(titulo: str, emoji: str, bank: float, s: dict) -> list:
    return [
        SEPARATOR,
        f"{emoji} <b>{titulo}</b>",
        SEPARATOR,
        f"💰 Bank: <b>{fmt_bank(bank)}</b>",
        f"📈 Hoy: <b>{fmt_eur(s['balance_hoy'])}</b>",
        f"📅 Mes: <b>{fmt_eur(s['balance_mes'])}</b>",
        f"🔥 Racha: <b>{racha_str(s)}</b>",
        f"🎯 Acierto: <b>{s['pct_acierto']:.1f}%</b>  ({s['ganadas']}/{s['total']})",
        f"📊 ROI: <b>{fmt_pct(s['roi'])}</b>",
    ]


def texto_stats(data: dict) -> str:
    apuestas = data.get("apuestas", [])
    bank_total = data.get("bank", 0.0) or 0.0

    s_rico = calcular_stats_sistema(apuestas, "Rico")
    s_capi = calcular_stats_sistema(apuestas, "Capi")
    s_total = calcular_stats_sistema(apuestas, None)

    # Bank por sistema = bank_total ajustado por beneficio neto de cada sistema
    # (el bank total ya incluye todo; desglosamos por beneficio neto)
    beneficio_rico = s_rico["beneficio_neto"]
    beneficio_capi = s_capi["beneficio_neto"]
    bank_base = bank_total - beneficio_rico - beneficio_capi  # bank inicial aproximado
    bank_rico = bank_base / 2 + beneficio_rico if bank_base > 0 else beneficio_rico
    bank_capi = bank_base / 2 + beneficio_capi if bank_base > 0 else beneficio_capi

    lines = []
    lines += bloque_sistema("SISTEMA RICO", "🔵", bank_rico, s_rico)
    lines += [""]
    lines += bloque_sistema("SISTEMA CAPI", "🟡", bank_capi, s_capi)
    lines += [
        "",
        SEPARATOR,
        "📊 <b>TOTAL COMBINADO</b>",
        SEPARATOR,
        f"💰 Bank total: <b>{fmt_bank(bank_total)}</b>",
        f"📈 Hoy: <b>{fmt_eur(s_total['balance_hoy'])}</b>",
        f"📅 Mes: <b>{fmt_eur(s_total['balance_mes'])}</b>",
        f"🎯 Acierto global: <b>{s_total['pct_acierto']:.1f}%</b>  ({s_total['ganadas']}/{s_total['total']})",
        f"📊 ROI global: <b>{fmt_pct(s_total['roi'])}</b>",
        SEPARATOR,
    ]
    return "\n".join(lines)


# ─── Handlers de comandos ─────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if data["bank"] is None:
        msg = (
            "👋 ¡Bienvenido al <b>Bot de Apuestas</b>!\n\n"
            "Para empezar, establece tu bank inicial:\n"
            "<code>/setbank 1000</code>\n\n"
            "Usa /ayuda para ver todos los comandos disponibles."
        )
    else:
        msg = (
            f"👋 ¡Hola de nuevo!\n\n"
            f"💰 Tu bank actual es <b>{fmt_bank(data['bank'])}</b>\n\n"
            "Usa /ayuda para ver todos los comandos disponibles."
        )
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_setbank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) != 1:
        await update.message.reply_text(
            "⚠️ Uso correcto: <code>/setbank &lt;cantidad&gt;</code>\nEjemplo: <code>/setbank 1000</code>",
            parse_mode="HTML",
        )
        return

    try:
        cantidad = float(args[0].replace(",", "."))
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ La cantidad debe ser un número positivo.", parse_mode="HTML")
        return

    data = load_data()
    data["bank"] = cantidad
    save_data(data)

    await update.message.reply_text(
        f"✅ Bank inicial establecido en <b>{fmt_bank(cantidad)}</b>\n\n"
        "¡Ya puedes registrar apuestas con /apuesta!",
        parse_mode="HTML",
    )


async def cmd_apuesta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()

    if data["bank"] is None:
        await update.message.reply_text(
            "⚠️ Primero debes establecer tu bank con <code>/setbank &lt;cantidad&gt;</code>",
            parse_mode="HTML",
        )
        return

    args = context.args
    if not args or len(args) != 3:
        await update.message.reply_text(
            "⚠️ Uso correcto:\n<code>/apuesta &lt;cuota&gt; &lt;cantidad&gt; &lt;resultado&gt;</code>\n\n"
            "Ejemplo: <code>/apuesta 1.75 50 ganada</code>\n"
            "Resultados válidos: <b>ganada</b> o <b>perdida</b>",
            parse_mode="HTML",
        )
        return

    try:
        cuota = float(args[0].replace(",", "."))
        if cuota <= 1.0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ La cuota debe ser un número mayor que 1.0", parse_mode="HTML")
        return

    try:
        cantidad = float(args[1].replace(",", "."))
        if cantidad <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ La cantidad debe ser un número positivo.", parse_mode="HTML")
        return

    resultado = args[2].lower().strip()
    if resultado not in ("ganada", "perdida"):
        await update.message.reply_text(
            "❌ El resultado solo puede ser <b>ganada</b> o <b>perdida</b>.",
            parse_mode="HTML",
        )
        return

    # Guardar apuesta pendiente en memoria hasta que el usuario elija sistema
    context.user_data[PENDING_KEY] = {
        "cuota": cuota,
        "cantidad": cantidad,
        "resultado": resultado,
    }

    emoji = "✅" if resultado == "ganada" else "❌"
    keyboard = [
        [
            InlineKeyboardButton("🔵 Sistema Rico", callback_data="sistema_Rico"),
            InlineKeyboardButton("🟡 Sistema Capi", callback_data="sistema_Capi"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"{emoji} <b>Apuesta lista para registrar</b>\n\n"
        f"Cuota: <b>{cuota}</b> | Cantidad: <b>{fmt_bank(cantidad)}</b> | {resultado.upper()}\n\n"
        "¿A qué sistema pertenece esta apuesta?",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def callback_sistema(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    sistema = query.data.split("_")[1]  # 'Rico' o 'Capi'

    pending = context.user_data.get(PENDING_KEY)
    if not pending:
        await query.edit_message_text(
            "⚠️ No hay ninguna apuesta pendiente. Usa /apuesta para registrar una nueva.",
            parse_mode="HTML",
        )
        return

    # Limpiar apuesta pendiente
    context.user_data.pop(PENDING_KEY, None)

    cuota = pending["cuota"]
    cantidad = pending["cantidad"]
    resultado = pending["resultado"]

    if resultado == "ganada":
        beneficio = round((cantidad * cuota) - cantidad, 2)
    else:
        beneficio = round(-cantidad, 2)

    data = load_data()
    bank_anterior = data["bank"]
    data["bank"] = round(bank_anterior + beneficio, 2)

    apuesta = {
        "timestamp": datetime.now().isoformat(),
        "cuota": cuota,
        "cantidad": cantidad,
        "resultado": resultado,
        "beneficio": beneficio,
        "bank_resultante": data["bank"],
        "sistema": sistema,
    }
    data["apuestas"].append(apuesta)
    save_data(data)

    emoji_res = "✅" if resultado == "ganada" else "❌"
    emoji_sis = "🔵" if sistema == "Rico" else "🟡"
    signo_ben = "+" if beneficio >= 0 else ""

    msg = (
        f"{emoji_res} <b>Apuesta registrada</b> {emoji_sis} Sistema {sistema}\n"
        f"Cuota: <b>{cuota}</b> | Cantidad: <b>{fmt_bank(cantidad)}</b>\n"
        f"Resultado: <b>{resultado.upper()}</b> | Beneficio: <b>{signo_ben}{fmt_bank(beneficio)}</b>\n\n"
        + texto_stats(data)
    )
    await query.edit_message_text(msg, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if data["bank"] is None:
        await update.message.reply_text(
            "⚠️ Aún no has configurado tu bank. Usa <code>/setbank &lt;cantidad&gt;</code>",
            parse_mode="HTML",
        )
        return
    await update.message.reply_text(texto_stats(data), parse_mode="HTML")


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    apuestas = data.get("apuestas", [])

    if not apuestas:
        await update.message.reply_text("📭 Aún no hay apuestas registradas.")
        return

    ultimas = apuestas[-10:]
    lines = [SEPARATOR, "📋 <b>ÚLTIMAS 10 APUESTAS</b>", SEPARATOR]

    for ap in reversed(ultimas):
        ts = datetime.fromisoformat(ap["timestamp"])
        fecha_str = ts.strftime("%d/%m %H:%M")
        emoji_res = "✅" if ap["resultado"] == "ganada" else "❌"
        sistema = ap.get("sistema", "Rico")
        emoji_sis = "🔵" if sistema == "Rico" else "🟡"
        signo = "+" if ap["beneficio"] >= 0 else ""
        lines.append(
            f"{emoji_res} <b>{fecha_str}</b> {emoji_sis} <b>{sistema}</b>\n"
            f"   Cuota: {ap['cuota']} | Apuesta: {fmt_bank(ap['cantidad'])}\n"
            f"   Resultado: {ap['resultado'].upper()} | {signo}{fmt_bank(ap['beneficio'])}\n"
            f"   Bank: {fmt_bank(ap['bank_resultante'])}"
        )
        lines.append("")

    lines.append(SEPARATOR)
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [
            InlineKeyboardButton("✅ Sí, resetear todo", callback_data="confirm_reset"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel_reset"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚠️ <b>¿Estás seguro?</b>\n\n"
        "Esto eliminará <b>todo el historial</b> de apuestas y el bank actual.\n"
        "Esta acción <b>no se puede deshacer</b>.",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def callback_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_reset":
        save_data({"bank": None, "apuestas": []})
        await query.edit_message_text(
            "🗑️ <b>Reset completado.</b>\n\n"
            "Todos los datos han sido eliminados.\n"
            "Configura tu nuevo bank con <code>/setbank &lt;cantidad&gt;</code>",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("✅ Reset cancelado. Tus datos están seguros.")


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        f"{SEPARATOR}\n"
        "📖 <b>COMANDOS DISPONIBLES</b>\n"
        f"{SEPARATOR}\n\n"
        "🏦 <b>Configuración</b>\n"
        "<code>/setbank &lt;cantidad&gt;</code>\n"
        "   Establece el bank inicial\n\n"
        "🎲 <b>Apuestas</b>\n"
        "<code>/apuesta &lt;cuota&gt; &lt;cantidad&gt; &lt;resultado&gt;</code>\n"
        "   Registra una apuesta\n"
        "   Ejemplo: <code>/apuesta 1.75 50 ganada</code>\n"
        "   ➡️ El bot te pedirá elegir entre 🔵 Sistema Rico o 🟡 Sistema Capi\n\n"
        "📊 <b>Estadísticas</b>\n"
        "<code>/stats</code> → Estadísticas por sistema y total\n"
        "<code>/historial</code> → Últimas 10 apuestas con etiqueta de sistema\n\n"
        "⚙️ <b>Otros</b>\n"
        "<code>/reset</code> → Resetear todos los datos\n"
        "<code>/ayuda</code> → Este mensaje\n\n"
        f"{SEPARATOR}\n"
        "💡 <b>Resultados válidos:</b> <code>ganada</code> | <code>perdida</code>\n"
        "💡 <b>La cuota debe ser mayor que 1.0</b>\n"
        "🔵 <b>Sistema Rico</b> | 🟡 <b>Sistema Capi</b>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Migración silenciosa al arrancar
    data = load_data()
    migrar_sistema(data)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setbank", cmd_setbank))
    app.add_handler(CommandHandler("apuesta", cmd_apuesta))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("historial", cmd_historial))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_reset, pattern="^(confirm|cancel)_reset$"))
    app.add_handler(CallbackQueryHandler(callback_sistema, pattern="^sistema_(Rico|Capi)$"))

    logger.info("Bot v2.0 iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


# =============================================================================
# INSTRUCCIONES DE EJECUCIÓN
# =============================================================================
#
# 1. INSTALAR DEPENDENCIAS:
#    pip install -r requirements.txt
#
# 2. REEMPLAZAR bot.py antiguo por este archivo
#
# 3. EJECUTAR EL BOT:
#    python bot.py
#    → Al arrancar, migrará automáticamente las apuestas antiguas a Sistema Rico
#
# 4. NUEVO FLUJO DE APUESTA:
#    /apuesta 1.75 50 ganada
#    → El bot muestra botones: [🔵 Sistema Rico] [🟡 Sistema Capi]
#    → Pulsas el sistema y se registra con estadísticas completas
#
# 5. DATOS:
#    data.json se mantiene intacto. Solo se añade el campo "sistema" a cada apuesta.
#
# =============================================================================
