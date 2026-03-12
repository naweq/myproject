# ==========================================
# ФАЙЛ: bot/utils/validators.py
# ОПИСАНИЕ: Валидаторы данных
# ==========================================
import re
import zipfile
from pathlib import Path
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class FileValidator:
    """Валидатор файлов"""

    MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10MB

    @staticmethod
    def validate_zip_file(file_path: Path, max_size: int = MAX_ZIP_SIZE) -> Tuple[bool, Optional[str]]:
        """Валидация ZIP файла"""
        try:
            if file_path.stat().st_size > max_size:
                return False, f"❌ Файл больше {max_size / (1024 * 1024):.0f}MB"

            if not zipfile.is_zipfile(file_path):
                return False, "❌ Не является ZIP-архивом"

            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                total_size = sum(info.file_size for info in zip_ref.infolist())
                if total_size > max_size * 10:
                    return False, "❌ Содержимое слишком большое"

                session_files = [
                    name for name in zip_ref.namelist()
                    if name.lower().endswith('.session') and '__MACOSX' not in name
                ]

                if not session_files:
                    return False, "❌ Нет .session файлов"

                if len(session_files) > 1000:
                    return False, f"❌ Максимум 100 0 файлов"

            return True, None

        except Exception as e:
            logger.error(f"Ошибка валидации ZIP: {e}")
            return False, f"❌ Ошибка: {str(e)}"

    @staticmethod
    def validate_user_id(user_id: str) -> Tuple[bool, Optional[int], Optional[str]]:
        """Валидация ID пользователя"""
        try:
            uid = int(user_id.strip())
            if uid <= 0:
                return False, None, "❌ ID должен быть > 0"
            return True, uid, None
        except ValueError:
            return False, None, "❌ Некорректный ID"


class TextValidator:
    """Валидатор текста"""

    # @staticmethod
    # def validate_message(text: str) -> Tuple[bool, Optional[str]]:
    #     """Валидация сообщения"""
    #     if not text or not text.strip():
    #         return False, "❌ Текст пустой"
    #
    #     if len(text) > 4096:
    #         return False, "❌ Текст > 4096 символов"
    #
    #     return True, None

    @staticmethod
    def validate_folder_link(link: str) -> Tuple[bool, Optional[str]]:
        """Валидация ссылки на папку"""
        if not link or not link.strip():
            return False, "❌ Ссылка пустая"

        if "t.me/addlist/" not in link and "telegram.me/addlist/" not in link:
            return False, "❌ Неверный формат ссылки на папку"

        return True, None

    @staticmethod
    def validate_target(target: str) -> Tuple[bool, Optional[str]]:
        """Валидация цели (username или ID)"""
        if not target or not target.strip():
            return False, "❌ Цель не указана"

        target = target.strip()

        # Проверка username
        if target.startswith('@'):
            if len(target) < 5:
                return False, "❌ Username слишком короткий"
            return True, None

        # Проверка ID
        try:
            uid = int(target)
            if uid <= 0:
                return False, "❌ ID должен быть > 0"
            return True, None
        except ValueError:
            return False, "❌ Неверный формат (нужен @username или ID)"

    @staticmethod
    def normalize_chat_link(link: str) -> Optional[str]:
        """
        Нормализовать ссылку на чат в формат для pyrogram

        Поддерживаемые форматы:
        - https://t.me/chatname
        - t.me/chatname
        - @chatname
        - tg://resolve?domain=chatname

        Возвращает:
        - @chatname для публичных чатов
        - None если ссылка невалидна
        """
        if not link or not isinstance(link, str):
            return None

        link = link.strip()

        # Паттерны для разных форматов ссылок
        patterns = [
            r'(?:https?://)?t\.me/([a-zA-Z0-9_]+)',  # https://t.me/chatname или t.me/chatname
            r'tg://resolve\?domain=([a-zA-Z0-9_]+)',  # tg://resolve?domain=chatname
            r'@([a-zA-Z0-9_]+)',  # @chatname
            r'^([a-zA-Z0-9_]+)$',  # просто chatname
        ]

        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                username = match.group(1)
                # Проверяем, что username не пустой и валидный
                if username and re.match(r'^[a-zA-Z0-9_]{5,}$', username):
                    return f"@{username}"

        return None

    @staticmethod
    def validate_message(text: str) -> tuple[bool, str]:
        """Валидация текста сообщения"""
        if not text:
            return False, "❌ Сообщение не может быть пустым"

        if len(text) > 4096:
            return False, "❌ Сообщение слишком длинное (максимум 4096 символов)"

        return True, ""

    # @staticmethod
    # def validate_target(target: str) -> tuple[bool, str]:
    #     """Валидация цели для отправки"""
    #     if not target:
    #         return False, "❌ Цель не может быть пустой"
    #
    #     # Проверяем username или ID
    #     if target.startswith('@'):
    #         if len(target) < 6:
    #             return False, "❌ Username слишком короткий"
    #     elif target.isdigit():
    #         if len(target) < 5:
    #             return False, "❌ ID слишком короткий"
    #     else:
    #         return False, "❌ Введите username (@username) или ID"
    #
    #     return True, ""

