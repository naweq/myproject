# ==========================================
# ФАЙЛ: bot/handlers/inviting_handlers.py
# ОПИСАНИЕ: Обработчики инвайтинга
# ==========================================

import asyncio
import logging
import os
from typing import List

# from PyQt5.QtGui.QRawFont import style
from aiogram.types import FSInputFile
from modules.text_temp import KEYB
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from handlers.user_handlers import check_subs, check_api, NO_API_TEXT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from modules.task_manager import task_manager, TaskType, TaskStatus
from modules.account_cache import prefetch_accounts_meta
from modules.database import Database
from modules.session_manager import SessionManager
from services.inviting_service import InvitingService
from keyboards.user_keyboards import UserKeyboards
from modules.validators import TextValidator

logger = logging.getLogger(__name__)
router = Router()
temp_kb = KEYB()

db = Database()
session_mgr = SessionManager()
inviting_svc = InvitingService()

if not os.path.exists("../downloads"):
    os.makedirs("../downloads")


# ============= СОСТОЯНИЯ =============
class EditTaskStates(StatesGroup):
    edit_text = State()
    edit_msg_delay = State()
    edit_cycle_delay = State()


class InvitingStates(StatesGroup):
    """Состояния инвайтинга"""
    # Выбор аккаунтов
    selecting_accounts = State()

    # Рассылка по файлу со ссылками
    waiting_links_file = State()
    waiting_links_message = State()
    waiting_dialog_msg = State()

    # Рассылка по контактам
    waiting_contacts_message = State()
    confirm_contacts_mailing = State()  # <--- НОВОЕ
    editing_contacts_text = State()
    confirm_dialog_mailing = State()
    # Отправка одному
    waiting_target = State()
    waiting_one_message = State()
    confirm_one_sending = State()  # <--- Добавить
    editing_one_text = State()

    # Настройка задержек
    waiting_message_delay = State()
    waiting_cycle_delay = State()

    confirm_links_mailing = State()
    editing_message_text = State()  # ← новое: редактирование текста
    editing_mailing_mode = State()

    # Рассылка по юзернеймам
    waiting_usernames_input = State()   # ожидание файла или текста с юзернеймами
    waiting_usernames_message = State() # ожидание текста сообщения для рассылки
    confirm_usernames_mailing = State() # предпросмотр перед запуском
    editing_usernames_text = State()    # редактирование текста в предпросмотре


# Хранилище выбранных аккаунтов и задержек — персистентный JSON
from modules.selections_store import (
    get_selected_accounts,
    get_delays,
    set_delays,
    toggle_account as _toggle_account,
    select_all_accounts as _select_all,
    deselect_all_accounts as _deselect_all,
)


# ============= ГЛАВНОЕ МЕНЮ ИНВАЙТИНГА =============
@router.message(F.text == '💠Инвайтинг')
async def reply_invi(message: Message):
    """Главное меню инвайтинга"""
    user_id = message.from_user.id
    if await check_subs(user_id) is False:
        await message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        if not db.has_active_subscription(user_id):
            await message.answer("❌ Нужна подписка!", show_alert=True)
            return
        # Проверка API ключей
        if not await check_api(user_id):
            await message.answer(NO_API_TEXT, parse_mode="HTML")
            return
        else:
            selected = get_selected_accounts(user_id)
            delays = get_delays(user_id)

            text = (
                "<b>🔳 МЕНЮ ИНВАЙТИНГА</b>\n\n"
                "🕹️Выберите необходимый раздел:"

            )

            await message.reply(
                text,
                reply_markup=UserKeyboards.inv_menu(),
                parse_mode="HTML"
            )


@router.callback_query(F.data == "inviting")
async def invv_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("<b>🔳 МЕНЮ ИНВАЙТИНГА</b>\n\n"
                                         "🕹️Выберите необходимый раздел:",
                                         reply_markup=UserKeyboards.inv_menu())


@router.callback_query(F.data == "smm_menu")
async def smm_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)
    print(selected)
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        if not selected:
            await callback.answer('Сначала выберите аккаунты!', show_alert=True)
        else:
            await callback.message.edit_text(f'Выберите нужное действие:', reply_markup=UserKeyboards.smm_kb())


@router.callback_query(F.data == "invitings")
async def show_inviting_menu(callback: CallbackQuery):
    """Главное меню инвайтинга"""
    user_id = callback.from_user.id
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        if not db.has_active_subscription(user_id):
            await callback.answer("❌ Нужна подписка!", show_alert=True)
            return

        # Проверка API ключей
        if not await check_api(user_id):
            await callback.answer("🔑 API ключи не настроены!", show_alert=True)
            await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
            return

        selected = get_selected_accounts(user_id)
        delays = get_delays(user_id)

        text = (
            "📤 <b>ИНВАЙТИНГ</b>\n\n"
            f"📱 Выбрано аккаунтов: <b>{len(selected)}</b>\n"
            f"⏱ Задержка между сообщениями: <b>{delays['message']}с</b>\n"
            f"⏱ Задержка между циклами: <b>{delays['cycle']}с</b>\n\n"
            "<i>Сначала выберите аккаунты</i>"
        )

        await callback.message.edit_text(
            text,
            reply_markup=UserKeyboards.inviting_menu(),
            parse_mode="HTML"
        )
        await callback.answer()


# ============= ВЫБОР АККАУНТОВ =============

@router.callback_query(F.data.startswith("inv:select"))
async def select_accounts_menu(callback: CallbackQuery, state: FSMContext):
    """Меню выбора аккаунтов"""
    user_id = callback.from_user.id
    if await check_subs(user_id) is False:
        await callback.message.answer(
            "📢 <b>Подписка обязательна!</b>\n\n"
            "Подпишитесь на канал для использования бота 👇",
            reply_markup=UserKeyboards.check_subscription(),
            parse_mode="HTML"
        )
    else:
        # Проверка API ключей
        if not await check_api(user_id):
            await callback.answer("🔑 API ключи не настроены!", show_alert=True)
            await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
            return

        # Парсим страницу если есть
        parts = callback.data.split(":")
        page = int(parts[2]) if len(parts) > 2 else 0

        sessions = session_mgr.get_sessions(user_id)

        if not sessions:
            await callback.answer("❌ Нет аккаунтов!", show_alert=True)
            return

        selected = get_selected_accounts(user_id)

        text = (
            "📋 <b>ВЫБОР АККАУНТОВ</b>\n\n"
            f"Выбрано: <b>{len(selected)}</b> из {len(sessions)}\n\n"
            "🟢 - выбран | 🔴 - не выбран\n"
            "<i>Нажмите на аккаунт для переключения</i>"
        )

        await callback.message.edit_text(
            text,
            reply_markup=UserKeyboards.select_accounts(sessions, selected, page),
            parse_mode="HTML"
        )
        await state.set_state(InvitingStates.selecting_accounts)
        await callback.answer()


