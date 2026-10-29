import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from database import database
from utils import helpers, state, validators
from handlers import item_flow

logger = logging.getLogger(__name__)


def register(bot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith("ct:"))
    def request_contact(call):
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
        item_id = int(parts[2])
        item = database.get_item(item_type, item_id, active_only=True)
        if not helpers.user_can_view_item(call.from_user.id, item, item_type, chat_id=call.message.chat.id):
            helpers.safe_answer(bot, call, "You cannot contact this reporter.", show_alert=True)
            return
        if item["user_id"] == user["id"]:
            helpers.safe_answer(bot, call, "This is your own listing.", show_alert=True)
            return
        try:
            request_id, status, created = database.create_contact_request(
                user["id"], item["user_id"], item_type, item_id
            )
        except Exception:
            logger.exception("Failed to create contact request")
            helpers.safe_answer(bot, call, "Something went wrong.", show_alert=True)
            return
        if not created:
            helpers.safe_answer(bot, call, f"A contact request is already {status.lower()}.", show_alert=True)
            return
        helpers.safe_answer(bot, call, "Request sent")
        code = helpers.report_code(item_type, item_id)
        helpers.safe_send(bot, call.message.chat.id, f"Your contact request for {code} has been sent. You will be notified when the reporter responds.")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Accept", callback_data=f"ca:{request_id}"))
        markup.add(InlineKeyboardButton("❌ Decline", callback_data=f"cd:{request_id}"))
        helpers.notify_user(
            bot,
            item["user_id"],
            "CONTACT",
            f"Someone is interested in your report {code}. Open Notifications or use the buttons that were sent to respond.",
            telegram_text=None,
        )
        target_tg = database.get_telegram_id_by_internal_user_id(item["user_id"])
        if target_tg:
            try:
                bot.send_message(
                    target_tg,
                    f"🔔 Someone is interested in your report {code}.\n\nWould you like to respond?",
                    reply_markup=markup,
                )
            except Exception:
                logger.exception("Failed to send contact request to reporter")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ca:") or call.data.startswith("cd:"))
    def respond_contact(call):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return
        parts = call.data.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        request = database.get_contact_request(int(parts[1]))
        if not request or request["target_user_id"] != user["id"]:
            helpers.safe_answer(bot, call, "You cannot respond to this request.", show_alert=True)
            return
        if request["status"] != "PENDING":
            helpers.safe_answer(bot, call, "This request was already handled.", show_alert=True)
            return
        accept = parts[0] == "ca"
        new_status = "ACCEPTED" if accept else "DECLINED"
        database.update_contact_status(request["id"], new_status)
        helpers.safe_answer(bot, call, new_status.title())
        item_type = "lost" if request["lost_item_id"] else "found"
        item_id = request["lost_item_id"] or request["found_item_id"]
        code = helpers.report_code(item_type, item_id) if item_id else "a listing"
        if accept:
            helpers.safe_send(
                bot,
                call.message.chat.id,
                f"You accepted the contact request for {code}.\n\n"
                "Type 💬 Send Message, then write your reply. Private Telegram details stay hidden.",
            )
            state.contact_mode[call.message.chat.id] = request["id"]
            helpers.notify_user(
                bot,
                request["requester_user_id"],
                "CONTACT",
                f"Your contact request for {code} was accepted. Open the bot and tap 💬 Send Message to continue.",
            )
            requester_tg = database.get_telegram_id_by_internal_user_id(request["requester_user_id"])
            if requester_tg:
                try:
                    markup = ReplyKeyboardMarkup(resize_keyboard=True)
                    markup.add("💬 Send Message")
                    markup.add("🔒 Close Contact", "🏠 Main Menu")
                    bot.send_message(
                        requester_tg,
                        f"Your contact request for {code} was accepted. Use the buttons below to send a message.",
                        reply_markup=markup,
                    )
                    state.contact_mode[requester_tg] = request["id"]
                except Exception:
                    logger.exception("Failed to notify requester about accepted contact")
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("💬 Send Message")
            markup.add("🔒 Close Contact", "🏠 Main Menu")
            helpers.safe_send(bot, call.message.chat.id, "You can send a message now.", reply_markup=markup)
        else:
            helpers.safe_send(bot, call.message.chat.id, "You declined the contact request.")
            helpers.notify_user(
                bot,
                request["requester_user_id"],
                "CONTACT",
                f"Your contact request for {code} was declined.",
            )

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "💬 Send Message")
    def start_contact_message(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        request_id = state.contact_mode.get(message.chat.id)
        if not request_id:
            helpers.safe_send(bot, message.chat.id, "You do not have an open contact conversation.")
            return
        request = database.get_contact_request(request_id)
        if not request or request["status"] != "ACCEPTED":
            helpers.safe_send(bot, message.chat.id, "This contact conversation is not active.")
            return
        if user["id"] not in (request["requester_user_id"], request["target_user_id"]):
            helpers.safe_send(bot, message.chat.id, "You cannot use this conversation.")
            return
        msg = bot.send_message(message.chat.id, "Type your message. Do not share phone numbers or private IDs if you can avoid it.")
        bot.register_next_step_handler(msg, lambda m: relay_contact_message(bot, m, request_id))

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🔒 Close Contact")
    def close_contact(message):
        request_id = state.contact_mode.get(message.chat.id)
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user or not request_id:
            helpers.show_main_menu(bot, message)
            return
        request = database.get_contact_request(request_id)
        if request and user["id"] in (request["requester_user_id"], request["target_user_id"]):
            database.update_contact_status(request_id, "CLOSED")
            other = request["target_user_id"] if user["id"] == request["requester_user_id"] else request["requester_user_id"]
            helpers.notify_user(bot, other, "CONTACT", "A contact conversation was closed.")
        state.contact_mode.pop(message.chat.id, None)
        helpers.show_main_menu(bot, message, "Contact conversation closed.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("fl:"))
    def start_flag(call):
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
        item = database.get_item(item_type, int(parts[2]), active_only=True)
        if not helpers.user_can_view_item(call.from_user.id, item, item_type, chat_id=call.message.chat.id):
            helpers.safe_answer(bot, call, "You cannot report this listing.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        state.flag_state[call.message.chat.id] = {
            "item_type": item_type,
            "item_id": int(parts[2]),
            "user_id": user["id"],
        }
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        for reason in helpers.REPORT_REASONS:
            markup.add(reason)
        markup.add("❌ Cancel", "🏠 Main Menu")
        msg = bot.send_message(call.message.chat.id, "Why are you reporting this listing?", reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: process_flag_reason(bot, m))


def relay_contact_message(bot, message, request_id):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
    if not user:
        return
    request = database.get_contact_request(request_id)
    if not request or request["status"] != "ACCEPTED":
        helpers.safe_send(bot, message.chat.id, "This contact conversation is not active.")
        return
    if user["id"] not in (request["requester_user_id"], request["target_user_id"]):
        helpers.safe_send(bot, message.chat.id, "You cannot use this conversation.")
        return
    ok, text = validators.is_non_empty_text(getattr(message, "text", None), "Message", 1, 1000)
    if not ok:
        msg = bot.send_message(message.chat.id, text)
        bot.register_next_step_handler(msg, lambda m: relay_contact_message(bot, m, request_id))
        return
    other_id = request["target_user_id"] if user["id"] == request["requester_user_id"] else request["requester_user_id"]
    item_type = "lost" if request["lost_item_id"] else "found"
    item_id = request["lost_item_id"] or request["found_item_id"]
    code = helpers.report_code(item_type, item_id) if item_id else "your listing"
    delivered = (
        f"📩 Message about report {code}:\n\n{text}\n\n"
        "Reply with 💬 Send Message. Private Telegram IDs are not shown."
    )
    helpers.notify_user(bot, other_id, "CONTACT", delivered)
    helpers.safe_send(bot, message.chat.id, "Message sent.")
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💬 Send Message")
    markup.add("🔒 Close Contact", "🏠 Main Menu")
    helpers.safe_send(bot, message.chat.id, "You can send another message or return to the menu.", reply_markup=markup)


def process_flag_reason(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    flag = state.flag_state.get(message.chat.id)
    if not flag:
        helpers.show_main_menu(bot, message, "That report session expired.")
        return
    if message.content_type != "text" or message.text not in helpers.REPORT_REASONS:
        msg = bot.send_message(message.chat.id, "Please choose a reason from the keyboard.")
        bot.register_next_step_handler(msg, lambda m: process_flag_reason(bot, m))
        return
    flag["reason"] = message.text
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⏭️ Skip")
    markup.add("❌ Cancel")
    msg = bot.send_message(message.chat.id, "Add optional details, or press Skip.", reply_markup=markup)
    bot.register_next_step_handler(msg, lambda m: process_flag_details(bot, m))


def process_flag_details(bot, message):
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    flag = state.flag_state.get(message.chat.id)
    if not flag:
        helpers.show_main_menu(bot, message, "That report session expired.")
        return
    details = None
    if message.content_type == "text" and message.text not in (helpers.NAV_SKIP, "Skip"):
        ok, value = validators.is_non_empty_text(message.text, "Details", 1, 500)
        if not ok:
            msg = bot.send_message(message.chat.id, value)
            bot.register_next_step_handler(msg, lambda m: process_flag_details(bot, m))
            return
        details = value
    try:
        database.create_listing_report(
            flag["user_id"],
            flag["item_type"],
            flag["item_id"],
            flag["reason"],
            details,
        )
    except Exception:
        logger.exception("Failed to save listing report")
        helpers.safe_send(bot, message.chat.id, "Something went wrong. Please try again.")
        return
    state.flag_state.pop(message.chat.id, None)
    helpers.show_main_menu(bot, message, "Thank you. Administrators will review this listing.")
