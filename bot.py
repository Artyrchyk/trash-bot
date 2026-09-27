import logging
import pytz
import os
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from schedule import WASTE_SCHEDULE

# Налаштування логування
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = "8868034368:AAE14z1B8UMS13gZiigmsKhuaqPcMQUpvpY"

# Груповий ID чату
TARGET_CHAT_ID = -1004353435844  

completed_dates = set()

# --- МІНІ-СЕРВЕР FLASK ДЛЯ RENDER ---
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is alive and running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)
# ------------------------------------

async def start(command_update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = command_update.effective_chat.id
    await command_update.message.reply_text(
        f"Привіт! Бот нагадувань для Wenggasse активний.\n"
        f"ID цього чату: `{chat_id}`",
        parse_mode="Markdown"
    )

async def send_reminder_message(bot, date_str, waste_type, tag_info, time_label):
    if date_str in completed_dates:
        return

    message = (
        f"🔔 **Нагадування про вивіз сміття! ({time_label})**\n\n"
        f"📅 **Дата вивозу:** {date_str}\n"
        f"🗑 **Що виносимо:** {waste_type}\n"
        f"👤 **Черговий(а):** **{tag_info}**\n\n"
        f"*Будь ласка, підготуйте баки та не забудьте винести!*"
    )

    keyboard = [[InlineKeyboardButton("✅ Сміття вивезено", callback_data=f"done_{date_str}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await bot.send_message(
            chat_id=TARGET_CHAT_ID,
            text=message,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Помилка надсилання повідомлення: {e}")

async def scheduled_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await send_reminder_message(
        context.bot, 
        data["date"], 
        data["waste_type"], 
        data["tag"], 
        data["time_label"]
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("done_"):
        date_str = data.split("_", 1)[1]
        completed_dates.add(date_str)
        user_name = query.from_user.first_name

        await query.edit_message_text(
            text=f"✅ **Сміття на {date_str} успішно вивезено!**\n(Відзначив(la): {user_name}) Дякуємо!",
            parse_mode="Markdown"
        )

async def check_immediate_reminders(context: ContextTypes.DEFAULT_TYPE):
    """
    Перевіряє при запуску: якщо сьогодні або завтра є дата вивозу, 
    одразу надсилає сповіщення в групу!
    """
    tz = pytz.timezone("Europe/Berlin")
    now_local = datetime.now(tz)
    today_str = now_local.date().strftime("%d.%m.%Y")
    tomorrow_str = (now_local.date() + timedelta(days=1)).strftime("%d.%m.%Y")

    # Перевірка на сьогодні (щоб одразу прийшло нагадування про 28.09)
    if today_str in WASTE_SCHEDULE:
        info = WASTE_SCHEDULE[today_str]
        await send_reminder_message(
            context.bot, 
            today_str, 
            info["type"], 
            info["tag"], 
            "Сьогоднішнє термінове нагадування"
        )

    # Перевірка на завтра
    if tomorrow_str in WASTE_SCHEDULE:
        info = WASTE_SCHEDULE[tomorrow_str]
        await send_reminder_message(
            context.bot, 
            tomorrow_str, 
            info["type"], 
            info["tag"], 
            "Нагадування на завтра"
        )

def schedule_jobs(application: Application):
    tz = pytz.timezone("Europe/Berlin")
    job_queue = application.job_queue

    for date_str, info in WASTE_SCHEDULE.items():
        try:
            # Очищаємо дату від додаткових індексів на кшталт "(2)" для парсингу
            clean_date_str = date_str.split(" ")[0]
            collection_date = datetime.strptime(clean_date_str, "%d.%m.%Y").date()
            reminder_date = collection_date - timedelta(days=1)
            
            if reminder_date < datetime.now(tz).date():
                continue

            waste_type = info["type"]
            tag_info = info["tag"]

            times = [
                (10, 0, "Ранкове нагадування"),
                (14, 0, "Денне нагадування"),
                (19, 0, "Вечірнє нагадування")
            ]

            for hour, minute, label in times:
                run_time = datetime(
                    reminder_date.year, reminder_date.month, reminder_date.day,
                    hour, minute, 0, tzinfo=tz
                )

                job_queue.run_once(
                    scheduled_reminder_job,
                    when=run_time,
                    data={
                        "date": date_str,
                        "waste_type": waste_type,
                        "tag": tag_info,
                        "time_label": label
                    }
                )
        except Exception as e:
            logger.error(f"Помилка планування для дати {date_str}: {e}")

def main():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    schedule_jobs(application)
    
    # Запускаємо миттєву перевірку при стартові
    application.job_queue.run_once(check_immediate_reminders, when=2)

    print("Бот успішно запущено!")
    application.run_polling()

if __name__ == "__main__":
    main()