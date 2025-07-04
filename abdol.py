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
    message_text = update.message.text
    if not message_text:
        return
    
    # Parse test scores from the message
    scores = parse_test_scores(message_text)
    
    if not scores:
        return  # No valid scores found, don't respond
    
    group_id = update.effective_chat.id
    
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

# === Save group owner and admin list ===
async def save_group_and_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        group_id = chat.id
        
        try:
            # Get admins and owner
            admins = await context.bot.get_chat_administrators(chat.id)
            admin_ids = []
            owner_id = None
            
            for admin in admins:
                if admin.status == 'creator':
                    owner_id = admin.user.id
                elif admin.status == 'administrator':
                    admin_ids.append(admin.user.id)
            
            # Save owner ID
            if owner_id:
                owner_file = get_group_owner_file(group_id)
                with open(owner_file, 'w') as f:
                    f.write(str(owner_id))
                print(f"👑 Saved group owner {owner_id} for group {group_id}")
            
            # Save admin IDs
            admins_file = get_group_admins_file(group_id)
            with open(admins_file, 'w') as f:
                json.dump(admin_ids, f)
            
            # Schedule weekly job for this group
            if context.application.job_queue:
                schedule_leaderboard(context.application, group_id)
            
            print(f"✅ Saved group {group_id}: owner={owner_id}, {len(admin_ids)} admins")
            await context.bot.send_message(
                chat.id,
                f"✅ البوت جاهز في الجروب: {chat.title}\n\n"
                "الأوامر:\n"
                "/dash - عرض قايمة المتصدرين دلوقتي\n"
                "/reset - مسح النقط (الأدمنز/صاحب الجروب بس)\n\n"
                f"الكلمات المفتاحية: {', '.join(KEYWORDS)}\n"
                f"كلمة النقص: {', '.join(SUBTRACT_KEYWORDS)}\n\n"
                "📝 إضافة نقاط امتحانات:\n"
                "اكتب رسالة بالشكل ده:\n"
                "@username1 85\n"
                "@username2 92\n"
                "username3 78"
            )
        except Exception as e:
            print(f"❌ Error saving group data for {group_id}: {e}")
            await context.bot.send_message(
                chat.id,
                "⚠️ مقدرش أشتغل كامل. خلي ليا صلاحيات أدمن في الجروب."
            )

# === Handle admin/owner replies ===
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return
    
    # Only work in groups
    if update.effective_chat.type == 'private':
        return

    user_id = update.message.from_user.id
    group_id = update.effective_chat.id
    replied_user = update.message.reply_to_message.from_user

    # Check admin/owner status
    if not await is_admin_or_owner(context, group_id, user_id):
        return

    # Check keyword first
    text = update.message.text.lower().strip()
    
    # Only check restrictions if using point keywords
    if text in KEYWORDS or text in SUBTRACT_KEYWORDS:
        # Prevent self-awarding only when using keywords
        if user_id == replied_user.id:
            await update.message.reply_text("⛔ مينفعش تدي نفسك نقط!")
            return
        
        # Prevent awarding points to bots only when using keywords
        if replied_user.is_bot:
            await update.message.reply_text("⛔ مينفعش إدي نقط للبوتات!")
            return

    # Check keyword for adding points
    if text in KEYWORDS:
        replied_user_id = str(replied_user.id)
        
        # Load current points for this group
        points = load_group_points(group_id)
        points[replied_user_id] = points.get(replied_user_id, 0) + 1
        
        # Save updated points
        save_group_points(group_id, points)
        
        # Get user's current points
        current_points = points.get(replied_user_id, 0)
        await update.message.reply_text(
            f"✅ +1 نقطة لـ {replied_user.full_name}! المجموع: {current_points} 🔥"
        )
    
    # Check keyword for subtracting points
    elif text in SUBTRACT_KEYWORDS:
        replied_user_id = str(replied_user.id)
        
        # Load current points for this group
        points = load_group_points(group_id)
        current_points = points.get(replied_user_id, 0)
        
        if current_points > 0:
            points[replied_user_id] = current_points - 1
            save_group_points(group_id, points)
            new_points = points[replied_user_id]
            await update.message.reply_text(
                f"❌ -1 نقطة لـ {replied_user.full_name}! المجموع: {new_points} 📉"
            )
        else:
            await update.message.reply_text(
                f"⚠️ {replied_user.full_name} معوش نقط أصلاً! مينفعش نشيل أكتر من كده."
            )