@router.callback_query(F.data.startswith("inv_toggle:"))
async def toggle_account(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    # callback_data: inv_toggle:{page}:{global_index}
    parts = callback.data.split(":")
    current_page = int(parts[1])
    global_idx   = int(parts[2])   # <-- теперь числовой индекс, не имя сессии

    sessions = session_mgr.get_sessions(user_id)

    if global_idx < 0 or global_idx >= len(sessions):
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    session_name = sessions[global_idx]
    is_selected  = _toggle_account(user_id, session_name)
    selected     = get_selected_accounts(user_id)

    await callback.message.edit_reply_markup(
        reply_markup=UserKeyboards.select_accounts(sessions, selected, current_page)
    )

    status_text = "✅ Выбран" if is_selected else "❌ Отменён"
    await callback.answer(status_text)


@router.callback_query(F.data == "inv_select_all")
async def select_all_accounts(callback: CallbackQuery):
    """Выбрать все аккаунты"""
    user_id = callback.from_user.id
    sessions = session_mgr.get_sessions(user_id)

    _select_all(user_id, sessions)

    await callback.message.edit_reply_markup(
        reply_markup=UserKeyboards.select_accounts(sessions, sessions, 0)
    )
    await callback.answer(f"✅ Выбрано {len(sessions)} аккаунтов")


@router.callback_query(F.data == "inv_deselect_all")
async def deselect_all_accounts(callback: CallbackQuery):
    """Отменить выбор всех"""
    user_id = callback.from_user.id
    sessions = session_mgr.get_sessions(user_id)

    _deselect_all(user_id)

    await callback.message.edit_reply_markup(
        reply_markup=UserKeyboards.select_accounts(sessions, [], 0)
    )
    await callback.answer("❌ Выбор отменён")


@router.callback_query(F.data == "inv_selected_done")
async def finish_selection(callback: CallbackQuery, state: FSMContext):
    """Завершить выбор аккаунтов"""
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)

    if not selected:
        await callback.answer("⚠️ Выберите хотя бы 1 аккаунт!", show_alert=True)
        return

    await state.clear()

    delays = get_delays(user_id)

    await callback.message.edit_text(
        f"✅ <b>Выбрано {len(selected)} аккаунтов</b>\n\n"
        "Теперь выберите действие:",
        reply_markup=UserKeyboards.inv_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


# ============= РАССЫЛКА ПО ССЫЛКАМ ИЗ ФАЙЛА =============

@router.callback_query(F.data == "inv:links")
async def start_links_mailing(callback: CallbackQuery, state: FSMContext):
    """Начать рассылку по ссылкам из файла"""
    user_id = callback.from_user.id

    # Проверка API ключей
    if not await check_api(user_id):
        await callback.answer("🔑 API ключи не настроены!", show_alert=True)
        await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
        return

    selected = get_selected_accounts(user_id)
    print(selected)
    if not selected:
        await callback.answer("❌ Сначала выберите аккаунты!", show_alert=True)
        return

    # if inviting_svc.is_running(user_id):
    #     await callback.answer("⚠️ Уже выполняется рассылка!", show_alert=True)
    #     return

    await callback.message.edit_text(
        "📄 <b>РАССЫЛКА ПО ССЫЛКАМ</b>\n\n"
        "Отправьте TXT файл со ссылками на чаты <b>или</b> напишите ссылки текстом — по одной на строку\n\n"
        "📋 <b>Формат:</b>\n"
        "• Одна ссылка на строку\n"
        "• Поддерживаются форматы:\n"
        "  - https://t.me/chatname\n"
        "  - t.me/chatname\n"
        "  - @chatname\n\n"
        "⚠️ <b>Примечание:</b>\n"
        "• Бот автоматически вступит в чаты, если аккаунтов там нет\n"
        "• Порядок чатов будет рандомным\n"
        "• Об ошибках будет сообщено без остановки рассылки\n"
        "<b>Инструкция:</b> https://telegra.ph/Instrukciya-po-sozdaniyu-tekstovogo-fajla-s-ssylkami-01-11",
        parse_mode="HTML",
        reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
    )

    await state.set_state(InvitingStates.waiting_links_file)
    await callback.answer()


@router.message(InvitingStates.waiting_links_message)
async def receive_links_message(message: Message, state: FSMContext):
    is_valid, error = TextValidator.validate_message(message.text)
    if not is_valid:
        await message.answer(error)
        return

    message_text, photo_path = await save_message_content(message)

    await state.update_data(message_text=message_text, photo_path=photo_path)
    await show_mailing_preview(message, state)


async def show_mailing_preview(message: Message | CallbackQuery, state: FSMContext):
    """Показывает предпросмотр + кнопки управления"""
    data = await state.get_data()
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id

    chat_links = data['chat_links']
    mode = data.get('mode', 'parallel')  # дефолт
    message_text = data.get('message_text', '')

    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    # Клавиатура управления
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить", callback_data="start_links_mailing", style='success')],
        [
            InlineKeyboardButton(text="✏️ Изменить текст", callback_data="edit_message_text", style='primary'),
            InlineKeyboardButton(text="🔄 Изменить режим", callback_data="edit_mailing_mode"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_mailing", style='danger')],
    ])

    preview_text = (
        "📤 <b>ПРЕДПРОСМОТР РАССЫЛКИ</b>\n\n"
        f"📋 Чатов: <b>{len(chat_links)}</b>\n"
        f"📱 Аккаунтов: <b>{len(selected)}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>\n"
        f"⏱ Между сообщениями: <b>{delays['message']}с</b>\n"
        f"⏱ Между циклами: <b>{delays['cycle']}с</b>\n\n"
        "™<b>Текст:</b>\n"
        f"<blockquote expandable>{message_text}</blockquote>\n"  # ← вот цитирование

        "<i>Выберите действие:</i>"
    )

    # Если вызвали из callback — редактируем сообщение
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

    await state.set_state(InvitingStates.confirm_links_mailing)


@router.callback_query(F.data == "start_links_mailing", InvitingStates.confirm_links_mailing)
async def start_mailing(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    user_id = call.from_user.id
    photo_path = data.get('photo_path')
    message_text = data.get('message_text', '')
    chat_links = data.get('chat_links', [])
    mode = data.get('mode', 'parallel')

    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    # ── Создаём таск в task_manager ──
    task, conflicts = await task_manager.try_create_task(
        user_id=user_id,
        task_type=TaskType.LINKS_MAILING,
        accounts=selected,
        message_text=message_text,
        message_delay=float(delays['message']),
        cycle_delay=float(delays['cycle']),
        photo_path=photo_path,
    )
    if conflicts:
        await call.message.answer(
            task_manager.format_conflict_message(conflicts),
            parse_mode="HTML"
        )
        return

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    await call.message.answer(
        f"📤 <b>ЗАПУСК РАССЫЛКИ ПО ССЫЛКАМ</b>\n\n"
        f"🆔 Таск: <b>#{task.task_id}</b>\n"
        f"📋 Чатов: <b>{len(chat_links)}</b>\n"
        f"📱 Аккаунтов: <b>{len(selected)}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>\n"
        f"⏱ Задержка между сообщениями: <b>{delays['message']}с</b>\n"
        f"⏱ Задержка между циклами: <b>{delays['cycle']}с</b>\n\n"
        f"<i>Рассылка запущена!</i>",
        parse_mode="HTML",
    )

    await prefetch_accounts_meta(user_id, selected)
    await state.clear()

    asyncio_task = asyncio.create_task(
        run_links_mailing(
            user_id, selected, chat_links, message_text, photo_path,
            delays['message'], delays['cycle'], mode, call.message, task
        )
    )
    task.asyncio_task = asyncio_task


# Изменить текст
@router.callback_query(F.data == "edit_message_text", InvitingStates.confirm_links_mailing)
async def edit_text_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    await call.message.answer(
        "✏️ Отправьте <b>новый текст сообщения</b> для рассылки:\n\n"
        "<i>(можно использовать форматирование Telegram)</i>",
        parse_mode="HTML"
    )
    await state.set_state(InvitingStates.editing_message_text)


@router.message(InvitingStates.editing_message_text)
async def process_new_text(message: Message, state: FSMContext):
    is_valid, error = TextValidator.validate_message(message.text)
    if not is_valid:
        await message.answer(error)
        return

    await state.update_data(message_text=message.text)
    await show_mailing_preview(message, state)  # возвращаемся к предпросмотру


# Изменить режим
@router.callback_query(F.data == "edit_mailing_mode", InvitingStates.confirm_links_mailing)
async def edit_mode_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    current_mode = (await state.get_data()).get('mode', 'parallel')

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚡ Параллельно" + (" ✅" if current_mode == "parallel" else ""),
            callback_data="set_mode_parallel"
        )],
        [InlineKeyboardButton(
            text="📝 Последовательно" + (" ✅" if current_mode == "sequential" else ""),
            callback_data="set_mode_sequential"
        )],
        [InlineKeyboardButton(text="← Назад", callback_data="back_to_preview")],
    ])

    await call.message.answer("Выберите режим рассылки:", reply_markup=kb)
    await state.set_state(InvitingStates.editing_mailing_mode)


@router.callback_query(F.data.in_({"set_mode_parallel", "set_mode_sequential"}), InvitingStates.editing_mailing_mode)
async def set_new_mode(call: CallbackQuery, state: FSMContext):
    new_mode = "parallel" if call.data == "set_mode_parallel" else "sequential"
    await state.update_data(mode=new_mode)
    await call.answer(f"Режим изменён на: {new_mode}")
    await show_mailing_preview(call, state)  # назад в предпросмотр


@router.callback_query(F.data == "back_to_preview")
async def back_to_preview(call: CallbackQuery, state: FSMContext):
    await show_mailing_preview(call, state)


# Отмена (можно оставить общий)
@router.callback_query(F.data == "cancel_mailing")
async def cancel_mailing(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text(
        call.message.text.html + "\n\n❌ <b>Рассылка отменена</b>",
        parse_mode="HTML"
    )
    await state.clear()


@router.message(InvitingStates.waiting_links_file)
async def receive_links_file(message: Message, state: FSMContext):
    """Получить файл или текст со ссылками"""

    lines = []

    # Вариант 1: прислан TXT-файл
    if message.document:
        if not message.document.file_name.endswith('.txt'):
            await message.answer(
                "❌ Файл должен быть в формате .txt\n\nИли отправьте ссылки обычным сообщением (по одной на строку).",
                reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
            )
            return

        try:
            file = await message.bot.download(message.document)
            content = file.read().decode('utf-8')
            lines = [line.strip() for line in content.split('\n') if line.strip()]
        except Exception as e:
            logger.error(f"Ошибка обработки файла: {e}")
            await message.answer(f"❌ Ошибка обработки файла: {str(e)}")
            return

    # Вариант 2: прислан текст со ссылками
    elif message.text:
        lines = [line.strip() for line in message.text.split('\n') if line.strip()]

    else:
        await message.answer(
            "❌ Отправьте TXT файл или текст со ссылками (по одной на строку).",
            reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
        )
        return

    if not lines:
        await message.answer("❌ Список пустой!")
        return

    # Валидируем и нормализуем ссылки
    valid_links = []
    for line in lines:
        normalized = TextValidator.normalize_chat_link(line)
        if normalized:
            if not normalized.startswith(('@', 'https://t.me/', 't.me/')):
                normalized = '@' + normalized
            valid_links.append(normalized)

    if not valid_links:
        await message.answer(
            "❌ Не найдено ни одной валидной ссылки!\n\n"
            "Проверьте формат ссылок.",
            reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
        )
        return

    await state.update_data(chat_links=valid_links)

    # Выбор режима рассылки
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⚡ Параллельно (быстрее)", callback_data="links_mode:parallel"))
    kb.row(InlineKeyboardButton(text="📝 Последовательно", callback_data="links_mode:sequential"))
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="inviting"))

    await message.answer(
        f"✅ <b>Ссылки приняты</b>\n\n"
        f"📊 Найдено валидных ссылок: <b>{len(valid_links)}</b>\n\n"
        "Выберите режим рассылки:\n\n"
        "⚡ <b>Параллельно</b> - быстрее, но может вызвать флуд\n"
        "📝 <b>Последовательно</b> - медленнее, но безопаснее",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("links_mode:"))
