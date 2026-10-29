import logging
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import database
from config import is_admin
from utils import helpers, state, validators, matching
from handlers import item_flow

logger = logging.getLogger(__name__)

_ADMIN_SENTINEL = object()  # Returned by require_* when caller is admin but has no user row


def deny(bot, chat_id):
    helpers.safe_send(bot, chat_id, "ACCESS DENIED. This section is only for administrators.")


def require_admin_message(bot, message):
    """Return user row (or sentinel) for admins, None for non-admins/unregistered users."""
    if not is_admin(message.from_user.id):
        # Non-admin: must be a registered, approved user
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return None
        deny(bot, message.chat.id)
        return None
    # Admin: may operate without a user row
    user = database.get_user_by_telegram_id(message.from_user.id)
    return user if user else _ADMIN_SENTINEL


def require_admin_call(bot, call):
    """Return user row (or sentinel) for admins, None for non-admins/unregistered users."""
    if not is_admin(call.from_user.id):
        user = helpers.get_registered_user(bot, call.from_user.id, call.message.chat.id)
        if not user:
            helpers.safe_answer(bot, call)
            return None
        helpers.safe_answer(bot, call, "ACCESS DENIED", show_alert=True)
        return None
    user = database.get_user_by_telegram_id(call.from_user.id)
    return user if user else _ADMIN_SENTINEL


def _admin_internal_id(admin_obj):
    """Extract the internal user id from an admin result, or None for the sentinel."""
    if admin_obj is _ADMIN_SENTINEL or admin_obj is None:
        return None
    return admin_obj["id"]


ID_VERIFY_BTN = "🪪 Pending ID Verifications"


def admin_menu_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("👥 Users"), KeyboardButton("🔴 All Lost Items"))
    markup.add(KeyboardButton("🟢 All Found Items"), KeyboardButton("🔎 Potential Matches"))
    markup.add(KeyboardButton(ID_VERIFY_BTN))
    markup.add(KeyboardButton("📢 Announcements"), KeyboardButton("📊 Statistics"))
    markup.add(KeyboardButton("🏠 Main Menu"))
    return markup


def show_admin_panel(bot, message):
    helpers.safe_send(
        bot,
        message.chat.id,
        "👨‍💼 Admin Panel\n\nOnly administrators can use these tools.",
        reply_markup=admin_menu_markup(),
    )


