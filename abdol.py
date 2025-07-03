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
import re
from pathlib import Path

# === Config ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN"))
DATA_DIR = os.getenv("DATA_DIR", ".")
GROUPS_DATA_DIR = Path(DATA_DIR) / 'groups_data'
KEYWORDS = ['ok', 'tamm', 'تم', 'ضن']
SUBTRACT_KEYWORDS = ['حذف']

# Railway port configuration
PORT = int(os.getenv("PORT", 8000))

# Create groups data directory if it doesn't exist
GROUPS_DATA_DIR.mkdir(exist_ok=True)

print(f"📁 Using persistent storage at: {DATA_DIR}")
print(f"📂 Groups data directory: {GROUPS_DATA_DIR}")

# === Helper functions for file paths ===
def get_group_points_file(group_id: int) -> Path:
    return GROUPS_DATA_DIR / f'points_{group_id}.json'

def get_group_admins_file(group_id: int) -> Path:
    return GROUPS_DATA_DIR / f'admins_{group_id}.json'

def get_group_owner_file(group_id: int) -> Path:
    return GROUPS_DATA_DIR / f'owner_{group_id}.txt'

# === Load group points ===
def load_group_points(group_id: int) -> dict:
    points_file = get_group_points_file(group_id)
    if points_file.exists():
        try:
            with open(points_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"⚠️ Could not load points file for group {group_id}")
            return {}
    return {}

# === Save group points ===
def save_group_points(group_id: int, points: dict):
    points_file = get_group_points_file(group_id)
    with open(points_file, 'w') as f:
        json.dump(points, f)

# === Check if user is admin or owner ===
async def is_admin_or_owner(context: ContextTypes.DEFAULT_TYPE, group_id: int, user_id: int) -> bool:
    # Check if user is owner
    owner_file = get_group_owner_file(group_id)
    if owner_file.exists():
        try:
            with open(owner_file, 'r') as f:
                owner_id = int(f.read().strip())
            if user_id == owner_id:
                return True
        except (ValueError, FileNotFoundError):
            pass
    
    # Check if user is admin
    admins_file = get_group_admins_file(group_id)
    if admins_file.exists():
        try:
            with open(admins_file, 'r') as f:
                admins = json.load(f)
            return user_id in admins
        except:
            pass
    
    return False

# === Check if command is allowed in private chat ===
def is_private_chat_allowed(command: str) -> bool:
    return command == 'start'

# === Parse test scores from message ===
def parse_test_scores(message_text: str) -> list:
    """
    Parse test scores from a multi-line message.
    Expected format: @username score or username score
    Returns list of tuples (username, score)
    """
    lines = message_text.strip().split('\n')
    scores = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Pattern to match: @username score or username score
        # Also handles mentions like @user_name 5 or user_name 5
        pattern = r'(@?\w+)\s+(\d+(?:\.\d+)?)'
        match = re.search(pattern, line)
        
        if match:
            username = match.group(1).lstrip('@')  # Remove @ if present
            try:
                score = float(match.group(2))
                scores.append((username, score))
            except ValueError:
                continue
    
    return scores

# === Get user ID from username ===
async def get_user_id_from_username(context: ContextTypes.DEFAULT_TYPE, group_id: int, username: str) -> int:
    """
    Try to get user ID from username by checking recent messages or mentions.
    This is a simplified approach - in practice, you might want to maintain a username->ID mapping.
    """
    try:
        # Try to get chat member by username (this works for some cases)
        member = await context.bot.get_chat_member(group_id, f"@{username}")
        return member.user.id
    except:
        # If that fails, we'll need to return None and handle it in the calling function
        return None

