"""
migrate_all.py — Миграция всех JSON хранилищ в единую SQLite БД (data/bot.db)

Запустить ОДИН РАЗ перед первым стартом бота:
    python migrate_all.py

Что мигрируется:
    data/users_data.json        → users + stats
    data/admins.json            → admins
    data/api_settings.json      → user_api_keys
    data/current_api.json       → user_api_keys (is_current)
    data/session_settings.json  → session_proxies
    data/promo.json             → promo_codes + promo_used
    data/selected_accounts.json → selected_accounts
    data/user_delays.json       → user_delays
    data/kb_layout_settings.json→ kb_layout
    text_temp.json              → text_templates
    users/*/accounts_meta.json  → account_meta_cache
    users/*/spamblock_config.json→ spamblock_config + spamblock_templates
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/bot.db")

# ── DDL (копия из database.py) ────────────────────────────────────────────────
DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
    subscription_until TEXT, subscription_type TEXT,
    test_used INTEGER NOT NULL DEFAULT 0, is_blocked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, last_active TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_subscriptions INTEGER NOT NULL DEFAULT 0,
    total_stars_earned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS user_api_keys (
    user_id INTEGER NOT NULL, slot INTEGER NOT NULL DEFAULT 1,
    api_id TEXT NOT NULL, api_hash TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, slot)
);
CREATE TABLE IF NOT EXISTS session_proxies (
    user_id INTEGER NOT NULL, session_name TEXT NOT NULL, proxy_uri TEXT,
    PRIMARY KEY (user_id, session_name)
);
CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY, reward TEXT NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1, remaining INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promo_used (
    code TEXT NOT NULL REFERENCES promo_codes(code) ON DELETE CASCADE,
    user_id INTEGER NOT NULL, PRIMARY KEY (code, user_id)
);
CREATE TABLE IF NOT EXISTS text_templates (
    user_id INTEGER NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL,
    PRIMARY KEY (user_id, name)
);
CREATE TABLE IF NOT EXISTS selected_accounts (
    user_id INTEGER NOT NULL, session_name TEXT NOT NULL,
    PRIMARY KEY (user_id, session_name)
);
CREATE TABLE IF NOT EXISTS user_delays (
    user_id INTEGER PRIMARY KEY,
    message_delay INTEGER NOT NULL DEFAULT 10,
    cycle_delay INTEGER NOT NULL DEFAULT 300
);
CREATE TABLE IF NOT EXISTS kb_layout (
    user_id INTEGER PRIMARY KEY, per_page INTEGER NOT NULL DEFAULT 10,
    cols INTEGER NOT NULL DEFAULT 2, name_length INTEGER NOT NULL DEFAULT 10,
    show_status INTEGER NOT NULL DEFAULT 1, auto_delete_invalid INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS account_meta_cache (
    user_id INTEGER NOT NULL, session_name TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '', tg_user_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, session_name)
);
CREATE TABLE IF NOT EXISTS spamblock_config (
    user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
    premium_retry_wait INTEGER NOT NULL DEFAULT 180,
    premium_retry_wait_max INTEGER NOT NULL DEFAULT 240,
    auto_translate INTEGER NOT NULL DEFAULT 1,
    active_template_id TEXT NOT NULL DEFAULT 'default_ru'
);
CREATE TABLE IF NOT EXISTS spamblock_templates (
    user_id INTEGER NOT NULL, tpl_id TEXT NOT NULL,
    name TEXT NOT NULL, text TEXT NOT NULL,
    PRIMARY KEY (user_id, tpl_id)
);
"""

# ─────────────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  Не удалось прочитать {path}: {e}")
        return None