async def choose_links_mode(callback: CallbackQuery, state: FSMContext):
    """Выбрать режим рассылки по ссылкам"""
    mode = callback.data.split(":")[1]
    await state.update_data(mode=mode)

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    text = "Для гиперссылок:\n<a href='сайт'>ссылка</a>\n"
    text_s = html.escape(text)
    user_id = callback.from_user.id  # <-- было callback.message.from_user.id (БАГ!)

    # Получаем клавиатуру шаблонов и добавляем кнопку отмены
    templates_kb = await temp_kb.get_temp_keyboards(user_id=user_id)
    if templates_kb:
        # Добавляем строку с отменой к существующей клавиатуре шаблонов
        from aiogram.types import InlineKeyboardMarkup as IKM
        rows = list(templates_kb.inline_keyboard)
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_to_inviting_menu")])
        cancel_templates_kb = IKM(inline_keyboard=rows)
    else:
        cancel_templates_kb = UserKeyboards.cancel_input("cancel_to_inviting_menu")

    await callback.message.edit_text(
        f"✅ <b>Режим: {mode_text}</b>\n\n"
        "Теперь отправьте текст сообщения для рассылки\n\n"
        f"{text_s}",
        parse_mode="HTML",
        reply_markup=cancel_templates_kb,
    )
    await state.set_state(InvitingStates.waiting_links_message)
    await callback.answer()


from modules.text_temp import TEMP

loader = TEMP()


@router.callback_query(F.data.startswith("check_temp:"), InvitingStates.waiting_links_message)
async def apply_template_links(callback: CallbackQuery, state: FSMContext):
    name_temp = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id  # исправлен источник user_id
    text = await loader.get_temp(user_id, name_temp)
    if not text:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    await callback.answer(f"✅ Шаблон «{name_temp}» применён")
    # Кладём текст в state и идём к превью — так же как при ручном вводе
    await state.update_data(message_text=text, photo_path=None)
    await show_mailing_preview(callback, state)


async def run_links_mailing(
        user_id: int,
        session_names: List[str],
        chat_links: List[str],
        message_text: str,
        photo_path: str,
        message_delay: int,
        cycle_delay: int,
        mode: str,
        original_message: Message,
        task=None  # ← НОВЫЙ параметр
):
    """Запустить рассылку по ссылкам"""
    progress_msg = None

    task_id_str = task.task_id if task else "unknown"
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"task_pause:{task_id_str}"),
            InlineKeyboardButton(text="⛔ Завершить", callback_data=f"task_stop:{task_id_str}"),
        ],
        [InlineKeyboardButton(text="🗂 Мои таски", callback_data="tasks_menu")],
    ])

    async def update_progress(text: str, reply_markup=stop_kb):
        nonlocal progress_msg
        try:
            if progress_msg:
                await progress_msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                progress_msg = await original_message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            logger.debug(f"Не удалось обновить прогресс: {e}")

    try:
        await update_progress("🔄 Подготовка к рассылке...")

        stats = await inviting_svc.send_to_chat_links(
            session_names,
            chat_links,
            message_text,
            photo_path,
            user_id,
            message_delay,
            cycle_delay,
            update_progress,
            mode,
            task=task  # ← ПЕРЕДАЁМ task
        )

        # Убираем кнопки с прогресс-сообщения — текст не меняем
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        # Отдельное итоговое сообщение
        final = (
            f"✅ <b>РАССЫЛКА ПО ССЫЛКАМ ЗАВЕРШЕНА</b>\n\n"
            f"📊 Статистика:\n"
            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
            f"❌ Ошибок: <b>{stats['total_failed']}</b>\n"
            f"➕ Вступлений в чаты: <b>{stats['total_joined']}</b>\n"
            f"🔄 Циклов выполнено: <b>{stats['cycles']}</b>\n"
            f"📱 Использовано аккаунтов: <b>{stats['accounts_used']}</b>"
        )

        if stats.get('errors'):
            error_text_content = ""
            for error in stats['errors'][:10]:
                error_text_content += f"• {error}\n"
            if len(stats['errors']) > 10:
                error_text_content += f"... и ещё {len(stats['errors']) - 10} ошибок"
            errors_block = (
                f"\n\n⚠️ <b>Детали ошибок:</b>\n"
                f"<blockquote expandable>{error_text_content}</blockquote>"
            )
            if len(final) + len(errors_block) > 4000:
                available = 4000 - len(final) - 60
                error_text_content = error_text_content[:max(0, available)] + "..."
                errors_block = (
                    f"\n\n⚠️ <b>Детали ошибок (обрезано):</b>\n"
                    f"<blockquote expandable>{error_text_content}</blockquote>"
                )
            final += errors_block

        await original_message.answer(final, parse_mode="HTML", reply_markup=UserKeyboards.come_to_inv())

        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.FINISHED)

    except Exception as e:
        logger.error(f"Критическая ошибка рассылки: {e}")
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await original_message.answer(f"❌ Критическая ошибка: {str(e)}", reply_markup=UserKeyboards.come_to_inv())
        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.ERROR)


@router.callback_query(F.data == "inv:dialog")
async def dialog(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)
    if not selected:
        await callback.answer("❌ Сначала выберите аккаунты!", show_alert=True)
        return
    # if inviting_svc.is_running(user_id):
    #     await callback.answer("⚠️ Уже выполняется рассылка!", show_alert=True)
    #     return
    text = "Для гиперссылок:\n<a href='сайт'>ссылка</a>\n"

    text_s = html.escape(text)

    templates_kb_dialog = await temp_kb.get_temp_keyboards(user_id=callback.from_user.id)
    if templates_kb_dialog:
        from aiogram.types import InlineKeyboardMarkup as IKM
        rows = list(templates_kb_dialog.inline_keyboard)
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_to_inviting_menu")])
        cancel_dialog_kb = IKM(inline_keyboard=rows)
    else:
        cancel_dialog_kb = UserKeyboards.cancel_input("cancel_to_inviting_menu")

    await callback.message.answer(
        "💬 <b>РАССЫЛКА ПО ДИАЛОГАМ</b>\n\n"
        "Отправьте текст сообщения для рассылки по всем диалогам на аккаунте\n\n"
        "<i>Сообщение будет отправлено во все диалоги выбранных аккаунтов</i>\n"
        f"{text_s}"
        "<tg-spoiler>А также поддерживается отправка фото</tg-spoiler>",
        parse_mode="HTML",
        reply_markup=cancel_dialog_kb,
    )
    await state.set_state(InvitingStates.waiting_dialog_msg)


@router.callback_query(F.data.startswith("check_temp:"), InvitingStates.waiting_dialog_msg)
async def apply_template_dialog(callback: CallbackQuery, state: FSMContext):
    name_temp = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    text = await loader.get_temp(user_id, name_temp)
    if not text:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    await callback.answer(f"✅ Шаблон «{name_temp}» применён")
    await state.update_data(message_text=text, photo_path=None)
    await show_dialogs_preview(callback, state)


@router.message(InvitingStates.waiting_dialog_msg)
async def receive_dialog_message(message: Message, state: FSMContext):
    """Получение сообщения для рассылки по диалогам"""

    # 1. Создаем папку если нет
    if not os.path.exists("../downloads"):
        os.makedirs("../downloads")

    message_text = ""
    photo_path = None

    # 2. Обработка ФОТО
    if message.photo:
        photo = message.photo[-1]
        photo_path = f"downloads/dialog_{message.from_user.id}.jpg"
        await message.bot.download(photo, destination=photo_path)
        message_text = message.caption or ""

    # 3. Обработка ТЕКСТА
    elif message.text:
        message_text = message.text
        # Сбрасываем фото, если пользователь решил отправить только текст после фото
        await state.update_data(photo_path=None)
    else:
        await message.answer("❌ Тип сообщения не поддерживается. Пришлите текст или фото.")
        return

    # 4. Валидация (опционально, если у вас есть валидатор)
    # if message_text:
    #     is_valid, error = TextValidator.validate_message(message_text)
    #     if not is_valid:
    #         await message.answer(error)
    #         return

    # 5. Сохраняем в стейт
    await state.update_data(message_text=message_text, photo_path=photo_path)

    # 6. Показываем превью
    await show_dialogs_preview(message, state)