def register(bot):
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "👨‍💼 Admin Panel")
    def open_admin(message):
        if not require_admin_message(bot, message):
            return
        show_admin_panel(bot, message)

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "👥 Users")
    def admin_users(message):
        if not require_admin_message(bot, message):
            return
        send_users_page(bot, message.chat.id, 0)

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🔴 All Lost Items")
    def admin_lost(message):
        if not require_admin_message(bot, message):
            return
        send_admin_items(bot, message.chat.id, "lost", 0)

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🟢 All Found Items")
    def admin_found(message):
        if not require_admin_message(bot, message):
            return
        send_admin_items(bot, message.chat.id, "found", 0)

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🔎 Potential Matches")
    def admin_potential_matches(message):
        if not require_admin_message(bot, message):
            return
        send_potential_matches_page(bot, message.chat.id, 0, refresh=True)

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "📊 Statistics")
    def admin_stats(message):
        if not require_admin_message(bot, message):
            return
        try:
            stats = database.get_statistics()
        except Exception:
            logger.exception("Stats query failed")
            helpers.safe_send(bot, message.chat.id, "Something went wrong. Please try again.")
            return
        text = (
            "📊 Statistics\n\n"
            f"Total registered users: {stats['total_users']}\n"
            f"Active users: {stats['active_users']}\n"
            f"Total Lost reports: {stats['total_lost']}\n"
            f"Active Lost reports: {stats['active_lost']}\n"
            f"Recovered reports: {stats['recovered']}\n"
            f"Total Found reports: {stats['total_found']}\n"
            f"Active Found reports: {stats['active_found']}\n"
            f"Returned reports: {stats['returned']}\n"
            f"Pending moderation reports: {stats['pending_moderation']}"
        )
        helpers.safe_send(bot, message.chat.id, text, reply_markup=admin_menu_markup())

    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "📢 Announcements")
    def start_announce(message):
        if not require_admin_message(bot, message):
            return
        state.announce_state[message.chat.id] = {"step": "text"}
        msg = bot.send_message(message.chat.id, "Type the announcement to send to all active users.")
        bot.register_next_step_handler(msg, lambda m: process_announce_text(bot, m))

    @bot.callback_query_handler(func=lambda call: call.data.startswith("au:"))
    def cb_users(call):
        if not require_admin_call(bot, call):
            return
        helpers.safe_answer(bot, call)
        page = int(call.data.split(":")[1]) if call.data.split(":")[1].isdigit() else 0
        send_users_page(bot, call.message.chat.id, page)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ai:"))
    def cb_admin_items(call):
        if not require_admin_call(bot, call):
            return
        parts = call.data.split(":")
        if len(parts) != 3 or parts[1] not in ("l", "f") or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        item_type = "lost" if parts[1] == "l" else "found"
        send_admin_items(bot, call.message.chat.id, item_type, int(parts[2]))

    @bot.callback_query_handler(func=lambda call: call.data.startswith("av:"))
    def cb_admin_view(call):
        if not require_admin_call(bot, call):
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
        if not item:
            helpers.safe_answer(bot, call, "Report not found.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        send_admin_item_details(bot, call.message.chat.id, item, item_type)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("as:"))
    def cb_admin_status(call):
        admin = require_admin_call(bot, call)
        if not admin:
            return
        parts = call.data.split(":")
        # as:l:12:DELETED
        if len(parts) != 4:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        item_type = helpers.parse_item_type(parts[1])
        if item_type is None or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        new_status = parts[3]
        allowed = {"LOST", "FOUND", "RECOVERED", "RETURNED", "DELETED"}
        if new_status not in allowed:
            helpers.safe_answer(bot, call, "Invalid status.", show_alert=True)
            return
        item_id = int(parts[2])
        database.update_item_fields(item_type, item_id, {"status": new_status})
        item = database.get_item(item_type, item_id, active_only=False)
        code = helpers.report_code(item_type, item_id)
        admin_id = _admin_internal_id(admin)
        if admin_id:
            database.record_admin_action(
                admin_id,
                f"SET_STATUS_{new_status}",
                target_type=item_type,
                target_id=item_id,
                details=f"Admin set {code} status to {new_status}",
            )
        helpers.safe_answer(bot, call, "Updated")
        helpers.safe_send(bot, call.message.chat.id, f"{code} status is now {new_status}.")
        if item:
            helpers.notify_user(
                bot,
                item["user_id"],
                "MODERATION",
                f"An administrator updated your report {code} to {new_status}.",
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ud:") or call.data.startswith("ux:"))
    def cb_user_deactivate(call):
        if not require_admin_call(bot, call):
            return
        parts = call.data.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        user_id = int(parts[1])
        target = database.get_user_by_id(user_id)
        if not target:
            helpers.safe_answer(bot, call, "User not found.", show_alert=True)
            return
        if parts[0] == "ud":
            helpers.safe_answer(bot, call)
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("✅ Yes, deactivate", callback_data=f"ux:{user_id}"))
            helpers.safe_send(
                bot,
                call.message.chat.id,
                f"Deactivate user #{user_id} ({target['full_name']})?",
                reply_markup=markup,
            )
            return
        database.set_user_active(user_id, False)
        helpers.safe_answer(bot, call, "Deactivated")
        helpers.safe_send(bot, call.message.chat.id, f"User #{user_id} is now inactive.")
        helpers.notify_user(bot, user_id, "ACCOUNT", "Your KKWIEER Lost & Found account has been deactivated.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("af:"))
    def cb_admin_filter(call):
        if not require_admin_call(bot, call):
            return
        parts = call.data.split(":")
        if len(parts) != 2 or parts[1] not in ("l", "f"):
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        item_type = "lost" if parts[1] == "l" else "found"
        state.admin_state[call.message.chat.id] = {"type": item_type}
        msg = bot.send_message(call.message.chat.id, "Type a keyword to filter these listings (item, description, category, or location).")
        bot.register_next_step_handler(msg, lambda m: process_admin_keyword(bot, m))

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rm_ask:"))
    def cb_admin_remove_ask(call):
        if not require_admin_call(bot, call):
            return
        parts = call.data.split(":")
        if len(parts) != 3 or parts[1] not in ("l", "f") or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        item_type = helpers.parse_item_type(parts[1])
        item_id = int(parts[2])
        code = helpers.report_code(item_type, item_id)
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🗑 Yes, Remove", callback_data=f"rm_yes:{parts[1]}:{item_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"av:{parts[1]}:{item_id}"),
        )
        helpers.safe_send(
            bot,
            call.message.chat.id,
            f"⚠️ Remove this listing?\n\nReport:\n{code}\n\nThis action will remove the listing from normal active searches.",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rm_yes:"))
    def cb_admin_remove_yes(call):
        admin = require_admin_call(bot, call)
        if not admin:
            return
        parts = call.data.split(":")
        if len(parts) != 3 or parts[1] not in ("l", "f") or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        item_type = helpers.parse_item_type(parts[1])
        item_id = int(parts[2])
        code = helpers.report_code(item_type, item_id)
        database.update_item_fields(item_type, item_id, {"status": "DELETED"})
        item = database.get_item(item_type, item_id, active_only=False)
        admin_id = _admin_internal_id(admin)
        if admin_id:
            database.record_admin_action(
                admin_id,
                f"REMOVE_{item_type.upper()}",
                target_type=item_type,
                target_id=item_id,
                details=f"Admin removed listing {code}",
            )
        helpers.safe_answer(bot, call, "Listing removed")
        helpers.safe_send(bot, call.message.chat.id, f"Listing {code} has been removed from normal active searches.")
        if item:
            helpers.notify_user(
                bot,
                item["user_id"],
                "MODERATION",
                f"Your report {code} was removed by an administrator.",
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rst_ask:"))
    def cb_admin_restore_ask(call):
        if not require_admin_call(bot, call):
            return
        parts = call.data.split(":")
        if len(parts) != 3 or parts[1] not in ("l", "f") or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        helpers.safe_answer(bot, call)
        item_type = helpers.parse_item_type(parts[1])
        item_id = int(parts[2])
        code = helpers.report_code(item_type, item_id)
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("♻️ Yes, Restore", callback_data=f"rst_yes:{parts[1]}:{item_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"av:{parts[1]}:{item_id}"),
        )
        helpers.safe_send(
            bot,
            call.message.chat.id,
            f"⚠️ Restore this listing?\n\nReport:\n{code}\n\nThis action will restore the listing to active searches.",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("rst_yes:"))
    def cb_admin_restore_yes(call):
        admin = require_admin_call(bot, call)
        if not admin:
            return
        parts = call.data.split(":")
        if len(parts) != 3 or parts[1] not in ("l", "f") or not parts[2].isdigit():
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
            return
        item_type = helpers.parse_item_type(parts[1])
        item_id = int(parts[2])
        code = helpers.report_code(item_type, item_id)
        new_status = "LOST" if item_type == "lost" else "FOUND"
        database.update_item_fields(item_type, item_id, {"status": new_status})
        item = database.get_item(item_type, item_id, active_only=False)
        admin_id = _admin_internal_id(admin)
        if admin_id:
            database.record_admin_action(
                admin_id,
                f"RESTORE_{item_type.upper()}",
                target_type=item_type,
                target_id=item_id,
                details=f"Admin restored listing {code} to {new_status}",
            )
        helpers.safe_answer(bot, call, "Listing restored")
        helpers.safe_send(bot, call.message.chat.id, f"Listing {code} has been restored to {new_status}.")
        if item:
            helpers.notify_user(
                bot,
                item["user_id"],
                "STATUS",
                f"Your report {code} was restored to {new_status} by an administrator.",
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm:"))
    def cb_potential_matches(call):
        admin = require_admin_call(bot, call)
        if not admin:
            return
        parts = call.data.split(":")
        # pm:p:{page} | pm:ref | pm:v:{match_id} | pm:c:{match_id} | pm:r:{match_id}
        action = parts[1] if len(parts) > 1 else ""
        if action == "p":
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            helpers.safe_answer(bot, call)
            send_potential_matches_page(bot, call.message.chat.id, page, refresh=False)
        elif action == "ref":
            helpers.safe_answer(bot, call, "Refreshing matches...")
            send_potential_matches_page(bot, call.message.chat.id, 0, refresh=True)
        elif action == "v":
            if len(parts) < 3 or not parts[2].isdigit():
                helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
                return
            helpers.safe_answer(bot, call)
            send_potential_match_detail(bot, call.message.chat.id, int(parts[2]))
        elif action == "c":
            if len(parts) < 3 or not parts[2].isdigit():
                helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
                return
            confirm_potential_match(bot, call, admin, int(parts[2]))
        elif action == "r":
            if len(parts) < 3 or not parts[2].isdigit():
                helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
                return
            reject_potential_match(bot, call, admin, int(parts[2]))
        else:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)

    # Register ID card verification handlers
    register_id_verification_handlers(bot)

def process_admin_keyword(bot, message):
    if not require_admin_message(bot, message):
        return
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    admin = state.admin_state.get(message.chat.id)
    if not admin:
        show_admin_panel(bot, message)
        return
    keyword = message.text.strip() if message.content_type == "text" else ""
    if not keyword:
        helpers.safe_send(bot, message.chat.id, "Keyword cannot be empty.")
        return
    send_admin_items(bot, message.chat.id, admin["type"], 0, keyword=keyword)


def process_announce_text(bot, message):
    if not require_admin_message(bot, message):
        return
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    ok, text = validators.is_non_empty_text(getattr(message, "text", None), "Announcement", 1, 1500)
    if not ok:
        msg = bot.send_message(message.chat.id, text)
        bot.register_next_step_handler(msg, lambda m: process_announce_text(bot, m))
        return
    state.announce_state[message.chat.id] = {"step": "confirm", "text": text}
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Send Announcement", "❌ Cancel")
    msg = bot.send_message(
        message.chat.id,
        f"Send this announcement to all active users?\n\n{text}",
        reply_markup=markup,
    )
    bot.register_next_step_handler(msg, lambda m: process_announce_confirm(bot, m))


def process_announce_confirm(bot, message):
    if not require_admin_message(bot, message):
        return
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        return
    pending = state.announce_state.get(message.chat.id)
    if not pending or pending.get("step") != "confirm":
        show_admin_panel(bot, message)
        return
    if message.content_type != "text" or message.text != "✅ Send Announcement":
        state.announce_state.pop(message.chat.id, None)
        helpers.safe_send(bot, message.chat.id, "Announcement cancelled.")
        show_admin_panel(bot, message)
        return
    text = pending["text"].strip()
    if not text:
        helpers.safe_send(bot, message.chat.id, "Cannot send an empty announcement.")
        show_admin_panel(bot, message)
        return
    users = database.get_all_active_telegram_ids()
    sent = 0
    failed = 0
    for row in users:
        try:
            database.create_notification(row["id"], "ANNOUNCEMENT", text)
        except Exception:
            logger.exception("Failed to store announcement notification")
        try:
            bot.send_message(row["telegram_id"], f"📢 Announcement\n\n{text}")
            sent += 1
        except Exception:
            failed += 1
            logger.exception("Failed to deliver announcement")
    state.announce_state.pop(message.chat.id, None)
    helpers.safe_send(
        bot,
        message.chat.id,
        f"Announcement finished.\nDelivered: {sent}\nFailed: {failed}",
        reply_markup=admin_menu_markup(),
    )


def send_users_page(bot, chat_id, page):
    limit = 10
    offset = page * limit
    rows, total = database.get_users_page(offset, limit)
    if total == 0:
        helpers.safe_send(bot, chat_id, "No registered users yet.")
        return
    lines = [f"👥 Users (Page {page + 1})", ""]
    inline = InlineKeyboardMarkup()
    for row in rows:
        active = "Active" if row["is_active"] else "Inactive"
        username = f"@{row['username']}" if row["username"] else "No username"
        lines.append(
            f"ID #{row['id']} — {row['full_name']}\n{username} | {row['registered_at']} | {active}\n"
        )
        if row["is_active"]:
            inline.add(InlineKeyboardButton(f"Deactivate #{row['id']}", callback_data=f"ud:{row['id']}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"au:{page-1}"))
    if offset + limit < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"au:{page+1}"))
    if nav:
        inline.row(*nav)
    helpers.safe_send(bot, chat_id, "\n".join(lines), reply_markup=inline)


def send_admin_items(bot, chat_id, item_type, page, keyword=None):
    limit = 10
    offset = page * limit
    rows, total = database.search_items(
        item_type,
        keyword=keyword,
        category=None,
        location=None,
        offset=offset,
        limit=limit,
        include_inactive=True,
    )
    title = "🔴 All Lost Items" if item_type == "lost" else "🟢 All Found Items"
    if total == 0:
        helpers.safe_send(bot, chat_id, f"{title}\n\nNo reports found.")
        return
    short = "l" if item_type == "lost" else "f"
    lines = [f"{title} (Page {page + 1})", ""]
    inline = InlineKeyboardMarkup()
    inline.add(InlineKeyboardButton("🔎 Filter by keyword", callback_data=f"af:{short}"))
    for row in rows:
        code = helpers.report_code(item_type, row["id"])
        lines.append(
            f"{code} — {row['item_name']}\n{row['category']} | {row['location']} | {validators.iso_to_display(row['date'])} | {row['status']}\n"
        )
        inline.add(InlineKeyboardButton(f"Open {code}", callback_data=f"av:{short}:{row['id']}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"ai:{short}:{page-1}"))
    if offset + limit < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"ai:{short}:{page+1}"))
    if nav:
        inline.row(*nav)
    helpers.safe_send(bot, chat_id, "\n".join(lines), reply_markup=inline)


def send_admin_item_details(bot, chat_id, item, item_type):
    owner = database.get_user_by_id(item["user_id"])
    owner_name = owner["full_name"] if owner else "Unknown"
    caption = helpers.format_item_card(item, item_type)
    caption += f"\n\n<b>Owner name:</b> {helpers.esc(owner_name)}\n<b>Internal user ID:</b> {item['user_id']}"
    short = "l" if item_type == "lost" else "f"
    markup = InlineKeyboardMarkup()
    if item["status"] != "DELETED":
        if item_type == "lost":
            markup.add(InlineKeyboardButton("Set LOST", callback_data=f"as:{short}:{item['id']}:LOST"))
            markup.add(InlineKeyboardButton("Set RECOVERED", callback_data=f"as:{short}:{item['id']}:RECOVERED"))
        else:
            markup.add(InlineKeyboardButton("Set FOUND", callback_data=f"as:{short}:{item['id']}:FOUND"))
            markup.add(InlineKeyboardButton("Set RETURNED", callback_data=f"as:{short}:{item['id']}:RETURNED"))
        markup.add(InlineKeyboardButton("🗑 Remove listing", callback_data=f"rm_ask:{short}:{item['id']}"))
    else:
        # Listing is already deleted - allow admin to restore it (Requirement 17)
        markup.add(InlineKeyboardButton("♻️ Restore listing", callback_data=f"rst_ask:{short}:{item['id']}"))

    if item["photo_id"]:
        helpers.safe_send_photo(bot, chat_id, item["photo_id"], caption, markup)
    else:
        helpers.safe_send(bot, chat_id, caption, parse_mode="HTML", reply_markup=markup)


def send_potential_matches_page(bot, chat_id, page, refresh=False):
    if refresh:
        matching.refresh_matches_for_active_items()
    limit = 10
    offset = page * limit
    rows, total = database.get_potential_matches(offset=offset, limit=limit, min_score=matching.MATCH_THRESHOLD)
    if total == 0:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔄 Refresh Now", callback_data="pm:ref"))
        helpers.safe_send(
            bot,
            chat_id,
            f"🔎 Potential Matches\n\nNo pending potential matches found (threshold: {matching.MATCH_THRESHOLD}%+).",
            reply_markup=markup,
        )
        return

    lines = [f"🔎 Potential Matches (Page {page + 1})", ""]
    inline = InlineKeyboardMarkup()
    for row in rows:
        lost_code = helpers.report_code("lost", row["lost_item_id"])
        found_code = helpers.report_code("found", row["found_item_id"])
        item_title = row["lost_name"] or row["found_name"] or "Item"
        lines.append(f"⚠️ {row['match_score']}% — {lost_code} ↔ {found_code}\n{item_title}\n")
        inline.add(
            InlineKeyboardButton(
                f"Open {lost_code} ↔ {found_code} ({row['match_score']}%)",
                callback_data=f"pm:v:{row['id']}",
            )
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"pm:p:{page - 1}"))
    if offset + limit < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"pm:p:{page + 1}"))
    if nav:
        inline.row(*nav)
    inline.add(InlineKeyboardButton("🔄 Refresh Matches", callback_data="pm:ref"))
    helpers.safe_send(bot, chat_id, "\n".join(lines), reply_markup=inline)


