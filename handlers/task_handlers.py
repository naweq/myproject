# ==========================================
# ФАЙЛ: task_handlers.py
# ОПИСАНИЕ: Меню тасков — просмотр, управление, пауза, редактирование
# ==========================================

import asyncio
import time
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from modules.account_cache import get_account_meta
from modules.task_manager import task_manager, AccountMeta

logger = logging.getLogger(__name__)
router = Router()


# ─────────────────────────────────────────────────────────────────────────────
# FSM — редактирование параметров приостановленного таска
# ─────────────────────────────────────────────────────────────────────────────

class EditTaskStates(StatesGroup):
    edit_text        = State()
    edit_msg_delay   = State()
    edit_cycle_delay = State()


# ─────────────────────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────────────────────

def kb_tasks_list(user_id: int) -> InlineKeyboardMarkup:
    """Список активных тасков пользователя"""
    tasks = task_manager.get_user_tasks(user_id, only_active=True)
    builder = InlineKeyboardBuilder()

    if not tasks:
        builder.row(InlineKeyboardButton(
            text="📭 Нет активных тасков",
            callback_data="tasks_noop"
        ))
    else:
        for t in tasks:
            icon = "🟢" if t.is_running else "⏸"
            label = f"{icon} #{t.task_id} · {t.task_type.value[:22]}"
            builder.row(InlineKeyboardButton(
                text=label,
                callback_data=f"task_view:{t.task_id}"
            ))

    # Завершённые таски (последние 3)
    finished = [
        t for t in task_manager.get_user_tasks(user_id)
        if not t.is_active
    ][:3]

    if finished:
        builder.row(InlineKeyboardButton(
            text="─── Завершённые ───",
            callback_data="tasks_noop"
        ))
        for t in finished:
            label = f"✅ #{t.task_id} · {t.task_type.value[:22]}"
            builder.row(InlineKeyboardButton(
                text=label,
                callback_data=f"task_view:{t.task_id}"
            ))

    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="tasks_refresh"))
    return builder.as_markup()


def kb_task_detail(task_id: str, is_paused: bool, is_active: bool) -> InlineKeyboardMarkup:
    """Клавиатура детальной страницы таска"""
    builder = InlineKeyboardBuilder()

    if is_active:
        if is_paused:
            # На паузе — можно возобновить, редактировать, остановить
            builder.row(
                InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"task_resume:{task_id}"),
                InlineKeyboardButton(text="⛔ Завершить",  callback_data=f"task_stop:{task_id}")
            )
            builder.row(
                InlineKeyboardButton(text="✏️ Изменить текст",    callback_data=f"task_edit_text:{task_id}"),
                InlineKeyboardButton(text="⏱ Изменить задержки", callback_data=f"task_edit_delays:{task_id}")
            )
        else:
            # Запущен — можно поставить на паузу или остановить
            builder.row(
                InlineKeyboardButton(text="⏸ Пауза",    callback_data=f"task_pause:{task_id}"),
                InlineKeyboardButton(text="⛔ Завершить", callback_data=f"task_stop:{task_id}")
            )

    builder.row(
        InlineKeyboardButton(text="🔄 Обновить",       callback_data=f"task_view:{task_id}"),
        InlineKeyboardButton(text="◀️ К списку тасков", callback_data="tasks_menu")
    )
    return builder.as_markup()


def kb_cancel_edit(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"task_view:{task_id}")
    ]])


# ─────────────────────────────────────────────────────────────────────────────
# ФОРМАТИРОВАНИЕ ДЕТАЛЬНОЙ СТРАНИЦЫ ТАСКА
# ─────────────────────────────────────────────────────────────────────────────

