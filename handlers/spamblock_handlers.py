# ==========================================
# ФАЙЛ: spamblock_handlers.py
# ОПИСАНИЕ: Хендлеры меню автоснятия спамблока
# ==========================================

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from spamblock_config import (
    get_spamblock_config, DEFAULT_APPEAL_TEMPLATES
)

logger = logging.getLogger(__name__)
router = Router()


# ──────────────────────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ — вывод главного меню
# ──────────────────────────────────────────────────────────────────────────────

async def _show_sb_main(callback: CallbackQuery):
    """Обновить или показать главное меню настроек спамблока."""
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    s = cfg.to_summary_dict()
    tpl = cfg.get_active_template()
    tpl_preview = ""
    if tpl:
        preview_text = tpl["text"][:120] + ("..." if len(tpl["text"]) > 120 else "")
        tpl_preview = f"\n📝 <i>{preview_text}</i>"

    text = (
        "🛡 <b>АВТОСНЯТИЕ СПАМБЛОКА</b>\n\n"
        f"Статус: <b>{'✅ Включено' if s['enabled'] else '❌ Выключено'}</b>\n"
        f"Перевод апелляции: <b>{'🌍 ВКЛ' if s['auto_translate'] else 'ВЫКЛ'}</b>\n"
        f"Ожидание (Premium): <b>{s['premium_retry_wait'] // 60}–{s['premium_retry_wait_max'] // 60} мин</b>\n"
        f"Активный шаблон: <b>{s['active_template_name']}</b>{tpl_preview}\n"
        f"Пользовательских шаблонов: <b>{s['custom_templates_count']}</b>\n\n"
        "<i>При обнаружении PeerFlood во время рассылки бот "
        "автоматически предпримет попытку снятия ограничений.</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb_spamblock_main(user_id), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb_spamblock_main(user_id), parse_mode="HTML")


# ──────────────────────────────────────────────────────────────────────────────
# СОСТОЯНИЯ
# ──────────────────────────────────────────────────────────────────────────────

class SpamBlockStates(StatesGroup):
    # Добавление кастомного шаблона
    waiting_template_name = State()
    waiting_template_text = State()
    # Редактирование шаблона
    editing_template_choose_field = State()
    editing_template_name = State()
    editing_template_text = State()
    # Задержка ожидания
    waiting_retry_min = State()
    waiting_retry_max = State()


# ──────────────────────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ──────────────────────────────────────────────────────────────────────────────

def kb_spamblock_main(user_id: int) -> InlineKeyboardMarkup:
    cfg = get_spamblock_config(user_id)
    enabled_text = "✅ Включено" if cfg.enabled else "❌ Выключено"
    translate_text = "🌍 Перевод: ВКЛ" if cfg.auto_translate else "🌍 Перевод: ВЫКЛ"
    tpl = cfg.get_active_template()
    tpl_name = tpl["name"] if tpl else "Не выбран"
    wait_text = f"{cfg.premium_retry_wait // 60}–{cfg.premium_retry_wait_max // 60} мин"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text=f"{'🟢' if cfg.enabled else '🔴'} Автоснятие: {enabled_text}",
        callback_data="sb:toggle_enabled"
    ))
    kb.row(InlineKeyboardButton(
        text=f"📋 Шаблон: {tpl_name}",
        callback_data="sb:templates_menu"
    ))
    kb.row(InlineKeyboardButton(
        text=f"⏱ Ожидание Premium: {wait_text}",
        callback_data="sb:set_wait"
    ))
    kb.row(InlineKeyboardButton(
        text=translate_text,
        callback_data="sb:toggle_translate"
    ))
    kb.row(InlineKeyboardButton(text="ℹ️ Как это работает?", callback_data="sb:howto"))
    kb.row(InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data="user_settings"))
    return kb.as_markup()


