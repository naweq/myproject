# ==========================================
# ФАЙЛ: modules/core.py
# ОПИСАНИЕ: Прокси и API-ключи пользователей
# Исправления:
#   - asyncio.Lock для _proxy_index (thread/task safe)
#   - run_in_executor для блокирующих I/O операций
#   - Строгие аннотации типов
# ==========================================

import asyncio
import json
import logging
import os
from typing import Optional

from config import (
    api_settings as API_SETTINGS,
    current_api as CURRENT_API,
    session_settings as SESSION_SETTINGS,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# ПРОКСИ — круговая ротация (asyncio-safe)
# ─────────────────────────────────────────

_proxy_index: int = 0
_proxy_lock: asyncio.Lock = asyncio.Lock()


def get_next_proxy(filepath: str = "proxies.txt") -> Optional[str]:
    """
    Возвращает следующий прокси из файла по кругу.
    ВНИМАНИЕ: Это синхронная функция — вызывать только из синхронного
    контекста или обернуть в run_in_executor для async.
    """
    global _proxy_index

    if not os.path.exists(filepath):
        logger.warning(f"Файл {filepath} не найден.")
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        proxies = [line.strip() for line in f if line.strip()]

    if not proxies:
        logger.warning("Файл proxies.txt пустой.")
        return None

    proxy = proxies[_proxy_index % len(proxies)]
    _proxy_index += 1

    if "://" not in proxy:
        proxy = "socks5://" + proxy

    return proxy


async def get_next_proxy_async(filepath: str = "proxies.txt") -> Optional[str]:
    """Asyncio-safe ротация прокси."""
    global _proxy_index

    loop = asyncio.get_running_loop()

    def _read() -> list[str]:
        if not os.path.exists(filepath):
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    proxies = await loop.run_in_executor(None, _read)
    if not proxies:
        return None

    async with _proxy_lock:
        proxy = proxies[_proxy_index % len(proxies)]
        _proxy_index += 1

    if "://" not in proxy:
        proxy = "socks5://" + proxy

    return proxy


# ─────────────────────────────────────────
# JSON helpers (async via executor)
# ─────────────────────────────────────────

def _load_json(path: str) -> dict:
    """Синхронное чтение JSON. Используй только из executor."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Ошибка чтения {path}: {e}")
        return {}


def _save_json(path: str, data: dict) -> None:
    """Синхронная запись JSON. Используй только из executor."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except OSError as e:
        logger.error(f"Ошибка записи {path}: {e}")


async def _async_load(path: str) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _load_json, path)


async def _async_save(path: str, data: dict) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _save_json, path, data)


# ─────────────────────────────────────────
# ПРОКСИ ДЛЯ СЕССИЙ
# ─────────────────────────────────────────

async def set_session_proxy(user_id: int, session_name: str) -> Optional[str]:
    data = await _async_load(SESSION_SETTINGS)
    uid = str(user_id)

    if uid not in data:
        data[uid] = {}

    if session_name in data[uid]:
        return data[uid][session_name]

    proxy = await get_next_proxy_async()
    data[uid][session_name] = proxy
    await _async_save(SESSION_SETTINGS, data)
    return proxy


async def get_session_proxy(user_id: int, session_name: str) -> Optional[str]:
    data = await _async_load(SESSION_SETTINGS)
    uid = str(user_id)
    user_data = data.get(uid)

    if user_data and session_name in user_data:
        return user_data[session_name]

    logger.info(f"Прокси для '{session_name}' (user {user_id}) не найден — назначаю.")
    return await set_session_proxy(user_id, session_name)


async def delete_session_proxy(user_id: int, session_name: str) -> bool:
    data = await _async_load(SESSION_SETTINGS)
    uid = str(user_id)

    if uid in data and session_name in data[uid]:
        del data[uid][session_name]
        if not data[uid]:
            del data[uid]
        await _async_save(SESSION_SETTINGS, data)
        return True
    return False


# ─────────────────────────────────────────
# API КЛЮЧИ ПОЛЬЗОВАТЕЛЕЙ
# ─────────────────────────────────────────

async def set_user_api(
    user_id: int, now_change: int, api_id: str, api_hash: str
) -> str:
    data = await _async_load(API_SETTINGS)
    uid = str(user_id)

    if uid not in data:
        data[uid] = {}

    api_key = f"api_{now_change}"
    data[uid][api_key] = {"api_id": str(api_id), "api_hash": api_hash}
    await _async_save(API_SETTINGS, data)
    return api_key


async def get_user_api(
    user_id: int, now_change: int
) -> Optional[dict]:
    data = await _async_load(API_SETTINGS)
    user_data = data.get(str(user_id))
    if not user_data:
        return None
    return user_data.get(f"api_{now_change}") or None


async def delete_user_api(user_id: int, now_change: int) -> bool:
    data = await _async_load(API_SETTINGS)
    uid = str(user_id)
    api_key = f"api_{now_change}"

    if uid in data and api_key in data[uid]:
        del data[uid][api_key]
        if not data[uid]:
            del data[uid]
        await _async_save(API_SETTINGS, data)
        return True
    return False


# ─────────────────────────────────────────
# ТЕКУЩИЙ API
# ─────────────────────────────────────────

async def get_current_api(user_id: int) -> Optional[str]:
    data = await _async_load(CURRENT_API)
    return data.get(str(user_id)) or None


async def set_current_api(user_id: int, number: int) -> bool:
    data = await _async_load(CURRENT_API)
    data[str(user_id)] = str(number)
    try:
        await _async_save(CURRENT_API, data)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения current api: {e}")
        return False
