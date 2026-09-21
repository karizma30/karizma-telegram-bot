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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS study_reports (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                name TEXT,
                study_date DATE NOT NULL,
                minutes INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)

        conn.commit()


# =========================================================
# Wake Up
# =========================================================

def save_wakeup(telegram_id, name):

    now = datetime.now(TIMEZONE)

    with get_connection() as conn:

        existing = conn.execute("""
            SELECT wake_time
            FROM wakeups
            WHERE telegram_id = %s
              AND wake_date = %s
            ORDER BY id ASC
            LIMIT 1
        """, (
            telegram_id,
            now.date(),
        )).fetchone()

        if existing:
            return now, False, existing[0]

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

    return now, True, now.time()


# =========================================================
# Wake Up Ranking
# =========================================================

def get_today_ranking():

    today = datetime.now(TIMEZONE).date()

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT DISTINCT ON (telegram_id)
                telegram_id,
                name,
                wake_time
            FROM wakeups
            WHERE wake_date = %s
            ORDER BY telegram_id, wake_time ASC, id ASC
        """, (today,)).fetchall()

    rows.sort(key=lambda row: row[2])

    return rows


def get_today_user_rank(telegram_id):

    ranking = get_today_ranking()

    for index, row in enumerate(ranking, start=1):

        if row[0] == telegram_id:
            return index, len(ranking), row[2]

    return None


# =========================================================
# Personal Wake Report
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
# Weekly Wake Report
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
# Study Report
# =========================================================

def save_study_report(telegram_id, name, minutes):

    now = datetime.now(TIMEZONE)

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO study_reports
            (telegram_id, name, study_date, minutes, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            telegram_id,
            name,
            now.date(),
            minutes,
            now,
        ))

        conn.commit()

    return now


# =========================================================
# Today's Study Ranking
# =========================================================

def get_today_study_ranking():

    today = datetime.now(TIMEZONE).date()

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT
                telegram_id,
                MAX(name) AS name,
                SUM(minutes) AS total_minutes
            FROM study_reports
            WHERE study_date = %s
            GROUP BY telegram_id
            ORDER BY total_minutes DESC
        """, (today,)).fetchall()

    return rows


def get_today_study_user(telegram_id):

    ranking = get_today_study_ranking()

    for index, row in enumerate(ranking, start=1):

        if row[0] == telegram_id:

            return (
                index,
                len(ranking),
                row[2]
            )

    return None


def get_personal_today_study(telegram_id):

    today = datetime.now(TIMEZONE).date()

    with get_connection() as conn:

        result = conn.execute("""
            SELECT COALESCE(SUM(minutes), 0)
            FROM study_reports
            WHERE telegram_id = %s
              AND study_date = %s
        """, (
            telegram_id,
            today,
        )).fetchone()

    return result[0] if result else 0


# =========================================================
# Format Minutes
# =========================================================

def format_minutes(minutes):

    hours = minutes // 60
    mins = minutes % 60

    if hours > 0 and mins > 0:

        return f"{hours} ساعت و {mins} دقیقه"

    if hours > 0:

        return f"{hours} ساعت"

    return f"{mins} دقیقه"


# =========================================================
# Parse Study Time
# =========================================================

def parse_study_time(text):

    text = text.strip()

    # Format: 2:30
    if ":" in text:

        parts = text.split(":")

        if len(parts) != 2:
            return None

        try:

            hours = int(parts[0])
            minutes = int(parts[1])

        except ValueError:

            return None

        if hours < 0 or minutes < 0 or minutes >= 60:
            return None

        total = hours * 60 + minutes

        if total <= 0:
            return None

        return total

    # Format: 150
    try:

        minutes = int(text)

        if minutes <= 0:
            return None

        return minutes

    except ValueError:

        return None


