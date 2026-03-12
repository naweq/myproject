# ============================================================
# QR-АВТОРИЗАЦИЯ — qr_auth_handler.py
# Установить зависимость: pip install qrcode[pil] pillow
# ============================================================

import io
import base64
import asyncio
import logging
import os

import qrcode
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from hydrogram import Client, raw
from hydrogram.errors import SessionPasswordNeeded

from core import get_user_api
from session_manager import SessionManager

logger = logging.getLogger(__name__)
router = Router()
session_mgr = SessionManager()


# ── Состояния ────────────────────────────────────────────────
class QRAuthStates(StatesGroup):
    waiting_for_2fa = State()


# ── Вспомогательные функции ──────────────────────────────────
def _make_qr_image(token: bytes) -> BufferedInputFile:
    """Генерирует PNG из токена и возвращает BufferedInputFile для aiogram."""
    token_b64 = base64.urlsafe_b64encode(token).decode()
    qr_url = f"tg://login?token={token_b64}"
    img = qrcode.make(qr_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="qr.png")


async def _wait_for_login_token(client: Client, timeout: float) -> bool:
    """
    Слушаем UpdateLoginToken — сигнал что QR отсканирован.
    Возвращает True если сканирование прошло, False если таймаут.
    """
    event = asyncio.Event()

    @client.on_raw_update()
    async def handler(c, update, users, chats):
        if isinstance(update, raw.types.UpdateLoginToken):
            event.set()

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        client.remove_handler(handler)


async def _cleanup_temp(client: Client, session_path: str):
    """Отключает клиент и удаляет временные файлы сессии."""
    try:
        if client and client.is_connected:
            await client.disconnect()
    except Exception:
        pass

    base_dir = os.path.dirname(session_path)
    base_name = os.path.basename(session_path)
    if os.path.exists(base_dir):
        for fname in os.listdir(base_dir):
            if fname.startswith(base_name):
                try:
                    os.remove(os.path.join(base_dir, fname))
                except Exception:
                    pass


async def _finalize_session(
    client: Client,
    event,           # Message или CallbackQuery
    user_id: int,
    session_path: str,
    qr_photo_msg=None,
):
    """Получает данные аккаунта, переименовывает сессию, сохраняет состояние."""
    try:
        me = await client.get_me()
        account_id = str(me.id)
        name = me.first_name or account_id

        await client.disconnect()

        # Переименовываем qr_temp_{user_id}.* → {account_id}.*
        user_folder = os.path.join("../users", str(user_id))
        temp_base = os.path.basename(session_path)

        for fname in os.listdir(user_folder):
            if fname.startswith(temp_base):
                suffix = fname[len(temp_base):]
                new_name = account_id + suffix
                old_full = os.path.join(user_folder, fname)
                new_full = os.path.join(user_folder, new_name)
                if os.path.exists(new_full):
                    os.remove(new_full)
                os.rename(old_full, new_full)
                logger.info(f"QR: сессия переименована {fname} → {new_name}")

        session_mgr.save_account_state(user_id, f"{account_id}.session", "🟢")

        if qr_photo_msg:
            try:
                await qr_photo_msg.delete()
            except Exception:
                pass

        success_text = (
            f"✅ <b>Авторизация успешна!</b>\n\n"
            f"👤 Имя: <b>{name}</b>\n"
            f"🆔 ID: <code>{account_id}</code>\n"
            f"💾 Сессия сохранена в <code>users/{user_id}/{account_id}.session</code>"
        )

        if isinstance(event, CallbackQuery):
            await event.message.answer(success_text, parse_mode="HTML")
        else:
            await event.answer(success_text, parse_mode="HTML")

        logger.info(f"QR: сессия {account_id}.session создана для user {user_id}")

    except Exception as e:
        logger.error(f"QR: ошибка финализации: {e}", exc_info=True)
        msg = f"❌ Ошибка при сохранении сессии: {e}"
        if isinstance(event, CallbackQuery):
            await event.message.answer(msg, parse_mode="HTML")
        else:
            await event.answer(msg, parse_mode="HTML")
        await _cleanup_temp(client, session_path)


