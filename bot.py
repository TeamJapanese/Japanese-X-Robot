import asyncio
import aiosqlite
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ChatMemberHandler, CallbackQueryHandler, filters, ContextTypes
)
from functools import wraps

# ========== CONFIG ==========
OWNER_ID = 7208410467
TOKEN = "YOUR_BOT_TOKEN"  # Replace this with your bot token
MAX_WARN = 3

# ========== DATABASE SETUP ==========
async def init_db():
    async with aiosqlite.connect("data.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                chat_id INTEGER,
                user_id INTEGER,
                count INTEGER,
                PRIMARY KEY(chat_id, user_id)
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                chat_id INTEGER PRIMARY KEY,
                text TEXT
            )""")
        await db.commit()

# ========== OWNER CHECK DECORATOR ==========
def owner_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != OWNER_ID:
            await update.message.reply_text("🚫 Access Denied. Only the bot owner can use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("こんにちは！私はJapanese X管理ボットです 🇯🇵✨")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
Available Commands:
/start - Start the bot
/help - Show help
/id - Get your Telegram ID
/ban @user - Ban user
/mute @user - Mute user
/unmute @user - Unmute user
/warn @user - Warn user
/warns @user - Show user warnings
/resetwarn @user - Reset user warnings
/rules - Show group rules
/setrules <text> - Set custom rules (admin only)
/button - Test button (fun feature)
/eval <code> - Owner only
/shutdown - Owner only
""")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    await update.message.reply_text(f"User ID: `{uid}`\nChat ID: `{cid}`", parse_mode="Markdown")

async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect("data.db") as db:
        cursor = await db.execute("SELECT text FROM rules WHERE chat_id=?", (update.effective_chat.id,))
        row = await cursor.fetchone()
        if row:
            await update.message.reply_text(f"📜 Group Rules:\n{row[0]}")
        else:
            await update.message.reply_text("📜 No rules set yet. Use /setrules to define group rules.")

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    rule_text = " ".join(context.args)
    if not rule_text:
        await update.message.reply_text("⚠️ Please provide rules text.")
        return
    async with aiosqlite.connect("data.db") as db:
        await db.execute("REPLACE INTO rules (chat_id, text) VALUES (?, ?)", (update.effective_chat.id, rule_text))
        await db.commit()
    await update.message.reply_text("✅ Group rules updated!")

async def button_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Click Me", callback_data="clicked")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Press the button below!", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎉 You clicked the button!")

@owner_only
async def eval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = " ".join(context.args)
    try:
        result = eval(code)
        await update.message.reply_text(f"✅ Result: {result}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

@owner_only
async def shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Shutting down... 📴")
    await context.application.stop()  # Stop safely without crashing the loop

# ========== ADMIN COMMANDS ==========
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    user = await extract_user(update)
    if user:
        await update.effective_chat.ban_member(user.id)
        await update.message.reply_text(f"Banned {user.mention_html()}", parse_mode="HTML")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    user = await extract_user(update)
    if user:
        await update.effective_chat.restrict_member(user.id, ChatPermissions())
        await update.message.reply_text(f"Muted {user.mention_html()}", parse_mode="HTML")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    user = await extract_user(update)
    if user:
        await update.effective_chat.restrict_member(user.id, ChatPermissions(can_send_messages=True))
        await update.message.reply_text(f"Unmuted {user.mention_html()}", parse_mode="HTML")

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    user = await extract_user(update)
    if user:
        async with aiosqlite.connect("data.db") as db:
            await db.execute("""
                INSERT INTO warns (chat_id, user_id, count)
                VALUES (?, ?, 1)
                ON CONFLICT(chat_id, user_id)
                DO UPDATE SET count = count + 1
            """, (update.effective_chat.id, user.id))
            await db.commit()

            cursor = await db.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (update.effective_chat.id, user.id))
            row = await cursor.fetchone()
            count = row[0] if row else 0

        await update.message.reply_text(f"{user.mention_html()} has been warned ({count}/{MAX_WARN})", parse_mode="HTML")

        if count >= MAX_WARN:
            await update.effective_chat.ban_member(user.id)
            await update.message.reply_text(f"{user.mention_html()} was auto-banned for reaching {MAX_WARN} warnings.", parse_mode="HTML")

async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await extract_user(update)
    if user:
        async with aiosqlite.connect("data.db") as db:
            cursor = await db.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (update.effective_chat.id, user.id))
            row = await cursor.fetchone()
            count = row[0] if row else 0
        await update.message.reply_text(f"{user.mention_html()} has {count} warning(s).", parse_mode="HTML")

async def resetwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    user = await extract_user(update)
    if user:
        async with aiosqlite.connect("data.db") as db:
            await db.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (update.effective_chat.id, user.id))
            await db.commit()
        await update.message.reply_text(f"✅ Reset warnings for {user.mention_html()}.", parse_mode="HTML")

# ========== WELCOME MESSAGE ==========
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = update.chat_member
    if member.new_chat_member.status == "member":
        await update.effective_chat.send_message(f"ようこそ {member.new_chat_member.user.mention_html()}！", parse_mode="HTML")

# ========== UTILITY ==========
async def extract_user(update: Update):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    return None

async def is_admin(update: Update):
    member = await update.effective_chat.get_member(update.effective_user.id)
    if member.status not in ("administrator", "creator"):
        await update.message.reply_text("❌ You must be admin to use this command.")
        return False
    return True

# ========== MAIN ==========
async def main():
    await init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("warns", warns))
    app.add_handler(CommandHandler("resetwarn", resetwarn))
    app.add_handler(CommandHandler("eval", eval_cmd))
    app.add_handler(CommandHandler("shutdown", shutdown))
    app.add_handler(CommandHandler("button", button_cmd))

    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(ChatMemberHandler(welcome, ChatMemberHandler.CHAT_MEMBER))

    print("Bot running... ")
    await app.run_polling()

# Use asyncio.run to avoid loop errors
if __name__ == "__main__":
    asyncio.run(main())
