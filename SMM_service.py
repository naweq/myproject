# ==========================================
# ФАЙЛ: SMM_service.py — ПАТЧ (полная замена файла)
# Скопируй и замени содержимое файла целиком
# ==========================================

import asyncio
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from modules.SMM import TelegramActions
from handlers.inviting_handlers import get_selected_accounts, get_delays
from modules.task_manager import task_manager, TaskType, TaskStatus  # ← НОВЫЙ импорт

router = Router()


class sub(StatesGroup):
    wait_link = State()

class chat(StatesGroup):
    wait_link = State()

class review(StatesGroup):
    wait_post = State()

class reaction(StatesGroup):
    wait_post = State()
    wait_reaction = State()

class voite(StatesGroup):
    wait_post = State()
    wait_change = State()

class refer(StatesGroup):
    wait_ref_link = State()

class reply(StatesGroup):
    wait_msg_link = State()
    wait_chat_link = State()
    wait_text = State()

class giveaway(StatesGroup):
    wait_link_post = State()
    wait_button = State()


from modules.session_manager import SessionManager
session_manager = SessionManager()
smm = TelegramActions()


# ─── Вспомогательная функция ───────────────────────────────
async def _run_smm_task(coro, task):
    """Обёртка: запускает корутину и завершает таск после"""
    try:
        await coro
        await task_manager.finish_task(task.task_id, TaskStatus.FINISHED)
    except Exception as e:
        await task_manager.finish_task(task.task_id, TaskStatus.ERROR)
        raise


# ─────────────────────────────────────────────────────────────
# ПОДПИСКА НА КАНАЛ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'sub')
async def start_subbing(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)
    if not selected:
        await callback.answer('Для начала выберите аккаунты', show_alert=True)
        return
    await callback.message.answer(
        f'<b>Отправьте ссылку на канал:</b>\n\n'
        f'<i>Поддерживаются все типы каналов</i>',
        parse_mode="HTML"
    )
    await state.set_state(sub.wait_link)