def ok(msg): print(f"  ✅ {msg}")
def skip(msg): print(f"  ⏭️  {msg}")
def warn(msg): print(f"  ⚠️  {msg}")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.executescript(DDL)
    db.execute("INSERT OR IGNORE INTO stats (id) VALUES (1)")
    db.commit()
    print(f"\n🗄️  База данных: {DB_PATH}\n")

    now = datetime.now().isoformat()

    # ── 1. users_data.json ───────────────────────────────────────────────────
    print("📦 Миграция users_data.json...")
    raw = load_json(Path("data/users_data.json")) or {}
    if not raw:
        raw = load_json(Path("data/users.db")) or {}
    # Структура может быть {"users": {...}, "stats": {...}} или просто {uid: {...}}
    if "users" in raw and isinstance(raw["users"], dict):
        users_data = raw["users"]
        # Перенос статистики если есть
        raw_stats = raw.get("stats", {})
        if raw_stats:
            db.execute(
                """UPDATE stats SET
                    total_subscriptions = ?,
                    total_stars_earned  = ?
                WHERE id = 1""",
                (
                    int(raw_stats.get("total_subscriptions", 0)),
                    int(raw_stats.get("total_stars_earned", 0)),
                ),
            )
            db.commit()
    else:
        users_data = raw
    count = 0
    for uid_str, info in users_data.items():
        try:
            uid = int(uid_str)
            db.execute(
                """
                INSERT INTO users
                    (user_id, username, first_name, subscription_until, subscription_type,
                     test_used, is_blocked, created_at, last_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (
                    uid,
                    info.get("username"),
                    info.get("first_name"),
                    info.get("subscription_until"),
                    info.get("subscription_type"),
                    1 if info.get("test_used") else 0,
                    1 if info.get("is_blocked") else 0,
                    info.get("created_at") or now,
                    info.get("last_active") or now,
                ),
            )
            count += 1
        except Exception as e:
            warn(f"user {uid_str}: {e}")
    db.commit()
    ok(f"Пользователи: {count} записей")

    # ── 2. admins.json ───────────────────────────────────────────────────────
    print("📦 Миграция admins.json...")
    admins_raw = load_json(Path("data/admins.json"))
    if admins_raw is None:
        skip("admins.json не найден")
    else:
        # Может быть [id1, id2] или {"admins": [id1, id2]} или {id: ...}
        if isinstance(admins_raw, list):
            admins = admins_raw
        elif isinstance(admins_raw, dict) and "admins" in admins_raw:
            admins = admins_raw["admins"]
        else:
            admins = list(admins_raw.keys())
        for a in admins:
            try:
                db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(a),))
            except Exception as e:
                warn(f"admin {a}: {e}")
        db.commit()
        ok(f"Администраторы: {len(admins)} записей")

    # ── 3. api_settings.json + current_api.json ──────────────────────────────
    print("📦 Миграция API ключей...")
    api_settings = load_json(Path("data/api_settings.json")) or {}
    current_api  = load_json(Path("data/current_api.json"))  or {}
    count = 0
    for uid_str, slots in api_settings.items():
        uid = int(uid_str)
        # slots может быть dict вида:
        #   {"api_id": ..., "api_hash": ...}         → один слот
        #   {"api_1": {...}, "api_2": {...}}          → несколько слотов
        #   {1: {...}, 2: {...}}                      → числовые ключи
        if isinstance(slots, dict) and "api_id" in slots:
            slots = {1: slots}
        elif isinstance(slots, dict):
            parsed = {}
            for k, v in slots.items():
                # "api_1" → 1, "1" → 1, 1 → 1
                key_str = str(k).replace("api_", "").strip()
                try:
                    parsed[int(key_str)] = v
                except ValueError:
                    warn(f"Неизвестный формат слота '{k}' у user {uid_str}, пропускаю")
            slots = parsed
        else:
            continue
        cur_val = current_api.get(uid_str, 1)
        if isinstance(cur_val, dict):
            cur_val = cur_val.get("slot", 1)
        # "api_1" → 1, "1" → 1, 1 → 1
        try:
            current_slot = int(str(cur_val).replace("api_", "").strip())
        except (ValueError, TypeError):
            current_slot = 1
        for slot, keys in slots.items():
            if not isinstance(keys, dict):
                continue
            api_id   = str(keys.get("api_id", ""))
            api_hash = str(keys.get("api_hash", ""))
            if not api_id or not api_hash:
                continue
            is_cur = 1 if slot == current_slot else 0
            db.execute(
                """
                INSERT INTO user_api_keys (user_id, slot, api_id, api_hash, is_current)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, slot) DO NOTHING
                """,
                (uid, slot, api_id, api_hash, is_cur),
            )
            count += 1
    db.commit()
    ok(f"API ключи: {count} записей")

    # ── 4. session_settings.json ─────────────────────────────────────────────
    print("📦 Миграция session_settings.json...")
    sess = load_json(Path("data/session_settings.json")) or {}
    count = 0
    for uid_str, sessions in sess.items():
        uid = int(uid_str)
        if not isinstance(sessions, dict):
            continue
        for sname, cfg in sessions.items():
            if not isinstance(cfg, dict):
                continue
            proxy = cfg.get("proxy")
            db.execute(
                """
                INSERT INTO session_proxies (user_id, session_name, proxy_uri)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, session_name) DO NOTHING
                """,
                (uid, sname, proxy),
            )
            count += 1
    db.commit()
    ok(f"Прокси сессий: {count} записей")

    # ── 5. promo.json ────────────────────────────────────────────────────────
    print("📦 Миграция promo.json...")
    promo_data = load_json(Path("data/promo.json")) or {}
    count_codes = count_used = 0
    for code, info in promo_data.items():
        if not isinstance(info, dict):
            continue
        reward    = info.get("reward", "")
        max_uses  = int(info.get("max_uses", 1))
        used_by   = info.get("used_by", [])
        remaining = max(0, max_uses - len(used_by))
        try:
            db.execute(
                """
                INSERT INTO promo_codes (code, reward, max_uses, remaining, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(code) DO NOTHING
                """,
                (code.upper(), reward, max_uses, remaining, now[:10]),
            )
            count_codes += 1
        except Exception as e:
            warn(f"promo {code}: {e}")
        for uid in used_by:
            try:
                db.execute(
                    "INSERT OR IGNORE INTO promo_used (code, user_id) VALUES (?, ?)",
                    (code.upper(), int(uid)),
                )
                count_used += 1
            except Exception:
                pass
    db.commit()
    ok(f"Промокоды: {count_codes} кодов, {count_used} использований")

    # ── 6. text_temp.json ────────────────────────────────────────────────────
    print("📦 Миграция text_temp.json...")
    # ищем в нескольких местах
    temp_path = None
    for p in [Path("text_temp.json"), Path("data/text_temp.json"), Path("../text_temp.json")]:
        if p.exists():
            temp_path = p
            break
    temp_data = load_json(temp_path) if temp_path else None
    if temp_data is None:
        skip("text_temp.json не найден")
    else:
        count = 0
        for uid_str, templates in temp_data.items():
            uid = int(uid_str)
            if not isinstance(templates, dict):
                continue
            for name, text in templates.items():
                db.execute(
                    """
                    INSERT INTO text_templates (user_id, name, text) VALUES (?, ?, ?)
                    ON CONFLICT(user_id, name) DO NOTHING
                    """,
                    (uid, name, text),
                )
                count += 1
        db.commit()
        ok(f"Шаблоны текстов: {count} записей")

    # ── 7. selected_accounts.json ────────────────────────────────────────────
    print("📦 Миграция selected_accounts.json...")
    sel_data = load_json(Path("data/selected_accounts.json")) or {}
    count = 0
    for uid_str, sessions in sel_data.items():
        uid = int(uid_str)
        sess_list = sessions if isinstance(sessions, list) else list(sessions)
        for sname in sess_list:
            db.execute(
                "INSERT OR IGNORE INTO selected_accounts (user_id, session_name) VALUES (?, ?)",
                (uid, sname),
            )
            count += 1
    db.commit()
    ok(f"Выбранные аккаунты: {count} записей")

    # ── 8. user_delays.json ──────────────────────────────────────────────────
    print("📦 Миграция user_delays.json...")
    delays_data = load_json(Path("data/user_delays.json")) or {}
    count = 0
    for uid_str, delays in delays_data.items():
        uid = int(uid_str)
        if not isinstance(delays, dict):
            continue
        msg_d = int(delays.get("message_delay", delays.get("message", 10)))
        cyc_d = int(delays.get("cycle_delay",   delays.get("cycle",   300)))
        db.execute(
            """
            INSERT INTO user_delays (user_id, message_delay, cycle_delay)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (uid, msg_d, cyc_d),
        )
        count += 1
    db.commit()
    ok(f"Задержки: {count} записей")

    # ── 9. kb_layout_settings.json ───────────────────────────────────────────
    print("📦 Миграция kb_layout_settings.json...")
    kb_data = load_json(Path("data/kb_layout_settings.json")) or {}
    count = 0
    for uid_str, layout in kb_data.items():
        uid = int(uid_str)
        if not isinstance(layout, dict):
            continue
        db.execute(
            """
            INSERT INTO kb_layout
                (user_id, per_page, cols, name_length, show_status, auto_delete_invalid)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (
                uid,
                int(layout.get("per_page", 10)),
                int(layout.get("cols", 2)),
                int(layout.get("name_length", 10)),
                1 if layout.get("show_status", True) else 0,
                1 if layout.get("auto_delete_invalid", False) else 0,
            ),
        )
        count += 1
    db.commit()
    ok(f"Настройки клавиатуры: {count} записей")

    # ── 10. users/*/accounts_meta.json ───────────────────────────────────────
    print("📦 Миграция account_meta из users/*/accounts_meta.json...")
    count = 0
    for meta_path in Path("users").glob("*/accounts_meta.json"):
        try:
            uid = int(meta_path.parent.name)
        except ValueError:
            continue
        meta_data = load_json(meta_path) or {}
        for sname, info in meta_data.items():
            if not isinstance(info, dict):
                continue
            db.execute(
                """
                INSERT INTO account_meta_cache
                    (user_id, session_name, full_name, phone, username, tg_user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, session_name) DO NOTHING
                """,
                (
                    uid, sname,
                    info.get("full_name", ""),
                    info.get("phone", ""),
                    info.get("username", ""),
                    int(info.get("user_id") or 0),
                ),
            )
            count += 1
    db.commit()
    ok(f"Кеш метаданных: {count} записей")

    # ── 11. users/*/spamblock_config.json ────────────────────────────────────
    print("📦 Миграция spamblock_config из users/*/spamblock_config.json...")
    count_cfg = count_tpl = 0
    for sb_path in Path("users").glob("*/spamblock_config.json"):
        try:
            uid = int(sb_path.parent.name)
        except ValueError:
            continue
        cfg = load_json(sb_path) or {}
        db.execute(
            """
            INSERT INTO spamblock_config
                (user_id, enabled, premium_retry_wait, premium_retry_wait_max,
                 auto_translate, active_template_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (
                uid,
                1 if cfg.get("enabled") else 0,
                int(cfg.get("premium_retry_wait", 180)),
                int(cfg.get("premium_retry_wait_max", 240)),
                1 if cfg.get("auto_translate", True) else 0,
                cfg.get("active_template_id", "default_ru"),
            ),
        )
        count_cfg += 1
        for tpl in cfg.get("custom_templates", []):
            if not isinstance(tpl, dict):
                continue
            db.execute(
                """
                INSERT INTO spamblock_templates (user_id, tpl_id, name, text)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, tpl_id) DO NOTHING
                """,
                (uid, tpl.get("id", ""), tpl.get("name", ""), tpl.get("text", "")),
            )
            count_tpl += 1
    db.commit()
    ok(f"Spamblock: {count_cfg} конфигов, {count_tpl} пользовательских шаблонов")

    # ── Финал ────────────────────────────────────────────────────────────────
    db.close()
    print(f"\n{'─'*50}")
    print(f"✅ Миграция завершена! Файл: {DB_PATH}")
    print(f"{'─'*50}")
    print("\n📌 Следующие шаги:")
    print("  1. Проверь данные: sqlite3 data/bot.db")
    print("  2. Замени modules/database.py новой версией")
    print("  3. Убедись что в config.py нет старых путей к JSON")
    print("  4. Запускай бота!\n")


if __name__ == "__main__":
    main()