def send_potential_match_detail(bot, chat_id, match_id):
    match_row, lost_item, found_item = database.get_match_detail(match_id)
    if not match_row or not lost_item or not found_item:
        helpers.safe_send(bot, chat_id, "This match is no longer available.")
        return

    lost_code = helpers.report_code("lost", lost_item["id"])
    found_code = helpers.report_code("found", found_item["id"])
    score = match_row["match_score"]
    level = "High Potential Match" if score >= 80 else "Possible Match"

    lost_date = validators.iso_to_display(lost_item["lost_date"]) if lost_item["lost_date"] else "N/A"
    found_date = validators.iso_to_display(found_item["found_date"]) if found_item["found_date"] else "N/A"

    reasons_text = match_row["matched_reasons"] or "Multiple similar factors"

    text = (
        "🔎 POTENTIAL MATCH\n\n"
        f"Match Score: {score}% ({level})\n\n"
        f"🔴 LOST REPORT\n"
        f"{lost_code}\n\n"
        f"Item:\n{lost_item['item_name']}\n\n"
        f"Category:\n{lost_item['category']}\n\n"
        f"Description:\n{lost_item['description'] or 'None'}\n\n"
        f"Location:\n{lost_item['location'] or 'None'}\n\n"
        f"Date:\n{lost_date}\n\n\n"
        f"🟢 FOUND REPORT\n"
        f"{found_code}\n\n"
        f"Item:\n{found_item['item_name']}\n\n"
        f"Category:\n{found_item['category']}\n\n"
        f"Description:\n{found_item['description'] or 'None'}\n\n"
        f"Location:\n{found_item['location'] or 'None'}\n\n"
        f"Date:\n{found_date}\n\n\n"
        f"Why this is a potential match:\n"
        f"{reasons_text}"
    )

    markup = InlineKeyboardMarkup()
    if match_row["status"] == "PENDING":
        markup.row(
            InlineKeyboardButton("✅ Confirm Match", callback_data=f"pm:c:{match_id}"),
            InlineKeyboardButton("❌ Reject Match", callback_data=f"pm:r:{match_id}"),
        )
    else:
        markup.add(InlineKeyboardButton(f"Status: {match_row['status']}", callback_data="none"))
    markup.add(InlineKeyboardButton("⬅️ Back to Matches", callback_data="pm:p:0"))
    helpers.safe_send(bot, chat_id, text, reply_markup=markup)