def kb_templates_menu(user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    cfg = get_spamblock_config(user_id)
    all_templates = cfg.get_all_templates()
    active_id = cfg.active_template_id

    per_page = 5
    start = page * per_page
    end = start + per_page
    page_templates = all_templates[start:end]
    total_pages = (len(all_templates) + per_page - 1) // per_page

    kb = InlineKeyboardBuilder()

    for tpl in page_templates:
        is_active = tpl["id"] == active_id
        prefix = "✅ " if is_active else ""
        builtin_mark = " 🔒" if tpl.get("builtin") else " ✏️"
        btn_text = f"{prefix}{tpl['name']}{builtin_mark}"
        kb.row(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"sb:tpl_view:{tpl['id']}"
        ))

    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"sb:tpl_page:{page - 1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}", callback_data="sb:tpl_noop"
        ))
    if end < len(all_templates):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"sb:tpl_page:{page + 1}"))
    if nav:
        kb.row(*nav)

    kb.row(InlineKeyboardButton(text="➕ Добавить шаблон", callback_data="sb:tpl_add"))
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="sb:main"))
    return kb.as_markup()


def kb_template_view(template_id: str, is_builtin: bool, is_active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not is_active:
        kb.row(InlineKeyboardButton(
            text="✅ Выбрать этот шаблон",
            callback_data=f"sb:tpl_select:{template_id}"
        ))
    else:
        kb.row(InlineKeyboardButton(
            text="✅ Активный шаблон",
            callback_data="sb:tpl_noop"
        ))
    if not is_builtin:
        kb.row(
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"sb:tpl_edit:{template_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sb:tpl_delete_ask:{template_id}"),
        )
    kb.row(InlineKeyboardButton(text="🔙 К шаблонам", callback_data="sb:templates_menu"))
    return kb.as_markup()


# ──────────────────────────────────────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ СПАМБЛОКА
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sb:main")
@router.callback_query(F.data == "spamblock_settings")
async def sb_main_menu(callback: CallbackQuery, state: FSMContext):
    """Главное меню автоснятия спамблока."""
    await state.clear()
    await _show_sb_main(callback)
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# ПЕРЕКЛЮЧАТЕЛИ
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sb:toggle_enabled")
async def sb_toggle_enabled(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    cfg.enabled = not cfg.enabled
    status = "✅ включено" if cfg.enabled else "❌ выключено"
    await callback.answer(f"Автоснятие спамблока {status}", show_alert=False)
    await _show_sb_main(callback)


@router.callback_query(F.data == "sb:toggle_translate")
async def sb_toggle_translate(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    cfg.auto_translate = not cfg.auto_translate
    status = "включён" if cfg.auto_translate else "выключен"
    await callback.answer(f"Автоперевод {status}")
    await _show_sb_main(callback)


# ──────────────────────────────────────────────────────────────────────────────
# НАСТРОЙКА ЗАДЕРЖКИ
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sb:set_wait")
async def sb_set_wait_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    await callback.message.edit_text(
        f"⏱ <b>Время ожидания перед повтором (Premium-аккаунты)</b>\n\n"
        f"Текущее: <b>{cfg.premium_retry_wait // 60}–{cfg.premium_retry_wait_max // 60} мин</b>\n\n"
        "Введите <b>минимальное</b> время ожидания в минутах (от 1 до 10):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="sb:main")]
        ])
    )
    await state.set_state(SpamBlockStates.waiting_retry_min)
    await callback.answer()


@router.message(SpamBlockStates.waiting_retry_min)
async def sb_receive_retry_min(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
        if not 1 <= val <= 10:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 1 до 10")
        return

    await state.update_data(retry_min=val * 60)
    await message.answer(
        f"✅ Минимум: <b>{val} мин</b>\n\n"
        "Теперь введите <b>максимальное</b> время ожидания (≥ минимального, до 10 мин):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="sb:main")]
        ])
    )
    await state.set_state(SpamBlockStates.waiting_retry_max)


@router.message(SpamBlockStates.waiting_retry_max)
async def sb_receive_retry_max(message: Message, state: FSMContext):
    data = await state.get_data()
    retry_min = data.get("retry_min", 180)

    try:
        val = int(message.text.strip())
        if not 1 <= val <= 10:
            raise ValueError
        val_sec = val * 60
        if val_sec < retry_min:
            await message.answer(f"❌ Максимум не может быть меньше минимума ({retry_min // 60} мин)")
            return
    except ValueError:
        await message.answer("❌ Введите число от 1 до 10")
        return

    user_id = message.from_user.id
    cfg = get_spamblock_config(user_id)
    cfg.premium_retry_wait = retry_min
    cfg.premium_retry_wait_max = val_sec

    await state.clear()
    await message.answer(
        f"✅ Время ожидания установлено: <b>{retry_min // 60}–{val} мин</b>\n\n"
        "Возвращайтесь в настройки:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛡 К настройкам спамблока", callback_data="sb:main")]
        ])
    )


