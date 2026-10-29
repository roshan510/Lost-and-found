import logging
from datetime import datetime, timedelta
from telebot.types import ReplyKeyboardMarkup
from database import database
from utils import state, helpers, validators, matching
from utils.validators import iso_to_display
from handlers.registration import send_welcome

logger = logging.getLogger(__name__)

STEPS = [
    "category",
    "item_name",
    "description",
    "location",
    "date",
    "time",
    "photo",
    "review",
]


def start_flow(bot, message, kind):
    chat_id = message.chat.id
    other = "found" if kind == "lost" else "lost"
    draft = state.drafts.get(chat_id)
    if draft and draft.get("kind") == other:
        state.drafts.pop(chat_id, None)
    state.drafts[chat_id] = {
        "kind": kind,
        "step": "category",
        "from_review_edit": False,
        "category": None,
        "item_name": None,
        "description": None,
        "location": None,
        "date": None,
        "time": None,
        "photo_id": None,
    }
    ask_step(bot, message, "category")


def handle_cancel(bot, message):
    if not message or message.content_type != "text":
        return False
    text = message.text
    chat_id = message.chat.id
    if text == "/start":
        state.clear_user(chat_id)
        try:
            bot.clear_step_handler_by_chat_id(chat_id)
        except Exception:
            pass
        send_welcome(bot, message)
        return "start"
    if text in (helpers.NAV_MAIN, "/menu"):
        state.clear_user(chat_id)
        try:
            bot.clear_step_handler_by_chat_id(chat_id)
        except Exception:
            pass
        helpers.show_main_menu(bot, message, "Returned to the main menu.")
        return True
    if text in (helpers.NAV_CANCEL, "/cancel"):
        state.clear_user(chat_id)
        try:
            bot.clear_step_handler_by_chat_id(chat_id)
        except Exception:
            pass
        helpers.show_main_menu(bot, message, "Action cancelled.")
        return True
    return False


def previous_step(current):
    if current not in STEPS:
        return "category"
    index = STEPS.index(current)
    if index <= 0:
        return None
    return STEPS[index - 1]


def ask_step(bot, message, step_name):
    chat_id = message.chat.id
    draft = state.drafts.get(chat_id)
    if not draft:
        helpers.show_main_menu(bot, message, "That session expired. Please start again from the menu.")
        return
    draft["step"] = step_name
    kind = draft["kind"]
    lost = kind == "lost"

    try:
        if step_name == "category":
            prompt = "What category is the item?"
            msg = bot.send_message(chat_id, prompt, reply_markup=helpers.category_keyboard())
            bot.register_next_step_handler(msg, lambda m: process_category(bot, m))
        elif step_name == "item_name":
            prompt = "What did you lose? (example: Black Samsung Galaxy Buds)" if lost else "What did you find? (example: Black Samsung Galaxy Buds)"
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(helpers.NAV_BACK, helpers.NAV_CANCEL)
            markup.add(helpers.NAV_MAIN)
            msg = bot.send_message(chat_id, prompt, reply_markup=markup)
            bot.register_next_step_handler(msg, lambda m: process_text_field(bot, m, "item_name", "Item name", 2, 120))
        elif step_name == "description":
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(helpers.NAV_BACK, helpers.NAV_CANCEL)
            markup.add(helpers.NAV_MAIN)
            msg = bot.send_message(chat_id, "Describe the item and any identifying details:", reply_markup=markup)
            bot.register_next_step_handler(msg, lambda m: process_text_field(bot, m, "description", "Description", 3, 1000))
        elif step_name == "location":
            prompt = "Where did you lose it?" if lost else "Where did you find it?"
            msg = bot.send_message(chat_id, prompt, reply_markup=helpers.location_keyboard())
            bot.register_next_step_handler(msg, lambda m: process_location(bot, m))
        elif step_name == "date":
            msg = bot.send_message(chat_id, "When did this happen?", reply_markup=helpers.date_keyboard())
            bot.register_next_step_handler(msg, lambda m: process_date(bot, m))
        elif step_name == "time":
            msg = bot.send_message(
                chat_id,
                "Approximately what time?\nYou can type values like 2:30 PM, around 2 PM, or 14:30.",
                reply_markup=helpers.skip_keyboard(),
            )
            bot.register_next_step_handler(msg, lambda m: process_time(bot, m))
        elif step_name == "photo":
            msg = bot.send_message(chat_id, "Upload a photo if you have one.", reply_markup=helpers.photo_keyboard())
            bot.register_next_step_handler(msg, lambda m: process_photo(bot, m))
        elif step_name == "review":
            show_review(bot, message)
    except Exception:
        logger.exception("Failed to send step prompt")