def confirm_potential_match(bot, call, admin, match_id):
    match_row, lost_item, found_item = database.get_match_detail(match_id)
    if not match_row or not lost_item or not found_item:
        helpers.safe_answer(bot, call, "Match not found.", show_alert=True)
        return
    database.update_match_status(match_id, "CONFIRMED")
    admin_id = _admin_internal_id(admin)
    if admin_id:
        database.record_admin_action(
            admin_id,
            "CONFIRM_MATCH",
            target_type="match",
            target_id=match_id,
            details=f"Confirmed match #{match_id} (Lost #{lost_item['id']} ↔ Found #{found_item['id']}, score {match_row['match_score']}%)",
        )
    helpers.safe_answer(bot, call, "Match Confirmed!")
    lost_code = helpers.report_code("lost", lost_item["id"])
    found_code = helpers.report_code("found", found_item["id"])
    helpers.safe_send(
        bot,
        call.message.chat.id,
        f"✅ Match confirmed: {lost_code} ↔ {found_code} ({match_row['match_score']}%).\n\n"
        f"The relationship is safely stored in the database.\n"
        f"(Note: Reports remain active until marked recovered or returned.)",
    )


def reject_potential_match(bot, call, admin, match_id):
    match_row, lost_item, found_item = database.get_match_detail(match_id)
    if not match_row or not lost_item or not found_item:
        helpers.safe_answer(bot, call, "Match not found.", show_alert=True)
        return
    database.update_match_status(match_id, "REJECTED")
    admin_id = _admin_internal_id(admin)
    if admin_id:
        database.record_admin_action(
            admin_id,
            "REJECT_MATCH",
            target_type="match",
            target_id=match_id,
            details=f"Rejected match #{match_id} (Lost #{lost_item['id']} ↔ Found #{found_item['id']})",
        )
    helpers.safe_answer(bot, call, "Match Rejected")
    lost_code = helpers.report_code("lost", lost_item["id"])
    found_code = helpers.report_code("found", found_item["id"])
    helpers.safe_send(
        bot,
        call.message.chat.id,
        f"❌ Match rejected: {lost_code} ↔ {found_code}.\n"
        f"This pair will no longer appear in the Potential Matches list.",
    )