def _format_task_detail(task_id: str) -> str:
    """Сформировать полное сообщение по таску"""
    from modules.task_manager import task_manager

    task = task_manager.get_task(task_id)
    if not task:
        return "❌ Таск не найден"

    # ── Шапка ──
    status_line = task.status_icon()
    lines = [
        f"📋 <b>ТАСК #{task.task_id}</b>",
        f"",
        f"⚙️ Тип: <b>{task.task_type.value}</b>",
        f"📊 Статус: <b>{status_line}</b>",
        f"🕐 Запущен: <b>{task.created_at.strftime('%d.%m %H:%M:%S')}</b>",
        f"⏳ Работает: <b>{task.elapsed()}</b>",
        f"📡 Пинг: <b>{task.ping_str()}</b>",
        f"",
    ]

    # ── Текст рассылки ──
    if task.message_text:
        text_preview = task.message_text[:300]
        if len(task.message_text) > 300:
            text_preview += "..."
        lines += [
            f"💬 <b>Текст рассылки:</b>",
            f"<blockquote>{text_preview}</blockquote>",
            f"",
        ]

    # ── Задержки ──
    lines += [
        f"⏱ <b>Задержки:</b>",
        f"   • Между сообщениями: <b>{task.message_delay}с</b>",
        f"   • Между циклами: <b>{task.cycle_delay}с</b>",
        f"",
    ]

    # ── Статистика ──
    s = task.stats
    lines += [
        f"📈 <b>Статистика:</b>",
        f"   ✅ Отправлено: <b>{s.sent}</b>",
        f"   ❌ Ошибок: <b>{s.failed}</b>",
    ]
    if s.joined:
        lines.append(f"   ➕ Вступлений: <b>{s.joined}</b>")
    if s.cycles:
        lines.append(f"   🔄 Циклов: <b>{s.cycles}</b>")
    if s.current_account:
        lines.append(f"   🔁 Сейчас: <code>{s.current_account}</code>")
    lines.append("")

    # ── Аккаунты ──
    lines.append(f"📱 <b>Аккаунты ({len(task.accounts)}):</b>")

    if task.accounts_meta:
        for meta in task.accounts_meta:
            block = meta.expandable_block()
            lines.append(f"<blockquote expandable>{block}</blockquote>")
    else:
        # Метаданные ещё грузятся — показываем просто имена
        for acc in task.accounts:
            clean = acc.replace(".session", "")
            lines.append(f"<blockquote><code>{clean}</code></blockquote>")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# ПИНГ — замер задержки до Telegram API
# ─────────────────────────────────────────────────────────────────────────────

