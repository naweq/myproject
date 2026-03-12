# ==========================================
# ФАЙЛ: spamblock_service.py
# ОПИСАНИЕ: Сервис автоснятия спамблока
# ==========================================

import asyncio
import logging
import random
from typing import Optional, Callable

from hydrogram import Client
from hydrogram.errors import FloodWait, UserIsBlocked

from spamblock_config import get_spamblock_config, get_lang_for_phone, LANG_NAMES

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# ПЕРЕВОДЧИК
# ──────────────────────────────────────────────────────────────────────────────

async def translate_text(text: str, target_lang: str) -> str:
    if target_lang == "ru":
        return text
    try:
        import urllib.parse, urllib.request, json as json_mod
        encoded = urllib.parse.quote(text)
        url = (
            f"https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=ru&tl={target_lang}&dt=t&q={encoded}"
        )
        loop = asyncio.get_event_loop()
        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8")
        raw = await loop.run_in_executor(None, _fetch)
        data = json_mod.loads(raw)
        translated = "".join(part[0] for part in data[0] if part[0])
        return translated.strip() or text
    except Exception as e:
        logger.warning(f"[Translator] Не удалось перевести на {target_lang}: {e}")
        return text


# ──────────────────────────────────────────────────────────────────────────────
# РЕЗУЛЬТАТ
# ──────────────────────────────────────────────────────────────────────────────

class SpamBlockResult:
    RETRIED_OK  = "retried_ok"
    APPEAL_SENT = "appeal_sent"
    SKIPPED     = "skipped"
    DISABLED    = "disabled"
    ERROR       = "error"

    def __init__(self, status: str, message: str = "", should_continue: bool = False):
        self.status = status
        self.message = message
        self.should_continue = should_continue

    def __repr__(self):
        return f"SpamBlockResult({self.status}, continue={self.should_continue})"


# ──────────────────────────────────────────────────────────────────────────────
# ХЕЛПЕР — ждём ответ от SpamBot
# ──────────────────────────────────────────────────────────────────────────────

# Числовой ID @SpamBot в Telegram
SPAMBOT_USER_ID = 178220800

async def _wait_spambot_reply(client: Client, timeout: int = 30) -> Optional[str]:
    """
    Ждём входящее сообщение от @SpamBot через on_message.
    Возвращает текст сообщения или None при таймауте.
    """
    got_text: list = []
    event = asyncio.Event()

    try:
        spambot_peer = await client.resolve_peer("SpamBot")
        spambot_id = getattr(spambot_peer, "user_id", SPAMBOT_USER_ID)
    except Exception:
        spambot_id = SPAMBOT_USER_ID

    @client.on_message()
    async def _handler(c, msg):
        sender_id = getattr(msg.from_user, "id", None) if msg.from_user else None
        if sender_id and sender_id == spambot_id:
            got_text.append(msg.text or "")
            event.set()

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        try:
            client.remove_handler(_handler)
        except Exception:
            pass

    return got_text[0] if got_text else None


# ──────────────────────────────────────────────────────────────────────────────
# УМНАЯ ПЕРЕПИСКА СО SPAMBOT
# ──────────────────────────────────────────────────────────────────────────────

