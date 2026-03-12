# ==========================================
# ФАЙЛ: SMM.py
# ОПИСАНИЕ: SMM-действия через Hydrogram + SessionManager
#   - Вступление в канал/чат
#   - Просмотр поста
#   - Реакция на пост
#   - Голосование в опросе
#   - Старт бота с реферальной ссылкой
#   - Ответ на сообщение
#   - Клик по инлайн-кнопке
# ==========================================

import asyncio
import re
import logging
from typing import List, Dict, Optional

from hydrogram import Client
from hydrogram.errors import (
    FloodWait,
    UserAlreadyParticipant,
    ChannelsTooMuch,
    UsernameNotOccupied,
    BadRequest,
    AuthKeyUnregistered,
    UserIsBlocked,
)
from hydrogram.raw.functions.channels import JoinChannel
from hydrogram.raw.functions.messages import (
    SendReaction,
    SendVote,
    ImportChatInvite,
    GetMessages,
)
from hydrogram.raw.functions.account import GetPassword
from hydrogram.raw import types as raw_types

import random
from modules.session_manager import SessionManager
from config import bot

logger = logging.getLogger(__name__)

session_manager = SessionManager()


# ══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════

def _parse_channel_link(link: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Разобрать ссылку на пост/канал.
    Возвращает: (channel_part, message_id, invite_hash)
    """
    # Приватная инвайт-ссылка с постом: t.me/+HASH  или t.me/joinchat/HASH
    m = re.search(r't\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', link)
    if m:
        return None, None, m.group(1)

    # Пост в приватном канале: t.me/c/1234567890/42
    m = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if m:
        return m.group(1), int(m.group(2)), None

    # Пост в публичном канале: t.me/username/42
    m = re.search(r't\.me/([\w\d_]+)/(\d+)', link)
    if m:
        return m.group(1), int(m.group(2)), None

    # Просто канал без поста: t.me/username
    m = re.search(r't\.me/([\w\d_]+)', link)
    if m:
        return m.group(1), None, None

    return None, None, None


async def _resolve_chat(client: Client, channel_part: str):
    """Получить объект чата по username или числовому ID."""
    if channel_part.isdigit():
        return await client.get_chat(int(f"-100{channel_part}"))
    return await client.get_chat(channel_part)


async def _join_by_invite(client: Client, invite_hash: str):
    """Вступить в чат по инвайт-хэшу через Raw API."""
    await client.invoke(ImportChatInvite(hash=invite_hash))


# ══════════════════════════════════════════════════════════════
# ОСНОВНОЙ КЛАСС
# ══════════════════════════════════════════════════════════════

class TelegramActions:
    """SMM-действия через Hydrogram + SessionManager."""

    def __init__(self):
        self.session_manager = session_manager
        self.bot = bot
        self.max_workers = 5

    # ──────────────────────────────────────────────────────────
    # ОТПРАВКА СТАТИСТИКИ
    # ──────────────────────────────────────────────────────────

    async def send_stats_to_user(self, user_id: int, text: str):
        """Отправить статистику пользователю."""
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки статистики user={user_id}: {e}")

    def _format_stats_message(
        self,
        title: str,
        link: str,
        stats: Dict,
        additional_info: str = ""
    ) -> str:
        """Форматировать HTML-сообщение со статистикой."""
        success = stats.get("success", 0)
        errors  = stats.get("errors", 0)
        total   = stats.get("total", 0)

        error_counts: Dict[str, int] = {}
        for r in stats.get("results", []):
            if not r.get("success") and r.get("error"):
                err = r["error"]
                error_counts[err] = error_counts.get(err, 0) + 1

        msg = f"<b>📊 {title}</b>\n"
        msg += f"<b>Ссылка:</b> <code>{link}</code>\n"
        if additional_info:
            msg += f"{additional_info}\n"
        msg += f"\n<b>Всего аккаунтов:</b> {total}\n"
        msg += f"<b>✅ Успешно:</b> {success}\n"
        msg += f"<b>❌ Ошибок:</b> {errors}\n"

        if error_counts:
            lines = "\n".join(f"• {e} (x{c})" for e, c in error_counts.items())
            msg += f"\n<blockquote expandable><b>Детали ошибок:</b>\n{lines}</blockquote>"

        return msg

    # ──────────────────────────────────────────────────────────
    # ЯДРО: ОБРАБОТКА ОДНОГО АККАУНТА
    # ──────────────────────────────────────────────────────────

    async def _process_account(
        self,
        session_file: str,
        user_id: int,
        action_func,
        delay: float,
        **kwargs
    ) -> Dict:
        """
        Подключить аккаунт, выполнить action_func(client, **kwargs),
        отключить. Возвращает {"success": bool, "error": str|None}.
        """
        await asyncio.sleep(delay)

        session_name = session_file  # уже с .session или без — _clean_name разберётся
        client: Optional[Client] = None

        try:
            client = await self.session_manager.get_hydrogram_client(session_name, user_id)
            await client.connect()

            result = await action_func(client, **kwargs)
            return result

        except FloodWait as e:
            wait_min = e.value // 60 + 1
            logger.warning(f"{session_name} → FloodWait {wait_min} мин")
            return {"success": False, "error": f"flood_wait_{e.value}s"}

        except AuthKeyUnregistered:
            logger.warning(f"{session_name} → не авторизован")
            return {"success": False, "error": "not_authorized"}

        except Exception as e:
            logger.error(f"{session_name} → ошибка: {str(e)[:120]}")
            return {"success": False, "error": str(e)[:120]}

        finally:
            if client:
                try:
                    await asyncio.sleep(0.3)
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────
    # ЯДРО: ПАРАЛЛЕЛЬНЫЙ ЗАПУСК
    # ──────────────────────────────────────────────────────────

    async def _run_parallel_action(
        self,
        session_files: List[str],
        user_id: int,
        action_func,
        delay_between: float,
        **kwargs
    ) -> Dict:
        """Запустить action_func параллельно для всех аккаунтов с семафором."""
        total = len(session_files)
        logger.info(f"🚀 Запуск действия для {total} аккаунтов (max_workers={self.max_workers})")

        semaphore = asyncio.Semaphore(self.max_workers)

        async def bounded(i: int, sf: str):
            async with semaphore:
                return await self._process_account(
                    sf, user_id, action_func, i * delay_between, **kwargs
                )

        results = await asyncio.gather(*[bounded(i, sf) for i, sf in enumerate(session_files)])

        success = sum(1 for r in results if r.get("success"))
        return {
            "success": success,
            "total": total,
            "errors": total - success,
            "success_rate": round(success / total * 100, 1) if total else 0,
            "results": list(results),
        }

    # ══════════════════════════════════════════════════════════
    # 1. ВСТУПЛЕНИЕ В КАНАЛ
    # ══════════════════════════════════════════════════════════

    async def _join_channel_action(self, client: Client, channel_link: str) -> Dict:
        try:
            if '/+' in channel_link or '/joinchat/' in channel_link:
                # Приватный канал
                if '/+' in channel_link:
                    invite_hash = channel_link.split('/+')[1].split('?')[0]
                else:
                    invite_hash = channel_link.split('/joinchat/')[1].split('?')[0]
                await _join_by_invite(client, invite_hash)
            else:
                # Публичный канал — через Raw API
                channel_part, _, _ = _parse_channel_link(channel_link)
                peer = await client.resolve_peer(channel_part or channel_link)
                await client.invoke(JoinChannel(channel=peer))

            return {"success": True, "error": None}

        except UserAlreadyParticipant:
            return {"success": True, "error": "already_in"}
        except ChannelsTooMuch:
            return {"success": False, "error": "channels_limit"}
        except UsernameNotOccupied:
            return {"success": False, "error": "not_found"}

    async def join_channel(
        self,
        session_files: List[str],
        user_id: int,
        channel_link: str,
        delay_between: float = 2.0
    ) -> Dict:
        """Вступить в канал всеми аккаунтами."""
        stats = await self._run_parallel_action(
            session_files, user_id, self._join_channel_action,
            delay_between, channel_link=channel_link
        )
        already_in = sum(1 for r in stats["results"] if r.get("error") == "already_in")
        additional = f"<b>ℹ️ Уже были в канале:</b> {already_in}" if already_in else ""
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Вступление в канал", channel_link, stats, additional
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 2. ВСТУПЛЕНИЕ В ЧАТ (алиас с другим заголовком)
    # ══════════════════════════════════════════════════════════

    async def _join_chat_action(self, client: Client, chat_link: str) -> Dict:
        try:
            if '/+' in chat_link or '/joinchat/' in chat_link:
                if '/+' in chat_link:
                    invite_hash = chat_link.split('/+')[1].split('?')[0]
                else:
                    invite_hash = chat_link.split('/joinchat/')[1].split('?')[0]
                await _join_by_invite(client, invite_hash)
            else:
                channel_part, _, _ = _parse_channel_link(chat_link)
                peer = await client.resolve_peer(channel_part or chat_link)
                await client.invoke(JoinChannel(channel=peer))

            return {"success": True, "error": None}

        except UserAlreadyParticipant:
            return {"success": True, "error": "already_in"}

    async def join_chat(
        self,
        session_files: List[str],
        user_id: int,
        chat_link: str,
        delay_between: float = 2.0
    ) -> Dict:
        """Вступить в чат всеми аккаунтами."""
        stats = await self._run_parallel_action(
            session_files, user_id, self._join_chat_action,
            delay_between, chat_link=chat_link
        )
        already_in = sum(1 for r in stats["results"] if r.get("error") == "already_in")
        additional = f"<b>ℹ️ Уже были в чате:</b> {already_in}" if already_in else ""
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Вступление в чат", chat_link, stats, additional
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 3. ПРОСМОТР ПОСТА
    # ══════════════════════════════════════════════════════════

    async def _view_post_action(
        self,
        client: Client,
        channel_part: str,
        message_id: int
    ) -> Dict:
        chat = await _resolve_chat(client, channel_part)
        await client.get_messages(chat.id, message_ids=message_id)
        return {"success": True, "error": None}

    async def view_post(
        self,
        session_files: List[str],
        user_id: int,
        post_link: str,
        delay_between: float = 1.0
    ) -> Dict:
        """Накрутить просмотры поста."""
        channel_part, message_id, _ = _parse_channel_link(post_link)
        if not channel_part or not message_id:
            logger.error(f"❌ Неверный формат ссылки: {post_link}")
            return {"success": 0, "total": 0, "errors": 0}

        stats = await self._run_parallel_action(
            session_files, user_id, self._view_post_action,
            delay_between, channel_part=channel_part, message_id=message_id
        )
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Просмотр поста", post_link, stats
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 4. РЕАКЦИЯ НА ПОСТ
    # ══════════════════════════════════════════════════════════

    async def _react_to_post_action(
        self,
        client: Client,
        channel_part: str,
        message_id: int,
        reaction: str
    ) -> Dict:
        peer = await client.resolve_peer(
            int(f"-100{channel_part}") if channel_part.isdigit() else channel_part
        )
        await client.invoke(
            SendReaction(
                peer=peer,
                msg_id=message_id,
                reaction=str(reaction),
            )
        )
        return {"success": True, "error": None}

    async def react_to_post(
        self,
        session_files: List[str],
        user_id: int,
        post_link: str,
        reaction: str = "👍",
        delay_between: float = 1.0
    ) -> Dict:
        """Поставить реакцию на пост."""
        channel_part, message_id, _ = _parse_channel_link(post_link)
        if not channel_part or not message_id:
            logger.error(f"❌ Неверный формат ссылки: {post_link}")
            return {"success": 0, "total": 0, "errors": 0}

        stats = await self._run_parallel_action(
            session_files, user_id, self._react_to_post_action,
            delay_between,
            channel_part=channel_part,
            message_id=message_id,
            reaction=reaction
        )
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Реакции на пост", post_link, stats,
            additional_info=f"<b>Реакция:</b> {reaction}"
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 5. ГОЛОСОВАНИЕ В ОПРОСЕ
    # ══════════════════════════════════════════════════════════

    async def _vote_in_poll_action(
        self,
        client: Client,
        channel_part: str,
        message_id: int,
        option_indices: List[int]
    ) -> Dict:
        chat = await _resolve_chat(client, channel_part)
        msg = await client.get_messages(chat.id, message_ids=message_id)

        if not msg or not msg.poll:
            raise ValueError("В сообщении нет опроса")

        poll = msg.poll.poll
        for idx in option_indices:
            if idx >= len(poll.answers):
                raise ValueError(f"Вариант {idx} не существует (всего {len(poll.answers)})")

        options = [poll.answers[idx].option for idx in option_indices]

        peer = await client.resolve_peer(
            int(f"-100{channel_part}") if channel_part.isdigit() else channel_part
        )
        await client.invoke(SendVote(peer=peer, msg_id=message_id, options=options))
        return {"success": True, "error": None}

    async def vote_in_poll(
        self,
        session_files: List[str],
        user_id: int,
        poll_link: str,
        option_indices: List[int],
        delay_between: float = 1.0
    ) -> Dict:
        """Проголосовать в опросе."""
        option_indices = [int(i) for i in option_indices]
        channel_part, message_id, _ = _parse_channel_link(poll_link)
        if not channel_part or not message_id:
            logger.error(f"❌ Неверный формат ссылки: {poll_link}")
            return {"success": 0, "total": 0, "errors": 0}

        stats = await self._run_parallel_action(
            session_files, user_id, self._vote_in_poll_action,
            delay_between,
            channel_part=channel_part,
            message_id=message_id,
            option_indices=option_indices
        )
        options_str = ", ".join(f"№{i + 1}" for i in option_indices)
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Голосование в опросе", poll_link, stats,
            additional_info=f"<b>Варианты:</b> {options_str}"
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 6. СТАРТ БОТА С РЕФЕРАЛЬНОЙ ССЫЛКОЙ
    # ══════════════════════════════════════════════════════════

    async def _start_bot_action(
        self,
        client: Client,
        bot_username: str,
        ref_param: Optional[str]
    ) -> Dict:
        text = f"/start {ref_param}" if ref_param else "/start"
        await client.send_message(bot_username, text)
        return {"success": True, "error": None}

    async def start_bot_with_ref(
        self,
        session_files: List[str],
        user_id: int,
        bot_link: str,
        delay_between: float = 1.0
    ) -> Dict:
        """Запустить бота с реферальной ссылкой."""
        bot_username: Optional[str] = None
        ref_param: Optional[str] = None

        # Парсим ссылку вида: https://t.me/bot?start=ref123
        m = re.search(r't\.me/([\w\d_]+)(?:\?start=([^\s&]+))?', bot_link)
        if m:
            bot_username = m.group(1)
            ref_param = m.group(2)
        elif bot_link.startswith('@'):
            bot_username = bot_link[1:]
        else:
            bot_username = bot_link

        if not bot_username:
            logger.error("❌ Не удалось распознать имя бота")
            return {"success": 0, "total": 0, "errors": 0}

        stats = await self._run_parallel_action(
            session_files, user_id, self._start_bot_action,
            delay_between, bot_username=bot_username, ref_param=ref_param
        )
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Переходы по реферальной ссылке", bot_link, stats
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 7. ОТВЕТ НА СООБЩЕНИЕ
    # ══════════════════════════════════════════════════════════

    async def _reply_to_message_action(
        self,
        client: Client,
        channel_part: str,
        message_id: int,
        text: str,
        invite_hash: Optional[str]
    ) -> Dict:
        # Вступаем по инвайту если нужно
        if invite_hash:
            try:
                await _join_by_invite(client, invite_hash)
                await asyncio.sleep(random.uniform(1, 2))
            except UserAlreadyParticipant:
                pass
            except Exception as e:
                logger.warning(f"Ошибка вступления по инвайту: {str(e)[:80]}")

        chat = await _resolve_chat(client, channel_part)

        # Нельзя отвечать в каналах (broadcast)
        if getattr(chat, 'type', None) and str(chat.type) in ('ChatType.CHANNEL',):
            raise ValueError("Это канал — отвечать на сообщения нельзя")

        msg = await client.get_messages(chat.id, message_ids=message_id)
        if not msg:
            raise ValueError(f"Сообщение {message_id} не найдено")

        await client.send_message(chat.id, text, reply_to_message_id=message_id)
        return {"success": True, "error": None}

    async def reply_to_message(
        self,
        session_files: List[str],
        user_id: int,
        message_link: str,
        text: str,
        invite_link: Optional[str] = None,
        delay_between: float = 2.0
    ) -> Dict:
        """Ответить на сообщение в чате."""
        channel_part, message_id, invite_hash = _parse_channel_link(message_link)

        # Если передана отдельная invite_link — парсим хэш из неё
        if invite_link and not invite_hash:
            m = re.search(r't\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', invite_link)
            if m:
                invite_hash = m.group(1)

        if not channel_part or not message_id:
            logger.error(f"❌ Неверный формат ссылки: {message_link}")
            return {"success": 0, "total": 0, "errors": 0}

        stats = await self._run_parallel_action(
            session_files, user_id, self._reply_to_message_action,
            delay_between,
            channel_part=channel_part,
            message_id=message_id,
            text=text,
            invite_hash=invite_hash
        )
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Ответы на сообщение", message_link, stats
        ))
        return stats

    # ══════════════════════════════════════════════════════════
    # 8. КЛИК ПО ИНЛАЙН-КНОПКЕ
    # ══════════════════════════════════════════════════════════

    async def _click_inline_button_action(
        self,
        client: Client,
        channel_part: str,
        message_id: int,
        button_index: int,
        invite_hash: Optional[str]
    ) -> Dict:
        # Вступаем по инвайту если нужно
        if invite_hash:
            try:
                await _join_by_invite(client, invite_hash)
                await asyncio.sleep(random.uniform(1, 2))
            except UserAlreadyParticipant:
                pass
            except Exception as e:
                logger.warning(f"Ошибка вступления: {str(e)[:80]}")

        chat = await _resolve_chat(client, channel_part)
        msg = await client.get_messages(chat.id, message_ids=message_id)

        if not msg:
            raise ValueError("Сообщение не найдено")
        if not msg.reply_markup:
            raise ValueError("У сообщения нет инлайн-кнопок")

        # Собираем все кнопки в плоский список
        buttons = []
        for row in msg.reply_markup.inline_keyboard:
            buttons.extend(row)

        if button_index >= len(buttons):
            raise ValueError(
                f"Кнопки с индексом {button_index} нет (всего кнопок: {len(buttons)})"
            )

        # Кликаем через click — Hydrogram сам отправит нужный запрос
        await msg.click(button_index)
        logger.info(f"✅ Нажата кнопка #{button_index}")
        return {"success": True, "error": None}

    async def click_inline_button(
        self,
        session_files: List[str],
        user_id: int,
        post_link: str,
        button_index: int = 0,
        delay_between: float = 2.0
    ) -> Dict:
        """Нажать на инлайн-кнопку в посте."""
        channel_part, message_id, invite_hash = _parse_channel_link(post_link)

        if not message_id:
            logger.error(f"❌ Ссылка не содержит ID сообщения: {post_link}")
            return {"success": 0, "total": 0, "errors": len(session_files)}

        if not channel_part and not invite_hash:
            logger.error(f"❌ Не удалось распознать канал: {post_link}")
            return {"success": 0, "total": 0, "errors": len(session_files)}

        stats = await self._run_parallel_action(
            session_files, user_id, self._click_inline_button_action,
            delay_between,
            channel_part=channel_part,
            message_id=message_id,
            button_index=button_index,
            invite_hash=invite_hash
        )
        await self.send_stats_to_user(user_id, self._format_stats_message(
            "Клики по инлайн-кнопке", post_link, stats,
            additional_info=f"<b>Кнопка №:</b> {button_index}"
        ))
        return stats