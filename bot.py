import logging
import telebot
from database import database
import config
from handlers import register_all
from utils import helpers, state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("kkwieer_bot")

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode=None)

HELP_TEXT = (
    "❓ KKWIEER Lost & Found Help\n\n"
    "This bot helps K. K. Wagh students and staff report lost or found items.\n\n"
    "What you can do:\n"
    "• Register with /start\n"
    "• Report a lost item\n"
    "• Report a found item\n"
    "• Search with a keyword, category, or location\n"
    "• View and manage your own reports\n"
    "• Mark items recovered or returned\n"
    "• Read your notifications\n"
    "• Contact a reporter through the bot\n"
    "• Report a suspicious listing\n\n"
    "Privacy:\n"
    "Phone numbers, email addresses, and Telegram IDs are never shown to other users.\n\n"
    "Search does not show the complete Lost & Found database. "
    "Full listings are only available to administrators.\n\n"
    "Use /start or 🏠 Main Menu if you get stuck."
)


def register_core_handlers(bot):
    @bot.message_handler(commands=["help"])
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "❓ Help")
    def handle_help(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        helpers.safe_send(bot, message.chat.id, HELP_TEXT)

    @bot.message_handler(commands=["menu", "cancel"])
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text in ("🏠 Main Menu", "⬅️ Back", "❌ Cancel"))
    def handle_main_menu(message):
        state.clear_user(message.chat.id)
        try:
            bot.clear_step_handler_by_chat_id(message.chat.id)
        except Exception:
            pass
        if not helpers.get_registered_user(bot, message.from_user.id, message.chat.id):
            return
        helpers.show_main_menu(bot, message)


def register_fallbacks(bot):
    @bot.callback_query_handler(func=lambda call: True)
    def unknown_callback(call):
        helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)

    @bot.message_handler(content_types=["text", "photo", "document", "sticker", "audio", "video", "voice", "location", "contact"])
    def fallback(message):
        if message.content_type == "text" and message.text in ("/start", "/help", "/menu", "/cancel"):
            return
        if message.chat.id in state.contact_mode and message.content_type == "text":
            helpers.safe_send(
                bot,
                message.chat.id,
                "To send a private message about a listing, tap 💬 Send Message first.",
            )
            return
        helpers.safe_send(bot, message.chat.id, "I didn't understand that. Please use the menu buttons.")


def main():
    try:
        database.init_db()
    except Exception:
        logger.exception("Database initialization failed")
        raise

    # Register specific handlers first
    register_all(bot)
    register_core_handlers(bot)

    # Register fallbacks last so they do not shadow legitimate handlers
    register_fallbacks(bot)

    logger.info("KKWIEER Lost & Found bot is running. Press Ctrl+C to stop.")
    print("Bot is successfully running... Press Ctrl+C in terminal to stop.")
    bot.infinity_polling(none_stop=True, timeout=60, long_polling_timeout=60, logger_level=logging.INFO)


if __name__ == "__main__":
    main()