# =========================================================
# Start
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["waiting_study"] = False

    keyboard = [
        ["🌅 بیدار شدم"],
        ["🏆 رتبه‌بندی امروز"],
        ["📚 ثبت گزارش کار"],
        ["🏆 رتبه‌بندی مطالعه"],
        ["📊 گزارش من", "📅 گزارش هفتگی"],
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.effective_chat.send_message(
        text=(
            "🌟 به ربات کاریزما خوش آمدی!\n\n"
            "🌅 ساعت بیداری خودت را ثبت کن.\n"
            "📚 میزان مطالعه‌ات را ثبت کن.\n"
            "🏆 رتبه خودت را با دیگر دانش‌آموزان ببین."
        ),
        reply_markup=reply_markup
    )


# =========================================================
# Wake Up
# =========================================================

async def wakeup(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    now, is_new, saved_time = save_wakeup(
        user.id,
        user.full_name
    )

    if not is_new:

        rank_info = get_today_user_rank(user.id)

        if rank_info:

            rank, total, original_time = rank_info

            await update.effective_chat.send_message(
                text=(
                    f"🌅 ساعت بیداری امروزت قبلاً ثبت شده است.\n\n"
                    f"⏰ اولین ثبت: {original_time}\n"
                    f"🏆 رتبه امروز: {rank} از {total}\n\n"
                    f"ثبت دوباره رتبه‌ات را تغییر نمی‌دهد. 💪"
                )
            )

        return

    rank_info = get_today_user_rank(user.id)

    if rank_info:

        rank, total, saved_time = rank_info

    else:

        rank = 1
        total = 1

    if rank == 1:

        medal = "🥇"
        message = "تو اولین نفر امروز بودی! 🔥"

    elif rank == 2:

        medal = "🥈"
        message = "عالیه! فقط یک نفر زودتر از تو بیدار شده. 💪"

    elif rank == 3:

        medal = "🥉"
        message = "آفرین! جزو سه نفر اول امروز هستی. 🔥"

    else:

        medal = "🏅"
        message = "آفرین که روزت رو شروع کردی! 💪"

    await update.effective_chat.send_message(
        text=(
            f"✅ ساعت بیداری ثبت شد!\n\n"
            f"👤 {user.full_name}\n"
            f"🌅 ساعت: {now.strftime('%H:%M:%S')}\n"
            f"📅 تاریخ: {now.strftime('%Y-%m-%d')}\n\n"
            f"{medal} رتبه امروز: {rank}\n"
            f"👥 تعداد ثبت‌شده‌ها: {total}\n\n"
            f"{message}"
        )
    )


# =========================================================
# Wake Ranking
# =========================================================

async def today_ranking(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    ranking = get_today_ranking()

    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

    if not ranking:

        await update.effective_chat.send_message(
            text=(
                f"🏆 رتبه‌بندی بیداری امروز\n\n"
                f"📅 {today}\n\n"
                f"هنوز کسی ساعت بیداری خود را ثبت نکرده است.\n\n"
                f"اولین نفر باش! 🔥"
            )
        )

        return

    lines = []

    for index, row in enumerate(ranking, start=1):

        telegram_id, name, wake_time = row

        if index == 1:
            medal = "🥇"
        elif index == 2:
            medal = "🥈"
        elif index == 3:
            medal = "🥉"
        else:
            medal = "🏅"

        clean_name = name or "دانش‌آموز"

        lines.append(
            f"{medal} {index}. {clean_name} — {wake_time}"
        )

    await update.effective_chat.send_message(
        text=(
            f"🏆 رتبه‌بندی بیداری امروز\n\n"
            f"📅 {today}\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🌅 فردا دوباره از رتبه ۱ شروع می‌کنیم!"
        )
    )


# =========================================================
# Register Study Report
# =========================================================

async def start_study_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["waiting_study"] = True

    await update.effective_chat.send_message(
        text=(
            "📚 ثبت گزارش کار\n\n"
            "مدت مطالعه امروزت را وارد کن.\n\n"
            "مثال:\n"
            "⏱ 2:30 یعنی ۲ ساعت و ۳۰ دقیقه\n"
            "⏱ 1:45 یعنی ۱ ساعت و ۴۵ دقیقه\n"
            "⏱ 60 یعنی ۶۰ دقیقه\n\n"
            "برای لغو بنویس: لغو"
        )
    )


# =========================================================
# Save Study Message
# =========================================================

async def process_study_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if text == "لغو":

        context.user_data["waiting_study"] = False

        await update.effective_chat.send_message(
            text="❌ ثبت گزارش کار لغو شد."
        )

        return

    minutes = parse_study_time(text)

    if minutes is None:

        await update.effective_chat.send_message(
            text=(
                "❌ فرمت واردشده درست نیست.\n\n"
                "مثلاً بنویس:\n"
                "2:30\n\n"
                "یعنی ۲ ساعت و ۳۰ دقیقه."
            )
        )

        return

    user = update.effective_user

    now = save_study_report(
        user.id,
        user.full_name,
        minutes
    )

    context.user_data["waiting_study"] = False

    total_today = get_personal_today_study(
        user.id
    )

    rank_info = get_today_study_user(
        user.id
    )

    if rank_info:

        rank, total_users, ranking_minutes = rank_info

    else:

        rank = 1
        total_users = 1

    await update.effective_chat.send_message(
        text=(
            f"✅ گزارش مطالعه ثبت شد!\n\n"
            f"📚 این نوبت: {format_minutes(minutes)}\n"
            f"⏰ زمان ثبت: {now.strftime('%H:%M')}\n\n"
            f"📖 مجموع مطالعه امروزت:\n"
            f"**{format_minutes(total_today)}**\n\n"
            f"🏆 رتبه امروز: {rank} از {total_users}\n\n"
            f"💪 ادامه بده؛ می‌تونی رتبه‌ات رو بهتر کنی!"
        ),
        parse_mode="Markdown"
    )


# =========================================================
# Study Ranking
# =========================================================

async def study_ranking(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    ranking = get_today_study_ranking()

    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

    if not ranking:

        await update.effective_chat.send_message(
            text=(
                f"🏆 رتبه‌بندی مطالعه امروز\n\n"
                f"📅 {today}\n\n"
                f"هنوز هیچ گزارشی ثبت نشده است.\n\n"
                f"اولین گزارش را تو ثبت کن! 🔥"
            )
        )

        return

    lines = []

    for index, row in enumerate(ranking, start=1):

        telegram_id, name, total_minutes = row

        if index == 1:
            medal = "🥇"
        elif index == 2:
            medal = "🥈"
        elif index == 3:
            medal = "🥉"
        else:
            medal = "🏅"

        clean_name = name or "دانش‌آموز"

        lines.append(
            f"{medal} {index}. {clean_name} — "
            f"{format_minutes(total_minutes)}"
        )

    await update.effective_chat.send_message(
        text=(
            f"🏆 رتبه‌بندی مطالعه امروز\n\n"
            f"📅 {today}\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"📚 رتبه‌ها بر اساس مجموع مطالعه امروز هستند.\n"
            f"🌅 فردا رتبه‌بندی از صفر شروع می‌شود."
        )
    )


# =========================================================
# Personal Study Report
# =========================================================

async def personal_study_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    total_today = get_personal_today_study(
        user.id
    )

    rank_info = get_today_study_user(
        user.id
    )

    if not rank_info:

        await update.effective_chat.send_message(
            text=(
                "📚 گزارش کار امروزت\n\n"
                "هنوز گزارشی ثبت نکرده‌ای.\n\n"
                "روی 📚 ثبت گزارش کار بزن."
            )
        )

        return

    rank, total_users, total_minutes = rank_info

    await update.effective_chat.send_message(
        text=(
            f"📚 گزارش کار امروز\n\n"
            f"👤 {user.full_name}\n\n"
            f"⏱ مجموع مطالعه:\n"
            f"{format_minutes(total_today)}\n\n"
            f"🏆 رتبه امروز: {rank} از {total_users}\n\n"
            f"🔥 برای افزایش رتبه، مطالعه بیشتری ثبت کن!"
        )
    )


# =========================================================
# Personal Wake Report
# =========================================================

async def personal_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

    total_seconds = 0
    valid_count = 0

    for wake_date, wake_time in rows:

        try:

            parts = wake_time.split(":")

            hour = int(parts[0])
            minute = int(parts[1])
            second = int(float(parts[2]))

            total_seconds += (
                hour * 3600
                + minute * 60
                + second
            )

            valid_count += 1

        except (ValueError, IndexError):

            pass

    if valid_count:

        average_seconds = total_seconds // valid_count

        avg_hour = average_seconds // 3600

        avg_minute = (
            average_seconds % 3600
        ) // 60

        average_text = (
            f"{avg_hour:02d}:{avg_minute:02d}"
        )

    else:

        average_text = "نامشخص"

    rank_info = get_today_user_rank(user.id)

    if rank_info:

        rank, today_total, today_time = rank_info

        today_rank_text = (
            f"🏆 رتبه بیداری امروز: "
            f"{rank} از {today_total}"
        )

    else:

        today_rank_text = (
            "🏆 امروز هنوز ثبت بیداری نداری"
        )

    study_rank = get_today_study_user(
        user.id
    )

    if study_rank:

        study_rank_number, study_total_users, study_minutes = study_rank

        study_rank_text = (
            f"📚 رتبه مطالعه امروز: "
            f"{study_rank_number} از {study_total_users}\n"
            f"⏱ مطالعه امروز: "
            f"{format_minutes(study_minutes)}"
        )

    else:

        study_rank_text = (
            "📚 امروز هنوز گزارش مطالعه ثبت نکرده‌ای"
        )

    await update.effective_chat.send_message(
        text=(
            f"📊 گزارش کلی شما\n\n"
            f"👤 {user.full_name}\n\n"
            f"🌅 تعداد ثبت بیداری: {total}\n"
            f"🌅 آخرین بیداری: {latest_time}\n"
            f"📅 آخرین تاریخ: {latest_date}\n"
            f"⏰ میانگین بیداری: {average_text}\n\n"
            f"{today_rank_text}\n"
            f"{study_rank_text}\n\n"
            f"💪 ادامه بده!"
        )
    )


# =========================================================
# Weekly Report
# =========================================================

async def weekly_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

    report_lines = []

    for wake_date, wake_time in rows:

        report_lines.append(
            f"🌅 {wake_date} → {wake_time}"
        )

    await update.effective_chat.send_message(
        text=(
            f"📅 گزارش هفتگی بیداری\n\n"
            f"از {start_date.strftime('%Y-%m-%d')} "
            f"تا {today.strftime('%Y-%m-%d')}\n\n"
            f"📈 تعداد ثبت‌ها: {len(rows)}\n"
            f"📆 تعداد روزهای ثبت‌شده: "
            f"{days_registered} از ۷ روز\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"{chr(10).join(report_lines)}\n"
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

    # اگر کاربر در حال ثبت گزارش مطالعه است
    if context.user_data.get("waiting_study"):

        await process_study_report(
            update,
            context
        )

        return

    if text == "🌅 بیدار شدم":

        await wakeup(update, context)

    elif text == "🏆 رتبه‌بندی امروز":

        await today_ranking(update, context)

    elif text == "📚 ثبت گزارش کار":

        await start_study_report(update, context)

    elif text == "🏆 رتبه‌بندی مطالعه":

        await study_ranking(update, context)

    elif text == "📊 گزارش من":

        await personal_report(update, context)

    elif text == "📅 گزارش هفتگی":

        await weekly_report(update, context)

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

    init_db()

    threading.Thread(
        target=start_web_server,
        daemon=True
    ).start()

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