# ---------------------------------------------------------------------------
# ID card verification panel (admin-only)
# ---------------------------------------------------------------------------

def send_id_verification_list(bot, chat_id, index=0):
    """Display a single pending registration to the admin, with approve/reject buttons."""
    try:
        pending = database.get_pending_id_verifications()
    except Exception:
        logger.exception("Failed to fetch pending ID verifications")
        helpers.safe_send(bot, chat_id, "Something went wrong. Please try again.")
        return

    if not pending:
        helpers.safe_send(
            bot,
            chat_id,
            f"{ID_VERIFY_BTN}\n\nNo pending registration requests at this time.",
            reply_markup=admin_menu_markup(),
        )
        return

    total = len(pending)
    index = max(0, min(index, total - 1))
    applicant = pending[index]

    name = applicant["full_name"] or applicant["name"] or "Unknown"
    tg_id = applicant["telegram_id"] or applicant["telegram_user_id"] or "?"
    submitted_at = applicant["submitted_at"] or "?"
    id_card_file_id = applicant["id_card_file_id"]

    caption = (
        f"🪪 Pending ID Verification ({index + 1} of {total})\n\n"
        f"Name: {name}\n"
        f"Telegram ID: {tg_id}\n"
        f"Submitted: {submitted_at}\n"
        f"Internal User ID: {applicant['id']}"
    )

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Approve Registration", callback_data=f"idv:approve:{applicant['id']}:{index}"),
        InlineKeyboardButton("❌ Reject Registration", callback_data=f"idv:reject:{applicant['id']}:{index}"),
    )
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"idv:list:{index - 1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"idv:list:{index + 1}"))
    if nav:
        markup.row(*nav)
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="idv:back"))

    if id_card_file_id:
        try:
            bot.send_photo(chat_id, id_card_file_id, caption=caption, reply_markup=markup)
            return
        except Exception:
            logger.exception("Failed to send ID card photo; falling back to text")
    helpers.safe_send(
        bot,
        chat_id,
        caption + "\n\n(ID card photo unavailable)",
        reply_markup=markup,
    )


