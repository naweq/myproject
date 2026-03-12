#!/usr/bin/env python3
"""
migrate_db.py — Миграция users_data.json → SQLite (data/users.db)

Запускать ОДИН РАЗ перед переходом на новую БД:
    python migrate_db.py

Скрипт безопасен: не удаляет исходный JSON-файл.
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

OLD_JSON = Path("data/users_data.json")
NEW_DB   = Path("data/users.db")


def main() -> None:
    if not OLD_JSON.exists():
        print(f"[INFO] Файл {OLD_JSON} не найден. Нечего мигрировать.")
        return

    print(f"[INFO] Читаю {OLD_JSON}...")
    with open(OLD_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    users = data.get("users", {})
    stats = data.get("stats", {})

    print(f"[INFO] Найдено пользователей: {len(users)}")

    NEW_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(NEW_DB))
    conn.execute("PRAGMA journal_mode=WAL;")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id            INTEGER PRIMARY KEY,
            username           TEXT,
            first_name         TEXT,
            subscription_until TEXT,
            subscription_type  TEXT,
            test_used          INTEGER NOT NULL DEFAULT 0,
            is_blocked         INTEGER NOT NULL DEFAULT 0,
            created_at         TEXT NOT NULL,
            last_active        TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id                      INTEGER PRIMARY KEY CHECK (id = 1),
            total_subscriptions     INTEGER NOT NULL DEFAULT 0,
            total_stars_earned      INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO stats (id, total_subscriptions, total_stars_earned) VALUES (1, ?, ?)",
        (stats.get("total_subscriptions", 0), stats.get("total_stars_earned", 0)),
    )

    now = datetime.now().isoformat()
    migrated = 0
    skipped  = 0

    for uid_str, u in users.items():
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO users
                    (user_id, username, first_name, subscription_until,
                     subscription_type, test_used, is_blocked, created_at, last_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(uid_str),
                    u.get("username"),
                    u.get("first_name"),
                    u.get("subscription_until"),
                    u.get("subscription_type"),
                    1 if u.get("test_used") else 0,
                    1 if u.get("is_blocked") else 0,
                    u.get("created_at", now),
                    u.get("last_active", now),
                ),
            )
            migrated += 1
        except Exception as e:
            print(f"[WARN] Пропускаю user_id={uid_str}: {e}")
            skipped += 1

    conn.commit()
    conn.close()

    print(f"[OK] Мигрировано: {migrated}, пропущено: {skipped}")
    print(f"[OK] БД создана: {NEW_DB}")
    print(f"[INFO] Исходный файл {OLD_JSON} НЕ удалён (резервная копия).")


if __name__ == "__main__":
    main()
