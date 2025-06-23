from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext,
    CommandHandler
)
import datetime
import json
import os
import pytz
from pathlib import Path

# === Config ===
TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", ".")
POINTS_FILE = Path(DATA_DIR) / 'points.json'
GROUP_CHAT_ID_FILE = Path(DATA_DIR) / 'group_id.txt'
ADMINS_FILE = Path(DATA_DIR) / 'admins.json'
KEYWORDS = ['ok', 'tam']
points = {}

print(f"📁 Using persistent storage at: {DATA_DIR}")
print(f"📝 Points file: {POINTS_FILE}")
print(f"🆔 Group ID file: {GROUP_CHAT_ID_FILE}")
print(f"👑 Admins file: {ADMINS_FILE}")

# === Load existing points ===
if POINTS_FILE.exists():
    try:
        with open(POINTS_FILE, 'r') as f:
            points = json.load(f)
        print(f"✅ Loaded {len(points)} user points")
    except (json.JSONDecodeError, FileNotFoundError):
        print("⚠️ Could not load points file")
        points = {}
else:
    print("ℹ️ No points file found, starting fresh")

# === Check if user is admin ===
async def is_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not ADMINS_FILE.exists():
        return False
        
    try:
        with open(ADMINS_FILE, 'r') as f:
            admins = json.load(f)
        return user_id in admins
    except:
        return False

# === /start command ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I'm the Points Bot!\n\n"
        "Here's how I work:\n"
        "1. Add me to a group\n"
        "2. Admins can reply to messages with 'ok' or 'tam' to award points\n"
        "3. I'll post weekly leaderboards every Saturday\n\n"
        "Commands:\n"
        "/dash - Show current leaderboard\n"
        "/reset - Reset points (admins only)"
    )

# === /dash command - show current leaderboard ===
async def dash_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not points:
        await update.message.reply_text("📊 No points yet! Start awarding points by replying to messages with 'ok' or 'tam'.")
        return

    # Create leaderboard
    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        try:
            user = await context.bot.get_chat_member(update.effective_chat.id, int(uid))
            name = user.user.full_name
        except:
            name = f"User {uid}"
        leaderboard.append(f"{idx+1}. {name} - {pts} pts")
    
    # Add emoji indicators for top 3
    if len(leaderboard) > 0:
        leaderboard[0] = "🥇 " + leaderboard[0]
    if len(leaderboard) > 1:
        leaderboard[1] = "🥈 " + leaderboard[1]
    if len(leaderboard) > 2:
        leaderboard[2] = "🥉 " + leaderboard[2]
    
    await update.message.reply_text(
        "📊 Current Leaderboard 📊\n\n" + "\n".join(leaderboard)
    )

# === /reset command - reset all points (admin only) ===
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Check if user is admin
    if not await is_admin(context, user_id):
        await update.message.reply_text("⛔ You need to be an admin to reset points!")
        return
        
    # Reset points
    global points
    points.clear()
    with open(POINTS_FILE, 'w') as f:
        json.dump(points, f)
    
    await update.message.reply_text("✅ Leaderboard has been reset! All points cleared.")
    print(f"♻️ Points reset by user {user_id}")

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
        
        print(f"✅ Saved group ID {group_id} and {len(admin_ids)} admins")
        await context.bot.send_message(
            chat.id,
            "✅ Bot initialized and admins saved.\n\n"
            "Commands:\n"
            "/dash - Show current leaderboard\n"
            "/reset - Reset points (admins only)"
        )

# === Handle admin replies ===
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return

    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id

    # Check admin status
    if not await is_admin(context, user_id):
        return

    # Check keyword
    text = update.message.text.lower().strip()
    if text in KEYWORDS:
        replied_user_id = str(update.message.reply_to_message.from_user.id)
        points[replied_user_id] = points.get(replied_user_id, 0) + 1
        
        with open(POINTS_FILE, 'w') as f:
            json.dump(points, f)
        
        # Get user's current points
        current_points = points.get(replied_user_id, 0)
        await update.message.reply_text(
            f"✅ +1 point! Total: {current_points} 🔥"
        )

# === Leaderboard function ===
async def send_leaderboard(context: CallbackContext):
    job_ctx = context.job.context
    if not points:
        await context.bot.send_message(job_ctx, "📭 No points awarded this week!")
        return

    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        try:
            user = await context.bot.get_chat_member(job_ctx, int(uid))
            name = user.user.full_name
        except:
            name = f"User {uid}"
        leaderboard.append(f"{idx+1}. {name} - {pts} pts")
    
    # Add emoji indicators for top 3
    if len(leaderboard) > 0:
        leaderboard[0] = "🥇 " + leaderboard[0]
    if len(leaderboard) > 1:
        leaderboard[1] = "🥈 " + leaderboard[1]
    if len(leaderboard) > 2:
        leaderboard[2] = "🥉 " + leaderboard[2]
    
    await context.bot.send_message(
        chat_id=job_ctx,
        text=f"🏆 Weekly Leaderboard 🏆\n\n" + "\n".join(leaderboard)
    )
    
    # Reset points
    points.clear()
    with open(POINTS_FILE, 'w') as f:
        json.dump(points, f)
    print("♻️ Weekly points reset after leaderboard")

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
    print(f"⏰ Scheduled weekly leaderboard for chat {chat_id} on Saturdays at 06:00 UTC")

# === Load group ID ===
def load_group_id():
    if GROUP_CHAT_ID_FILE.exists():
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
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("dash", dash_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, save_group_and_admins))
    application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_reply))
    
    # Load existing group ID and schedule job
    if group_id := load_group_id():
        print(f"🔍 Found existing group ID: {group_id}")
        schedule_leaderboard(application, group_id)
    
    # Start the bot
    print("🤖 Starting bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
