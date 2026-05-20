import os
import time
import aiosqlite
from pathlib import Path
from cryptography.fernet import Fernet

DB_PATH = Path(os.getenv("DB_PATH", "data/transparency.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
MESSAGE_TTL = 7 * 86400  # 7 дней


def _fernet() -> Fernet:
    from config import config
    return Fernet(config.fernet_key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


# ── Инициализация ─────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                premium_until INTEGER DEFAULT 0,
                consent_given INTEGER DEFAULT 0,
                is_owner      INTEGER DEFAULT 0,
                created_at    INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                user_id         INTEGER PRIMARY KEY,
                session_enc     TEXT NOT NULL,
                account_tg_id   INTEGER,
                created_at      INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id      INTEGER NOT NULL,
                chat_id       INTEGER NOT NULL,
                message_id    INTEGER NOT NULL,
                from_username TEXT,
                from_name     TEXT,
                chat_title    TEXT,
                chat_username TEXT,
                chat_type     TEXT,
                text          TEXT,
                caption       TEXT,
                media_type    TEXT,
                file_id       TEXT,
                is_viewonce   INTEGER DEFAULT 0,
                date          INTEGER NOT NULL,
                expires_at    INTEGER NOT NULL,
                UNIQUE(owner_id, chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS edits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id   INTEGER NOT NULL,
                chat_id    INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                old_text   TEXT,
                new_text   TEXT,
                edited_at  INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS muted_chats (
                owner_id INTEGER NOT NULL,
                chat_id  INTEGER NOT NULL,
                PRIMARY KEY (owner_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                charge_id   TEXT NOT NULL UNIQUE,
                amount      INTEGER NOT NULL,
                months      INTEGER NOT NULL,
                created_at  INTEGER NOT NULL,
                refunded_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS chat_filters (
                owner_id  INTEGER NOT NULL,
                chat_type TEXT NOT NULL,
                mode      TEXT NOT NULL DEFAULT 'all',
                PRIMARY KEY (owner_id, chat_type)
            );

            CREATE TABLE IF NOT EXISTS chat_exceptions (
                owner_id      INTEGER NOT NULL,
                chat_id       INTEGER NOT NULL,
                chat_title    TEXT NOT NULL DEFAULT '',
                chat_username TEXT,
                chat_type     TEXT NOT NULL,
                PRIMARY KEY (owner_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS invites (
                code       TEXT PRIMARY KEY,
                owner_id   INTEGER NOT NULL UNIQUE,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invite_uses (
                code    TEXT NOT NULL,
                used_by INTEGER NOT NULL,
                used_at INTEGER NOT NULL,
                PRIMARY KEY (code, used_by)
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                code       TEXT PRIMARY KEY,
                months     INTEGER NOT NULL,
                max_uses   INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                expires_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS promo_uses (
                code    TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                used_at INTEGER NOT NULL,
                PRIMARY KEY (code, user_id)
            );

            CREATE TABLE IF NOT EXISTS public_group_monitors (
                owner_id      INTEGER NOT NULL,
                chat_id       INTEGER NOT NULL,
                chat_username TEXT NOT NULL,
                chat_title    TEXT NOT NULL DEFAULT '',
                added_at      INTEGER NOT NULL,
                PRIMARY KEY (owner_id, chat_id)
            );
        """)
        # Миграции: добавляем новые колонки если их нет
        migrations = [
            ("ALTER TABLE messages ADD COLUMN chat_username TEXT",),
            ("ALTER TABLE users ADD COLUMN trial_until INTEGER DEFAULT 0",),
            ("ALTER TABLE users ADD COLUMN trial_expired_notified INTEGER DEFAULT 0",),
            ("ALTER TABLE users ADD COLUMN display_name TEXT",),
            ("ALTER TABLE users ADD COLUMN premium_plus_until INTEGER DEFAULT 0",),
            ("ALTER TABLE promo_codes ADD COLUMN promo_type TEXT DEFAULT 'premium'",),
        ]
        for (sql,) in migrations:
            try:
                await db.execute(sql)
                await db.commit()
            except aiosqlite.OperationalError:
                pass
        await db.commit()


# ── Очистка устаревших сообщений ──────────────────────────────────────────────

async def purge_expired() -> int:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM messages WHERE expires_at < ?", (now,))
        await db.commit()
        return cur.rowcount


# ── Пользователи ──────────────────────────────────────────────────────────────

async def ensure_user(user_id: int, is_owner: bool = False, display_name: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, is_owner, created_at) VALUES (?,?,?)",
            (user_id, int(is_owner), int(time.time())),
        )
        if is_owner:
            await db.execute("UPDATE users SET is_owner=1 WHERE user_id=?", (user_id,))
        if display_name:
            await db.execute("UPDATE users SET display_name=? WHERE user_id=?", (display_name, user_id))
        await db.commit()


async def set_consent(user_id: int, given: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET consent_given=? WHERE user_id=?", (int(given), user_id))
        await db.commit()


async def has_consent(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT consent_given FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return bool(row[0]) if row else False


async def is_premium(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_until, trial_until, is_owner FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    premium_until, trial_until, is_owner = row
    now = int(time.time())
    return (
        bool(is_owner)
        or bool(premium_until and premium_until > now)
        or bool(trial_until and trial_until > now)
    )


async def revoke_premium(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET premium_until=0 WHERE user_id=?", (user_id,))
        await db.commit()


async def is_premium_plus(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_plus_until, is_owner FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    plus_until, is_owner = row
    return bool(is_owner) or bool(plus_until and plus_until > int(time.time()))


async def set_premium_plus(user_id: int, months: int = 1) -> int:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_plus_until FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    base = max((row[0] or 0) if row else 0, now)
    new_until = base + months * 30 * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET premium_plus_until=? WHERE user_id=?", (new_until, user_id)
        )
        await db.commit()
    return new_until


async def revoke_premium_plus(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET premium_plus_until=0 WHERE user_id=?", (user_id,))
        await db.commit()


async def reset_days(user_id: int) -> None:
    """Сбрасывает premium_until и trial_until в 0 (для тестирования бесплатного режима)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET premium_until=0, trial_until=0, trial_expired_notified=0 WHERE user_id=?",
            (user_id,),
        )
        await db.commit()


async def extend_days(user_id: int, days: int) -> int:
    """Добавляет дни поверх текущего остатка. Возвращает новый timestamp истечения."""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_until, trial_until FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return 0
    base = max(row[0] or 0, row[1] or 0, now)
    new_until = base + days * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET premium_until=?, trial_expired_notified=0 WHERE user_id=?",
            (new_until, user_id),
        )
        await db.commit()
    return new_until


async def set_premium(user_id: int, months: int = 1) -> int:
    return await extend_days(user_id, months * 30)


async def give_trial(user_id: int, days: int = 7) -> bool:
    """Выдаёт пробный период только если ещё не выдавался. Возвращает True при успехе."""
    trial_until = int(time.time()) + days * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE users SET trial_until=? WHERE user_id=? AND (trial_until IS NULL OR trial_until=0)",
            (trial_until, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_days_left(user_id: int) -> int:
    """Возвращает дней до истечения. -1 для владельца. 0 если истёк."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_until, trial_until, is_owner FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return 0
    premium_until, trial_until, is_owner = row
    if is_owner:
        return -1
    now = int(time.time())
    until = max(premium_until or 0, trial_until or 0)
    if until <= now:
        return 0
    return max(1, (until - now + 86399) // 86400)


async def get_premium_until(user_id: int) -> int:
    """Returns -1 for owner (unlimited), 0 if no premium, else unix timestamp."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_until, trial_until, is_owner FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return 0
    premium_until, trial_until, is_owner = row
    if is_owner:
        return -1
    return max(premium_until or 0, trial_until or 0)


async def get_users_to_notify_expiry() -> list[int]:
    """Пользователи, у которых закончился доступ и ещё не было уведомления."""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT user_id FROM users
               WHERE trial_until > 0
                 AND trial_until < ?
                 AND (premium_until IS NULL OR premium_until < ?)
                 AND trial_expired_notified = 0""",
            (now, now),
        ) as cur:
            rows = await cur.fetchall()
    return [r["user_id"] for r in rows]


async def mark_trial_notified(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET trial_expired_notified=1 WHERE user_id=?", (user_id,)
        )
        await db.commit()


# ── Инвайты ───────────────────────────────────────────────────────────────────

async def create_invite(owner_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT code FROM invites WHERE owner_id=?", (owner_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row[0]
        import secrets as _secrets
        code = _secrets.token_urlsafe(8)
        await db.execute(
            "INSERT INTO invites (code, owner_id, created_at) VALUES (?,?,?)",
            (code, owner_id, int(time.time())),
        )
        await db.commit()
    return code


async def use_invite(code: str, new_user_id: int) -> int | None:
    """Начисляет реферальную награду. Возвращает owner_id или None если недопустимо."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT owner_id FROM invites WHERE code=?", (code,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        owner_id = row[0]
        if owner_id == new_user_id:
            return None
        async with db.execute(
            "SELECT 1 FROM invite_uses WHERE code=? AND used_by=?", (code, new_user_id)
        ) as cur:
            already = await cur.fetchone()
        if already:
            return None
        await db.execute(
            "INSERT INTO invite_uses (code, used_by, used_at) VALUES (?,?,?)",
            (code, new_user_id, int(time.time())),
        )
        await db.commit()
    return owner_id


async def delete_user_data(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE owner_id=?", (user_id,))
        await db.execute("DELETE FROM edits WHERE owner_id=?", (user_id,))
        await db.execute("DELETE FROM muted_chats WHERE owner_id=?", (user_id,))
        await db.execute("DELETE FROM chat_filters WHERE owner_id=?", (user_id,))
        await db.execute("DELETE FROM chat_exceptions WHERE owner_id=?", (user_id,))
        await db.execute("DELETE FROM payments WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM invites WHERE owner_id=?", (user_id,))
        await db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        await db.commit()


# ── Сессии userbot ────────────────────────────────────────────────────────────

async def save_session(user_id: int, session_string: str, account_tg_id: int | None = None) -> None:
    encrypted = encrypt(session_string)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO sessions (user_id, session_enc, account_tg_id, created_at)
            VALUES (?,?,?,?)
        """, (user_id, encrypted, account_tg_id, int(time.time())))
        await db.commit()


async def get_session(user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT session_enc FROM sessions WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return decrypt(row[0])


async def get_all_sessions() -> list[tuple[int, str]]:
    """Returns list of (user_id, session_string) for all connected accounts."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, session_enc FROM sessions") as cur:
            rows = await cur.fetchall()
    result = []
    for user_id, enc in rows:
        try:
            result.append((user_id, decrypt(enc)))
        except Exception:
            pass  # испорченная/устаревшая сессия
    return result


async def delete_session(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        await db.commit()


# ── Сообщения (кеш) ───────────────────────────────────────────────────────────

async def save_message(
    owner_id: int, chat_id: int, message_id: int,
    from_username: str | None, from_name: str,
    chat_title: str, chat_username: str | None, chat_type: str,
    text: str | None, caption: str | None,
    media_type: str | None, file_id: str | None,
    is_viewonce: bool, date: int,
) -> None:
    expires_at = date + MESSAGE_TTL
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO messages
                (owner_id, chat_id, message_id, from_username, from_name,
                 chat_title, chat_username, chat_type, text, caption, media_type, file_id,
                 is_viewonce, date, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (owner_id, chat_id, message_id, from_username, from_name,
              chat_title, chat_username, chat_type, text, caption, media_type, file_id,
              int(is_viewonce), date, expires_at))
        await db.commit()


async def get_message(owner_id: int, chat_id: int, message_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?",
            (owner_id, chat_id, message_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def find_by_msg_id(owner_id: int, message_id: int) -> dict | None:
    """Fallback: ищем по message_id когда chat_id неизвестен (приватные/группы).
    Приоритет отдаём не-приватным чатам чтобы избежать коллизий ID."""
    week_ago = int(time.time()) - MESSAGE_TTL
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM messages
               WHERE owner_id=? AND message_id=? AND date>?
               ORDER BY CASE WHEN chat_type != 'private' THEN 0 ELSE 1 END, date DESC
               LIMIT 1""",
            (owner_id, message_id, week_ago),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def save_edit(
    owner_id: int, chat_id: int, message_id: int,
    old_text: str | None, new_text: str | None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO edits (owner_id, chat_id, message_id, old_text, new_text, edited_at) VALUES (?,?,?,?,?,?)",
            (owner_id, chat_id, message_id, old_text, new_text, int(time.time())),
        )
        await db.commit()


# ── Заглушённые чаты ─────────────────────────────────────────────────────────

# ── Платежи ───────────────────────────────────────────────────────────────────

async def save_payment(user_id: int, charge_id: str, amount: int, months: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO payments (user_id, charge_id, amount, months, created_at) VALUES (?,?,?,?,?)",
            (user_id, charge_id, amount, months, int(time.time())),
        )
        await db.commit()


async def get_last_payment(user_id: int) -> dict | None:
    """Последний неотозванный платёж пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM payments WHERE user_id=? AND refunded_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def mark_refunded(charge_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET refunded_at=? WHERE charge_id=?",
            (int(time.time()), charge_id),
        )
        await db.commit()


# ── Фильтры чатов ─────────────────────────────────────────────────────────────

async def get_filter_mode(owner_id: int, chat_type: str) -> str:
    """Возвращает 'all' или 'none' для типа чата (group/channel)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT mode FROM chat_filters WHERE owner_id=? AND chat_type=?",
            (owner_id, chat_type),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else "all"


async def set_filter_mode(owner_id: int, chat_type: str, mode: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO chat_filters (owner_id, chat_type, mode) VALUES (?,?,?)",
            (owner_id, chat_type, mode),
        )
        await db.commit()


async def is_exception(owner_id: int, chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM chat_exceptions WHERE owner_id=? AND chat_id=?",
            (owner_id, chat_id),
        ) as cur:
            return await cur.fetchone() is not None


async def add_exception(
    owner_id: int, chat_id: int,
    chat_title: str, chat_username: str | None, chat_type: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO chat_exceptions (owner_id, chat_id, chat_title, chat_username, chat_type) VALUES (?,?,?,?,?)",
            (owner_id, chat_id, chat_title, chat_username, chat_type),
        )
        await db.commit()


async def remove_exception(owner_id: int, chat_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM chat_exceptions WHERE owner_id=? AND chat_id=?",
            (owner_id, chat_id),
        )
        await db.commit()


async def get_exceptions(owner_id: int, chat_type: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM chat_exceptions WHERE owner_id=? AND chat_type=? ORDER BY chat_title",
            (owner_id, chat_type),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_recent_chats(owner_id: int, chat_type: str, limit: int = 20) -> list[dict]:
    """Уникальные чаты из кеша сообщений для выбора исключений."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT chat_id, chat_title, chat_username, MAX(date) as last_date
               FROM messages
               WHERE owner_id=? AND chat_type=?
               GROUP BY chat_id
               ORDER BY last_date DESC
               LIMIT ?""",
            (owner_id, chat_type, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Админ-панель ──────────────────────────────────────────────────────────────

async def admin_overview() -> dict:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_owner=0") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE is_owner=0 AND premium_until > ?", (now,)
        ) as cur:
            premium = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE is_owner=0 AND trial_until > ? AND (premium_until IS NULL OR premium_until <= ?)",
            (now, now),
        ) as cur:
            trial = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM sessions") as cur:
            sessions = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE refunded_at IS NULL"
        ) as cur:
            revenue = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE is_owner=0 AND created_at > ?", (now - 86400,)
        ) as cur:
            new_today = (await cur.fetchone())[0]
    return {
        "total": total,
        "premium": premium,
        "trial": trial,
        "free": total - premium - trial,
        "sessions": sessions,
        "revenue": revenue,
        "new_today": new_today,
    }


async def admin_users_page(page: int, per_page: int = 10) -> tuple[list[dict], int]:
    now = int(time.time())
    offset = page * per_page
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_owner=0") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            """SELECT user_id, display_name, is_owner, premium_until, trial_until, created_at
               FROM users WHERE is_owner=0
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (per_page, offset),
        ) as cur:
            rows = await cur.fetchall()
    users = []
    for r in rows:
        d = dict(r)
        pu, tu = d.get("premium_until") or 0, d.get("trial_until") or 0
        until = max(pu, tu)
        days = max(0, (until - now + 86399) // 86400) if until > now else 0
        d["days_left"] = days
        d["status"] = "premium" if pu > now else ("trial" if tu > now else "free")
        users.append(d)
    return users, total


async def admin_user_detail(user_id: int) -> dict | None:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.user_id, u.display_name, u.is_owner, u.premium_until, u.trial_until,
                      u.created_at, s.account_tg_id,
                      (SELECT COUNT(*) FROM payments p
                       WHERE p.user_id=u.user_id AND p.refunded_at IS NULL) AS payment_count,
                      (SELECT COALESCE(SUM(p.amount),0) FROM payments p
                       WHERE p.user_id=u.user_id AND p.refunded_at IS NULL) AS total_spent,
                      (SELECT COUNT(*) FROM invite_uses iu
                       JOIN invites i ON i.code=iu.code
                       WHERE i.owner_id=u.user_id) AS invites_sent
               FROM users u LEFT JOIN sessions s ON s.user_id=u.user_id
               WHERE u.user_id=?""",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    pu, tu = d.get("premium_until") or 0, d.get("trial_until") or 0
    until = max(pu, tu)
    d["days_left"] = max(0, (until - now + 86399) // 86400) if until > now else 0
    d["until"] = until
    d["status"] = "owner" if d.get("is_owner") else (
        "premium" if pu > now else ("trial" if tu > now else "free")
    )
    return d


async def admin_all_user_ids(status_filter: str | None = None) -> list[int]:
    """Список всех user_id для рассылки. status_filter: 'premium'|'trial'|'free'|None."""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status_filter == "premium":
            sql = "SELECT user_id FROM users WHERE premium_until > ?"
            args = (now,)
        elif status_filter == "trial":
            sql = "SELECT user_id FROM users WHERE trial_until > ? AND (premium_until IS NULL OR premium_until <= ?)"
            args = (now, now)
        elif status_filter == "free":
            sql = "SELECT user_id FROM users WHERE (premium_until IS NULL OR premium_until <= ?) AND (trial_until IS NULL OR trial_until <= ?)"
            args = (now, now)
        else:
            sql = "SELECT user_id FROM users"
            args = ()
        async with db.execute(sql, args) as cur:
            rows = await cur.fetchall()
    return [r["user_id"] for r in rows]


# ── Промокоды ─────────────────────────────────────────────────────────────────

async def use_promo(code: str, user_id: int) -> dict | None:
    """Активирует промокод. Возвращает dict с полями кода или None если недействителен."""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM promo_codes WHERE code=?", (code.upper(),)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        promo = dict(row)
        if promo.get("expires_at") and promo["expires_at"] < now:
            return None
        if promo["used_count"] >= promo["max_uses"]:
            return None
        async with db.execute(
            "SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (promo["code"], user_id)
        ) as cur:
            if await cur.fetchone():
                return None
        await db.execute(
            "INSERT INTO promo_uses (code, user_id, used_at) VALUES (?,?,?)",
            (promo["code"], user_id, now),
        )
        await db.execute(
            "UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (promo["code"],)
        )
        await db.commit()
    return promo


async def create_promo(code: str, months: int, max_uses: int, expires_at: int | None = None, promo_type: str = "premium") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO promo_codes (code, months, max_uses, used_count, created_at, expires_at, promo_type) VALUES (?,?,?,0,?,?,?)",
            (code.upper(), months, max_uses, int(time.time()), expires_at, promo_type),
        )
        await db.commit()


async def get_promos() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM promo_codes ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_promo(code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM promo_codes WHERE code=?", (code.upper(),))
        await db.execute("DELETE FROM promo_uses WHERE code=?", (code.upper(),))
        await db.commit()


# ── Дерево приглашений ────────────────────────────────────────────────────────

async def get_invite_tree() -> list[dict]:
    """Все пользователи с информацией о том кто их пригласил."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.user_id, u.display_name, u.created_at,
                   u.premium_until, u.trial_until,
                   i.owner_id AS invited_by
            FROM users u
            LEFT JOIN invite_uses iu ON iu.used_by = u.user_id
            LEFT JOIN invites i ON i.code = iu.code
            ORDER BY u.created_at
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Публичные группы Premium Plus ────────────────────────────────────────────

PUBLIC_GROUP_LIMIT = 3


async def get_public_groups(owner_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM public_group_monitors WHERE owner_id=? ORDER BY added_at",
            (owner_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_public_group(owner_id: int, chat_id: int, chat_username: str | None, chat_title: str) -> bool:
    """Добавляет чат. Возвращает False если лимит исчерпан или уже есть."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM public_group_monitors WHERE owner_id=?", (owner_id,)
        ) as cur:
            count = (await cur.fetchone())[0]
        if count >= PUBLIC_GROUP_LIMIT:
            return False
        try:
            await db.execute(
                "INSERT INTO public_group_monitors (owner_id, chat_id, chat_username, chat_title, added_at) VALUES (?,?,?,?,?)",
                (owner_id, chat_id, chat_username or "", chat_title, int(time.time())),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_public_group(owner_id: int, chat_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM public_group_monitors WHERE owner_id=? AND chat_id=?",
            (owner_id, chat_id),
        )
        await db.commit()


async def is_monitored_public_group(owner_id: int, chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM public_group_monitors WHERE owner_id=? AND chat_id=?",
            (owner_id, chat_id),
        ) as cur:
            return await cur.fetchone() is not None


# ── Заглушённые чаты (legacy, не используется в UI) ──────────────────────────

async def is_muted(owner_id: int, chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM muted_chats WHERE owner_id=? AND chat_id=?", (owner_id, chat_id)
        ) as cur:
            return await cur.fetchone() is not None


async def toggle_mute(owner_id: int, chat_id: int) -> bool:
    """Returns True если теперь заглушён, False если разглушён."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM muted_chats WHERE owner_id=? AND chat_id=?", (owner_id, chat_id)
        ) as cur:
            exists = await cur.fetchone()
        if exists:
            await db.execute("DELETE FROM muted_chats WHERE owner_id=? AND chat_id=?", (owner_id, chat_id))
            await db.commit()
            return False
        else:
            await db.execute("INSERT INTO muted_chats (owner_id, chat_id) VALUES (?,?)", (owner_id, chat_id))
            await db.commit()
            return True