# === Handle general messages (for test scores) ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-reply messages that might contain test scores."""
    if not update.message or update.message.reply_to_message:
        return  # Skip if it's a reply message (handled by handle_reply)
    
    # Only work in groups
    if update.effective_chat.type == 'private':
        return
    
    # Check if this might be a test scores message
    message_text = update.message.text
    if not message_text or '\n' not in message_text:
        return  # Not a multi-line message
    
    # Only process if user is admin/owner (quick check to avoid unnecessary processing)
    user_id = update.message.from_user.id
    group_id = update.effective_chat.id
    
    if not await is_admin_or_owner(context, group_id, user_id):
        return
    
    # Handle potential test scores
    await handle_test_scores(update, context)

# === Leaderboard function ===
async def send_leaderboard(context: CallbackContext):
    group_id = context.job.context
    points = load_group_points(group_id)
    
    if not points:
        await context.bot.send_message(group_id, "📭 مفيش حد خد نقط الأسبوع ده!")
        return

    try:
        # Get group name
        chat = await context.bot.get_chat(group_id)
        group_name = chat.title
    except:
        group_name = f"جروب {group_id}"

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
    
    await context.bot.send_message(
        chat_id=group_id,
        text=f"🏆 قايمة المتصدرين الأسبوعية 🏆\n"
             f"الجروب: {group_name}\n\n" + "\n".join(leaderboard)
    )
    
    # Reset points for this group
    save_group_points(group_id, {})
    print(f"♻️ Weekly points reset for group {group_id} after leaderboard")

# === Schedule leaderboard ===
def schedule_leaderboard(application: Application, group_id: int):
    if not application.job_queue:
        return
    
    # Remove existing jobs for this group
    job_name = f"weekly_leaderboard_{group_id}"
    current_jobs = application.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    
    # Schedule new job (Saturday 6 AM UTC)
    application.job_queue.run_daily(
        send_leaderboard,
        time=datetime.time(hour=6, minute=0, tzinfo=pytz.UTC),
        days=(5,),  # Saturday (0=Monday, 6=Sunday)
        context=group_id,
        name=job_name
    )
    print(f"⏰ Scheduled weekly leaderboard for group {group_id} on Saturdays at 06:00 UTC")

# === Load and schedule existing groups ===
def load_existing_groups(application: Application):
    if not GROUPS_DATA_DIR.exists():
        return
    
    # Find all group data files
    group_ids = set()
    for file in GROUPS_DATA_DIR.iterdir():
        if file.name.startswith('points_') and file.name.endswith('.json'):
            try:
                group_id = int(file.name.replace('points_', '').replace('.json', ''))
                group_ids.add(group_id)
            except ValueError:
                continue
    
    # Schedule leaderboards for existing groups
    for group_id in group_ids:
        schedule_leaderboard(application, group_id)
        print(f"🔍 Found and scheduled existing group: {group_id}")

# === Main bot function ===
def main():
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("dash", dash_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, save_group_and_admins))
    application.add_handler(MessageHandler(filters.TEXT & filters.REPLY, handle_reply))
    # Add handler for multi-line messages (test scores) with lower priority
    application.add_handler(MessageHandler(filters.TEXT & ~filters.REPLY & ~filters.COMMAND, handle_message))
    
    # Load existing groups and schedule jobs
    load_existing_groups(application)
    
    # Start the bot
    print("🤖 البوت شغال دلوقتي...")
    application.run_polling()

if __name__ == '__main__':
    main()
