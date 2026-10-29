import logging
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from database import database
from config import is_admin
from utils import helpers, state
from utils.validators import iso_to_display
from handlers import item_flow

logger = logging.getLogger(__name__)


def register(bot):
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🔍 Search")
    def start_search(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        ask_search_type(bot, message)

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🔄 New Search")
    def new_search(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        state.search_state.pop(message.chat.id, None)
        ask_search_type(bot, message)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("sp:"))
    def handle_search_nav(call):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return
        helpers.safe_answer(bot, call)
        chat_id = call.message.chat.id
        if chat_id not in state.search_state:
            helpers.safe_send(bot, chat_id, "Search session expired. Start a new search from the menu.")
            return
        action = call.data.split(":")[1]
        if action == "next":
            state.search_state[chat_id]["page"] += 1
        elif action == "prev":
            state.search_state[chat_id]["page"] = max(0, state.search_state[chat_id]["page"] - 1)
        helpers.safe_delete(bot, chat_id, call.message.message_id)
        execute_search(bot, chat_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("v:"))
    def handle_view(call):
        parts = call.data.split(":")
        if len(parts) != 3:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        item_type = helpers.parse_item_type(parts[1])
        if item_type is None or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return
        item_id = int(parts[2])
        try:
            item = database.get_item(item_type, item_id, active_only=False)
        except Exception:
            logger.exception("Failed to load item")
            helpers.safe_answer(bot, call, "Something went wrong.", show_alert=True)
            return
        if not helpers.user_can_view_item(call.from_user.id, item, item_type, chat_id=call.message.chat.id):
            helpers.safe_answer(bot, call, "You cannot view this listing.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        show_public_item(bot, call.message.chat.id, user, item, item_type)


def ask_search_type(bot, message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔴 Lost Items", "🟢 Found Items", "🔎 Both")
    markup.add("🏠 Main Menu")
    msg = bot.send_message(
        message.chat.id,
        "🔍 Search Lost & Found\n\nChoose what you want to search.\n\n"
        "You must add a keyword, category, or location. "
        "Complete listings are only available to administrators.",
        reply_markup=markup,
    )
    bot.register_next_step_handler(msg, lambda m: process_search_type(bot, m))


def process_search_type(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    text = message.text if message.content_type == "text" else ""
    search_type = None
    if text == "🔴 Lost Items":
        search_type = "lost"
    elif text == "🟢 Found Items":
        search_type = "found"
    elif text == "🔎 Both":
        search_type = "both"
    if not search_type:
        msg = bot.send_message(message.chat.id, "Please select an option from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_search_type(bot, m))
        return
    state.search_state[message.chat.id] = {
        "type": search_type,
        "keyword": None,
        "category": None,
        "location": None,
        "page": 0,
    }
    show_search_filters(bot, message)


def show_search_filters(bot, message):
    chat_id = message.chat.id
    current = state.search_state.get(chat_id)
    if not current:
        return
    status_text = (
        "🔍 Search Filters\n\nCurrent Filters:\n"
        f"• Keyword: {current['keyword'] or 'None'}\n"
        f"• Category: {current['category'] or 'None'}\n"
        f"• Location: {current['location'] or 'None'}\n\n"
        "Add at least one filter, then press Search Now."
    )
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔎 Keyword", "📂 Category", "📍 Location")
    markup.add("✅ Search Now")
    markup.add("🔄 New Search", "🏠 Main Menu")
    msg = bot.send_message(chat_id, status_text, reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_search_filter_selection(bot, m))


def process_search_filter_selection(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    chat_id = message.chat.id
    if chat_id not in state.search_state:
        helpers.show_main_menu(bot, message, "Search session expired.")
        return
    text = message.text if message.content_type == "text" else ""
    if text == "🔄 New Search":
        state.search_state.pop(chat_id, None)
        ask_search_type(bot, message)
        return
    if text == "🔎 Keyword":
        msg = bot.send_message(chat_id, "Enter a keyword to search (example: phone, black, keys):")
        bot.register_next_step_handler(msg, lambda m: process_search_keyword(bot, m))
    elif text == "📂 Category":
        msg = bot.send_message(chat_id, "Select a category to filter by:", reply_markup=helpers.category_keyboard())
        bot.register_next_step_handler(msg, lambda m: process_search_category(bot, m))
    elif text == "📍 Location":
        msg = bot.send_message(chat_id, "Select a location to filter by:", reply_markup=helpers.location_keyboard())
        bot.register_next_step_handler(msg, lambda m: process_search_location(bot, m))
    elif text == "✅ Search Now":
        current = state.search_state[chat_id]
        if not (current.get("keyword") or current.get("category") or current.get("location")):
            helpers.safe_send(
                bot,
                chat_id,
                "Please add a keyword, category, or location first. "
                "Normal users cannot browse the complete Lost & Found list.",
            )
            show_search_filters(bot, message)
            return
        current["page"] = 0
        execute_search(bot, chat_id)
    else:
        show_search_filters(bot, message)


def process_search_keyword(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text.strip():
        state.search_state[message.chat.id]["keyword"] = message.text.strip()[:80]
    show_search_filters(bot, message)


def process_search_category(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        show_search_filters(bot, message)
        return
    if message.content_type == "text" and message.text == "📝 Other":
        msg = bot.send_message(message.chat.id, "Please type the custom category to search:")
        bot.register_next_step_handler(msg, lambda m: process_search_custom_category(bot, m))
        return
    if message.content_type == "text":
        state.search_state[message.chat.id]["category"] = message.text.strip()
    show_search_filters(bot, message)


def process_search_custom_category(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text.strip():
        state.search_state[message.chat.id]["category"] = message.text.strip()
    show_search_filters(bot, message)


def process_search_location(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        show_search_filters(bot, message)
        return
    if message.content_type == "text" and message.text == "📍 Other":
        msg = bot.send_message(message.chat.id, "Please type the exact location to search:")
        bot.register_next_step_handler(msg, lambda m: process_search_custom_location(bot, m))
        return
    if message.content_type == "text":
        state.search_state[message.chat.id]["location"] = message.text.strip()
    show_search_filters(bot, message)


def process_search_custom_location(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text.strip():
        state.search_state[message.chat.id]["location"] = message.text.strip()
    show_search_filters(bot, message)


def execute_search(bot, chat_id):
    current = state.search_state.get(chat_id)
    if not current:
        return
    if not (current.get("keyword") or current.get("category") or current.get("location")):
        helpers.safe_send(bot, chat_id, "Please add at least one search filter.")
        return
    limit = 10
    offset = current["page"] * limit
    try:
        results, total_results = database.search_items(
            current["type"],
            current["keyword"],
            current["category"],
            current["location"],
            offset,
            limit,
            include_inactive=False,
        )
    except Exception:
        logger.exception("Search query failed")
        helpers.safe_send(bot, chat_id, "Something went wrong. Please try again.")
        return

    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔄 New Search", "🏠 Main Menu")
    if total_results == 0:
        helpers.safe_send(
            bot,
            chat_id,
            "🔍 No matching reports found.\nTry a different keyword, category, or location.",
            reply_markup=markup,
        )
        return

    lines = [f"🔍 Search Results (Page {current['page'] + 1})", ""]
    inline = InlineKeyboardMarkup()
    for row in results:
        item_type = row["type"]
        icon = "🔴 Lost" if item_type == "lost" else "🟢 Found"
        code = helpers.report_code(item_type, row["id"])
        lines.append(f"{icon} — {row['item_name']}\n📍 {row['location']} | 📅 {iso_to_display(row['date'])} | 🆔 {code}\n")
        short = "l" if item_type == "lost" else "f"
        inline.add(InlineKeyboardButton(text=f"View {code}", callback_data=f"v:{short}:{row['id']}"))

    nav_buttons = []
    if current["page"] > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data="sp:prev"))
    if offset + limit < total_results:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data="sp:next"))
    if nav_buttons:
        inline.row(*nav_buttons)

    helpers.safe_send(bot, chat_id, "Select a report to view details:", reply_markup=markup)
    helpers.safe_send(bot, chat_id, "\n".join(lines), reply_markup=inline)


def show_public_item(bot, chat_id, viewer, item, item_type):
    if item["status"] not in ("LOST", "FOUND") and item["user_id"] != viewer["id"]:
        if not is_admin(viewer["telegram_id"]):
            helpers.safe_send(bot, chat_id, "This report is no longer available.")
            return
    caption = helpers.format_item_card(item, item_type)
    show_back = chat_id in state.search_state
    markup = helpers.public_item_buttons(item_type, item["id"], viewer["id"], item["user_id"], show_back=show_back)
    if item["photo_id"]:
        helpers.safe_send_photo(bot, chat_id, item["photo_id"], caption, markup)
    else:
        helpers.safe_send(bot, chat_id, caption, parse_mode="HTML", reply_markup=markup)
