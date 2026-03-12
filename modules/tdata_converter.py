# ==========================================
# ФАЙЛ: modules/tdata_converter.py
# ОПИСАНИЕ: Конвертация Hydrogram/Pyrogram .session → TData
# БЕЗ opentele (не требует PyQt5)
# Реализация: прямая запись TData формата
# ==========================================

import asyncio
import hashlib
import logging
import os
import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession

logger = logging.getLogger(__name__)

# DC адреса Telegram
DC_ADDRESSES = {
    1: ("149.154.175.53",  443),
    2: ("149.154.167.51",  443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91",  443),
    5: ("91.108.56.130",   443),
}


# ─────────────────────────────────────────────────────────────────────────────
# TData низкоуровневый формат
# ─────────────────────────────────────────────────────────────────────────────

def _tdf_magic() -> bytes:
    return b"TDF$"


def _pack_uint32(v: int) -> bytes:
    return struct.pack("<I", v)


def _pack_uint64(v: int) -> bytes:
    return struct.pack("<Q", v)


def _md5_digest(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def _tdf_checksum(data: bytes, version: bytes) -> bytes:
    """Контрольная сумма TDF файла."""
    digest = hashlib.md5(data + version + _tdf_magic()).digest()
    return digest


def _write_tdf_file(path: Path, data: bytes, version: int = 2007013) -> None:
    """
    Записывает файл в формате TDF (Telegram Desktop Format).
    Структура: magic(4) + version(4) + data + checksum(16)
    """
    ver = _pack_uint32(version)
    checksum = _tdf_checksum(data, ver)
    content = _tdf_magic() + ver + data + checksum
    path.write_bytes(content)

    # TDesktop создаёт 3 копии: file, file1, file2 (файл + бэкапы)
    path.with_name(path.name + "1").write_bytes(content)
    path.with_name(path.name + "2").write_bytes(content)


def _encode_tdf_string(s: str) -> bytes:
    """Кодирует строку в формат QDataStream (uint32 length_in_bytes + utf16le)."""
    encoded = s.encode("utf-16-le")
    return _pack_uint32(len(encoded)) + encoded


def _encode_tdf_bytearray(data: bytes) -> bytes:
    """Кодирует байты как QByteArray (int32 size + bytes)."""
    return struct.pack(">i", len(data)) + data


def _build_key_data(
    dc_id: int,
    auth_key: bytes,
    user_id: int,
) -> bytes:
    """
    Строит содержимое файла 'key_datas' (хранит auth_key и dc).
    Формат — QDataStream сериализация.
    """
    stream = b""
    # localKey placeholder (256 нулей — TDesktop генерирует при первом запуске)
    local_key = b"\x00" * 256
    stream += _encode_tdf_bytearray(local_key)

    # Массив аккаунтов (1 аккаунт)
    stream += _pack_uint32(1)  # count

    # Для каждого аккаунта: dc_id (int32) + auth_key (256 bytes)
    stream += struct.pack(">i", dc_id)
    stream += _encode_tdf_bytearray(auth_key.ljust(256, b"\x00")[:256])

    return stream


def _build_map_data(dc_id: int, user_id: int) -> bytes:
    """Строит файл 'map' — индекс хранилища TDesktop."""
    stream = b""
    # salt (64 байта нулей для незашифрованного варианта)
    stream += _encode_tdf_bytearray(b"\x00" * 64)
    # legacySalt
    stream += _encode_tdf_bytearray(b"\x00" * 64)
    # keyEncrypted (256 нулей)
    stream += _encode_tdf_bytearray(b"\x00" * 256)
    return stream


# ─────────────────────────────────────────────────────────────────────────────
# Основная логика
# ─────────────────────────────────────────────────────────────────────────────

async def convert_to_tdata(full_session_name: str, user_id: int) -> Path:
    """
    Конвертирует Hydrogram/Pyrogram .session в TData.
    Возвращает путь к готовому ZIP-архиву.
    """
    from modules.session_manager import SessionManager
    from modules.database import Database

    session_mgr = SessionManager()

    base_path    = session_mgr._get_session_path(full_session_name, user_id)
    session_path = Path(str(base_path) + ".session")

    if not session_path.exists():
        raise FileNotFoundError(f"Файл сессии не найден: {session_path}")

    db  = Database()
    api = await db.get_current_api(user_id)
    if not api or not api.get("api_id") or not api.get("api_hash"):
        api = await db.get_user_api(user_id, 1)
    if not api or not api.get("api_id") or not api.get("api_hash"):
        raise ValueError("API ключи не настроены. Перейдите: Меню → Настройки → Настройки API")

    api_id   = int(api["api_id"])
    api_hash = api["api_hash"]

    logger.info(f"Конвертация {full_session_name} (user={user_id}, api_id={api_id})")

    clean_name = full_session_name.replace(":", "_").replace(".session", "")
    work_dir   = Path("temp") / f"conv_{user_id}_{clean_name}"
    work_dir.mkdir(parents=True, exist_ok=True)

    tele_session_path = work_dir / "tele_temp.session"
    tdata_folder      = work_dir / "tdata"

    try:
        dc_id, auth_key_bytes, tg_user_id = _read_pyro_session(session_path)
        _write_telethon_session(dc_id, auth_key_bytes, tele_session_path)
        _build_tdata(dc_id, auth_key_bytes, tg_user_id, api_id, api_hash, tdata_folder)
        zip_path = _make_zip(tdata_folder, clean_name, user_id)
        logger.info(f"Конвертация завершена: {zip_path}")
        return zip_path

    except Exception as e:
        logger.error(f"Ошибка конвертации {full_session_name}: {e}", exc_info=True)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _read_pyro_session(session_path: Path) -> Tuple[int, bytes, int]:
    """Читает dc_id, auth_key, user_id из Pyrogram/Hydrogram SQLite сессии."""
    conn = sqlite3.connect(str(session_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT dc_id, auth_key, user_id FROM sessions LIMIT 1")
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise ValueError("Pyrogram сессия пуста или повреждена")

    dc_id, auth_key_bytes, tg_user_id = row

    if not auth_key_bytes:
        raise ValueError("auth_key отсутствует — сессия не авторизована")

    logger.info(f"  Прочитана сессия: DC={dc_id}, user_id={tg_user_id}")
    return dc_id, auth_key_bytes, tg_user_id


def _write_telethon_session(dc_id: int, auth_key_bytes: bytes, path: Path) -> None:
    """Создаёт Telethon SQLiteSession из сырых данных."""
    dc_ip, dc_port = DC_ADDRESSES.get(dc_id, ("149.154.167.51", 443))
    session = SQLiteSession(str(path))
    session.set_dc(dc_id, dc_ip, dc_port)
    session.auth_key = AuthKey(data=auth_key_bytes)
    session.save()
    del session
    logger.info(f"  Telethon сессия записана: DC={dc_id} ({dc_ip})")


def _build_tdata(
    dc_id: int,
    auth_key_bytes: bytes,
    user_id: int,
    api_id: int,
    api_hash: str,
    tdata_folder: Path,
) -> None:
    """
    Создаёт папку tdata с файлами в формате Telegram Desktop.

    Структура:
        tdata/
        ├── key_datas        (auth_key + dc)
        ├── key_datas1       (копия)
        ├── key_datas2       (копия)
        ├── settings         (настройки)
        ├── settings1
        ├── settings2
        └── D877F783D5D3EF8C/ (папка аккаунта)
            ├── map
            ├── map1
            └── map2
    """
    tdata_folder.mkdir(parents=True, exist_ok=True)

    auth_key_padded = auth_key_bytes[:256].ljust(256, b"\x00")

    # ── key_datas ──────────────────────────────────────────────────────────
    # Формат: version(4) + dc_count(4) + [dc_id(4) + auth_key(256+4)] + user_id(8)
    kd_stream = b""
    kd_stream += _pack_uint32(2)        # version
    kd_stream += _pack_uint32(1)        # accounts count

    # Account entry
    kd_stream += struct.pack(">i", dc_id)
    kd_stream += _encode_tdf_bytearray(auth_key_padded)

    # Main DC
    kd_stream += struct.pack(">i", dc_id)
    # user_id as int64
    kd_stream += struct.pack(">q", user_id if user_id else 0)

    _write_tdf_file(tdata_folder / "key_datas", kd_stream)
    logger.info("  key_datas записан")

    # ── settings ──────────────────────────────────────────────────────────
    settings_stream = b""
    # Минимальные настройки — версия и пустой блок
    settings_stream += _pack_uint32(3010000)  # app version
    settings_stream += _pack_uint32(0)        # settings flags
    _write_tdf_file(tdata_folder / "settings", settings_stream)
    logger.info("  settings записан")

    # ── Папка аккаунта ────────────────────────────────────────────────────
    # TDesktop использует хеш от user_id как имя папки
    account_folder_name = _account_folder_name(user_id)
    account_dir = tdata_folder / account_folder_name
    account_dir.mkdir(parents=True, exist_ok=True)

    # map файл
    map_stream = b""
    map_stream += _encode_tdf_bytearray(b"\x00" * 64)   # legacy salt
    map_stream += _encode_tdf_bytearray(b"\x00" * 64)   # legacy salt 2
    map_stream += _encode_tdf_bytearray(b"\x00" * 256)  # key encrypted
    _write_tdf_file(account_dir / "map", map_stream)
    logger.info(f"  Папка аккаунта: {account_folder_name}/map записан")


def _account_folder_name(user_id: int) -> str:
    """
    TDesktop вычисляет имя папки как верхний регистр MD5 от user_id.
    Для незашифрованного хранилища используется стандартное имя.
    """
    # Стандартное имя для первого аккаунта без шифрования
    return "D877F783D5D3EF8C"


def _make_zip(tdata_folder: Path, clean_name: str, user_id: int) -> Path:
    """Упаковывает папку tdata в ZIP."""
    out_dir = Path("temp")
    out_dir.mkdir(exist_ok=True)

    zip_name = f"tdata_{clean_name}_{user_id}"
    zip_base = out_dir / zip_name

    shutil.make_archive(
        str(zip_base),
        "zip",
        tdata_folder.parent,
        tdata_folder.name,
    )

    zip_path = out_dir / f"{zip_name}.zip"
    logger.info(f"  ZIP создан: {zip_path} ({zip_path.stat().st_size // 1024} KB)")
    return zip_path
