from handlers import (
    registration,
    item_flow,
    lost,
    found,
    search,
    reports,
    notifications,
    contact,
    admin,
)


def register_all(bot):
    registration.register(bot)
    item_flow.register(bot)
    lost.register(bot)
    found.register(bot)
    search.register(bot)
    reports.register(bot)
    notifications.register(bot)
    contact.register(bot)
    admin.register(bot)
