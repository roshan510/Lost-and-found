import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "lost_found.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(cursor, table_name, column_name, column_type, copy_from=None):
    """Add a column to a table if it doesn't already exist, and optionally backfill it."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        if copy_from and copy_from in columns:
            cursor.execute(f"UPDATE {table_name} SET {column_name} = {copy_from} WHERE {column_name} IS NULL")


def init_db():
    """Create tables if they do not exist, run non-destructive migrations. Never drops existing user data."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Users table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                telegram_user_id INTEGER UNIQUE,
                username TEXT,
                full_name TEXT,
                name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )'''
        )

        # 2. Lost items table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS lost_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                item_name TEXT NOT NULL,
                description TEXT,
                location TEXT,
                lost_date DATE,
                approximate_time TEXT,
                lost_time TEXT,
                photo_id TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'LOST',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )'''
        )

        # 3. Found items table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS found_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                item_name TEXT NOT NULL,
                description TEXT,
                location TEXT,
                found_date DATE,
                approximate_time TEXT,
                found_time TEXT,
                photo_id TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'FOUND',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )'''
        )

        # 4. Notifications table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type TEXT,
                lost_item_id INTEGER,
                found_item_id INTEGER,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (lost_item_id) REFERENCES lost_items(id) ON DELETE SET NULL,
                FOREIGN KEY (found_item_id) REFERENCES found_items(id) ON DELETE SET NULL
            )'''
        )

        # 5. Reports (moderation) table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                reporter_user_id INTEGER,
                lost_item_id INTEGER,
                reported_lost_item_id INTEGER,
                found_item_id INTEGER,
                reported_found_item_id INTEGER,
                reason TEXT NOT NULL,
                details TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (lost_item_id) REFERENCES lost_items(id) ON DELETE CASCADE,
                FOREIGN KEY (found_item_id) REFERENCES found_items(id) ON DELETE CASCADE
            )'''
        )

        # 6. Contact requests table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS contact_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_user_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                lost_item_id INTEGER,
                found_item_id INTEGER,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (requester_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (lost_item_id) REFERENCES lost_items(id) ON DELETE SET NULL,
                FOREIGN KEY (found_item_id) REFERENCES found_items(id) ON DELETE SET NULL
            )'''
        )

        # Non-destructive migrations for existing databases to support both naming schemas
        _ensure_column(cursor, "users", "telegram_user_id", "INTEGER", copy_from="telegram_id")
        _ensure_column(cursor, "users", "name", "TEXT", copy_from="full_name")
        _ensure_column(cursor, "lost_items", "lost_time", "TEXT", copy_from="approximate_time")
        _ensure_column(cursor, "lost_items", "photo_file_id", "TEXT", copy_from="photo_id")
        _ensure_column(cursor, "found_items", "found_time", "TEXT", copy_from="approximate_time")
        _ensure_column(cursor, "found_items", "photo_file_id", "TEXT", copy_from="photo_id")
        _ensure_column(cursor, "reports", "reporter_user_id", "INTEGER", copy_from="reporter_id")
        _ensure_column(cursor, "reports", "reported_lost_item_id", "INTEGER", copy_from="lost_item_id")
        _ensure_column(cursor, "reports", "reported_found_item_id", "INTEGER", copy_from="found_item_id")

        # ID card verification columns (non-destructive — added only if missing)
        _ensure_column(cursor, "users", "reg_status", "TEXT")
        _ensure_column(cursor, "users", "id_card_file_id", "TEXT")
        _ensure_column(cursor, "users", "submitted_at", "TIMESTAMP")
        _ensure_column(cursor, "users", "reviewed_at", "TIMESTAMP")
        _ensure_column(cursor, "users", "reviewed_by_admin", "INTEGER")
        _ensure_column(cursor, "users", "rejection_reason", "TEXT")

        # Migrate existing users (registered before this feature) to APPROVED so they are not locked out.
        cursor.execute(
            "UPDATE users SET reg_status = 'APPROVED' WHERE reg_status IS NULL"
        )

        # 7. Matches table (Admin potential matching)
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lost_item_id INTEGER NOT NULL,
                found_item_id INTEGER NOT NULL,
                match_score INTEGER NOT NULL,
                status TEXT DEFAULT 'PENDING',
                matched_reasons TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(lost_item_id, found_item_id),
                FOREIGN KEY (lost_item_id) REFERENCES lost_items(id) ON DELETE CASCADE,
                FOREIGN KEY (found_item_id) REFERENCES found_items(id) ON DELETE CASCADE
            )'''
        )

        # 8. Admin actions audit log table
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''
        )

        conn.commit()


def get_user_by_telegram_id(telegram_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE telegram_id = ? OR telegram_user_id = ?",
            (telegram_id, telegram_id),
        )
        return cursor.fetchone()


def get_user_by_id(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cursor.fetchone()


def create_user(telegram_id, username, full_name, id_card_file_id=None, reg_status="PENDING"):
    """Create a new user.  New registrations default to PENDING and require admin approval.
    Pass reg_status='APPROVED' only when migrating legacy rows programmatically."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users
               (telegram_id, telegram_user_id, username, full_name, name,
                id_card_file_id, reg_status, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (telegram_id, telegram_id, username, full_name, full_name,
             id_card_file_id, reg_status),
        )
        conn.commit()
        return cursor.lastrowid


def update_user_username(telegram_id, username):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET username = ? WHERE telegram_id = ? OR telegram_user_id = ?",
            (username, telegram_id, telegram_id),
        )
        conn.commit()


def set_user_active(user_id, is_active):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_users_page(offset=0, limit=10):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM users")
        total = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT id, telegram_id, telegram_user_id, username, full_name, name, registered_at, is_active
            FROM users
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return cursor.fetchall(), total


def get_all_active_telegram_ids():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, COALESCE(telegram_user_id, telegram_id) AS telegram_id FROM users WHERE is_active = 1"
        )
        return cursor.fetchall()


def save_lost_item(telegram_id, category, item_name, description, location, lost_date, approximate_time, photo_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE telegram_id = ? OR telegram_user_id = ?",
            (telegram_id, telegram_id),
        )
        user_row = cursor.fetchone()
        if not user_row:
            return None
        cursor.execute(
            '''INSERT INTO lost_items
               (user_id, category, item_name, description, location, lost_date,
                approximate_time, lost_time, photo_id, photo_file_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOST')''',
            (
                user_row["id"],
                category,
                item_name,
                description,
                location,
                lost_date,
                approximate_time,
                approximate_time,
                photo_id,
                photo_id,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def save_found_item(telegram_id, category, item_name, description, location, found_date, approximate_time, photo_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE telegram_id = ? OR telegram_user_id = ?",
            (telegram_id, telegram_id),
        )
        user_row = cursor.fetchone()
        if not user_row:
            return None
        cursor.execute(
            '''INSERT INTO found_items
               (user_id, category, item_name, description, location, found_date,
                approximate_time, found_time, photo_id, photo_file_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FOUND')''',
            (
                user_row["id"],
                category,
                item_name,
                description,
                location,
                found_date,
                approximate_time,
                approximate_time,
                photo_id,
                photo_id,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_item_fields(item_type, item_id, fields):
    """Update allowed columns on a lost or found item. Ownership is checked by callers."""
    allowed = {
        "category",
        "item_name",
        "description",
        "location",
        "lost_date",
        "found_date",
        "approximate_time",
        "lost_time",
        "found_time",
        "photo_id",
        "photo_file_id",
        "status",
    }
    table = "lost_items" if item_type == "lost" else "found_items"
    normalized_fields = dict(fields)
    # Sync alias columns
    if "approximate_time" in normalized_fields:
        time_alias = "lost_time" if item_type == "lost" else "found_time"
        normalized_fields[time_alias] = normalized_fields["approximate_time"]
    elif "lost_time" in normalized_fields and item_type == "lost":
        normalized_fields["approximate_time"] = normalized_fields["lost_time"]
    elif "found_time" in normalized_fields and item_type == "found":
        normalized_fields["approximate_time"] = normalized_fields["found_time"]

    if "photo_id" in normalized_fields:
        normalized_fields["photo_file_id"] = normalized_fields["photo_id"]
    elif "photo_file_id" in normalized_fields:
        normalized_fields["photo_id"] = normalized_fields["photo_file_id"]

    assignments = []
    params = []
    for key, value in normalized_fields.items():
        if key not in allowed:
            continue
        if item_type == "lost" and key in ("found_date", "found_time"):
            continue
        if item_type == "found" and key in ("lost_date", "lost_time"):
            continue
        assignments.append(f"{key} = ?")
        params.append(value)
    if not assignments:
        return False
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    params.append(item_id)
    sql = f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0


def get_item(item_type, item_id, active_only=False):
    with get_connection() as conn:
        cursor = conn.cursor()
        if item_type == "lost":
            sql = "SELECT * FROM lost_items WHERE id = ?"
            params = [item_id]
            if active_only:
                sql += " AND status = 'LOST'"
        elif item_type == "found":
            sql = "SELECT * FROM found_items WHERE id = ?"
            params = [item_id]
            if active_only:
                sql += " AND status = 'FOUND'"
        else:
            return None
        cursor.execute(sql, params)
        return cursor.fetchone()


def get_item_details(item_type, item_id):
    """Active listing only (public/search)."""
    return get_item(item_type, item_id, active_only=True)


def get_user_items(item_type, internal_user_id):
    table = "lost_items" if item_type == "lost" else "found_items"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT * FROM {table}
            WHERE user_id = ? AND status != 'DELETED'
            ORDER BY created_at DESC
            """,
            (internal_user_id,),
        )
        return cursor.fetchall()


def _escape_like(keyword):
    return (
        keyword.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def search_items(search_type, keyword=None, category=None, location=None, offset=0, limit=10, include_inactive=False):
    with get_connection() as conn:
        cursor = conn.cursor()
        queries = []
        if search_type in ("lost", "both"):
            if include_inactive:
                queries.append(
                    "SELECT 'lost' AS type, id, category, item_name, description, location, "
                    "lost_date AS date, COALESCE(approximate_time, lost_time) AS time, "
                    "COALESCE(photo_id, photo_file_id) AS photo_id, status "
                    "FROM lost_items WHERE status != 'DELETED'"
                )
            else:
                queries.append(
                    "SELECT 'lost' AS type, id, category, item_name, description, location, "
                    "lost_date AS date, COALESCE(approximate_time, lost_time) AS time, "
                    "COALESCE(photo_id, photo_file_id) AS photo_id, status "
                    "FROM lost_items WHERE status = 'LOST'"
                )
        if search_type in ("found", "both"):
            if include_inactive:
                queries.append(
                    "SELECT 'found' AS type, id, category, item_name, description, location, "
                    "found_date AS date, COALESCE(approximate_time, found_time) AS time, "
                    "COALESCE(photo_id, photo_file_id) AS photo_id, status "
                    "FROM found_items WHERE status != 'DELETED'"
                )
            else:
                queries.append(
                    "SELECT 'found' AS type, id, category, item_name, description, location, "
                    "found_date AS date, COALESCE(approximate_time, found_time) AS time, "
                    "COALESCE(photo_id, photo_file_id) AS photo_id, status "
                    "FROM found_items WHERE status = 'FOUND'"
                )

        if not queries:
            return [], 0

        base_query = " UNION ALL ".join(queries)
        final_query = f"SELECT * FROM ({base_query}) WHERE 1=1"
        params = []

        if category:
            final_query += " AND category = ?"
            params.append(category)
        if location:
            final_query += " AND location = ?"
            params.append(location)
        if keyword:
            final_query += (
                " AND (item_name LIKE ? ESCAPE '\\' "
                "OR description LIKE ? ESCAPE '\\' "
                "OR category LIKE ? ESCAPE '\\' "
                "OR location LIKE ? ESCAPE '\\')"
            )
            kw = f"%{_escape_like(keyword)}%"
            params.extend([kw, kw, kw, kw])

        cursor.execute(f"SELECT COUNT(*) FROM ({final_query})", params)
        total = cursor.fetchone()[0]

        final_query += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(final_query, params)
        return cursor.fetchall(), total


def item_matches_filters(item, item_type, keyword=None, category=None, location=None):
    if item is None:
        return False
    if category and item["category"] != category:
        return False
    if location and item["location"] != location:
        return False
    if keyword:
        blob = " ".join(
            [
                str(item["item_name"] or ""),
                str(item["description"] or ""),
                str(item["category"] or ""),
                str(item["location"] or ""),
            ]
        ).lower()
        if keyword.lower() not in blob:
            return False
    return item["status"] in ("LOST", "FOUND")


def create_notification(user_id, notif_type, message):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO notifications (user_id, notification_type, message)
               VALUES (?, ?, ?)''',
            (user_id, notif_type, message),
        )
        conn.commit()
        return cursor.lastrowid


def get_user_notifications(telegram_id, limit=15, offset=0):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT COUNT(*) AS total
            FROM notifications n
            JOIN users u ON n.user_id = u.id
            WHERE u.telegram_id = ? OR u.telegram_user_id = ?
            ''',
            (telegram_id, telegram_id),
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            '''
            SELECT n.* FROM notifications n
            JOIN users u ON n.user_id = u.id
            WHERE u.telegram_id = ? OR u.telegram_user_id = ?
            ORDER BY n.created_at DESC
            LIMIT ? OFFSET ?
            ''',
            (telegram_id, telegram_id, limit, offset),
        )
        return cursor.fetchall(), total


def get_notification_for_user(notif_id, telegram_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT n.* FROM notifications n
            JOIN users u ON n.user_id = u.id
            WHERE n.id = ? AND (u.telegram_id = ? OR u.telegram_user_id = ?)
            ''',
            (notif_id, telegram_id, telegram_id),
        )
        return cursor.fetchone()


def mark_notification_read(notif_id, telegram_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE notifications
            SET is_read = 1
            WHERE id = ?
              AND user_id = (SELECT id FROM users WHERE telegram_id = ? OR telegram_user_id = ?)
            ''',
            (notif_id, telegram_id, telegram_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def create_listing_report(reporter_internal_id, item_type, item_id, reason, details):
    with get_connection() as conn:
        cursor = conn.cursor()
        lost_id = item_id if item_type == "lost" else None
        found_id = item_id if item_type == "found" else None
        cursor.execute(
            '''INSERT INTO reports
               (reporter_id, reporter_user_id, lost_item_id, reported_lost_item_id,
                found_item_id, reported_found_item_id, reason, details, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')''',
            (
                reporter_internal_id,
                reporter_internal_id,
                lost_id,
                lost_id,
                found_id,
                found_id,
                reason,
                details,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_moderation_reports(status=None, offset=0, limit=10):
    with get_connection() as conn:
        cursor = conn.cursor()
        where = ""
        params = []
        if status:
            where = "WHERE r.status = ?"
            params.append(status)
        cursor.execute(f"SELECT COUNT(*) AS total FROM reports r {where}", params)
        total = cursor.fetchone()["total"]
        cursor.execute(
            f'''
            SELECT r.*,
                   COALESCE(u.full_name, u.name) AS reporter_name,
                   li.item_name AS lost_name,
                   fi.item_name AS found_name
            FROM reports r
            JOIN users u ON COALESCE(r.reporter_user_id, r.reporter_id) = u.id
            LEFT JOIN lost_items li ON COALESCE(r.reported_lost_item_id, r.lost_item_id) = li.id
            LEFT JOIN found_items fi ON COALESCE(r.reported_found_item_id, r.found_item_id) = fi.id
            {where}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
            ''',
            params + [limit, offset],
        )
        return cursor.fetchall(), total


def get_moderation_report(report_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        return cursor.fetchone()


def update_moderation_status(report_id, status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET status = ? WHERE id = ?", (status, report_id))
        conn.commit()
        return cursor.rowcount > 0


def create_contact_request(requester_user_id, target_user_id, item_type, item_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        lost_id = item_id if item_type == "lost" else None
        found_id = item_id if item_type == "found" else None
        cursor.execute(
            '''
            SELECT id, status FROM contact_requests
            WHERE requester_user_id = ?
              AND target_user_id = ?
              AND COALESCE(lost_item_id, 0) = COALESCE(?, 0)
              AND COALESCE(found_item_id, 0) = COALESCE(?, 0)
              AND status IN ('PENDING', 'ACCEPTED')
            ''',
            (requester_user_id, target_user_id, lost_id, found_id),
        )
        existing = cursor.fetchone()
        if existing:
            return existing["id"], existing["status"], False
        cursor.execute(
            '''INSERT INTO contact_requests
               (requester_user_id, target_user_id, lost_item_id, found_item_id, status)
               VALUES (?, ?, ?, ?, 'PENDING')''',
            (requester_user_id, target_user_id, lost_id, found_id),
        )
        conn.commit()
        return cursor.lastrowid, "PENDING", True


def get_contact_request(request_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contact_requests WHERE id = ?", (request_id,))
        return cursor.fetchone()


def update_contact_status(request_id, status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''UPDATE contact_requests
               SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (status, request_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_statistics():
    with get_connection() as conn:
        cursor = conn.cursor()
        stats = {}
        cursor.execute("SELECT COUNT(*) FROM users")
        stats["total_users"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        stats["active_users"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM lost_items WHERE status != 'DELETED'")
        stats["total_lost"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM lost_items WHERE status = 'LOST'")
        stats["active_lost"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM lost_items WHERE status = 'RECOVERED'")
        stats["recovered"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM found_items WHERE status != 'DELETED'")
        stats["total_found"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM found_items WHERE status = 'FOUND'")
        stats["active_found"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM found_items WHERE status = 'RETURNED'")
        stats["returned"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'PENDING'")
        stats["pending_moderation"] = cursor.fetchone()[0]
        return stats


def get_telegram_id_by_internal_user_id(user_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(telegram_user_id, telegram_id) AS telegram_id FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        return row["telegram_id"] if row else None


def record_admin_action(admin_user_id, action, target_type=None, target_id=None, details=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO admin_actions (admin_user_id, action, target_type, target_id, details)
               VALUES (?, ?, ?, ?, ?)''',
            (admin_user_id, action, target_type, target_id, details),
        )
        conn.commit()
        return cursor.lastrowid


def upsert_match(lost_item_id, found_item_id, match_score, matched_reasons):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, status FROM matches WHERE lost_item_id = ? AND found_item_id = ?",
            (lost_item_id, found_item_id),
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                '''INSERT INTO matches (lost_item_id, found_item_id, match_score, status, matched_reasons)
                   VALUES (?, ?, ?, 'PENDING', ?)''',
                (lost_item_id, found_item_id, match_score, matched_reasons),
            )
            conn.commit()
            return cursor.lastrowid
        elif row["status"] == "PENDING":
            cursor.execute(
                '''UPDATE matches
                   SET match_score = ?, matched_reasons = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (match_score, matched_reasons, row["id"]),
            )
            conn.commit()
            return row["id"]
        return row["id"]


def get_potential_matches(offset=0, limit=10, min_score=60):
    with get_connection() as conn:
        cursor = conn.cursor()
        count_sql = """
            SELECT COUNT(*) AS total
            FROM matches m
            JOIN lost_items li ON m.lost_item_id = li.id
            JOIN found_items fi ON m.found_item_id = fi.id
            WHERE m.status = 'PENDING'
              AND m.match_score >= ?
              AND li.status = 'LOST'
              AND fi.status = 'FOUND'
        """
        cursor.execute(count_sql, (min_score,))
        total = cursor.fetchone()["total"]

        sql = """
            SELECT m.*,
                   li.item_name AS lost_name, li.category AS lost_category,
                   fi.item_name AS found_name, fi.category AS found_category
            FROM matches m
            JOIN lost_items li ON m.lost_item_id = li.id
            JOIN found_items fi ON m.found_item_id = fi.id
            WHERE m.status = 'PENDING'
              AND m.match_score >= ?
              AND li.status = 'LOST'
              AND fi.status = 'FOUND'
            ORDER BY m.match_score DESC, m.id DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(sql, (min_score, limit, offset))
        return cursor.fetchall(), total


def get_match_detail(match_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        match_row = cursor.fetchone()
        if not match_row:
            return None, None, None
        cursor.execute("SELECT * FROM lost_items WHERE id = ?", (match_row["lost_item_id"],))
        lost_row = cursor.fetchone()
        cursor.execute("SELECT * FROM found_items WHERE id = ?", (match_row["found_item_id"],))
        found_row = cursor.fetchone()
        return match_row, lost_row, found_row


def update_match_status(match_id, status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''UPDATE matches
               SET status = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?''',
            (status, match_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_active_items_for_matching():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lost_items WHERE status = 'LOST'")
        lost_items = cursor.fetchall()
        cursor.execute("SELECT * FROM found_items WHERE status = 'FOUND'")
        found_items = cursor.fetchall()
        return lost_items, found_items



# ---------------------------------------------------------------------------
# ID card verification functions
# ---------------------------------------------------------------------------

def get_pending_id_verifications():
    """Return all users with reg_status = 'PENDING', newest first."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE reg_status = 'PENDING' ORDER BY submitted_at DESC"
        )
        return cursor.fetchall()


def get_pending_id_verification_count():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE reg_status = 'PENDING'")
        return cursor.fetchone()[0]


def set_user_reg_status(user_internal_id, status, admin_telegram_id=None, rejection_reason=None):
    """Update registration status only if currently PENDING (prevents double-action corruption)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE users
               SET reg_status = ?,
                   reviewed_at = CURRENT_TIMESTAMP,
                   reviewed_by_admin = ?,
                   rejection_reason = ?
               WHERE id = ? AND reg_status = 'PENDING'""",
            (status, admin_telegram_id, rejection_reason, user_internal_id),
        )
        conn.commit()
        return cursor.rowcount > 0
