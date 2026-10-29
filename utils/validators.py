import re
from datetime import datetime


def is_valid_name(text):
    if not text or not str(text).strip():
        return False, "Name cannot be empty."
    name = str(text).strip()
    if len(name) < 2:
        return False, "Please enter a name with at least 2 characters."
    if len(name) > 80:
        return False, "Name is too long. Please use up to 80 characters."
    if not re.search(r"[A-Za-z]", name):
        return False, "Please enter a real name using letters."
    if re.search(r"[<>{}[\]|\\]", name):
        return False, "Name contains invalid characters."
    return True, name


def is_non_empty_text(text, field_name, min_len=2, max_len=200):
    if text is None or not str(text).strip():
        return False, f"{field_name} cannot be empty."
    value = str(text).strip()
    if len(value) < min_len:
        return False, f"{field_name} is too short."
    if len(value) > max_len:
        return False, f"{field_name} is too long."
    return True, value


def parse_display_date(text):
    """Parse DD-MM-YYYY and reject future dates. Returns (ok, iso_date_or_error)."""
    raw = (text or "").strip()
    try:
        parsed = datetime.strptime(raw, "%d-%m-%Y").date()
    except ValueError:
        return False, "Invalid date. Use DD-MM-YYYY (example: 10-09-2026)."
    if parsed > datetime.today().date():
        return False, "Date cannot be in the future. Please try again."
    return True, parsed.strftime("%Y-%m-%d")


def iso_to_display(iso_date):
    if not iso_date:
        return "Not provided"
    text = str(iso_date)[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d-%m-%Y")
        except ValueError:
            pass
    return text


def is_valid_time_text(text):
    if not text or not str(text).strip():
        return False, "Please enter a time or choose Skip."
    value = str(text).strip()
    if len(value) > 50:
        return False, "Time text is too long."
    return True, value