# ── Запуск QR-авторизации ────────────────────────────────────
@router.callback_query(F.data == "qr_auth")
async def start_qr_auth(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id

    api = await get_user_api(user_id, 1)
    if not api or not api.get("api_id") or not api.get("api_hash"):
        await callback.message.answer(
            "🔑 <b>API ключи не настроены</b>\n\n"
            "Перейдите: Меню → ⚙️ Настройки → 🔑 Настройки API",
            parse_mode="HTML"
        )
        return

    api_id = int(api["api_id"])
    api_hash = api["api_hash"]

    # Папка users/{user_id}/
    session_dir = os.path.join("../users", str(user_id))
    os.makedirs(session_dir, exist_ok=True)

    # Временное имя — после авторизации переименуем в ID аккаунта
    temp_session_name = f"qr_temp_{user_id}"
    session_path = os.path.join(session_dir, temp_session_name)

    client = Client(
        name=session_path,
        api_id=api_id,
        api_hash=api_hash,
    )

    status_msg = await callback.message.answer("🔄 Подключаемся...", parse_mode="HTML")

    try:
        await client.connect()
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка подключения: {e}", parse_mode="HTML")
        return

    await status_msg.delete()

    qr_photo_msg = None
    authorized = False

    try:
        while True:
            # Запрашиваем токен
            try:
                qr_login = await client.invoke(
                    raw.functions.auth.ExportLoginToken(
                        api_id=api_id,
                        api_hash=api_hash,
                        except_ids=[],
                    )
                )
            except Exception as e:
                await callback.message.answer(f"❌ Ошибка генерации QR: {e}", parse_mode="HTML")
                break

            # Миграция DC
            if isinstance(qr_login, raw.types.auth.LoginTokenMigrateTo):
                try:
                    await client.invoke(
                        raw.functions.auth.ImportLoginToken(token=qr_login.token)
                    )
                    continue
                except Exception as e:
                    await callback.message.answer(f"❌ Ошибка миграции DC: {e}", parse_mode="HTML")
                    break

            # Уже авторизован
            if isinstance(qr_login, raw.types.auth.LoginTokenSuccess):
                authorized = True
                break

            if not isinstance(qr_login, raw.types.auth.LoginToken):
                await callback.message.answer("❌ Неизвестный ответ от Telegram", parse_mode="HTML")
                break

            # Считаем сколько секунд до истечения токена
            expires_in = max(qr_login.expires - int(asyncio.get_event_loop().time()), 5)
            qr_file = _make_qr_image(qr_login.token)
            caption = (
                "📱 <b>Войдите через QR-код</b>\n\n"
                "1. Откройте Telegram на телефоне\n"
                "2. Настройки → Устройства → Подключить устройство\n"
                "3. Наведите камеру на QR-код\n\n"
                f"⏱ Действителен <b>{expires_in}</b> сек.\n"
                "<i>QR обновится автоматически если истечёт</i>"
            )

            # Отправляем или обновляем фото с QR
            if qr_photo_msg is None:
                qr_photo_msg = await callback.message.answer_photo(
                    photo=qr_file,
                    caption=caption,
                    parse_mode="HTML"
                )
            else:
                try:
                    await qr_photo_msg.delete()
                except Exception:
                    pass
                qr_photo_msg = await callback.message.answer_photo(
                    photo=qr_file,
                    caption=caption,
                    parse_mode="HTML"
                )

            # Ждём сканирования или истечения
            scanned = await _wait_for_login_token(client, timeout=expires_in - 2)

            if scanned:
                # Финальный запрос токена после сканирования
                try:
                    result = await client.invoke(
                        raw.functions.auth.ExportLoginToken(
                            api_id=api_id,
                            api_hash=api_hash,
                            except_ids=[],
                        )
                    )
                    if isinstance(result, raw.types.auth.LoginTokenSuccess):
                        authorized = True
                        break
                    elif isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                        await client.invoke(
                            raw.functions.auth.ImportLoginToken(token=result.token)
                        )
                        authorized = True
                        break
                    else:
                        # Считаем что авторизация прошла — get_me покажет
                        authorized = True
                        break

                except SessionPasswordNeeded:
                    # 2FA включена — просим пароль
                    if qr_photo_msg:
                        try:
                            await qr_photo_msg.delete()
                        except Exception:
                            pass

                    await callback.message.answer(
                        "🔐 <b>Включена двухфакторная аутентификация</b>\n\n"
                        "Введите пароль от аккаунта:",
                        parse_mode="HTML"
                    )
                    await state.update_data(
                        qr_client=client,
                        temp_session_path=session_path,
                        user_id=user_id,
                    )
                    await state.set_state(QRAuthStates.waiting_for_2fa)
                    return  # не отключаем клиент — нужен для 2FA

                except Exception as e:
                    logger.warning(f"QR: ошибка после сканирования: {e}")
                    authorized = True  # всё равно пробуем get_me
                    break

            # Таймаут — цикл идёт дальше, генерируем новый QR

        if authorized:
            await _finalize_session(client, callback, user_id, session_path, qr_photo_msg)

    except Exception as e:
        logger.error(f"QR: критическая ошибка: {e}", exc_info=True)
        if qr_photo_msg:
            try:
                await qr_photo_msg.delete()
            except Exception:
                pass
        await callback.message.answer(f"❌ Критическая ошибка: {e}", parse_mode="HTML")
        await _cleanup_temp(client, session_path)


# ── 2FA после QR ─────────────────────────────────────────────
@router.message(QRAuthStates.waiting_for_2fa)
async def qr_process_2fa(message: Message, state: FSMContext):
    password = message.text.strip()

    try:
        await message.delete()  # убираем пароль из чата
    except Exception:
        pass

    data = await state.get_data()
    client: Client = data.get("qr_client")
    session_path: str = data.get("temp_session_path")
    user_id: int = data.get("user_id")

    if not client:
        await message.answer("❌ Сессия потеряна. Начните QR-авторизацию заново.")
        await state.clear()
        return

    try:
        await client.check_password(password)
        await state.clear()
        await _finalize_session(client, message, user_id, session_path)
    except Exception as e:
        await message.answer(
            f"❌ Неверный пароль: {e}\n\nПопробуйте ещё раз:",
            parse_mode="HTML"
        )