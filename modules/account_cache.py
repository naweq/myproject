# ==========================================
# ФАЙЛ: account_cache.py  (НОВЫЙ ФАЙЛ)
# Положить в папку проекта рядом с остальными
# ==========================================
#
# Кешируем мету аккаунтов в JSON.
# Чтение из кеша — никаких подключений к сессии.
# Обновление происходит ТОЛЬКО когда сессия свободна
# (т.е. вне активной рассылки).
# ==========================================

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path("../users")   # рядом с папками сессий


def _cache_path(user_id: int) -> Path:
    return CACHE_DIR / str(user_id) / "accounts_meta.json"


def load_cache(user_id: int) -> dict:
    """Загрузить весь кеш пользователя. Ключ — имя сессии."""
    path = _cache_path(user_id)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка чтения кеша аккаунтов: {e}")
    return {}


def save_cache(user_id: int, cache: dict):
    """Сохранить весь кеш пользователя."""
    path = _cache_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Ошибка записи кеша аккаунтов: {e}")


def get_account_meta(user_id: int, session_name: str) -> Optional[dict]:
    """
    Получить мету аккаунта из кеша.
    Возвращает dict с ключами: full_name, phone, username, user_id
    или None если в кеше нет.
    """
    cache = load_cache(user_id)
    return cache.get(session_name)


def set_account_meta(user_id: int, session_name: str, meta: dict):
    """Сохранить мету одного аккаунта в кеш."""
    cache = load_cache(user_id)
    cache[session_name] = meta
    save_cache(user_id, cache)


async def ensure_account_meta(user_id: int, session_name: str) -> dict:
    """
    Вернуть мету из кеша.
    Если в кеше нет — подключиться и получить, затем сохранить.
    Вызывать ТОЛЬКО когда сессия гарантированно свободна.
    """
    cached = get_account_meta(user_id, session_name)
    if cached:
        return cached

    try:
        from session_manager import SessionManager
        mgr = SessionManager()
        # FIX: get_session_info возвращает кортеж (success: bool, data: dict|str)
        success, info = await mgr.get_session_info(session_name, user_id)
        if not success or not isinstance(info, dict):
            logger.warning(f"Не удалось получить мету {session_name}: {info}")
            return {"full_name": "", "phone": "", "username": "", "user_id": 0}
        meta = {
            "full_name": info.get("full_name", ""),
            "phone":     info.get("phone", ""),
            "username":  info.get("username", ""),
            "user_id":   info.get("user_id") or 0,
        }
        set_account_meta(user_id, session_name, meta)
        return meta
    except Exception as e:
        logger.warning(f"Не удалось получить мету {session_name}: {e}")
        return {"full_name": "", "phone": "", "username": "", "user_id": 0}


async def prefetch_accounts_meta(user_id: int, session_names: list):
    """
    Предзагрузить мету для списка аккаунтов перед запуском таска.
    Только для тех, кого ещё нет в кеше.
    Вызывать ДО asyncio.create_task(run_*_mailing).
    """
    cache = load_cache(user_id)
    missing = [s for s in session_names if s not in cache]

    if not missing:
        return  # всё уже в кеше

    logger.info(f"Загрузка меты {len(missing)} аккаунтов пользователя {user_id}...")

    for session_name in missing:
        await ensure_account_meta(user_id, session_name)