async def show_dialogs_preview(message: Message | CallbackQuery, state: FSMContext):
    """Показывает превью рассылки по диалогам с выбором режима"""
    data = await state.get_data()
    user_id = message.from_user.id

    if isinstance(message, CallbackQuery):
        msg_obj = message.message
        await msg_obj.delete()
    else:
        msg_obj = message

    message_text = data.get('message_text', '')
    photo_path = data.get('photo_path')
    mode = data.get('mode', 'sequential')

    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)
    delay_val = delays.get('message', 5)

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="start_dialog_mailing", style='success')],
        [
            InlineKeyboardButton(
                text=f"🔄 Режим: {mode_text}",
                callback_data="toggle_dialog_mode",
                style='primary',
            ),
        ],
        [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="edit_dialog_text", style='primary')],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_dialog_mailing", style='danger')],
    ])

    info_text = (
        "💬 <b>ПРЕДПРОСМОТР РАССЫЛКИ ПО ДИАЛОГАМ</b>\n\n"
        f"📱 Аккаунтов: <b>{len(selected)}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>\n"
        f"⏱ Задержка: <b>{delay_val}с</b>\n"
        "➖➖➖➖➖➖➖➖➖➖"
    )

    if photo_path and os.path.exists(photo_path):
        caption = f"{info_text}\n\n{message_text}" if message_text else info_text
        photo_file = FSInputFile(photo_path)
        await msg_obj.answer_photo(photo_file, caption=caption, reply_markup=kb, parse_mode="HTML")
    else:
        full_text = f"{info_text}\n\n{message_text}"
        await msg_obj.answer(full_text, reply_markup=kb, parse_mode="HTML")

    await state.set_state(InvitingStates.confirm_dialog_mailing)


# ══════════════════════════════════════════════════════════════
# ДОБАВИТЬ новый хендлер — переключение режима диалогов
# Вставить сразу ПОСЛЕ функции show_dialogs_preview
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "toggle_dialog_mode", InvitingStates.confirm_dialog_mailing)
async def toggle_dialog_mode(call: CallbackQuery, state: FSMContext):
    """Переключить режим параллельный/последовательный"""
    data = await state.get_data()
    current = data.get('mode', 'sequential')
    new_mode = 'parallel' if current == 'sequential' else 'sequential'
    await state.update_data(mode=new_mode)
    await call.answer(
        "⚡ Режим: Параллельно" if new_mode == "parallel" else "📝 Режим: Последовательно"
    )
    await show_dialogs_preview(call, state)


# --- КНОПКА ЗАПУСТИТЬ ---
@router.callback_query(F.data == "start_dialog_mailing", InvitingStates.confirm_dialog_mailing)
async def start_dialog_mailing_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    user_id = call.from_user.id

    message_text = data.get('message_text')
    photo_path = data.get('photo_path')
    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    # ── Проверка занятости аккаунтов ──
    task, conflicts = await task_manager.try_create_task(
        user_id=user_id,
        task_type=TaskType.DIALOG_MAILING,
        accounts=selected,
        message_text=message_text or "",
        message_delay=float(delays.get('message', 5)),
        cycle_delay=float(delays.get('cycle', 60)),
        photo_path=photo_path,
    )
    if conflicts:
        await call.message.answer(
            task_manager.format_conflict_message(conflicts),
            parse_mode="HTML"
        )
        return

    await call.message.answer(
        f"🚀 <b>Рассылка по диалогам запущена!</b>\n"
        f"🆔 Таск: <b>#{task.task_id}</b>\n"
        f"<i>Не закрывайте бота, пока идет процесс.</i>",
        parse_mode="HTML"
    )

    await state.clear()

    asyncio_task = asyncio.create_task(
        run_dialogs_mailing(
            user_id, selected, message_text, photo_path,
            delays.get('message', 5), call.message, task
        )
    )
    task.asyncio_task = asyncio_task


# --- КНОПКА ИЗМЕНИТЬ ---
router.callback_query(F.data == "edit_dialog_text")


async def edit_dialog_text(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.delete()
    await call.message.answer("✏️ Пришлите новый текст или фото для рассылки:")
    await state.set_state(InvitingStates.waiting_dialog_msg)


# --- КНОПКА ОТМЕНА (предпросмотр, рассылка ещё не запущена) ---
@router.callback_query(F.data == "cancel_dialog_mailing")
async def cancel_dialog_mailing(call: CallbackQuery):
    await call.answer("Отменено", show_alert=True)
    try:
        await call.message.delete()
    except:
        pass


async def run_dialogs_mailing(
        user_id: int,
        session_names: List[str],
        message_text: str,
        photo_path: str | None,
        message_delay: int,
        original_message: Message,
        task=None,
        mode: str = "sequential"  # ← ДОБАВИТЬ
):
    progress_msg = None

    task_id_str = task.task_id if task else "unknown"
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"task_pause:{task_id_str}"),
            InlineKeyboardButton(text="⛔ Завершить", callback_data=f"task_stop:{task_id_str}"),
        ],
        [InlineKeyboardButton(text="🗂 Мои таски", callback_data="tasks_menu")],
    ])

    async def update_progress(text: str, reply_markup=stop_kb):
        nonlocal progress_msg
        try:
            if progress_msg:
                if progress_msg.text != text and progress_msg.caption != text:
                    await progress_msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                progress_msg = await original_message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            pass

    try:
        await update_progress("🔄 Инициализация сессий...")

        stats = await inviting_svc.send_to_dialogs(
            session_names,
            message_text,
            photo_path,
            user_id,
            message_delay,
            update_progress,
            task=task,
            mode=mode  # ← ДОБАВИТЬ
            # ← ПЕРЕДАЁМ task
        )

        # Убираем кнопки с прогресс-сообщения
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        # Отдельное итоговое сообщение
        final = (
            f"✅ <b>РАССЫЛКА ПО ДИАЛОГАМ ЗАВЕРШЕНА</b>\n\n"
            f"📊 Итоги:\n"
            f"✅ Успешно: <b>{stats['total_sent']}</b>\n"
            f"❌ Ошибок: <b>{stats['total_failed']}</b>"
        )

        if stats.get('errors'):
            error_list = "\n".join([f"• {e}" for e in stats['errors'][:15]])
            if len(stats['errors']) > 15:
                error_list += f"\n...и еще {len(stats['errors']) - 15}"
            errors_block = (
                f"\n\n⚠️ <b>Ошибки:</b>\n"
                f"<blockquote expandable>{html.escape(error_list)}</blockquote>"
            )
            if len(final) + len(errors_block) > 4000:
                available = 4000 - len(final) - 60
                error_list = error_list[:max(0, available)] + "..."
                errors_block = (
                    f"\n\n⚠️ <b>Ошибки (обрезано):</b>\n"
                    f"<blockquote expandable>{html.escape(error_list)}</blockquote>"
                )
            final += errors_block

        await original_message.answer(final, parse_mode="HTML", reply_markup=UserKeyboards.come_to_inv())

        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.FINISHED)

    except Exception as e:
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await original_message.answer(f"❌ Критическая ошибка скрипта: {e}", reply_markup=UserKeyboards.come_to_inv())
        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.ERROR)


# ============= РАССЫЛКА ПО КОНТАКТАМ =============

@router.callback_query(F.data == "inv:contacts")
async def start_contacts_mailing(callback: CallbackQuery, state: FSMContext):
    """Начать рассылку по контактам"""
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)

    if not selected:
        await callback.answer("❌ Сначала выберите аккаунты!", show_alert=True)
        return

    # if inviting_svc.is_running(user_id):
    #     await callback.answer("⚠️ Уже выполняется рассылка!", show_alert=True)
    #     return
    text = "Для гиперссылок:\n<a href='сайт'>ссылка</a>\n"

    text_s = html.escape(text)

    templates_kb_contacts = await temp_kb.get_temp_keyboards(user_id=callback.from_user.id)
    if templates_kb_contacts:
        from aiogram.types import InlineKeyboardMarkup as IKM
        rows = list(templates_kb_contacts.inline_keyboard)
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_to_inviting_menu")])
        cancel_contacts_kb = IKM(inline_keyboard=rows)
    else:
        cancel_contacts_kb = UserKeyboards.cancel_input("cancel_to_inviting_menu")

    await callback.message.answer(
        "👥 <b>РАССЫЛКА ПО КОНТАКТАМ</b>\n\n"
        "Отправьте текст сообщения для рассылки по всем контактам\n\n"
        "<i>Сообщение будет отправлено всем контактам выбранных аккаунтов</i>\n"
        f"{text_s}"
        "<tg-spoiler>А также поддерживается отправка фото</tg-spoiler>",
        parse_mode="HTML",
        reply_markup=cancel_contacts_kb,
    )

    await state.set_state(InvitingStates.waiting_contacts_message)
    await callback.answer()