# ──────────────────────────────────────────────────────────────────────────────
# КАК РАБОТАЕТ
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sb:howto")
async def sb_howto(callback: CallbackQuery):
    text = (
        "🛡 <b>Как работает автоснятие спамблока</b>\n\n"
        "<b>Когда срабатывает:</b>\n"
        "При обнаружении ошибки <code>PeerFlood</code> во время рассылки.\n\n"
        "<b>💎 Premium-аккаунт:</b>\n"
        "1. Отправляет /start в @SpamBot\n"
        "2. Ждёт указанное время (3–4 мин по умолчанию)\n"
        "3. Продолжает рассылку\n\n"
        "<b>📱 Обычный аккаунт:</b>\n"
        "1. Определяет язык по номеру телефона (если включён перевод)\n"
        "2. Переводит текст апелляции на нужный язык\n"
        "3. Отправляет /start в @SpamBot\n"
        "4. Отправляет текст апелляции\n"
        "5. Рассылка с этого аккаунта приостанавливается\n\n"
        "<b>Шаблоны апелляций:</b>\n"
        "Встроенные шаблоны — заготовленные тексты.\n"
        "Вы можете добавить свои собственные шаблоны.\n"
        "🔒 — встроенный (нельзя удалить)\n"
        "✏️ — пользовательский (можно редактировать)\n\n"
        "<i>⚠️ Результат зависит от решения Telegram. "
        "Автоснятие повышает шансы, но не гарантирует успех.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="sb:main")]
        ])
    )
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# МЕНЮ ШАБЛОНОВ
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sb:templates_menu")
async def sb_templates_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    all_tpls = cfg.get_all_templates()

    text = (
        f"📋 <b>ШАБЛОНЫ АПЕЛЛЯЦИЙ</b>\n\n"
        f"Всего: <b>{len(all_tpls)}</b> шаблонов "
        f"({len(DEFAULT_APPEAL_TEMPLATES)} встроенных + {len(all_tpls) - len(DEFAULT_APPEAL_TEMPLATES)} ваших)\n"
        f"Активный: <b>{cfg.get_active_template()['name'] if cfg.get_active_template() else '—'}</b>\n\n"
        "Нажмите на шаблон для просмотра и выбора.\n"
        "🔒 — встроенный  |  ✏️ — пользовательский"
    )

    try:
        await callback.message.edit_text(text, reply_markup=kb_templates_menu(user_id), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb_templates_menu(user_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sb:tpl_page:"))
async def sb_tpl_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    await callback.message.edit_reply_markup(reply_markup=kb_templates_menu(user_id, page))
    await callback.answer()


@router.callback_query(F.data == "sb:tpl_noop")
async def sb_tpl_noop(callback: CallbackQuery):
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# ПРОСМОТР ШАБЛОНА
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sb:tpl_view:"))
async def sb_tpl_view(callback: CallbackQuery):
    template_id = callback.data[len("sb:tpl_view:"):]
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    tpl = cfg.get_template(template_id)

    if not tpl:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    is_active = template_id == cfg.active_template_id
    is_builtin = tpl.get("builtin", False)
    active_mark = " ✅" if is_active else ""

    text = (
        f"📋 <b>Шаблон: {tpl['name']}{active_mark}</b>\n"
        f"{'🔒 Встроенный' if is_builtin else '✏️ Пользовательский'}\n\n"
        f"<blockquote>{tpl['text']}</blockquote>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb_template_view(template_id, is_builtin, is_active),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sb:tpl_select:"))
async def sb_tpl_select(callback: CallbackQuery):
    template_id = callback.data[len("sb:tpl_select:"):]
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    tpl = cfg.get_template(template_id)

    if not tpl:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    cfg.active_template_id = template_id
    await callback.answer(f"✅ Выбран шаблон: {tpl['name']}")

    # Обновляем кнопки
    is_builtin = tpl.get("builtin", False)
    await callback.message.edit_reply_markup(
        reply_markup=kb_template_view(template_id, is_builtin, True)
    )


# ──────────────────────────────────────────────────────────────────────────────
# ДОБАВЛЕНИЕ ШАБЛОНА
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sb:tpl_add")
async def sb_tpl_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "➕ <b>Новый шаблон апелляции</b>\n\n"
        "Введите <b>название</b> шаблона (не более 40 символов):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="sb:templates_menu")]
        ])
    )
    await state.set_state(SpamBlockStates.waiting_template_name)
    await callback.answer()


