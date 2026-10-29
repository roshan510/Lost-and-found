import re
import logging
from difflib import SequenceMatcher
from datetime import datetime
from database import database

logger = logging.getLogger(__name__)

# Configurable threshold: only matches with score >= MATCH_THRESHOLD are treated as potential matches
MATCH_THRESHOLD = 60

# Common English and filler stop words to ignore when comparing meaningful descriptive terms
STOP_WORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "over", "after", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "it", "its", "this", "that", "these",
    "those", "i", "me", "my", "myself", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their", "there", "here", "found", "lost", "item",
    "some", "any", "please", "help", "thank", "thanks", "near", "around"
}

# Domain-specific word equivalences in campus lost & found
SYNONYMS = {
    "mobile": "phone",
    "cellphone": "phone",
    "smartphone": "phone",
    "backpack": "bag",
    "rucksack": "bag",
    "spectacles": "glasses",
    "specs": "glasses",
    "earbuds": "earphones",
    "headphones": "earphones",
    "airpods": "earphones",
    "tiffin": "bottle",
}


def normalize_text(text):
    """Lowercase and normalize whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).lower().strip())


def extract_meaningful_tokens(text):
    """Extract lowercase alphanumeric tokens excluding short words and stop words, normalized with synonyms."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z0-9]+\b", str(text).lower())
    tokens = []
    for w in words:
        if len(w) > 1 and w not in STOP_WORDS:
            tokens.append(SYNONYMS.get(w, w))
    return tokens


def calculate_token_similarity(tokens1, tokens2):
    """Calculate token overlap using Jaccard and containment metrics."""
    s1 = set(tokens1)
    s2 = set(tokens2)
    if not s1 or not s2:
        return 0.0
    overlap = len(s1 & s2)
    if overlap == 0:
        return 0.0
    jaccard = overlap / len(s1 | s2)
    containment = overlap / min(len(s1), len(s2))
    return max(jaccard, containment, 0.5 * jaccard + 0.5 * containment)


def calculate_category_score(cat1, cat2):
    """Category: 25 points if equal/equivalent, else 0."""
    c1 = normalize_text(cat1)
    c2 = normalize_text(cat2)
    if c1 and c2 and c1 == c2:
        return 25, "✓ Same category"
    return 0, None


def calculate_name_score(name1, name2):
    """Item Name: up to 30 points using SequenceMatcher and token overlap."""
    n1 = normalize_text(name1)
    n2 = normalize_text(name2)
    if not n1 or not n2:
        return 0, None
    if n1 == n2:
        return 30, "✓ Similar item name"

    seq_ratio = SequenceMatcher(None, n1, n2).ratio()
    tokens1 = extract_meaningful_tokens(n1)
    tokens2 = extract_meaningful_tokens(n2)
    token_ratio = calculate_token_similarity(tokens1, tokens2)

    best_ratio = max(seq_ratio, token_ratio, 0.5 * seq_ratio + 0.5 * token_ratio)
    score = round(best_ratio * 30)
    score = min(30, max(0, score))
    reason = "✓ Similar item name" if score >= 18 else None
    return score, reason


def calculate_description_score(desc1, desc2):
    """Description: up to 25 points recognizing common descriptive terms and token overlap."""
    d1 = normalize_text(desc1)
    d2 = normalize_text(desc2)
    if not d1 or not d2:
        return 0, None
    if d1 == d2:
        return 25, "✓ Strong description similarity"

    seq_ratio = SequenceMatcher(None, d1, d2).ratio()
    tokens1 = extract_meaningful_tokens(d1)
    tokens2 = extract_meaningful_tokens(d2)
    token_ratio = calculate_token_similarity(tokens1, tokens2)

    combined_ratio = max(seq_ratio, 0.3 * seq_ratio + 0.7 * token_ratio, token_ratio)
    score = round(combined_ratio * 25)
    score = min(25, max(0, score))

    if score >= 16:
        reason = "✓ Strong description similarity"
    elif score >= 10:
        reason = "✓ Similar description"
    else:
        reason = None
    return score, reason


