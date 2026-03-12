# ==========================================
# ФАЙЛ: bot/services/inviting_service.py
# ОПИСАНИЕ: Сервис инвайтинга на Hydrogram
# ==========================================

import asyncio
import logging
from typing import List, Dict, Callable, Optional, Tuple

from hydrogram import Client
from hydrogram.enums import ParseMode, ChatType
from hydrogram.errors import (
    FloodWait,
    UserAlreadyParticipant,
    InviteHashExpired,
    InviteHashInvalid,
    ChannelsTooMuch,
    UserPrivacyRestricted,
    ChatWriteForbidden,
    ChatAdminRequired,
    ChannelPrivate,
    PeerIdInvalid,
    UsernameNotOccupied,
    UsernameInvalid,
    InviteRequestSent,
    AuthKeyUnregistered,
    BadRequest, PeerFlood, )
from hydrogram.raw import functions as raw_functions
from hydrogram.raw.functions.channels import GetParticipant, JoinChannel
from hydrogram.types import Chat

logger = logging.getLogger(__name__)


def _is_spamblock_error(e: Exception) -> bool:
    """
    Возвращает True если исключение является спамблоком:
    - тип PeerFlood
    - текст ошибки содержит упоминание spambot или PEER_FLOOD
    """
    if isinstance(e, PeerFlood):
        return True
    err_text = str(e).lower()
    return any(k in err_text for k in ["peerflood", "peer_flood", "spambot", "spam bot", "t.me/spambot"])