@router.message(SpamBlockStates.waiting_template_name)
async def sb_tpl_receive_name(message: Message, state: FSMContext):
    name = message.text.strip()[:40]
    if not name:
        await message.answer("❌ Название не может быть пустым")
        return

    await state.update_data(template_name=name)
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "Теперь введите <b>текст апелляции</b>.\n"
        "Это текст, который будет отправлен в @SpamBot.\n\n"
        "<i>Совет: пишите от первого лица, кратко объясните ситуацию.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="sb:templates_menu")]
        ])
    )
    await state.set_state(SpamBlockStates.waiting_template_text)


@router.message(SpamBlockStates.waiting_template_text)
async def sb_tpl_receive_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("❌ Текст не может быть пустым")
        return
    if len(text) > 4000:
        await message.answer("❌ Текст слишком длинный (максимум 4000 символов)")
        return

    data = await state.get_data()
    name = data.get("template_name", "Новый шаблон")

    user_id = message.from_user.id
    cfg = get_spamblock_config(user_id)
    template_id = cfg.add_custom_template(name, text)
    # Автоматически выбираем новый шаблон
    cfg.active_template_id = template_id

    await state.clear()
    await message.answer(
        f"✅ <b>Шаблон «{name}» добавлен и выбран!</b>\n\n"
        f"<blockquote>{text[:300]}{'...' if len(text) > 300 else ''}</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 К шаблонам", callback_data="sb:templates_menu")],
            [InlineKeyboardButton(text="🛡 К настройкам", callback_data="sb:main")],
        ])
    )


# ──────────────────────────────────────────────────────────────────────────────
# РЕДАКТИРОВАНИЕ ПОЛЬЗОВАТЕЛЬСКОГО ШАБЛОНА
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sb:tpl_edit:"))
async def sb_tpl_edit_start(callback: CallbackQuery, state: FSMContext):
    template_id = callback.data[len("sb:tpl_edit:"):]
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    tpl = cfg.get_template(template_id)

    if not tpl or tpl.get("builtin"):
        await callback.answer("❌ Встроенные шаблоны нельзя редактировать", show_alert=True)
        return

    await state.update_data(editing_template_id=template_id)
    await callback.message.edit_text(
        f"✏️ <b>Редактирование шаблона «{tpl['name']}»</b>\n\nЧто изменить?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Название", callback_data=f"sb:tpl_edit_name:{template_id}")],
            [InlineKeyboardButton(text="📄 Текст апелляции", callback_data=f"sb:tpl_edit_text:{template_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"sb:tpl_view:{template_id}")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sb:tpl_edit_name:"))
async def sb_tpl_edit_name_start(callback: CallbackQuery, state: FSMContext):
    template_id = callback.data[len("sb:tpl_edit_name:"):]
    await state.update_data(editing_template_id=template_id)
    await callback.message.edit_text(
        "📝 Введите новое <b>название</b> шаблона:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"sb:tpl_view:{template_id}")]
        ])
    )
    await state.set_state(SpamBlockStates.editing_template_name)
    await callback.answer()


@router.message(SpamBlockStates.editing_template_name)
async def sb_tpl_save_name(message: Message, state: FSMContext):
    data = await state.get_data()
    template_id = data.get("editing_template_id")
    new_name = message.text.strip()[:40]

    user_id = message.from_user.id
    cfg = get_spamblock_config(user_id)
    cfg.update_custom_template(template_id, name=new_name)

    await state.clear()
    await message.answer(
        f"✅ Название изменено на <b>{new_name}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 Просмотр шаблона", callback_data=f"sb:tpl_view:{template_id}")],
        ])
    )


