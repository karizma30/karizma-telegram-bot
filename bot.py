import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
TIMEZONE = ZoneInfo("Asia/Tehran")


# =========================================================
# Database
# =========================================================

def get_connection():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wakeups (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                name TEXT,
                wake_date DATE NOT NULL,
                wake_time TIME NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)

        conn.commit()


def save_wakeup(telegram_id, name):
    now = datetime.now(TIMEZONE)

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO wakeups
            (telegram_id, name, wake_date, wake_time, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            telegram_id,
            name,
            now.date(),
            now.time(),
            now,
        ))

        conn.commit()

    return now


# =========================================================
# Personal Report
# =========================================================

def get_personal_report(telegram_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                wake_date::text,
                wake_time::text
            FROM wakeups
            WHERE telegram_id = %s
            ORDER BY id DESC
        """, (telegram_id,)).fetchall()

    return rows


# =========================================================
# Weekly Report
# =========================================================

def get_weekly_report(telegram_id):
    today = datetime.now(TIMEZONE).date()
    start_date = today - timedelta(days=6)

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                wake_date::text,
                wake_time::text
            FROM wakeups
            WHERE telegram_id = %s
            AND wake_date >= %s
            AND wake_date <= %s
            ORDER BY wake_date ASC, wake_time ASC
        """, (
            telegram_id,
            start_date,
            today,
        )).fetchall()

    return rows


# =========================================================
# /start
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        ["🌅 بیدار شدم"],
        ["📊 گزارش من", "📅 گزارش هفتگی"],
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.effective_chat.send_message(
        text=(
            "🌟 به ربات کاریزما خوش آمدی!\n\n"
            "برای ثبت ساعت بیدار شدنت روی دکمه زیر بزن:"
        ),
        reply_markup=reply_markup
    )


# =========================================================
# Wake Up
# =========================================================

async def wakeup(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    now = save_wakeup(
        user.id,
        user.full_name
    )

    await update.effective_chat.send_message(
        text=(
            f"✅ ساعت بیداری ثبت شد!\n\n"
            f"👤 {user.full_name}\n"
            f"🌅 ساعت: {now.strftime('%H:%M:%S')}\n"
            f"📅 تاریخ: {now.strftime('%Y-%m-%d')}\n\n"
            f"آفرین! روزت رو قدرتمند شروع کن 💪"
        )
    )


# =========================================================
# Personal Report
# =========================================================

async def personal_report(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    rows = get_personal_report(user.id)

    if not rows:
        await update.effective_chat.send_message(
            text=(
                "📊 هنوز هیچ ساعت بیداری برای شما ثبت نشده است.\n\n"
                "ابتدا روی دکمه 🌅 بیدار شدم بزن."
            )
        )
        return

    total = len(rows)

    latest_date, latest_time = rows[0]

    # Calculate average wake-up time
    total_seconds = 0

    for wake_date, wake_time in rows:
        try:
            hour, minute, second = map(
                int,
                wake_time.split(":")
            )

            total_seconds += (
                hour * 3600
                + minute * 60
                + second
            )

        except ValueError:
            pass

    average_seconds = total_seconds // total

    avg_hour = average_seconds // 3600

    avg_minute = (
        average_seconds % 3600
    ) // 60

    await update.effective_chat.send_message(
        text=(
            f"📊 گزارش بیداری شما\n\n"
            f"👤 {user.full_name}\n"
            f"🔢 تعداد ثبت‌ها: {total}\n"
            f"🌅 آخرین بیداری: {latest_time}\n"
            f"📅 تاریخ آخرین ثبت: {latest_date}\n"
            f"⏰ میانگین ساعت بیداری: "
            f"{avg_hour:02d}:{avg_minute:02d}\n\n"
            f"💪 ادامه بده؛ نظم روزانه یعنی پیشرفت!"
        )
    )


# =========================================================
# Weekly Report
# =========================================================

async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    rows = get_weekly_report(user.id)

    if not rows:
        await update.effective_chat.send_message(
            text=(
                "📅 در ۷ روز گذشته هیچ ثبت بیداری‌ای ندارید.\n\n"
                "از فردا شروع کن و هر روز ساعت بیدار شدنت را ثبت کن 🌅"
            )
        )
        return

    today = datetime.now(TIMEZONE).date()

    start_date = today - timedelta(days=6)

    days_registered = len(
        set(row[0] for row in rows)
    )

    total_seconds = 0

    for wake_date, wake_time in rows:
        try:
            hour, minute, second = map(
                int,
                wake_time.split(":")
            )

            total_seconds += (
                hour * 3600
                + minute * 60
                + second
            )

        except ValueError:
            pass

    average_seconds = (
        total_seconds // len(rows)
    )

    avg_hour = average_seconds // 3600

    avg_minute = (
        average_seconds % 3600
    ) // 60

    report_lines = []

    for wake_date, wake_time in rows:

        report_lines.append(
            f"🌅 {wake_date} → {wake_time}"
        )

    report_text = "\n".join(
        report_lines
    )

    await update.effective_chat.send_message(
        text=(
            f"📅 گزارش هفتگی بیداری\n\n"
            f"از {start_date.strftime('%Y-%m-%d')} "
            f"تا {today.strftime('%Y-%m-%d')}\n\n"
            f"📈 تعداد ثبت‌ها: {len(rows)}\n"
            f"📆 تعداد روزهای ثبت‌شده: "
            f"{days_registered} از ۷ روز\n"
            f"⏰ میانگین ساعت بیداری: "
            f"{avg_hour:02d}:{avg_minute:02d}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"{report_text}\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"🎯 هدف کاریزما: نظم بیشتر، پیشرفت بیشتر!"
        )
    )


# =========================================================
# Message Handler
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message or not update.message.text:
        return

    text = update.message.text

    if text == "🌅 بیدار شدم":

        await wakeup(
            update,
            context
        )

    elif text == "📊 گزارش من":

        await personal_report(
            update,
            context
        )

    elif text == "📅 گزارش هفتگی":

        await weekly_report(
            update,
            context
        )

    else:

        await update.effective_chat.send_message(
            text="لطفاً یکی از گزینه‌های منو را انتخاب کن 👇"
        )


# =========================================================
# Render Health Server
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"Karizma Bot is running"
        )

    def log_message(self, format, *args):
        pass


def start_web_server():

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"Health server started on port {port}"
    )

    server.serve_forever()


# =========================================================
# Main
# =========================================================

def main():

    # Initialize PostgreSQL database
    init_db()

    # Start HTTP server for Render
    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

    # Telegram application
    # Increased timeouts for Render/Telegram connection
    application = (
        Application
        .builder()
        .token(TOKEN)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(30)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "report",
            personal_report
        )
    )

    application.add_handler(
        CommandHandler(
            "weekly",
            weekly_report
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        "Karizma30_bot started..."
    )

    application.run_polling()


# =========================================================
# Run
# =========================================================

if __name__ == "__main__":
    main()
