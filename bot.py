"""
Dars yuboruvchi Telegram bot
-----------------------------
Ishlash tartibi:
1. /vaqt HH:MM  -> har kuni shu vaqtda darslik yuborilishini sozlaydi
2. Darslik qo'shish: botga oddiy xabar (matn, rasm, fayl, video) yuboring -> navbatga qo'shiladi
3. Belgilangan vaqtda navbatdagi eng birinchi darslik avtomatik yuboriladi
4. /royxat -> navbatdagi darsliklar sonini ko'rsatadi
5. /bekor -> rejalashtirilgan yuborishni to'xtatadi

O'rnatish:
    pip install python-telegram-bot==21.4 apscheduler

Ishga tushirish:
    python main.py

Bot tokenini @BotFather orqali oling va pastdagi BOT_TOKEN ga qo'ying,
yoki muhit o'zgaruvchisi orqali bering: export BOT_TOKEN="..."
"""

import json
import os
import logging
from datetime import time as dt_time

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8860944673:AAHf5VGZiHiix7oH0B3ItKTYJwMtylEo5R8")
DATA_FILE = "darsliklar.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}}  # {chat_id: {"queue": [...], "time": "HH:MM"}}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()
scheduler = AsyncIOScheduler()


def get_user(chat_id):
    cid = str(chat_id)
    if cid not in data["users"]:
        data["users"][cid] = {"queue": [], "time": None}
    return data["users"][cid]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom! Men sizga har kuni belgilangan vaqtda darslik yuboraman.\n\n"
        "1) Menga darslik (matn/rasm/fayl) yuboring - saqlab qo'yaman.\n"
        "2) /vaqt 19:00 kabi yozib, qaysi vaqtda yuborishimni belgilang.\n"
        "3) /royxat - navbatda nechta darslik borligini ko'rasiz.\n"
        "4) /bekor - avtomatik yuborishni to'xtatadi."
    )


async def vaqt_belgila(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Masalan: /vaqt 19:00")
        return
    try:
        h, m = map(int, context.args[0].split(":"))
        dt_time(h, m)
    except Exception:
        await update.message.reply_text("Noto'g'ri format. Masalan: /vaqt 19:00")
        return

    user = get_user(chat_id)
    user["time"] = f"{h:02d}:{m:02d}"
    save_data(data)
    schedule_user_job(context.application, chat_id, h, m)
    await update.message.reply_text(f"Bo'ldi! Har kuni soat {h:02d}:{m:02d} da darslik yuboraman.")


async def royxat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_chat.id)
    n = len(user["queue"])
    vaqt = user["time"] or "belgilanmagan"
    await update.message.reply_text(f"Navbatda: {n} ta darslik.\nYuborish vaqti: {vaqt}")


async def bekor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    user["time"] = None
    save_data(data)
    job_id = f"job_{chat_id}"
    if context.application.job_queue.get_jobs_by_name(job_id):
        for j in context.application.job_queue.get_jobs_by_name(job_id):
            j.schedule_removal()
    await update.message.reply_text("Avtomatik yuborish bekor qilindi.")


async def darslik_qabul_qil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi yuborgan har qanday xabarni (matn/rasm/fayl) navbatga qo'shadi."""
    chat_id = update.effective_chat.id
    msg = update.message
    user = get_user(chat_id)

    item = None
    if msg.text:
        item = {"type": "text", "content": msg.text}
    elif msg.photo:
        item = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": msg.caption or ""}
    elif msg.document:
        item = {"type": "document", "file_id": msg.document.file_id, "caption": msg.caption or ""}
    elif msg.video:
        item = {"type": "video", "file_id": msg.video.file_id, "caption": msg.caption or ""}

    if item:
        user["queue"].append(item)
        save_data(data)
        await msg.reply_text(f"Saqlandi. Navbatda {len(user['queue'])} ta darslik bor.")


async def send_next_lesson(application, chat_id):
    user = get_user(chat_id)
    if not user["queue"]:
        await application.bot.send_message(chat_id, "Navbatda darslik qolmadi. Yangi material yuboring.")
        return

    item = user["queue"].pop(0)
    save_data(data)

    if item["type"] == "text":
        await application.bot.send_message(chat_id, item["content"])
    elif item["type"] == "photo":
        await application.bot.send_photo(chat_id, item["file_id"], caption=item["caption"])
    elif item["type"] == "document":
        await application.bot.send_document(chat_id, item["file_id"], caption=item["caption"])
    elif item["type"] == "video":
        await application.bot.send_video(chat_id, item["file_id"], caption=item["caption"])


def schedule_user_job(application, chat_id, h, m):
    job_id = f"job_{chat_id}"
    for j in application.job_queue.get_jobs_by_name(job_id):
        j.schedule_removal()
    application.job_queue.run_daily(
        callback=lambda ctx: send_next_lesson(application, chat_id),
        time=dt_time(hour=h, minute=m),
        name=job_id,
    )


async def on_startup(application):
    # Bot qayta ishga tushganda avvalgi vaqt sozlamalarini tiklaydi
    for chat_id, user in data["users"].items():
        if user.get("time"):
            h, m = map(int, user["time"].split(":"))
            schedule_user_job(application, int(chat_id), h, m)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vaqt", vaqt_belgila))
    app.add_handler(CommandHandler("royxat", royxat))
    app.add_handler(CommandHandler("bekor", bekor))
    app.add_handler(MessageHandler(~filters.COMMAND, darslik_qabul_qil))

    app.run_polling()


if __name__ == "__main__":
    main()