def register_id_verification_handlers(bot):
    """Register the 'Pending ID Verifications' button and all idv: callbacks."""

    @bot.message_handler(
        func=lambda m: m.content_type == "text"
        and (
            m.text == ID_VERIFY_BTN
            or (m.text and "Pending ID Verifications" in m.text)
        )
    )
    def admin_id_verifications(message):
        if not require_admin_message(bot, message):
            return
        state.id_verify_state[message.chat.id] = {"index": 0}
        send_id_verification_list(bot, message.chat.id, 0)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("idv:"))
    def cb_id_verify(call):
        admin = require_admin_call(bot, call)
        if not admin:
            return
        parts = call.data.split(":")
        action = parts[1] if len(parts) > 1 else ""

        if action == "list":
            index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            helpers.safe_answer(bot, call)
            send_id_verification_list(bot, call.message.chat.id, index)

        elif action == "back":
            helpers.safe_answer(bot, call)
            helpers.safe_send(
                bot,
                call.message.chat.id,
                "👨‍💼 Admin Panel\n\nOnly administrators can use these tools.",
                reply_markup=admin_menu_markup(),
            )

        elif action == "approve":
            if len(parts) < 3 or not parts[2].isdigit():
                helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
                return
            user_internal_id = int(parts[2])
            index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            # Re-verify admin
            if not is_admin(call.from_user.id):
                helpers.safe_answer(bot, call, "ACCESS DENIED", show_alert=True)
                return
            target = database.get_user_by_id(user_internal_id)
            if not target:
                helpers.safe_answer(bot, call, "User not found.", show_alert=True)
                return
            current_status = target["reg_status"] if "reg_status" in target.keys() else "APPROVED"
            if current_status != "PENDING":
                helpers.safe_answer(bot, call, f"This registration is already {current_status}.", show_alert=True)
                send_id_verification_list(bot, call.message.chat.id, max(0, index - 1))
                return
            ok = database.set_user_reg_status(user_internal_id, "APPROVED", admin_telegram_id=call.from_user.id)
            if not ok:
                helpers.safe_answer(bot, call, "Could not update status. It may have already been reviewed.", show_alert=True)
                return
            helpers.safe_answer(bot, call, "Registration approved!")
            # Notify the user
            applicant_tg_id = target["telegram_id"] or target["telegram_user_id"]
            if applicant_tg_id:
                try:
                    bot.send_message(
                        applicant_tg_id,
                        "✅ Your college ID card has been verified, and your registration has been approved.\n\n"
                        "You can now use the KKWIEER Lost & Found Bot.\n"
                        "Send /start to continue.",
                    )
                except Exception:
                    logger.exception("Failed to notify user %s of approval", applicant_tg_id)
            name = target["full_name"] or target["name"] or "User"
            helpers.safe_send(bot, call.message.chat.id, f"✅ Approved registration for {name} (ID: {user_internal_id}).")
            send_id_verification_list(bot, call.message.chat.id, max(0, index - 1))

        elif action == "reject":
            if len(parts) < 3 or not parts[2].isdigit():
                helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)
                return
            user_internal_id = int(parts[2])
            index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            # Re-verify admin
            if not is_admin(call.from_user.id):
                helpers.safe_answer(bot, call, "ACCESS DENIED", show_alert=True)
                return
            target = database.get_user_by_id(user_internal_id)
            if not target:
                helpers.safe_answer(bot, call, "User not found.", show_alert=True)
                return
            current_status = target["reg_status"] if "reg_status" in target.keys() else "APPROVED"
            if current_status != "PENDING":
                helpers.safe_answer(bot, call, f"This registration is already {current_status}.", show_alert=True)
                send_id_verification_list(bot, call.message.chat.id, max(0, index - 1))
                return
            # Ask for a rejection reason via next step handler
            state.id_verify_state[call.message.chat.id] = {
                "step": "reject_reason",
                "user_internal_id": user_internal_id,
                "index": index,
            }
            helpers.safe_answer(bot, call)
            msg = bot.send_message(
                call.message.chat.id,
                f"Type a short rejection reason for this applicant, or type 'skip' to reject without a reason:",
            )
            bot.register_next_step_handler(msg, lambda m: process_reject_reason(bot, m))

        else:
            helpers.safe_answer(bot, call, "This button is no longer valid.", show_alert=True)


