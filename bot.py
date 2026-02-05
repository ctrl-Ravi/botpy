import os
import re
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler,
    CommandHandler, ConversationHandler
)

TELEGRAM_TOKEN: str | None = os.environ.get('TELEGRAM_TOKEN')
GEMINI_KEY: str | None = os.environ.get('GEMINI_KEY')

USER_TEXT: dict[int, str] = {}
LAST_TITLE: dict[int, str] = {}
LAST_BODY: dict[int, str] = {}
USER_SETTINGS: dict[int, dict] = {}

SET_PROMPT = 1

# -------- DEFAULT PROMPT --------
DEFAULT_PROMPT = """
You are STRICTLY a DEAL POST REWRITER.

TASK:
Rewrite the given text ONLY. Treat input as a deal/offer post.

FORMAT:
- FIRST LINE = TITLE  
- REMAINING = BODY

RULES:
- You MUST paraphrase – change sentence structure & wording  
- Keep meaning, price, coupon, and ALL links EXACTLY same  
- Same language as original (Hindi/Hinglish/English)  
- Add some relatable emojis for better look
- Keep {length_rule}

DO NOT:
- Add any new information  
- Add benefits, CTA, or marketing claims  
- Ask questions or suggestions  
- Write help/tutorial/community text  
- Act like an assistant  
- Use words like "Part 1/Title/Body"  
- Repeat sentences from original as-is

If input is non-deal content, still rewrite it as neutral text without adding opinions.
If input is /settings, /setprompt, /clearprompt don't rewrite because its setting

Rewrite ONLY the provided content.
"""


# ================= GEMINI CALL =================

async def call_ai(text: str, user_id: int, mode: str = "normal") -> str:

    links = re.findall(r'https?://\S+', text)

    setting = USER_SETTINGS.get(user_id, {})
    custom_prompt = setting.get("prompt", DEFAULT_PROMPT)

    length_rule = "normal length"
    if mode == "short":
        length_rule = "very short"

    prompt = f"""
{custom_prompt}

Extra Rule: {length_rule}

ORIGINAL POST:
{text}
"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ.get('OPENROUTER_KEY')}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost",
                "X-Title": "telegram-bot"
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7
            },
            timeout=60
        )

        data = response.json()

        output = data["choices"][0]["message"]["content"]

        if not output:
            return "AI empty response"

        # ---- Link Protection ----
        for link in links:
            output = re.sub(r'https?://\S+', link, output, count=1)

        return output

    except Exception as e:
        return f"Rewrite error: {str(e)}"


# ================= BUTTONS =================

def buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔁 Another Style", callback_data="again"),
            InlineKeyboardButton("🩳 Short", callback_data="short")
        ],
        [
            InlineKeyboardButton("📋 Copy Title", callback_data="copy_title"),
            InlineKeyboardButton("📋 Copy Body", callback_data="copy_body")
        ]
    ])


# ================= MESSAGE HANDLER =================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    message: Message | None = update.message
    if message is None:
        return

    text: str | None = message.text if message.text else message.caption

    if not text:
        await message.reply_text("Text ya caption bhejo bhai")
        return

    user = message.from_user
    if user is None:
        return

    user_id: int = user.id

    await message.reply_text("Rewriting... ⏳")

    new_text = await call_ai(text, user_id)

    parts = new_text.split("\n", 1)

    title = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else new_text.strip()

    LAST_TITLE[user_id] = title
    LAST_BODY[user_id] = body
    USER_TEXT[user_id] = text

    await message.reply_text(
        f"TITLE:\n{title}\n\nBODY:\n{body}",
        reply_markup=buttons()
    )


# ================= SETTINGS =================

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    message = update.message
    if message is None:
        return

    await message.reply_text("""
⚙️ COMMANDS

/setprompt – Custom prompt  
/clearprompt – Default
""")


async def ask_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message is None:
        return ConversationHandler.END

    await message.reply_text("Apna custom prompt likho 👇")
    return SET_PROMPT


async def save_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    if message is None:
        return ConversationHandler.END

    user = message.from_user
    if user is None:
        return ConversationHandler.END

    user_id = user.id
    text = message.text or ""

    USER_SETTINGS.setdefault(user_id, {})
    USER_SETTINGS[user_id]["prompt"] = text

    await message.reply_text("✅ Custom prompt saved!")
    return ConversationHandler.END


async def clear_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    if message is None:
        return

    user = message.from_user
    if user is None:
        return

    user_id = user.id

    USER_SETTINGS.setdefault(user_id, {})
    USER_SETTINGS[user_id]["prompt"] = DEFAULT_PROMPT

    await message.reply_text("Default prompt restore ho gaya")


# ================= CALLBACKS =================

async def regenerate(update: Update, mode: str = "normal"):

    query = update.callback_query
    if query is None:
        return

    user = query.from_user
    if user is None:
        return

    user_id = user.id
    await query.answer()

    text = USER_TEXT.get(user_id)

    if not text:
        await query.message.reply_text("Pehle koi post bhejo")
        return

    new_text = await call_ai(text, user_id, mode)

    parts = new_text.split("\n", 1)

    title = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else new_text.strip()

    LAST_TITLE[user_id] = title
    LAST_BODY[user_id] = body

    await query.message.reply_text(
        f"TITLE:\n{title}\n\nBODY:\n{body}",
        reply_markup=buttons()
    )


async def again_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await regenerate(update, "normal")


async def short_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await regenerate(update, "short")


async def copy_title(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    if query is None:
        return

    user = query.from_user
    if user is None:
        return

    user_id = user.id
    await query.answer()

    title = LAST_TITLE.get(user_id)

    if title:
        await query.message.reply_text(title)


async def copy_body(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    if query is None:
        return

    user = query.from_user
    if user is None:
        return

    user_id = user.id
    await query.answer()

    body = LAST_BODY.get(user_id)

    if body:
        await query.message.reply_text(body)


# ================= MAIN =================

def main():

    if TELEGRAM_TOKEN is None:
        print("ERROR: TELEGRAM_TOKEN missing in secrets")
        return


    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT | filters.CAPTION, handle_message)
    )

    app.add_handler(CallbackQueryHandler(again_callback, pattern="again"))
    app.add_handler(CallbackQueryHandler(short_callback, pattern="short"))
    app.add_handler(CallbackQueryHandler(copy_title, pattern="copy_title"))
    app.add_handler(CallbackQueryHandler(copy_body, pattern="copy_body"))

    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("clearprompt", clear_prompt))

    conv = ConversationHandler(
        entry_points=[CommandHandler("setprompt", ask_prompt)],
        states={SET_PROMPT: [MessageHandler(filters.TEXT, save_prompt)]},
        fallbacks=[]
    )

    app.add_handler(conv)

        # ---- Fake HTTP server for Render ----
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")
    
    def run_server():
        port = int(os.environ.get("PORT", 10000))
        server = HTTPServer(("0.0.0.0", port), Handler)
        server.serve_forever()
    
    threading.Thread(target=run_server, daemon=True).start()
    # -------------------------------------


    print("Bot Started...")
    app.run_polling()


if __name__ == "__main__":
    main()
