from telebot.types import ReplyKeyboardRemove
from database import database
from utils import helpers, state, validators
from config import is_admin
import config
import logging

logger = logging.getLogger(__name__)


def send_welcome(bot, message):
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    state.clear_user(chat_id)
    try:
        bot.clear_step_handler_by_chat_id(chat_id)
    except Exception:
        pass

    # Admins skip the registration gate entirely
    if is_admin(telegram_id):
        try:
            user = database.get_user_by_telegram_id(telegram_id)
            if user:
                try:
                    database.update_user_username(telegram_id, message.from_user.username)
                except Exception:
                    pass
                helpers.safe_send(bot, chat_id, "👋 Welcome back to KKWIEER Lost & Found!")
                helpers.show_main_menu(bot, message)
                return
        except Exception:
            pass
        # Admin has no user row — still show the menu (admin-only features work without a row)
        helpers.safe_send(bot, chat_id, "👋 Welcome, Administrator!")
        helpers.show_main_menu(bot, message)
        return

    try:
        user = database.get_user_by_telegram_id(telegram_id)
    except Exception:
        helpers.safe_send(bot, chat_id, "Something went wrong. Please try again.")
        return

    if user:
        reg_status = user["reg_status"] if "reg_status" in user.keys() else "APPROVED"

        if not user["is_active"]:
            helpers.safe_send(
                bot,
                chat_id,
                "Your account has been deactivated. Contact a college administrator if you need help.",
            )
            return

        if reg_status == "APPROVED":
            try:
                database.update_user_username(telegram_id, message.from_user.username)
            except Exception:
                pass
            helpers.safe_send(bot, chat_id, "👋 Welcome back to KKWIEER Lost & Found!")
            helpers.show_main_menu(bot, message)
            return

        if reg_status == "PENDING":
            helpers.safe_send(
                bot,
                chat_id,
                "⏳ Your registration is pending admin verification.\n\n"
                "An administrator will review your college ID card photo and approve "
                "or reject your registration. You will be notified once a decision is made.\n\n"
                "Please be patient — you cannot access the bot's features until your "
                "registration is approved.",
            )
            return

        if reg_status == "REJECTED":
            reason = user["rejection_reason"] if "rejection_reason" in user.keys() else None
            reason_text = f"\n\nReason: {reason}" if reason else ""
            helpers.safe_send(
                bot,
                chat_id,
                f"❌ Your previous registration was rejected by an administrator.{reason_text}\n\n"
                "You may submit a new registration request below. "
                "Please make sure to upload a clear photo of your KKWIEER college ID card.\n\n"
                "Let's start fresh — please enter your name:",
                reply_markup=ReplyKeyboardRemove(),
            )
            # Delete the rejected record so the user can re-register
            _delete_rejected_user(telegram_id)
            msg = bot.send_message(chat_id, "Enter your full name:")
            bot.register_next_step_handler(msg, lambda m: process_name_step(bot, m))
            return

    # New user — begin registration
    msg = bot.send_message(
        chat_id,
        "👋 Welcome to KKWIEER Lost & Found!\n"
        "Let's create your profile first.\n\n"
        "Please enter your full name:",
        reply_markup=ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, lambda m: process_name_step(bot, m))


def _delete_rejected_user(telegram_id):
    """Remove a rejected user row so they can re-register. Called only for REJECTED status."""
    try:
        from database.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM users WHERE (telegram_id = ? OR telegram_user_id = ?) AND reg_status = 'REJECTED'",
                (telegram_id, telegram_id),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to delete rejected user record")


