# ==========================================
# ФАЙЛ: bot/keyboards/admin_keyboards.py
# ОПИСАНИЕ: Клавиатуры администратора
# ==========================================

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AdminKeyboards:
    """Клавиатуры администратора"""

    @staticmethod
    def admin_panel() -> InlineKeyboardMarkup:
        """Главная админ-панель"""
        kb = InlineKeyboardBuilder()

        kb.row(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
        kb.row(
            InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users:0"),
            InlineKeyboardButton(text="🔍 Найти юзера", callback_data="admin_find")
        )
        kb.row(
            InlineKeyboardButton(text="💎 Выдать подписку", callback_data="admin_give_sub"),
            InlineKeyboardButton(text="↩️ Вернуть подписку", callback_data="admin_refund")
        )
        kb.row(
            InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block"),
            InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unblock")
        )
        kb.row(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
        kb.row(InlineKeyboardButton(text="🧑‍💼 Добавить админа", callback_data="add_admin"))
        kb.row(
            InlineKeyboardButton(text="🎁 Добавить промокод", callback_data="add_promo"),
            InlineKeyboardButton(text="🎰 Генерировать промо", callback_data="gen_promos")
        )
        kb.row(InlineKeyboardButton(text="🔙 Закрыть", callback_data="close_admin"))

        return kb.as_markup()

    @staticmethod
    def back_admin() -> InlineKeyboardMarkup:
        """Назад к админ-панели"""
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel"))
        return kb.as_markup()

    @staticmethod
    def users_list_pagination(page: int, total_pages: int) -> InlineKeyboardMarkup:
        """Пагинация списка пользователей"""
        kb = InlineKeyboardBuilder()

        nav_btns = []
        if page > 0:
            nav_btns.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_users:{page - 1}"))

        nav_btns.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="page_info"))

        if page < total_pages - 1:
            nav_btns.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_users:{page + 1}"))

        if nav_btns:
            kb.row(*nav_btns)

        kb.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel"))
        return kb.as_markup()

    @staticmethod
    def user_actions(user_id: int) -> InlineKeyboardMarkup:
        """Действия с пользователем"""
        kb = InlineKeyboardBuilder()

        kb.row(
            InlineKeyboardButton(text="💎 Подписка", callback_data=f"admin_user_sub:{user_id}"),
            InlineKeyboardButton(text="🚫 Блок", callback_data=f"admin_user_block:{user_id}")
        )
        kb.row(InlineKeyboardButton(text="✉️ Написать", callback_data=f"admin_msg:{user_id}"))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_users:0"))

        return kb.as_markup()

    @staticmethod
    def broadcast_confirm() -> InlineKeyboardMarkup:
        """Подтверждение рассылки"""
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_broadcast"))
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel"))
        return kb.as_markup()

    @staticmethod
    def subscription_types() -> InlineKeyboardMarkup:
        """Выбор типа подписки для выдачи"""
        kb = InlineKeyboardBuilder()

        kb.row(InlineKeyboardButton(text="⚡️ 3 дня", callback_data="admin_sub_type:3_days"))
        kb.row(InlineKeyboardButton(text="📅 Неделя", callback_data="admin_sub_type:week"))
        kb.row(InlineKeyboardButton(text="📆 Месяц", callback_data="admin_sub_type:month"))
        kb.row(InlineKeyboardButton(text="♾ Навсегда", callback_data="admin_sub_type:forever"))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))

        return kb.as_markup()

    @staticmethod
    def gen_promo_count() -> InlineKeyboardMarkup:
        """Выбор количества промокодов для генерации"""
        kb = InlineKeyboardBuilder()

        kb.row(
            InlineKeyboardButton(text="5",   callback_data="gen_count:5"),
            InlineKeyboardButton(text="10",  callback_data="gen_count:10"),
            InlineKeyboardButton(text="25",  callback_data="gen_count:25"),
        )
        kb.row(
            InlineKeyboardButton(text="50",  callback_data="gen_count:50"),
            InlineKeyboardButton(text="100", callback_data="gen_count:100"),
            InlineKeyboardButton(text="✏️ Своё", callback_data="gen_count:custom"),
        )
        kb.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel"))

        return kb.as_markup()

    @staticmethod
    def gen_promo_reward() -> InlineKeyboardMarkup:
        """Выбор награды для генерируемых промокодов"""
        kb = InlineKeyboardBuilder()

        kb.row(
            InlineKeyboardButton(text="⚡️ 3 дня",   callback_data="gen_reward:3_days"),
            InlineKeyboardButton(text="📅 Неделя",  callback_data="gen_reward:week"),
        )
        kb.row(
            InlineKeyboardButton(text="📆 Месяц",   callback_data="gen_reward:month"),
            InlineKeyboardButton(text="♾ Навсегда", callback_data="gen_reward:forever"),
        )
        kb.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_panel"))

        return kb.as_markup()