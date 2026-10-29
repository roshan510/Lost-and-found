import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from database import database
from utils import helpers, state
from handlers import item_flow

logger = logging.getLogger(__name__)


def register(bot):
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🔔 Notifications")
    def open_notifications(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        send_notification_list(bot, message.chat.id, message.from_user.id, 0)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("nf:"))
    def handle_notification_callback(call):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return
        parts = call.data.split(":")
        if len(parts) < 3:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        action = parts[1]
        if not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        value = int(parts[2])
        helpers.safe_answer(bot, call)
        if action == "p":
            send_notification_list(bot, call.message.chat.id, call.from_user.id, value)
            return
        if action == "v":
            notif = database.get_notification_for_user(value, call.from_user.id)
            if not notif:
                helpers.safe_send(bot, call.message.chat.id, "You cannot open this notification.")
                return
            database.mark_notification_read(value, call.from_user.id)
            helpers.safe_send(
                bot,
                call.message.chat.id,
                f"🔔 {notif['notification_type'] or 'Notice'}\n\n{notif['message']}",
            )


def send_notification_list(bot, chat_id, telegram_id, page):
    limit = 10
    offset = page * limit
    try:
        rows, total = database.get_user_notifications(telegram_id, limit=limit, offset=offset)
    except Exception:
        logger.exception("Failed to load notifications")
        helpers.safe_send(bot, chat_id, "Something went wrong. Please try again.")
        return
    if total == 0:
        helpers.safe_send(bot, chat_id, "You have no notifications yet.")
        return
    lines = ["🔔 Your Notifications", ""]
    inline = InlineKeyboardMarkup()
    for row in rows:
        icon = "🆕" if not row["is_read"] else "📭"
        snippet = (row["message"] or "").replace("\n", " ")
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."
        lines.append(f"{icon} {snippet}\n🕒 {row['created_at']}\n")
        inline.add(InlineKeyboardButton("Open", callback_data=f"nf:v:{row['id']}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"nf:p:{page-1}"))
    if offset + limit < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"nf:p:{page+1}"))
    if nav:
        inline.row(*nav)
    helpers.safe_send(bot, chat_id, "\n".join(lines), reply_markup=inline)