# === Handle test scores message ===
async def handle_test_scores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle multi-line test scores message from admin.
    Format: Each line should contain a mention/username and a score.
    """
    # Only work in groups
    if update.effective_chat.type == 'private':
        return
        
    user_id = update.message.from_user.id
    group_id = update.effective_chat.id
    
    # Check if user is admin or owner
    if not await is_admin_or_owner(context, group_id, user_id):
        return
    
    message_text = update.message.text
    if not message_text:
        return
    
    # Parse test scores from the message
    scores = parse_test_scores(message_text)
    
    if not scores:
        return  # No valid scores found, don't respond
    
    # Load current points for this group
    points = load_group_points(group_id)
    
    # Process each score
    successful_updates = []
    failed_updates = []
    
    for username, score in scores:
        # First, try to find the user ID from entities (mentions)
        user_id_found = None
        
        # Check if there are any mentions in the message
        if update.message.entities:
            for entity in update.message.entities:
                if entity.type == 'mention':
                    mention_text = message_text[entity.offset:entity.offset + entity.length]
                    if mention_text.lower() == f"@{username.lower()}":
                        # This is a mention, but we still need to get the user ID
                        # Try to get user ID from username
                        user_id_found = await get_user_id_from_username(context, group_id, username)
                        break
                elif entity.type == 'text_mention':
                    # Direct mention with user object
                    mention_text = message_text[entity.offset:entity.offset + entity.length]
                    if mention_text.lower() == f"@{username.lower()}" or mention_text.lower() == username.lower():
                        user_id_found = entity.user.id
                        break
        
        # If we couldn't find user ID from mentions, try to get it from username
        if user_id_found is None:
            user_id_found = await get_user_id_from_username(context, group_id, username)
        
        if user_id_found:
            user_id_str = str(user_id_found)
            points[user_id_str] = points.get(user_id_str, 0) + score
            
            # Get user's name for the response
            try:
                user = await context.bot.get_chat_member(group_id, user_id_found)
                display_name = user.user.full_name
            except:
                display_name = username
            
            successful_updates.append(f"✅ {display_name}: +{score} نقطة (المجموع: {points[user_id_str]})")
        else:
            failed_updates.append(f"❌ {username}: لم يتم العثور على المستخدم")
    
    # Save updated points if there were successful updates
    if successful_updates:
        save_group_points(group_id, points)
    
    # Send response if there were any score updates attempted
    if successful_updates or failed_updates:
        response_lines = []
        
        if successful_updates:
            response_lines.append("📊 تم تحديث النقاط:")
            response_lines.extend(successful_updates)
        
        if failed_updates:
            if successful_updates:
                response_lines.append("")
            response_lines.append("⚠️ لم يتم العثور على:")
            response_lines.extend(failed_updates)
        
        await update.message.reply_text("\n".join(response_lines))

# === /start command ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً وسهلاً! أنا بوت النقط!\n\n"
        "إزاي أشتغل:\n"
        "1. ضيفني للجروب\n"
        "2. الأدمنز وصاحب الجروب يقدروا يردوا على الرسايل بكلمات معينة علشان يدوا نقط أو يشيلوها\n"
        "3. يقدروا يضيفوا نقط امتحانات بكتابة رسالة فيها عدة أسطر، كل سطر فيه منشن واسكور\n"
        "4. هنشر قايمة المتصدرين كل يوم سبت\n\n"
        "الأوامر (الجروبات بس):\n"
        "/dash - عرض قايمة المتصدرين دلوقتي\n"
        "/reset - مسح النقط كلها (الأدمنز/صاحب الجروب بس)\n\n"
        f"زيادة نقط: {', '.join(KEYWORDS)}\n"
        f"نقص نقط: {', '.join(SUBTRACT_KEYWORDS)}\n\n"
        "📝 إضافة نقاط امتحانات:\n"
        "اكتب رسالة بالشكل ده:\n"
        "@username1 85\n"
        "@username2 92\n"
        "username3 78"
    )

# === /dash command - show current leaderboard ===
async def dash_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if command is in group
    if update.effective_chat.type == 'private':
        await update.message.reply_text("⛔ الأمر ده بيشتغل في الجروبات بس!")
        return
    
    group_id = update.effective_chat.id
    points = load_group_points(group_id)
    
    if not points:
        await update.message.reply_text("📊 مفيش نقط لسه! ابدأ إدي نقط بالرد على الرسايل بالكلمات المحددة.")
        return

    # Create leaderboard
    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        try:
            user = await context.bot.get_chat_member(group_id, int(uid))
            name = user.user.full_name
        except:
            name = f"يوزر {uid}"
        leaderboard.append(f"{idx+1}. {name} - {pts} نقطة")
    
    # Add emoji indicators for top 3
    if len(leaderboard) > 0:
        leaderboard[0] = "🥇 " + leaderboard[0]
    if len(leaderboard) > 1:
        leaderboard[1] = "🥈 " + leaderboard[1]
    if len(leaderboard) > 2:
        leaderboard[2] = "🥉 " + leaderboard[2]
    
    await update.message.reply_text(
        f"📊 قايمة المتصدرين دلوقتي 📊\n"
        f"الجروب: {update.effective_chat.title}\n\n" + "\n".join(leaderboard)
    )

# === /reset command - reset all points (admin/owner only) ===
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if command is in group
    if update.effective_chat.type == 'private':
        await update.message.reply_text("⛔ الأمر ده بيشتغل في الجروبات بس!")
        return
    
    user_id = update.message.from_user.id
    group_id = update.effective_chat.id
    
    # Check if user is admin or owner
    if not await is_admin_or_owner(context, group_id, user_id):
        await update.message.reply_text("⛔ لازم تكون أدمن أو صاحب الجروب علشان تمسح النقط!")
        return
        
    # Reset points for this group
    save_group_points(group_id, {})
    
    await update.message.reply_text("✅ تم مسح قايمة المتصدرين! كل النقط اتمسحت من الجروب ده.")
    print(f"♻️ Points reset for group {group_id} by user {user_id}")

# === Save g
