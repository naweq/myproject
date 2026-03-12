# ==========================================
# ФАЙЛ: bot/handlers/text_temp.py
# ОПИСАНИЕ: Система текстовых шаблонов
# ==========================================

import json
from typing import Dict, List, Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

JSON_FILE = '../text_temp.json'
router = Router()


# ============= СОСТОЯНИЯ =============

class TempStates(StatesGroup):
    wait_temp_name   = State()   # ввод названия при создании
    wait_text_temp   = State()   # ввод текста при создании
    edit_name        = State()   # ввод нового названия
    edit_text        = State()   # ввод нового текста


# ============= ХРАНИЛИЩЕ =============

class TEMP:
    def __init__(self, file_path: str = JSON_FILE):
        self.file_path = file_path

    async def load_data(self) -> Dict[str, Dict[str, str]]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {str(k): v for k, v in data.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    async def save_data(self, data: Dict[str, Dict[str, str]]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    async def get_temp_names(self, user_id: int | str) -> List[str]:
        data = await self.load_data()
        return list(data.get(str(user_id), {}).keys())

    async def get_temp(self, user_id: int | str, name: str) -> Optional[str]:
        data = await self.load_data()
        return data.get(str(user_id), {}).get(name)

    async def del_temp(self, user_id: int | str, name: str) -> bool:
        data = await self.load_data()
        uid = str(user_id)
        if uid in data and name in data[uid]:
            del data[uid][name]
            await self.save_data(data)
            return True
        return False

    async def rename_temp(self, user_id: int | str, old_name: str, new_name: str) -> bool:
        data = await self.load_data()
        uid = str(user_id)
        if uid not in data or old_name not in data[uid]:
            return False
        if new_name in data[uid]:
            return False  # имя уже занято
        data[uid][new_name] = data[uid].pop(old_name)
        await self.save_data(data)
        return True

    async def write_temp(self, user_id: int | str, name: str, text: str) -> None:
        data = await self.load_data()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {}
        data[uid][name] = text
        await self.save_data(data)


loader = TEMP()


# ============= КЛАВИАТУРЫ =============

class KEYB:

    async def get_temp_keyboards(self, user_id: int | str) -> InlineKeyboardMarkup:
        """
        Клавиатура шаблонов для подстановки под запросом текста.
        Каждый шаблон — кнопка с callback check_temp:<имя>.
        """
        keyb = InlineKeyboardBuilder()
        temps = await loader.get_temp_names(user_id)

        for temp in temps:
            keyb.row(InlineKeyboardButton(
                text=f"📄 {temp}",
                callback_data=f"check_temp:{temp}"
            ))
        keyb.row(InlineKeyboardButton(
            text="➕ Добавить шаблон",
            callback_data="add_temp"
        ))
        return keyb.as_markup()

    async def temps_list_keyboard(self, user_id: int | str) -> InlineKeyboardMarkup:
        """
        Клавиатура управления шаблонами (/temps меню).
        Каждый шаблон открывает детальное меню.
        """
        keyb = InlineKeyboardBuilder()
        temps = await loader.get_temp_names(user_id)

        for temp in temps:
            keyb.row(InlineKeyboardButton(
                text=f"📄 {temp}",
                callback_data=f"temp_detail:{temp}"
            ))

        keyb.row(InlineKeyboardButton(
            text="➕ Добавить шаблон",
            callback_data="add_temp"
        ))
        return keyb.as_markup()

    def temp_detail_keyboard(self, name: str) -> InlineKeyboardMarkup:
        """Клавиатура для просмотра/редактирования одного шаблона."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить текст",
                    callback_data=f"temp_edit_text:{name}"
                ),
                InlineKeyboardButton(
                    text="🔤 Переименовать",
                    callback_data=f"temp_rename:{name}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"temp_delete_confirm:{name}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад к списку",
                    callback_data="temps_menu"
                ),
            ],
        ])

    def temp_delete_confirm_keyboard(self, name: str) -> InlineKeyboardMarkup:
        """Подтверждение удаления."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"temp_delete_yes:{name}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"temp_detail:{name}"
                ),
            ],
        ])