class InvitingService:
    """Сервис для массовых действий с Hydrogram"""

    def __init__(self):
        self.active_clients: Dict[str, List[Client]] = {}

    def is_running(self, user_id: int) -> bool:
        from modules.task_manager import task_manager
        return task_manager.get_running_count(user_id) > 0

    def stop_task(self, user_id: int):
        pass

    async def _disconnect_all_clients(self, task_id: str):
        """Отключить все клиенты таска"""
        if task_id not in self.active_clients:
            return
        clients = self.active_clients.pop(task_id, [])
        for client in clients:
            try:
                if client and client.is_connected:
                    await client.disconnect()
            except Exception as e:
                logger.debug(f"Ошибка при отключении: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_link(self, link: str) -> Tuple[bool, str]:
        """
        Возвращает (is_private, normalized).
        is_private=True  → invite-ссылка (t.me/+... / t.me/joinchat/...)
        is_private=False → публичный username
        """
        original = link.strip()

        if any(s in original for s in ['t.me/+', 't.me/joinchat/', '/+']):
            return True, original

        if original.startswith('@'):
            return False, original.lstrip('@')

        if 't.me/' in original:
            try:
                after = original.split('t.me/', 1)[1]
                username = after.split('/')[0].split('?')[0]
                return False, username.lstrip('@')
            except IndexError:
                return False, original.lstrip('@')

        return False, original.lstrip('@')

    def _extract_invite_hash(self, link: str) -> str:
        """Извлечь hash из приватной invite-ссылки"""
        h = link.split('/')[-1].split('?')[0]
        if h.startswith('+'):
            h = h[1:]
        return h

    async def _verify_membership(self, client, chat, client_idx):
        try:
            peer = await client.resolve_peer(chat.id)
            is_channel = chat.type == ChatType.CHANNEL
            is_supergroup = chat.type == ChatType.SUPERGROUP

            if is_channel:
                try:
                    result = await client.invoke(
                        GetParticipant(channel=peer, participant=await client.resolve_peer("me"))
                    )
                    p = result.participant
                    if getattr(p, 'creator', False):
                        return True
                    admin_rights = getattr(p, 'admin_rights', None)
                    if admin_rights and getattr(admin_rights, 'post_messages', False):
                        return True
                    logger.info(f"ℹ️ [Клиент {client_idx + 1}] Подписчик канала — писать нельзя")
                    return False
                except Exception as e:
                    logger.warning(f"[Клиент {client_idx + 1}] Канал — ошибка проверки: {type(e).__name__}: {e}")
                    return False

            if is_supergroup:
                try:
                    result = await client.invoke(
                        GetParticipant(channel=peer, participant=await client.resolve_peer("me"))
                    )
                    p = result.participant
                    if getattr(p, 'creator', False):
                        return True
                    if getattr(p, 'admin_rights', None):
                        return True
                    banned = getattr(p, 'banned_rights', None)
                    if banned and getattr(banned, 'send_messages', False):
                        logger.warning(f"❌ [Клиент {client_idx + 1}] Запрещена отправка")
                        return False
                    return True
                except Exception as e:
                    # Если не участник — GetParticipant бросит ошибку
                    logger.warning(
                        f"[Клиент {client_idx + 1}] Супергруппа — не участник или ошибка: {type(e).__name__}: {e}")
                    return False  # ← было True, исправлено на False

            # Обычная группа
            logger.info(f"✅ [Клиент {client_idx + 1}] Обычная группа, считаем участником")
            return True

        except ChannelPrivate:
            logger.warning(f"❌ [Клиент {client_idx + 1}] ChannelPrivate")
            return False
        except ChatAdminRequired:
            logger.info(f"ℹ️ [Клиент {client_idx + 1}] Требуются права админа")
            return False
        except Exception as e:
            logger.error(f"⚠️ [Клиент {client_idx + 1}] Ошибка проверки: {type(e).__name__}: {e}")
            return False  # ← было True, безопаснее False

    async def _get_or_join_chat(
            self,
            client: Client,
            link: str,
            stats: Dict,
            client_idx: int,
    ) -> Tuple[Optional[Chat], bool]:
        """
        Получить чат и проверить участие.
        Возвращает: (chat, is_member)
        """
        max_retries = 2
        is_private, normalized = self._parse_link(link)

        logger.debug(f"Ссылка: '{link}' → private={is_private}, normalized='{normalized}'")

        for attempt in range(max_retries):
            try:
                # ── ПРИВАТНАЯ INVITE-ССЫЛКА ──────────────────────────────────
                if is_private:
                    invite_hash = self._extract_invite_hash(link)
                    try:
                        logger.info(f"[Клиент {client_idx + 1}] Вступаем по invite-ссылке: {link}")
                        result = await client.join_chat(link)
                        raw_chat = result.chats[0]
                        chat = await client.get_chat(raw_chat.id)
                        stats["total_joined"] += 1
                        logger.info(f"✅ [Клиент {client_idx + 1}] Вступили в приватный чат")
                        await asyncio.sleep(1)
                        is_member = await self._verify_membership(client, chat, client_idx)
                        return chat, is_member

                    except UserAlreadyParticipant:
                        logger.info(f"[Клиент {client_idx + 1}] Уже участник: {link}")
                        try:
                            chat = await client.get_chat(link)
                            is_member = await self._verify_membership(client, chat, client_idx)
                            return chat, is_member
                        except Exception as e:
                            logger.error(f"Не удалось получить чат после UserAlreadyParticipant: {e}")
                            return None, False

                    except (InviteHashExpired, InviteHashInvalid) as e:
                        stats["errors"].append(f"Недействительная ссылка: {link}")
                        logger.warning(f"❌ Недействительная ссылка: {link} — {e}")
                        return None, False

                    except InviteRequestSent:
                        stats["errors"].append(f"Требуется одобрение админа: {link}")
                        logger.warning(f"⏳ Требуется одобрение для: {link}")
                        return None, False

                # ── ПУБЛИЧНЫЙ ЧАТ ────────────────────────────────────────────
                else:
                    username = '@' + normalized
                    try:
                        chat = await client.get_chat(username)
                        logger.info(f"[Клиент {client_idx + 1}] Получили чат: {chat.title}")
                    except (UsernameNotOccupied, UsernameInvalid, PeerIdInvalid):
                        stats["errors"].append(f"Чат не существует: {link}")
                        logger.warning(f"❌ [Клиент {client_idx + 1}] Чат не найден: {normalized}")
                        return None, False
                    except BadRequest as e:
                        if any(p in str(e).lower() for p in ['username', 'no user has', 'not occupied']):
                            stats["errors"].append(f"Чат не найден: {link}")
                            logger.warning(f"❌ [Клиент {client_idx + 1}] Чат не найден: {normalized} — {e}")
                            return None, False
                        raise

                    # Проверяем текущее участие
                    is_already_member = await self._verify_membership(client, chat, client_idx)
                    if is_already_member:
                        logger.info(f"✅ [Клиент {client_idx + 1}] Уже участник: {link}")
                        return chat, True

                    # Вступаем
                    try:
                        logger.info(f"[Клиент {client_idx + 1}] Вступаем в публичный чат: {link}")
                        peer = await client.resolve_peer(username)
                        await client.invoke(JoinChannel(channel=peer))
                        stats["total_joined"] += 1
                        await asyncio.sleep(1)
                        is_member = await self._verify_membership(client, chat, client_idx)
                        if is_member:
                            logger.info(f"✅ [Клиент {client_idx + 1}] Вступили в чат: {link}")
                        else:
                            logger.warning(f"⚠️ [Клиент {client_idx + 1}] Вступили, но нет прав: {link}")
                        return chat, is_member

                    except UserAlreadyParticipant:
                        is_member = await self._verify_membership(client, chat, client_idx)
                        return chat, is_member

            except ChannelsTooMuch:
                stats["errors"].append("Достигнут лимит 500 чатов")
                logger.warning(f"❌ Лимит чатов превышен на клиенте {client_idx + 1}")
                return None, False

            except ChannelPrivate:
                stats["errors"].append(f"Чат приватный/бан: {link}")
                logger.warning(f"❌ Приватный чат/бан: {link}")
                return None, False

            except FloodWait as e:
                stats["errors"].append(f"FloodWait {e.value}s при вступлении в {link}")
                logger.warning(f"⏳ [Клиент {client_idx + 1}] FloodWait {e.value}s при {link}")
                await asyncio.sleep(e.value)
                return None, False

            except (ConnectionError, asyncio.TimeoutError, OSError) as e:
                logger.warning(f"⚠️ [Клиент {client_idx + 1}] Потеря соединения при {link}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return None, False

            except Exception as e:
                error_msg = str(e)
                if any(p in error_msg.lower() for p in ['no user has', 'username', 'not occupied']):
                    stats["errors"].append(f"Чат не найден: {link}")
                    logger.warning(f"❌ [Клиент {client_idx + 1}] Чат не найден: {normalized} — {e}")
                    return None, False

                stats["errors"].append(f"Ошибка с чатом {link}: {error_msg}")
                logger.error(f"❌ Неизвестная ошибка при {link}: {e}", exc_info=True)
                return None, False

        return None, False

    async def _send_message(
            self,
            client: Client,
            chat_id,
            message_text: str,
            photo_path: Optional[str],
    ):
        """Отправить сообщение или фото в чат."""
        if photo_path:
            await client.send_photo(
                chat_id=chat_id,
                photo=photo_path,
                caption=message_text,
                parse_mode=ParseMode.HTML,
            )
        else:
            await client.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # РАССЫЛКА ПО ССЫЛКАМ НА ЧАТЫ
    # ──────────────────────────────────────────────────────────────────────────

    async def send_to_chat_links(
            self,
            session_names: List[str],
            chat_links: List[str],
            message_text: str,
            photo_path: Optional[str],
            user_id: int,
            message_delay: int,
            cycle_delay: int,
            progress_callback: Callable,
            mode: str = "parallel",
            task=None,
    ) -> Dict:
        """Рассылка по чатам из списка ссылок."""
        from modules.session_manager import SessionManager
        session_mgr = SessionManager()

        stats = {
            "total_sent": 0,
            "total_failed": 0,
            "total_joined": 0,
            "cycles": 0,
            "accounts_used": len(session_names),
            "errors": [],
        }

        def _is_active() -> bool:
            if task is not None:
                return not task.stop_event.is_set()
            return True

        async def _check_pause():
            if task is not None and task.pause_event.is_set():
                await progress_callback("⏸ <b>Рассылка на паузе...</b>")
                while task.pause_event.is_set() and not task.stop_event.is_set():
                    await asyncio.sleep(1)

        try:
            await progress_callback("🔄 Подготовка к рассылке...")

            cycle = 0
            while _is_active():
                await _check_pause()
                if not _is_active():
                    break

                if task is not None:
                    message_delay = task.message_delay
                    cycle_delay   = task.cycle_delay
                    message_text  = task.message_text

                cycle += 1
                stats["cycles"] = cycle

                shuffled_links = chat_links.copy()

                async def process_client(idx: int, session_name: str):
                    if not _is_active():
                        return

                    client: Optional[Client] = None
                    max_connection_retries = 3

                    try:
                        for attempt in range(max_connection_retries):
                            try:
                                logger.info(f"🔄 [Клиент {idx + 1}] Подключение: {session_name}")
                                client = await session_mgr.get_hydrogram_client(session_name, user_id)
                                await client.connect()

                                me = await client.get_me()
                                if me is None:
                                    raise Exception("Session not authorized")

                                logger.info(f"✅ [Клиент {idx + 1}] Подключён как {me.first_name}")
                                break

                            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                                logger.warning(
                                    f"⚠️ [Клиент {idx + 1}] Ошибка подключения "
                                    f"(попытка {attempt + 1}/{max_connection_retries}): {e}"
                                )
                                if client and client.is_connected:
                                    try:
                                        await client.disconnect()
                                    except Exception:
                                        pass
                                    client = None

                                if attempt < max_connection_retries - 1:
                                    await asyncio.sleep(2)
                                else:
                                    raise Exception(
                                        f"Не удалось подключиться после {max_connection_retries} попыток"
                                    )

                        if not client or not client.is_connected:
                            logger.error(f"❌ [Клиент {idx + 1}] Нет подключения, пропускаем")
                            return

                        for link in shuffled_links:
                            if not _is_active():
                                break

                            await _check_pause()
                            if not _is_active():
                                break

                            try:
                                chat, is_member = await self._get_or_join_chat(
                                    client, link, stats, idx
                                )

                                if not chat:
                                    stats["total_failed"] += 1
                                    logger.warning(f"❌ [Клиент {idx + 1}] Не удалось получить чат: {link}")
                                    continue

                                if not is_member:
                                    stats["total_failed"] += 1
                                    stats["errors"].append(f"Нет прав на отправку: {link}")
                                    logger.warning(f"⚠️ [Клиент {idx + 1}] Нет прав писать в чат: {link}")
                                    continue

                                try:
                                    await self._send_message(client, chat.id, message_text, photo_path)
                                    stats["total_sent"] += 1
                                    logger.info(f"✅ [Клиент {idx + 1}] Отправлено в {link}")

                                except FloodWait as e:
                                    stats["errors"].append(f"FloodWait {e.value}s на аккаунте {idx + 1}")
                                    logger.warning(f"⏳ [Клиент {idx + 1}] FloodWait {e.value}s")
                                    await asyncio.sleep(e.value)
                                    continue

                                except ChatWriteForbidden:
                                    stats["total_failed"] += 1
                                    stats["errors"].append(f"Нет прав на отправку: {link}")
                                    continue

                                except Exception as send_err:
                                    error_text = str(send_err)
                                    if _is_spamblock_error(send_err):
                                        # ── Автоснятие спамблока ──
                                        stats["total_failed"] += 1
                                        stats["errors"].append(f"На аккаунте {idx + 1} спам-блок")
                                        from spamblock_service import spamblock_service
                                        _me = await client.get_me()
                                        _phone = getattr(_me, "phone_number", None)
                                        sb_result = await spamblock_service.handle_peer_flood(
                                            client, user_id, session_name, _phone, progress_callback
                                        )
                                        if sb_result.should_continue:
                                            try:
                                                await self._send_message(client, chat.id, message_text, photo_path)
                                                stats["total_sent"] += 1
                                                stats["total_failed"] -= 1
                                            except Exception as _retry_err:
                                                stats["errors"].append(f"Повтор после спамблока провалился: {_retry_err}")
                                        else:
                                            if sb_result.message:
                                                stats["errors"].append(sb_result.message)
                                            break
                                    elif "ALLOW_PAYMENT_REQUIRED" in error_text:
                                        stats["errors"].append(f"Требуется оплата: {link}")
                                        stats["total_failed"] += 1
                                        logger.warning(f"❌ [Клиент {idx + 1}] Оплата требуется: {link}")
                                        continue
                                    else:
                                        stats["errors"].append(f"Ошибка отправки в {link}: {send_err}")
                                        stats["total_failed"] += 1
                                        logger.warning(f"❌ [Клиент {idx + 1}] Ошибка отправки в {link}: {send_err}")
                                        continue

                                if task is not None:
                                    task.stats.update(
                                        sent=stats["total_sent"],
                                        failed=stats["total_failed"],
                                        joined=stats["total_joined"],
                                        cycles=stats["cycles"],
                                        current_account=session_name,
                                    )

                                await progress_callback(
                                    f"📤 Отправлено: <b>{stats['total_sent']}</b>\n"
                                    f"❌ Ошибок: <b>{stats['total_failed']}</b>\n"
                                    f"➕ Вступлений: <b>{stats['total_joined']}</b>\n"
                                    f"🔄 Цикл: <b>{cycle}</b>\n"
                                    f"📱 Аккаунт: <b>{idx + 1}/{len(session_names)}</b>\n"
                                    f"✅ Последний: <code>{link}</code>\n\n"
                                    f"<i>Рассылка активна. Нажмите «Стоп» для отмены</i>"
                                )

                                await asyncio.sleep(message_delay)

                            except (ConnectionError, asyncio.TimeoutError, OSError) as e:
                                logger.warning(f"⚠️ [Клиент {idx + 1}] Потеря соединения: {e}")
                                try:
                                    if client.is_connected:
                                        await client.disconnect()
                                    await asyncio.sleep(2)
                                    client = await session_mgr.get_hydrogram_client(session_name, user_id)
                                    await client.connect()
                                    logger.info(f"✅ [Клиент {idx + 1}] Переподключён")
                                    continue
                                except Exception as reconnect_err:
                                    logger.error(f"❌ [Клиент {idx + 1}] Переподключение не удалось: {reconnect_err}")
                                    stats["total_failed"] += 1
                                    break

                            except Exception as e:
                                stats["total_failed"] += 1
                                stats["errors"].append(f"Ошибка обработки {link}: {str(e)}")

                    except Exception as e:
                        logger.error(f"❌ [Клиент {idx + 1}] Критическая ошибка: {e}", exc_info=True)
                        stats["errors"].append(f"Критическая ошибка аккаунта {idx + 1}: {str(e)}")

                    finally:
                        if client:
                            try:
                                if client.is_connected:
                                    await client.disconnect()
                                    logger.info(f"🔌 [Клиент {idx + 1}] Отключён")
                            except Exception as e:
                                logger.debug(f"Ошибка отключения клиента {idx + 1}: {e}")

                # ── Запуск параллельно / последовательно ──
                if mode == "parallel":
                    semaphore = asyncio.Semaphore(3)

                    async def bounded_task(i: int, name: str):
                        async with semaphore:
                            await process_client(i, name)

                    await asyncio.gather(*[bounded_task(i, n) for i, n in enumerate(session_names)])
                else:
                    for idx, session_name in enumerate(session_names):
                        if not _is_active():
                            break
                        await process_client(idx, session_name)

                if _is_active():
                    await _check_pause()
                    if _is_active():
                        await progress_callback(
                            f"⏸ Пауза <b>{cycle_delay}с</b> перед следующим циклом...\n\n"
                            f"📊 Текущая статистика:\n"
                            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
                            f"❌ Ошибок: <b>{stats['total_failed']}</b>\n"
                            f"➕ Вступлений: <b>{stats['total_joined']}</b>\n"
                            f"🔄 Циклов: <b>{cycle}</b>\n\n"
                            f"<i>Нажмите «Стоп» для отмены</i>"
                        )
                        await asyncio.sleep(cycle_delay)

        except Exception as e:
            logger.error(f"💥 Критическая ошибка в рассылке: {e}", exc_info=True)
            stats["errors"].append(f"Критическая ошибка: {str(e)}")

        return stats

    # ──────────────────────────────────────────────────────────────────────────
    # РАССЫЛКА ПО ДИАЛОГАМ
    # ──────────────────────────────────────────────────────────────────────────

    async def send_to_dialogs(
            self,
            sessions: List[str],
            message_text: str,
            photo_path: Optional[str],
            user_id: int,
            message_delay: int,
            progress_callback: Callable,
            task=None,
            mode: str = "sequential",
    ) -> Dict:
        """Рассылка по существующим диалогам."""
        stats = {
            "total_sent": 0,
            "total_failed": 0,
            "errors": [],
        }

        from modules.session_manager import SessionManager
        session_mgr = SessionManager()

        total_sessions = len(sessions)

        def _is_active() -> bool:
            if task is not None:
                return not task.stop_event.is_set()
            return True

        async def _check_pause():
            if task is not None and task.pause_event.is_set():
                await progress_callback("⏸ <b>Рассылка на паузе...</b>")
                while task.pause_event.is_set() and not task.stop_event.is_set():
                    await asyncio.sleep(1)

        async def process_account(idx: int, session_name: str):
            if not _is_active():
                return

            await _check_pause()
            if not _is_active():
                return

            cur_delay = task.message_delay if task else message_delay
            cur_text  = task.message_text  if task else message_text

            client: Optional[Client] = None
            try:
                await progress_callback(
                    f"📤 <b>Аккаунт {idx + 1}/{total_sessions}</b>: {session_name}\n"
                    f"✅ Отправлено: {stats['total_sent']} | ❌ Ошибок: {stats['total_failed']}\n"
                    f"<i>Подключение...</i>"
                )

                client = await session_mgr.get_hydrogram_client(session_name, user_id)
                await client.connect()

                me = await client.get_me()
                if me is None:
                    stats["errors"].append(f"{session_name}: Не авторизован")
                    return

                async for dialog in client.get_dialogs():
                    if not _is_active():
                        break

                    await _check_pause()
                    if not _is_active():
                        break

                    if task is not None:
                        cur_delay = task.message_delay
                        cur_text  = task.message_text

                    chat = dialog.chat

                    # Пропускаем каналы (broadcast) и ботов
                    if chat.type == ChatType.CHANNEL:
                        continue
                    if chat.type == ChatType.BOT:
                        continue

                    try:
                        await self._send_message(client, chat.id, cur_text, photo_path)

                        stats["total_sent"] += 1

                        if task is not None:
                            task.stats.update(
                                sent=stats["total_sent"],
                                failed=stats["total_failed"],
                                current_account=session_name,
                            )

                        await progress_callback(
                            f"📤 <b>Аккаунт {idx + 1}/{total_sessions}</b>\n"
                            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
                            f"❌ Ошибок: <b>{stats['total_failed']}</b>\n"
                            f"📨 Текущий: {chat.title or chat.first_name}\n"
                            f"<i>Рассылка активна...</i>"
                        )

                        await asyncio.sleep(cur_delay)

                    except FloodWait as e:
                        logger.warning(f"FloodWait {e.value}s на {session_name}")
                        stats["errors"].append(f"{session_name}: FloodWait {e.value}s")
                        await asyncio.sleep(e.value)
                        break

                    except Exception as e:
                        stats["total_failed"] += 1
                        if _is_spamblock_error(e):
                            # ── Автоснятие спамблока ──
                            from spamblock_service import spamblock_service
                            try:
                                _me = await client.get_me()
                                _phone = getattr(_me, "phone_number", None)
                            except Exception:
                                _phone = None
                            sb_result = await spamblock_service.handle_peer_flood(
                                client, user_id, session_name, _phone, progress_callback
                            )
                            if sb_result.should_continue:
                                stats["total_failed"] -= 1
                                continue
                            else:
                                if sb_result.message:
                                    stats["errors"].append(sb_result.message)
                                break
                        else:
                            stats["errors"].append(f"{session_name}: {str(e)}")
                            continue

            except Exception as global_e:
                stats["errors"].append(f"{session_name} Init Error: {str(global_e)}")

            finally:
                if client:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass

        # ── Запуск ──
        if mode == "parallel":
            semaphore = asyncio.Semaphore(3)

            async def bounded(i: int, name: str):
                async with semaphore:
                    await process_account(i, name)

            await asyncio.gather(*[bounded(i, s) for i, s in enumerate(sessions)])
        else:
            for idx, session_name in enumerate(sessions):
                if not _is_active():
                    break
                await process_account(idx, session_name)
                if idx < total_sessions - 1:
                    await asyncio.sleep(5)

        return stats

    # ──────────────────────────────────────────────────────────────────────────
    # РАССЫЛКА ПО КОНТАКТАМ
    # ──────────────────────────────────────────────────────────────────────────

    async def send_to_contacts(
            self,
            sessions: List[str],
            message_text: str,
            photo_path: Optional[str],
            user_id: int,
            message_delay: int,
            progress_callback: Callable,
            task=None,
            mode: str = "sequential",
    ) -> Dict:
        """Рассылка по контактам всех аккаунтов."""
        stats = {
            "total_sent": 0,
            "total_failed": 0,
            "errors": [],
        }

        from modules.session_manager import SessionManager
        session_mgr = SessionManager()

        def _is_active() -> bool:
            if task is not None:
                return not task.stop_event.is_set()
            return True

        async def _check_pause():
            if task is not None and task.pause_event.is_set():
                await progress_callback("⏸ <b>Рассылка на паузе...</b>")
                while task.pause_event.is_set() and not task.stop_event.is_set():
                    await asyncio.sleep(1)

        async def process_account(idx: int, session_name: str):
            if not _is_active():
                return

            await _check_pause()
            if not _is_active():
                return

            cur_delay = task.message_delay if task else message_delay
            cur_text  = task.message_text  if task else message_text

            client: Optional[Client] = None
            try:
                logger.info(f"📱 [Аккаунт {idx + 1}/{len(sessions)}] Подключение к {session_name}")

                client = await session_mgr.get_hydrogram_client(session_name, user_id)
                await client.connect()

                me = await client.get_me()
                if me is None:
                    stats["errors"].append(f"{session_name}: Не авторизован")
                    return

                logger.info(f"✅ [Аккаунт {idx + 1}] Подключён, получаем контакты...")

                try:
                    result = await client.invoke(
                        raw_functions.contacts.GetContacts(hash=0)
                    )
                    contacts = result.users
                    logger.info(f"📋 [Аккаунт {idx + 1}] Найдено контактов: {len(contacts)}")
                except Exception as e:
                    logger.error(f"❌ [Аккаунт {idx + 1}] Ошибка получения контактов: {e}")
                    stats["total_failed"] += 1
                    stats["errors"].append(f"Аккаунт {idx + 1}: {str(e)}")
                    return

                contact_count = 0
                for contact in contacts:
                    if not _is_active():
                        break

                    await _check_pause()
                    if not _is_active():
                        break

                    if task is not None:
                        cur_delay = task.message_delay
                        cur_text  = task.message_text

                    if getattr(contact, 'bot', False) or getattr(contact, 'deleted', False):
                        continue

                    try:
                        contact_count += 1
                        await self._send_message(client, contact.id, cur_text, photo_path)

                        stats["total_sent"] += 1

                        if task is not None:
                            task.stats.update(
                                sent=stats["total_sent"],
                                failed=stats["total_failed"],
                                current_account=session_name,
                            )

                        await progress_callback(
                            f"📤 <b>Аккаунт {idx + 1}/{len(sessions)}</b>\n"
                            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
                            f"❌ Ошибок: <b>{stats['total_failed']}</b>\n"
                            f"📊 Текущий аккаунт: {contact_count} контактов\n\n"
                            f"<i>Рассылка активна...</i>"
                        )

                        await asyncio.sleep(cur_delay)

                    except FloodWait as e:
                        logger.warning(f"⏳ [Аккаунт {idx + 1}] FloodWait {e.value}s")
                        stats["total_failed"] += 1
                        stats["errors"].append(f"Аккаунт {idx + 1}: FloodWait {e.value}s")
                        await asyncio.sleep(e.value)
                        break

                    except UserPrivacyRestricted:
                        stats["total_failed"] += 1
                        stats["errors"].append(f"Аккаунт {idx + 1}: Privacy restricted — {contact.id}")
                        continue

                    except PeerFlood:
                        stats["total_failed"] += 1
                        # ── Автоснятие спамблока ──
                        from spamblock_service import spamblock_service
                        try:
                            _me = await client.get_me()
                            _phone = getattr(_me, "phone_number", None)
                        except Exception:
                            _phone = None
                        sb_result = await spamblock_service.handle_peer_flood(
                            client, user_id, session_name, _phone, progress_callback
                        )
                        if sb_result.should_continue:
                            stats["total_failed"] -= 1
                            continue
                        else:
                            if sb_result.message:
                                stats["errors"].append(sb_result.message)
                            break

                    except Exception as e:
                        stats["total_failed"] += 1
                        if _is_spamblock_error(e):
                            from spamblock_service import spamblock_service
                            try:
                                _me = await client.get_me()
                                _phone = getattr(_me, "phone_number", None)
                            except Exception:
                                _phone = None
                            sb_result = await spamblock_service.handle_peer_flood(
                                client, user_id, session_name, _phone, progress_callback
                            )
                            if sb_result.should_continue:
                                stats["total_failed"] -= 1
                                continue
                            else:
                                if sb_result.message:
                                    stats["errors"].append(sb_result.message)
                                break
                        else:
                            stats["errors"].append(f"Аккаунт {idx + 1}: {str(e)}")
                            continue

                logger.info(f"✅ [Аккаунт {idx + 1}] Завершён. Отправлено: {contact_count}")

            except Exception as e:
                logger.error(f"❌ [Аккаунт {idx + 1}] Критическая ошибка: {e}", exc_info=True)
                stats["total_failed"] += 1
                stats["errors"].append(f"Аккаунт {idx + 1}: {str(e)}")

            finally:
                if client:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                            logger.info(f"🔌 [Аккаунт {idx + 1}] Отключён")
                    except Exception as e:
                        logger.debug(f"Ошибка отключения аккаунта {idx + 1}: {e}")

        # ── Запуск ──
        if mode == "parallel":
            semaphore = asyncio.Semaphore(3)

            async def bounded(i: int, name: str):
                async with semaphore:
                    await process_account(i, name)

            await asyncio.gather(*[bounded(i, s) for i, s in enumerate(sessions)])
        else:
            for idx, session_name in enumerate(sessions):
                if not _is_active():
                    break
                await process_account(idx, session_name)
                if idx < len(sessions) - 1:
                    await asyncio.sleep(2)

        logger.info(
            f"🏁 Рассылка по контактам завершена. "
            f"Отправлено: {stats['total_sent']}, Ошибок: {stats['total_failed']}"
        )
        return stats

    # ──────────────────────────────────────────────────────────────────────────
    # РАССЫЛКА ОДНОМУ ПОЛЬЗОВАТЕЛЮ С НЕСКОЛЬКИХ АККАУНТОВ
    # ──────────────────────────────────────────────────────────────────────────

    async def send_to_one_user(
            self,
            session_names: List[str],
            target: str,
            message_text: str,
            photo_path: Optional[str],
            user_id: int,
            message_delay: int,
            progress_callback: Callable,
            task=None,
    ) -> Dict:
        """Отправка сообщения одному пользователю со всех аккаунтов."""
        stats = {
            "total_sent": 0,
            "total_failed": 0,
            "errors": [],
        }

        from modules.session_manager import SessionManager
        session_mgr = SessionManager()

        def _is_active() -> bool:
            if task is not None:
                return not task.stop_event.is_set()
            return True

        async def _check_pause():
            if task is not None and task.pause_event.is_set():
                await progress_callback("⏸ <b>Рассылка на паузе...</b>")
                while task.pause_event.is_set() and not task.stop_event.is_set():
                    await asyncio.sleep(1)

        try:
            for idx, session_name in enumerate(session_names):
                if not _is_active():
                    break

                await _check_pause()
                if not _is_active():
                    break

                if task is not None:
                    message_delay = task.message_delay
                    message_text  = task.message_text

                client: Optional[Client] = None
                try:
                    client = await session_mgr.get_hydrogram_client(session_name, user_id)
                    await client.connect()

                    me = await client.get_me()
                    if me is None:
                        stats["total_failed"] += 1
                        stats["errors"].append(f"Аккаунт {idx + 1}: Не авторизован")
                        continue

                    await self._send_message(client, target, message_text, photo_path)
                    stats["total_sent"] += 1

                    if task is not None:
                        task.stats.update(
                            sent=stats["total_sent"],
                            failed=stats["total_failed"],
                            current_account=f"аккаунт {idx + 1}",
                        )

                    await progress_callback(
                        f"✅ Отправлено с аккаунта {idx + 1}/{len(session_names)}\n"
                        f"📊 Всего отправлено: <b>{stats['total_sent']}</b>"
                    )

                    await asyncio.sleep(message_delay)

                except FloodWait as e:
                    stats["total_failed"] += 1
                    stats["errors"].append(f"Аккаунт {idx + 1}: FloodWait {e.value}s")
                    logger.warning(f"⏳ [Аккаунт {idx + 1}] FloodWait {e.value}s")
                    await asyncio.sleep(e.value)

                except PeerFlood:
                    stats["total_failed"] += 1
                    from spamblock_service import spamblock_service
                    _phone = getattr(me, "phone_number", None) if me else None
                    sb_result = await spamblock_service.handle_peer_flood(
                        client, user_id, session_name, _phone, progress_callback
                    )
                    if sb_result.should_continue:
                        try:
                            await self._send_message(client, target, message_text, photo_path)
                            stats["total_sent"] += 1
                            stats["total_failed"] -= 1
                        except Exception as _re:
                            stats["errors"].append(f"Повтор после спамблока: {_re}")
                    else:
                        if sb_result.message:
                            stats["errors"].append(sb_result.message)

                except Exception as e:
                    stats["total_failed"] += 1
                    stats["errors"].append(f"Аккаунт {idx + 1}: {str(e)}")
                    logger.error(f"Ошибка отправки аккаунтом {idx + 1}: {e}")

                finally:
                    if client:
                        try:
                            if client.is_connected:
                                await client.disconnect()
                        except Exception:
                            pass

        except Exception as e:
            logger.error(f"Критическая ошибка send_to_one_user: {e}", exc_info=True)
            stats["errors"].append(f"Критическая ошибка: {str(e)}")

        return stats

    # ──────────────────────────────────────────────────────────────────────────
    # РАССЫЛКА ПО СПИСКУ ЮЗЕРНЕЙМОВ
    # ──────────────────────────────────────────────────────────────────────────

    async def send_to_usernames(
            self,
            sessions: List[str],
            usernames: List[str],
            message_text: str,
            photo_path: Optional[str],
            user_id: int,
            message_delay: int,
            progress_callback: Callable,
            task=None,
            mode: str = "sequential",
    ) -> Dict:
        """Рассылка по списку юзернеймов пользователей."""
        stats = {
            "total_sent": 0,
            "total_failed": 0,
            "errors": [],
        }

        from modules.session_manager import SessionManager
        session_mgr = SessionManager()

        total_sessions = len(sessions)

        def _is_active() -> bool:
            if task is not None:
                return not task.stop_event.is_set()
            return True

        async def _check_pause():
            if task is not None and task.pause_event.is_set():
                await progress_callback("⏸ <b>Рассылка на паузе...</b>")
                while task.pause_event.is_set() and not task.stop_event.is_set():
                    await asyncio.sleep(1)

        # Распределяем юзернеймы между аккаунтами
        def chunks(lst, n):
            k, m = divmod(len(lst), n)
            return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]

        num_sessions = len(sessions)
        username_chunks = chunks(usernames, num_sessions) if num_sessions > 0 else [usernames]

        async def process_account(idx: int, session_name: str):
            if not _is_active():
                return

            await _check_pause()
            if not _is_active():
                return

            my_usernames = username_chunks[idx] if idx < len(username_chunks) else []
            if not my_usernames:
                return

            cur_delay = task.message_delay if task else message_delay
            cur_text = task.message_text if task else message_text

            client: Optional[Client] = None
            account_phone: Optional[str] = None
            try:
                await progress_callback(
                    f"📤 <b>Аккаунт {idx + 1}/{total_sessions}</b>: {session_name}\n"
                    f"✅ Отправлено: {stats['total_sent']} | ❌ Ошибок: {stats['total_failed']}\n"
                    f"<i>Подключение...</i>"
                )

                client = await session_mgr.get_hydrogram_client(session_name, user_id)
                await client.connect()

                me = await client.get_me()
                if me is None:
                    stats["errors"].append(f"{session_name}: Не авторизован")
                    return
                account_phone = getattr(me, "phone_number", None)

                for username in my_usernames:
                    if not _is_active():
                        break

                    await _check_pause()
                    if not _is_active():
                        break

                    if task is not None:
                        cur_delay = task.message_delay
                        cur_text = task.message_text

                    target = username.strip()
                    if not target.startswith('@'):
                        target = '@' + target

                    try:
                        await self._send_message(client, target, cur_text, photo_path)
                        stats["total_sent"] += 1

                        if task is not None:
                            task.stats.update(
                                sent=stats["total_sent"],
                                failed=stats["total_failed"],
                                current_account=session_name,
                            )

                        await progress_callback(
                            f"📤 <b>Аккаунт {idx + 1}/{total_sessions}</b>\n"
                            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
                            f"❌ Ошибок: <b>{stats['total_failed']}</b>\n"
                            f"📨 Текущий: <code>{target}</code>\n"
                            f"<i>Рассылка активна...</i>"
                        )

                        await asyncio.sleep(cur_delay)

                    except FloodWait as e:
                        logger.warning(f"FloodWait {e.value}s на {session_name}")
                        stats["errors"].append(f"{session_name}: FloodWait {e.value}s")
                        await asyncio.sleep(e.value)
                        try:
                            await self._send_message(client, target, cur_text, photo_path)
                            stats["total_sent"] += 1
                        except Exception:
                            stats["total_failed"] += 1
                            stats["errors"].append(f"{session_name}: не удалось отправить {target} после FloodWait")

                    except UserPrivacyRestricted:
                        stats["total_failed"] += 1
                        stats["errors"].append(f"Приватность: {target}")
                        continue

                    except (UsernameNotOccupied, UsernameInvalid, PeerIdInvalid):
                        stats["total_failed"] += 1
                        stats["errors"].append(f"Пользователь не найден: {target}")
                        continue

                    except PeerFlood:
                        stats["total_failed"] += 1
                        from spamblock_service import spamblock_service
                        sb_result = await spamblock_service.handle_peer_flood(
                            client, user_id, session_name, account_phone, progress_callback
                        )
                        if sb_result.should_continue:
                            try:
                                await self._send_message(client, target, cur_text, photo_path)
                                stats["total_sent"] += 1
                                stats["total_failed"] -= 1
                            except Exception as _re:
                                stats["errors"].append(f"Повтор после спамблока: {_re}")
                        else:
                            if sb_result.message:
                                stats["errors"].append(sb_result.message)
                            break

                    except AuthKeyUnregistered:
                        stats["errors"].append(f"{session_name}: Сессия недействительна")
                        break

                    except Exception as e:
                        if _is_spamblock_error(e):
                            stats["total_failed"] += 1
                            from spamblock_service import spamblock_service
                            sb_result = await spamblock_service.handle_peer_flood(
                                client, user_id, session_name, account_phone, progress_callback
                            )
                            if sb_result.should_continue:
                                try:
                                    await self._send_message(client, target, cur_text, photo_path)
                                    stats["total_sent"] += 1
                                    stats["total_failed"] -= 1
                                except Exception as _re:
                                    stats["errors"].append(f"Повтор после спамблока: {_re}")
                            else:
                                if sb_result.message:
                                    stats["errors"].append(sb_result.message)
                                break
                        else:
                            stats["total_failed"] += 1
                            stats["errors"].append(f"{target}: {str(e)}")
                            continue

            except Exception as global_e:
                stats["errors"].append(f"{session_name} Init Error: {str(global_e)}")

            finally:
                if client:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass

        # ── Запуск ──
        if mode == "parallel":
            semaphore = asyncio.Semaphore(3)

            async def bounded(i: int, name: str):
                async with semaphore:
                    await process_account(i, name)

            await asyncio.gather(*[bounded(i, s) for i, s in enumerate(sessions)])
        else:
            for idx, session_name in enumerate(sessions):
                if not _is_active():
                    break
                await process_account(idx, session_name)
                if idx < total_sessions - 1:
                    await asyncio.sleep(5)

        return stats