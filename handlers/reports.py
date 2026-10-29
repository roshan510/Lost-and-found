import logging
from datetime import datetime, timedelta
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton
from database import database
from utils import helpers, state, validators
from utils.validators import iso_to_display
from handlers import item_flow

logger = logging.getLogger(__name__)


def register(bot):
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "📋 My Reports")
    def my_reports_home(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        show_my_reports_menu(bot, message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data == "my:home")
    def cb_my_home(call):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        helpers.safe_answer(bot, call)
        if not user:
            return
        show_my_reports_menu(bot, call.message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("my:") and call.data != "my:home")
    def cb_my_list(call):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return
        parts = call.data.split(":")
        if len(parts) < 3:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        kind = parts[1]
        if kind not in ("l", "f") or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        page = int(parts[2])
        item_type = "lost" if kind == "l" else "found"
        send_my_list(bot, call.message.chat.id, user, item_type, page)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ow:"))
    def cb_open_own(call):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return
        parts = call.data.split(":")
        if len(parts) != 3:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        item_type = helpers.parse_item_type(parts[1])
        if item_type is None or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        item = database.get_item(item_type, int(parts[2]), active_only=False)
        if not item or item["user_id"] != user["id"] or item["status"] == "DELETED":
            helpers.safe_answer(bot, call, "You cannot open this report.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        send_own_item(bot, call.message.chat.id, item, item_type)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ed:"))
    def cb_edit(call):
        handle_owner_action(bot, call, "edit")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("dl:"))
    def cb_delete(call):
        handle_owner_action(bot, call, "delete_ask")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("dx:"))
    def cb_delete_yes(call):
        handle_owner_action(bot, call, "delete_yes")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rc:"))
    def cb_recover(call):
        handle_owner_action(bot, call, "recover_ask")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rx:"))
    def cb_recover_yes(call):
        handle_owner_action(bot, call, "recover_yes")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rt:"))
    def cb_return(call):
        handle_owner_action(bot, call, "return_ask")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ry:"))
    def cb_return_yes(call):
        handle_owner_action(bot, call, "return_yes")

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text in ("🔴 My Lost Reports", "🟢 My Found Reports"))
    def my_reports_section(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        item_type = "lost" if "Lost" in message.text else "found"
        send_my_list(bot, message.chat.id, user, item_type, 0)


def show_my_reports_menu(bot, chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🔴 My Lost Reports"), KeyboardButton("🟢 My Found Reports"))
    markup.add(KeyboardButton("🏠 Main Menu"))
    helpers.safe_send(bot, chat_id, "📋 My Reports\n\nChoose a section:", reply_markup=markup)


def send_my_list(bot, chat_id, user, item_type, page):
    try:
        items = database.get_user_items(item_type, user["id"])
    except Exception:
        logger.exception("Failed to load user reports")
        helpers.safe_send(bot, chat_id, "Something went wrong. Please try again.")
        return
    if not items:
        helpers.safe_send(bot, chat_id, "You have no reports in this section yet.")
        return
    limit = 10
    total = len(items)
    start = page * limit
    chunk = items[start:start + limit]
    if not chunk:
        helpers.safe_send(bot, chat_id, "No more reports on this page.")
        return
    title = "🔴 My Lost Reports" if item_type == "lost" else "🟢 My Found Reports"
    lines = [title, ""]
    inline = InlineKeyboardMarkup()
    short = "l" if item_type == "lost" else "f"
    for item in chunk:
        date_key = "lost_date" if item_type == "lost" else "found_date"
        code = helpers.report_code(item_type, item["id"])
        lines.append(
            f"{code} — {item['item_name']}\n📍 {item['location']} | 📅 {iso_to_display(item[date_key])} | {item['status']}\n"
        )
        inline.add(InlineKeyboardButton(f"Open {code}", callback_data=f"ow:{short}:{item['id']}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"my:{short}:{page-1}"))
    if start + limit < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"my:{short}:{page+1}"))
    if nav:
        inline.row(*nav)
    helpers.safe_send(bot, chat_id, "\n".join(lines), reply_markup=inline)


def send_own_item(bot, chat_id, item, item_type):
    caption = helpers.format_item_card(item, item_type)
    markup = helpers.owner_item_buttons(item_type, item["id"], item["status"])
    photo_val = item["photo_id"] if "photo_id" in item.keys() else item["photo_file_id"]
    if photo_val:
        helpers.safe_send_photo(bot, chat_id, photo_val, caption, markup)
    else:
        helpers.safe_send(bot, chat_id, caption, parse_mode="HTML", reply_markup=markup)


def parse_owner_call(call):
    parts = call.data.split(":")
    if len(parts) != 3:
        return None, None
    item_type = helpers.parse_item_type(parts[1])
    if item_type is None or not parts[2].isdigit():
        return None, None
    return item_type, int(parts[2])


def handle_owner_action(bot, call, action):
    user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
    if not user:
        helpers.safe_answer(bot, call)
        return
    item_type, item_id = parse_owner_call(call)
    if not item_type:
        helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
        return
    item = database.get_item(item_type, item_id, active_only=False)
    if not item or item["user_id"] != user["id"]:
        helpers.safe_answer(bot, call, "You can only manage your own reports.", show_alert=True)
        return
    code = helpers.report_code(item_type, item_id)
    short = "l" if item_type == "lost" else "f"
    chat_id = call.message.chat.id

    if action == "edit":
        if item["status"] not in ("LOST", "FOUND"):
            helpers.safe_answer(bot, call, "Only active reports can be edited.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        start_owner_edit(bot, call.message, user, item_type, item)
        return

    if action == "delete_ask":
        helpers.safe_answer(bot, call)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Yes, Delete", callback_data=f"dx:{short}:{item_id}"))
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data=f"ow:{short}:{item_id}"))
        helpers.safe_send(bot, chat_id, f"⚠️ Are you sure you want to delete report {code}?", reply_markup=markup)
        return

    if action == "delete_yes":
        try:
            database.update_item_fields(item_type, item_id, {"status": "DELETED"})
        except Exception:
            logger.exception("Delete failed")
            helpers.safe_answer(bot, call, "Something went wrong.", show_alert=True)
            return
        helpers.safe_answer(bot, call, "Deleted")
        helpers.safe_send(bot, chat_id, f"Report {code} has been deleted.")
        return

    if action == "recover_ask":
        if item_type != "lost" or item["status"] != "LOST":
            helpers.safe_answer(bot, call, "This report cannot be marked recovered.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Yes", callback_data=f"rx:{short}:{item_id}"))
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data=f"ow:{short}:{item_id}"))
        helpers.safe_send(bot, chat_id, "✅ Mark this item as recovered?", reply_markup=markup)
        return

    if action == "recover_yes":
        if item_type != "lost" or item["user_id"] != user["id"]:
            helpers.safe_answer(bot, call, "Not allowed.", show_alert=True)
            return
        database.update_item_fields(item_type, item_id, {"status": "RECOVERED"})
        helpers.safe_answer(bot, call, "Updated")
        helpers.safe_send(bot, chat_id, f"{code} is now marked RECOVERED.")
        helpers.notify_user(bot, user["id"], "STATUS", f"Your lost report {code} was marked RECOVERED.")
        return

    if action == "return_ask":
        if item_type != "found" or item["status"] != "FOUND":
            helpers.safe_answer(bot, call, "This report cannot be marked returned.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Yes", callback_data=f"ry:{short}:{item_id}"))
        markup.add(InlineKeyboardButton("❌ Cancel", callback_data=f"ow:{short}:{item_id}"))
        helpers.safe_send(bot, chat_id, "✅ Mark this item as returned?", reply_markup=markup)
        return

    if action == "return_yes":
        database.update_item_fields(item_type, item_id, {"status": "RETURNED"})
        helpers.safe_answer(bot, call, "Updated")
        helpers.safe_send(bot, chat_id, f"{code} is now marked RETURNED.")
        helpers.notify_user(bot, user["id"], "STATUS", f"Your found report {code} was marked RETURNED.")


