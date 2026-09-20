import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]
DB_FILE = "karizma_wakeup.db"
TIMEZONE = ZoneInfo("Asia/Tehran")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wakeups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            name TEXT,
            wake_date TEXT NOT NULL,
            wake_time TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_wakeup(telegram_id, name):
    now = datetime.now(TIMEZONE)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO wakeups
        (telegram_id, name, wake_date, wake_time, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        telegram_id,
        name,
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        now.isoformat(),
    ))

    conn.commit()
    conn.close()

    return now


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["🌅 بیدار شدم"],
        ["📊 گزارش من", "📅 گزارش هفتگی"],
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "🌟 به ربات کاریزما خوش آمدی!\n\n"
        "برای ثبت ساعت بیدار شدنت روی دکمه زیر بزن:",
        reply_markup=reply_markup
    )


async def wakeup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    now = save_wakeup(
        user.id,
        user.full_name
    )

    await update.message.reply_text(
        f"✅ ساعت بیداری ثبت شد!\n\n"
        f"👤 {user.full_name}\n"
        f"🌅 ساعت: {now.strftime('%H:%M:%S')}\n"
        f"📅 تاریخ: {now.strftime('%Y-%m-%d')}\n\n"
        f"آفرین! روزت رو قدرتمند شروع کن 💪"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🌅 بیدار شدم":
        await wakeup(update, context)
    else:
        await update.message.reply_text(
            "برای ثبت ساعت بیداری روی دکمه «🌅 بیدار شدم» بزن."
        )


def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("Karizma30_bot started...")

    application.run_polling()


if __name__ == "__main__":
    main()
