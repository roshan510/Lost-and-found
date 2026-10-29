import html
import logging
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import database
from config import is_admin
from utils import state
from utils.validators import iso_to_display

logger = logging.getLogger(__name__)

CATEGORIES = [
    "📱 Electronics",
    "🎒 Bags",
    "👛 Wallet/Purse",
    "🪪 ID/Card",
    "🔑 Keys",
    "📚 Books/Notes",
    "👕 Clothing",
    "💍 Accessories",
    "💧 Bottle",
    "📝 Other",
]

LOCATIONS = [
    "📚 Library",
    "🍔 Canteen",
    "🏫 Classroom",
    "🏢 Department",
    "🏃 Ground",
    "🅿️ Parking",
    "🚌 Bus Area",
    "🏢 Administrative Building",
    "📍 Other",
]

NAV_CANCEL = "❌ Cancel"
NAV_BACK = "⬅️ Back"
NAV_MAIN = "🏠 Main Menu"
NAV_SKIP = "⏭️ Skip"
NAV_SKIP_PHOTO = "⏭️ Skip Photo"

REPORT_REASONS = [
    "Incorrect information",
    "Spam",
    "Suspicious",
    "Duplicate",
    "Inappropriate",
    "Other",
]


def esc(value):
    if value is None:
        return ""
    return html.escape(str(value))


def report_code(item_type, item_id):
    prefix = "L" if item_type == "lost" else "F"
    return f"#{prefix}{item_id}"


def parse_item_type(value):
    if value in ("lost", "l"):
        return "lost"
    if value in ("found", "f"):
        return "found"
    return None


def main_menu_markup(telegram_user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("🔴 I Lost Something"), KeyboardButton("🟢 I Found Something"))
    markup.row(KeyboardButton("🔍 Search"), KeyboardButton("📋 My Reports"))
    markup.row(KeyboardButton("🔔 Notifications"), KeyboardButton("❓ Help"))
    if is_admin(telegram_user_id):
        markup.row(KeyboardButton("👨‍💼 Admin Panel"))
    return markup


def show_main_menu(bot, message_or_chat_id, text="Here is the main menu. What would you like to do?", user_id=None):
    if hasattr(message_or_chat_id, "chat"):
        chat_id = message_or_chat_id.chat.id
        tg_id = user_id or (message_or_chat_id.from_user.id if getattr(message_or_chat_id, "from_user", None) else chat_id)
    else:
        chat_id = message_or_chat_id
        tg_id = user_id or chat_id
    safe_send(
        bot,
        chat_id,
        text,
        reply_markup=main_menu_markup(tg_id),
    )


def nav_keyboard(*extra_rows):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in extra_rows:
        if isinstance(row, str):
            markup.add(row)
        else:
            markup.add(*row)
    markup.add(NAV_BACK, NAV_CANCEL)
    markup.add(NAV_MAIN)
    return markup


def category_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*CATEGORIES[:4])
    markup.add(*CATEGORIES[4:8])
    markup.add(CATEGORIES[8], CATEGORIES[9])
    markup.add(NAV_CANCEL, NAV_MAIN)
    return markup


def location_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*LOCATIONS[:3])
    markup.add(*LOCATIONS[3:6])
    markup.add(*LOCATIONS[6:8])
    markup.add(LOCATIONS[8])
    markup.add(NAV_BACK, NAV_CANCEL)
    markup.add(NAV_MAIN)
    return markup


def date_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📅 Today", "📅 Yesterday", "📅 Enter Date")
    markup.add(NAV_BACK, NAV_CANCEL)
    markup.add(NAV_MAIN)
    return markup


def skip_keyboard(include_back=True):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(NAV_SKIP)
    if include_back:
        markup.add(NAV_BACK, NAV_CANCEL)
    else:
        markup.add(NAV_CANCEL)
    markup.add(NAV_MAIN)
    return markup


def photo_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(NAV_SKIP_PHOTO)
    markup.add(NAV_BACK, NAV_CANCEL)
    markup.add(NAV_MAIN)
    return markup


def review_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Submit", "✏️ Edit", NAV_CANCEL)
    markup.add(NAV_MAIN)
    return markup


def is_nav_cancel(message):
    if not message or message.content_type != "text":
        return False
    return message.text in ("/start", NAV_CANCEL, NAV_MAIN)


def get_registered_user(bot, telegram_id, chat_id=None):
    """Return user row if fully approved, or send a friendly message and return None.

    Admins (defined in ADMIN_IDS) bypass the registration-approval check so they
    are never locked out even if they have no user row or a non-APPROVED status.
    """
    target_chat = chat_id if chat_id is not None else telegram_id
    # Admins are never blocked by the registration gate
    if is_admin(telegram_id):
        try:
            user = database.get_user_by_telegram_id(telegram_id)
        except Exception:
            logger.exception("Database error while loading admin user")
            safe_send(bot, target_chat, "Something went wrong. Please try again.")
            return None
        # Admins may use the bot even without a user row
        return user  # may be None — callers that need a row must check themselves
    try:
        user = database.get_user_by_telegram_id(telegram_id)
    except Exception:
        logger.exception("Database error while loading user")
        safe_send(bot, target_chat, "Something went wrong. Please try again.")
        return None
    if not user:
        safe_send(bot, target_chat, "Please type /start to register first.")
        return None
    if not user["is_active"]:
        safe_send(bot, target_chat, "Your account has been deactivated. Contact a college administrator if you need help.")
        return None
    reg_status = user["reg_status"] if "reg_status" in user.keys() else "APPROVED"
    if reg_status == "PENDING":
        safe_send(
            bot,
            target_chat,
            "⏳ Your registration is awaiting admin verification.\n\n"
            "An admin will review your college ID card and approve your registration. "
            "You will be notified once your registration is processed.\n\n"
            "Please wait — you cannot access the bot's features until your registration is approved.",
        )
        return None
    if reg_status == "REJECTED":
        reason = user["rejection_reason"] if "rejection_reason" in user.keys() else None
        reason_text = f"\n\nReason: {reason}" if reason else ""
        safe_send(
            bot,
            target_chat,
            f"❌ Your registration was rejected by an administrator.{reason_text}\n\n"
            "If you believe this is a mistake or wish to resubmit, please type /start to begin a new registration.",
        )
        return None
    return user



