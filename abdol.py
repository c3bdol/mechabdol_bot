from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
import json
import os

# === Config ===
TOKEN = '8178675165:AAGgw_tEt5fHFsdSpWjYgn6SwawJ4LlL-Lc'  # <--- put your real token here
POINTS_FILE = 'points.json'
GROUP_CHAT_ID_FILE = 'group_id.txt'
ADMINS_FILE = 'admins.json'
KEYWORDS = ['ok', 'tam']
points = {}

# === Load existing points if file exists ===
if os.path.exists(POINTS_FILE):
    with open(POINTS_FILE, 'r') as f:
        points = json.load(f)

# === Save group ID and admin list when bot joins ===
async def save_group_and_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        group_id = chat.id

        # Save group chat ID
        with open(GROUP_CHAT_ID_FILE, 'w') as f:
            f.write(str(group_id))

        # Get and save admin IDs
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_ids = [admin.user.id for admin in admins]
        with open(ADMINS_FILE, 'w') as f:
            json.dump(admin_ids, f)

        await context.bot.send_message(chat.id, "✅ Bot initialized and admins saved.")

# === Handle admin replies with keyword ===
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return

    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id

    # Check if user is admin from saved file
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE, 'r') as f:
            admins = json.load(f)
        if user_id not in admins:
            return
    else:
        return

    # Check if message is keyword
    text = update.message.text.lower()
    if text in KEYWORDS:
        replied_user_id = str(update.message.reply_to_message.from_user.id)
        points[replied_user_id] = points.get(replied_user_id, 0) + 1

        with open(POINTS_FILE, 'w') as f:
            json.dump(points, f)

        await update.message.reply_text("Points added 🔥")

# === Helper to get user name ===
async def get_username(context, chat_id, user_id):
    try:
        user = await context.bot.get_chat_member(chat_id, user_id)
        return user.user.full_name
    except:
        return f"User {user_id}"

# === Send leaderboard and reset points ===
async def send_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if not points:
        return

    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = "\n".join(
        [f"{idx+1}. {await get_username(context, chat_id, int(uid))} - {pts} pts"
         for idx, (uid, pts) in enumerate(sorted_points)]
    )

    await context.bot.send_message(chat_id=chat_id, text=f"🏆 Weekly Leaderboard 🏆\n\n{leaderboard}")

    # Reset points
    points.clear()
    with open(POINTS_FILE, 'w') as f:
        json.dump(points, f)

# === Schedule weekly leaderboard ===
def schedule_jobs(application: Application, chat_id: int):
    if not chat_id:
        return
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        application.create_task,
        'cron',
        day_of_week='sat',
        hour=6,
        minute=0,
        args=[send_leaderboard],
        kwargs={'context': ContextTypes.DEFAULT_TYPE(job=None, chat_id=chat_id)}
    )
    scheduler.start()

def load_group_id():
    if os.path.exists(GROUP_CHAT_ID_FILE):
        with open(GROUP_CHAT_ID_FILE, 'r') as f:
            return int(f.read())
    return None

# === Start the bot ===
async def start_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, save_group_and_admins))
    application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_reply))

    application.post_init = lambda _: schedule_jobs(application, load_group_id())

    await application.run_polling()

# === Safe event loop fix for hosting environments ===
if __name__ == '__main__':
    import asyncio
    import sys

    try:
        asyncio.run(start_bot())
    except RuntimeError as e:
        print(f"⚠️ Bot stopped: {e}")
        sys.exit(1)

