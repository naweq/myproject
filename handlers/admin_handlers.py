# ==========================================
# ФАЙЛ: bot/handlers/admin_handlers.py
# ОПИСАНИЕ: Обработчики админ-панели
# ==========================================

import asyncio
import logging
import random
import string
from datetime import datetime
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import bot, ADMIN_IDS, SUBSCRIPTION_PRICES
from modules.database import Database
from keyboards.admin_keyboards import AdminKeyboards
from modules.validators import FileValidator
from config import ADMIN_NOTIFY_ID
logger = logging.getLogger(__name__)
router = Router()

db = Database()
from modules.payment import add_promo

# ============= СОСТОЯНИЯ =============

class AdminStates(StatesGroup):
    """Состояния админа"""
    waiting_user_id_sub = State()
    waiting_user_id_refund = State()
    waiting_user_id_block = State()
    waiting_user_id_unblock = State()
    waiting_user_id_find = State()
    waiting_broadcast = State()
    waiting_message_to_user = State()

class Promo(StatesGroup):
    wait_rew_code = State()
    wait_reward = State()
    wait_quant_promo = State()

class GenPromo(StatesGroup):
    wait_count_custom = State()   # если выбрал "Своё"
    wait_reward = State()
    wait_activations = State()

# ============= ПРОВЕРКА АДМИНА =============

def is_admin(user_id: int) -> bool:
    """Проверка админ прав"""
    return user_id in ADMIN_IDS


# ============= АДМИН ПАНЕЛЬ =============
rewards = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='3 дня', callback_data='promo:3_days'), InlineKeyboardButton(text='7 Дней', callback_data='promo:week')],
    [InlineKeyboardButton(text='Месяц', callback_data='promo:month'), InlineKeyboardButton(text='Навсегда', callback_data='promo:forever')],
])

@router.message(Command("admin"))
async def admin_panel(message: Message):
    """Админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("🚫 Доступ запрещён!")
        return

    logger.info(f"👑 Админ {message.from_user.id} открыл панель")

    await message.answer(
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "🎛 Панель управления ботом\n"
        "Выберите действие:",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery):
    """Показать админ-панель"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выберите действие:",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "close_admin")
async def close_admin(callback: CallbackQuery):
    """Закрыть панель"""
    await callback.message.delete()
    await callback.answer("Панель закрыта")