keyb = KEYB()


# ============= ВСПОМОГАТЕЛЬНЫЕ =============

async def _send_temps_menu(target: Message | CallbackQuery, user_id: int | str):
    """Универсальный показ меню шаблонов."""
    temps = await loader.get_temp_names(user_id)
    count = len(temps)
    text = (
        "📝 <b>Ваши шаблоны</b>\n\n"
        f"Всего: <b>{count}</b>\n\n"
        "<i>Выберите шаблон для просмотра или добавьте новый</i>"
        if count else
        "📝 <b>Ваши шаблоны</b>\n\n"
        "У вас пока нет шаблонов.\n"
        "<i>Нажмите «➕ Добавить шаблон» чтобы создать первый</i>"
    )
    markup = await keyb.temps_list_keyboard(user_id)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await target.message.answer(text, reply_markup=markup, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


# ============= ХЕНДЛЕРЫ: КОМАНДА /temps и колбек temps_menu =============

@router.message(Command("temps"))
async def cmd_temps(message: Message):
    await _send_temps_menu(message, message.from_user.id)


@router.callback_query(F.data == "temps_menu")
async def cb_temps_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _send_temps_menu(callback, callback.from_user.id)


# ============= СОЗДАНИЕ ШАБЛОНА =============

@router.callback_query(F.data == "add_temp")
async def add_temp(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            "✍️ <b>Новый шаблон</b>\n\nВведите <b>название</b> шаблона(количество символов не должно превышать 12 штук):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="temps_menu")
            ]])
        )
    except Exception:
        await callback.message.answer(
            "✍️ <b>Новый шаблон</b>\n\nВведите <b>название</b> шаблона(количество символов не должно превышать 12 штук):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="temps_menu")
            ]])
        )
    await state.set_state(TempStates.wait_temp_name)
    await callback.answer()


@router.message(TempStates.wait_temp_name)
async def set_temp_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым!")
        return
    if len(name) > 64:
        await message.answer("❌ Название слишком длинное (макс. 64 символа)")
        return
    # Проверяем уникальность
    existing = await loader.get_temp_names(message.from_user.id)
    if name in existing:
        await message.answer(f"❌ Шаблон с именем <b>{name}</b> уже существует!", parse_mode="HTML")
        return

    await state.update_data(temp_name=name)
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "📋 Теперь отправьте <b>текст шаблона</b>:\n\n"
        "<i>Поддерживается HTML-разметка Telegram</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="temps_menu")
        ]])
    )
    await state.set_state(TempStates.wait_text_temp)


@router.message(TempStates.wait_text_temp)
async def set_temp_text(message: Message, state: FSMContext):
    text = message.text or message.caption
    if not text:
        await message.answer("❌ Текст не может быть пустым!")
        return

    data = await state.get_data()
    name = data.get('temp_name')
    user_id = message.from_user.id

    try:
        await loader.write_temp(user_id, name, text)
        await state.clear()
        await message.answer(
            f"✅ <b>Шаблон «{name}» сохранён!</b>",
            parse_mode="HTML"
        )
        await _send_temps_menu(message, user_id)
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")


# ============= ДЕТАЛИ ШАБЛОНА =============

@router.callback_query(F.data.startswith("temp_detail:"))
async def temp_detail(callback: CallbackQuery):
    name = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    text = await loader.get_temp(user_id, name)
    if text is None:
        await callback.answer("❌ Шаблон не найден", show_alert=True)
        await _send_temps_menu(callback, user_id)
        return

    preview = text[:300] + ("..." if len(text) > 300 else "")
    detail_text = (
        f"📄 <b>Шаблон: {name}</b>\n\n"
        f"<blockquote expandable>{preview}</blockquote>\n\n"
        "Выберите действие:"
    )
    try:
        await callback.message.edit_text(
            detail_text,
            reply_markup=keyb.temp_detail_keyboard(name),
            parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            detail_text,
            reply_markup=keyb.temp_detail_keyboard(name),
            parse_mode="HTML"
        )
    await callback.answer()


