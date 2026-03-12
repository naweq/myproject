import datetime
import json

import aiofiles
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiocryptopay import AioCryptoPay, Networks
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()
from keyboards.user_keyboards import UserKeyboards

kb = UserKeyboards()
from config import CRYPTO_TOKEN, PROMO_FILE
from modules.database import Database
db = Database()
cryptopay = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)

class Promo(StatesGroup):
    wait_promo = State()

str_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='👤Менеджер', url='https://t.me/SenderX_GIFT')],
])


def add_promo(code: str, reward: str, max_uses: int = 1) -> bool:
    code = code.strip().upper()

    # Создаём файл если его нет
    if not PROMO_FILE.exists():
        PROMO_FILE.write_text('{}', encoding='utf-8')

    with open(PROMO_FILE, "r+", encoding="utf-8") as f:
        data = json.load(f)

        if code in data:
            return False  # Уже существует

        data[code] = {
            "reward": reward,
            "max_uses": max_uses,
            "remaining": max_uses,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d"),
            "used_by": []  # Новый список для пользователей
        }

        f.seek(0)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.truncate()

        return True


async def use_promo(code: str, user_id: int) -> tuple[bool, str, int | None]:
    code = code.strip().upper()

    try:
        async with aiofiles.open(PROMO_FILE, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return False, "Промокод не найден!", None

    if code not in data:
        return False, "Промокод не найден!", None

    promo = data[code]

    if user_id in promo.get("used_by", []):
        return False, "Вы уже использовали этот промокод!", None

    if promo["remaining"] <= 0:
        return False, "Промокод уже исчерпан!", None

    # Обновляем
    promo["used_by"].append(user_id)
    promo["remaining"] -= 1
    reward = promo["reward"]

    async with aiofiles.open(PROMO_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=2, ensure_ascii=False))
    return True, f"✅ Промокод успешно активирован", reward


# 1. Сначала вызываем общее меню выбора способа оплаты
@router.callback_query(F.data == 'subscriptions')
async def buy_subs_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    has_test = db.is_test_used(user_id)

    # Показываем способы оплаты.
    # Важно: теперь передаем sub_type как "none" или пустой,
    # так как тариф еще не выбран.
    await callback.message.edit_text(
        '<b>Выберите удобный способ оплаты:</b>',
        reply_markup=kb.buy_subs(sub_type="choosing", has_test=has_test)
    )


# 2. Если выбрали CryptoBot — только тогда показываем выбор длительности
@router.callback_query(F.data == 'crypto_bot')
async def crypto_bot_durations(callback: CallbackQuery):
    user_id = callback.from_user.id
    has_test = db.is_test_used(user_id)

    await callback.message.edit_text(
        '<b>CryptoBot: Выберите длительность подписки:</b>',
        reply_markup=kb.subscription_menu(has_test)
    )


# 3. Обработка выбора тарифа (теперь она запускает инвойс CryptoBot)
@router.callback_query(F.data.startswith('sub:'))
async def process_sub_selection(callback: CallbackQuery):
    sub_type = callback.data.split(':')[1]
    user_id = callback.from_user.id

    if sub_type == "test":
        if db.is_test_used(user_id):
            await callback.answer("❌ Тест уже использован!", show_alert=True)
        else:
            await db.activate_subscription(user_id, "test")
            await callback.message.edit_text(
                "🎉 <b>Тестовый период активирован!</b>",
                reply_markup=UserKeyboards.main_menu(True),
                parse_mode="HTML"
            )
    else:
        # Сразу вызываем создание счета CryptoBot, так как тариф выбран внутри ветки крипты
        await create_crypto_invoice(callback, sub_type)


# Вынес создание инвойса в отдельную функцию для чистоты
async def create_crypto_invoice(callback: CallbackQuery, sub_type: str):
    await callback.message.edit_text('<i>Создаю ссылку для оплаты...</i>')

    prices = {
        "3_days": 0.3,
        "week": 0.65,
        "month": 2.7,
        "forever": 4
    }
    amount = prices.get(sub_type)

    invoice = await cryptopay.create_invoice(
        asset='USDT',
        amount=amount,
        description=f"Подписка {sub_type}",
        expires_in=3600
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Перейти к оплате", url=invoice.bot_invoice_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_invoice:{invoice.invoice_id}:{sub_type}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_bot")]
    ])

    await callback.message.edit_text(
        f"Счет создан! ID: {invoice.invoice_id}\nСумма: {amount} USDT",
        reply_markup=markup
    )



