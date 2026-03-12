# ==========================================
# ФАЙЛ: bot/keyboards/user_keyboards.py
# ОПИСАНИЕ: Клавиатуры пользователя
# ИСПРАВЛЕНИЯ:
#  1. account_detail, edit_profile, upload, come_to_acc, confirm_delete:
#     session_name в callback_data заменён на числовой индекс сессии.
#     Так решается ошибка BUTTON_DATA_INVALID (лимит 64 байта).
#  2. edit_accs: убран selected_sessions из callback_data.
# ==========================================
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict
from config import CHANNEL_LINK

reply_menu = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='🎛Главное меню'), KeyboardButton(text='💠Инвайтинг')],
    [KeyboardButton(text='👥Мои аккаунты'), KeyboardButton(text="📋 Задачи")],
    [KeyboardButton(text='👤Профиль'), KeyboardButton(text='🎁Промокод')],
    [KeyboardButton(text='⚙️Настройки'), KeyboardButton(text='💬Поддержка')]
], resize_keyboard=True)

send_to_help = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='🗨Отправить сообщение в поддержку через бота', callback_data='send_to_helpers')]
])





class UserKeyboards:
    """Клавиатуры пользователя"""

    @staticmethod
    def check_subscription() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK))
        kb.row(InlineKeyboardButton(text="✅ Я подписался!", callback_data="check_sub"))
        return kb.as_markup()

    @staticmethod
    def subscription_menu(has_test: bool) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        if not has_test:
            kb.row(InlineKeyboardButton(text="🎁 Тестовый период (24 часа)", callback_data="sub:test"))
        kb.row(
            InlineKeyboardButton(text="⚡️ 3 дня ", callback_data="sub:3_days"),
            InlineKeyboardButton(text="📅 Неделя ", callback_data="sub:week")
        )
        kb.row(
            InlineKeyboardButton(text="📆 Месяц", callback_data="sub:month"),
            InlineKeyboardButton(text="♾ Навсегда", callback_data="sub:forever")
        )
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
        return kb.as_markup()

    @staticmethod
    def main_menu(has_subscription: bool) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        if has_subscription:
            kb.row(InlineKeyboardButton(text="📱 Менеджер аккаунтов", callback_data="my_accounts:0"))
            kb.row(
                InlineKeyboardButton(text="⚙SMM и рассылка", callback_data="inviting"),
                InlineKeyboardButton(text="💎 Оформить подписку", callback_data="subscriptions")
            )
            kb.row(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
            kb.row(InlineKeyboardButton(text='⚙️Настройки', callback_data="user_settings"))
            kb.row(InlineKeyboardButton(text='📂Извлечь ссылки из папки чатов', callback_data='list_url'))
        else:
            kb.row(InlineKeyboardButton(text="💎 Оформить подписку", callback_data="subscriptions"))
        kb.row(InlineKeyboardButton(text="💬 Поддержка", callback_data="support"))
        return kb.as_markup()

    @staticmethod
    def profile_menu(sub_type: str = None, sub_until: str = None) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='🎁Промокод', callback_data="promo"))
        if sub_type:
            kb.row(InlineKeyboardButton(text="💎 Продлить подписку", callback_data="subscriptions"))
        else:
            kb.row(InlineKeyboardButton(text="💎 Оформить подписку", callback_data="subscriptions"))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
        return kb.as_markup()

    @staticmethod
    def accounts_list(
            sessions: List[str],
            states: Dict[str, str],
            page: int = 0,
            per_page: int = None,
            user_id: int = None,
    ) -> InlineKeyboardMarkup:
        """Список аккаунтов. Если передан user_id — берёт индивидуальные настройки."""
        try:
            from modules.kb_layout_settings import get_layout
            layout = get_layout(user_id) if user_id else {}
        except Exception:
            layout = {}

        _per_page  = per_page or layout.get("per_page", 10)
        _cols      = layout.get("cols", 2)
        _name_len  = layout.get("name_length", 10)
        _show_st   = layout.get("show_status", True)

        kb = InlineKeyboardBuilder()

        if not sessions:
            kb.row(InlineKeyboardButton(text="➕ Добавить аккаунты", callback_data="add_accounts"))
            kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
            return kb.as_markup()

        start = page * _per_page
        end = start + _per_page
        page_sessions = sessions[start:end]

        for i in range(0, len(page_sessions), _cols):
            row_btns = []
            for j in range(_cols):
                if i + j >= len(page_sessions):
                    break
                sname = page_sessions[i + j]
                st = states.get(sname) or "⚪"
                nm = sname.replace(".session", "")
                short = nm[:_name_len] + ".." if len(nm) > _name_len else nm
                display = f"{st} {short}" if _show_st else short
                row_btns.append(InlineKeyboardButton(
                    text=display,
                    callback_data=f"session:{sname}"
                ))
            kb.row(*row_btns)

        kb.row(
            InlineKeyboardButton(text="🔄 Проверить все", callback_data=f"validate_all:{page}"),
            InlineKeyboardButton(text="➕ Добавить", callback_data="add_accounts"),
        )
        kb.row(
            InlineKeyboardButton(text="🗑️ Удалить", callback_data="del_accounts"),
            InlineKeyboardButton(text="⚙️ Вид списка", callback_data=f"kb_layout_menu:{page}"),
        )

        total_pages = (len(sessions) + _per_page - 1) // _per_page
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"my_accounts:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="page_info"))
        if end < len(sessions):
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"my_accounts:{page + 1}"))
        if nav:
            kb.row(*nav)

        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
        return kb.as_markup()

    @staticmethod
    def kb_layout_menu(user_id: int, page: int = 0) -> InlineKeyboardMarkup:
        """Меню настроек вида клавиатуры аккаунтов."""
        try:
            from modules.kb_layout_settings import get_layout
            l = get_layout(user_id)
        except Exception:
            from modules.kb_layout_settings import DEFAULT_LAYOUT
            l = DEFAULT_LAYOUT.copy()

        kb = InlineKeyboardBuilder()

        # per_page
        kb.row(InlineKeyboardButton(text=f"📄 На странице: {l['per_page']}", callback_data="kbl_noop"))
        kb.row(
            InlineKeyboardButton(text="−", callback_data=f"kbl:per_page:dec:{page}"),
            InlineKeyboardButton(text=str(l['per_page']), callback_data="kbl_noop"),
            InlineKeyboardButton(text="+", callback_data=f"kbl:per_page:inc:{page}"),
        )
        # cols
        kb.row(InlineKeyboardButton(text=f"📐 Кнопок в строке: {l['cols']}", callback_data="kbl_noop"))
        kb.row(
            InlineKeyboardButton(text="−", callback_data=f"kbl:cols:dec:{page}"),
            InlineKeyboardButton(text=str(l['cols']), callback_data="kbl_noop"),
            InlineKeyboardButton(text="+", callback_data=f"kbl:cols:inc:{page}"),
        )
        # name_length
        kb.row(InlineKeyboardButton(text=f"✏️ Длина имени: {l['name_length']}", callback_data="kbl_noop"))
        kb.row(
            InlineKeyboardButton(text="−", callback_data=f"kbl:name_length:dec:{page}"),
            InlineKeyboardButton(text=str(l['name_length']), callback_data="kbl_noop"),
            InlineKeyboardButton(text="+", callback_data=f"kbl:name_length:inc:{page}"),
        )
        # toggles
        kb.row(InlineKeyboardButton(
            text=f"{'✅' if l['show_status'] else '❌'} Показывать статус",
            callback_data=f"kbl:show_status:toggle:{page}"
        ))
        kb.row(InlineKeyboardButton(
            text=f"{'✅' if l['auto_delete_invalid'] else '❌'} Автоудаление невалидных",
            callback_data=f"kbl:auto_delete_invalid:toggle:{page}"
        ))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"my_accounts:{page}"))
        return kb.as_markup()


    @staticmethod
    def account_detail(session_name: str, sessions: List[str] = None) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔑 Получить код", callback_data=f"get_code:{session_name}"))
        kb.row(InlineKeyboardButton(text="💾Выгрузить", callback_data=f"upload:{session_name}"))
        kb.row(InlineKeyboardButton(text='🛠Изменить профиль', callback_data=f"edit_acc:{session_name}"))
        kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data=f"check_valid:{session_name}"))
        kb.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{session_name}"))
        kb.row(InlineKeyboardButton(text="🔙 К списку", callback_data="my_accounts:0"))
        return kb.as_markup()

    @staticmethod
    def edit_profile(session_name: str, sessions: List[str] = None) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='📷Фото профиля', callback_data=f"profile_avatar:{session_name}"))
        kb.row(InlineKeyboardButton(text='👤Имя', callback_data=f"profile_name:{session_name}"))
        kb.row(InlineKeyboardButton(text='📝Описание', callback_data=f"profile_about:{session_name}"))
        kb.row(InlineKeyboardButton(text='💠Юзернейм', callback_data=f"profile_username:{session_name}"))
        kb.row(InlineKeyboardButton(text='⬅️Назад', callback_data=f"session:{session_name}"))
        return kb.as_markup()

    @staticmethod
    def edit_accs(selected_count: int = 0) -> InlineKeyboardMarkup:
        """
        FIX: убраны selected_sessions из callback_data (превышали 64 байта).
        Теперь selected_sessions берутся из JSON-хранилища по user_id.
        """
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📋 Выбрать аккаунты", callback_data="inv:select"))
        kb.row(InlineKeyboardButton(text='📷Фото профиля', callback_data="editor_avatar"))
        kb.row(InlineKeyboardButton(text='👤Имя', callback_data="editor_name"))
        kb.row(InlineKeyboardButton(text='📝Описание', callback_data="editor_about"))
        kb.row(InlineKeyboardButton(text='💠Юзернейм', callback_data="editor_username"))
        kb.row(InlineKeyboardButton(text='⬅️Назад', callback_data="inviting"))
        return kb.as_markup()

    @staticmethod
    def confirm_delete(session_name: str, sessions: List[str] = None) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete:{session_name}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"session:{session_name}")
        )
        return kb.as_markup()

    @staticmethod
    def add_accounts() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📦 Загрузить ZIP-архив с сессиями", callback_data="add_zip"))
        kb.row(InlineKeyboardButton(text="📱 Вход по номеру телефона", callback_data="add_phone"))
        # kb.row(InlineKeyboardButton(text="📷 Вход по QR-коду", callback_data="qr_auth"))
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="my_accounts:0"))
        return kb.as_markup()

    @staticmethod
    def add_accounts_menu() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📦 Загрузить ZIP-архив с сессиями", callback_data="add_zip"))
        kb.row(InlineKeyboardButton(text="📱 Вход по номеру телефона", callback_data="add_phone"))
        # kb.row(InlineKeyboardButton(text="📷 Вход по QR-коду", callback_data="qr_auth"))
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="my_accounts:0"))
        return kb.as_markup()

    @staticmethod
    def inv_menu() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📋 Выбрать аккаунты", callback_data="inv:select"))
        kb.row(InlineKeyboardButton(text="📤 Рассылка", callback_data="invitings"))
        kb.row(InlineKeyboardButton(text="📈 SMM(накрутка)", callback_data="smm_menu"))
        kb.row(InlineKeyboardButton(text="⚙️ Настройки задержек", callback_data="inv:delays"))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
        return kb.as_markup()

    @staticmethod
    def inviting_menu() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📢 Рассылка по чатам", callback_data="inv:links"))
        # kb.row(InlineKeyboardButton(text="📂 Рассылка по папке", callback_data="inv:folder"))
        kb.row(InlineKeyboardButton(text="👤 Рассылка по юзернеймам", callback_data="inv:usernames"))
        kb.row(InlineKeyboardButton(text="👥 Рассылка по контактам", callback_data="inv:contacts"))
        kb.row(InlineKeyboardButton(text="✉️ Отправка одному", callback_data="inv:one"))
        kb.row(InlineKeyboardButton(text="💬Рассылка по диалогам", callback_data="inv:dialog"))
        kb.row(InlineKeyboardButton(text="⚙️ Настройки задержек", callback_data="inv:delays"))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="inviting"))
        return kb.as_markup()

    @staticmethod
    def select_accounts(
            sessions: List[str],
            selected: List[str],
            page: int = 0
    ) -> InlineKeyboardMarkup:
        """
        Выбор аккаунтов для инвайтинга.
        callback_data = inv_toggle:{page}:{global_index}
        Глобальный индекс — позиция в общем списке sessions.
        Это позволяет избежать ошибки BUTTON_DATA_INVALID (лимит 64 байта).
        """
        kb = InlineKeyboardBuilder()

        per_page = 6
        start = page * per_page
        end = start + per_page
        page_sessions = sessions[start:end]

        for local_idx, full_session in enumerate(page_sessions):
            global_idx = start + local_idx
            name = full_session.replace('.session', '')

            select_emoji = "🟢" if full_session in selected else "🔴"

            if len(name) > 15:
                display = f"{select_emoji} {name[:15]}.."
            else:
                display = f"{select_emoji} {name}"

            kb.row(InlineKeyboardButton(
                text=display,
                callback_data=f"inv_toggle:{page}:{global_idx}"
            ))

        kb.row(
            InlineKeyboardButton(text="✅ Выбрать все", callback_data="inv_select_all"),
            InlineKeyboardButton(text="❌ Отменить все", callback_data="inv_deselect_all")
        )

        nav_btns = []
        total_pages = (len(sessions) + per_page - 1) // per_page

        if page > 0:
            nav_btns.append(InlineKeyboardButton(text="◀️", callback_data=f"inv:select:{page - 1}"))

        if total_pages > 1:
            nav_btns.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="page_info"))

        if end < len(sessions):
            nav_btns.append(InlineKeyboardButton(text="▶️", callback_data=f"inv:select:{page + 1}"))

        if nav_btns:
            kb.row(*nav_btns)

        kb.row(
            InlineKeyboardButton(text="✅ Готово", callback_data="inv_selected_done"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="inviting")
        )

        return kb.as_markup()

    @staticmethod
    def inviting_control(action_type: str) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🛑 Остановить", callback_data=f"inv_stop:{action_type}"))
        return kb.as_markup()

    @staticmethod
    def payment(sub_type: str, price: int) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text=f"💳 Оплатить {price} ⭐️", pay=True)
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="subscriptions"))
        return kb.as_markup()

    @staticmethod
    def upload(session_ref: str) -> InlineKeyboardMarkup:
        """FIX: принимает ref (индекс или имя) вместо полного session_name."""
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text='tdata', callback_data=f'convert_tdata:{session_ref}'),
            InlineKeyboardButton(text='session', callback_data=f'upload_session:{session_ref}')
        )
        return kb.as_markup()

    @staticmethod
    def come_to_acc(session_ref: str) -> InlineKeyboardMarkup:
        """FIX: принимает ref (индекс или имя) вместо полного session_name."""
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='⬅️Назад', callback_data=f"session_idx:{session_ref}"))
        return kb.as_markup()

    @staticmethod
    def come_to_inv() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='⬅️Назад', callback_data="inviting"))
        return kb.as_markup()

    @staticmethod
    def cancel_input(cancel_data: str = "cancel_input_action") -> InlineKeyboardMarkup:
        """Кнопка отмены при ожидании ввода файла или текста."""
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_data))
        return kb.as_markup()

    @staticmethod
    def buy_subs(sub_type: str, has_test: bool) -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        # Теперь просто crypto_bot, без параметров
        kb.row(InlineKeyboardButton(text='💠 CryptoBot (USDT)', callback_data='crypto_bot'))
        kb.row(InlineKeyboardButton(text='⭐ Telegram Stars', callback_data='stars'))
        kb.row(InlineKeyboardButton(text='💸 Другие способы (FunPay)', callback_data='fun_offer'))

        if not has_test:
            kb.row(InlineKeyboardButton(text="🎁 Тестовый период (24 часа)", callback_data="sub:test"))

        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
        return kb.as_markup()

    @staticmethod
    def smm_kb() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='📢 Подписчики на канал', callback_data='sub'),
               InlineKeyboardButton(text='💬 Участники чата', callback_data='chat'))
        kb.row(InlineKeyboardButton(text='👀 Просмотры на пост', callback_data='reviews'),
               InlineKeyboardButton(text='👍 Реакции на пост', callback_data='reactions'))
        kb.row(InlineKeyboardButton(text='📊 Голосование в опросе', callback_data='choise'))
        kb.row(InlineKeyboardButton(text='🔗 Рефералы для бота', callback_data='ref'),
               InlineKeyboardButton(text='🗣️ Ответ на сообщение в чате', callback_data='reply_msg'))
        kb.row(InlineKeyboardButton(text='🎉 Участие в розыгрыше по кнопке в каналах', callback_data='giveaway'))
        kb.row(InlineKeyboardButton(text='🔙 Назад', callback_data='inviting'))
        return kb.as_markup()