import html


# ============= РАССЫЛКА ПО КОНТАКТАМ: ОБРАБОТЧИКИ =============
@router.callback_query(F.data.startswith("check_temp:"), InvitingStates.waiting_contacts_message)
async def apply_template_contacts(callback: CallbackQuery, state: FSMContext):
    """Применить шаблон для рассылки по контактам."""
    name_temp = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    text = await loader.get_temp(user_id, name_temp)
    if not text:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    await callback.answer(f"✅ Шаблон «{name_temp}» применён")
    await state.update_data(message_text=text, photo_path=None)
    await show_contacts_preview(callback, state)


@router.message(InvitingStates.waiting_contacts_message)
async def receive_contacts_message(message: Message, state: FSMContext):
    """Получить сообщение (текст или фото) для рассылки"""

    # Создаем папку для загрузок, если нет
    if not os.path.exists("../downloads"):
        os.makedirs("../downloads")

    message_text = ""
    photo_path = None

    # Если прислали ФОТО
    if message.photo:
        # Берем фото лучшего качества
        photo = message.photo[-1]
        # Путь куда сохраним: downloads/user_id.jpg
        photo_path = f"downloads/{message.from_user.id}.jpg"

        # Скачиваем фото
        await message.bot.download(photo, destination=photo_path)

        # Текстом становится подпись к фото (caption)
        message_text = message.caption or ""

    # Если прислали только ТЕКСТ
    elif message.text:
        message_text = message.text
        # Удаляем старое фото из состояния, если оно там было
        await state.update_data(photo_path=None)
    else:
        await message.answer("❌ Пришлите текст или фото!")
        return

    # Валидация текста (если он есть)
    if message_text:
        is_valid, error = TextValidator.validate_message(message_text)
        if not is_valid:
            await message.answer(error)
            return

    # Сохраняем в состояние путь к фото и текст
    await state.update_data(message_text=message_text, photo_path=photo_path)

    # Показываем превью
    await show_contacts_preview(message, state)


async def show_contacts_preview(message: Message | CallbackQuery, state: FSMContext):
    """Показывает предпросмотр рассылки по контактам с выбором режима"""
    data = await state.get_data()

    if isinstance(message, CallbackQuery):
        user_id = message.from_user.id
        await message.message.delete()
        msg_obj = message.message
    else:
        user_id = message.from_user.id
        msg_obj = message

    message_text = data.get('message_text', '')
    photo_path = data.get('photo_path')
    mode = data.get('mode', 'sequential')

    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="start_contacts_mailing", style='success')],
        [
            InlineKeyboardButton(
                text=f"🔄 Режим: {mode_text}",
                callback_data="toggle_contacts_mode",
                style='primary',
            ),
        ],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_contacts_text", style='primary')],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_contacts_mailing", style='danger')],
    ])

    info_text = (
        "👥 <b>ПРЕДПРОСМОТР РАССЫЛКИ ПО КОНТАКТАМ</b>\n\n"
        f"📱 Аккаунтов: <b>{len(selected)}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>\n"
        f"⏱ Задержка: <b>{delays['message']}с</b>\n"
        "➖➖➖➖➖➖➖➖➖➖"
    )

    if photo_path and os.path.exists(photo_path):
        caption_text = f"{info_text}\n\n{message_text}" if message_text else info_text
        photo_file = FSInputFile(photo_path)
        await msg_obj.answer_photo(photo_file, caption=caption_text, reply_markup=kb, parse_mode="HTML")
    else:
        full_text = f"{info_text}\n\n{message_text}"
        await msg_obj.answer(full_text, reply_markup=kb, parse_mode="HTML")

    await state.set_state(InvitingStates.confirm_contacts_mailing)


# ══════════════════════════════════════════════════════════════
# ДОБАВИТЬ новый хендлер — переключение режима контактов
# Вставить сразу ПОСЛЕ функции show_contacts_preview
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "toggle_contacts_mode", InvitingStates.confirm_contacts_mailing)
async def toggle_contacts_mode(call: CallbackQuery, state: FSMContext):
    """Переключить режим параллельный/последовательный"""
    data = await state.get_data()
    current = data.get('mode', 'sequential')
    new_mode = 'parallel' if current == 'sequential' else 'sequential'
    await state.update_data(mode=new_mode)
    await call.answer(
        "⚡ Режим: Параллельно" if new_mode == "parallel" else "📝 Режим: Последовательно"
    )
    await show_contacts_preview(call, state)


# --- Обработчик кнопки ЗАПУСТИТЬ ---
@router.callback_query(F.data == "start_contacts_mailing", InvitingStates.confirm_contacts_mailing)
async def start_contacts_mailing_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    photo_path = data.get('photo_path')
    message_text = data.get('message_text')
    mode = data.get('mode', 'sequential')  # ← режим из state

    user_id = call.from_user.id
    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    # ── Проверка занятости аккаунтов ──
    task, conflicts = await task_manager.try_create_task(
        user_id=user_id,
        task_type=TaskType.CONTACTS_MAILING,
        accounts=selected,
        message_text=message_text or "",
        message_delay=float(delays['message']),
        cycle_delay=float(delays.get('cycle', 60)),
        photo_path=photo_path,
    )
    if conflicts:
        await call.message.answer(
            task_manager.format_conflict_message(conflicts),
            parse_mode="HTML"
        )
        return

    # ── Prefetch меты аккаунтов ДО запуска (сессии ещё свободны) ──
    await prefetch_accounts_meta(user_id, selected)

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    await call.message.answer(
        f"✅ <b>Рассылка по контактам запущена!</b>\n"
        f"🆔 Таск: <b>#{task.task_id}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>",
        parse_mode="HTML"
    )

    await state.clear()

    asyncio_task = asyncio.create_task(
        run_contacts_mailing(
            user_id, selected, message_text, photo_path,
            delays['message'], call.message, task, mode  # ← mode добавлен
        )
    )
    task.asyncio_task = asyncio_task


# --- Обработчик кнопки ИЗМЕНИТЬ ТЕКСТ ---
@router.callback_query(F.data == "edit_contacts_text", InvitingStates.confirm_contacts_mailing)
async def edit_contacts_text_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "✏️ Отправьте <b>новый текст сообщения</b> для рассылки по контактам:\n\n"
        "<i>(поддерживается форматирование Telegram)</i>",
        parse_mode="HTML"
    )
    await state.set_state(InvitingStates.editing_contacts_text)


@router.message(InvitingStates.editing_contacts_text)
async def process_new_contacts_text(message: Message, state: FSMContext):
    is_valid, error = TextValidator.validate_message(message.text)
    if not is_valid:
        await message.answer(error)
        return
    await state.update_data(message_text=message.text)
    await show_contacts_preview(message, state)


# --- Обработчик кнопки ОТМЕНА (предпросмотр) ---
@router.callback_query(F.data == "cancel_contacts_mailing")
async def cancel_contacts_mailing(callback: CallbackQuery):
    await callback.answer("Отменено")
    try:
        await callback.message.delete()
    except:
        pass


async def run_contacts_mailing(
        user_id: int,
        session_names: List[str],
        message_text: str,
        photo_path: str | None,
        message_delay: int,
        original_message: Message,
        task=None,
        mode: str = "sequential"  # ← НОВЫЙ параметр
):
    """Запустить рассылку по контактам"""
    progress_msg = None

    task_id_str = task.task_id if task else "unknown"
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"task_pause:{task_id_str}"),
            InlineKeyboardButton(text="⛔ Завершить", callback_data=f"task_stop:{task_id_str}"),
        ],
        [InlineKeyboardButton(text="🗂 Мои таски", callback_data="tasks_menu")],
    ])

    async def update_progress(text: str, reply_markup=stop_kb):
        nonlocal progress_msg
        try:
            if progress_msg:
                await progress_msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                progress_msg = await original_message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            logger.debug(f"Не удалось обновить прогресс: {e}")

    try:
        await update_progress("🔄 Подключаюсь к аккаунтам...")

        stats = await inviting_svc.send_to_contacts(
            session_names,
            message_text,
            photo_path,
            user_id,
            message_delay,
            update_progress,
            task=task,
            mode=mode  # ← ДОБАВИТЬ
            # ← ПЕРЕДАЁМ task
        )

        # Убираем кнопки с прогресс-сообщения
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        # Отдельное итоговое сообщение
        final = (
            f"✅ <b>РАССЫЛКА ПО КОНТАКТАМ ЗАВЕРШЕНА</b>\n\n"
            f"📊 Статистика:\n"
            f"✅ Отправлено: <b>{stats.get('total_sent', 0)}</b>\n"
            f"❌ Ошибок: <b>{stats.get('total_failed', 0)}</b>"
        )

        if stats.get('errors'):
            # Ограничиваем количество ошибок, чтобы не превысить лимит 4096 символов
            errors = stats['errors']
            max_errors = 20
            error_lines = [f"• {e}" for e in errors[:max_errors]]
            if len(errors) > max_errors:
                error_lines.append(f"... и ещё {len(errors) - max_errors} ошибок")
            error_text_content = "\n".join(error_lines)

            # Проверяем итоговую длину сообщения
            errors_block = (
                f"\n\n⚠️ <b>Детали ошибок:</b>\n"
                f"<blockquote expandable>{error_text_content}</blockquote>"
            )
            if len(final) + len(errors_block) > 4000:
                # Обрезаем блок ошибок, чтобы уложиться в лимит
                available = 4000 - len(final) - 60
                error_text_content = error_text_content[:max(0, available)] + "..."
                errors_block = (
                    f"\n\n⚠️ <b>Детали ошибок (обрезано):</b>\n"
                    f"<blockquote expandable>{error_text_content}</blockquote>"
                )
            final += errors_block

        await original_message.answer(final, parse_mode="HTML", reply_markup=UserKeyboards.come_to_inv())

        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.FINISHED)

    except Exception as e:
        logger.error(f"Ошибка рассылки по контактам: {e}")
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        # Обрезаем текст ошибки, чтобы не превысить лимит Telegram
        err_str = str(e)[:500]
        await original_message.answer(
            f"❌ Критическая ошибка: {err_str}",
            reply_markup=UserKeyboards.come_to_inv()
        )
        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.ERROR)


