import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN found. Check your .env file.")


def _parse_admin_ids(raw_value):
    """Turn ADMIN_IDS from .env into a set of integers."""
    admin_ids = set()
    if not raw_value:
        return admin_ids
    cleaned = raw_value.replace(";", ",")
    for part in cleaned.split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.add(int(part))
    return admin_ids


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))


def is_admin(telegram_user_id):
    try:
        return int(telegram_user_id) in ADMIN_IDS
    except (TypeError, ValueError):
        return False