async def _smart_spambot_dialog(
    client: Client,
    appeal_text: str,
    session_name: str,
    progress_callback: Optional[Callable],
    user_id: int,
    bot_instance,   # aiogram Bot — для отправки капчи юзеру
) -> bool:
    """
    Умный диалог с @SpamBot:
    1. /start → читаем ответ
    2. Если ответ чистый — возвращаем True сразу
    3. Если есть inline URL-кнопка (капча) — отправляем ссылку юзеру бота,
       ждём подтверждения до 5 минут
    4. Если есть reply-клавиатура с кнопкой «No spam» — нажимаем её
    5. Отправляем текст апелляции
    6. Читаем финальный ответ

    Возвращает True если апелляция отправлена успешно.
    """
    SPAMBOT = "SpamBot"

    async def _cb(text: str):
        if progress_callback:
            try:
                await progress_callback(text)
            except Exception:
                pass

    try:
        # ── Шаг 1: /start ──────────────────────────────────────────────────
        await _cb(f"🤖 <b>{session_name}</b>: начинаю диалог с @SpamBot...")
        await client.send_message(SPAMBOT, "/start")
        await asyncio.sleep(2)

        reply1 = await _wait_spambot_reply(client, timeout=15)
        logger.info(f"[SpamBot:{session_name}] Ответ на /start: {reply1!r}")
        reply1_lower = (reply1 or "").lower()

        # Если уже чисто
        if any(k in reply1_lower for k in ["no limits", "нет ограничений", "no spam", "you're free"]):
            await _cb(f"✅ <b>{session_name}</b>: спамблок не обнаружен или уже снят!")
            return True

        # ── Шаг 2: Проверяем inline-кнопки (капча) ─────────────────────────
        captcha_url = None
        try:
            async for msg in client.get_chat_history(SPAMBOT, limit=3):
                if not msg.reply_markup:
                    continue
                rows = getattr(msg.reply_markup, "inline_keyboard", [])
                for row in rows:
                    for btn in row:
                        url = getattr(btn, "url", None)
                        if url:
                            captcha_url = url
                            logger.info(f"[SpamBot:{session_name}] Найдена капча: {url}")
                            break
                    if captcha_url:
                        break
                if captcha_url:
                    break
        except Exception as e:
            logger.warning(f"[SpamBot:{session_name}] Ошибка чтения inline-кнопок: {e}")

        # ── Шаг 3: Отправляем капчу юзеру и ждём подтверждения ─────────────
        if captcha_url and bot_instance and user_id:
            await _cb(
                f"🔐 <b>{session_name}</b>: @SpamBot требует прохождение капчи!\n"
                f"⏳ Отправляю ссылку пользователю, жду подтверждения..."
            )
            try:
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔐 Пройти капчу", url=captcha_url)],
                    [InlineKeyboardButton(
                        text="✅ Я прошёл капчу",
                        callback_data=f"sb:captcha_done:{session_name}"
                    )]
                ])
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=(
                        f"🚨 <b>Требуется капча для аккаунта <code>{session_name}</code></b>\n\n"
                        f"@SpamBot запрашивает подтверждение личности.\n\n"
                        f"1️⃣ Нажмите кнопку «Пройти капчу»\n"
                        f"2️⃣ Пройдите проверку в Telegram\n"
                        f"3️⃣ Вернитесь и нажмите «Я прошёл капчу»\n\n"
                        f"⏱ Ожидание: до 5 минут"
                    ),
                    reply_markup=kb,
                    parse_mode="HTML"
                )

                # Регистрируем событие ожидания
                captcha_event = asyncio.Event()
                spamblock_service.pending_captcha[session_name] = captcha_event

                try:
                    await asyncio.wait_for(captcha_event.wait(), timeout=300)
                    await _cb(f"✅ <b>{session_name}</b>: пользователь подтвердил прохождение капчи!")
                    logger.info(f"[SpamBot:{session_name}] Капча подтверждена")
                    await asyncio.sleep(2)
                except asyncio.TimeoutError:
                    await _cb(f"⏰ <b>{session_name}</b>: таймаут ожидания капчи (5 мин), продолжаю без неё...")
                    logger.warning(f"[SpamBot:{session_name}] Таймаут капчи")
                finally:
                    spamblock_service.pending_captcha.pop(session_name, None)

            except Exception as e:
                logger.error(f"[SpamBot:{session_name}] Ошибка отправки капчи: {e}")

        # ── Шаг 4: Reply-клавиатура — нажимаем кнопку «No spam» ───────────
        try:
            async for msg in client.get_chat_history(SPAMBOT, limit=3):
                rm = msg.reply_markup
                if not rm or not hasattr(rm, "keyboard"):
                    continue
                for row in rm.keyboard:
                    for btn in row:
                        btn_text_raw = getattr(btn, "text", "")
                        btn_text_lower = btn_text_raw.lower()
                        if any(k in btn_text_lower for k in [
                            "no spam", "нет спама", "yes", "да",
                            "i'm not", "not spam", "не спам"
                        ]):
                            logger.info(f"[SpamBot:{session_name}] Нажимаем кнопку: {btn_text_raw!r}")
                            await client.send_message(SPAMBOT, btn_text_raw)
                            await asyncio.sleep(2)
                            # Читаем следующий ответ
                            reply2 = await _wait_spambot_reply(client, timeout=10)
                            logger.info(f"[SpamBot:{session_name}] Ответ после кнопки: {reply2!r}")
                            break
                break
        except Exception as e:
            logger.warning(f"[SpamBot:{session_name}] Ошибка reply-клавиатуры: {e}")

        # ── Шаг 5: Отправляем апелляцию ────────────────────────────────────
        await _cb(f"📝 <b>{session_name}</b>: отправляю текст апелляции в @SpamBot...")
        await client.send_message(SPAMBOT, appeal_text)
        await asyncio.sleep(3)

        # ── Шаг 6: Финальный ответ ──────────────────────────────────────────
        reply_final = await _wait_spambot_reply(client, timeout=15)
        logger.info(f"[SpamBot:{session_name}] Финальный ответ: {reply_final!r}")

        reply_final_lower = (reply_final or "").lower()
        if any(k in reply_final_lower for k in [
            "no limits", "нет ограничений", "no spam", "you're free",
            "thank", "спасибо", "received", "получено", "appeal", "апелляция"
        ]):
            await _cb(f"✅ <b>{session_name}</b>: апелляция принята @SpamBot!")
        else:
            await _cb(
                f"📋 <b>{session_name}</b>: апелляция отправлена.\n"
                f"💬 Ответ: {reply_final[:120] if reply_final else '(нет ответа)'}"
            )

        return True

    except UserIsBlocked:
        logger.warning(f"[SpamBot:{session_name}] @SpamBot заблокирован аккаунтом")
        await _cb(f"⚠️ <b>{session_name}</b>: @SpamBot заблокирован — разблокируйте его вручную!")
        return False
    except Exception as e:
        logger.error(f"[SpamBot:{session_name}] Ошибка диалога: {e}", exc_info=True)
        await _cb(f"❌ <b>{session_name}</b>: ошибка диалога с @SpamBot: {str(e)[:120]}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ СЕРВИС
# ──────────────────────────────────────────────────────────────────────────────

class SpamBlockService:
    SPAMBOT = "@SpamBot"

    def __init__(self):
        # session_name → asyncio.Event
        # Устанавливается когда юзер нажимает «Я прошёл капчу»
        self.pending_captcha: dict = {}

    def confirm_captcha(self, session_name: str) -> bool:
        """Вызывается из aiogram-хендлера кнопки 'Я прошёл капчу'."""
        event = self.pending_captcha.get(session_name)
        if event:
            event.set()
            return True
        return False

    async def handle_peer_flood(
        self,
        client: Client,
        user_id: int,
        session_name: str,
        phone: Optional[str],
        progress_callback: Optional[Callable] = None,
    ) -> SpamBlockResult:
        """
        Вызывается при PeerFlood ИЛИ когда в тексте ошибки есть упоминание spambot.
        Решает что делать согласно настройкам пользователя.
        """
        cfg = get_spamblock_config(user_id)

        if not cfg.enabled:
            return SpamBlockResult(SpamBlockResult.DISABLED, "Автоснятие отключено")

        is_premium = await self._check_premium(client)

        if is_premium:
            return await self._handle_premium_account(
                client, user_id, session_name, phone, cfg, progress_callback
            )
        else:
            return await self._handle_non_premium_account(
                client, user_id, session_name, phone, cfg, progress_callback
            )

    async def _check_premium(self, client: Client) -> bool:
        try:
            me = await client.get_me()
            return bool(getattr(me, "is_premium", False))
        except Exception as e:
            logger.warning(f"Не удалось проверить Premium: {e}")
            return False

    async def _get_phone(self, client: Client) -> Optional[str]:
        try:
            me = await client.get_me()
            return getattr(me, "phone_number", None)
        except Exception:
            return None

    def _get_appeal_text(self, cfg, phone: Optional[str] = None) -> str:
        template = cfg.get_active_template()
        return template["text"] if template else (
            "Здравствуйте, я не рассылаю спам и не нарушаю правила Telegram. "
            "Прошу снять ограничения с моего аккаунта."
        )

    async def _handle_premium_account(
        self,
        client: Client,
        user_id: int,
        session_name: str,
        phone: Optional[str],
        cfg,
        progress_callback: Optional[Callable],
    ) -> SpamBlockResult:
        """Premium: умная переписка + ожидание + повтор рассылки."""
        wait_sec = random.randint(cfg.premium_retry_wait, cfg.premium_retry_wait_max)

        # Подготавливаем текст апелляции
        appeal_text = self._get_appeal_text(cfg, phone)
        if cfg.auto_translate and phone:
            lang = get_lang_for_phone(phone)
            if lang != "ru":
                appeal_text = await translate_text(appeal_text, lang)

        try:
            from config import bot as aiogram_bot
        except Exception:
            aiogram_bot = None

        # Умный диалог
        await _smart_spambot_dialog(
            client, appeal_text, session_name, progress_callback, user_id, aiogram_bot
        )

        if progress_callback:
            await progress_callback(
                f"💎 <b>{session_name}</b> (Premium): апелляция подана.\n"
                f"⏳ Жду <b>{wait_sec // 60} мин</b> перед повтором рассылки..."
            )

        # Ждём с отчётом каждую минуту
        elapsed = 0
        while elapsed < wait_sec:
            chunk = min(60, wait_sec - elapsed)
            await asyncio.sleep(chunk)
            elapsed += chunk
            remaining = wait_sec - elapsed
            if progress_callback and remaining > 0:
                await progress_callback(
                    f"⏳ <b>{session_name}</b>: ожидание снятия ограничений... "
                    f"осталось ~{remaining // 60} мин {remaining % 60} сек"
                )

        return SpamBlockResult(
            SpamBlockResult.RETRIED_OK,
            f"Premium-аккаунт {session_name}: ожидание завершено, пробуем снова",
            should_continue=True,
        )

    async def _handle_non_premium_account(
        self,
        client: Client,
        user_id: int,
        session_name: str,
        phone: Optional[str],
        cfg,
        progress_callback: Optional[Callable],
    ) -> SpamBlockResult:
        """Обычный аккаунт: умный диалог, апелляция, остановка рассылки."""
        appeal_text = self._get_appeal_text(cfg, phone)

        if cfg.auto_translate and phone:
            lang = get_lang_for_phone(phone)
            lang_name = LANG_NAMES.get(lang, lang)
            if lang != "ru":
                if progress_callback:
                    await progress_callback(
                        f"🌍 <b>{session_name}</b>: перевожу апелляцию на {lang_name}..."
                    )
                appeal_text = await translate_text(appeal_text, lang)

        try:
            from config import bot as aiogram_bot
        except Exception:
            aiogram_bot = None

        await _smart_spambot_dialog(
            client, appeal_text, session_name, progress_callback, user_id, aiogram_bot
        )

        result_msg = (
            f"📋 <b>Аккаунт {session_name}</b>: апелляция подана в @SpamBot\n"
            f"⏹ Рассылка с этого аккаунта приостановлена до снятия ограничений"
        )
        if progress_callback:
            await progress_callback(result_msg)

        return SpamBlockResult(
            SpamBlockResult.APPEAL_SENT,
            result_msg,
            should_continue=False,
        )

    async def check_spamblock_status(self, client: Client) -> str:
        """Проверить статус: 'clean' | 'blocked' | 'error'"""
        try:
            await client.send_message(self.SPAMBOT, "/start")
            reply = await _wait_spambot_reply(client, timeout=10)
            if not reply:
                return "error"
            text = reply.lower()
            if any(k in text for k in ["no limits", "нет ограничений", "no spam"]):
                return "clean"
            elif any(k in text for k in ["spam", "ограничен", "limited", "reported"]):
                return "blocked"
            return "error"
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return "error"
        except Exception as e:
            logger.warning(f"[SpamBlock] Ошибка проверки статуса: {e}")
            return "error"


# Синглтон
spamblock_service = SpamBlockService()