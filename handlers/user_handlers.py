# ==========================================
# ФАЙЛ: bot/handlers/user_handlers.py
# ОПИСАНИЕ: Обработчики пользовательских команд
# ==========================================
import json
import zipfile

import asyncio
import logging
from pathlib import Path
from datetime import datetime
from aiogram.utils.markdown import hbold, hcode, hitalic
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from modules.list_adder import main as get_list_url
from keyboards import user_keyboards as kb
from config import bot, CHANNEL_ID, PYROGRAM_PROXIES, API_PAIRS, user_confirm, ADMIN_IDS
from modules.database import Database
from modules.session_manager import SessionManager
from keyboards.user_keyboards import UserKeyboards, choice

logger = logging.getLogger(__name__)
router = Router()
BASE_DIR = Path("../users")
db = Database()
session_mgr = SessionManager()

# ============= ПРОВЕРКА API КЛЮЧЕЙ =============

NO_API_TEXT = (
    "🔑 <b>API ключи не настроены</b>\n\n"
    "Для работы с аккаунтами необходимо добавить API ключи.\n\n"
    "📍 <b>Как добавить:</b>\n"
    "Меню → ⚙️ Настройки → 🔑 Настройки API\n\n"
    "<i>Получить ключи можно на my.telegram.org</i>"
)

async def check_api(user_id: int) -> bool:
    """Вернуть True если API ключи установлены, иначе False"""
    api = await get_user_api(user_id, 1)
    return bool(api and api.get("api_id") and api.get("api_hash"))


sogl = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='📜Пользовательское соглашение', url=user_confirm)],
    [InlineKeyboardButton(text='☑️Я согласен', callback_data="sogl")]
])

semaphore = asyncio.Semaphore(5)

async def bounded_check(full_session_name, user_id):
    async with semaphore:
        raw = await session_mgr.check_session_valid(full_session_name, user_id)
        return raw[0] if isinstance(raw, tuple) else raw
# ============= СОСТОЯНИЯ =============
class AddAccountStates(StatesGroup):
    waiting_for_zip = State()
    session_type = State()


class ZipStates(StatesGroup):
    waiting_for_zip = State()


class AddPhoneStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()


async def check_subs(user_id):
    member = await bot.get_chat_member(CHANNEL_ID, user_id)
    if member.status not in ("member", "administrator", "creator"):
        return False
    else:
        return True


def get_random_api():
    return random.choice(API_PAIRS)


def get_random_proxy():
    if not PYROGRAM_PROXIES:
        return None
    proxy = random.choice(PYROGRAM_PROXIES)
    return dict(
        scheme=proxy["scheme"],
        hostname=proxy["hostname"],
        port=proxy["port"],
        username=proxy["username"],
        password=proxy["password"]
    )


async def cleanup_temp_session(user_id: int, temp_session: str):
    """Очистка временной сессии"""
    try:
        session_path = session_mgr.get_user_folder(user_id, "pyrogram") / f"{temp_session}.session"
        if session_path.exists():
            session_path.unlink()
            logger.info(f"🗑 Удалена временная сессия: {temp_session}")

        # Удаляем также журнальные файлы
        journal_path = session_path.parent / f"{temp_session}.session-journal"
        if journal_path.exists():
            journal_path.unlink()

        # Удаляем .session-shm и .session-wal файлы если есть
        shm_path = session_path.parent / f"{temp_session}.session-shm"
        if shm_path.exists():
            shm_path.unlink()

        wal_path = session_path.parent / f"{temp_session}.session-wal"
        if wal_path.exists():
            wal_path.unlink()

    except Exception as e:
        logger.error(f"❌ Ошибка очистки временной сессии: {e}")


