# ==========================================
# ФАЙЛ: modules/kb_layout_settings.py
# ОПИСАНИЕ: Настройки вида клавиатуры аккаунтов
# Исправления:
#   - Async I/O через aiofiles
#   - Типизация
# ==========================================

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

logger = logging.getLogger(__name__)

LAYOUT_SETTINGS_FILE = Path("data") / "kb_layout_settings.json"

DEFAULT_LAYOUT: Dict[str, Any] = {
    "per_page":           10,
    "cols":               2,
    "name_length":        10,
    "show_status":        True,
    "auto_delete_invalid": False,
}


# ─────────────────────────────────────────
# ASYNC I/O
# ─────────────────────────────────────────

async def _load_async() -> Dict[str, Any]:
    if not LAYOUT_SETTINGS_FILE.exists():
        return {}
    try:
        async with aiofiles.open(LAYOUT_SETTINGS_FILE, "r", encoding="utf-8") as f:
            content = await f.read()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Ошибка чтения kb_layout_settings: {e}")
        return {}


async def _save_async(data: Dict[str, Any]) -> None:
    LAYOUT_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiofiles.open(LAYOUT_SETTINGS_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Ошибка записи kb_layout_settings: {e}")


# ─────────────────────────────────────────
# SYNC (обратная совместимость)
# ─────────────────────────────────────────

def _load() -> Dict[str, Any]:
    if not LAYOUT_SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(LAYOUT_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: Dict[str, Any]) -> None:
    LAYOUT_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAYOUT_SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ─────────────────────────────────────────
# PUBLIC API — sync (для хендлеров)
# ─────────────────────────────────────────

def get_layout(user_id: int) -> Dict[str, Any]:
    """Получить настройки с дефолтами."""
    data = _load()
    user_settings = data.get(str(user_id), {})
    return {**DEFAULT_LAYOUT, **user_settings}


def set_layout(user_id: int, **kwargs: Any) -> None:
    """Обновить одно или несколько полей настроек."""
    data = _load()
    uid = str(user_id)
    current = data.get(uid, {})
    current.update(kwargs)
    data[uid] = current
    _save(data)


def toggle_auto_delete(user_id: int) -> bool:
    """Переключить автоудаление невалидных. Возвращает новое значение."""
    layout = get_layout(user_id)
    new_val = not layout["auto_delete_invalid"]
    set_layout(user_id, auto_delete_invalid=new_val)
    return new_val


def is_auto_delete_enabled(user_id: int) -> bool:
    return get_layout(user_id)["auto_delete_invalid"]


# ─────────────────────────────────────────
# PUBLIC API — async
# ─────────────────────────────────────────

async def get_layout_async(user_id: int) -> Dict[str, Any]:
    data = await _load_async()
    return {**DEFAULT_LAYOUT, **data.get(str(user_id), {})}


async def set_layout_async(user_id: int, **kwargs: Any) -> None:
    data = await _load_async()
    uid = str(user_id)
    current = data.get(uid, {})
    current.update(kwargs)
    data[uid] = current
    await _save_async(data)