def start_owner_edit(bot, message, user, item_type, item):
    state.edit_state[message.chat.id] = {
        "item_type": item_type,
        "item_id": item["id"],
        "user_id": user["id"],
    }
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Category", "Item name", "Description")
    markup.add("Location", "Date", "Time")
    markup.add("Photo")
    markup.add("❌ Cancel", "🏠 Main Menu")
    msg = bot.send_message(message.chat.id, f"Editing {helpers.report_code(item_type, item['id'])}. Choose a field:", reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_edit_field_choice(bot, m))


def process_edit_field_choice(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    edit = state.edit_state.get(message.chat.id)
    if not edit:
        helpers.show_main_menu(bot, message, "Edit session expired.")
        return
    mapping = {
        "Category": "category",
        "Item name": "item_name",
        "Description": "description",
        "Location": "location",
        "Date": "date",
        "Time": "time",
        "Photo": "photo",
    }
    field = mapping.get(message.text if message.content_type == "text" else "")
    if not field:
        msg = bot.send_message(message.chat.id, "Please choose a field from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_edit_field_choice(bot, m))
        return
    edit["field"] = field
    if field == "category":
        msg = bot.send_message(message.chat.id, "Select the new category:", reply_markup=helpers.category_keyboard())
        bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
    elif field == "location":
        msg = bot.send_message(message.chat.id, "Select the new location:", reply_markup=helpers.location_keyboard())
        bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
    elif field == "date":
        msg = bot.send_message(message.chat.id, "When did this happen?", reply_markup=helpers.date_keyboard())
        bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
    elif field == "time":
        msg = bot.send_message(message.chat.id, "Enter the approximate time, or press Skip.", reply_markup=helpers.skip_keyboard(False))
        bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
    elif field == "photo":
        msg = bot.send_message(message.chat.id, "Send a new photo or press Skip Photo to remove it.", reply_markup=helpers.photo_keyboard())
        bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
    else:
        msg = bot.send_message(message.chat.id, f"Type the new {field.replace('_', ' ')}:")
        bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))


