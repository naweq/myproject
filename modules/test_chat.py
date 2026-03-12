#!/usr/bin/env python3
"""
Скрипт для тестирования доступа к конкретному чату.
Использование: python test_chat.py @channel_name
"""

import asyncio
import sys
import logging
from telethon import TelegramClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# ВСТАВЬ СВОИ ДАННЫЕ
API_ID = 12345678  # Твой API ID
API_HASH = "your_api_hash_here"  # Твой API Hash
PHONE = "+1234567890"  # Номер телефона
SESSION_NAME = "test_session"  # Имя сессии


async def test_chat_detailed(client, chat_link: str):
    """Детальная проверка чата"""
    print("\n" + "=" * 60)
    print(f"🔍 ТЕСТИРОВАНИЕ ЧАТА: {chat_link}")
    print("=" * 60 + "\n")

    try:
        # 1. Получаем информацию о чате
        print("📋 Шаг 1: Получение информации о чате...")
        try:
            chat = await client.get_entity(chat_link)
            print(f"  ✅ Чат найден: {chat.title}")
            print(f"  📌 ID: {chat.id}")
            print(f"  📌 Username: {getattr(chat, 'username', 'Нет')}")
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
            return

        # 2. Проверяем тип чата
        print("\n📊 Шаг 2: Определение типа чата...")
        chat_type = type(chat).__name__
        print(f"  📌 Тип: {chat_type}")

        if hasattr(chat, 'broadcast'):
            is_channel = chat.broadcast
            print(f"  📢 Это канал (broadcast): {is_channel}")

        if hasattr(chat, 'megagroup'):
            is_megagroup = chat.megagroup
            print(f"  👥 Это супергруппа (megagroup): {is_megagroup}")

        # 3. Проверяем участие
        print("\n👤 Шаг 3: Проверка участия в чате...")
        is_member = False
        try:
            async for _ in client.iter_participants(chat, limit=1):
                is_member = True
                break
            if is_member:
                print(f"  ✅ Вы УЧАСТНИК этого чата")
            else:
                print(f"  ⚠️ Чат пустой или особые настройки")
        except Exception as e:
            print(f"  ❌ Вы НЕ участник: {e}")

        # 4. Проверяем общие настройки чата
        print("\n⚙️ Шаг 4: Проверка настроек чата...")
        if hasattr(chat, 'default_banned_rights') and chat.default_banned_rights:
            rights = chat.default_banned_rights
            print(f"  🚫 Глобальные ограничения:")
            if hasattr(rights, 'send_messages'):
                print(f"     • Отправка сообщений запрещена: {rights.send_messages}")
            if hasattr(rights, 'send_media'):
                print(f"     • Отправка медиа запрещена: {rights.send_media}")
            if hasattr(rights, 'send_polls'):
                print(f"     • Создание опросов запрещено: {rights.send_polls}")
        else:
            print(f"  ✅ Нет глобальных ограничений")

        # 5. Проверяем НАШИ права
        print("\n🔑 Шаг 5: Проверка ваших прав...")
        try:
            perms = await client.get_permissions(chat)
            print(f"  📌 Тип объекта прав: {type(perms).__name__}")

            # Проверяем все возможные атрибуты
            if hasattr(perms, 'is_admin'):
                print(f"  👑 Админ: {perms.is_admin}")
            if hasattr(perms, 'is_banned'):
                print(f"  🚫 Забанен: {perms.is_banned}")
            if hasattr(perms, 'send_messages'):
                print(f"  ✉️ Право писать (send_messages): {perms.send_messages}")
            if hasattr(perms, 'send_media'):
                print(f"  🖼️ Право отправлять медиа: {perms.send_media}")

            # Выводим все атрибуты для отладки
            print(f"\n  🔍 Все атрибуты объекта прав:")
            for attr in dir(perms):
                if not attr.startswith('_'):
                    try:
                        value = getattr(perms, attr)
                        if not callable(value):
                            print(f"     • {attr}: {value}")
                    except:
                        pass

        except Exception as e:
            print(f"  ❌ Ошибка получения прав: {e}")

        # 6. Пробуем отправить тестовое сообщение
        print("\n📨 Шаг 6: Попытка отправки тестового сообщения...")
        try:
            test_message = "🧪 Тестовое сообщение от бота"
            msg = await client.send_message(chat, test_message)
            print(f"  ✅ Сообщение успешно отправлено! ID: {msg.id}")

            # Удаляем тестовое сообщение
            print(f"  🗑️ Удаляем тестовое сообщение...")
            await client.delete_messages(chat, msg.id)
            print(f"  ✅ Тестовое сообщение удалено")

        except Exception as e:
            print(f"  ❌ ОШИБКА отправки: {e}")
            error_str = str(e)

            if "CHAT_WRITE_FORBIDDEN" in error_str:
                print(f"     💡 Причина: Обычным участникам запрещено писать в этом чате")
            elif "ALLOW_PAYMENT_REQUIRED" in error_str:
                print(f"     💡 Причина: Требуется платная подписка для отправки сообщений")
            elif "CHANNEL_PRIVATE" in error_str:
                print(f"     💡 Причина: Чат приватный или вы забанены")

        # 7. Итоговая оценка
        print("\n" + "=" * 60)
        print("📊 ИТОГОВАЯ ОЦЕНКА")
        print("=" * 60)

        can_send = False

        if is_member:
            print("✅ Вы участник чата")

            # Логика определения прав
            try:
                perms = await client.get_permissions(chat)

                if hasattr(perms, 'is_admin') and perms.is_admin:
                    print("✅ У вас есть права администратора")
                    can_send = True
                elif hasattr(chat, 'broadcast') and chat.broadcast:
                    print("❌ Это канал - писать могут только админы")
                    can_send = False
                elif hasattr(perms, 'send_messages') and not perms.send_messages:
                    print("❌ У вас нет прав на отправку сообщений")
                    can_send = False
                elif hasattr(chat, 'default_banned_rights') and chat.default_banned_rights:
                    if hasattr(chat.default_banned_rights,
                               'send_messages') and chat.default_banned_rights.send_messages:
                        print("❌ Отправка сообщений запрещена в этом чате")
                        can_send = False
                    else:
                        print("✅ Нет запретов на отправку")
                        can_send = True
                else:
                    print("✅ Вероятно, вы можете отправлять сообщения")
                    can_send = True
            except:
                print("⚠️ Не удалось точно определить права")
        else:
            print("❌ Вы НЕ участник чата")

        if can_send:
            print("\n🎉 ВЕРДИКТ: Скорее всего, вы МОЖЕТЕ отправлять сообщения")
        else:
            print("\n🚫 ВЕРДИКТ: Вы НЕ МОЖЕТЕ отправлять сообщения")

        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()


async def main():
    if len(sys.argv) < 2:
        print("Использование: python test_chat.py @channel_name")
        print("Пример: python test_chat.py @durov")
        sys.exit(1)

    chat_link = sys.argv[1]

    print("\n🚀 Запуск тестирования...")
    print(f"📱 Номер телефона: {PHONE}")

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    await client.start(phone=PHONE)
    print("✅ Успешно авторизованы\n")

    await test_chat_detailed(client, chat_link)

    await client.disconnect()
    print("👋 Завершено")


if __name__ == "__main__":
    asyncio.run(main())