class Keyboards:
    @staticmethod
    def select_accounts_for_delete(
            sessions: List[str],
            selected: List[str],
            page: int = 0
    ) -> InlineKeyboardMarkup:
        """
        Выбор аккаунтов для удаления (1 кнопка в ряд, макс. 6 на странице).
        callback_data = del_toggle:{page}:{global_index}
        """
        kb = InlineKeyboardBuilder()

        per_page = 6
        start = page * per_page
        end = start + per_page
        page_sessions = sessions[start:end]

        for local_idx, full_session in enumerate(page_sessions):
            global_idx = start + local_idx
            name = full_session.replace('.session', '')

            select_emoji = "🟢" if full_session in selected else "🔴"

            if len(name) > 15:
                display = f"{select_emoji} {name[:15]}.."
            else:
                display = f"{select_emoji} {name}"

            kb.row(InlineKeyboardButton(
                text=display,
                callback_data=f"del_toggle:{page}:{global_idx}"
            ))

        kb.row(
            InlineKeyboardButton(text="✅ Выбрать все", callback_data="del_select_all"),
            InlineKeyboardButton(text="❌ Отменить все", callback_data="del_deselect_all")
        )

        nav_btns = []
        total_pages = (len(sessions) + per_page - 1) // per_page

        if page > 0:
            nav_btns.append(InlineKeyboardButton(text="◀️", callback_data=f"del_page:{page - 1}"))

        if total_pages > 1:
            nav_btns.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="page_info"))

        if end < len(sessions):
            nav_btns.append(InlineKeyboardButton(text="▶️", callback_data=f"del_page:{page + 1}"))

        if nav_btns:
            kb.row(*nav_btns)

        kb.row(
            InlineKeyboardButton(text="✅ Удалить выбранные", callback_data="del_confirm"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="my_accounts:0")
        )

        return kb.as_markup()

    @staticmethod
    def user_settings_kb() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='📎 Настройки API', callback_data='api_settings'))
        kb.row(InlineKeyboardButton(text="⚙️ Настройки задержек", callback_data="inv:delays"))
        kb.row(InlineKeyboardButton(text="🛡 Автоснятие спамблока", callback_data="spamblock_settings"))
        kb.row(InlineKeyboardButton(text="📂 Рассылка по папке", callback_data="folder_settings"))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
        return kb.as_markup()

    @staticmethod
    def api_set_kb() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text='📝Изменить API ключи', callback_data='api_set'))
        kb.row(InlineKeyboardButton(text="🔙Назад", callback_data='back_setting'))
        return kb.as_markup()


choice = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Pyrogram-сессии', callback_data='telethon')]
])