def process_name_step(bot, message):
    if message.content_type == "text" and message.text == "/start":
        send_welcome(bot, message)
        return
    ok, value = validators.is_valid_name(getattr(message, "text", None))
    if not ok:
        msg = bot.send_message(message.chat.id, value + " Try again:")
        bot.register_next_step_handler(msg, lambda m: process_name_step(bot, m))
        return
    # Check for race condition: user registered from another session between steps
    try:
        existing = database.get_user_by_telegram_id(message.from_user.id)
        if existing:
            reg_status = existing["reg_status"] if "reg_status" in existing.keys() else "APPROVED"
            if reg_status == "APPROVED":
                helpers.show_main_menu(bot, message, "You are already registered.")
                return
            if reg_status == "PENDING":
                helpers.safe_send(
                    bot,
                    message.chat.id,
                    "⏳ Your registration is already pending verification.",
                )
                return
    except Exception:
        helpers.safe_send(bot, message.chat.id, "Something went wrong. Please try again.")
        return

    # Store name in state, proceed to ID photo step
    state.drafts[message.chat.id] = {"name": value, "step": "id_photo"}

    msg = bot.send_message(
        message.chat.id,
        f"👍 Hello, {value}!\n\n"
        "📸 Please upload a clear photo of your KKWIEER college ID card for verification.\n\n"
        "Your registration will be completed only after an admin approves your ID card.\n\n"
        "⚠️ Send the photo now (not a document/file — use the 📎 attachment and choose 'Photo').",
        reply_markup=ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, lambda m: process_id_photo_step(bot, m))


def process_id_photo_step(bot, message):
    if message.content_type == "text" and message.text == "/start":
        state.drafts.pop(message.chat.id, None)
        send_welcome(bot, message)
        return

    draft = state.drafts.get(message.chat.id, {})
    if draft.get("step") != "id_photo":
        # State lost — restart
        send_welcome(bot, message)
        return

    if message.content_type != "photo":
        msg = bot.send_message(
            message.chat.id,
            "⚠️ Please send a *photo* of your college ID card (not a document or text).\n\n"
            "Use the 📎 attachment button and select 'Photo'.",
        )
        bot.register_next_step_handler(msg, lambda m: process_id_photo_step(bot, m))
        return

    # Use the highest resolution version of the photo
    file_id = message.photo[-1].file_id
    name = draft["name"]
    telegram_id = message.from_user.id

    # Final race-condition check before inserting
    try:
        existing = database.get_user_by_telegram_id(telegram_id)
        if existing:
            reg_status = existing["reg_status"] if "reg_status" in existing.keys() else "APPROVED"
            if reg_status == "APPROVED":
                state.drafts.pop(message.chat.id, None)
                helpers.show_main_menu(bot, message, "You are already registered.")
                return
            if reg_status == "PENDING":
                state.drafts.pop(message.chat.id, None)
                helpers.safe_send(
                    bot,
                    message.chat.id,
                    "⏳ Your registration is already pending verification.",
                )
                return
        database.create_user(telegram_id, message.from_user.username, name, id_card_file_id=file_id, reg_status="PENDING")
    except Exception:
        logger.exception("Failed to create pending user")
        helpers.safe_send(bot, message.chat.id, "Something went wrong. Please try again.")
        return

    state.drafts.pop(message.chat.id, None)

    helpers.safe_send(
        bot,
        message.chat.id,
        "✅ Your registration request has been submitted successfully!\n\n"
        "An admin will verify your KKWIEER college ID card. "
        "You will receive a notification here once your registration is approved or rejected.\n\n"
        "⏳ Please wait — you can access the bot's features after your registration is approved.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Notify all admins
    _notify_admins_new_registration(bot, name, telegram_id)


def _notify_admins_new_registration(bot, user_name, user_telegram_id):
    """Send a notification to all configured admins about a new pending registration."""
    for admin_id in config.ADMIN_IDS:
        try:
            bot.send_message(
                admin_id,
                f"🪪 New ID Verification Request\n\n"
                f"Name: {user_name}\n"
                f"Telegram ID: {user_telegram_id}\n\n"
                "Open the Admin Panel → 🪪 Pending ID Verifications to review.",
            )
        except Exception:
            logger.exception("Failed to notify admin %s of new registration", admin_id)


def register(bot):
    @bot.message_handler(commands=["start"])
    def handle_start(message):
        send_welcome(bot, message)
