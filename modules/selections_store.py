# ==========================================
# ФАЙЛ: modules/selections_store.py
# ОПИСАНИЕ: Персистентное хранилище выбранных аккаунтов и задержек
# Исправления:
#   - Все I/O переведены на aiofiles (неблокирующие)
#   - Синхронные обёртки оставлены для обратной совместимости
#   - Типизация
# ==========================================

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import aiofiles

logger = logging.getLogger(__name__)


def _selected_path() -> Path:
    from config import SELECTED_ACCS_FILE
    return Path(SELECTED_ACCS_FILE)


def _delays_path() -> Path:
    from config import USER_DELAYS_FILE
    return Path(USER_DELAYS_FILE)


# ─────────────────────────────────────────
# ASYNC I/O HELPERS
# ─────────────────────────────────────────

async def _read_json_async(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Ошибка чтения {path}: {e}")
        return {}


async def _write_json_async(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"Ошибка записи {path}: {e}")


# Sync fallback (для мест где нет await)
def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Ошибка чтения {path}: {e}")
    return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Ошибка записи {path}: {e}")


# ─────────────────────────────────────────
# ВЫБРАННЫЕ АККАУНТЫ — async API
# ─────────────────────────────────────────

async def get_selected_accounts_async(user_id: int) -> List[str]:
    data = await _read_json_async(_selected_path())
    return data.get(str(user_id), [])


async def set_selected_accounts_async(user_id: int, accounts: List[str]) -> None:
    path = _selected_path()
    data = await _read_json_async(path)
    data[str(user_id)] = accounts
    await _write_json_async(path, data)


async def toggle_account_async(user_id: int, session_name: str) -> bool:
    """Переключить аккаунт. Возвращает True если теперь выбран."""
    path = _selected_path()
    data = await _read_json_async(path)
    uid = str(user_id)
    selected: List[str] = data.get(uid, [])

    if session_name in selected:
        selected.remove(session_name)
        is_selected = False
    else:
        selected.append(session_name)
        is_selected = True

    data[uid] = selected
    await _write_json_async(path, data)
    return is_selected


async def select_all_accounts_async(user_id: int, all_sessions: List[str]) -> None:
    path = _selected_path()
    data = await _read_json_async(path)
    data[str(user_id)] = list(all_sessions)
    await _write_json_async(path, data)


async def deselect_all_accounts_async(user_id: int) -> None:
    path = _selected_path()
    data = await _read_json_async(path)
    data[str(user_id)] = []
    await _write_json_async(path, data)


async def clear_missing_accounts_async(
    user_id: int, existing_sessions: List[str]
) -> List[str]:
    selected = await get_selected_accounts_async(user_id)
    cleaned = [s for s in selected if s in existing_sessions]
    if len(cleaned) != len(selected):
        await set_selected_accounts_async(user_id, cleaned)
    return cleaned


# ─────────────────────────────────────────
# SYNC-ОБЁРТКИ (обратная совместимость)
# ─────────────────────────────────────────

def get_selected_accounts(user_id: int) -> List[str]:
    return _read_json(_selected_path()).get(str(user_id), [])


def set_selected_accounts(user_id: int, accounts: List[str]) -> None:
    path = _selected_path()
    data = _read_json(path)
    data[str(user_id)] = accounts
    _write_json(path, data)


def toggle_account(user_id: int, session_name: str) -> bool:
    path = _selected_path()
    data = _read_json(path)
    uid = str(user_id)
    selected: List[str] = data.get(uid, [])
    if session_name in selected:
        selected.remove(session_name)
        is_selected = False
    else:
        selected.append(session_name)
        is_selected = True
    data[uid] = selected
    _write_json(path, data)
    return is_selected


def select_all_accounts(user_id: int, all_sessions: List[str]) -> None:
    path = _selected_path()
    data = _read_json(path)
    data[str(user_id)] = list(all_sessions)
    _write_json(path, data)


def deselect_all_accounts(user_id: int) -> None:
    path = _selected_path()
    data = _read_json(path)
    data[str(user_id)] = []
    _write_json(path, data)


def clear_missing_accounts(user_id: int, existing_sessions: List[str]) -> List[str]:
    selected = get_selected_accounts(user_id)
    cleaned = [s for s in selected if s in existing_sessions]
    if len(cleaned) != len(selected):
        set_selected_accounts(user_id, cleaned)
    return cleaned


# ─────────────────────────────────────────
# ЗАДЕРЖКИ — async API
# ─────────────────────────────────────────

async def get_delays_async(user_id: int) -> Dict[str, int]:
    from config import DEFAULT_MESSAGE_DELAY, DEFAULT_CYCLE_DELAY
    data = await _read_json_async(_delays_path())
    user_data = data.get(str(user_id), {})
    return {
        "message": user_data.get("message", DEFAULT_MESSAGE_DELAY),
        "cycle":   user_data.get("cycle",   DEFAULT_CYCLE_DELAY),
    }


async def set_delays_async(
    user_id: int,
    message_delay: Optional[int] = None,
    cycle_delay: Optional[int] = None,
) -> None:
    path = _delays_path()
    data = await _read_json_async(path)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    if message_delay is not None:
        data[uid]["message"] = message_delay
    if cycle_delay is not None:
        data[uid]["cycle"] = cycle_delay
    await _write_json_async(path, data)


# Sync-обёртки задержек
def get_delays(user_id: int) -> Dict[str, int]:
    from config import DEFAULT_MESSAGE_DELAY, DEFAULT_CYCLE_DELAY
    data = _read_json(_delays_path())
    user_data = data.get(str(user_id), {})
    return {
        "message": user_data.get("message", DEFAULT_MESSAGE_DELAY),
        "cycle":   user_data.get("cycle",   DEFAULT_CYCLE_DELAY),
    }


def set_delays(
    user_id: int,
    message_delay: Optional[int] = None,
    cycle_delay: Optional[int] = None,
) -> None:
    path = _delays_path()
    data = _read_json(path)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    if message_delay is not None:
        data[uid]["message"] = message_delay
    if cycle_delay is not None:
        data[uid]["cycle"] = cycle_delay
    _write_json(path, data)