def safe_send(bot, chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception:
        logger.exception("Failed to send Telegram message")
        return None


def safe_send_photo(bot, chat_id, photo_id, caption, reply_markup=None):
    try:
        return bot.send_photo(chat_id, photo_id, caption=caption, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        logger.exception("Failed to send photo; sending text instead")
        return safe_send(bot, chat_id, caption, parse_mode="HTML", reply_markup=reply_markup)


def safe_answer(bot, call, text=None, show_alert=False):
    try:
        bot.answer_callback_query(call.id, text=text, show_alert=show_alert)
    except Exception:
        logger.exception("Failed to answer callback")


def safe_delete(bot, chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        logger.debug("Could not delete message", exc_info=True)


def notify_user(bot, internal_user_id, notif_type, message, telegram_text=None, send_telegram=True):
    try:
        database.create_notification(internal_user_id, notif_type, message)
    except Exception:
        logger.exception("Failed to store notification")
    if not send_telegram:
        return
    telegram_id = database.get_telegram_id_by_internal_user_id(internal_user_id)
    if not telegram_id:
        return
    try:
        bot.send_message(telegram_id, telegram_text or message)
    except Exception:
        logger.exception("Failed to deliver notification via Telegram")


def format_item_card(item, item_type, include_status=True):
    date_key = "lost_date" if item_type == "lost" else "found_date"
    icon = "🔴 Lost Item" if item_type == "lost" else "🟢 Found Item"
    photo_val = item["photo_id"] if "photo_id" in item.keys() else item["photo_file_id"]
    photo_text = "✅ Attached" if photo_val else "❌ Not provided"
    time_val = item["approximate_time"] if "approximate_time" in item.keys() else item.get("lost_time" if item_type == "lost" else "found_time")
    time_text = time_val if time_val else "Not provided"
    lines = [
        f"{icon}",
        f"<b>Report ID:</b> {esc(report_code(item_type, item['id']))}",
        "",
        f"<b>Category:</b> {esc(item['category'])}",
        f"<b>Item:</b> {esc(item['item_name'])}",
        f"<b>Description:</b>",
        esc(item["description"] or "Not provided"),
        "",
        f"<b>Location:</b> {esc(item['location'])}",
        f"<b>Date:</b> {esc(iso_to_display(item[date_key]))}",
        f"<b>Approximate Time:</b> {esc(time_text)}",
        f"<b>Photo:</b> {photo_text}",
    ]
    if include_status:
        lines.extend(["", f"<b>Status:</b> {esc(item['status'])}"])
    text = "\n".join(lines)
    if len(text) > 1000:
        text = text[:990] + "…"
    return text


def user_can_view_item(telegram_id, item, item_type, chat_id=None, as_admin=False):
    if item is None:
        return False
    if as_admin or is_admin(telegram_id):
        return True
    user = database.get_user_by_telegram_id(telegram_id)
    if not user:
        return False
    if item["user_id"] == user["id"]:
        return True

    chat_id = chat_id if chat_id is not None else telegram_id
    search = state.search_state.get(chat_id)
    if search and item["status"] in ("LOST", "FOUND"):
        search_type = search.get("type", "both")
        if search_type in (item_type, "both"):
            if search.get("keyword") or search.get("category") or search.get("location"):
                if database.item_matches_filters(
                    item,
                    item_type,
                    search.get("keyword"),
                    search.get("category"),
                    search.get("location"),
                ):
                    return True

    contact = state.contact_mode.get(chat_id)
    if contact:
        request = database.get_contact_request(contact)
        if request and request["status"] == "ACCEPTED":
            if item_type == "lost" and request["lost_item_id"] == item["id"]:
                return True
            if item_type == "found" and request["found_item_id"] == item["id"]:
                return True
    return False


def public_item_buttons(item_type, item_id, viewer_internal_id, owner_internal_id, show_back=False):
    markup = InlineKeyboardMarkup()
    short_type = "l" if item_type == "lost" else "f"
    if viewer_internal_id != owner_internal_id:
        markup.add(InlineKeyboardButton("📩 Contact Reporter", callback_data=f"ct:{short_type}:{item_id}"))
        markup.add(InlineKeyboardButton("🚩 Report Listing", callback_data=f"fl:{short_type}:{item_id}"))
    if show_back:
        markup.add(InlineKeyboardButton("⬅️ Back to Results", callback_data="sp:back"))
    return markup


def owner_item_buttons(item_type, item_id, status):
    markup = InlineKeyboardMarkup()
    short_type = "l" if item_type == "lost" else "f"
    active = status in ("LOST", "FOUND")
    if active:
        markup.add(InlineKeyboardButton("✏️ Edit", callback_data=f"ed:{short_type}:{item_id}"))
        markup.add(InlineKeyboardButton("🗑 Delete", callback_data=f"dl:{short_type}:{item_id}"))
        if item_type == "lost":
            markup.add(InlineKeyboardButton("✅ Mark Recovered", callback_data=f"rc:{short_type}:{item_id}"))
        else:
            markup.add(InlineKeyboardButton("✅ Mark Returned", callback_data=f"rt:{short_type}:{item_id}"))
    markup.add(InlineKeyboardButton("⬅️ My Reports", callback_data="my:home"))
    return markup