# ============= РЕДАКТИРОВАНИЕ ТЕКСТА ШАБЛОНА =============

@router.callback_query(F.data.startswith("temp_edit_text:"))
async def temp_edit_text_start(callback: CallbackQuery, state: FSMContext):
    name = callback.data.split(":", 1)[1]
    await state.update_data(editing_temp_name=name)

    await callback.message.edit_text(
        f"✏️ <b>Редактирование текста шаблона «{name}»</b>\n\n"
        "Отправьте новый текст:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"temp_detail:{name}")
        ]])
    )
    await state.set_state(TempStates.edit_text)
    await callback.answer()


@router.message(TempStates.edit_text)
async def temp_edit_text_receive(message: Message, state: FSMContext):
    new_text = message.text or message.caption
    if not new_text:
        await message.answer("❌ Текст не может быть пустым!")
        return

    data = await state.get_data()
    name = data.get('editing_temp_name')
    user_id = message.from_user.id

    await loader.write_temp(user_id, name, new_text)
    await state.clear()
    await message.answer(
        f"✅ <b>Текст шаблона «{name}» обновлён!</b>",
        parse_mode="HTML"
    )
    # Показываем обновлённый шаблон
    preview = new_text[:300] + ("..." if len(new_text) > 300 else "")
    await message.answer(
        f"📄 <b>Шаблон: {name}</b>\n\n"
        f"<blockquote expandable>{preview}</blockquote>\n\n"
        "Выберите действие:",
        reply_markup=keyb.temp_detail_keyboard(name),
        parse_mode="HTML"
    )


# ============= ПЕРЕИМЕНОВАНИЕ ШАБЛОНА =============

@router.callback_query(F.data.startswith("temp_rename:"))
async def temp_rename_start(callback: CallbackQuery, state: FSMContext):
    name = callback.data.split(":", 1)[1]
    await state.update_data(renaming_temp_name=name)

    await callback.message.edit_text(
        f"🔤 <b>Переименование шаблона «{name}»</b>\n\n"
        "Введите новое название:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"temp_detail:{name}")
        ]])
    )
    await state.set_state(TempStates.edit_name)
    await callback.answer()


@router.message(TempStates.edit_name)
async def temp_rename_receive(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if not new_name:
        await message.answer("❌ Название не может быть пустым!")
        return
    if len(new_name) > 64:
        await message.answer("❌ Название слишком длинное (макс. 64 символа)")
        return

    data = await state.get_data()
    old_name = data.get('renaming_temp_name')
    user_id = message.from_user.id

    success = await loader.rename_temp(user_id, old_name, new_name)
    await state.clear()

    if success:
        await message.answer(
            f"✅ Шаблон переименован: <b>{old_name}</b> → <b>{new_name}</b>",
            parse_mode="HTML"
        )
        await message.answer(
            f"📄 <b>Шаблон: {new_name}</b>\n\nВыберите действие:",
            reply_markup=keyb.temp_detail_keyboard(new_name),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"❌ Не удалось переименовать. Возможно, шаблон <b>{new_name}</b> уже существует.",
            parse_mode="HTML"
        )
        await _send_temps_menu(message, user_id)


# ============= УДАЛЕНИЕ ШАБЛОНА =============

@router.callback_query(F.data.startswith("temp_delete_confirm:"))
async def temp_delete_confirm(callback: CallbackQuery):
    name = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        f"🗑 <b>Удалить шаблон «{name}»?</b>\n\n"
        "<i>Это действие необратимо</i>",
        reply_markup=keyb.temp_delete_confirm_keyboard(name),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("temp_delete_yes:"))
async def temp_delete_yes(callback: CallbackQuery):
    name = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    deleted = await loader.del_temp(user_id, name)
    if deleted:
        await callback.answer(f"✅ Шаблон «{name}» удалён", show_alert=False)
    else:
        await callback.answer("❌ Шаблон не найден", show_alert=True)

    await _send_temps_menu(callback, user_id)