@router.callback_query(F.data.startswith("sb:tpl_edit_text:"))
async def sb_tpl_edit_text_start(callback: CallbackQuery, state: FSMContext):
    template_id = callback.data[len("sb:tpl_edit_text:"):]
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    tpl = cfg.get_template(template_id)

    await state.update_data(editing_template_id=template_id)
    await callback.message.edit_text(
        f"📄 Текущий текст:\n<blockquote>{tpl['text'][:500]}</blockquote>\n\n"
        "Введите <b>новый текст</b> апелляции:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"sb:tpl_view:{template_id}")]
        ])
    )
    await state.set_state(SpamBlockStates.editing_template_text)
    await callback.answer()


@router.message(SpamBlockStates.editing_template_text)
async def sb_tpl_save_text(message: Message, state: FSMContext):
    data = await state.get_data()
    template_id = data.get("editing_template_id")
    new_text = message.text.strip()

    if not new_text or len(new_text) > 4000:
        await message.answer("❌ Текст должен быть от 1 до 4000 символов")
        return

    user_id = message.from_user.id
    cfg = get_spamblock_config(user_id)
    cfg.update_custom_template(template_id, text=new_text)

    await state.clear()
    await message.answer(
        "✅ Текст апелляции обновлён!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 Просмотр", callback_data=f"sb:tpl_view:{template_id}")],
        ])
    )


# ──────────────────────────────────────────────────────────────────────────────
# УДАЛЕНИЕ ШАБЛОНА
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sb:tpl_delete_ask:"))
async def sb_tpl_delete_ask(callback: CallbackQuery):
    # sb:tpl_delete_ask:TEMPLATE_ID  — ID может содержать подчёркивания, берём всё после 3-го ":"
    template_id = callback.data[len("sb:tpl_delete_ask:"):]
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    tpl = cfg.get_template(template_id)

    if not tpl:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        return

    await callback.message.edit_text(
        f"🗑 <b>Удалить шаблон «{tpl['name']}»?</b>\n\n"
        "Это действие нельзя отменить.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"sb:tpl_delete_ok:{template_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"sb:tpl_view:{template_id}"),
            ]
        ])
    )
    await callback.answer()


# ──────────────────────────────────────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ ПРОХОЖДЕНИЯ КАПЧИ
# ──────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("sb:captcha_done:"))
async def sb_captcha_done(callback: CallbackQuery):
    """
    Юзер нажал «Я прошёл капчу» — уведомляем сервис спамблока.
    Формат callback_data: sb:captcha_done:{session_name}
    """
    session_name = callback.data[len("sb:captcha_done:"):]

    from services.spamblock_service import spamblock_service
    confirmed = spamblock_service.confirm_captcha(session_name)

    if confirmed:
        await callback.answer("✅ Подтверждено! Продолжаю работу со SpamBot...", show_alert=False)
        try:
            await callback.message.edit_text(
                f"✅ <b>Капча подтверждена для аккаунта <code>{session_name}</code></b>\n\n"
                f"Бот продолжает диалог с @SpamBot и подаёт апелляцию.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await callback.answer(
            "⚠️ Ожидание уже завершилось (таймаут) или капча не нужна.",
            show_alert=True
        )


@router.callback_query(F.data.startswith("sb:tpl_delete_ok:"))
async def sb_tpl_delete_ok(callback: CallbackQuery):
    template_id = callback.data[len("sb:tpl_delete_ok:"):]
    user_id = callback.from_user.id
    cfg = get_spamblock_config(user_id)
    deleted = cfg.delete_custom_template(template_id)

    if deleted:
        await callback.answer("✅ Шаблон удалён")
    else:
        await callback.answer("❌ Не удалось удалить шаблон", show_alert=True)

    # Переходим к списку шаблонов
    all_tpls = cfg.get_all_templates()
    text = (
        f"📋 <b>ШАБЛОНЫ АПЕЛЛЯЦИЙ</b>\n\n"
        f"Всего: <b>{len(all_tpls)}</b> шаблонов\n"
        f"Активный: <b>{cfg.get_active_template()['name'] if cfg.get_active_template() else '—'}</b>\n\n"
        "Нажмите на шаблон для просмотра и выбора.\n"
        "🔒 — встроенный  |  ✏️ — пользовательский"
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb_templates_menu(user_id), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb_templates_menu(user_id), parse_mode="HTML")