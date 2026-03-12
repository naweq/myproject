# ==========================================
# ФАЙЛ: modules/database.py
# ОПИСАНИЕ: Единая SQLite база данных проекта
#
# ВАЖНО: при старте бота вызови await Database().init()
#        при остановке:        await Database().close()
# ==========================================

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path("data/bot.db")

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id            INTEGER PRIMARY KEY,
    username           TEXT,
    first_name         TEXT,
    subscription_until TEXT,
    subscription_type  TEXT,
    test_used          INTEGER NOT NULL DEFAULT 0,
    is_blocked         INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT    NOT NULL,
    last_active        TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS stats (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    total_subscriptions INTEGER NOT NULL DEFAULT 0,
    total_stars_earned  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS user_api_keys (
    user_id    INTEGER NOT NULL,
    slot       INTEGER NOT NULL DEFAULT 1,
    api_id     TEXT    NOT NULL,
    api_hash   TEXT    NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, slot)
);
CREATE TABLE IF NOT EXISTS session_proxies (
    user_id      INTEGER NOT NULL,
    session_name TEXT    NOT NULL,
    proxy_uri    TEXT,
    PRIMARY KEY (user_id, session_name)
);
CREATE TABLE IF NOT EXISTS promo_codes (
    code       TEXT    PRIMARY KEY,
    reward     TEXT    NOT NULL,
    max_uses   INTEGER NOT NULL DEFAULT 1,
    remaining  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS promo_used (
    code    TEXT    NOT NULL REFERENCES promo_codes(code) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (code, user_id)
);
CREATE TABLE IF NOT EXISTS text_templates (
    user_id INTEGER NOT NULL,
    name    TEXT    NOT NULL,
    text    TEXT    NOT NULL,
    PRIMARY KEY (user_id, name)
);
CREATE TABLE IF NOT EXISTS selected_accounts (
    user_id      INTEGER NOT NULL,
    session_name TEXT    NOT NULL,
    PRIMARY KEY (user_id, session_name)
);
CREATE TABLE IF NOT EXISTS user_delays (
    user_id       INTEGER PRIMARY KEY,
    message_delay INTEGER NOT NULL DEFAULT 10,
    cycle_delay   INTEGER NOT NULL DEFAULT 300
);
CREATE TABLE IF NOT EXISTS kb_layout (
    user_id             INTEGER PRIMARY KEY,
    per_page            INTEGER NOT NULL DEFAULT 10,
    cols                INTEGER NOT NULL DEFAULT 2,
    name_length         INTEGER NOT NULL DEFAULT 10,
    show_status         INTEGER NOT NULL DEFAULT 1,
    auto_delete_invalid INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS account_meta_cache (
    user_id      INTEGER NOT NULL,
    session_name TEXT    NOT NULL,
    full_name    TEXT    NOT NULL DEFAULT '',
    phone        TEXT    NOT NULL DEFAULT '',
    username     TEXT    NOT NULL DEFAULT '',
    tg_user_id   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, session_name)
);
CREATE TABLE IF NOT EXISTS spamblock_config (
    user_id                INTEGER PRIMARY KEY,
    enabled                INTEGER NOT NULL DEFAULT 0,
    premium_retry_wait     INTEGER NOT NULL DEFAULT 180,
    premium_retry_wait_max INTEGER NOT NULL DEFAULT 240,
    auto_translate         INTEGER NOT NULL DEFAULT 1,
    active_template_id     TEXT    NOT NULL DEFAULT 'default_ru'
);
CREATE TABLE IF NOT EXISTS spamblock_templates (
    user_id INTEGER NOT NULL,
    tpl_id  TEXT    NOT NULL,
    name    TEXT    NOT NULL,
    text    TEXT    NOT NULL,
    PRIMARY KEY (user_id, tpl_id)
);
"""


def _init_db_sync() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(_DDL)
    conn.execute("INSERT OR IGNORE INTO stats (id) VALUES (1)")
    conn.commit()
    conn.close()
    logger.info(f"✅ SQLite БД инициализирована: {DB_PATH}")


class Database:
    """
    Единая асинхронная SQLite БД (Singleton).
    Одно постоянное соединение на весь lifecycle бота.

    В main.py:
        db = Database()
        # при старте:
        await db.init()
        # при остановке:
        await db.close()
    """

    _instance: Optional["Database"] = None

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
            cls._instance._db = None
        return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        _init_db_sync()
        self._ready = True

    async def init(self) -> None:
        """Открыть постоянное соединение. Вызвать один раз при старте бота."""
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(str(DB_PATH))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.commit()
        logger.info("✅ БД: постоянное соединение установлено")

    async def close(self) -> None:
        """Закрыть соединение при остановке бота."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not initialized! Call: await Database().init()")
        return self._db

    # ════════════════════════════════════════════════════════════════════════
    # USERS
    # ════════════════════════════════════════════════════════════════════════

    async def add_user(self, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            """
            INSERT INTO users (user_id, username, first_name, created_at, last_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                first_name  = excluded.first_name,
                last_active = excluded.last_active
            """,
            (user_id, username, first_name, now, now),
        )
        await self.db.commit()

    async def get_user(self, user_id: int) -> Optional[Dict]:
        async with self.db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def has_active_subscription(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user or not user.get("subscription_until"):
            return False
        try:
            return datetime.now() < datetime.fromisoformat(user["subscription_until"])
        except Exception:
            return False

    async def is_test_used(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user.get("test_used")) if user else False

    async def activate_subscription(self, user_id: int, sub_type: str, stars: int = 0) -> bool:
        from config import SUBSCRIPTION_PRICES, bot

        price_info = SUBSCRIPTION_PRICES.get(sub_type)
        if not price_info:
            logger.error(f"Неизвестный тип подписки: {sub_type}")
            return False

        days: int = price_info["days"]
        now = datetime.now()

        await self.db.execute(
            "INSERT OR IGNORE INTO users (user_id, created_at, last_active) VALUES (?, ?, ?)",
            (user_id, now.isoformat(), now.isoformat()),
        )

        async with self.db.execute("SELECT subscription_until FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()

        start = now
        if row and row["subscription_until"]:
            try:
                existing = datetime.fromisoformat(row["subscription_until"])
                if existing > now:
                    start = existing
            except Exception:
                pass

        until = (start + timedelta(days=days)).isoformat()

        await self.db.execute(
            """
            UPDATE users SET
                subscription_until = ?,
                subscription_type  = ?,
                test_used = CASE WHEN ? = 'test' THEN 1 ELSE test_used END,
                last_active = ?
            WHERE user_id = ?
            """,
            (until, sub_type, sub_type, now.isoformat(), user_id),
        )
        if sub_type != "test":
            await self.db.execute(
                "UPDATE stats SET total_subscriptions = total_subscriptions + 1, total_stars_earned = total_stars_earned + ? WHERE id = 1",
                (stars,),
            )
        await self.db.commit()

        logger.info(f"✅ Подписка {sub_type} → user {user_id} до {until}")
        try:
            await bot.send_message(user_id, f"<b>💎 Вам выдана подписка: {sub_type}</b>")
        except Exception:
            pass
        return True

    async def remove_subscription(self, user_id: int) -> None:
        await self.db.execute(
            "UPDATE users SET subscription_until = NULL, subscription_type = NULL WHERE user_id = ?",
            (user_id,),
        )
        await self.db.commit()

    async def set_blocked(self, user_id: int, is_blocked: bool) -> None:
        await self.db.execute(
            "UPDATE users SET is_blocked = ? WHERE user_id = ?",
            (1 if is_blocked else 0, user_id),
        )
        await self.db.commit()

    async def is_blocked(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user.get("is_blocked")) if user else False

    async def get_all_users(self) -> List[int]:
        async with self.db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def get_users_list(self, page: int = 0, per_page: int = 20) -> Tuple[List[Dict], int]:
        async with self.db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with self.db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows], total

    async def get_stats(self) -> Dict:
        async with self.db.execute("SELECT * FROM users") as cur:
            users = await cur.fetchall()
        async with self.db.execute("SELECT * FROM stats WHERE id = 1") as cur:
            stats_row = await cur.fetchone()

        now = datetime.now()
        active_subs = test_subs = 0
        for u in users:
            until = u["subscription_until"]
            if until:
                try:
                    if now < datetime.fromisoformat(until):
                        if u["subscription_type"] == "test":
                            test_subs += 1
                        else:
                            active_subs += 1
                except Exception:
                    pass

        return {
            "total_users": len(users),
            "active_subscriptions": active_subs,
            "test_subscriptions": test_subs,
            "total_subscriptions_sold": stats_row["total_subscriptions"] if stats_row else 0,
            "total_stars_earned": stats_row["total_stars_earned"] if stats_row else 0,
        }

    # ════════════════════════════════════════════════════════════════════════
    # ADMINS
    # ════════════════════════════════════════════════════════════════════════

    async def get_admins(self) -> List[int]:
        async with self.db.execute("SELECT user_id FROM admins") as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def add_admin(self, user_id: int) -> bool:
        try:
            await self.db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
            await self.db.commit()
            return True
        except Exception as e:
            logger.error(f"add_admin error: {e}")
            return False

    async def remove_admin(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await self.db.commit()

    async def is_admin(self, user_id: int) -> bool:
        async with self.db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None

    # ════════════════════════════════════════════════════════════════════════
    # API KEYS
    # ════════════════════════════════════════════════════════════════════════

    async def set_user_api(self, user_id: int, slot: int, api_id: str, api_hash: str) -> None:
        await self.db.execute(
            """
            INSERT INTO user_api_keys (user_id, slot, api_id, api_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, slot) DO UPDATE SET
                api_id   = excluded.api_id,
                api_hash = excluded.api_hash
            """,
            (user_id, slot, str(api_id), api_hash),
        )
        await self.db.commit()

    async def get_user_api(self, user_id: int, slot: int) -> Optional[Dict]:
        async with self.db.execute(
            "SELECT api_id, api_hash FROM user_api_keys WHERE user_id = ? AND slot = ?",
            (user_id, slot),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_user_api(self, user_id: int, slot: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM user_api_keys WHERE user_id = ? AND slot = ?", (user_id, slot)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def set_current_api(self, user_id: int, slot: int) -> None:
        await self.db.execute("UPDATE user_api_keys SET is_current = 0 WHERE user_id = ?", (user_id,))
        await self.db.execute(
            "UPDATE user_api_keys SET is_current = 1 WHERE user_id = ? AND slot = ?",
            (user_id, slot),
        )
        await self.db.commit()

    async def get_current_api(self, user_id: int) -> Optional[Dict]:
        async with self.db.execute(
            "SELECT api_id, api_hash, slot FROM user_api_keys WHERE user_id = ? AND is_current = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    # ════════════════════════════════════════════════════════════════════════
    # SESSION PROXIES
    # ════════════════════════════════════════════════════════════════════════

    async def set_session_proxy(self, user_id: int, session_name: str, proxy_uri: Optional[str]) -> None:
        await self.db.execute(
            """
            INSERT INTO session_proxies (user_id, session_name, proxy_uri)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, session_name) DO UPDATE SET proxy_uri = excluded.proxy_uri
            """,
            (user_id, session_name, proxy_uri),
        )
        await self.db.commit()

    async def get_session_proxy(self, user_id: int, session_name: str) -> Optional[str]:
        async with self.db.execute(
            "SELECT proxy_uri FROM session_proxies WHERE user_id = ? AND session_name = ?",
            (user_id, session_name),
        ) as cur:
            row = await cur.fetchone()
        return row["proxy_uri"] if row else None

    async def delete_session_proxy(self, user_id: int, session_name: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM session_proxies WHERE user_id = ? AND session_name = ?",
            (user_id, session_name),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ════════════════════════════════════════════════════════════════════════
    # PROMO CODES
    # ════════════════════════════════════════════════════════════════════════

    async def add_promo(self, code: str, reward: str, max_uses: int = 1) -> bool:
        code = code.strip().upper()
        try:
            await self.db.execute(
                "INSERT INTO promo_codes (code, reward, max_uses, remaining, created_at) VALUES (?, ?, ?, ?, ?)",
                (code, reward, max_uses, max_uses, datetime.now().strftime("%Y-%m-%d")),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def use_promo(self, code: str, user_id: int) -> Tuple[bool, str, Optional[str]]:
        code = code.strip().upper()
        async with self.db.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)) as cur:
            promo = await cur.fetchone()
        if not promo:
            return False, "Промокод не найден!", None

        async with self.db.execute(
            "SELECT 1 FROM promo_used WHERE code = ? AND user_id = ?", (code, user_id)
        ) as cur:
            if await cur.fetchone():
                return False, "Вы уже использовали этот промокод!", None

        if promo["remaining"] <= 0:
            return False, "Промокод уже исчерпан!", None

        reward = promo["reward"]
        await self.db.execute("UPDATE promo_codes SET remaining = remaining - 1 WHERE code = ?", (code,))
        await self.db.execute("INSERT INTO promo_used (code, user_id) VALUES (?, ?)", (code, user_id))
        await self.db.commit()
        return True, "✅ Промокод успешно активирован", reward

    # ════════════════════════════════════════════════════════════════════════
    # TEXT TEMPLATES
    # ════════════════════════════════════════════════════════════════════════

    async def get_template_names(self, user_id: int) -> List[str]:
        async with self.db.execute(
            "SELECT name FROM text_templates WHERE user_id = ? ORDER BY name", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def get_template(self, user_id: int, name: str) -> Optional[str]:
        async with self.db.execute(
            "SELECT text FROM text_templates WHERE user_id = ? AND name = ?", (user_id, name)
        ) as cur:
            row = await cur.fetchone()
        return row["text"] if row else None

    async def write_template(self, user_id: int, name: str, text: str) -> None:
        await self.db.execute(
            """
            INSERT INTO text_templates (user_id, name, text) VALUES (?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET text = excluded.text
            """,
            (user_id, name, text),
        )
        await self.db.commit()

    async def delete_template(self, user_id: int, name: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM text_templates WHERE user_id = ? AND name = ?", (user_id, name)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def rename_template(self, user_id: int, old_name: str, new_name: str) -> bool:
        async with self.db.execute(
            "SELECT text FROM text_templates WHERE user_id = ? AND name = ?", (user_id, old_name)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        try:
            await self.db.execute(
                "INSERT INTO text_templates (user_id, name, text) VALUES (?, ?, ?)",
                (user_id, new_name, row["text"]),
            )
            await self.db.execute(
                "DELETE FROM text_templates WHERE user_id = ? AND name = ?", (user_id, old_name)
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    # ════════════════════════════════════════════════════════════════════════
    # SELECTED ACCOUNTS
    # ════════════════════════════════════════════════════════════════════════

    async def get_selected_accounts(self, user_id: int) -> List[str]:
        async with self.db.execute(
            "SELECT session_name FROM selected_accounts WHERE user_id = ?", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def set_selected_accounts(self, user_id: int, accounts: List[str]) -> None:
        await self.db.execute("DELETE FROM selected_accounts WHERE user_id = ?", (user_id,))
        await self.db.executemany(
            "INSERT INTO selected_accounts (user_id, session_name) VALUES (?, ?)",
            [(user_id, a) for a in accounts],
        )
        await self.db.commit()

    async def toggle_account(self, user_id: int, session_name: str) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM selected_accounts WHERE user_id = ? AND session_name = ?",
            (user_id, session_name),
        ) as cur:
            exists = await cur.fetchone()
        if exists:
            await self.db.execute(
                "DELETE FROM selected_accounts WHERE user_id = ? AND session_name = ?",
                (user_id, session_name),
            )
            selected = False
        else:
            await self.db.execute(
                "INSERT INTO selected_accounts (user_id, session_name) VALUES (?, ?)",
                (user_id, session_name),
            )
            selected = True
        await self.db.commit()
        return selected

    async def clear_missing_accounts(self, user_id: int, existing_sessions: List[str]) -> List[str]:
        selected = await self.get_selected_accounts(user_id)
        cleaned = [s for s in selected if s in existing_sessions]
        if len(cleaned) != len(selected):
            await self.set_selected_accounts(user_id, cleaned)
        return cleaned

    # ════════════════════════════════════════════════════════════════════════
    # USER DELAYS
    # ════════════════════════════════════════════════════════════════════════

    async def get_delays(self, user_id: int) -> Dict[str, int]:
        from config import DEFAULT_MESSAGE_DELAY, DEFAULT_CYCLE_DELAY
        async with self.db.execute(
            "SELECT message_delay, cycle_delay FROM user_delays WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return {
            "message": row["message_delay"] if row else DEFAULT_MESSAGE_DELAY,
            "cycle":   row["cycle_delay"]   if row else DEFAULT_CYCLE_DELAY,
        }

    async def set_delays(self, user_id: int, message_delay: Optional[int] = None, cycle_delay: Optional[int] = None) -> None:
        await self.db.execute("INSERT OR IGNORE INTO user_delays (user_id) VALUES (?)", (user_id,))
        if message_delay is not None:
            await self.db.execute(
                "UPDATE user_delays SET message_delay = ? WHERE user_id = ?", (message_delay, user_id)
            )
        if cycle_delay is not None:
            await self.db.execute(
                "UPDATE user_delays SET cycle_delay = ? WHERE user_id = ?", (cycle_delay, user_id)
            )
        await self.db.commit()

    # ════════════════════════════════════════════════════════════════════════
    # KB LAYOUT
    # ════════════════════════════════════════════════════════════════════════

    _KB_DEFAULTS: Dict[str, Any] = {
        "per_page": 10, "cols": 2, "name_length": 10,
        "show_status": True, "auto_delete_invalid": False,
    }

    async def get_kb_layout(self, user_id: int) -> Dict[str, Any]:
        async with self.db.execute("SELECT * FROM kb_layout WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return dict(self._KB_DEFAULTS)
        return {
            "per_page":            row["per_page"],
            "cols":                row["cols"],
            "name_length":         row["name_length"],
            "show_status":         bool(row["show_status"]),
            "auto_delete_invalid": bool(row["auto_delete_invalid"]),
        }

    async def set_kb_layout(self, user_id: int, **kwargs: Any) -> None:
        valid = set(self._KB_DEFAULTS.keys())
        await self.db.execute("INSERT OR IGNORE INTO kb_layout (user_id) VALUES (?)", (user_id,))
        for field, value in kwargs.items():
            if field not in valid:
                continue
            db_val = (1 if value else 0) if isinstance(value, bool) else value
            await self.db.execute(f"UPDATE kb_layout SET {field} = ? WHERE user_id = ?", (db_val, user_id))
        await self.db.commit()

    async def toggle_auto_delete(self, user_id: int) -> bool:
        layout = await self.get_kb_layout(user_id)
        new_val = not layout["auto_delete_invalid"]
        await self.set_kb_layout(user_id, auto_delete_invalid=new_val)
        return new_val

    async def is_auto_delete_enabled(self, user_id: int) -> bool:
        return (await self.get_kb_layout(user_id))["auto_delete_invalid"]

    # ════════════════════════════════════════════════════════════════════════
    # ACCOUNT META CACHE
    # ════════════════════════════════════════════════════════════════════════

    async def get_account_meta(self, user_id: int, session_name: str) -> Optional[Dict]:
        async with self.db.execute(
            "SELECT * FROM account_meta_cache WHERE user_id = ? AND session_name = ?",
            (user_id, session_name),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "full_name": row["full_name"],
            "phone":     row["phone"],
            "username":  row["username"],
            "user_id":   row["tg_user_id"],
        }

    async def set_account_meta(self, user_id: int, session_name: str, meta: Dict) -> None:
        await self.db.execute(
            """
            INSERT INTO account_meta_cache (user_id, session_name, full_name, phone, username, tg_user_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, session_name) DO UPDATE SET
                full_name  = excluded.full_name,
                phone      = excluded.phone,
                username   = excluded.username,
                tg_user_id = excluded.tg_user_id
            """,
            (user_id, session_name,
             meta.get("full_name", ""), meta.get("phone", ""),
             meta.get("username", ""), meta.get("user_id", 0)),
        )
        await self.db.commit()

    async def ensure_account_meta(self, user_id: int, session_name: str) -> Dict:
        cached = await self.get_account_meta(user_id, session_name)
        if cached:
            return cached
        try:
            from modules.session_manager import SessionManager
            success, info = await SessionManager().get_session_info(session_name, user_id)
            if not success or not isinstance(info, dict):
                return {"full_name": "", "phone": "", "username": "", "user_id": 0}
            meta = {
                "full_name": info.get("full_name", ""),
                "phone":     info.get("phone", ""),
                "username":  info.get("username", ""),
                "user_id":   info.get("user_id") or 0,
            }
            await self.set_account_meta(user_id, session_name, meta)
            return meta
        except Exception as e:
            logger.warning(f"ensure_account_meta {session_name}: {e}")
            return {"full_name": "", "phone": "", "username": "", "user_id": 0}

    async def prefetch_accounts_meta(self, user_id: int, session_names: List[str]) -> None:
        async with self.db.execute(
            "SELECT session_name FROM account_meta_cache WHERE user_id = ?", (user_id,)
        ) as cur:
            cached = {r[0] for r in await cur.fetchall()}
        for name in session_names:
            if name not in cached:
                await self.ensure_account_meta(user_id, name)

    # ════════════════════════════════════════════════════════════════════════
    # SPAMBLOCK CONFIG
    # ════════════════════════════════════════════════════════════════════════

    _SB_DEFAULTS: Dict[str, Any] = {
        "enabled": False,
        "premium_retry_wait": 180,
        "premium_retry_wait_max": 240,
        "auto_translate": True,
        "active_template_id": "default_ru",
    }

    async def get_spamblock_config(self, user_id: int) -> Dict[str, Any]:
        async with self.db.execute("SELECT * FROM spamblock_config WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return dict(self._SB_DEFAULTS)
        return {
            "enabled":                bool(row["enabled"]),
            "premium_retry_wait":     row["premium_retry_wait"],
            "premium_retry_wait_max": row["premium_retry_wait_max"],
            "auto_translate":         bool(row["auto_translate"]),
            "active_template_id":     row["active_template_id"],
        }

    async def set_spamblock_config(self, user_id: int, **kwargs: Any) -> None:
        valid = set(self._SB_DEFAULTS.keys())
        await self.db.execute("INSERT OR IGNORE INTO spamblock_config (user_id) VALUES (?)", (user_id,))
        for field, value in kwargs.items():
            if field not in valid:
                continue
            db_val = (1 if value else 0) if isinstance(value, bool) else value
            await self.db.execute(
                f"UPDATE spamblock_config SET {field} = ? WHERE user_id = ?", (db_val, user_id)
            )
        await self.db.commit()

    async def get_spamblock_templates(self, user_id: int) -> List[Dict]:
        async with self.db.execute(
            "SELECT tpl_id, name, text FROM spamblock_templates WHERE user_id = ?", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"id": r[0], "name": r[1], "text": r[2], "builtin": False} for r in rows]

    async def add_spamblock_template(self, user_id: int, tpl_id: str, name: str, text: str) -> None:
        await self.db.execute(
            """
            INSERT INTO spamblock_templates (user_id, tpl_id, name, text) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, tpl_id) DO UPDATE SET name = excluded.name, text = excluded.text
            """,
            (user_id, tpl_id, name, text),
        )
        await self.db.commit()

    async def delete_spamblock_template(self, user_id: int, tpl_id: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM spamblock_templates WHERE user_id = ? AND tpl_id = ?", (user_id, tpl_id)
        )
        await self.db.commit()
        return cur.rowcount > 0