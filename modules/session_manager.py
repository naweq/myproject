# ==========================================
# ФАЙЛ: bot/services/session_manager.py
# ОПИСАНИЕ: Менеджер сессий исключительно на Hydrogram
# ==========================================
import os
import re
import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse

from hydrogram.raw.functions.account import GetPassword
# from urllib.parse import urlparsefrom
from hydrogram import Client
from hydrogram.errors import (
    FloodWait,
    BadRequest,
    AuthKeyUnregistered,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    SessionPasswordNeeded, UserIsBlocked, PeerFlood
)

from modules.core import (
    set_session_proxy,
    get_session_proxy,
    set_user_api,
    get_user_api,
    delete_user_api
)
from config import SESSIONS_DIR, bot, ADMIN_IDS

logger = logging.getLogger(__name__)
logging.getLogger("hydrogram").setLevel(logging.ERROR)


class SessionManager:
    """Менеджер сессий Hydrogram с ротацией API и прокси"""

    def __init__(self):
        self.sessions_dir = Path(SESSIONS_DIR)
        self.sessions_dir.mkdir(exist_ok=True)

    def get_user_folder(self, user_id: int) -> Path:
        folder = Path(f"users/{user_id}")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def get_sessions(self, user_id: int) -> List[str]:
        """Получить все сессии пользователя."""
        sessions = []
        user_folder = self.get_user_folder(user_id)
        for f in user_folder.iterdir():
            if f.suffix == ".session" and f.is_file():
                sessions.append(f.name)
        return sorted(sessions)

    def _clean_name(self, session_name: str) -> str:
        """Убрать ВСЕ .session суффиксы. Hydrogram добавляет .session сам."""
        name = session_name
        while name.endswith('.session'):
            name = name[:-8]
        return name

    def _get_session_path(self, session_name: str, user_id: int) -> Path:
        """Возвращает путь БЕЗ .session — Hydrogram добавит сам при создании."""
        return self.get_user_folder(user_id) / self._clean_name(session_name)

    def _get_account_states_path(self, user_id: int) -> Path:
        return self.get_user_folder(user_id) / "account_states.json"

    def get_account_states(self, user_id: int) -> Dict[str, str]:
        states_path = self._get_account_states_path(user_id)
        if states_path.exists():
            try:
                return json.loads(states_path.read_text(encoding='utf-8'))
            except Exception as e:
                logger.error(f"Ошибка чтения состояний: {e}")
        return {}

    def save_account_state(self, user_id: int, session_name: str, state: str):
        states = self.get_account_states(user_id)
        states[session_name] = state
        states_path = self._get_account_states_path(user_id)
        states_path.parent.mkdir(parents=True, exist_ok=True)
        states_path.write_text(json.dumps(states, indent=2, ensure_ascii=False), encoding='utf-8')

    async def _safe_disconnect(self, app: Client):
        """Корректное отключение — даём фоновым задачам завершиться."""
        if app.is_connected:
            await app.disconnect()
        else:
            pass

    def _parse_proxy(self, proxy_uri: str) -> Optional[dict]:
        if not proxy_uri or proxy_uri in ("None", "none", ""):
            return None
        try:
            parsed = urlparse(str(proxy_uri))
            if not parsed.hostname or not parsed.port:
                logger.warning(f"Прокси без hostname/port, пропускаем: {proxy_uri}")
                return None
            proxy = {
                "scheme": parsed.scheme or "socks5",
                "hostname": parsed.hostname,
                "port": int(parsed.port)
            }
            if parsed.username:
                proxy["username"] = parsed.username
            if parsed.password:
                proxy["password"] = parsed.password
            return proxy
        except Exception as e:
            logger.error(f"Ошибка парсинга прокси: {e}")
            return None

    async def get_hydrogram_client(self, session_name: str, user_id: int, now_change: int = 1):
        """Создать экземпляр клиента Hydrogram."""
        clean = self._clean_name(session_name)
        session_path = self._get_session_path(clean, user_id)  # уже без .session
        proxy_uri = await get_session_proxy(user_id, session_name=clean)
        api = await get_user_api(user_id, now_change)

        if not api:
            raise Exception('API ключи не настроены. Перейдите в настройки и добавьте API.')

        return Client(
            name=str(session_path),  # передаём БЕЗ .session
            api_id=int(api['api_id']),
            api_hash=api['api_hash'],
            proxy=self._parse_proxy(proxy_uri) if proxy_uri else None
        )

    async def create_session_by_phone(self, user_id: int, phone: str):
        """Шаг 1: Создаём клиент. Имя сессии = номер без +. После входа переименуется в ID."""
        now_change = 1
        api = await get_user_api(user_id, now_change)
        if not api:
            raise Exception("API ключи не настроены. Перейдите в настройки и добавьте API.")

        phone_clean = phone.replace("+", "")
        proxy_uri = await set_session_proxy(user_id, session_name=phone_clean)

        # ВАЖНО: передаём путь БЕЗ .session — Hydrogram добавит сам
        session_path = self._get_session_path(phone_clean, user_id)

        return Client(
            name=str(session_path),
            api_id=int(api['api_id']),
            api_hash=api['api_hash'],
            proxy=self._parse_proxy(proxy_uri) if proxy_uri else None
        )

    async def sign_in_combined(self, user_id: int, phone: str, code: str, phone_hash: str, temp_session: str = None,
                               password: str = None):
        """Шаг 2: Завершение входа (Код или 2FA). Переименовывает сессию в ID аккаунта."""
        phone_clean = phone.replace("+", "")
        app = await self.get_hydrogram_client(phone_clean, user_id)

        try:
            await app.connect()

            # 1. Сначала ВСЕГДА пытаемся войти по коду
            try:
                await app.sign_in(phone_number=phone, phone_code_hash=phone_hash, phone_code=code)
            except SessionPasswordNeeded:
                # 2. Если Telegram говорит, что нужен пароль:
                if password:
                    # Если пароль передан — вводим его. Это завершит авторизацию.
                    await app.check_password(password)
                else:
                    # Если пароля нет — выбрасываем спец-ошибку для бота/интерфейса
                    raise Exception("2FA_REQUIRED")

            # 3. Успех — получаем ID ДО отключения
            me = await app.get_me()
            account_id = str(me.id)
            phone_clean = phone.replace("+", "")

            await self._safe_disconnect(app)

            # Переименовываем ВСЕ файлы сессии: НОМЕР.* -> ID.*
            user_folder = self.get_user_folder(user_id)
            for f in list(user_folder.iterdir()):
                # Ищем файлы вида: НОМЕР, НОМЕР.session, НОМЕР.session-journal, ...
                stem = f.name.split(".")[0]
                if stem == phone_clean:
                    suffix = f.name[len(phone_clean):]   # например ".session" или ".session-journal"
                    new_path = user_folder / (account_id + suffix)
                    if new_path.exists():
                        new_path.unlink()
                    f.rename(new_path)
                    logger.info(f"Переименован: {f.name} -> {new_path.name}")

            self.save_account_state(user_id, f"{account_id}.session", "🟢")
            logger.info(f"Сессия сохранена как {account_id}.session (номер: {phone})")
            return account_id

        except PhoneCodeInvalid:
            raise Exception("Неверный код")
        except PhoneCodeExpired:
            raise Exception("Код просрочен")
        except Exception as e:
            # Прокидываем "2FA_REQUIRED" дальше, остальные ошибки логируем
            if str(e) == "2FA_REQUIRED":
                raise e
            raise Exception(f"Ошибка входа: {e}")
        finally:
            await self._safe_disconnect(app)

    async def get_login_code(self, session_name: str, user_id: int) -> Optional[str]:
        """Получить код из чата 777000."""
        app = await self.get_hydrogram_client(session_name, user_id)
        try:
            await app.connect()
            async for msg in app.get_chat_history(777000, limit=5):
                if msg.text:
                    match = re.search(r'\b\d{5}\b', msg.text)
                    if match:
                        return match.group(0)
            return None
        except Exception as e:
            logger.error(f"Ошибка получения кода: {e}")
            return None
        finally:
            await self._safe_disconnect(app)



    async def get_session_info(self, session_name: str, user_id: int):
        app = await self.get_hydrogram_client(session_name, user_id)
        spamblock = "Неизвестно..."

        try:
            await app.connect()
            me = await app.get_me()

            if me is None:
                return False, 'Не удалось получить данные аккаунта'

            phone = me.phone_number or "—"
            idx = me.id
            name = me.full_name or "—"
            username = me.username or None
            prem = me.is_premium or False
            status = 'Активен' if me.status else 'Оффлайн'

            try:
                from hydrogram.raw.functions.account import GetPassword
                result = await app.invoke(GetPassword())
                passwd = 'Подключена' if result.has_password else 'Без 2FA'
            except Exception:
                passwd = 'Неизвестно'

            try:
                await app.send_message("@SpamBot", "/start")
                await asyncio.sleep(2)
                async for message in app.get_chat_history("@SpamBot", limit=1):
                    if message.text:
                        text = message.text.lower()
                        if "no limits" in text or "нет ограничений" in text:
                            spamblock = "Отсутствует"
                        elif "spam" in text or "ограничен" in text or "limited" in text:
                            spamblock = "Есть"
                    break
            except UserIsBlocked:
                spamblock = "SpamBot заблокирован"
            except PeerFlood:
                spamblock = "PeerFlood"
            except Exception as e:
                logger.warning(f"Ошибка проверки спамблока: {e}")

            return True, {
                "full_name": name,
                "user_id": idx,
                "phone": phone,
                "username": username,
                "status": status,
                "is_premium": prem,
                "has_2fa": passwd,
                "spamblock": spamblock
            }

        except Exception as e:
            return False, f'Не удалось подключиться к аккаунту: {e}'
        finally:
            await self._safe_disconnect(app)

    async def check_session_valid(self, full_session_name: str, user_id: int) -> tuple:
        """
        Проверка валидности: подключиться и получить user_id аккаунта.

        Логика повторов:
          - 1 попытка
          - сетевая ошибка → ещё 1 попытка
          - снова сетевая → сменить прокси, повторить (до 3 смен)
          - auth-ошибка → сразу 🔴, не повторять

        Лог в консоль:
          🔴: |bot_user_id|username|session_name|🔴
          🟢: |bot_user_id|username|session_name|🟢|account_tg_id

        Возвращает: tuple(status: str, account_id: str | None)
        """
        clean = self._clean_name(full_session_name)
        session_path = str(self._get_session_path(full_session_name, user_id)) + ".session"

        # Получаем отображаемое имя пользователя бота для лога
        try:
            tg_user = await bot.get_chat(user_id)
            user_display = tg_user.username or tg_user.full_name or str(user_id)
        except Exception:
            user_display = str(user_id)

        def _log(status: str, account_id: str = ""):
            if account_id:
                logger.info(f"|{user_id}|{user_display}|{clean}|{status}|{account_id}")
            else:
                logger.info(f"|{user_id}|{user_display}|{clean}|{status}")

        def _save(status: str):
            self.save_account_state(user_id, full_session_name, status)

        if not os.path.exists(session_path):
            _save("🔴")
            _log("🔴")
            return "🔴", None

        def _is_auth_err(e: Exception) -> bool:
            kw = ("authkeyunregistered", "auth_key_unregistered",
                  "sessionrevoked", "session_revoked",
                  "not authorized", "unauthorized")
            return isinstance(e, AuthKeyUnregistered) or any(k in str(e).lower() for k in kw)

        def _is_net_err(e: Exception) -> bool:
            return isinstance(e, (asyncio.TimeoutError, OSError, ConnectionError, TimeoutError))

        max_proxy_swaps = 3

        for proxy_attempt in range(max_proxy_swaps + 1):
            net_fails = 0

            while net_fails < 2:
                client = None
                try:
                    client = await self.get_hydrogram_client(full_session_name, user_id)
                    await asyncio.wait_for(client.connect(), timeout=15.0)
                    me = await asyncio.wait_for(client.get_me(), timeout=10.0)
                    try:
                        await asyncio.wait_for(client.disconnect(), timeout=5.0)
                    except Exception:
                        pass

                    if me and me.id:
                        _save("🟢")
                        _log("🟢", str(me.id))
                        return "🟢", str(me.id)
                    else:
                        _save("🔴")
                        _log("🔴")
                        return "🔴", None

                except Exception as e:
                    try:
                        if client and getattr(client, "is_connected", False):
                            await asyncio.wait_for(client.disconnect(), timeout=3.0)
                    except Exception:
                        pass

                    if _is_auth_err(e):
                        _save("🔴")
                        _log("🔴")
                        return "🔴", None

                    if _is_net_err(e):
                        net_fails += 1
                        if net_fails < 2:
                            await asyncio.sleep(1)
                            continue
                        break  # две сетевые подряд — идём менять прокси
                    else:
                        _save("🔴")
                        _log("🔴")
                        return "🔴", None

            # Меняем прокси и пробуем снова
            if proxy_attempt < max_proxy_swaps:
                try:
                    from core import get_next_proxy, _save_json, _load_json
                    from config import session_settings as SESSION_SETTINGS
                    new_proxy = get_next_proxy()
                    if not new_proxy:
                        break
                    data = _load_json(SESSION_SETTINGS)
                    uid_str = str(user_id)
                    if uid_str not in data:
                        data[uid_str] = {}
                    data[uid_str][clean] = new_proxy
                    _save_json(SESSION_SETTINGS, data)
                    logger.info(f"|{user_id}|{user_display}|{clean}|proxy_swap:{proxy_attempt + 1}")
                    await asyncio.sleep(1)
                except Exception as pe:
                    logger.warning(f"proxy swap error: {pe}")
                    break
            else:
                break

        _save("🔴")
        _log("🔴")
        return "🔴", None






    def delete_session(self, session_name: str, user_id: int) -> bool:
        """Удалить сессию и все связанные файлы, очистить states."""
        try:
            clean = self._clean_name(session_name)
            user_folder = self.get_user_folder(user_id)

            # Удаляем .session и .session.json (если есть)
            for suffix in (".session", ".session.json"):
                f = user_folder / (clean + suffix)
                if f.exists():
                    f.unlink()
                    logger.debug(f"Удалён файл: {f.name}")

            # Очищаем account_states — ключ может быть с .session или без
            states = self.get_account_states(user_id)
            changed = False
            for key in (session_name, clean, clean + ".session"):
                if key in states:
                    del states[key]
                    changed = True
            if changed:
                self._get_account_states_path(user_id).write_text(
                    json.dumps(states, indent=2, ensure_ascii=False), encoding='utf-8'
                )

            return True
        except Exception as e:
            logger.error(f"Ошибка удаления сессии {session_name}: {e}")
            return False