# ============= БАЗОВЫЕ КОМАНДЫ =============
@router.message(Command('menu'))
async def menu_hand(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    logger.info(f"👤 Пользователь {user_id} ({username}) запустил бота")

    # Проверка блокировки
    if db.is_blocked(user_id):
        await message.answer(
            "🚫 <b>Доступ заблокирован</b>\n\n"
            "Обратитесь в поддержку для уточнения причины.",
            parse_mode="HTML"
        )
        return

    await show_main_menu(message, message.from_user.id)

@router.message(CommandStart())
async def start_handler(message: Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    logger.info(f"👤 Пользователь {user_id} ({username}) запустил бота")

    # Проверка блокировки
    if await db.is_blocked(user_id):
        await message.answer(
            "🚫 <b>Доступ заблокирован</b>\n\n"
            "Обратитесь в поддержку для уточнения причины.",
            parse_mode="HTML"
        )
        return

    # Добавляем пользователя (если новый)
    user = await db.get_user(user_id)
    os.makedirs(f'users/{user_id}', exist_ok=True)
    welcome_text = (
        f"⚡️ {hbold('SenderX — Professional Telegram Marketing')}\n\n"
        f"Добро пожаловать в панель управления! {hbold('SenderX')} — это мощный инструмент на базе "
        f"{hitalic('Telethon')}, созданный для автоматизации и эффективного управления аккаунтами.\n\n"

        f"🚀 {hbold('ФУНКЦИОНАЛ РАССЫЛОК')}\n"
        f"• {hitalic('По чатам')} — массовый охват сообществ\n"
        f"• {hitalic('По контактам')} — работа с телефонной книгой\n"
        f"• {hitalic('По диалогам')} — касание активных переписок\n"
        f"• {hitalic('Target')} — отправка конкретному пользователю\n\n"

        f"📂 {hbold('МЕНЕДЖЕР АККАУНТОВ')}\n"
        f"👤 {hbold('Smart Switch')}: Смена профиля прямо в боте\n"
        f"🔄 {hbold('Converter')}: Конвертация сессий в {hcode('TDATA')}\n\n"

        f"🛠 {hbold('ОСНОВНЫЕ КОМАНДЫ')}\n"
        f"👉  /menu — Главное меню\n"
        f"👉 /tasks — Активные задачи\n"
        f"👉 /help — Техническая поддержка\n\n"
        f"__________________________________\n"
    )
    # photo = 'AgACAgIAAxkBAAIUOGmamAZQJZIFUtUPaSEJYulvlmv2AAIWF2sbgU7QSDBiU1BM6JO5AQADAgADeQADOgQ'

        # Новый пользователь - показываем соглашение
    await db.add_user(user_id, username, first_name)
    msg = await message.answer(text=welcome_text, parse_mode="HTML", reply_markup=kb.reply_menu)
    if not await db.get_user(user_id):
        await message.answer(
                "📜 <b>Пользовательское соглашение</b>\n\n"
                "Пожалуйста, ознакомьтесь с условиями использования бота.\n\n"
                "Для продолжения нажмите кнопку '☑️ Я согласен', чтобы согласиться с соглашением.",
                reply_markup=sogl,
                parse_mode="HTML"
            )
    await msg.pin(disable_notification=False)
        # Существующий пользователь - сразу в главное меню


async def show_main_menu(message: Message, user_id: int):
    """Показать главное меню"""
    # Проверка подписки на канал
    try:
        if await check_subs(user_id) is False:
            await message.answer(
                "📢 <b>Подписка обязательна!</b>\n\n"
                "Подпишитесь на канал для использования бота 👇",
                reply_markup=UserKeyboards.check_subscription(),
                parse_mode="HTML"
            )
            return
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")

    # Проверяем подписку
    has_sub = await db.has_active_subscription(user_id)
    photo = 'AgACAgIAAxkBAAPzaWNbSCk0z3zkHcJyMir9ht6BPwQAAjILaxte9SBLK6Gfc2LSNygBAAMCAAN3AAM4BA'
    # Приветственное сообщение
    await message.answer(

        text="<b>🔲----SenderX----🔲</b>️️\n"
             f"━━━━━━━━━━━━━━━━━━━\n\n"
             f"<b>📱 Функции бота:</b>\n"
             f"• Поддержка Telethon\n"
             f"• Управление до 1000 аккаунтами\n"
             f"• Получение кодов входа\n"
             f"• Массовые рассылки\n"
             f"• Инвайтинг\n"
             f"• Проверка валидности\n"
             f"• <b>Конвертер сессий в TDATA</b>\n\n"
             f"<i>{'💎 Ваша подписка активна!' if has_sub else '⚠️ Оформите подписку для доступа'}</i>",
        reply_markup=UserKeyboards.main_menu(has_subscription=has_sub),
        parse_mode="HTML"
    )
    # await message.answer('⌨️', reply_markup=kb.reply_menu)


@router.callback_query(F.data == "sogl")
async def sogll(callback: CallbackQuery):
    """Пользователь согласился с соглашением"""
    user_id = callback.from_user.id

    await callback.message.delete()

    # Создаём новое сообщение с главным меню
    await show_main_menu(callback.message, user_id)
    await callback.answer("✅ Добро пожаловать!")


@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery):
    """Проверка подписки"""
    user_id = callback.from_user.id

    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ("member", "administrator", "creator"):
            has_sub = db.has_active_subscription(user_id)
            await callback.message.edit_text(
                "✅ <b>Подписка подтверждена!</b>\n\n"
                "Теперь вы можете пользоваться ботом 🚀",
                reply_markup=UserKeyboards.main_menu(has_sub),
                parse_mode="HTML"
            )
        else:
            await callback.answer("❌ Вы не подписались!", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка проверки: {e}")
        await callback.answer("Ошибка. Попробуйте позже", show_alert=True)


@router.callback_query(F.data == "back_from_list")
async def back_from_lists(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    # Проверяем, есть ли активная подписка
    has_sub = await db.has_active_subscription(user_id)

    await callback.message.answer(
        "🏠 <b>Главное меню</b>\n\n"
        "Выберите нужный раздел:",
        reply_markup=UserKeyboards.main_menu(has_sub),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    user_id = callback.from_user.id
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        # Проверяем, есть ли активная подписка
        has_sub = await db.has_active_subscription(user_id)

        await callback.message.edit_text(
            "🏠 <b>Главное меню</b>\n\n"
            "Выберите нужный раздел:",
            reply_markup=UserKeyboards.main_menu(has_sub),
            parse_mode="HTML"
        )

        await callback.answer()  # Убирает "часики" с кнопки


@router.message(F.text == '🎛Главное меню')
async def reply_menu(message: Message):
    user_id = message.from_user.id
    is_sub = await check_subs(user_id)
    if is_sub is False:
        await message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    # Проверяем, есть ли активная подписка
    else:
        has_sub = await db.has_active_subscription(user_id)

        await message.answer(
            "🏠 <b>Главное меню</b>\n\n"
            "Выберите нужный раздел:",
            reply_markup=UserKeyboards.main_menu(has_sub),
            parse_mode="HTML"
        )


async def show_accounts_list(message_or_callback, user_id: int, page: int = 0):
    """Вспомогательная функция для обновления списка аккаунтов"""
    sessions = session_mgr.get_sessions(user_id)  # должен возвращать с типом!
    states = session_mgr.get_account_states(user_id)

    text = (
        f"📱 <b>МОИ АККАУНТЫ</b>\n\n"
        f"📊 Всего: <b>{len(sessions)}</b>\n"
        f"📄 Страница: <b>{page + 1}</b>\n\n"
        f"<i>Нажмите на аккаунт для деталей</i>"
    ) if sessions else (
        "📱 <b>МОИ АККАУНТЫ</b>\n\n"
        "📭 У вас пока нет аккаунтов\n\n"
        "Нажмите ➕ Добавить аккаунты"
    )

    if isinstance(message_or_callback, Message):
        await message_or_callback.edit_text(
            text,
            reply_markup=UserKeyboards.accounts_list(sessions, states, page, user_id=user_id),
            parse_mode="HTML"
        )
    else:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=UserKeyboards.accounts_list(sessions, states, page, user_id=user_id),
            parse_mode="HTML"
        )


@router.callback_query(F.data.in_(["pyrogram", "telethon"]))
async def choose_session_type(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал тип сессий"""
    session_type = callback.data  # "pyrogram" или "telethon"
    folder_name = "pyro_sessions" if session_type == "pyrogram" else "tele_sessions"
    display_name = "Pyrogram" if session_type == "pyrogram" else "Telethon"
    user_id = int(callback.from_user.id)

    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    await state.update_data(session_type=session_type)

    await callback.message.answer(
        f"📤 Отправьте ZIP-архив с <b>{display_name}</b>-сессиями (.session файлы).\n\n",
        # f"⚠️ Архив будет распакован в папку: <code>{folder_name}</code>",
        parse_mode="HTML"
    )
    await state.set_state(AddAccountStates.waiting_for_zip)
    await callback.answer()


@router.message(StateFilter(AddAccountStates.waiting_for_zip), F.document.mime_type == "application/zip")
async def handle_zip_archive(message: Message, state: FSMContext):
    """Универсальная обработка ZIP для обоих типов"""
    data = await state.get_data()
    session_type = data.get("session_type")

    if not session_type:
        await message.answer("❌ Ошибка: тип сессии не выбран. Начните заново.")
        await state.clear()
        return

    user_id = message.from_user.id

    # ИСПРАВЛЕНО: правильная папка users/{user_id}/
    user_path = Path("../users") / str(user_id)
    user_path.mkdir(parents=True, exist_ok=True)

    zip_path = f"temp_{user_id}_{session_type}.zip"

    # Скачивание файла
    await bot.download(file=message.document, destination=zip_path)

    # Сообщение о статусе — будем его редактировать
    status_msg = await message.answer("📦 <b>Распаковываю ZIP...</b>", parse_mode="HTML")

    try:
        import shutil, tempfile as _tempfile, sqlite3

        def _is_hydrogram_session(path: str) -> bool:
            """
            Проверка совместимости .session с Hydrogram без подключения.
            Hydrogram хранит сессию в SQLite с таблицей 'sessions'
            и колонками dc_id, api_id, test_mode, auth_key, date, user_id, is_bot.
            """
            try:
                if os.path.getsize(path) < 512:
                    return False
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {r[0].lower() for r in cur.fetchall()}
                if "sessions" not in tables:
                    conn.close()
                    return False
                # Проверяем наличие нужных колонок
                cur.execute("PRAGMA table_info(sessions)")
                cols = {r[1].lower() for r in cur.fetchall()}
                conn.close()
                required = {"dc_id", "auth_key"}
                return required.issubset(cols)
            except Exception:
                return False

        await status_msg.edit_text(
            "🔍 <b>Проверяю совместимость сессий...</b>",
            parse_mode="HTML"
        )

        with _tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp_dir)

            all_files = list(Path(tmp_dir).rglob("*.session"))
            added = skipped = incompatible = 0

            for sf in all_files:
                dest = user_path / sf.name
                if dest.exists():
                    skipped += 1
                    continue
                if not _is_hydrogram_session(str(sf)):
                    incompatible += 1
                    logger.info(f"[ZIP] несовместима: {sf.name}")
                    continue
                shutil.copy2(str(sf), str(dest))
                # Рядом может быть .session.json
                json_f = Path(str(sf) + ".json")
                if json_f.exists():
                    shutil.copy2(str(json_f), str(user_path / json_f.name))
                added += 1

        parts = []
        if added:
            parts.append(f"➕ Добавлено: <b>{added}</b>")
        if skipped:
            parts.append(f"⏭ Уже были: <b>{skipped}</b>")
        if incompatible:
            parts.append(f"⚠️ Несовместимых: <b>{incompatible}</b>")

        if not all_files:
            await status_msg.edit_text(
                "⚠️ В архиве нет .session файлов.", parse_mode="HTML"
            )
        elif added:
            await status_msg.edit_text(
                "✅ <b>Готово!</b>" + "".join(parts), parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(
                "⚠️ <b>Ни один файл не добавлен.</b>" + "".join(parts),
                parse_mode="HTML"
            )

    except zipfile.BadZipFile:
        await status_msg.edit_text("❌ Файл не является валидным ZIP-архивом.")
    except Exception as e:
        await status_msg.edit_text("❌ Произошла ошибка при распаковке.")
        logger.error(f"ZIP error user {user_id}: {e}", exc_info=True)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    await state.clear()
    await show_accounts_list(message, user_id)


# ============= ПОДПИСКИ =============
#
# @router.callback_query(F.data == "subscriptions")
# async def show_subscriptions(callback: CallbackQuery):
#     """Показать меню подписок"""
#     user_id = callback.from_user.id
#     has_test = db.is_test_used(user_id)
#     has_active = db.has_active_subscription(user_id)
#
#     text = "💎 <b>ПОДПИСКИ</b>\n\n"
#
#     if has_active:
#         user = db.get_user(user_id)
#         sub_until = datetime.fromisoformat(user['subscription_until'])
#         sub_type = user['subscription_type']
#
#         text += (
#             f"✅ <b>Подписка активна!</b>\n\n"
#             f"📋 Тип: <b>{sub_type}</b>\n"
#             f"📅 До: <b>{sub_until.strftime('%d.%m.%Y %H:%M')}</b>"
#         )
#     else:
#         text += (
#             "<b>Выберите подходящий тариф:</b>\n\n"
#             "🎁 <b>Тест</b> - <s>36</s> 72 часа бесплатно!\n"
#             "⚡️ <b>3 дня</b> - 75 ⭐️\n"
#             "📅 <b>Неделя</b> - 125 ⭐️\n"
#             "📆 <b>Месяц</b> - 425 ⭐️\n"
#             "♾ <b>Навсегда</b> - 625 ⭐️\n\n"
#             "<i>Каждая купленная подписка делает бот лучше, масштабнее и дает плюсик к мотивации разработчику❤️</i>"
#         )
#
#     await callback.message.answer(
#         text,
#         reply_markup=UserKeyboards.subscription_menu(has_test, has_active),
#         parse_mode="HTML"
#     )
#     await callback.answer()
#
#
# @router.callback_query(F.data.startswith("sub:"))
# async def process_subscription(callback: CallbackQuery):
#     """Обработка выбора подписки"""
#     user_id = callback.from_user.id
#     sub_type = callback.data.split(":")[1]
#
#     from config import SUBSCRIPTION_PRICES
#
#     price_info = SUBSCRIPTION_PRICES.get(sub_type)
#     if not price_info:
#         await callback.answer("Ошибка", show_alert=True)
#         return
#
#     # Тестовая подписка
#     if sub_type == "test":
#         if db.is_test_used(user_id):
#             await callback.answer("❌ Тест уже использован!", show_alert=True)
#             return
#
#         db.activate_subscription(user_id, "test")
#         await callback.message.edit_text(
#             "🎉 <b>Тестовый период активирован!</b>\n\n"
#             "⏰ Длительность: 36 часов\n"
#             "✨ Все функции доступны!\n\n"
#             "Приятного использования! 🚀",
#             reply_markup=UserKeyboards.main_menu(True),
#             parse_mode="HTML"
#         )
#         await callback.answer()
#         return
#
#     # Платная подписка
#     names = {
#         "3_days": "3 дня",
#         "week": "Неделю",
#         "month": "Месяц",
#         "forever": "Навсегда"
#     }
#
#     try:
#         from aiogram.types import LabeledPrice
#
#         await callback.message.answer_invoice(
#             title=f"💎 Подписка на {names[sub_type]}",
#             description=f"Полный доступ ко всем функциям бота",
#             prices=[LabeledPrice(label=names[sub_type], amount=price_info['stars'])],
#             provider_token="",
#             payload=f"sub:{sub_type}",
#             currency="XTR",
#             reply_markup=UserKeyboards.payment(sub_type, price_info['stars'])
#         )
#         await callback.answer()
#     except Exception as e:
#         logger.error(f"Ошибка создания инвойса: {e}")
#         await callback.answer("❌ Ошибка создания счёта", show_alert=True)
#
#
# @router.pre_checkout_query()
# async def process_pre_checkout(pre_checkout_query):
#     """Предварительная проверка оплаты"""
#     await pre_checkout_query.answer(ok=True)
#
#
# @router.message(F.successful_payment)
# async def successful_payment(message: Message):
#     """Успешная оплата - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
#     user_id = message.from_user.id
#     payload = message.successful_payment.invoice_payload
#
#     # Логируем для отладки
#     logger.info(f"💰 Получена оплата от {user_id}, payload: {payload}")
#
#     # Извлекаем тип подписки
#     try:
#         sub_type = payload.split(":")[1]
#     except (IndexError, AttributeError):
#         logger.error(f"❌ Неверный payload: {payload}")
#         await message.answer(
#             "❌ <b>Ошибка обработки платежа</b>\n\n"
#             "Обратитесь в поддержку с чеком об оплате.",
#             parse_mode="HTML"
#         )
#         return
#
#     from config import SUBSCRIPTION_PRICES
#
#     # Проверяем существование типа подписки
#     if sub_type not in SUBSCRIPTION_PRICES:
#         logger.error(f"❌ Неизвестный тип подписки: {sub_type}")
#         await message.answer(
#             "❌ <b>Неизвестный тип подписки</b>\n\n"
#             "Обратитесь в поддержку.",
#             parse_mode="HTML"
#         )
#         return
#
#     stars = SUBSCRIPTION_PRICES[sub_type]['stars']
#
#     # ✅ КРИТИЧЕСКИ ВАЖНО: Убедимся, что пользователь существует в БД
#     existing_user = db.get_user(user_id)
#     if not existing_user:
#         logger.warning(f"⚠️ Пользователь {user_id} не найден в БД, добавляем...")
#         db.add_user(
#             user_id,
#             message.from_user.username,
#             message.from_user.first_name
#         )
#
#     # Активируем подписку
#     logger.info(f"🔄 Активация подписки {sub_type} для {user_id}...")
#     success = db.activate_subscription(user_id, sub_type, stars)
#
#     if not success:
#         logger.error(f"❌ Не удалось активировать подписку для {user_id}")
#         await message.answer(
#             "❌ <b>Ошибка активации подписки</b>\n\n"
#             "Обратитесь в поддержку с чеком об оплате.",
#             parse_mode="HTML"
#         )
#         return
#
#     # ✅ ДВОЙНАЯ ПРОВЕРКА: Убедимся что подписка действительно активна
#     verification = db.has_active_subscription(user_id)
#     logger.info(f"✅ Проверка активации подписки для {user_id}: {verification}")
#
#     if not verification:
#         logger.error(f"❌ Подписка не активна после активации для {user_id}!")
#
#         # Пытаемся повторно активировать
#         logger.info(f"🔄 Повторная попытка активации...")
#         db.activate_subscription(user_id, sub_type, stars)
#
#         # Проверяем снова
#         verification2 = db.has_active_subscription(user_id)
#         if not verification2:
#             await message.answer(
#                 "⚠️ <b>Возможная ошибка активации</b>\n\n"
#                 "Платёж прошёл, но возникла проблема с активацией.\n"
#                 "Обратитесь в поддержку с чеком об оплате.",
#                 parse_mode="HTML"
#             )
#             return
#
#     # Получаем актуальные данные пользователя
#     updated_user = db.get_user(user_id)
#
#     # Формируем сообщение с деталями подписки
#     from datetime import datetime
#     sub_until = datetime.fromisoformat(updated_user['subscription_until'])
#
#     await message.answer(
#         "🎉 <b>Оплата успешна!</b>\n\n"
#         "💎 Подписка активирована!\n"
#         f"📅 Действует до: <b>{sub_until.strftime('%d.%m.%Y %H:%M')}</b>\n"
#         f"📋 Тип: <b>{sub_type}</b>\n\n"
#         "✨ Все функции разблокированы\n\n"
#         "Спасибо за поддержку! 🙏",
#         reply_markup=UserKeyboards.main_menu(True),
#         parse_mode="HTML"
#     )
#
#     logger.info(f"✅ Подписка {sub_type} успешно активирована для {user_id} за {stars} ⭐️")


# ============= ПРОФИЛЬ =============
@router.message(F.text == '👤Профиль')
async def profile_txt(message: Message, state: FSMContext):
    """Показать профиль"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    sessions = session_mgr.get_sessions(user_id)

    text = (
        f"👤 <b>ВАШ ПРОФИЛЬ</b>\n\n"
        f"📛 Имя: <b>{user['first_name']}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👨‍💻 Username: @{user['username'] or 'не указан'}\n"
        f"📱 Аккаунтов: <b>{len(sessions)}/100</b>\n\n"
    )

    if await db.has_active_subscription(user_id):
        sub_until = datetime.fromisoformat(user['subscription_until'])
        text += (
            f"💎 <b>Подписка активна</b>\n"
            f"📅 До: <b>{sub_until.strftime('%d.%m.%Y %H:%M')}</b>"
        )
    else:
        text += "⚠️ <i>Подписка неактивна</i>"

    await message.answer(
        text,
        reply_markup=UserKeyboards.profile_menu(
            user.get('subscription_type'),
            user.get('subscription_until')
        ),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    """Показать профиль"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)

    sessions = session_mgr.get_sessions(user_id)

    text = (
        f"👤 <b>ВАШ ПРОФИЛЬ</b>\n\n"
        f"📛 Имя: <b>{user['first_name']}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👨‍💻 Username: @{user['username'] or 'не указан'}\n"
        f"📱 Аккаунтов: <b>{len(sessions)}/100</b>\n\n"
    )

    if await db.has_active_subscription(user_id):
        sub_until = datetime.fromisoformat(user['subscription_until'])
        text += (
            f"💎 <b>Подписка активна</b>\n"
            f"📅 До: <b>{sub_until.strftime('%d.%m.%Y %H:%M')}</b>"
        )
    else:
        text += "⚠️ <i>Подписка неактивна</i>"

    await callback.message.answer(
        text,
        reply_markup=UserKeyboards.profile_menu(
            user.get('subscription_type'),
            user.get('subscription_until')
        ),
        parse_mode="HTML"
    )
    await callback.answer()


# ============= МОИ АККАУНТЫ =============
@router.message(F.text == '👥Мои аккаунты')
async def reply_accs(message: Message):
    user_id = message.from_user.id
    if await check_subs(user_id) is False:
        await message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        # Проверка подписки
        if not await db.has_active_subscription(user_id):
            await message.answer("❌ Нужна подписка!", show_alert=True)
            return

        # Проверка API ключей
        if not await check_api(user_id):
            await message.answer(NO_API_TEXT, parse_mode="HTML")
            return

        page = 0

        sessions = session_mgr.get_sessions(user_id)
        states = session_mgr.get_account_states(user_id)

        if not sessions:
            text = (
                "📱 <b>МОИ АККАУНТЫ</b>\n\n"
                "📭 У вас пока нет аккаунтов\n\n"
                "Загрузите ZIP с .session файлами!"
            )
        else:
            text = (
                f"📱 <b>МОИ АККАУНТЫ</b>\n\n"
                f"📊 Всего: <b>{len(sessions)}</b>\n"
                f"📄 Страница: <b>{page + 1}</b>\n\n"
                f"<i>Нажмите на аккаунт для деталей</i>"
            )

        await message.answer(
            text,
            reply_markup=UserKeyboards.accounts_list(sessions, states, page, user_id=user_id),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("my_accounts:"))
async def show_accounts(callback: CallbackQuery):
    """Показать список аккаунтов"""
    user_id = callback.from_user.id

    # Проверка подписки
    if not await db.has_active_subscription(user_id):
        await callback.answer("❌ Нужна подписка!", show_alert=True)
        return

    # Проверка API ключей
    if not await check_api(user_id):
        await callback.answer("🔑 API ключи не настроены!", show_alert=True)
        await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
        return

    page = int(callback.data.split(":")[1])
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        sessions = session_mgr.get_sessions(user_id)
        states = session_mgr.get_account_states(user_id)

        if not sessions:
            text = (
                "📱 <b>МОИ АККАУНТЫ</b>\n\n"
                "📭 У вас пока нет аккаунтов\n\n"
                "Загрузите ZIP с .session файлами!"
            )
        else:
            text = (
                f"📱 <b>МОИ АККАУНТЫ</b>\n\n"
                f"📊 Всего: <b>{len(sessions)}</b>\n"
                f"📄 Страница: <b>{page + 1}</b>\n\n"
                f"<i>Нажмите на аккаунт для деталей</i>"
            )

        await callback.message.edit_text(
            text,
            reply_markup=UserKeyboards.accounts_list(sessions, states, page, user_id=user_id),
            parse_mode="HTML"
        )
        await callback.answer()


@router.callback_query(F.data == "add_zip")
async def add_accounts(callback: CallbackQuery, state: FSMContext):
    """Выбор типа сессий для добавления"""
    await callback.message.answer(
        "<b>📦 Добавление аккаунтов</b>\n\n"
        "Выберите тип сессий, которые хотите загрузить:",
        parse_mode="HTML",
        reply_markup=choice
    )
    await callback.answer()


@router.callback_query(F.data == "telethon")
async def callback_pyro_zip(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправьте мне ZIP-архив с сессиями Hydrogram (или pyrogram).")
    await state.set_state(ZipStates.waiting_for_zip)
    await callback.answer()


@router.message(StateFilter(ZipStates.waiting_for_zip), F.document.mime_type == "application/zip")
async def handle_zip_archive(message: Message, state: FSMContext):
    user_id = message.from_user.id
    extract_path = Path(f"users/{user_id}")
    extract_path.mkdir(parents=True, exist_ok=True)

    # Временный путь для ZIP-архива
    zip_path = f"temp_{user_id}.zip"

    # Правильный способ скачивания в aiogram 3.x
    await bot.download(file=message.document, destination=zip_path)

    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_path)

            # Подсчёт сессий
            session_files = list(extract_path.rglob("*.session"))
            added_accounts = len(session_files)

            if added_accounts > 0:
                await message.answer(
                    f"Архив успешно распакован!\n"
                    f"Добавлено аккаунтов: <b>{added_accounts}</b>", parse_mode="HTML"
                )
            else:
                await message.answer(
                    "Архив распакован, но в нём не найдено ни одного файла с расширением <code>.session</code>.\n",
                    parse_mode="HTML"
                               "Проверьте содержимое архива."
                )

    except zipfile.BadZipFile:
        await message.answer("Ошибка: отправленный файл не является валидным ZIP-архивом.")
    except Exception as e:
        await message.answer("Произошла ошибка при распаковке архива.")
        print(e)
    finally:

        if os.path.exists(zip_path):
            os.remove(zip_path)

    await state.clear()


def _resolve_session_ref(ref: str, sessions: list) -> str:
    """
    Разрешает ref в имя сессии.
    ref может быть числовым индексом (из новых кнопок) или именем сессии.
    """
    if ref.isdigit():
        idx = int(ref)
        if 0 <= idx < len(sessions):
            return sessions[idx]
    return ref


def set_status(user_id: int, session_name: str, emoji: str):
    path = Path(f"users/{user_id}/account_states.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Плоская структура: { session_name: emoji } — так же читает session_manager
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[session_name] = emoji
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

@router.callback_query(F.data.startswith("session_idx:"))
async def show_session_by_index(callback: CallbackQuery):
    """Детали аккаунта по числовому индексу (FIX: BUTTON_DATA_INVALID)"""
    user_id = callback.from_user.id
    ref = callback.data.split(":", 1)[1]
    sessions = session_mgr.get_sessions(user_id)
    session_name = _resolve_session_ref(ref, sessions)

    # Нельзя менять callback.data напрямую (frozen pydantic model)
    # Поэтому дублируем логику show_session_detail прямо здесь
    if not db.has_active_subscription(user_id):
        await callback.answer("❌ Нужна подписка!", show_alert=True)
        return

    # Проверка API ключей
    if not await check_api(user_id):
        await callback.answer("🔑 API ключи не настроены!", show_alert=True)
        await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
        return

    await callback.message.edit_text(
        "⏳ <b>Подключаюсь к аккаунту...</b>\n\n<i>Получаю актуальную информацию</i>",
        parse_mode="HTML"
    )

    _, info = await session_mgr.get_session_info(session_name, user_id)

    if _ is False:
        raw_error = str(info).lower()
        if "frozen" in raw_error or "frozen_method_invalid" in raw_error:
            error_desc = "Аккаунт заморожен ❄️\n\nTelegram ввёл режим «только чтение».\nРазморозится автоматически через 1–7 дней."
        elif "authkeyunregistered" in raw_error or "unregistered" in raw_error:
            error_desc = "Сессия невалидна или разлогинена ❌\n\nАккаунт вышел из сессии.\nРекомендуется удалить эту сессию."
        elif "timeout" in raw_error or "connection" in raw_error or "proxy" in raw_error:
            error_desc = "Проблема с подключением ⚠️\n\nТаймаут — возможно, прокси не работает.\nПопробуйте позже."
        elif "flood" in raw_error:
            error_desc = "Флудвейт ⏳\n\nTelegram временно ограничил аккаунт.\nПодождите и попробуйте снова."
        else:
            error_desc = str(info)
        set_status(user_id, session_name, "🔴")
        text = (
            f"❌ <b>Ошибка подключения</b>\n\n"
            f"📱 <b>Сессия:</b> <code>{session_name}</code>\n\n"
            f"{error_desc}"
        )
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔙 Назад к аккаунтам", callback_data="my_accounts:0"))
        kb.row(InlineKeyboardButton(text="🗑 Удалить сессию", callback_data=f"delete:{session_name}"))
        reply_markup = kb.as_markup()
    else:
        set_status(user_id, session_name, "🟢")
        full_name = info.get('full_name') or "Неизвестно"
        user_id_val = info.get('user_id') or "—"
        phone = info.get('phone') or "Скрыт"
        username = f"@{info.get('username')}" if info.get('username') else "Нет"
        status_text = info.get('status') or "Неизвестно"
        is_premium = info.get('is_premium')
        has_2fa = info.get('has_2fa')
        spamblock = info.get('spamblock') or "Неизвестно"

        premium_icon = "💎 Premium" if is_premium else "👤 Обычный"
        fa_icon = "✅ Включена" if has_2fa == "Подключена" else "❌ Выключена"
        spam_icon = "✅ Чист" if spamblock == "Отсутствует" else ("🚫 Есть" if spamblock == "Есть" else f"⚠️ {spamblock}")
        online_icon = "🟢" if status_text == "Активен" else "⚫️"

        text = (
            f"━━━━━━━━━━━━━━━━━\n"
            f"  📋 <b>ПРОФИЛЬ АККАУНТА</b>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Имя:</b> {full_name}\n"
            f"🆔 <b>ID:</b> <code>{user_id_val}</code>\n"
            f"📱 <b>Телефон:</b> <code>{phone}</code>\n"
            f"🔗 <b>Username:</b> {username}\n\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"{online_icon} <b>Статус:</b> {status_text}\n"
            f"🏅 <b>Аккаунт:</b> {premium_icon}\n"
            f"🔐 <b>2FA:</b> {fa_icon}\n"
            f"🛡 <b>Спамблок:</b> {spam_icon}\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<i>🕐 Обновлено только что</i>"
        )
        reply_markup = UserKeyboards.account_detail(session_name, sessions)

    await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("session:"))
async def show_session_detail(callback: CallbackQuery, session_name: str = None):
    """Детали аккаунта"""
    user_id = callback.from_user.id

    if not await db.has_active_subscription(user_id):
        await callback.answer("❌ Нужна подписка!", show_alert=True)
        return

    # Проверка API ключей
    if not await check_api(user_id):
        await callback.answer("🔑 API ключи не настроены!", show_alert=True)
        await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
        return

    if session_name is None:
        session_name = callback.data.rsplit(":", 1)[-1]

    await callback.message.edit_text(
        "⏳ <b>Подключаюсь к аккаунту...</b>\n\n<i>Получаю актуальную информацию</i>",
        parse_mode="HTML"
    )

    _, info = await session_mgr.get_session_info(session_name, user_id)

    # ========== ЕСЛИ ЕСТЬ ОШИБКА ==========
    if _ is False:
        raw_error = str(info).lower()

        if "frozen" in raw_error or "frozen_method_invalid" in raw_error:
            error_desc = "Аккаунт заморожен ❄️\n\nTelegram ввёл режим «только чтение».\nНельзя писать, вступать в чаты или отправлять сообщения.\nРазморозится автоматически через 1–7 дней."
        elif "authkeyunregistered" in raw_error or "unregistered" in raw_error:
            error_desc = "Сессия невалидна или разлогинена ❌\n\nАккаунт вышел из сессии на другом устройстве.\nРекомендуется удалить эту сессию."
        elif "timeout" in raw_error or "connection" in raw_error or "proxy" in raw_error:
            error_desc = "Проблема с подключением ⚠️\n\nТаймаут — возможно, прокси не работает или слабый интернет.\nПопробуйте позже."
        elif "flood" in raw_error:
            error_desc = "Флудвейт ⏳\n\nTelegram временно ограничил действия аккаунта.\nПодождите и попробуйте снова."
        else:
            error_desc = str(info)

        text = (
            f"❌ <b>Ошибка подключения</b>\n\n"
            f"📱 <b>Сессия:</b> <code>{session_name}</code>\n\n"
            f"{error_desc}"
        )

        # ПРОСТАЯ КНОПКА НАЗАД — БЕЗОПАСНО
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔙 Назад к аккаунтам", callback_data="my_accounts:0"))
        # Опционально: кнопка удаления
        kb.row(InlineKeyboardButton(text="🗑 Удалить сессию", callback_data=f"delete:{session_name}"))
        reply_markup = kb.as_markup()
    # ========== УСПЕШНОЕ ПОДКЛЮЧЕНИЕ ==========
    else:
        full_name = info.get('full_name') or "Неизвестно"
        user_id_val = info.get('user_id') or "—"
        phone = info.get('phone') or "Скрыт"
        username = f"@{info.get('username')}" if info.get('username') else "Нет"
        status_text = info.get('status') or "Неизвестно"
        is_premium = info.get('is_premium')
        has_2fa = info.get('has_2fa')
        spamblock = info.get('spamblock') or "Неизвестно"

        # Иконки
        premium_icon = "💎 Premium" if is_premium else "👤 Обычный"
        fa_icon = "✅ Включена" if has_2fa == "Подключена" else "❌ Выключена"
        spam_icon = "✅ Чист" if spamblock == "Отсутствует" else ("🚫 Есть" if spamblock == "Есть" else f"⚠️ {spamblock}")
        online_icon = "🟢" if status_text == "Активен" else "⚫️"

        text = (
            f"━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id='5980813840252671861'>🟢</tg-emoji> <b>ПРОФИЛЬ АККАУНТА</b>\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Имя:</b> {full_name}\n"
            f"🆔 <b>ID:</b> <code>{user_id_val}</code>\n"
            f"<tg-emoji emoji-id='5983361898320501111'>🟢</tg-emoji> <b>Телефон:</b> <code>{phone}</code>\n"
            f"<tg-emoji emoji-id='5390863029464213754'>🔗</tg-emoji> <b>Username:</b> {username}\n\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"{online_icon} <b>Статус:</b> {status_text}\n"
            f"<tg-emoji emoji-id='5981092119773714425'>🏅</tg-emoji> <b>Аккаунт:</b> {premium_icon}\n"
            f"<tg-emoji emoji-id='5251203410396458957'>👤</tg-emoji> <b>2FA:</b> {fa_icon}\n"
            f"<tg-emoji emoji-id='5447410659077661506'>🛡</tg-emoji> <b>Спамблок:</b> {spam_icon}\n\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<i>🕐 Обновлено только что</i>"
        )
        sessions = [f.name for f in Path(f"users/{user_id}").glob("*.session")]
        reply_markup = UserKeyboards.account_detail(session_name, sessions)

    await callback.message.edit_text(
        text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    await callback.answer()


# @router.message(F.photo)
# async def get_photo(message: Message):
#     photo_data = message.photo[-1]
#     print('Фото:', photo_data)


@router.callback_query(F.data.startswith("refresh:"))
async def refresh_session(callback: CallbackQuery):
    """Обновить информацию об аккаунте"""
    user_id = callback.from_user.id

    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
        if not db.has_active_subscription(user_id):
            await callback.answer("❌ Нужна подписка!", show_alert=True)
            return

        session_name = callback.data.split(":", 1)[1]

        await callback.answer("🔄 Обновляю информацию...")

        # Уведомляем пользователя, что идёт обновление
        await callback.message.edit_text(
            "⏳ <b>Подключаюсь к аккаунту...</b>\n\n<i>Получаю свежие данные</i>",
            parse_mode="HTML"
        )

        # Получаем свежую информацию
        info = await session_mgr.get_session_info(session_name, user_id)

        # Используем ту же логику, что и в show_session_detail
        if info['error']:
            raw_error = info.get('error', '').lower()

            if "frozen" in raw_error or "frozen_method_invalid" in raw_error:
                error_text = "Аккаунт заморожен ❄️\n\nВременный read-only режим от Telegram.\nРазморозится сам через 1–7 дней."
            elif "authkeyunregistered" in raw_error or "unregistered" in raw_error:
                error_text = "Сессия невалидна или разлогинена ❌\n\nУдалите эту сессию."
            elif "timeout" in raw_error or "connection" in raw_error:
                error_text = "Таймаут подключения ⚠️\n\nПроблема с прокси или сетью. Попробуйте еще раз подключиться к сессии."
            elif "flood" in raw_error:
                error_text = "Флудвейт ⏳\n\nПодождите некоторое время."
            else:
                error_text = f"{info['error']}"

            text = (
                f"❌ <b>Ошибка аккаунта</b>\n\n"
                f"📱 <b>Сессия:</b> <code>{session_name}</code>\n\n"
                f"{error_text}"
            )
            sessions = [f.name for f in Path(f"users/{user_id}").glob("*.session")]
            reply_markup = UserKeyboards.account_detail(session_name, sessions)  # или back-кнопка
        else:

            status = "🟢" if info.get('is_valid', False) else "🔴"

            full_name = info.get('full_name') or "Неизвестно"
            user_id_val = info.get('user_id') or "—"
            phone = info.get('phone') or "Скрыт"
            username = info.get('username') or "Нет"
            status_text = info.get('status') or "Неизвестно"

            text = (
                f"{status} <b>ИНФОРМАЦИЯ ОБ АККАУНТЕ</b>\n\n",
                f"<tg-emoji emoji-id='5980955947835594177'>🟢</tg-emoji> <b>{full_name}</b>\n",
                f"🆔 ID: <code>{user_id_val}</code>\n",
                f"<tg-emoji emoji-id='5983361898320501111'>🟢</tg-emoji> Телефон: <code>{phone}</code>\n",
                f"<tg-emoji emoji-id='5390863029464213754'>🟢</tg-emoji> Username: @{username}\n\n",
                f"<tg-emoji emoji-id='5981092119773714425'>🟢</tg-emoji> Статус: {'Premium' if info.get('is_premium') else 'Обычный'}\n",
                f"<tg-emoji emoji-id='5251203410396458957'>🟢</tg-emoji> 2FA: {'✅' if info.get('has_2fa') else '❌'}\n",
                f"<tg-emoji emoji-id='5980813840252671861'>🟢</tg-emoji> Статус: {status_text}\n\n",
                f"<i>Обновлено только что</i>"
            )

        await callback.message.edit_text(
            text,
            reply_markup=UserKeyboards.account_detail(session_name),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("get_code:"))
async def get_login_code(callback: CallbackQuery):
    """Получить код входа"""
    user_id = callback.from_user.id
    session_name = callback.data.split(":", 1)[1]

    await callback.answer("🔍 Ищу код...")

    progress = await callback.message.answer("⏳ <b>Получаю код...</b>", parse_mode="HTML")

    try:
        code = await session_mgr.get_login_code(session_name, user_id)

        if code:
            await progress.edit_text(
                f"🔑 <b>Код получен!</b>\n\n"
                f"📱 Аккаунт: {session_name.replace('.session', '')}\n"
                f"🔢 Код: <code>{code}</code>\n\n"
                f"<i>Скопируйте и используйте</i>",
                parse_mode="HTML"
            )
        else:
            await progress.edit_text(
                "❌ <b>Код не найден</b>\n\n"
                "Возможно, Telegram ещё не прислал код\n"
                "Проверьте телефон вручную",
                parse_mode="HTML"
            )
    except Exception as e:
        await progress.edit_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")


@router.callback_query(F.data.startswith("check_valid:"))
async def check_validity(callback: CallbackQuery):
    """Проверить валидность"""
    user_id = callback.from_user.id
    session_name = callback.data.split(":", 1)[1]

    await callback.answer("🔍 Проверяю...")

    raw = await session_mgr.check_session_valid(session_name, user_id)
    status = raw[0] if isinstance(raw, tuple) else raw

    if status == "🟢":
        await callback.answer("✅ Аккаунт валиден!", show_alert=True)
    else:
        await callback.answer("❌ Аккаунт невалиден!", show_alert=True)

    callback.data = f"session:{session_name}"
    await show_session_detail(callback)


@router.callback_query(F.data.startswith("delete:"))
async def confirm_delete(callback: CallbackQuery):
    """Подтверждение удаления"""
    session_name = callback.data.split(":", 1)[1]

    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение</b>\n\n"
        f"Удалить аккаунт:\n"
        f"<b>{session_name.replace('.session', '')}</b>?\n\n"
        f"<i>Действие необратимо!</i>",
        reply_markup=UserKeyboards.confirm_delete(session_name),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete:"))
async def delete_session(callback: CallbackQuery):
    """Удалить сессию"""
    user_id = callback.from_user.id
    session_name = callback.data.split(":", 1)[1]

    success = session_mgr.delete_session(session_name, user_id)

    if success:
        await callback.answer("✅ Удалено!", show_alert=True)

        sessions = session_mgr.get_sessions(user_id)
        states = session_mgr.get_account_states(user_id)

        await callback.message.edit_text(
            f"✅ <b>Аккаунт удалён!</b>\n\n"
            f"Осталось: {len(sessions)}",
            reply_markup=UserKeyboards.accounts_list(sessions, states, 0, user_id=user_id),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Ошибка!", show_alert=True)


@router.callback_query(F.data.startswith("validate_all:"))
async def validate_all(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])

    sessions = session_mgr.get_sessions(user_id)
    if await check_subs(user_id) is False:
        return await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )

    if not sessions:
        await callback.answer("📭 Нет аккаунтов для проверки", show_alert=True)
        return

    await callback.answer("🔄 Запущена проверка...")

    # Простой прогресс без спама — обновляем счётчик
    progress_msg = await callback.message.answer(
        f"⏳ <b>Проверка аккаунтов...</b>"
        f"0 / {len(sessions)}",
        parse_mode="HTML"
    )

    from modules.kb_layout_settings import is_auto_delete_enabled
    auto_delete = is_auto_delete_enabled(user_id)

    valid = invalid = checked = deleted = 0
    semaphore = asyncio.Semaphore(3)

    async def check_one(full_session_name: str):
        nonlocal valid, invalid, checked, deleted
        async with semaphore:
            try:
                raw = await session_mgr.check_session_valid(full_session_name, user_id)
                result = raw[0] if isinstance(raw, tuple) else raw
            except Exception as e:
                logger.error(f"check_one {full_session_name}: {e}")
                result = "🔴"

            if result == "🟢":
                valid += 1
            else:
                invalid += 1
                if auto_delete:
                    try:
                        session_mgr.delete_session(full_session_name, user_id)
                        deleted += 1
                    except Exception as e:
                        logger.error(f"auto-delete {full_session_name}: {e}")

            checked += 1

            if checked % 5 == 0 or checked == len(sessions):
                try:
                    await progress_msg.edit_text(
                        f"⏳ <b>Проверка аккаунтов...</b>"
                        f"{checked} / {len(sessions)} | 🟢 {valid} 🔴 {invalid}",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

    await asyncio.gather(*[check_one(s) for s in sessions], return_exceptions=True)

    # Итог в боту
    sessions_after = session_mgr.get_sessions(user_id)
    states = session_mgr.get_account_states(user_id)
    final_markup = UserKeyboards.accounts_list(sessions_after, states, page, user_id=user_id)

    del_text = f"🗑 Автоудалено: <b>{deleted}</b>" if auto_delete and deleted else ""

    await progress_msg.edit_text(
        f"✅ <b>Проверка завершена</b>"
        f"Всего: <b>{len(sessions)}</b>"
        f"🟢 Валидных: <b>{valid}</b>"
        f"🔴 Невалидных: <b>{invalid}</b>{del_text}",
        reply_markup=final_markup,
        parse_mode="HTML"
    )


# ============= НАСТРОЙКИ ВИДА КЛАВИАТУРЫ =============

@router.callback_query(F.data.startswith("kb_layout_menu:"))
async def kb_layout_menu_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    from modules.kb_layout_settings import get_layout
    l = get_layout(user_id)
    text = (
        "⚙️ <b>Настройки вида списка аккаунтов</b>"
        f"📄 На странице: <b>{l['per_page']}</b>"
        f"📐 Кнопок в строке: <b>{l['cols']}</b>"
        f"✏️ Длина имени: <b>{l['name_length']}</b>"
        f"👁 Статус: <b>{'Вкл' if l['show_status'] else 'Выкл'}</b>"
        f"🗑 Автоудаление: <b>{'Вкл' if l['auto_delete_invalid'] else 'Выкл'}</b>"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=UserKeyboards.kb_layout_menu(user_id, page), parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=UserKeyboards.kb_layout_menu(user_id, page), parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "kbl_noop")
async def kbl_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("kbl:"))
async def kbl_adjust(callback: CallbackQuery):
    """kbl:{field}:{inc|dec|toggle}:{page}"""
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    field, action, page = parts[1], parts[2], int(parts[3])

    from modules.kb_layout_settings import get_layout, set_layout
    l = get_layout(user_id)

    limits = {
        "per_page":    (5, 50, 5),
        "cols":        (1, 4, 1),
        "name_length": (5, 30, 1),
    }

    if action == "toggle":
        set_layout(user_id, **{field: not l[field]})
    elif action in ("inc", "dec") and field in limits:
        mn, mx, step = limits[field]
        cur = l[field]
        new_val = min(mx, cur + step) if action == "inc" else max(mn, cur - step)
        set_layout(user_id, **{field: new_val})
    await callback.answer()

    from modules.kb_layout_settings import get_layout as gl
    updated = gl(user_id)
    text = (
        "⚙️ <b>Настройки вида списка аккаунтов</b>"
        f"📄 На странице: <b>{updated['per_page']}</b>"
        f"📐 Кнопок в строке: <b>{updated['cols']}</b>"
        f"✏️ Длина имени: <b>{updated['name_length']}</b>"
        f"👁 Статус: <b>{'Вкл' if updated['show_status'] else 'Выкл'}</b>"
        f"🗑 Автоудаление: <b>{'Вкл' if updated['auto_delete_invalid'] else 'Выкл'}</b>"
    )
    try:
        await callback.message.edit_text(
            text, reply_markup=UserKeyboards.kb_layout_menu(user_id, page), parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data == "add_accounts")  # Или какой у тебя callback на "➕ Добавить"
async def show_add_accounts_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "➕ <b>ДОБАВИТЬ АККАУНТЫ</b>\n\n"
        "Выберите способ добавления:",
        reply_markup=UserKeyboards.add_accounts_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


from aiogram.types import CallbackQuery
from aiogram import F
import random


# TELE_SESSIONS_BASE = "users223"

@router.callback_query(F.data == "add_phone")
async def start_add_phone(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "📱 Отправьте номер телефона в международном формате\n"
        "Например: +79991234567"
    )
    await state.set_state(AddPhoneStates.waiting_for_phone)


from hydrogram import Client
from hydrogram.errors import (
    FloodWait, PhoneNumberInvalid, PhoneCodeInvalid,
    PhoneCodeExpired, SessionPasswordNeeded
)
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram import F
import asyncio
import os


# @router.message(F.photo)
# async def get_photo_file_id(message: Message):
#     # Telegram присылает несколько вариантов размера одного фото.
#     # Последний в списке [-1] — самый большой и качественный.
#     photo_id = message.photo[-1].file_id
#     print(photo_id)
#     await message.reply(f"✅ <b>File ID этой фотографии:</b>\n\n<code>{photo_id}</code>")

@router.message(AddPhoneStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()

    if not phone.startswith('+'):
        await message.answer("❌ Номер должен начинаться с +\nПопробуйте снова:")
        return

    if not API_PAIRS:
        await message.answer("❌ Ошибка конфигурации: API пары не настроены")
        await state.clear()
        return

    user_id = message.from_user.id

    session_dir = os.path.join(f'users223/{user_id}')
    os.makedirs(session_dir, exist_ok=True)

    session_name = phone.replace('+', '')
    session_path = os.path.join(session_dir, session_name)

    try:
        # Создаём клиент Hydrogram
        client = await session_mgr.create_session_by_phone(user_id=user_id,
                                                           phone=phone)

        await client.connect()

        # Отправляем код
        sent_code = await client.send_code(phone)

        await state.update_data(
            phone=phone,
            phone_code_hash=sent_code.phone_code_hash,
            client=client,
            session_path=session_path
        )

        await message.answer(
            f"✅ Код отправлен на номер {phone}\n"
            "📨 Отправьте полученный код (5 цифр):"
        )
        await state.set_state(AddPhoneStates.waiting_for_code)

    except FloodWait as e:
        await message.answer(f"⏳ Слишком много попыток. Подождите {e.value} секунд")
        await state.clear()
    except PhoneNumberInvalid:
        await message.answer("❌ Неверный формат номера телефона")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке кода: {str(e)}")
        await state.clear()


@router.message(AddPhoneStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip().replace('-', '').replace(' ', '')

    data = await state.get_data()
    client: Client = data['client']
    phone = data['phone']
    phone_code_hash = data['phone_code_hash']

    try:
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code
        )

        me = await client.get_me()
        await message.answer(
            "✅ Сессия успешно создана!\n"
            f"ID аккаунта: {me.id}\n"
        )
        await client.disconnect()
        await state.clear()

    except SessionPasswordNeeded:
        await message.answer(
            "🔐 Включена двухфакторная аутентификация\n"
            "Введите пароль от аккаунта:"
        )
        await state.set_state(AddPhoneStates.waiting_for_2fa)

    except (PhoneCodeInvalid, PhoneCodeExpired):
        await message.answer("❌ Неверный или истекший код.\nНачните заново: /add_account")
        await client.disconnect()
        await state.clear()

    except FloodWait as e:
        await message.answer(f"⏳ Флудвейт: подождите {e.value} секунд")
        await client.disconnect()
        await state.clear()

    except Exception as e:
        await message.answer(f"❌ Ошибка авторизации: {str(e)}")
        await client.disconnect()
        await state.clear()


@router.message(AddPhoneStates.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext):
    password = message.text.strip()

    data = await state.get_data()
    client: Client = data['client']

    try:
        await asyncio.sleep(1.2)
        await message.delete()

        await client.check_password(password)

        me = await client.get_me()
        await message.answer(
            "✅ Сессия успешно создана!\n"
            f"ID аккаунта: {me.id}\n"
        )

        await client.disconnect()
        await state.clear()

    except Exception as e:
        await message.answer(f"❌ Неверный пароль или ошибка: {str(e)}")


@router.callback_query(F.data == "cancel_auth")
async def cancel_auth(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    client: Client = data.get("client")

    if client and client.is_connected:
        try:
            await client.disconnect()
        except:
            pass

    session_path = data.get("session_path")
    if session_path and os.path.exists(session_path + ".session"):
        try:
            os.remove(session_path + ".session")
        except:
            pass

    await state.clear()

    await callback.message.edit_text(
        "❌ <b>Авторизация отменена</b>",
        reply_markup=UserKeyboards.add_accounts_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


class help(StatesGroup):
    wait_msg = State()


@router.message(Command('help'))
async def helpp(message: Message):
    await message.answer(
        text='<b>Что-то случилось?</b>\n\n<i>По вопросам и помощи</i> - @senders_support (если у вас бан - пишите в комментарии канала)',
        reply_markup=kb.send_to_help,
        parse_mode='html')


@router.message(F.text == '💬Поддержка')
async def help_reply(message: Message):
    await message.answer(
        text='<b>Что-то случилось?</b>\n\n<i>По вопросам и помощи</i> - @senders_support (если у вас бан - пишите в комментарии канала или отправьте сообщение через бота)',
        reply_markup=kb.send_to_help, parse_mode='html')


@router.callback_query(F.data == 'support')
async def help_data(callback: CallbackQuery):
    await callback.message.answer(
        text='<b>Что-то случилось?</b>\n\n<i>По вопросам и помощи</i> - @senders_support (если у вас бан - пишите в комментарии канала)',
        reply_markup=kb.send_to_help, parse_mode='html')


@router.callback_query(F.data == 'send_to_helpers')
async def send_to_helpers(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(text='<b>Отправьте ваше обращение:</b> ')
    await state.set_state(help.wait_msg)


@router.message(help.wait_msg)
async def wait_help_msg(message: Message, state: FSMContext):
    await state.update_data(caption=message.caption)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption
        for admin in ADMIN_IDS:
            await bot.send_message(text='<b>Новое обращение!</b>\n\n'
                                        f'ID: {message.from_user.id}\n'
                                        f'Username: {message.from_user.username}\n\n'
                                        f'Текст Обращения: <blockquote expandable>{caption}</blockquote>\n'
                                        'Фото отправлено ниже', chat_id=admin
                                   )
            await bot.send_photo(chat_id=admin, photo=photo.file_id, caption='Прикрепленное фото')
            await state.clear()
        await message.answer('Сообщение отправлено админам!')

    elif message.text:
        user_id = message.from_user.id
        for admin in ADMIN_IDS:
            await bot.send_message(text='<b>Новое обращение!</b>\n\n'
                                        f'ID: {message.from_user.id}\n'
                                        f'Username: {message.from_user.username}\n\n'
                                        f'Текст Обращения: <blockquote expandable>{message.text}</blockquote>\n',
                                   chat_id=admin, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✉️ Написать", callback_data=f"admin_msg:{user_id}")]]))

        await state.clear()
        await message.answer('Сообщение отправлено админам!')


class lists(StatesGroup):
    list_url = State()


@router.callback_query(F.data == 'list_url')
async def list_url(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer('<b>🔗Отправьте ссылку на папку из которой необходимо извлечь ссылки: </b>\n\n'
                                  'Внимание! В папке не должно быть более 100 чатов.\n'
                                  '<i>Бот пришлет вам .txt файл со всеми извлеченными ссылками</i>')
    await state.set_state(lists.list_url)


@router.message(lists.list_url)
async def list_url2(message: Message, state: FSMContext):
    msg = await message.reply('<i>⏳Начинаю извлечение.</i>')
    await asyncio.sleep(0.45)
    await msg.edit_text('<i>⌛Начинаю извлечение..</i>')
    await asyncio.sleep(0.45)
    await msg.edit_text('<i>⏳Начинаю извлечение...</i>')
    await state.update_data(list_url=msg.text)

    user_id = int(message.from_user.id)
    list_url = str(message.text)
    await state.clear()
    await get_list_url(list_url, user_id, msg)



keyboard = kb.Keyboards()
from modules.core import get_user_api, set_current_api


@router.callback_query(F.data == 'back_setting')
@router.callback_query(F.data == 'user_settings')
async def user_settings(callback: CallbackQuery):
    await callback.message.edit_text(
        text="<tg-emoji emoji-id='5341715473882955310'></tg-emoji><b>Настройки</b>\n\n"
             "Выберите необходимый пункт:",
        reply_markup=keyboard.user_settings_kb()
    )


@router.message(F.text.contains('Настройки'))
async def api_msg_setting(message: Message):
    await message.reply(
        text="<tg-emoji emoji-id='5341715473882955310'>⚙️</tg-emoji><b>Настройки</b>\n\n"
             "Выберите необходимый пункт:",
        reply_markup=keyboard.user_settings_kb()
    )


@router.callback_query(F.data == 'api_settings')
async def api_settings(callback: CallbackQuery):
    user_id = callback.from_user.id
    numb = await get_user_api(user_id, 1)
    if numb == False or numb is None:
        api_n = 'Не установлен'
        text = '🔑<b>Настройка API ключей</b>\nГайд по получению ключей - https://telegra.ph/Poluchenie-Telegram-API-ID--Hash-02-21\n\nAPI ключи не установлены.'
        await callback.message.edit_text(text=text,
                                         reply_markup=keyboard.api_set_kb()
                                         )

    else:
        apis = await get_user_api(user_id, 1)

        idx = str(apis["api_id"])
        api_hash = str(apis["api_hash"])
        text = f'🔑<b>Настройка API ключей</b>\nГайд по получению ключей - https://telegra.ph/Poluchenie-Telegram-API-ID--Hash-02-21\n\nТекущий API_ID: <code>{idx}</code>\n\nТекущий API_HASH: <code>{api_hash}</code>\n'

        await callback.message.edit_text(text=text,
                                         reply_markup=keyboard.api_set_kb()
                                         )


class API(StatesGroup):
    api_id = State()
    api_hash = State()


@router.callback_query(F.data == 'api_set')
async def set_apis(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.answer(text="<b>Отправьте новый API_ID(цифровой формат): </b>")
    await state.set_state(API.api_id)


@router.message(API.api_id)
async def set_api_id(message: Message, state: FSMContext):
    await state.update_data(api_id=message.text)
    await message.reply(text='<b>Отправьте новый API_HASH:</b>')
    await state.set_state(API.api_hash)


from modules.core import set_user_api


@router.message(API.api_hash)
async def set_api_hash(message: Message, state: FSMContext):
    data = await state.get_data()
    api_id = data['api_id']
    api_hash = message.text
    msg = await message.reply(text='<i>Обновляю данные...</i>')
    user_id = message.from_user.id
    await set_user_api(user_id, 1, api_id, api_hash)
    await set_current_api(user_id, 1)
    apis = await get_user_api(user_id, 1)
    idx = apis["api_id"]
    api_hash = apis["api_hash"]
    text = f'🔑<b>Настройка API ключей</b>\n\nТекущий API_ID: <code>{idx}</code>\nТекущий API_HASH: <code>{api_hash}</code>\n'
    await msg.answer(text=text, reply_markup=keyboard.api_set_kb())