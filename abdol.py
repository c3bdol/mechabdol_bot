from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext
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
        await context.bot.send_message(chat.id, "✅ Bot initialized and admins saved.")

# ... (rest of the code remains same as previous fix) ...

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