def save_edit_value(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    edit = state.edit_state.get(message.chat.id)
    if not edit:
        helpers.show_main_menu(bot, message, "Edit session expired.")
        return
    user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
    if not user or user["id"] != edit["user_id"]:
        state.edit_state.pop(message.chat.id, None)
        return
    item = database.get_item(edit["item_type"], edit["item_id"], active_only=False)
    if not item or item["user_id"] != user["id"] or item["status"] not in ("LOST", "FOUND"):
        helpers.safe_send(bot, message.chat.id, "You can no longer edit this report.")
        state.edit_state.pop(message.chat.id, None)
        helpers.show_main_menu(bot, message)
        return

    # Handle back button safely during field edit
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        start_owner_edit(bot, message, user, edit["item_type"], item)
        return

    field = edit["field"]
    updates = {}
    if field == "photo":
        if message.content_type == "photo":
            updates["photo_id"] = message.photo[-1].file_id
        elif message.content_type == "text" and message.text in (helpers.NAV_SKIP_PHOTO, helpers.NAV_SKIP, "Skip"):
            updates["photo_id"] = None
        else:
            msg = bot.send_message(message.chat.id, "Please send a photo or press Skip Photo.")
            bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
            return
    elif field == "time":
        if message.content_type == "text" and message.text in (helpers.NAV_SKIP, "Skip"):
            updates["approximate_time"] = None
        else:
            ok, value = validators.is_valid_time_text(getattr(message, "text", None))
            if not ok:
                msg = bot.send_message(message.chat.id, value)
                bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
                return
            updates["approximate_time"] = value
    elif field == "date":
        text = message.text.strip() if message.content_type == "text" else ""
        today = datetime.today().date()
        if text in ("📅 Today", "Today"):
            iso = today.strftime("%Y-%m-%d")
        elif text in ("📅 Yesterday", "Yesterday"):
            iso = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        elif text in ("📅 Enter Date", "Enter Date"):
            msg = bot.send_message(message.chat.id, "Enter date in DD-MM-YYYY format:")
            bot.register_next_step_handler(msg, lambda m: save_edit_custom_date(bot, m))
            return
        else:
            ok, iso = validators.parse_display_date(text)
            if not ok:
                msg = bot.send_message(message.chat.id, iso)
                bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
                return
        date_key = "lost_date" if edit["item_type"] == "lost" else "found_date"
        updates[date_key] = iso
    elif field == "category":
        if message.content_type == "text" and message.text == "📝 Other":
            msg = bot.send_message(message.chat.id, "Type the custom category:")
            bot.register_next_step_handler(msg, lambda m: save_edit_custom_text(bot, m, "category", "Category", 80))
            return
        ok, value = validators.is_non_empty_text(getattr(message, "text", None), "Category", 2, 80)
        if not ok:
            msg = bot.send_message(message.chat.id, value)
            bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
            return
        updates["category"] = value
    elif field == "location":
        if message.content_type == "text" and message.text == "📍 Other":
            msg = bot.send_message(message.chat.id, "Type the exact location:")
            bot.register_next_step_handler(msg, lambda m: save_edit_custom_text(bot, m, "location", "Location", 120))
            return
        ok, value = validators.is_non_empty_text(getattr(message, "text", None), "Location", 2, 120)
        if not ok:
            msg = bot.send_message(message.chat.id, value)
            bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
            return
        updates["location"] = value
    elif field == "item_name":
        ok, value = validators.is_non_empty_text(getattr(message, "text", None), "Item name", 2, 120)
        if not ok:
            msg = bot.send_message(message.chat.id, value)
            bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
            return
        updates["item_name"] = value
    elif field == "description":
        ok, value = validators.is_non_empty_text(getattr(message, "text", None), "Description", 3, 1000)
        if not ok:
            msg = bot.send_message(message.chat.id, value)
            bot.register_next_step_handler(msg, lambda m: save_edit_value(bot, m))
            return
        updates["description"] = value

    try:
        database.update_item_fields(edit["item_type"], edit["item_id"], updates)
        item = database.get_item(edit["item_type"], edit["item_id"], active_only=False)
    except Exception:
        logger.exception("Edit save failed")
        helpers.safe_send(bot, message.chat.id, "Something went wrong. Please try again.")
        return
    state.edit_state.pop(message.chat.id, None)
    helpers.safe_send(bot, message.chat.id, "Report updated.")
    send_own_item(bot, message.chat.id, item, edit["item_type"])
    helpers.show_main_menu(bot, message)


def save_edit_custom_date(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    edit = state.edit_state.get(message.chat.id)
    if not edit:
        return
    ok, iso = validators.parse_display_date(getattr(message, "text", ""))
    if not ok:
        msg = bot.send_message(message.chat.id, iso)
        bot.register_next_step_handler(msg, lambda m: save_edit_custom_date(bot, m))
        return
    date_key = "lost_date" if edit["item_type"] == "lost" else "found_date"
    database.update_item_fields(edit["item_type"], edit["item_id"], {date_key: iso})
    item = database.get_item(edit["item_type"], edit["item_id"], active_only=False)
    state.edit_state.pop(message.chat.id, None)
    helpers.safe_send(bot, message.chat.id, "Report updated.")
    send_own_item(bot, message.chat.id, item, edit["item_type"])
    helpers.show_main_menu(bot, message)


def save_edit_custom_text(bot, message, field, label, max_len):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    edit = state.edit_state.get(message.chat.id)
    if not edit:
        return
    ok, value = validators.is_non_empty_text(getattr(message, "text", None), label, 2, max_len)
    if not ok:
        msg = bot.send_message(message.chat.id, value)
        bot.register_next_step_handler(msg, lambda m: save_edit_custom_text(bot, m, field, label, max_len))
        return
    database.update_item_fields(edit["item_type"], edit["item_id"], {field: value})
    item = database.get_item(edit["item_type"], edit["item_id"], active_only=False)
    state.edit_state.pop(message.chat.id, None)
    helpers.safe_send(bot, message.chat.id, "Report updated.")
    send_own_item(bot, message.chat.id, item, edit["item_type"])
    helpers.show_main_menu(bot, message)
