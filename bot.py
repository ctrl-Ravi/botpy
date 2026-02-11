import os
import re
import threading
import time
import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler,
    CommandHandler, ConversationHandler
)

def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    
    print("KeepAlive URL:", url)

    if not url:
        print("KeepAlive: RENDER_EXTERNAL_URL not found")
        return

    while True:
        try:
            requests.get(url, timeout=10)
            print("KeepAlive ping sent")
        except Exception as e:
            print("KeepAlive error:", e)

        time.sleep(600)


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
- You MUST paraphrase: change sentence structure & wording 
- You MAY add light relatable emojis for readability 
- Keep meaning, price, coupon, and ALL links EXACTLY same  
- Same language as original (Hindi/Hinglish/English)  
- Keep {length_rule}

DO NOT:
- Add any new facts or claims  
- Add benefits, CTA, urgency or marketing lines  
- Ask questions or give suggestions  
- Write as an assistant or add explanations  
- Repeat original sentences word-to-word
- Use words like "Part 1/Title/Body"

If input is non-deal content, still rewrite it as neutral text without adding opinions.

OUTPUT ONLY the rewritten content. No extra text.
"""


# ================= GEMINI CALL =================

async def call_ai(text: str, user_id: int, mode: str = "normal") -> str:
    # ---- Link Protection: Extract & Hide Links ----
    
    links_storage = {}
    
    def link_replacer(match):
        # Generate a unique placeholder
        placeholder = f"__LINK_{len(links_storage)}__"
        # Store the actual link
        links_storage[placeholder] = match.group(0)
        return placeholder

    # Replace all links with placeholders like __LINK_0__, __LINK_1__
    text_with_placeholders = re.sub(r'https?://\S+', link_replacer, text)

    setting = USER_SETTINGS.get(user_id, {})
    custom_prompt = setting.get("prompt", DEFAULT_PROMPT)

    length_rule = "normal length"
    if mode == "short":
        length_rule = "very short"

    prompt = f"""
{custom_prompt}

CRITICAL: 
The input text contains placeholders like __LINK_0__, __LINK_1__.
You MUST output these placeholders EXACTLY as they are in the rewritten text.
Do NOT change them to [Link], URL, or anything else.
Keep them in the correct position relative to the product/item.

Extra Rule: {length_rule}

ORIGINAL POST:
{text_with_placeholders}
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

        # ---- Restore Links ----
        # Loop through stored links and put them back
        # We do this carefully to avoid any partial matches, though placeholders are unique enough
        for placeholder, original_link in links_storage.items():
            output = output.replace(placeholder, original_link)

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
# ================= welcom message =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Mujhe koi DEAL POST bhejo — main usko fresh style me rewrite kar dunga 😎\n\n"
        "Features:\n"
        "• Title + Body format\n"
        "• Links same rahenge\n"
        "• Light emojis\n\n"
        "Bas message paste/forward karo 🚀"
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
/help – How to use 
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


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
            📘 HOW TO USE – QUICK GUIDE
            
            1️⃣ Paste/ Forward any deal post like:
            • Amazon / Flipkart offers  
            • Coupon deals  
            • Telegram deal text  
            
            2️⃣ Bot will generate:
            TITLE  
            BODY  
            
            3️⃣ Buttons:
            🔁 Another Style – new rewrite  
            🩳 Short – compact version  
            📋 Copy – easy copy  
            
            RULES FOLLOWED:
            • Links never changed  
            • Price & coupon safe  
            • No fake claims added  
            
            — Pelupa Store Bot
        """
    await update.message.reply_text(text)



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

    # ----- COMMAND HANDLERS -----
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("clearprompt", clear_prompt))

    # ----- CONVERSATION -----
    conv = ConversationHandler(
        entry_points=[CommandHandler("setprompt", ask_prompt)],
        states={
            SET_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_prompt)
            ]
        },
        fallbacks=[]
    )

    app.add_handler(conv)

    # ----- CALLBACK BUTTONS -----
    app.add_handler(CallbackQueryHandler(again_callback, pattern="again"))
    app.add_handler(CallbackQueryHandler(short_callback, pattern="short"))
    app.add_handler(CallbackQueryHandler(copy_title, pattern="copy_title"))
    app.add_handler(CallbackQueryHandler(copy_body, pattern="copy_body"))

    # ----- NORMAL MESSAGE HANDLER (LAST) -----
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message
        )
    )

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
    threading.Thread(target=keep_alive, daemon=True).start()
    # -------------------------------------

    print("Bot Started...")
    app.run_polling()

# def main():

#     if TELEGRAM_TOKEN is None:
#         print("ERROR: TELEGRAM_TOKEN missing in secrets")
#         return


#     app = Application.builder().token(TELEGRAM_TOKEN).build()
    
#     app.add_handler(CommandHandler("start", start))
#     app.add_handler(
#         MessageHandler(
#             (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
#             handle_message
#         )
#     )

#     app.add_handler(CallbackQueryHandler(again_callback, pattern="again"))
#     app.add_handler(CallbackQueryHandler(short_callback, pattern="short"))
#     app.add_handler(CallbackQueryHandler(copy_title, pattern="copy_title"))
#     app.add_handler(CallbackQueryHandler(copy_body, pattern="copy_body"))

#     app.add_handler(CommandHandler("settings", settings))
#     app.add_handler(CommandHandler("clearprompt", clear_prompt))

#     conv = ConversationHandler(
#         entry_points=[CommandHandler("setprompt", ask_prompt)],
#         states={SET_PROMPT: [MessageHandler(filters.TEXT, save_prompt)]},
#         fallbacks=[]
#     )

#     app.add_handler(conv)

#         # ---- Fake HTTP server for Render ----
#     class Handler(BaseHTTPRequestHandler):
#         def do_GET(self):
#             self.send_response(200)
#             self.end_headers()
#             self.wfile.write(b"Bot is running")
    
#     def run_server():
#         port = int(os.environ.get("PORT", 10000))
#         server = HTTPServer(("0.0.0.0", port), Handler)
#         server.serve_forever()
    
#     threading.Thread(target=run_server, daemon=True).start()
#     # -------------------------------------


#     print("Bot Started...")
#     app.run_polling()


if __name__ == "__main__":
    main()