def process_reject_reason(bot, message):
    """Handle the admin's typed rejection reason."""
    if not is_admin(message.from_user.id):
        helpers.safe_send(bot, message.chat.id, "ACCESS DENIED.")
        return
    nav = item_flow.handle_cancel(bot, message)
    if nav:
        state.id_verify_state.pop(message.chat.id, None)
        return
    session = state.id_verify_state.get(message.chat.id, {})
    if session.get("step") != "reject_reason":
        show_admin_panel(bot, message)
        return

    user_internal_id = session.get("user_internal_id")
    index = session.get("index", 0)
    state.id_verify_state.pop(message.chat.id, None)

    reason = None
    if message.content_type == "text" and message.text.strip().lower() != "skip":
        reason = message.text.strip()[:300]

    target = database.get_user_by_id(user_internal_id)
    if not target:
        helpers.safe_send(bot, message.chat.id, "User not found. They may have been removed.")
        send_id_verification_list(bot, message.chat.id, max(0, index - 1))
        return

    current_status = target["reg_status"] if "reg_status" in target.keys() else "APPROVED"
    if current_status != "PENDING":
        helpers.safe_send(bot, message.chat.id, f"This registration is already {current_status}.")
        send_id_verification_list(bot, message.chat.id, max(0, index - 1))
        return

    ok = database.set_user_reg_status(
        user_internal_id, "REJECTED",
        admin_telegram_id=message.from_user.id,
        rejection_reason=reason,
    )
    if not ok:
        helpers.safe_send(bot, message.chat.id, "Could not update status. It may have already been reviewed.")
        return

    # Notify the user
    applicant_tg_id = target["telegram_id"] or target["telegram_user_id"]
    if applicant_tg_id:
        reason_text = f"\n\nReason: {reason}" if reason else ""
        try:
            bot.send_message(
                applicant_tg_id,
                f"❌ Your registration request was rejected by an administrator.{reason_text}\n\n"
                "If you believe this is a mistake, you may type /start to submit a new registration request.",
            )
        except Exception:
            logger.exception("Failed to notify user %s of rejection", applicant_tg_id)

    name = target["full_name"] or target["name"] or "User"
    helpers.safe_send(bot, message.chat.id, f"❌ Rejected registration for {name} (ID: {user_internal_id}).")
    send_id_verification_list(bot, message.chat.id, max(0, index - 1))