@router.callback_query(F.data.startswith('crypto_bot:'))
async def crypto_bot(callback: CallbackQuery):
    sub_type = callback.data.split(':')[1]
    await callback.message.edit_text('<i>Создаю ссылку для оплаты...</i>')
    asset = 'USDT'
    amount = None
    if sub_type == "3_days":
        amount = 0.3
    elif sub_type == "week":
        amount = 0.65
    elif sub_type == "month":
        amount = 2.7
    elif sub_type == "forever":
        amount = 4

    invoice = await cryptopay.create_invoice(
        asset='USDT',  # Валюта (USDT, TON, BTC, etc.)
        amount=amount,  # Сумма
        description="Оплата подписки",
        expires_in=3600  # Срок жизни счета в секундах (1 час)
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Перейти к оплате", url=invoice.bot_invoice_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_invoice:{invoice.invoice_id}:{sub_type}")],
    ])

    await callback.message.edit_text(
        f"Счет создан! ID: {invoice.invoice_id}\nСумма: {amount} USDT\n<i>Счет действует 1 час</i>",
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("check_invoice:"))
async def check_invoice(callback: CallbackQuery):
    # FIX: был startswith("check_") — перехватывал check_temp:, check_sub: и др.
    # Теперь точный префикс check_invoice:
    try:
        _, invoice_id_str, sub_type = callback.data.split(":", 2)
        invoice_id = int(invoice_id_str)
    except (ValueError, IndexError):
        await callback.answer("❌ Некорректные данные счёта", show_alert=True)
        return

    user_id = callback.from_user.id
    print(f"ID: {invoice_id}, Тариф: {sub_type}")
    invoices = await cryptopay.get_invoices(invoice_ids=[invoice_id])
    if not invoices:
        await callback.answer("Счет не найден.", show_alert=True)
        return

    invoice = invoices[0]

    stars = None
    if sub_type == "3_days":
        stars = 12
    elif sub_type == "week":
        stars = 40
    elif sub_type == "month":
        stars = 125
    elif sub_type == "forever":
        stars = 180

    if invoice.status == "paid":
        await callback.message.edit_text(f"<b>✅ Оплата прошла успешно!</b> Выдаю подписку...")
        # ТУТ ВАША ЛОГИКА (выдать роль, записать в БД и т.д.)
        await db.activate_subscription(user_id, sub_type, stars=stars)
    elif invoice.status == "active":
        await callback.answer("Оплата пока не поступила. Попробуйте через минуту.", show_alert=True)
    else:
        await callback.message.edit_text(f"Статус счета: {invoice.status}")

@router.callback_query(F.data == 'stars')
async def stars(callback: CallbackQuery):
    await callback.message.edit_text('<b>Оплата в звёздах</b>\n'
                                     '⚡️ 3 дня — 15 ⭐\n'
                                    '📅 7 дней (неделя) — 40 ⭐\n'
                                    '📆 30 дней (месяц) — 125 ⭐\n'
                                    '♾ Навсегда — 200 ⭐\n'
                                    '<b>Для оплаты подписки отправьте подарки на необходимую сумму <a href="https://t.me/SenderX_GIFT">нашему менеджеру</a> </b>',
                                     reply_markup=str_kb
                                     )

to_prof = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='🔙 Назад', callback_data='profile')]
])
@router.message(F.text == '🎁Промокод')
async def promocode_txt(message: Message, state: FSMContext):
    await message.reply('<b>Введите промокод для получения подарка:</b>', reply_markup=to_prof)
    await state.set_state(Promo.wait_promo)

@router.callback_query(F.data == 'promo')
async def promocode(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('<b>Введите промокод для получения подарка:</b>', reply_markup=to_prof)
    await state.set_state(Promo.wait_promo)

@router.message(Promo.wait_promo)
async def check_promo(message: Message, state: FSMContext):
    await state.update_data(promo=message.text)
    data = await state.get_data()
    promo = data['promo']
    user_id = message.from_user.id
    succes, msg, reward = await use_promo(promo, user_id)

    if succes:
        await message.reply(msg, reply_markup=to_prof)
        await db.activate_subscription(user_id=user_id, sub_type=str(reward), stars=0)

    else:
        await message.reply(msg, reply_markup=to_prof)

    await state.clear()

from config import OFFER_LINKS


def get_offers_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Добавляем кнопки (они выстроятся в ряд автоматически, если не указать adjust)
    builder.button(text="3 дня", url=OFFER_LINKS["3_days"])
    builder.button(text="7 Дней", url=OFFER_LINKS["week"])
    builder.button(text="1 Месяц", url=OFFER_LINKS["month"])
    builder.button(text="Навсегда", url=OFFER_LINKS["forever"])

    # Метод .adjust(2) говорит билдеру делать по 2 кнопки в ряд
    builder.adjust(2)

    return builder.as_markup()

@router.callback_query(F.data == 'fun_offer')
async def fun_offer(callback: CallbackQuery):
    user_id = callback.message.from_user.id
    has_test = db.is_test_used(user_id)

    await callback.message.edit_text(text="💵 Для оплаты другим способом оплатите оффер на <b>FunPay</b>. Стоит автовыдача - <b>после оплаты вы получите промокод на соответсвующий срок</b>\n\nАктивировать его можно с помощью кнопки на клавиатуре или в разделе Профиль - Промокод",
                                     reply_markup=get_offers_keyboard()
                                     )