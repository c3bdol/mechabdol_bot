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

# === /start command ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 مرحباً! أنا بوت النقاط!\n\n"
        "طريقة عملي:\n"
        "1. أضفني إلى مجموعة\n"
        "2. المشرفون ومالك المجموعة يمكنهم الرد على الرسائل بكلمات مفتاحية لإضافة/خصم النقاط\n"
        "3. سأنشر جدول المتصدرين الأسبوعي كل يوم سبت\n\n"
        "الأوامر (المجموعات فقط):\n"
        "/dash - عرض جدول المتصدرين الحالي\n"
        "/reset - إعادة تعيين النقاط (المشرفون/المالك فقط)\n\n"
        f"إضافة نقاط: {', '.join(KEYWORDS)}\n"
        f"خصم نقاط: {', '.join(SUBTRACT_KEYWORDS)}"
    )

# === /dash command - show current leaderboard ===
async def dash_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if command is in group
    if update.effective_chat.type == 'private':
        await update.message.reply_text("⛔ هذا الأمر يمكن استخدامه في المجموعات فقط!")
        return
    
    group_id = update.effective_chat.id
    points = load_group_points(group_id)
    
    if not points:
        await update.message.reply_text("📊 لا توجد نقاط بعد! ابدأ بمنح النقاط من خلال الرد على الرسائل بالكلمات المفتاحية.")
        return

    # Create leaderboard
    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        try:
            user = await context.bot.get_chat_member(group_id, int(uid))
            name = user.user.full_name
        except:
            name = f"مستخدم {uid}"
        leaderboard.append(f"{idx+1}. {name} - {pts} pts")
    
    # Add emoji indicators for top 3
    if len(leaderboard) > 0:
        leaderboard[0] = "🥇 " + leaderboard[0]
    if len(leaderboard) > 1:
        leaderboard[1] = "🥈 " + leaderboard[1]
    if len(leaderboard) > 2:
        leaderboard[2] = "🥉 " + leaderboard[2]
    
    await update.message.reply_text(
        f"📊 جدول المتصدرين الحالي 📊\n"
        f"المجموعة: {update.effective_chat.title}\n\n" + "\n".join(leaderboard)
    )

# === /reset command - reset all points (admin/owner only) ===
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if command is in group
    if update.effective_chat.type == 'private':
        await update.message.reply_text("⛔ هذا الأمر يمكن استخدامه في المجموعات فقط!")
        return
    
    user_id = update.message.from_user.id
    group_id = update.effective_chat.id
    
    # Check if user is admin or owner
    if not await is_admin_or_owner(context, group_id, user_id):
        await update.message.reply_text("⛔ تحتاج إلى أن تكون مشرفاً أو مالك المجموعة لإعادة تعيين النقاط!")
        return
        
    # Reset points for this group
    save_group_points(group_id, {})
    
    await update.message.reply_text("✅ تم إعادة تعيين جدول المتصدرين! تم مسح جميع النقاط لهذه المجموعة.")
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
                f"✅ Bot initialized for group: {chat.title}\n\n"
                "Commands:\n"
                "/dash - Show current leaderboard\n"
                "/reset - Reset points (admins/owner only)\n\n"
                f"Keywords: {', '.join(KEYWORDS)}\n"
                f"Subtract keyword: {', '.join(SUBTRACT_KEYWORDS)}"
            )
        except Exception as e:
            print(f"❌ Error saving group data for {group_id}: {e}")
            await context.bot.send_message(
                chat.id,
                "⚠️ لا يمكن تهيئة البوت بالكامل. يرجى التأكد من أن لدي صلاحيات المشرف."
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

    # Prevent self-awarding
    if user_id == replied_user.id:
        await update.message.reply_text("⛔ لا يمكنك منح نقاط لنفسك!")
        return
    
    # Prevent awarding points to bots
    if replied_user.is_bot:
        await update.message.reply_text("⛔ لا يمكن منح نقاط للبوتات!")
        return

    # Check keyword for adding points
    text = update.message.text.lower().strip()
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
                f"⚠️ {replied_user.full_name} لديه 0 نقطة بالفعل! لا يمكن خصم المزيد."
            )

# === Leaderboard function ===
async def send_leaderboard(context: CallbackContext):
    group_id = context.job.context
    points = load_group_points(group_id)
    
    if not points:
        await context.bot.send_message(group_id, "📭 لم يتم منح نقاط هذا الأسبوع!")
        return

    try:
        # Get group name
        chat = await context.bot.get_chat(group_id)
        group_name = chat.title
    except:
        group_name = f"مجموعة {group_id}"

    sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=True)
    leaderboard = []
    
    for idx, (uid, pts) in enumerate(sorted_points):
        try:
            user = await context.bot.get_chat_member(group_id, int(uid))
            name = user.user.full_name
        except:
            name = f"مستخدم {uid}"
        leaderboard.append(f"{idx+1}. {name} - {pts} pts")
    
    # Add emoji indicators for top 3
    if len(leaderboard) > 0:
        leaderboard[0] = "🥇 " + leaderboard[0]
    if len(leaderboard) > 1:
        leaderboard[1] = "🥈 " + leaderboard[1]
    if len(leaderboard) > 2:
        leaderboard[2] = "🥉 " + leaderboard[2]
    
    await context.bot.send_message(
        chat_id=group_id,
        text=f"🏆 جدول المتصدرين الأسبوعي 🏆\n"
             f"المجموعة: {group_name}\n\n" + "\n".join(leaderboard)
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
    
    # Load existing groups and schedule jobs
    load_existing_groups(application)
    
    # Start the bot
    print("🤖 بدء تشغيل البوت متعدد المجموعات...")
    application.run_polling()

if __name__ == '__main__':
    main()
