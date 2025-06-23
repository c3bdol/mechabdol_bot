from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext,
    Defaults
)
from telegram.constants import ChatAction
import datetime
import json
import os
import pytz  # For timezone handling

# === Config ===
TOKEN = '8178675165:AAGgw_tEt5fHFsdSpWjYgn6SwawJ4LlL-Lc'  # Replace with your actual token
POINTS_FILE = 'points.json'
GROUP_CHAT_ID_FILE = 'group_id.txt'
ADMINS_FILE = 'admins.json'
KEYWORDS = ['ok', 'tam']
points = {}

# === Load existing points ===
if os.path.exists(POINTS_FILE):
    try:
        with open(POINTS_FILE, 'r') as f:
            points = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        points = {}

# === Save group ID and admin list ===
async def save_group_and_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        group_id = chat.id
        
        # Save group ID
        with open(GROUP_CHAT_ID_FILE, 'w') as f:
            f.write(str(group_id))
        
        # Save admin IDs
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_ids = [admin.user.id for admin in admins]
        with open(ADMINS_FILE, 'w') as f:
            json.dump(admin_ids, f)
        
        # Schedule weekly job
        if context.application.job_queue:
            schedule_leaderboard(context.application, group_id)
        
        await context.bot.send_message(chat.id, "✅ Bot initialized and admins saved.")

# === Handle admin replies ===
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return

    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id

    # Check admin status
    if os.path.exists(ADMINS_FILE):
        try:
            with open(ADMINS_FILE, 'r') as f:
                admins = json.load(f)
            if user_id not in admins:
                return
        except (json.JSONDecodeError, FileNotFoundError):
            return

    # Check keyword
    text = update.message.text.lower().strip()
    if text in KEYWORDS:
        replied_user_id = str(update.message.reply_to_message.from_user.id)
        points[replied_user_id] = points.get(replied_user_id, 0) + 1
        
        with open(POINTS_FILE, 'w') as f:
            json.dump(points, f)
        
        await update.message.reply_text("✅ Points added!")

# === Get username helper ===
async def get_username(context: CallbackContext, user_id: int):
    try:
        user = await context.bot.get_chat_member(context.job.context, user_id)
        return user.user.full_name
    except Exception:
        return f"User {user_id}"

# === Leaderboard function ===
async def send_leaderboard(context: CallbackContext):
    job_ctx = context.job.context
    if not points:
        return

    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        name = await get_username(context, int(uid))
        leaderboard.append(f"{idx+1}. {name} - {pts} pts")
    
    await context.bot.send_message(
        chat_id=job_ctx,
        text=f"🏆 Weekly Leaderboard 🏆\n\n" + "\n".join(leaderboard)
    )
    
    # Reset points
    points.clear()
    with open(POINTS_FILE, 'w') as f:
        json.dump(points, f)

# === Schedule leaderboard ===
def schedule_leaderboard(application: Application, chat_id: int):
    if not application.job_queue:
        return
    
    # Remove existing jobs
    current_jobs = application.job_queue.get_jobs_by_name("weekly_leaderboard")
    for job in current_jobs:
        job.schedule_removal()
    
    # Schedule new job (Saturday 6 AM UTC)
    application.job_queue.run_daily(
        send_leaderboard,
        time=datetime.time(hour=6, minute=0, tzinfo=pytz.UTC),
        days=(5,),  # Saturday (0=Monday, 6=Sunday)
        context=chat_id,
        name="weekly_leaderboard"
    )

# === Load group ID ===
def load_group_id():
    if os.path.exists(GROUP_CHAT_ID_FILE):
        try:
            with open(GROUP_CHAT_ID_FILE, 'r') as f:
                return int(f.read().strip())
        except (ValueError, FileNotFoundError):
            return None
    return None

# === Main bot function ===
def main():
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, save_group_and_admins))
    application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_reply))
    
    # Load existing group ID and schedule job
    if group_id := load_group_id():
        schedule_leaderboard(application, group_id)
    
    # Start the bot
    application.run_polling()

# === Entry point ===
if __name__ == '__main__':
    main()
