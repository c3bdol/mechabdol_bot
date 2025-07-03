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

def get_group_users_file(group_id: int) -> Path:
    return GROUPS_DATA_DIR / f'users_{group_id}.json'

# === Load/Save username mappings ===
def load_group_users(group_id: int) -> dict:
    """Load username -> user_id mappings for this group"""
    users_file = get_group_users_file(group_id)
    if users_file.exists():
        try:
            with open(users_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    return {}

def save_group_users(group_id: int, users: dict):
    """Save username -> user_id mappings for this group"""
    users_file = get_group_users_file(group_id)
    with open(users_file, 'w') as f:
        json.dump(users, f)

def update_user_mapping(group_id: int, user_id: int, username: str = None, full_name: str = None):
    """Update user mapping with username and full name"""
    users = load_group_users(group_id)
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        users[user_id_str] = {}
    
    if username:
        users[user_id_str]['username'] = username.lower()
    if full_name:
        users[user_id_str]['full_name'] = full_name
    
    save_group_users(group_id, users)

def find_user_by_username(group_id: int, username: str) -> int:
    """Find user ID by username from stored mappings"""
    users = load_group_users(group_id)
    username_lower = username.lower()
    
    for user_id_str, user_data in users.items():
        if user_data.get('username', '').lower() == username_lower:
            return int(user_id_str)
    
    return None

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

# === Enhanced user ID resolution ===
async def get_user_id_from_username(context: ContextTypes.DEFAULT_TYPE, group_id: int, username: str) -> int:
    """
    Try multiple methods to get user ID from username
    """
    # Method 1: Check stored mappings first
    user_id = find_user_by_username(group_id, username)
    if user_id:
        return user_id
    
    # Method 2: Try direct API call
    try:
        member = await context.bot.get_chat_member(group_id, f"@{username}")
        if member and member.user:
            # Store this mapping for future use
            update_user_mapping(group_id, member.user.id, username, member.user.full_name)
            return member.user.id
    except Exception as e:
        print(f"⚠️ Could not get user @{username} via API: {e}")
    
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
        user_id_found = None
        
        # First, check if there are any text mentions in the message
        if update.message.entities:
            for entity in update.message.entities:
                if entity.type == 'text_mention':
                    # Direct mention with user object
                    mention_text = message_text[entity.offset:entity.offset + entity.length]
                    if mention_text.lower() == f"@{username.lower()}" or mention_text.lower() == username.lower():
                        user_id_found = entity.user.id
                        # Store this mapping
                        update_user_mapping(group_id, entity.user.id, username, entity.user.full_name)
                        break
        
        # If not found in text mentions, try username resolution
        if user_id_found is None:
            user_id_found = await get_user_id_from_username(context, group_id, username)
        
        if user_id_found:
            user_id_str = str(user_id_found)
            points[user_id_str] = points.get(user_id_str, 0) + score
            
            # Get user's display name
            users = load_group_users(group_id)
            user_data = users.get(user_id_str, {})
            display_name = user_data.get('full_name', username)
            
            successful_updates.append(f"✅ {display_name}: +{score} نقطة (المجموع: {points[user_id_str]})")
        else:
            failed_updates.append(f"❌ {username}: لم يتم العثور على المستخدم")
    
    # Save updated points if there were successful updates
    if successful_updates:
        save_group_points(group_id, points)
    
    # Send response with suggestions for failed updates
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
            response_lines.append("")
            response_lines.append("💡 نصائح لحل المشكلة:")
            response_lines.append("• تأكد من كتابة اليوزرنيم صح")
            response_lines.append("• استخدم منشن مباشر (@username)")
            response_lines.append("• تأكد ان المستخدم متفاعل في الجروب")
        
        await update.message.reply_text("\n".join(response_lines))

# === Track all messages to build user mappings ===
async def track_user_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track user activity to build username mappings"""
    if update.effective_chat.type == 'private':
        return
    
    if update.message and update.message.from_user:
        user = update.message.from_user
        group_id = update.effective_chat.id
        
        # Update user mapping
        update_user_mapping(
            group_id=group_id,
            user_id=user.id,
            username=user.username,
            full_name=user.full_name
        )

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
        "/reset - مسح النقط كلها (الأدمنز/صاحب الجروب بس)\n"
        "/users - عرض قائمة الأعضاء المحفوظين\n\n"
        f"زيادة نقط: {', '.join(KEYWORDS)}\n"
        f"نقص نقط: {', '.join(SUBTRACT_KEYWORDS)}\n\n"
        "📝 إضافة نقاط امتحانات:\n"
        "اكتب رسالة بالشكل ده:\n"
        "@username1 85\n"
        "@username2 92\n"
        "username3 78\n\n"
        "💡 نصائح لإضافة النقاط:\n"
        "• استخدم منشن مباشر (@username)\n"
        "• تأكد ان الأعضاء متفاعلين في الجروب\n"
        "• البوت يحفظ معلومات الأعضاء تلقائياً"
    )

# === /users command - show stored users ===
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if command is in group
    if update.effective_chat.type == 'private':
        await update.message.reply_text("⛔ الأمر ده بيشتغل في الجروبات بس!")
        return
    
    # Check if user is admin or owner
    user_id = update.message.from_user.id
    group_id = update.effective_chat.id
    
    if not await is_admin_or_owner(context, group_id, user_id):
        await update.message.reply_text("⛔ لازم تكون أدمن أو صاحب الجروب علشان تشوف قائمة الأعضاء!")
        return
    
    users = load_group_users(group_id)
    
    if not users:
        await update.message.reply_text("📭 مفيش أعضاء محفوظين لسه! الأعضاء هيتحفظوا لما يكتبوا رسايل.")
        return
    
    user_list = []
    for user_id_str, user_data in users.items():
        username = user_data.get('username', 'لا يوجد')
        full_name = user_data.get('full_name', 'غير محدد')
        user_list.append(f"• {full_name} (@{username})")
    
    # Split into chunks if too long
    message = f"👥 الأعضاء المحفوظين ({len(users)} عضو):\n\n" + "\n".join(user_list)
    
    if len(message) > 4000:
        # Split message
        chunks = []
        current_chunk = f"👥 الأعضاء المحفوظين ({len(users)} عضو):\n\n"
        
        for user_line in user_list:
            if len(current_chunk + user_line + "\n") > 4000:
                chunks.append(current_chunk)
                current_chunk = user_line + "\n"
            else:
                current_chunk += user_line + "\n"
        
        if current_chunk:
            chunks.append(current_chunk)
        
        for chunk in chunks:
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_text(message)

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

    # Create leaderboard using stored user data
    users = load_group_users(group_id)
    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        user_data = users.get(uid, {})
        name = user_data.get('full_name', f"يوزر {uid}")
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
                
                # Store admin/owner user mapping
                update_user_mapping(
                    group_id=group_id,
                    user_id=admin.user.id,
                    username=admin.user.username,
                    full_name=admin.user.full_name
                )
            
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
                "/reset - مسح النقط (الأدمنز/صاحب الجروب بس)\n"
                "/users - عرض قائمة الأعضاء المحفوظين\n\n"
                f"الكلمات المفتاحية: {', '.join(KEYWORDS)}\n"
                f"كلمة النقص: {', '.join(SUBTRACT_KEYWORDS)}\n\n"
                "📝 إضافة نقاط امتحانات:\n"
                "اكتب رسالة بالشكل ده:\n"
                "@username1 85\n"
                "@username2 92\n"
                "username3 78\n\n"
                "💡 البوت هيحفظ معلومات الأعضاء تلقائياً عشان يقدر يديهم نقط بسهولة!"
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

    # Track user activity
    await track_user_activity(update, context)

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
        
        # Update user mapping
        update_user_mapping(group_id, replied_user.id, replied_user.username, replied_user.full_name)
        
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
        
        # Update user mapping
        update_user_mapping(group_id, replied_user.id, replied_user.username, replied_user.full_name)
        
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
    
    # Track user activity
    await track_user_activity(update, context)
    
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

    # Use stored user data for leaderboard
    users = load_group_users(group_id)
    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        user_data = users.get(uid, {})
        name = user_data.get('full_name', f"يوزر {uid}")
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
    for file in GROUPS_DATA_DIR.iterdir