@router.message(Command("logs"))
async def send_logs(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer('🚫Вы не админ!')
        return
    log_path = "logs/bot.log"
    log_file = FSInputFile(log_path, filename="bot_log")

    await message.answer_document(document=log_file, caption='<b>📄Лог файл бота</b>', parse_mode="HTML")




# ============= СТАТИСТИКА =============

@router.callback_query(F.data == "admin_stats")
async def show_stats(callback: CallbackQuery):
    """Показать статистику"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    stats = await db.get_stats()

    text = (
        f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"💎 Активных подписок: <b>{stats['active_subscriptions']}</b>\n"
        f"🎁 Тестовых подписок: <b>{stats['test_subscriptions']}</b>\n\n"
        f"💰 Всего продано подписок: <b>{stats['total_subscriptions_sold']}</b>\n"
        f"⭐️ Всего заработано звёзд: <b>{stats['total_stars_earned']}</b>\n\n"
        f"<i>Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=AdminKeyboards.back_admin(),
        parse_mode="HTML"
    )
    await callback.answer()
class admin(StatesGroup):
    admin_id = State()
@router.callback_query(F.data == 'add_admin')
async def add_admins(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer('<b>Введите id админа:</b>')
    await state.set_state(admin.admin_id)
from config import add_admins

@router.message(admin.admin_id)
async def add_admin_id(message: Message, state: FSMContext):
    msg = await message.answer('Добавляю админа...')
    await state.update_data(admin_id=message.text)
    data = await state.get_data()
    adm_id = data['admin_id']
    if add_admins(adm_id):
        await msg.edit_text(f'<b>Добавил админа {adm_id}</b>')
    else:
        await msg.edit_text('<b>Не удалось добавить админа( Проверьте лог-файл</b>')





# ============= СПИСОК ПОЛЬЗОВАТЕЛЕЙ =============

@router.callback_query(F.data.startswith("admin_users:"))
async def show_users_list(callback: CallbackQuery):
    """Показать список пользователей"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    page = int(callback.data.split(":")[1])

    users, total = await db.get_users_list(page, per_page=10)
    total_pages = (total + 9) // 10

    if not users:
        await callback.message.edit_text(
            "👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\n"
            "📭 Пока нет пользователей",
            reply_markup=AdminKeyboards.back_admin(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    text = f"👥 <b>ПОЛЬЗОВАТЕЛИ</b> (стр. {page + 1}/{total_pages})\n\n"

    for user in users:
        user_id = user['user_id']
        username = user.get('username', 'нет')
        first_name = user.get('first_name', 'Нет имени')

        sub_status = "💎" if db.has_active_subscription(user_id) else "⭐️"
        block_status = "🚫" if user.get('is_blocked') else ""

        text += (
            f"{sub_status}{block_status} <b>{first_name}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ @{username}\n"
            f"└─────────────\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=AdminKeyboards.users_list_pagination(page, total_pages),
        parse_mode="HTML"
    )
    await callback.answer()


# ============= ПОИСК ПОЛЬЗОВАТЕЛЯ =============

@router.callback_query(F.data == "admin_find")
async def find_user_start(callback: CallbackQuery, state: FSMContext):
    """Начать поиск пользователя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "🔍 <b>ПОИСК ПОЛЬЗОВАТЕЛЯ</b>\n\n"
        "Отправьте ID пользователя:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_user_id_find)
    await callback.answer()


@router.message(AdminStates.waiting_user_id_find)
async def find_user_process(message: Message, state: FSMContext):
    """Обработка поиска"""
    is_valid, user_id, error = FileValidator.validate_user_id(message.text)

    if not is_valid:
        await message.answer(error)
        return

    user = await db.get_user(user_id)

    if not user:
        await message.answer(
            f"❌ Пользователь с ID <code>{user_id}</code> не найден",
            parse_mode="HTML"
        )
        return

    has_sub = await db.has_active_subscription(user_id)
    is_blocked = user.get('is_blocked', False)

    text = (
        f"👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\n"
        f"📛 Имя: <b>{user.get('first_name', 'Нет')}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👨‍💻 Username: @{user.get('username', 'нет')}\n"
        f"📅 Регистрация: {user.get('created_at', 'неизвестно')[:10]}\n\n"
        f"💎 Подписка: {'✅ Активна' if has_sub else '❌ Неактивна'}\n"
        f"🚫 Блокировка: {'✅ Да' if is_blocked else '❌ Нет'}\n"
    )

    if has_sub:
        sub_until = datetime.fromisoformat(user['subscription_until'])
        text += f"📆 До: {sub_until.strftime('%d.%m.%Y %H:%M')}\n"

    await message.answer(
        text,
        reply_markup=AdminKeyboards.user_actions(user_id),
        parse_mode="HTML"
    )

    await state.clear()


# ============= ВЫДАЧА ПОДПИСКИ =============

@router.callback_query(F.data == "admin_give_sub")
async def give_sub_start(callback: CallbackQuery, state: FSMContext):
    """Начать выдачу подписки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "💎 <b>ВЫДАЧА ПОДПИСКИ</b>\n\n"
        "Отправьте ID пользователя:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_user_id_sub)
    await callback.answer()


@router.message(AdminStates.waiting_user_id_sub)
async def give_sub_receive_id(message: Message, state: FSMContext):
    """Получить ID для выдачи подписки"""
    is_valid, user_id, error = FileValidator.validate_user_id(message.text)

    if not is_valid:
        await message.answer(error)
        return

    user = await db.get_user(user_id)
    if not user:
        await message.answer(f"❌ Пользователь {user_id} не найден")
        return

    await state.update_data(target_user_id=user_id)

    await message.answer(
        f"💎 Выдача подписки для <code>{user_id}</code>\n\n"
        "Выберите тип подписки:",
        reply_markup=AdminKeyboards.subscription_types(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin_sub_type:"))
async def give_sub_select_type(callback: CallbackQuery, state: FSMContext):
    """Выбрать тип подписки"""
    sub_type = callback.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get('target_user_id')

    if not user_id:
        await callback.answer("Ошибка", show_alert=True)
        return

    await db.activate_subscription(user_id, sub_type, 0)

    await callback.message.edit_text(
        f"✅ <b>Подписка выдана!</b>\n\n"
        f"Пользователь <code>{user_id}</code> получил подписку типа <b>{sub_type}</b>",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            "🎉 <b>Вам выдана подписка!</b>\n\n"
            "💎 Администратор активировал Premium\n"
            "Все функции разблокированы! ✨",
            parse_mode="HTML"
        )
    except:
        pass

    await state.clear()
    await callback.answer()


# ============= ВОЗВРАТ ПОДПИСКИ =============

@router.callback_query(F.data == "admin_refund")
async def refund_sub_start(callback: CallbackQuery, state: FSMContext):
    """Начать возврат подписки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "↩️ <b>ВОЗВРАТ ПОДПИСКИ</b>\n\n"
        "Отправьте ID пользователя для обнуления подписки:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_user_id_refund)
    await callback.answer()


@router.message(AdminStates.waiting_user_id_refund)
async def refund_sub_process(message: Message, state: FSMContext):
    """Обработка возврата"""
    is_valid, user_id, error = FileValidator.validate_user_id(message.text)

    if not is_valid:
        await message.answer(error)
        return

    user = await db.get_user(user_id)
    if not user:
        await message.answer(f"❌ Пользователь {user_id} не найден")
        return

    await db.remove_subscription(user_id)

    await message.answer(
        f"✅ <b>Подписка обнулена!</b>\n\n"
        f"У пользователя <code>{user_id}</code> удалена подписка",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )

    # Уведомляем
    try:
        await bot.send_message(
            user_id,
            "⚠️ <b>Ваша подписка обнулена</b>\n\n"
            "Администратор отменил вашу подписку\n"
            "Обратитесь в поддержку для уточнения",
            parse_mode="HTML"
        )
    except:
        pass

    await state.clear()


# ============= БЛОКИРОВКА =============

@router.callback_query(F.data == "admin_block")
async def block_user_start(callback: CallbackQuery, state: FSMContext):
    """Начать блокировку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "🚫 <b>БЛОКИРОВКА</b>\n\n"
        "Отправьте ID пользователя для блокировки:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_user_id_block)
    await callback.answer()


@router.message(AdminStates.waiting_user_id_block)
async def block_user_process(message: Message, state: FSMContext):
    """Обработка блокировки"""
    is_valid, user_id, error = FileValidator.validate_user_id(message.text)

    if not is_valid:
        await message.answer(error)
        return

    await db.set_blocked(user_id, True)

    await message.answer(
        f"✅ <b>Пользователь заблокирован!</b>\n\n"
        f"ID: <code>{user_id}</code>",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )

    await state.clear()


@router.callback_query(F.data == "admin_unblock")
async def unblock_user_start(callback: CallbackQuery, state: FSMContext):
    """Начать разблокировку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "✅ <b>РАЗБЛОКИРОВКА</b>\n\n"
        "Отправьте ID пользователя:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_user_id_unblock)
    await callback.answer()


@router.message(AdminStates.waiting_user_id_unblock)
async def unblock_user_process(message: Message, state: FSMContext):
    """Обработка разблокировки"""
    is_valid, user_id, error = FileValidator.validate_user_id(message.text)

    if not is_valid:
        await message.answer(error)
        return

    await db.set_blocked(user_id, False)

    await message.answer(
        f"✅ <b>Пользователь разблокирован!</b>\n\n"
        f"ID: <code>{user_id}</code>",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )

    await state.clear()


# ============= РАССЫЛКА =============

@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Начать рассылку"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.edit_text(
        "📢 <b>РАССЫЛКА</b>\n\n"
        "Отправьте текст для рассылки всем пользователям\n\n"
        "⚠️ HTML разметка поддерживается",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()


@router.message(AdminStates.waiting_broadcast)
async def broadcast_confirm(message: Message, state: FSMContext):
    """Подтверждение рассылки"""
    text = message.text or message.caption

    if not text:
        await message.answer("❌ Текст не может быть пустым")
        return

    await state.update_data(broadcast_text=text)

    users = await db.get_all_users()

    await message.answer(
        f"📢 <b>ПРЕДПРОСМОТР</b>\n\n"
        f"Получателей: <b>{len(users)}</b>\n\n"
        f"Текст:\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{text}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Подтвердите отправку:",
        reply_markup=AdminKeyboards.broadcast_confirm(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "confirm_broadcast")
async def broadcast_send(callback: CallbackQuery, state: FSMContext):
    """Отправить рассылку"""
    data = await state.get_data()
    text = data.get('broadcast_text')

    if not text:
        await callback.answer("Ошибка", show_alert=True)
        return

    users = await db.get_all_users()

    progress = await callback.message.edit_text(
        f"📤 <b>РАССЫЛКА...</b>\n\n"
        f"Отправлено: 0/{len(users)}",
        parse_mode="HTML"
    )

    sent = 0
    failed = 0

    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            sent += 1

            if sent % 10 == 0:
                try:
                    await progress.edit_text(
                        f"📤 <b>РАССЫЛКА...</b>\n\n"
                        f"✅ Отправлено: {sent}/{len(users)}\n"
                        f"❌ Ошибок: {failed}",
                        parse_mode="HTML"
                    )
                except:
                    pass

            await asyncio.sleep(0.05)

        except Exception as e:
            failed += 1
            logger.error(f"Ошибка рассылки {user_id}: {e}")

    await progress.edit_text(
        f"✅ <b>РАССЫЛКА ЗАВЕРШЕНА!</b>\n\n"
        f"✅ Доставлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n"
        f"📊 Всего: <b>{len(users)}</b>",
        reply_markup=AdminKeyboards.admin_panel(),
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "add_promo")
async def add_promos(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer('<b>Введите промокод:</b>')
    await state.set_state(Promo.wait_rew_code)

@router.message(Promo.wait_rew_code)
async def get_promo(message: Message, state: FSMContext):
    await state.update_data(promo=message.text)
    await message.answer('<b>Какая награда за него?</b>', reply_markup=rewards)
    await state.set_state(Promo.wait_reward)

@router.callback_query(F.data.startswith("promo:"), Promo.wait_reward)
async def get_rew(callback: CallbackQuery, state: FSMContext):
    reward = callback.data.split(":")[1]
    await state.update_data(reward=reward)
    await callback.message.answer('<b>Введите количество активаций:</b>')
    await state.set_state(Promo.wait_quant_promo)

@router.message(Promo.wait_quant_promo)
async def promo_code(message: Message, state: FSMContext):
    await state.update_data(quant=message.text)
    data = await state.get_data()
    try_promo = add_promo(data['promo'], data['reward'], int(data['quant']))
    if try_promo:
        await message.reply(f"<b>✨Промокод</b> <code>{data['promo']}</code> <b>создан!</b>\n"
                            f"Количество активаций: {data['quant']}\n"
                            f'Награда за активацию: {data["reward"]}\n')
    else:
        await message.answer('Не удалось создать промокод.')
    await state.clear()


# ============= ГЕНЕРАЦИЯ ПАЧКИ ПРОМОКОДОВ =============

def _generate_promo_code() -> str:
    """Генерировать случайный 6-значный промокод (буквы + цифры, верхний регистр)"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=6))


@router.callback_query(F.data == "gen_promos")
async def gen_promos_start(callback: CallbackQuery, state: FSMContext):
    """Шаг 1 — выбор количества промокодов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    await callback.message.answer(
        "🎰 <b>Генерация промокодов</b>\n\n"
        "Шаг 1 из 3 — выберите количество:",
        reply_markup=AdminKeyboards.gen_promo_count(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gen_count:"))
async def gen_promos_count(callback: CallbackQuery, state: FSMContext):
    """Шаг 1 — обработка выбора количества"""
    if not is_admin(callback.from_user.id):
        await callback.answer("🚫 Доступ запрещён!", show_alert=True)
        return

    value = callback.data.split(":")[1]

    if value == "custom":
        await callback.message.edit_text(
            "🎰 <b>Генерация промокодов</b>\n\n"
            "Шаг 1 из 3 — введите нужное количество (от 1 до 500):",
            parse_mode="HTML"
        )
        await state.set_state(GenPromo.wait_count_custom)
    else:
        await state.update_data(gen_count=int(value))
        await callback.message.edit_text(
            f"🎰 <b>Генерация промокодов</b>\n\n"
            f"✅ Количество: <b>{value}</b>\n\n"
            f"Шаг 2 из 3 — выберите награду:",
            reply_markup=AdminKeyboards.gen_promo_reward(),
            parse_mode="HTML"
        )
        await state.set_state(GenPromo.wait_reward)

    await callback.answer()


@router.message(GenPromo.wait_count_custom)
async def gen_promos_count_custom(message: Message, state: FSMContext):
    """Шаг 1 (своё число) — валидация и переход к награде"""
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 500):
        await message.answer("❌ Введите число от 1 до 500:")
        return

    count = int(text)
    await state.update_data(gen_count=count)
    await message.answer(
        f"🎰 <b>Генерация промокодов</b>\n\n"
        f"✅ Количество: <b>{count}</b>\n\n"
        f"Шаг 2 из 3 — выберите награду:",
        reply_markup=AdminKeyboards.gen_promo_reward(),
        parse_mode="HTML"
    )
    await state.set_state(GenPromo.wait_reward)


@router.callback_query(F.data.startswith("gen_reward:"), GenPromo.wait_reward)
async def gen_promos_reward(callback: CallbackQuery, state: FSMContext):
    """Шаг 2 — выбор награды"""
    reward = callback.data.split(":")[1]
    await state.update_data(gen_reward=reward)

    reward_labels = {
        "3_days": "⚡️ 3 дня",
        "week":   "📅 Неделя",
        "month":  "📆 Месяц",
        "forever": "♾ Навсегда",
    }
    label = reward_labels.get(reward, reward)

    await callback.message.edit_text(
        f"🎰 <b>Генерация промокодов</b>\n\n"
        f"✅ Награда: <b>{label}</b>\n\n"
        f"Шаг 3 из 3 — введите количество активаций каждого промокода:",
        parse_mode="HTML"
    )
    await state.set_state(GenPromo.wait_activations)
    await callback.answer()


@router.message(GenPromo.wait_activations)
async def gen_promos_create(message: Message, state: FSMContext):
    """Шаг 3 — генерируем и выводим промокоды"""
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("❌ Введите целое число больше 0:")
        return

    activations = int(text)
    data = await state.get_data()
    count = data['gen_count']
    reward = data['gen_reward']

    reward_labels = {
        "3_days":  "⚡️ 3 дня",
        "week":    "📅 Неделя",
        "month":   "📆 Месяц",
        "forever": "♾ Навсегда",
    }
    label = reward_labels.get(reward, reward)

    # Генерируем уникальные коды
    codes = set()
    while len(codes) < count:
        codes.add(_generate_promo_code())

    # Создаём промокоды в БД
    created = []
    failed = 0
    for code in codes:
        if add_promo(code, reward, activations):
            created.append(code)
        else:
            failed += 1

    # Выводим результат
    codes_block = "\n".join(created)
    header = (
        f"🎰 <b>Сгенерировано промокодов: {len(created)}</b>\n"
        f"🏆 Награда: <b>{label}</b>\n"
        f"🔁 Активаций каждый: <b>{activations}</b>\n"
    )
    if failed:
        header += f"⚠️ Не удалось создать: <b>{failed}</b>\n"
    header += "\n"

    # Если кодов много — отправляем отдельным сообщением чтобы не обрезалось
    await message.answer(header, parse_mode="HTML")
    await message.answer(f"<code>{codes_block}</code>", parse_mode="HTML")

    await state.clear()


class AdminSendMessage(StatesGroup):
    waiting_for_text = State()


@router.callback_query(F.data.startswith("admin_msg:"))
async def start_admin_msg_to_user(callback: CallbackQuery, state: FSMContext):
    # Можно добавить проверку, что это действительно админ
    # if callback.from_user.id not in ADMINS:
    #     await callback.answer("Нет доступа", show_alert=True)
    #     return

    try:
        _, user_id_str = callback.data.split(":")
        user_id = int(user_id_str)
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных кнопки", show_alert=True)
        return

    await state.update_data(target_user_id=user_id)

    await callback.message.edit_text(
        "✉️ Напиши сообщение, которое нужно отправить пользователю.\n\n"
        "• Можно отправить текст, фото, видео, голосовое и т.д.\n"
        "• Для отмены напиши /cancel",
        reply_markup=None  # убираем клавиатуру, если была
    )
    await callback.answer()
    await state.set_state(AdminSendMessage.waiting_for_text)


@router.message(AdminSendMessage.waiting_for_text, F.text == "/cancel")
async def cancel_sending(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отправка отменена.")


@router.message(AdminSendMessage.waiting_for_text)
async def process_admin_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("target_user_id")

    if not target_user_id:
        await message.answer("Произошла ошибка: не найден ID получателя.")
        await state.clear()
        return

    try:
        # Копируем сообщение пользователя (самый простой и надёжный способ)
        # сохраняются фото, видео, документы, подписи и т.д.
        await message.copy_to(chat_id=target_user_id)

        # Можно добавить приписку от кого сообщение
        # await bot.send_message(
        #     target_user_id,
        #     "Сообщение от администрации:"
        # )
        # await message.copy_to(chat_id=target_user_id)

        await message.answer(
            f"Сообщение успешно отправлено пользователю {target_user_id} ✅"
        )

    except Exception as e:
        await message.answer(
            f"Не удалось отправить сообщение:\n{type(e).__name__}: {e}"
        )

    await state.clear()