# ============= ОТПРАВКА ОДНОМУ ПОЛЬЗОВАТЕЛЮ =============


# --- Общий обработчик отмены (возврат в меню рассылки) ---
@router.callback_query(F.data == "cancel_to_inviting_menu")
async def cancel_to_inviting_menu(call: CallbackQuery, state: FSMContext):
    """Отмена — возврат в меню рассылки."""
    await call.answer()
    await state.clear()
    user_id = call.from_user.id
    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)
    text = (
        "📤 <b>ИНВАЙТИНГ</b>\n\n"
        f"📱 Выбрано аккаунтов: <b>{len(selected)}</b>\n"
        f"⏱ Задержка между сообщениями: <b>{delays['message']}с</b>\n"
        f"⏱ Задержка между циклами: <b>{delays['cycle']}с</b>\n\n"
        "<i>Действие отменено</i>"
    )
    try:
        await call.message.edit_text(text, reply_markup=UserKeyboards.inviting_menu(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=UserKeyboards.inviting_menu(), parse_mode="HTML")


# ============= РАССЫЛКА ПО ЮЗЕРНЕЙМАМ =============

@router.callback_query(F.data == "inv:usernames")
async def start_usernames_mailing(callback: CallbackQuery, state: FSMContext):
    """Начать рассылку по юзернеймам"""
    user_id = callback.from_user.id

    if not await check_api(user_id):
        await callback.answer("🔑 API ключи не настроены!", show_alert=True)
        await callback.message.answer(NO_API_TEXT, parse_mode="HTML")
        return

    selected = get_selected_accounts(user_id)
    if not selected:
        await callback.answer("❌ Сначала выберите аккаунты!", show_alert=True)
        return

    await callback.message.edit_text(
        "👤 <b>РАССЫЛКА ПО ЮЗЕРНЕЙМАМ</b>\n\n"
        "Отправьте TXT файл с юзернеймами <b>или</b> напишите их текстом — по одному на строку\n\n"
        "📋 <b>Формат:</b>\n"
        "• Одна строка — один юзернейм\n"
        "• Можно с @ и без:\n"
        "  - @username\n"
        "  - username\n\n"
        "⚠️ Пользователи с закрытой приватностью будут пропущены.",
        parse_mode="HTML",
        reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
    )
    await state.set_state(InvitingStates.waiting_usernames_input)
    await callback.answer()


@router.message(InvitingStates.waiting_usernames_input)
async def receive_usernames_input(message: Message, state: FSMContext):
    """Получить файл или текст с юзернеймами"""
    lines = []

    # Вариант 1: TXT файл
    if message.document:
        if not message.document.file_name.endswith('.txt'):
            await message.answer(
                "❌ Файл должен быть в формате .txt\n\nИли отправьте юзернеймы обычным сообщением (по одному на строку).",
                reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
            )
            return
        try:
            file = await message.bot.download(message.document)
            content = file.read().decode('utf-8')
            lines = [line.strip() for line in content.split('\n') if line.strip()]
        except Exception as e:
            logger.error(f"Ошибка обработки файла юзернеймов: {e}")
            await message.answer(f"❌ Ошибка обработки файла: {str(e)}")
            return

    # Вариант 2: текст
    elif message.text:
        lines = [line.strip() for line in message.text.split('\n') if line.strip()]

    else:
        await message.answer(
            "❌ Отправьте TXT файл или текст с юзернеймами (по одному на строку).",
            reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
        )
        return

    if not lines:
        await message.answer(
            "❌ Список пустой!",
            reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
        )
        return

    # Нормализуем юзернеймы (убираем @, пробелы, пустые строки)
    usernames = []
    for line in lines:
        u = line.strip().lstrip('@')
        if u:
            usernames.append(u)

    if not usernames:
        await message.answer(
            "❌ Не найдено ни одного валидного юзернейма!",
            reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
        )
        return

    await state.update_data(usernames=usernames)

    text_hint = "Для гиперссылок:\n<a href='сайт'>ссылка</a>\n"
    text_s = html.escape(text_hint)

    # Клавиатура шаблонов + кнопка отмены
    templates_kb_usernames = await temp_kb.get_temp_keyboards(user_id=message.from_user.id)
    if templates_kb_usernames:
        from aiogram.types import InlineKeyboardMarkup as IKM
        rows = list(templates_kb_usernames.inline_keyboard)
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_to_inviting_menu")])
        cancel_usernames_kb = IKM(inline_keyboard=rows)
    else:
        cancel_usernames_kb = UserKeyboards.cancel_input("cancel_to_inviting_menu")

    await message.answer(
        f"✅ <b>Юзернеймов принято: {len(usernames)}</b>\n\n"
        "Теперь отправьте <b>текст сообщения</b> для рассылки\n"
        f"{text_s}"
        "<tg-spoiler>Поддерживается отправка фото с подписью</tg-spoiler>",
        parse_mode="HTML",
        reply_markup=cancel_usernames_kb,
    )
    await state.set_state(InvitingStates.waiting_usernames_message)


@router.callback_query(F.data.startswith("check_temp:"), InvitingStates.waiting_usernames_message)
async def apply_template_usernames(callback: CallbackQuery, state: FSMContext):
    """Применить шаблон для рассылки по юзернеймам."""
    name_temp = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    text = await loader.get_temp(user_id, name_temp)
    if not text:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    await callback.answer(f"✅ Шаблон «{name_temp}» применён")
    await state.update_data(message_text=text, photo_path=None)
    await show_usernames_preview(callback, state)


@router.message(InvitingStates.waiting_usernames_message)
async def receive_usernames_message(message: Message, state: FSMContext):
    """Получить текст/фото сообщения для рассылки по юзернеймам"""
    if not os.path.exists("../downloads"):
        os.makedirs("../downloads")

    message_text = ""
    photo_path = None

    if message.photo:
        photo = message.photo[-1]
        photo_path = f"downloads/usernames_{message.from_user.id}.jpg"
        await message.bot.download(photo, destination=photo_path)
        message_text = message.caption or ""
    elif message.text:
        message_text = message.text
        await state.update_data(photo_path=None)
    else:
        await message.answer(
            "❌ Тип сообщения не поддерживается. Пришлите текст или фото.",
            reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
        )
        return

    await state.update_data(message_text=message_text, photo_path=photo_path)
    await show_usernames_preview(message, state)


async def show_usernames_preview(source, state: FSMContext):
    """Предпросмотр рассылки по юзернеймам."""
    data = await state.get_data()

    if isinstance(source, CallbackQuery):
        user_id = source.from_user.id
        msg_obj = source.message
        try:
            await msg_obj.delete()
        except Exception:
            pass
    else:
        user_id = source.from_user.id
        msg_obj = source

    usernames = data.get('usernames', [])
    message_text = data.get('message_text', '')
    photo_path = data.get('photo_path')
    mode = data.get('usernames_mode', 'sequential')

    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)
    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="start_usernames_mailing")],
        [
            InlineKeyboardButton(text=f"🔄 Режим: {mode_text}", callback_data="toggle_usernames_mode"),
        ],
        [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="edit_usernames_text")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_to_inviting_menu")],
    ])

    info_text = (
        "👤 <b>ПРЕДПРОСМОТР — РАССЫЛКА ПО ЮЗЕРНЕЙМАМ</b>\n\n"
        f"👥 Юзернеймов: <b>{len(usernames)}</b>\n"
        f"📱 Аккаунтов: <b>{len(selected)}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>\n"
        f"⏱ Задержка: <b>{delays['message']}с</b>\n"
        "➖➖➖➖➖➖➖➖➖➖"
    )

    if photo_path and os.path.exists(photo_path):
        caption = f"{info_text}\n\n{message_text}" if message_text else info_text
        photo_file = FSInputFile(photo_path)
        await msg_obj.answer_photo(photo_file, caption=caption, reply_markup=kb, parse_mode="HTML")
    else:
        full_text = f"{info_text}\n\n<blockquote expandable>{message_text}</blockquote>"
        await msg_obj.answer(full_text, reply_markup=kb, parse_mode="HTML")

    await state.set_state(InvitingStates.confirm_usernames_mailing)