@router.message(sub.wait_link)
async def start_subbing_run(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    user_id = message.from_user.id
    selected = get_selected_accounts(user_id)
    link = message.text
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_SUB, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('Запускаю...')
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.join_channel(session_files=selected, user_id=user_id, channel_link=link, delay_between=delay_bet),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# ВСТУПЛЕНИЕ В ЧАТ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'chat')
async def start_chat(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected = get_selected_accounts(user_id)
    if not selected:
        await callback.answer('Для начала выберите аккаунты', show_alert=True)
        return
    await callback.message.answer('Отправьте ссылку на чат, в который необходимо вступить аккаунтам:')
    await state.set_state(chat.wait_link)


@router.message(chat.wait_link)
async def start_chat_run(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    link = message.text
    selected = get_selected_accounts(message.from_user.id)
    user_id = message.from_user.id
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_CHAT, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('Запускаю...')
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.join_chat(session_files=selected, user_id=user_id, chat_link=link, delay_between=delay_bet),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# ПРОСМОТРЫ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'reviews')
async def start_rewievs(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("<b>Отправьте ссылку на пост: </b>", parse_mode="HTML")
    await state.set_state(review.wait_post)


@router.message(review.wait_post)
async def start_rewievs_run(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    user_id = message.from_user.id
    selected = get_selected_accounts(user_id)
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])
    link = message.text

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_VIEWS, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('<i>Запускаю...</i>', parse_mode="HTML")
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.view_post(session_files=selected, user_id=user_id, post_link=link, delay_between=delay_bet),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# РЕАКЦИИ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'reactions')
async def start_reactions(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('<b>Отправьте ссылку на пост: </b>', parse_mode="HTML")
    await state.set_state(reaction.wait_post)


@router.message(reaction.wait_post)
async def start_reac2(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.reply('Отлично, теперь отправь нужную реакцию обычным эмодзи')
    await state.set_state(reaction.wait_reaction)


@router.message(reaction.wait_reaction)
async def start_reac3(message: Message, state: FSMContext):
    await state.update_data(reac=message.text)
    user_id = message.from_user.id
    data = await state.get_data()
    selected = get_selected_accounts(user_id)
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])
    link = data['link']
    reaction_emoji = data['reac']

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_REACTIONS, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('<i>Запускаю...</i>', parse_mode="HTML")
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.react_to_post(session_files=selected, user_id=user_id, post_link=link, reaction=str(reaction_emoji), delay_between=delay_bet),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# ГОЛОСОВАНИЕ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'choise')
async def start_choise(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('<b>Отправьте ссылку на пост с голосованием: </b>', parse_mode="HTML")
    await state.set_state(voite.wait_post)


@router.message(voite.wait_post)
async def start_choise2(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.reply(
        '<b>Отправьте номер ответа, начиная с 0:</b>\n\n'
        '<i>0 - первый вариант\n1 - второй\nи так далее...</i>',
        parse_mode="HTML"
    )
    await state.set_state(voite.wait_change)


@router.message(voite.wait_change)
async def start_choise3(message: Message, state: FSMContext):
    await state.update_data(numb=message.text)
    data = await state.get_data()
    selected = get_selected_accounts(message.from_user.id)
    user_id = message.from_user.id
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])
    link = data['link']
    numb = data['numb']

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_VOTE, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('<i>Запускаю...</i>', parse_mode="HTML")
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.vote_in_poll(session_files=selected, user_id=user_id, poll_link=link, option_indices=numb, delay_between=delay_bet),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# РЕФ-ССЫЛКА
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'ref')
async def start_ref(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('<b>Отправьте вашу реферальную ссылку: </b>', parse_mode="HTML")
    await state.set_state(refer.wait_ref_link)


@router.message(refer.wait_ref_link)
async def start_ref2(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    data = await state.get_data()
    selected = get_selected_accounts(message.from_user.id)
    user_id = message.from_user.id
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])
    link = data['link']

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_REF, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('<i>Запускаю...</i>', parse_mode="HTML")
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.start_bot_with_ref(session_files=selected, user_id=user_id, bot_link=link, delay_between=delay_bet),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# ОТВЕТ НА СООБЩЕНИЕ
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'reply_msg')
async def start_reply_msg(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer('<b>Отправьте ссылку на сообщение, на которое необходимо ответить: </b>', parse_mode="HTML")
    await state.set_state(reply.wait_msg_link)


@router.message(reply.wait_msg_link)
async def start_reply_msg2(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.reply(
        '<b>Нужно ли вступать в чат для ответа?</b>\n\n'
        'Если да, отправьте ссылку на чат, если нет - просто 0 или другой символ',
        parse_mode="HTML"
    )
    await state.set_state(reply.wait_chat_link)


@router.message(reply.wait_chat_link)
async def start_reply_msg3(message: Message, state: FSMContext):
    link = message.text if 'https://' in message.text else None
    await state.update_data(chat_link=link)
    await message.reply('<b>Введите текст сообщения для ответа:</b>', parse_mode="HTML")
    await state.set_state(reply.wait_text)


@router.message(reply.wait_text)
async def start_reply_msg4(message: Message, state: FSMContext):
    text = message.text
    user_id = message.from_user.id
    data = await state.get_data()
    selected = get_selected_accounts(user_id)
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_REPLY, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.reply('<i>Запускаю...</i>', parse_mode="HTML")
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.reply_to_message(
                session_files=selected, user_id=user_id,
                message_link=str(data['link']), invite_link=str(data['chat_link']),
                delay_between=delay_bet, text=text
            ),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()


# ─────────────────────────────────────────────────────────────
# РОЗЫГРЫШ (КНОПКА)
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == 'giveaway')
async def start_giveaway(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('<b>Отправьте ссылку на сообщение с розыгрышем и кнопкой: </b>', parse_mode="HTML")
    await state.set_state(giveaway.wait_link_post)


@router.message(giveaway.wait_link_post)
async def start_giveaway2(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.reply(
        '<b>На какую кнопку по счету аккаунты должны нажать?</b>\n\n'
        '<i>Начиная с 0 </i>',
        parse_mode="HTML"
    )
    await state.set_state(giveaway.wait_button)


@router.message(giveaway.wait_button)
async def start_giveaway3(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = get_selected_accounts(message.from_user.id)
    user_id = message.from_user.id
    delay_bt = get_delays(user_id)
    delay_bet = float(delay_bt['message'])

    task, conflicts = await task_manager.try_create_task(
        user_id=user_id, task_type=TaskType.SMM_GIVEAWAY, accounts=selected
    )
    if conflicts:
        await message.answer(task_manager.format_conflict_message(conflicts), parse_mode="HTML")
        return

    msg = await message.answer('<i>Запускаю...</i>', parse_mode="HTML")
    await asyncio.sleep(1.4)
    await msg.edit_text(f'Накрутка запущена, ожидайте...\n🆔 Таск: <b>#{task.task_id}</b>', parse_mode="HTML")

    asyncio_task = asyncio.create_task(
        _run_smm_task(
            smm.click_inline_button(
                session_files=selected, user_id=user_id,
                post_link=str(data['link']), button_index=int(message.text), delay_between=delay_bet
            ),
            task
        )
    )
    task.asyncio_task = asyncio_task
    await state.clear()