def calculate_location_score(loc1, loc2):
    """Location: up to 10 points for exact match, containment, or high similarity."""
    l1 = normalize_text(loc1)
    l2 = normalize_text(loc2)
    if not l1 or not l2:
        return 0, None
    if l1 == l2 or l1 in l2 or l2 in l1:
        return 10, "✓ Same location"

    ratio = SequenceMatcher(None, l1, l2).ratio()
    if ratio >= 0.75:
        return 8, "✓ Same location"
    return 0, None


def calculate_date_score(lost_date_str, found_date_str):
    """Date: up to 10 points based on chronological proximity."""
    if not lost_date_str or not found_date_str:
        return 5, None  # Neutral score if date unknown

    try:
        ld = datetime.strptime(str(lost_date_str).strip(), "%Y-%m-%d").date()
        fd = datetime.strptime(str(found_date_str).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 5, None

    diff_days = (fd - ld).days
    if diff_days >= 0:
        if diff_days <= 3:
            return 10, "✓ Nearby dates"
        elif diff_days <= 7:
            return 8, "✓ Nearby dates"
        elif diff_days <= 14:
            return 5, None
        elif diff_days <= 30:
            return 3, None
        else:
            return 1, None
    else:
        # Found item reported 1-2 days before estimated lost date (human date estimate uncertainty)
        if diff_days >= -2:
            return 5, "✓ Nearby dates"
        return 0, None


def calculate_match(lost_item, found_item):
    """
    Compare a Lost item and a Found item across 5 explainable factors.
    Returns: (match_score: int, reasons: list[str], match_level: str)
    """
    cat_score, cat_reason = calculate_category_score(
        lost_item.get("category"), found_item.get("category")
    )
    name_score, name_reason = calculate_name_score(
        lost_item.get("item_name"), found_item.get("item_name")
    )
    desc_score, desc_reason = calculate_description_score(
        lost_item.get("description"), found_item.get("description")
    )
    loc_score, loc_reason = calculate_location_score(
        lost_item.get("location"), found_item.get("location")
    )

    lost_date = lost_item.get("lost_date") or lost_item.get("date")
    found_date = found_item.get("found_date") or found_item.get("date")
    date_score, date_reason = calculate_date_score(lost_date, found_date)

    total_score = cat_score + name_score + desc_score + loc_score + date_score
    total_score = min(100, max(0, total_score))

    reasons = []
    for r in (cat_reason, name_reason, desc_reason, loc_reason, date_reason):
        if r:
            reasons.append(r)

    if total_score >= 80:
        level = "High Potential Match"
    elif total_score >= 60:
        level = "Possible Match"
    else:
        level = "Low"

    return total_score, reasons, level


def refresh_matches_for_active_items():
    """
    Scans all active Lost and Found items in the database and records candidate matches
    at or above MATCH_THRESHOLD. Never crashes or overwrites confirmed/rejected decisions.
    """
    try:
        lost_items, found_items = database.get_active_items_for_matching()
        count = 0
        for lost in lost_items:
            for found in found_items:
                score, reasons, _ = calculate_match(dict(lost), dict(found))
                if score >= MATCH_THRESHOLD:
                    database.upsert_match(
                        lost["id"],
                        found["id"],
                        score,
                        "\n".join(reasons),
                    )
                    count += 1
        return count
    except Exception:
        logger.exception("Failed to refresh potential matches")
        return 0


def evaluate_single_item(item_type, item_id):
    """
    Safely evaluate potential matches for a newly created or updated item against
    all active complementary items.
    """
    try:
        target = database.get_item(item_type, item_id, active_only=True)
        if not target:
            return
        lost_items, found_items = database.get_active_items_for_matching()
        if item_type == "lost":
            for found in found_items:
                score, reasons, _ = calculate_match(dict(target), dict(found))
                if score >= MATCH_THRESHOLD:
                    database.upsert_match(target["id"], found["id"], score, "\n".join(reasons))
        else:
            for lost in lost_items:
                score, reasons, _ = calculate_match(dict(lost), dict(target))
                if score >= MATCH_THRESHOLD:
                    database.upsert_match(lost["id"], target["id"], score, "\n".join(reasons))
    except Exception:
        logger.exception("Failed to evaluate single item for matching: %s #%s", item_type, item_id)