@router.callback_query(F.data == "toggle_usernames_mode", InvitingStates.confirm_usernames_mailing)
async def toggle_usernames_mode(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current = data.get('usernames_mode', 'sequential')
    new_mode = 'parallel' if current == 'sequential' else 'sequential'
    await state.update_data(usernames_mode=new_mode)
    await call.answer("⚡ Параллельно" if new_mode == "parallel" else "📝 Последовательно")
    await show_usernames_preview(call, state)


@router.callback_query(F.data == "edit_usernames_text", InvitingStates.confirm_usernames_mailing)
async def edit_usernames_text_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "✏️ Отправьте <b>новый текст сообщения</b> для рассылки:",
        parse_mode="HTML",
        reply_markup=UserKeyboards.cancel_input("cancel_to_inviting_menu"),
    )
    await state.set_state(InvitingStates.editing_usernames_text)


@router.message(InvitingStates.editing_usernames_text)
async def process_new_usernames_text(message: Message, state: FSMContext):
    if message.photo:
        photo = message.photo[-1]
        photo_path = f"downloads/usernames_{message.from_user.id}.jpg"
        await message.bot.download(photo, destination=photo_path)
        await state.update_data(message_text=message.caption or "", photo_path=photo_path)
    elif message.text:
        await state.update_data(message_text=message.text, photo_path=None)
    else:
        await message.answer("❌ Пришлите текст или фото.")
        return
    await show_usernames_preview(message, state)


@router.callback_query(F.data == "start_usernames_mailing", InvitingStates.confirm_usernames_mailing)
async def start_usernames_mailing_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    user_id = call.from_user.id

    usernames = data.get('usernames', [])
    message_text = data.get('message_text', '')
    photo_path = data.get('photo_path')
    mode = data.get('usernames_mode', 'sequential')

    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id,
        task_type=TaskType.CONTACTS_MAILING,  # переиспользуем тип, он подходит
        accounts=selected,
        message_text=message_text,
        message_delay=float(delays['message']),
        cycle_delay=float(delays.get('cycle', 60)),
        photo_path=photo_path,
    )
    if conflicts:
        await call.message.answer(
            task_manager.format_conflict_message(conflicts),
            parse_mode="HTML"
        )
        return

    mode_text = "⚡ Параллельно" if mode == "parallel" else "📝 Последовательно"

    await call.message.answer(
        f"🚀 <b>ЗАПУСК РАССЫЛКИ ПО ЮЗЕРНЕЙМАМ</b>\n\n"
        f"🆔 Таск: <b>#{task.task_id}</b>\n"
        f"👥 Юзернеймов: <b>{len(usernames)}</b>\n"
        f"📱 Аккаунтов: <b>{len(selected)}</b>\n"
        f"🔄 Режим: <b>{mode_text}</b>\n"
        f"⏱ Задержка: <b>{delays['message']}с</b>\n\n"
        f"<i>Рассылка запущена!</i>",
        parse_mode="HTML",
    )

    await prefetch_accounts_meta(user_id, selected)
    await state.clear()

    asyncio_task = asyncio.create_task(
        run_usernames_mailing(
            user_id, selected, usernames, message_text, photo_path,
            delays['message'], mode, call.message, task
        )
    )
    task.asyncio_task = asyncio_task


async def run_usernames_mailing(
        user_id: int,
        session_names: List[str],
        usernames: List[str],
        message_text: str,
        photo_path: str | None,
        message_delay: int,
        mode: str,
        original_message: Message,
        task=None,
):
    """Запустить рассылку по юзернеймам."""
    progress_msg = None

    task_id_str = task.task_id if task else "unknown"
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"task_pause:{task_id_str}"),
            InlineKeyboardButton(text="⛔ Завершить", callback_data=f"task_stop:{task_id_str}"),
        ],
        [InlineKeyboardButton(text="🗂 Мои таски", callback_data="tasks_menu")],
    ])

    async def update_progress(text: str, reply_markup=stop_kb):
        nonlocal progress_msg
        try:
            if progress_msg:
                await progress_msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                progress_msg = await original_message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            logger.debug(f"Не удалось обновить прогресс: {e}")

    try:
        await update_progress("🔄 Подготовка к рассылке по юзернеймам...")

        stats = await inviting_svc.send_to_usernames(
            session_names,
            usernames,
            message_text,
            photo_path,
            user_id,
            message_delay,
            update_progress,
            task=task,
            mode=mode,
        )

        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        final = (
            f"✅ <b>РАССЫЛКА ПО ЮЗЕРНЕЙМАМ ЗАВЕРШЕНА</b>\n\n"
            f"📊 Статистика:\n"
            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
            f"❌ Ошибок: <b>{stats['total_failed']}</b>"
        )

        if stats.get('errors'):
            error_lines = [f"• {e}" for e in stats['errors'][:20]]
            if len(stats['errors']) > 20:
                error_lines.append(f"... и ещё {len(stats['errors']) - 20} ошибок")
            error_text_content = "\n".join(error_lines)
            errors_block = (
                f"\n\n⚠️ <b>Детали ошибок:</b>\n"
                f"<blockquote expandable>{error_text_content}</blockquote>"
            )
            if len(final) + len(errors_block) > 4000:
                available = 4000 - len(final) - 60
                error_text_content = error_text_content[:max(0, available)] + "..."
                errors_block = (
                    f"\n\n⚠️ <b>Детали ошибок (обрезано):</b>\n"
                    f"<blockquote expandable>{error_text_content}</blockquote>"
                )
            final += errors_block

        await original_message.answer(final, parse_mode="HTML", reply_markup=UserKeyboards.come_to_inv())

        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.FINISHED)

    except Exception as e:
        logger.error(f"Критическая ошибка рассылки по юзернеймам: {e}")
        if progress_msg:
            try:
                await progress_msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await original_message.answer(
            f"❌ Критическая ошибка: {str(e)[:500]}",
            reply_markup=UserKeyboards.come_to_inv()
        )
        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.ERROR)


# ============= ОТПРАВКА ОДНОМУ ПОЛЬЗОВАТЕЛЮ =============

@router.callback_query(F.data == "inv:one")
async def start_one_user_sending(callback: CallbackQuery, state: FSMContext):
    """Начать отправку одному пользователю"""
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)

    if not selected:
        await callback.answer("❌ Сначала выберите аккаунты!", show_alert=True)
        return
    #
    # if inviting_svc.is_running(user_id):
    #     await callback.answer("⚠️ Уже выполняется рассылка!", show_alert=True)
    #     return

    await callback.message.edit_text(
        "✉️ <b>ОТПРАВКА ОДНОМУ</b>\n\n"
        "Отправьте username или ID целевого пользователя\n\n"
        "Примеры:\n"
        "• @username\n"
        "• 123456789",
        parse_mode="HTML"
    )
    await state.set_state(InvitingStates.waiting_target)
    await callback.answer()


@router.message(InvitingStates.waiting_target)
async def receive_target(message: Message, state: FSMContext):
    """Получить цель"""
    is_valid, error = TextValidator.validate_target(message.text)

    if not is_valid:
        await message.answer(error)
        return

    await state.update_data(target=message.text)

    await message.answer(
        f"✅ <b>Цель: {message.text}</b>\n\n"
        "Теперь отправьте текст сообщения:",
        parse_mode="HTML",
        reply_markup=await temp_kb.get_temp_keyboards(user_id=message.from_user.id)  # <-- ДОБАВИТЬ
    )
    await state.set_state(InvitingStates.waiting_one_message)


@router.message(InvitingStates.waiting_one_message)
async def receive_one_message(message: Message, state: FSMContext):
    """Получить сообщение (текст/фото) для отправки одному"""
    message_text, photo_path = await save_message_content(message)

    await state.update_data(message_text=message_text, photo_path=photo_path)
    await show_one_user_preview(message, state)  # Функция превью для "одного"


async def show_one_user_preview(message: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    msg_obj = message.message if isinstance(message, CallbackQuery) else message

    # Если мы пришли сюда по кнопке (callback), удаляем старое сообщение,
    # так как Telegram не дает сменить обычное сообщение на сообщение с фото
    if isinstance(message, CallbackQuery):
        await message.message.delete()

    target = data.get('target', 'Не указано')
    message_text = data.get('message_text', '')
    photo_path = data.get('photo_path')

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить", callback_data="start_one_sending")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_one_text")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_one_sending")],
    ])

    info = f"🎯 Получатель: <code>{target}</code>\n➖➖➖➖➖➖➖➖➖➖\n\n"

    if photo_path and os.path.exists(photo_path):
        await msg_obj.answer_photo(
            FSInputFile(photo_path),
            caption=f"✉️ <b>ПРЕДПРОСМОТР</b>\n\n{info}{message_text}",
            reply_markup=kb, parse_mode="HTML"
        )
    else:
        await msg_obj.answer(
            f"✉️ <b>ПРЕДПРОСМОТР</b>\n\n{info}{message_text}",
            reply_markup=kb, parse_mode="HTML"
        )
    await state.set_state(InvitingStates.confirm_one_sending)