async def _measure_ping(task_id: str, user_id: int):
    """Фоновая задача: замерить пинг и сохранить в таск"""
    from config import bot
    try:
        t0 = time.time()
        await bot.get_me()
        ping = (time.time() - t0) * 1000
        task_manager.update_ping(task_id, ping)
        logger.debug(f"Пинг таска #{task_id}: {ping:.0f}мс")
    except Exception as e:
        logger.debug(f"Ошибка замера пинга: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА МЕТАДАННЫХ АККАУНТОВ
# ─────────────────────────────────────────────────────────────────────────────

async def _load_account_meta(task_id: str, user_id: int):
    """
    Загрузить метаданные аккаунтов из JSON-кеша — без подключения к сессии.
    Если в кеше нет данных — показываем имя файла (не лезем в сессию пока она может быть занята).
    """
    task = task_manager.get_task(task_id)
    if not task:
        return

    meta_list = []
    for acc_name in task.accounts:
        meta = AccountMeta(session_name=acc_name)

        # Читаем из кеша — никаких подключений
        cached = get_account_meta(user_id, acc_name)
        if cached:
            meta.full_name = cached.get("full_name", "")
            meta.phone     = cached.get("phone", "")
            meta.username  = cached.get("username", "")
            meta.user_id   = cached.get("user_id", 0) or 0
        # Если в кеше нет — оставляем пустым, имя файла уже есть в session_name

        meta_list.append(meta)

    task_manager.set_account_meta(task_id, meta_list)
    logger.info(f"✅ Мета аккаунтов загружена из кеша для таска #{task_id}")



# ─────────────────────────────────────────────────────────────────────────────
# ХЕНДЛЕРЫ
# ─────────────────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "tasking")
async def call_tasks(callback: CallbackQuery):
    user_id = callback.message.from_user.id
    active = task_manager.get_user_tasks(user_id, only_active=True)
    total = task_manager.get_user_tasks(user_id)

    header = (
        f"🗂 <b>МОИ ТАСКИ</b>\n\n"
        f"🟢 Активных: <b>{len(active)}</b>\n"
        f"📦 Всего: <b>{len(total)}</b>\n\n"
        f"<i>Нажмите на таск для управления:</i>"
    )
    await callback.message.answer(header, reply_markup=kb_tasks_list(user_id), parse_mode="HTML")


@router.message(F.text == "📋 Задачи")
@router.message(F.text == "/tasks")
async def cmd_tasks(message: Message):
    """Команда /tasks — меню тасков"""
    user_id = message.from_user.id
    active  = task_manager.get_user_tasks(user_id, only_active=True)
    total   = task_manager.get_user_tasks(user_id)

    header = (
        f"🗂 <b>МОИ ТАСКИ</b>\n\n"
        f"🟢 Активных: <b>{len(active)}</b>\n"
        f"📦 Всего: <b>{len(total)}</b>\n\n"
        f"<i>Нажмите на таск для управления:</i>"
    )
    await message.answer(header, reply_markup=kb_tasks_list(user_id), parse_mode="HTML")


@router.callback_query(F.data == "tasks_menu")
async def cb_tasks_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    active  = task_manager.get_user_tasks(user_id, only_active=True)
    total   = task_manager.get_user_tasks(user_id)

    header = (
        f"🗂 <b>МОИ ТАСКИ</b>\n\n"
        f"🟢 Активных: <b>{len(active)}</b>\n"
        f"📦 Всего: <b>{len(total)}</b>\n\n"
        f"<i>Нажмите на таск для управления:</i>"
    )
    try:
        await callback.message.answer(header, reply_markup=kb_tasks_list(user_id), parse_mode="HTML")
    except Exception:
        await callback.message.answer(header, reply_markup=kb_tasks_list(user_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "tasks_refresh")
async def cb_tasks_refresh(callback: CallbackQuery):
    user_id = callback.from_user.id
    active  = task_manager.get_user_tasks(user_id, only_active=True)
    total   = task_manager.get_user_tasks(user_id)

    header = (
        f"🗂 <b>МОИ ТАСКИ</b>\n\n"
        f"🟢 Активных: <b>{len(active)}</b>\n"
        f"📦 Всего: <b>{len(total)}</b>\n\n"
        f"<i>Нажмите на таск для управления:</i>"
    )
    try:
        await callback.message.edit_text(header, reply_markup=kb_tasks_list(user_id), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("🔄 Обновлено")


@router.callback_query(F.data == "tasks_noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ── Детальный просмотр таска ──

@router.callback_query(F.data.startswith("task_view:"))
async def cb_task_view(callback: CallbackQuery):
    task_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    task = task_manager.get_task(task_id)
    if not task or task.user_id != user_id:
        await callback.answer("❌ Таск не найден", show_alert=True)
        return

    # Запускаем фоновые задачи замера пинга и загрузки мета
    asyncio.create_task(_measure_ping(task_id, user_id))
    if not task.accounts_meta:
        asyncio.create_task(_load_account_meta(task_id, user_id))

    text = _format_task_detail(task_id)
    kb   = kb_task_detail(task_id, task.is_paused, task.is_active)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ── Пауза ──

@router.callback_query(F.data.startswith("task_pause:"))
async def cb_task_pause(callback: CallbackQuery):
    task_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    task = task_manager.get_task(task_id)
    if not task or task.user_id != user_id:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    ok = await task_manager.pause_task(task_id)
    if ok:
        await callback.answer("⏸ Таск поставлен на паузу", show_alert=True)
        text = _format_task_detail(task_id)
        kb   = kb_task_detail(task_id, True, True)
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await callback.answer("⚠️ Не удалось поставить на паузу", show_alert=True)


# ── Возобновить ──

@router.callback_query(F.data.startswith("task_resume:"))
async def cb_task_resume(callback: CallbackQuery):
    task_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    task = task_manager.get_task(task_id)
    if not task or task.user_id != user_id:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    ok = await task_manager.resume_task(task_id)
    if ok:
        await callback.answer("▶️ Таск возобновлён!", show_alert=True)
        text = _format_task_detail(task_id)
        kb   = kb_task_detail(task_id, False, True)
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await callback.answer("⚠️ Не удалось возобновить", show_alert=True)


# ── Стоп ──

@router.callback_query(F.data.startswith("task_stop:"))
async def cb_task_stop(callback: CallbackQuery):
    task_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    task = task_manager.get_task(task_id)
    if not task or task.user_id != user_id:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    ok = await task_manager.stop_task(task_id)
    if ok:
        await callback.answer("⛔ Таск завершён", show_alert=True)
        text = _format_task_detail(task_id)
        kb   = kb_task_detail(task_id, False, False)
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        await callback.answer("⚠️ Таск уже завершён", show_alert=True)


# ── Редактирование текста (только на паузе) ──

@router.callback_query(F.data.startswith("task_edit_text:"))
async def cb_edit_text_start(callback: CallbackQuery, state: FSMContext):
    task_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    task = task_manager.get_task(task_id)
    if not task or task.user_id != user_id:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    if not task.is_paused:
        await callback.answer("⚠️ Сначала поставьте таск на паузу", show_alert=True)
        return

    await state.update_data(editing_task_id=task_id)
    await state.set_state(EditTaskStates.edit_text)

    current_text = task.message_text or "(пусто)"
    await callback.message.answer(
        f"✏️ <b>Изменение текста таска #{task_id}</b>\n\n"
        f"Текущий текст:\n<blockquote>{current_text[:400]}</blockquote>\n\n"
        f"<i>Отправьте новый текст рассылки:</i>",
        reply_markup=kb_cancel_edit(task_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditTaskStates.edit_text)
async def cb_edit_text_receive(message: Message, state: FSMContext):
    data    = await state.get_data()
    task_id = data.get("editing_task_id")

    if not task_id:
        await state.clear()
        return

    task = task_manager.get_task(task_id)
    if not task or task.user_id != message.from_user.id:
        await message.answer("❌ Таск не найден")
        await state.clear()
        return

    task_manager.update_task_params(task_id, message_text=message.text)
    await state.clear()

    await message.answer(
        f"✅ <b>Текст таска #{task_id} обновлён!</b>\n\n"
        f"<blockquote>{message.text[:300]}</blockquote>",
        parse_mode="HTML"
    )

    # Показать обновлённый таск
    text = _format_task_detail(task_id)
    kb   = kb_task_detail(task_id, task.is_paused, task.is_active)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ── Редактирование задержек (только на паузе) ──

@router.callback_query(F.data.startswith("task_edit_delays:"))
async def cb_edit_delays_start(callback: CallbackQuery, state: FSMContext):
    task_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    task = task_manager.get_task(task_id)
    if not task or task.user_id != user_id:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    if not task.is_paused:
        await callback.answer("⚠️ Сначала поставьте таск на паузу", show_alert=True)
        return

    await state.update_data(editing_task_id=task_id)
    await state.set_state(EditTaskStates.edit_msg_delay)

    await callback.message.answer(
        f"⏱ <b>Изменение задержек таска #{task_id}</b>\n\n"
        f"Текущие:\n"
        f"  • Между сообщениями: <b>{task.message_delay}с</b>\n"
        f"  • Между циклами: <b>{task.cycle_delay}с</b>\n\n"
        f"<i>Введите новую задержку <b>между сообщениями</b> (в секундах, например: 5):</i>",
        reply_markup=kb_cancel_edit(task_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditTaskStates.edit_msg_delay)
async def cb_edit_msg_delay(message: Message, state: FSMContext):
    try:
        delay = float(message.text.replace(",", "."))
        if delay < 0.5:
            await message.answer("⚠️ Минимальная задержка 0.5 секунды")
            return
    except ValueError:
        await message.answer("❌ Введите число, например: 3 или 2.5")
        return

    await state.update_data(new_msg_delay=delay)
    await state.set_state(EditTaskStates.edit_cycle_delay)

    await message.answer(
        f"✅ Задержка между сообщениями: <b>{delay}с</b>\n\n"
        f"<i>Теперь введите задержку <b>между циклами</b> (в секундах, например: 60):</i>",
        parse_mode="HTML"
    )


@router.message(EditTaskStates.edit_cycle_delay)
async def cb_edit_cycle_delay(message: Message, state: FSMContext):
    try:
        delay = float(message.text.replace(",", "."))
        if delay < 1:
            await message.answer("⚠️ Минимальная задержка цикла 1 секунда")
            return
    except ValueError:
        await message.answer("❌ Введите число, например: 60")
        return

    data    = await state.get_data()
    task_id = data.get("editing_task_id")
    msg_delay = data.get("new_msg_delay", 5.0)

    await state.clear()

    task = task_manager.get_task(task_id)
    if not task or task.user_id != message.from_user.id:
        await message.answer("❌ Таск не найден")
        return

    task_manager.update_task_params(task_id, message_delay=msg_delay, cycle_delay=delay)

    await message.answer(
        f"✅ <b>Задержки таска #{task_id} обновлены!</b>\n\n"
        f"  • Между сообщениями: <b>{msg_delay}с</b>\n"
        f"  • Между циклами: <b>{delay}с</b>",
        parse_mode="HTML"
    )

    text = _format_task_detail(task_id)
    kb   = kb_task_detail(task_id, task.is_paused, task.is_active)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
