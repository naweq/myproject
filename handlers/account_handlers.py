# ==========================================
# ФАЙЛ: bot/handlers/account_handlers.py
# ОПИСАНИЕ: Обработчики действий с аккаунтами (Hydrogram)
# ==========================================
import os
import asyncio
import zipfile
import io
import tempfile
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.enums import ContentType
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers import user_handlers
from keyboards import user_keyboards
from config import bot, MAX_ZIP_SIZE_MB
from modules.selections_store import get_selected_accounts
from modules.tdata_converter import convert_to_tdata
from modules.session_manager import SessionManager
from keyboards.user_keyboards import UserKeyboards

logger = logging.getLogger(__name__)
router = Router()

session_service = SessionManager()



# ============= СОСТОЯНИЯ =============

class DeleteAccountsState(StatesGroup):
    selecting = State()


class Profile(StatesGroup):
    avatar = State()
    about = State()
    name = State()
    username = State()


class Profilee(StatesGroup):
    avatar_album = State()
    avatar_zip = State()
    fullname = State()
    about = State()
    username = State()


# ============= ВСПОМОГАТЕЛЬНЫЕ =============

def get_sessions(user_id):
    sessions_dir = f'users/{user_id}'
    if not os.path.exists(sessions_dir):
        return []
    return [f for f in os.listdir(sessions_dir) if f.endswith('.session')]


def _is_auth_error(err_msg: str) -> bool:
    err_lower = err_msg.lower()
    return any(k in err_lower for k in [
        "auth_key_unregistered", "session_revoked", "need re-login",
        "authkeyunregistered", "not authorized"
    ])


# ============= КОД ВХОДА =============

