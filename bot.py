import os
import json
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")


DATA_FILE = "gastos.json"
BUDGET = 500_000

CATS = ["🛒 Supermercado", "🍔 Restaurantes", "🚌 Transporte", "🎬 Entretenimiento", "⛽ Bencina"]

ASK_DESC, ASK_AMOUNT, ASK_CAT = range(3)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def month_key():
    return datetime.now().strftime("%Y-%m")

def month_label(key=None):
    if key is None:
        key = month_key()
    y, m = key.split("-")
    meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
             "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    return f"{meses[int(m)-1]} {y}"

def get_expenses(data, uid, mk=None):
    if mk is None:
        mk = month_key()
    return data.get(str(uid), {}).get(mk, [])

def save_expense(data, uid, expense):
    uid = str(uid)
    mk  = month_key()
    if uid not in data:
        data[uid] = {}
    if mk not in data[uid]:
        data[uid][mk] = []
    data[uid][mk].append(expense)
    save_data(data)

def total_of(expenses):
    return sum(e["amount"] for e in expenses)

def cat_totals(expenses):
    totals = {}
    for e in expenses:
        totals[e["cat"]] = totals.get(e["cat"], 0) + e["amount"]
    return totals

def fmt(n):
    return f"${n:,.0f}".replace(",", ".")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hola {name}! Soy tu bot de presupuesto.\n\n"
        f"Te ayudo a controlar tus gastos mensuales con un límite de *{fmt(BUDGET)} CLP*.\n\n"
        f"*Comandos disponibles:*\n"
        f"💸 /gasto — registrar un gasto\n"
        f"📊 /reporte — ver resumen del mes\n"
        f"📅 /historial — ver meses anteriores\n"
        f"❌ /cancelar — cancelar lo que estés haciendo",
        parse_mode="Markdown"
    )

async def gasto_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💸 *Nuevo gasto*\n\n¿En qué gastaste?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_DESC

async def ask_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["desc"] = update.message.text.strip()
    await update.message.reply_text(
        f"✏️ _{ctx.user_data['desc']}_\n\n¿Cuánto gastaste? (solo el número)",
        parse_mode="Markdown"
    )
    return ASK_AMOUNT

async def ask_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(".", "").replace(",", "").replace("$", "")
    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Solo el número, sin puntos ni símbolos. Ej: *15000*", parse_mode="Markdown")
        return ASK_AMOUNT
    ctx.user_data["amount"] = amount
    keyboard = [[cat] for cat in CATS]
    await update.message.reply_text(
        f"✏️ _{ctx.user_data['desc']}_ — *{fmt(amount)}*\n\n¿En qué categoría?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_CAT

async def save_gasto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cat_raw = update.message.text.strip()
    cat = next((c for c in CATS if c == cat_raw or c.split(" ", 1)[1] == cat_raw), None)
    if not cat:
        keyboard = [[c] for c in CATS]
        await update.message.reply_text(
            "⚠️ Elige una categoría de la lista:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ASK_CAT
    expense = {
        "desc":   ctx.user_data["desc"],
        "amount": ctx.user_data["amount"],
        "cat":    cat,
        "date":   datetime.now().isoformat()
    }
    data = load_data()
    save_expense(data, update.effective_user.id, expense)
    expenses = get_expenses(data, update.effective_user.id)
    spent    = total_of(expenses)
    rem      = BUDGET - spent
    pct      = (spent / BUDGET) * 100
    bar      = build_bar(pct)
    if rem < 0:
        status = f"🚨 *¡Superaste el presupuesto!* Te pasaste por {fmt(abs(rem))}"
    elif pct >= 85:
        status = f"⚠️ Casi al límite — te quedan *{fmt(rem)}*"
    elif pct >= 60:
        status = f"🟡 Vas bien — te quedan *{fmt(rem)}*"
    else:
        status = f"✅ Vas bien — te quedan *{fmt(rem)}*"
    await update.message.reply_text(
        f"✅ *Gasto registrado*\n\n"
        f"📝 {expense['desc']}\n"
        f"{cat} — *{fmt(expense['amount'])}*\n\n"
        f"{bar} {pct:.0f}%\n"
        f"Gastado: *{fmt(spent)}* / {fmt(BUDGET)}\n\n"
        f"{status}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def reporte(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data     = load_data()
    uid      = update.effective_user.id
    expenses = get_expenses(data, uid)
    mk       = month_key()
    if not expenses:
        await update.message.reply_text(
            f"📊 No tienes gastos en *{month_label(mk)}*.\n\nUsa /gasto para agregar uno.",
            parse_mode="Markdown"
        )
        return
    spent  = total_of(expenses)
    rem    = BUDGET - spent
    pct    = (spent / BUDGET) * 100
    bar    = build_bar(pct)
    totals = cat_totals(expenses)
    lines  = [f"📊 *Reporte — {month_label(mk)}*\n"]
    lines.append(f"{bar} *{pct:.1f}%*")
    lines.append(f"💸 Gastado: *{fmt(spent)}* de {fmt(BUDGET)}")
    if rem >= 0:
        lines.append(f"✅ Disponible: *{fmt(rem)}*\n")
    else:
        lines.append(f"🚨 Exceso: *{fmt(abs(rem))}*\n")
    lines.append("*Por categoría:*")
    for cat, amt in sorted(totals.items(), key=lambda x: -x[1]):
        cat_pct = (amt / spent * 100) if spent else 0
        lines.append(f"{cat}: *{fmt(amt)}* ({cat_pct:.0f}%)")
    lines.append(f"\n_{len(expenses)} gastos registrados_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def historial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data      = load_data()
    uid       = str(update.effective_user.id)
    user_data = data.get(uid, {})
    months    = sorted(user_data.keys(), reverse=True)
    cur_mk    = month_key()
    if not months or (len(months) == 1 and months[0] == cur_mk):
        await update.message.reply_text(
            "📅 Aún no tienes historial de meses anteriores.",
            parse_mode="Markdown"
        )
        return
    lines = ["📅 *Historial de meses*\n"]
    for mk in months:
        expenses = user_data[mk]
        spent    = total_of(expenses)
        pct      = (spent / BUDGET) * 100
        flag     = " ← mes actual" if mk == cur_mk else ""
        status   = "🚨" if pct > 100 else "⚠️" if pct >= 85 else "✅"
        lines.append(f"{status} *{month_label(mk)}*{flag}")
        lines.append(f"   {fmt(spent)} ({pct:.0f}%) — {len(expenses)} gastos\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "No entendí ese mensaje. Usa:\n"
        "💸 /gasto — registrar un gasto\n"
        "📊 /reporte — ver el resumen\n"
        "📅 /historial — ver meses anteriores"
    )

def build_bar(pct, length=10):
    filled = round(min(pct, 100) / 100 * length)
    return "█" * filled + "░" * (length - filled)

def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("gasto", gasto_start)],
        states={
            ASK_DESC:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_cat)],
            ASK_CAT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, save_gasto)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reporte", reporte))
    app.add_handler(CommandHandler("historial", historial))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    logger.info("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()