def after_field(bot, message, next_step_name):
    draft = state.drafts.get(message.chat.id)
    if not draft:
        return
    if draft.get("from_review_edit"):
        draft["from_review_edit"] = False
        show_review(bot, message)
        return
    ask_step(bot, message, next_step_name)


def process_category(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type != "text":
        msg = bot.send_message(message.chat.id, "Please choose a category from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_category(bot, m))
        return
    if message.text == helpers.NAV_BACK:
        helpers.show_main_menu(bot, message, "Returned to the main menu.")
        state.drafts.pop(message.chat.id, None)
        return
    if message.text == "📝 Other":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(helpers.NAV_BACK, helpers.NAV_CANCEL)
        markup.add(helpers.NAV_MAIN)
        msg = bot.send_message(message.chat.id, "Please type the custom category:", reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: process_custom_category(bot, m))
        return
    if message.text not in helpers.CATEGORIES:
        msg = bot.send_message(message.chat.id, "Please select a category from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_category(bot, m))
        return
    state.drafts[message.chat.id]["category"] = message.text.strip()
    after_field(bot, message, "item_name")


def process_custom_category(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, "category")
        return
    ok, value = validators.is_non_empty_text(getattr(message, "text", None), "Category", 2, 80)
    if not ok:
        msg = bot.send_message(message.chat.id, value)
        bot.register_next_step_handler(msg, lambda m: process_custom_category(bot, m))
        return
    state.drafts[message.chat.id]["category"] = value
    after_field(bot, message, "item_name")


def process_text_field(bot, message, field, label, min_len, max_len):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, previous_step(field))
        return
    ok, value = validators.is_non_empty_text(getattr(message, "text", None), label, min_len, max_len)
    if not ok:
        msg = bot.send_message(message.chat.id, value)
        bot.register_next_step_handler(msg, lambda m: process_text_field(bot, m, field, label, min_len, max_len))
        return
    state.drafts[message.chat.id][field] = value
    nxt = "description" if field == "item_name" else "location"
    after_field(bot, message, nxt)


def process_location(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type != "text":
        msg = bot.send_message(message.chat.id, "Please choose a location from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_location(bot, m))
        return
    if message.text == helpers.NAV_BACK:
        ask_step(bot, message, "description")
        return
    if message.text == "📍 Other":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(helpers.NAV_BACK, helpers.NAV_CANCEL)
        markup.add(helpers.NAV_MAIN)
        msg = bot.send_message(message.chat.id, "Please type the exact location:", reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: process_custom_location(bot, m))
        return
    if message.text not in helpers.LOCATIONS:
        msg = bot.send_message(message.chat.id, "Please select a location from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_location(bot, m))
        return
    state.drafts[message.chat.id]["location"] = message.text.strip()
    after_field(bot, message, "date")


def process_custom_location(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, "location")
        return
    ok, value = validators.is_non_empty_text(getattr(message, "text", None), "Location", 2, 120)
    if not ok:
        msg = bot.send_message(message.chat.id, value)
        bot.register_next_step_handler(msg, lambda m: process_custom_location(bot, m))
        return
    state.drafts[message.chat.id]["location"] = value
    after_field(bot, message, "date")


def process_date(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, "location")
        return
    if message.content_type != "text":
        msg = bot.send_message(message.chat.id, "Please choose a date option.")
        bot.register_next_step_handler(msg, lambda m: process_date(bot, m))
        return
    text = message.text.strip()
    today = datetime.today().date()
    if text in ("📅 Today", "Today"):
        state.drafts[message.chat.id]["date"] = today.strftime("%Y-%m-%d")
        after_field(bot, message, "time")
    elif text in ("📅 Yesterday", "Yesterday"):
        state.drafts[message.chat.id]["date"] = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        after_field(bot, message, "time")
    elif text in ("📅 Enter Date", "Enter Date"):
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(helpers.NAV_BACK, helpers.NAV_CANCEL)
        markup.add(helpers.NAV_MAIN)
        msg = bot.send_message(message.chat.id, "Enter date in DD-MM-YYYY format (example: 10-09-2026):", reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: process_custom_date(bot, m))
    else:
        msg = bot.send_message(message.chat.id, "Please select Today, Yesterday, or Enter Date.")
        bot.register_next_step_handler(msg, lambda m: process_date(bot, m))


def process_custom_date(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, "date")
        return
    ok, value = validators.parse_display_date(getattr(message, "text", ""))
    if not ok:
        msg = bot.send_message(message.chat.id, value)
        bot.register_next_step_handler(msg, lambda m: process_custom_date(bot, m))
        return
    state.drafts[message.chat.id]["date"] = value
    after_field(bot, message, "time")


def process_time(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, "date")
        return
    if message.content_type == "text" and message.text in (helpers.NAV_SKIP, "Skip"):
        state.drafts[message.chat.id]["time"] = None
        after_field(bot, message, "photo")
        return
    ok, value = validators.is_valid_time_text(getattr(message, "text", None))
    if not ok:
        msg = bot.send_message(message.chat.id, value)
        bot.register_next_step_handler(msg, lambda m: process_time(bot, m))
        return
    state.drafts[message.chat.id]["time"] = value
    after_field(bot, message, "photo")


def process_photo(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type == "text" and message.text == helpers.NAV_BACK:
        ask_step(bot, message, "time")
        return
    if message.content_type == "photo":
        state.drafts[message.chat.id]["photo_id"] = message.photo[-1].file_id
        after_field(bot, message, "review")
        return
    if message.content_type == "text" and message.text in (helpers.NAV_SKIP_PHOTO, helpers.NAV_SKIP, "Skip"):
        state.drafts[message.chat.id]["photo_id"] = None
        after_field(bot, message, "review")
        return
    msg = bot.send_message(message.chat.id, "Please upload a photo or press Skip Photo.")
    bot.register_next_step_handler(msg, lambda m: process_photo(bot, m))


def show_review(bot, message):
    draft = state.drafts.get(message.chat.id)
    if not draft:
        helpers.show_main_menu(bot, message, "That session expired. Please start again.")
        return
    required = ["category", "item_name", "description", "location", "date"]
    if any(not draft.get(key) for key in required):
        helpers.show_main_menu(bot, message, "Some required details are missing. Please start again.")
        state.drafts.pop(message.chat.id, None)
        return
    draft["step"] = "review"

    kind = draft["kind"]
    title = "🔴 Review Lost Item" if kind == "lost" else "🟢 Review Found Item"
    time_text = draft.get("time") or "Not provided"
    photo_text = "✅ Attached" if draft.get("photo_id") else "❌ Not provided"
    summary = (
        f"{title}\n\n"
        f"<b>Category:</b> {helpers.esc(draft['category'])}\n"
        f"<b>Item:</b> {helpers.esc(draft['item_name'])}\n\n"
        f"<b>Description:</b>\n{helpers.esc(draft['description'])}\n\n"
        f"<b>Location:</b> {helpers.esc(draft['location'])}\n"
        f"<b>Date:</b> {helpers.esc(iso_to_display(draft['date']))}\n"
        f"<b>Time:</b> {helpers.esc(time_text)}\n"
        f"<b>Photo:</b> {photo_text}"
    )
    if draft.get("photo_id"):
        helpers.safe_send_photo(bot, message.chat.id, draft["photo_id"], summary, helpers.review_keyboard())
    else:
        helpers.safe_send(bot, message.chat.id, summary, parse_mode="HTML", reply_markup=helpers.review_keyboard())


def submit_draft(bot, message):
    chat_id = message.chat.id
    draft = state.drafts.get(chat_id)
    if not draft:
        helpers.safe_send(bot, chat_id, "There is nothing to submit. Please start a new report.")
        helpers.show_main_menu(bot, message)
        return
    required = ["category", "item_name", "description", "location", "date"]
    if any(not draft.get(key) for key in required):
        helpers.safe_send(bot, chat_id, "Please complete all required fields before submitting.")
        show_review(bot, message)
        return
    user = helpers.get_registered_user(bot, message.from_user.id, chat_id)
    if not user:
        return
    try:
        if draft["kind"] == "lost":
            report_id = database.save_lost_item(
                message.from_user.id,
                draft["category"],
                draft["item_name"],
                draft["description"],
                draft["location"],
                draft["date"],
                draft.get("time"),
                draft.get("photo_id"),
            )
        else:
            report_id = database.save_found_item(
                message.from_user.id,
                draft["category"],
                draft["item_name"],
                draft["description"],
                draft["location"],
                draft["date"],
                draft.get("time"),
                draft.get("photo_id"),
            )
    except Exception:
        logger.exception("Failed to save report")
        helpers.safe_send(bot, chat_id, "Something went wrong. Please try again.")
        return

    if not report_id:
        helpers.safe_send(bot, chat_id, "Could not save the report. Please type /start and try again.")
        helpers.show_main_menu(bot, message)
        return

    code = helpers.report_code(draft["kind"], report_id)
    icon = "🔴" if draft["kind"] == "lost" else "🟢"
    success = (
        # f"✅ {kind_text} item reported successfully!\n\n"
        f"✅ {code} item reported successfully!\n\n"
        f"Your Report ID:\n\n{icon} {code}\n\n"
        "Your report has been submitted successfully."
    )
    state.drafts.pop(chat_id, None)
    helpers.safe_send(bot, chat_id, success)
    helpers.show_main_menu(bot, message)

    # Safe admin matching evaluation (failures never affect submission, no user notifications sent)
    try:
        matching.evaluate_single_item(draft["kind"], report_id)
    except Exception:
        logger.exception("Failed to evaluate matching for %s #%s", draft["kind"], report_id)


def start_review_edit(bot, message):
    draft = state.drafts.get(message.chat.id)
    if not draft:
        helpers.show_main_menu(bot, message, "That session expired. Please start again.")
        return
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Category", "Item name", "Description")
    markup.add("Location", "Date", "Time")
    markup.add("Photo")
    markup.add("⬅️ Back to Review", helpers.NAV_CANCEL)
    msg = bot.send_message(message.chat.id, "Which field do you want to edit?", reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_review_edit_choice(bot, m))


def process_review_edit_choice(bot, message):
    nav = handle_cancel(bot, message)
    if nav:
        return
    if message.content_type != "text":
        start_review_edit(bot, message)
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
    if message.text == "⬅️ Back to Review":
        show_review(bot, message)
        return
    step = mapping.get(message.text)
    if not step:
        msg = bot.send_message(message.chat.id, "Please choose a field from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_review_edit_choice(bot, m))
        return
    state.drafts[message.chat.id]["from_review_edit"] = True
    ask_step(bot, message, step)


def register(bot):
    @bot.message_handler(
        func=lambda m: m.content_type == "text"
        and m.text in ("✅ Submit", "✏️ Edit", "❌ Cancel")
        and m.chat.id in state.drafts
    )
    def handle_review_buttons(message):
        if message.text == "❌ Cancel":
            handle_cancel(bot, message)
            return
        if message.text == "✅ Submit":
            submit_draft(bot, message)
            return
        start_review_edit(bot, message)