@router.callback_query(F.data.startswith("get_code:"))
async def get_login_code(callback: CallbackQuery):
    """Получить код для входа из чата 777000"""
    user_id = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    session_name = ref

    await callback.answer("🔍 Ищу последний код...", show_alert=False)
    progress_msg = await callback.message.answer(
        "⏳ <b>Получаю код входа...</b>\n\n<i>Подключаюсь к Telegram...</i>",
        parse_mode="HTML"
    )

    try:
        code = await session_service.get_login_code(session_name, user_id)
        if code:
            await progress_msg.edit_text(
                f"🔑 <b>Код для входа получен!</b>\n\n"
                f"📱 <b>Аккаунт:</b> {session_name.replace('.session', '')}\n"
                f"🔢 <b>Код:</b> <code>{code}</code>\n\n"
                f"<i>Скопируйте код и используйте для входа</i>",
                parse_mode="HTML"
            )
        else:
            await progress_msg.edit_text(
                "❌ <b>Код не найден</b>\n\n"
                "Возможные причины:\n"
                "• Telegram ещё не прислал код\n"
                "• Код был отправлен в виде звонка\n"
                "• Проверьте телефон вручную",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка получения кода: {e}")
        await progress_msg.edit_text(
            f"❌ <b>Ошибка получения кода</b>\n\nДетали: {str(e)}",
            parse_mode="HTML"
        )


# ============= ВАЛИДНОСТЬ =============

@router.callback_query(F.data.startswith("check_valid:"))
async def check_validity(callback: CallbackQuery):
    """Проверить валидность аккаунта"""
    user_id = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    session_name = ref

    msg = await callback.message.answer(
        "🔍 <b>Проверяю валидность аккаунта...</b>",
        parse_mode="HTML"
    )

    status = await session_service.check_session_valid(session_name, user_id)

    await msg.delete()
    if status == "🟢":
        await callback.answer("✅ Аккаунт валиден!", show_alert=True)
    else:
        await callback.answer("❌ Аккаунт невалиден!", show_alert=True)

    await user_handlers.show_session_detail(callback, session_name=session_name)


# ============= УДАЛЕНИЕ ОДНОГО АККАУНТА =============

@router.callback_query(F.data.startswith("delete:"))
async def confirm_delete_session(callback: CallbackQuery):
    """Подтверждение удаления"""
    user_id = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    session_name = ref

    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение удаления</b>\n\n"
        f"Вы действительно хотите удалить аккаунт:\n"
        f"<b>{session_name.replace('.session', '')}</b>?\n\n"
        f"<i>Это действие нельзя отменить!</i>",
        reply_markup=UserKeyboards.confirm_delete(session_name),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete:"))
async def delete_session(callback: CallbackQuery):
    """Удалить сессию"""
    user_id = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    session_name = ref

    success = session_service.delete_session(session_name, user_id)

    if success:
        await callback.answer("✅ Аккаунт удален!", show_alert=True)
        sessions = session_service.get_sessions(user_id)
        states = session_service.get_account_states(user_id)
        await callback.message.edit_text(
            f"✅ <b>Аккаунт успешно удален!</b>\n\nОсталось аккаунтов: {len(sessions)}",
            reply_markup=UserKeyboards.accounts_list(sessions, states, 0, user_id=user_id),
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Ошибка удаления!", show_alert=True)


# ============= КОНВЕРТАЦИЯ В TDATA =============

@router.callback_query(F.data.startswith("convert_tdata:"))
async def convert_session_to_tdata(callback: CallbackQuery):
    """Конвертировать сессию в TData"""
    user_id = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    session_name = ref
    clean_name = session_name.replace('.session', '')

    await callback.answer("🔄 Запускаю конвертацию в TData...", show_alert=False)
    progress_msg = await callback.message.answer(
        "⏳ <b>Конвертирую аккаунт в TData</b>\n\n"
        "1️⃣ Подключение к аккаунту...\n"
        "2️⃣ Конвертация формата сессии...\n"
        "3️⃣ Генерация TData файлов...\n"
        "4️⃣ Создание архива...\n\n"
        "<i>⏱ Обычно занимает 20–60 секунд</i>",
        parse_mode="HTML"
    )

    try:
        zip_path = await convert_to_tdata(session_name, user_id)

        try:
            await progress_msg.delete()
        except:
            pass

        file = FSInputFile(zip_path)
        await callback.message.answer_document(
            document=file,
            caption=(
                f"✅ <b>TData успешно создан!</b>\n\n"
                f"📱 <b>Аккаунт:</b> <code>{clean_name}</code>\n\n"
                f"<b>📖 Инструкция:</b>\n"
                f"1️⃣ Распакуйте архив\n"
                f"2️⃣ Закройте Telegram Desktop\n"
                f"3️⃣ Скопируйте папку <code>tdata</code> в:\n"
                f"   • Windows: <code>%APPDATA%\\Telegram Desktop</code>\n"
                f"   • macOS: <code>~/Library/Application Support/Telegram Desktop</code>\n"
                f"4️⃣ Запустите Telegram Desktop"
            ),
            parse_mode="HTML"
        )
        try:
            os.remove(zip_path)
        except OSError:
            pass

    except FileNotFoundError as e:
        await callback.message.answer(
            f"❌ <b>Файл сессии не найден</b>\n\nСессия: <code>{session_name}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        error_msg = str(e)
        if "not authorized" in error_msg.lower():
            text = "❌ <b>Сессия не авторизована</b>\n\nАккаунт был разлогинен или заблокирован."
        elif "flood" in error_msg.lower():
            text = "⏱ <b>Слишком много запросов</b>\n\nПопробуйте через 10-15 минут."
        else:
            text = f"❌ <b>Не удалось создать TData</b>\n\nОшибка: <code>{error_msg}</code>"
        await callback.message.answer(text, parse_mode="HTML")
    finally:
        try:
            await progress_msg.delete()
        except:
            pass


# ============= ВЫГРУЗКА СЕССИИ =============

@router.callback_query(F.data.startswith("upload:"))
async def upload(callback: CallbackQuery):
    user_id = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    # FIX: передаём ref напрямую в upload() — он уже безопасный (индекс или короткое имя)
    await callback.message.answer('<b>Выберите тип выгрузки:</b>', reply_markup=UserKeyboards.upload(ref))


@router.callback_query(F.data.startswith("upload_session:"))
async def upload_session(callback: CallbackQuery):
    user = callback.from_user.id
    ref = callback.data.rsplit(":", 1)[-1]
    session_name = ref
    await callback.message.edit_text('<i>Выгружаю сессию...</i>')
    await asyncio.sleep(1)
    session = FSInputFile(f'users/{user}/{session_name}')
    await callback.message.delete()
    await bot.send_document(user, session, caption=f'<b>Сессия</b> {session_name}', parse_mode="HTML")


# ============= РЕДАКТИРОВАНИЕ ПРОФИЛЯ (одиночный аккаунт) =============

@router.callback_query(F.data.startswith("edit_acc:"))
async def process_edit_acc(callback: CallbackQuery):
    # FIX: was split('_')[1] which broke on underscore in "edit_acc:SESSION"
    ref = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    session_name = ref
    await callback.message.edit_text(
        "<b>Изменение профиля</b>\n\nВыберите, что именно хотите изменить:",
        reply_markup=UserKeyboards.edit_profile(session_name)
    )


@router.callback_query(F.data.startswith("profile_"))
async def process_profile(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    # FIX: parse "profile_avatar:REF" correctly
    action_part, ref = data.split(":", 1)
    _, field = action_part.split("_", 1)
    user_id = callback.from_user.id
    clean_session_name = ref

    if field == 'avatar':
        await callback.message.answer('<b>Отправьте новую фотографию профиля:</b>')
        await state.set_state(Profile.avatar)
        await state.update_data(session_name=clean_session_name)
    elif field == 'username':
        await callback.message.answer('<b>Введите новый @username (без @):</b>')
        await state.set_state(Profile.username)
        await state.update_data(session_name=clean_session_name)
    elif field == 'about':
        await callback.message.answer('<b>Введите новое описание профиля:</b>')
        await state.set_state(Profile.about)
        await state.update_data(session_name=clean_session_name)
    elif field == 'name':
        await callback.message.answer('<b>Введите новое имя аккаунта:</b>')
        await state.set_state(Profile.name)
        await state.update_data(session_name=clean_session_name)


@router.message(Profile.avatar)
async def avatar(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Отправьте фотографию.")
        return

    msg = await message.reply('<b>Обрабатываю фото...</b>')
    data = await state.get_data()
    user = message.from_user.id

    photo = message.photo[-1]
    file_name = f"{photo.file_id}.jpg"
    photo_path = Path("../temp") / file_name
    photo_path.parent.mkdir(exist_ok=True)
    await bot.download(photo, destination=photo_path)

    app = await session_service.get_hydrogram_client(data['session_name'], user)
    try:
        await app.connect()
        await app.set_profile_photo(photo=str(photo_path))
        await msg.edit_text('<b>Фото успешно установлено!</b>',
                            reply_markup=UserKeyboards.come_to_acc(data['session_name']))

    # except AttributeError:
    #     await msg.edit_text('<b>Фото успешно установлено!</b>',
    #                         reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    except Exception as e:
        await msg.edit_text(f'Ошибка: {e}', reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    finally:
        await session_service._safe_disconnect(app)
        if photo_path.exists():
            photo_path.unlink()
        await state.clear()



@router.message(Profile.about)
async def about(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user.id
    new_about = message.text.strip()

    app = await session_service.get_hydrogram_client(data['session_name'], user)
    try:
        await app.connect()
        msg = await message.reply('<b>Меняю описание...</b>')
        await app.update_profile(bio=new_about)
        await msg.edit_text('<b>Описание сменено!</b>', reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    except Exception as e:
        await message.answer(f"Ошибка: {e}", reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    finally:
        await app.disconnect()
        await state.clear()


@router.message(Profile.name)
async def name(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user.id
    parts = message.text.strip().split(maxsplit=1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""

    app = await session_service.get_hydrogram_client(data['session_name'], user)
    try:
        await app.connect()
        msg = await message.reply('<b>Меняю имя...</b>')
        await app.update_profile(first_name=first, last_name=last)
        await msg.edit_text(f'<b>Имя сменено на</b> {message.text}',
                            reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    except Exception as e:
        await message.answer(f"Ошибка: {e}", reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    finally:
        await session_service._safe_disconnect(app)
        await state.clear()


@router.message(Profile.username)
async def username_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user.id
    new_username = message.text.strip().lstrip("@")

    app = await session_service.get_hydrogram_client(data['session_name'], user)
    try:
        await app.connect()
        msg = await message.reply('<b>Меняю юзернейм...</b>')
        await app.set_username(new_username)
        await msg.edit_text(f'<b>Юзернейм сменён на</b> @{new_username}',
                            reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    except Exception as e:
        await message.answer(f"Ошибка: {e}", reply_markup=UserKeyboards.come_to_acc(data['session_name']))
    finally:
        await session_service._safe_disconnect(app)
        await state.clear()


# ============= МАССОВОЕ УДАЛЕНИЕ =============

@router.callback_query(F.data == "del_accounts")
async def start_delete_accounts(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    sessions = get_sessions(user_id)
    if not sessions:
        await callback.message.edit_text("Нет доступных аккаунтов для удаления.")
        return

    await state.set_state(DeleteAccountsState.selecting)
    await state.set_data({"sessions": sessions, "selected": [], "page": 0})
    kb = user_keyboards.Keyboards.select_accounts_for_delete(sessions, [], page=0)
    await callback.message.edit_text("Выберите аккаунты для удаления:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("del_toggle:"), DeleteAccountsState.selecting)
async def toggle_account(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sessions = data.get("sessions", [])
    selected = data.get("selected", [])
    page = int(callback.data.split(":")[1])
    global_idx = int(callback.data.split(":")[2])   # теперь числовой индекс

    if global_idx < 0 or global_idx >= len(sessions):
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return

    full_session = sessions[global_idx]

    if full_session in selected:
        selected.remove(full_session)
    else:
        selected.append(full_session)

    await state.update_data(selected=selected)
    kb = user_keyboards.Keyboards.select_accounts_for_delete(sessions, selected, page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "del_select_all", DeleteAccountsState.selecting)
async def select_all(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sessions = data.get("sessions", [])
    page = data.get("page", 0)
    await state.update_data(selected=sessions.copy())
    kb = user_keyboards.Keyboards.select_accounts_for_delete(sessions, sessions, page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "del_deselect_all", DeleteAccountsState.selecting)
async def deselect_all(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sessions = data.get("sessions", [])
    page = data.get("page", 0)
    await state.update_data(selected=[])
    kb = user_keyboards.Keyboards.select_accounts_for_delete(sessions, [], page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("del_page:"), DeleteAccountsState.selecting)
async def change_page(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sessions = data.get("sessions", [])
    selected = data.get("selected", [])
    new_page = int(callback.data.split(":")[1])
    await state.update_data(page=new_page)
    kb = user_keyboards.Keyboards.select_accounts_for_delete(sessions, selected, new_page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "del_confirm", DeleteAccountsState.selecting)
async def confirm_delete_bulk(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected", [])

    if not selected:
        await callback.answer("Ничего не выбрано для удаления.", show_alert=True)
        return

    confirm_kb = InlineKeyboardBuilder()
    confirm_kb.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data="del_execute"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="del_cancel")
    )
    selected_names = [s.replace('.session', '') for s in selected]
    await callback.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить {len(selected)} аккаунтов?\n\n"
        f"{', '.join(selected_names)}",
        reply_markup=confirm_kb.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "del_execute", DeleteAccountsState.selecting)
async def execute_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected", [])
    user_id = callback.from_user.id

    deleted = []
    for session in selected:
        if session_service.delete_session(session, user_id):
            deleted.append(session.replace('.session', ''))

    await state.clear()
    # Получаем свежий список после удаления
    sessions_after = session_service.get_sessions(user_id)
    states_after = session_service.get_account_states(user_id)
    result_kb = UserKeyboards.accounts_list(sessions_after, states_after, 0, user_id=user_id)
    if deleted:
        await callback.message.edit_text(
            f"✅ <b>Удалено аккаунтов: {len(deleted)}</b>\n"
            f"Осталось: {len(sessions_after)}",
            reply_markup=result_kb,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            "⚠️ Ничего не удалено.",
            reply_markup=result_kb,
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "del_cancel", DeleteAccountsState.selecting)
async def cancel_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sessions = data.get("sessions", [])
    selected = data.get("selected", [])
    page = data.get("page", 0)
    kb = user_keyboards.Keyboards.select_accounts_for_delete(sessions, selected, page)
    await callback.message.edit_text("Выберите аккаунты для удаления:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "del_back", DeleteAccountsState.selecting)
async def back_from_delete(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    sessions = session_service.get_sessions(user_id)
    states = session_service.get_account_states(user_id)
    await callback.message.edit_text(
        f"📱 <b>МОИ АККАУНТЫ</b>\n\n📊 Всего: <b>{len(sessions)}</b>\n<i>Нажмите на аккаунт для деталей</i>",
        reply_markup=UserKeyboards.accounts_list(sessions, states, 0, user_id=user_id),
        parse_mode="HTML"
    )
    await callback.answer()


# ============= МАССОВОЕ РЕДАКТИРОВАНИЕ ПРОФИЛЯ =============

@router.callback_query(F.data == "edit_accounts")
async def edit_accounts_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)

    if not selected:
        await callback.answer("Нет выбранных аккаунтов", show_alert=True)
        return

    await state.update_data(selected_sessions=selected)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Аватар", callback_data="editor_avatar")],
        [InlineKeyboardButton(text="👤 Имя / Фамилия", callback_data="editor_fullname")],
        [InlineKeyboardButton(text="📝 О себе (bio)", callback_data="editor_about")],
        [InlineKeyboardButton(text="🔑 Username", callback_data="editor_username")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")],
    ])
    await callback.message.edit_text(
        f"<b>Выбрано аккаунтов: {len(selected)}</b>\n\nВыберите действие:",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editor_"))
async def process_editor(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_sessions", [])

    if not selected:
        await callback.answer("Список аккаунтов потерян. Выберите заново.", show_alert=True)
        await state.clear()
        return

    field = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    count = len(selected)

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]
    ])
    await state.update_data(selected=selected, user_id=user_id)

    if field == "avatar":
        if count > 3:
            await callback.message.answer(
                f"<b>Отправьте ZIP-архив</b> (до {MAX_ZIP_SIZE_MB} МБ) с фото/видео.",
                reply_markup=cancel_kb
            )
            await state.set_state(Profilee.avatar_zip)
        else:
            await callback.message.answer(
                f"<b>Отправьте до {count} фото/видео</b> (можно альбомом).\n"
                "После всех файлов напишите «готово».",
                reply_markup=cancel_kb
            )
            await state.set_state(Profilee.avatar_album)
            await state.update_data(media=[])
    elif field == "fullname":
        await callback.message.answer(
            f"<b>Введите имя и фамилию</b> (по одному на строку, {count} строк):",
            reply_markup=cancel_kb
        )
        await state.set_state(Profilee.fullname)
    elif field == "about":
        await callback.message.answer(
            "<b>Введите новое описание (bio)</b> — установится на все аккаунты:",
            reply_markup=cancel_kb
        )
        await state.set_state(Profilee.about)
    elif field == "username":
        await callback.message.answer(
            f"<b>Введите новые usernames</b> (по одному на строку, {count} строк):",
            reply_markup=cancel_kb
        )
        await state.set_state(Profilee.username)

    await callback.answer()


@router.callback_query(F.data == "cancel_edit")
async def cancel_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()


# ── Аватар (альбом) ──

@router.message(Profilee.avatar_album, F.content_type.in_({ContentType.PHOTO, ContentType.VIDEO}))
async def collect_avatar_media(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])
    if message.photo:
        media.append(("photo", message.photo[-1].file_id))
    elif message.video:
        media.append(("video", message.video.file_id))
    await state.update_data(media=media)
    await message.answer(f"Добавлено {len(media)} медиа. Ещё или «готово»?")


@router.message(Profilee.avatar_album, F.text.lower() == "готово")
async def apply_avatar_album(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected", [])
    media_ids = data.get("media", [])
    user_id = data.get("user_id")

    if not media_ids:
        await message.answer("Нет добавленных медиа.")
        return

    results = []
    for i, session in enumerate(selected, 1):
        progress_msg = await message.answer(f"⏳ Обрабатываю {i}/{len(selected)} → {session} ...")
        m_type, file_id = media_ids[(i - 1) % len(media_ids)]

        file_ext = "mp4" if m_type == "video" else "jpg"
        photo_path = Path("../temp") / f"{file_id}.{file_ext}"
        photo_path.parent.mkdir(exist_ok=True)

        app = await session_service.get_hydrogram_client(session, user_id)
        try:
            tg_file = await bot.get_file(file_id)
            await bot.download_file(tg_file.file_path, destination=photo_path)

            await app.connect()
            if m_type == "video":
                await app.set_profile_photo(video=str(photo_path))
            else:
                await app.set_profile_photo(photo=str(photo_path))
            results.append(f"✅ {session} — аватар обновлён")
        except Exception as e:
            err_msg = str(e)
            if _is_auth_error(err_msg):
                results.append(f"⚠️ {session} — требуется повторная авторизация")
            else:
                results.append(f"✗ {session} — {err_msg}")
        finally:
            await app.disconnect()

            if photo_path.exists():
                photo_path.unlink()
            try:
                await progress_msg.delete()
            except:
                pass

    await message.answer("\n".join(results))
    await state.clear()


# ── Аватар (ZIP) ──

@router.message(Profilee.avatar_zip, F.document)
async def apply_avatar_zip(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected", [])
    user_id = data.get("user_id")

    doc = message.document
    if doc.file_size > MAX_ZIP_SIZE_MB * 1024 * 1024:
        await message.answer(f"❌ Файл слишком большой. Максимум {MAX_ZIP_SIZE_MB} МБ.")
        return

    file_info = await bot.get_file(doc.file_id)
    zip_content = await bot.download_file(file_info.file_path)
    supported = (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov")

    results = []
    with zipfile.ZipFile(io.BytesIO(zip_content)) as z:
        with tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            files = sorted([
                os.path.join(tmp, f) for f in os.listdir(tmp)
                if os.path.isfile(os.path.join(tmp, f)) and f.lower().endswith(supported)
            ])

            if not files:
                await message.answer("В архиве нет поддерживаемых файлов.")
                return

            for i, session in enumerate(selected, 1):
                progress_msg = await message.answer(f"⏳ Обрабатываю {i}/{len(selected)} → {session} ...")
                path = files[(i - 1) % len(files)]
                is_video = path.lower().endswith((".mp4", ".mov", ".gif"))

                app = await session_service.get_hydrogram_client(session, user_id)
                try:
                    await app.connect()
                    if is_video:
                        await app.set_profile_photo(video=path)
                    else:
                        await app.set_profile_photo(photo=path)
                    results.append(f"✅ {session}")
                except Exception as e:
                    err_msg = str(e)
                    if _is_auth_error(err_msg):
                        results.append(f"⚠️ {session} — требуется повторная авторизация")
                    else:
                        results.append(f"✗ {session} — {err_msg}")
                finally:
                    await session_service._safe_disconnect(app)
                    try:
                        await progress_msg.delete()
                    except:
                        pass

    await message.answer("\n".join(results))
    await state.clear()


# ── Имя + Фамилия ──

@router.message(Profilee.fullname)
async def set_fullname(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data["selected"]
    user_id = data["user_id"]
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]

    if len(lines) != len(selected):
        await message.answer(f"❌ Нужно ровно {len(selected)} строк. Получено: {len(lines)}")
        return

    results = []
    for i, session in enumerate(selected, 1):
        progress_msg = await message.answer(f"⏳ Обрабатываю {i}/{len(selected)} → {session} ...")
        parts = lines[i - 1].split(maxsplit=1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""

        app = await session_service.get_hydrogram_client(session, user_id)
        try:
            await app.connect()
            await app.update_profile(first_name=first, last_name=last)
            results.append(f"✅ {session} → {first} {last}")
        except Exception as e:
            err_msg = str(e)
            if _is_auth_error(err_msg):
                results.append(f"⚠️ {session} — требуется повторная авторизация")
            else:
                results.append(f"✗ {session} — {err_msg}")
        finally:
            await session_service._safe_disconnect(app)
            try:
                await progress_msg.delete()
            except:
                pass

    await message.answer("\n".join(results))
    await state.clear()


# ── Bio ──

@router.message(Profilee.about)
async def set_about(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data["selected"]
    user_id = data["user_id"]
    text = message.text.strip()

    results = []
    for i, session in enumerate(selected, 1):
        progress_msg = await message.answer(f"⏳ Обрабатываю {i}/{len(selected)} → {session} ...")
        app = await session_service.get_hydrogram_client(session, user_id)
        try:
            await app.connect()
            await app.update_profile(bio=text)
            results.append(f"✅ {session}")
        except Exception as e:
            err_msg = str(e)
            if _is_auth_error(err_msg):
                results.append(f"⚠️ {session} — требуется повторная авторизация")
            else:
                results.append(f"✗ {session} — {err_msg}")
        finally:
            await session_service._safe_disconnect(app)
            try:
                await progress_msg.delete()
            except:
                pass

    await message.answer("\n".join(results))
    await state.clear()


# ── Username ──

@router.message(Profilee.username)
async def set_username(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data["selected"]
    user_id = data["user_id"]
    lines = [line.strip().lstrip("@") for line in message.text.splitlines() if line.strip()]

    if len(lines) != len(selected):
        await message.answer(f"❌ Нужно ровно {len(selected)} usernames. Получено: {len(lines)}")
        return

    results = []
    for i, session in enumerate(selected, 1):
        progress_msg = await message.answer(f"⏳ Обрабатываю {i}/{len(selected)} → {session} ...")
        uname = lines[i - 1]
        app = await session_service.get_hydrogram_client(session, user_id)
        try:
            await app.connect()
            await app.set_username(uname)
            results.append(f"✅ {session} → @{uname}")
        except Exception as e:
            err_msg = str(e)
            if _is_auth_error(err_msg):
                results.append(f"⚠️ {session} — требуется повторная авторизация")
            elif "username_occupied" in err_msg.lower():
                results.append(f"⚠️ {session} → @{uname} занят")
            elif "flood" in err_msg.lower():
                results.append(f"⏳ {session} — FloodWait")
            else:
                results.append(f"✗ {session} — {err_msg}")
        finally:
            await session_service._safe_disconnect(app)
            try:
                await progress_msg.delete()
            except:
                pass

    await message.answer("\n".join(results))
    await state.clear()