# --- ЗАПУСК ---
@router.callback_query(F.data == "start_one_sending", InvitingStates.confirm_one_sending)
async def start_one_sending_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    user_id = call.from_user.id
    photo_path = data.get('photo_path')
    target = data.get('target')
    message_text = data.get('message_text')
    selected = get_selected_accounts(user_id)
    delays = get_delays(user_id)

    # ── Проверка занятости аккаунтов ──
    task, conflicts = await task_manager.try_create_task(
        user_id=user_id,
        task_type=TaskType.ONE_MAILING,
        accounts=selected,
        message_text=message_text or "",
        message_delay=float(delays['message']),
    )
    if conflicts:
        await call.message.answer(
            task_manager.format_conflict_message(conflicts),
            parse_mode="HTML"
        )
        return

    await call.message.answer(
        f"🚀 <b>Запуск отправки на {target}...</b>\n"
        f"🆔 Таск: <b>#{task.task_id}</b>",
        parse_mode="HTML"
    )

    await state.clear()
    await prefetch_accounts_meta(user_id, selected)

    asyncio_task = asyncio.create_task(
        run_one_user_sending(
            user_id, selected, target, message_text, photo_path,
            delays['message'], call.message, task
        )
    )
    task.asyncio_task = asyncio_task


# --- РЕДАКТИРОВАНИЕ ТЕКСТА ---
@router.callback_query(F.data == "edit_one_text", InvitingStates.confirm_one_sending)
async def edit_one_text_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "✏️ Отправьте <b>новый текст сообщения</b> для отправки:",
        parse_mode="HTML",
        reply_markup=await temp_kb.get_temp_keyboards(user_id=call.from_user.id)  # <-- ДОБАВИТЬ
    )
    await state.set_state(InvitingStates.editing_one_text)


@router.message(InvitingStates.editing_one_text)
async def process_new_one_text(message: Message, state: FSMContext):
    is_valid, error = TextValidator.validate_message(message.text)
    if not is_valid:
        await message.answer(error)
        return
    await state.update_data(message_text=message.text)
    await show_one_user_preview(message, state)


# --- ОТМЕНА ---
@router.callback_query(F.data == "cancel_one_sending", InvitingStates.confirm_one_sending)
async def cancel_one_sending(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text(
        call.message.html_text + "\n\n❌ <b>Отправка отменена</b>",
        parse_mode="HTML"
    )
    await state.clear()


async def run_one_user_sending(
        user_id: int,
        session_names: List[str],
        target: str,
        message_text: str,
        photo_path: str,
        message_delay: int,
        original_message: Message,
        task=None  # ← НОВЫЙ параметр
):
    """Запустить отправку одному"""
    progress_msg = None

    async def update_progress(text: str):
        nonlocal progress_msg
        try:
            if progress_msg:
                await progress_msg.edit_text(text, parse_mode="HTML", reply_markup=UserKeyboards.come_to_inv())
            else:
                progress_msg = await original_message.answer(text, parse_mode="HTML",
                                                             reply_markup=UserKeyboards.come_to_inv())
        except:
            pass

    clients = []
    try:
        await update_progress("🔄 Подключаюсь...")

        for session_name in session_names:
            try:
                client = await session_mgr.create_client(session_name, user_id)
                clients.append(client)
            except Exception as e:
                logger.error(f"Ошибка подключения сессии {session_name}: {e}")

        if not clients:
            await update_progress("❌ Не удалось подключиться ни к одному аккаунту")
            if task:
                await task_manager.finish_task(task.task_id, TaskStatus.ERROR)
            return

        stats = await inviting_svc.send_to_one_user(
            clients,
            target,
            message_text,
            photo_path,
            user_id,
            message_delay,
            update_progress
        )

        # Отдельное итоговое сообщение — прогресс не трогаем
        final = (
            f"✅ <b>ОТПРАВКА ЗАВЕРШЕНА</b>\n\n"
            f"🎯 Цель: <code>{target}</code>\n"
            f"📊 Статистика:\n"
            f"✅ Отправлено: <b>{stats['total_sent']}</b>\n"
            f"❌ Ошибок: <b>{stats['total_failed']}</b>"
        )

        if stats.get('errors'):
            error_text_content = "".join([f"• {e}\n" for e in stats['errors']])
            final += (
                f"\n\n⚠️ <b>Детали ошибок:</b>\n"
                f"<blockquote expandable>{error_text_content}</blockquote>"
            )

        await original_message.answer(final, parse_mode="HTML", reply_markup=UserKeyboards.come_to_inv())

        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.FINISHED)

    except Exception as e:
        logger.error(f"Ошибка при отправке одному: {e}")
        await original_message.answer(f"❌ Ошибка: {str(e)}", reply_markup=UserKeyboards.come_to_inv())
        if task:
            await task_manager.finish_task(task.task_id, TaskStatus.ERROR)

    finally:
        for client in clients:
            try:
                if client.is_connected():
                    await client.stop()
            except Exception as e:
                logger.debug(f"Ошибка остановки клиента: {e}")


# ============= НАСТРОЙКА ЗАДЕРЖЕК =============

@router.callback_query(F.data == "inv:delays")
async def show_delays_settings(callback: CallbackQuery):
    """Показать настройки задержек"""
    user_id = callback.from_user.id
    delays = get_delays(user_id)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=f"⏱ Между сообщениями: {delays['message']}с",
            callback_data="inv_delay:message"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text=f"⏱ Между циклами: {delays['cycle']}с",
            callback_data="inv_delay:cycle"
        )
    )
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="inviting"))

    await callback.message.edit_text(
        "⚙️ <b>НАСТРОЙКИ ЗАДЕРЖЕК</b>\n\n"
        f"⏱ Задержка между сообщениями: <b>{delays['message']}с</b>\n"
        f"⏱ Задержка между циклами: <b>{delays['cycle']}с</b>\n\n"
        "<i>Выберите что хотите изменить</i>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("inv_delay:"))
async def start_delay_change(callback: CallbackQuery, state: FSMContext):
    """Начать изменение задержки"""
    delay_type = callback.data.split(":")[1]

    names = {
        "message": "между сообщениями",
        "cycle": "между циклами"
    }

    await callback.message.edit_text(
        f"⏱ <b>Задержка {names[delay_type]}</b>\n\n"
        f"Отправьте новое значение в секундах\n\n"
        f"Минимум: 1 секунда\n"
        f"Максимум: 3600 секунд (1 час)",
        parse_mode="HTML"
    )

    if delay_type == "message":
        await state.set_state(InvitingStates.waiting_message_delay)
    else:
        await state.set_state(InvitingStates.waiting_cycle_delay)

    await callback.answer()


@router.message(InvitingStates.waiting_message_delay)
async def receive_message_delay(message: Message, state: FSMContext):
    """Получить задержку между сообщениями"""
    try:
        delay = int(message.text)
        if delay < 1 or delay > 3600:
            await message.answer("❌ Значение должно быть от 1 до 3600")
            return

        user_id = message.from_user.id
        # FIX: вызываем set_delays() для сохранения в JSON (раньше менялся только локальный dict)
        set_delays(user_id, message_delay=delay)

        await message.answer(
            f"✅ Задержка между сообщениями установлена: <b>{delay}с</b>",
            reply_markup=UserKeyboards.inv_menu(),
            parse_mode="HTML"
        )

        await state.clear()

    except ValueError:
        await message.answer("❌ Отправьте число!")


@router.message(InvitingStates.waiting_cycle_delay)
async def receive_cycle_delay(message: Message, state: FSMContext):
    """Получить задержку между циклами"""
    try:
        delay = int(message.text)
        if delay < 1 or delay > 3600:
            await message.answer("❌ Значение должно быть от 1 до 3600")
            return

        user_id = message.from_user.id
        # FIX: вызываем set_delays() для сохранения в JSON (раньше менялся только локальный dict)
        set_delays(user_id, cycle_delay=delay)

        await message.answer(
            f"✅ Задержка между циклами установлена: <b>{delay}с</b>",
            reply_markup=UserKeyboards.inv_menu(),
            parse_mode="HTML"
        )

        await state.clear()

    except ValueError:
        await message.answer("❌ Отправьте число!")


async def save_message_content(message: Message):
    """Скачивает фото если есть и возвращает (текст, путь_к_фото)"""
    photo_path = None
    if message.photo:
        photo = message.photo[-1]
        photo_path = f"downloads/msg_{message.from_user.id}.jpg"
        await message.bot.download(photo, destination=photo_path)
        return message.caption or "", photo_path
    return message.text or "", None