from utils import helpers
from handlers import item_flow


def register(bot):
    @bot.message_handler(func=lambda m: m.content_type == "text" and m.text == "🟢 I Found Something")
    def start_found(message):
        user = helpers.get_registered_user(bot, message.from_user.id, message.chat.id)
        if not user:
            return
        item_flow.start_flow(bot, message, "found")
