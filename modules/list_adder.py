import asyncio
import os
from datetime import datetime
import logging

from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from config import bot
from pyrogram import Client
from pyrogram.raw import functions, types
import re

# Подавляем логи Pyrogram для чистого вывода
logging.getLogger("pyrogram").setLevel(logging.ERROR)

# ===== НАСТРОЙКИ API =====
API_ID = 21160027  # Замените на ваш API ID
API_HASH = "a2abb4acd88f932b40cc3dcbad390ad9"  # Замените на ваш API Hash
PHONE_NUMBER = "+989922231769"  # Ваш номер телефона с кодом страны
session = "folder_extractor"

# ===== НАСТРОЙКИ ПРОКСИ (опционально) =====
USE_PROXY = False  # Установите True для использования прокси
PROXY = None


#     {
#     "scheme": "socks5",  # "socks5" или "http"
#     "hostname": "127.0.0.1",
#     "port": 1080,
#     "username": "",  # Оставьте пустым, если не требуется
#     "password": ""  # Оставьте пустым, если не требуется
# }


async def extract_slug_from_url(url: str) -> str:
    """Извлекает slug из ссылки addlist"""
    match = re.search(r'addlist/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    raise ValueError("Неверный формат ссылки. Ожидается формат: t.me/addlist/SLUG")


async def get_chat_link(client: Client, chat_id, chat_username=None):
    """Получает ссылку на чат (оптимизированная версия)"""
    try:
        # Если username уже известен, используем его сразу
        if chat_username:
            return f"https://t.me/{chat_username}"

        chat = await client.get_chat(chat_id)

        if chat.username:
            return f"https://t.me/{chat.username}"
        else:
            # Для приватных чатов попробуем получить invite link
            try:
                if chat.type in ["group", "supergroup", "channel"]:
                    link = await client.export_chat_invite_link(chat_id)
                    return link
            except:
                pass

            return f"Приватный чат: {chat.title} (ID: {chat_id})"
    except Exception as e:
        return f"Ошибка: {chat_id} - {str(e)}"


async def main(list_url, user_id, msg):
    # Устанавливаем обработчик исключений для подавления ошибок Pyrogram
    loop = asyncio.get_event_loop()
    old_exception_handler = loop.get_exception_handler()

    def exception_handler(loop, context):
        # Игнорируем ошибки от фоновых задач Pyrogram
        exception = context.get("exception")
        if exception and isinstance(exception, (ValueError, KeyError)):
            return
        if "Cannot operate on a closed database" in str(context.get("message", "")):
            return
        if "Peer id invalid" in str(context.get("message", "")):
            return
        # Все остальные ошибки логируем
        if old_exception_handler:
            old_exception_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(exception_handler)

    # Создание клиента с или без прокси
    if USE_PROXY:
        app = Client(
            session,
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=PHONE_NUMBER,
            proxy=PROXY
        )
    else:
        app = Client(
            session,
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=PHONE_NUMBER
        )

    try:
        await app.start()
        print("✓ Авторизация успешна\n")
    except Exception as e:
        print(f"Ошибка авторизации: {e}")
        return

    try:
        # Получение ссылки от пользователя
        addlist_url = list_url
        # input("Введите ссылку на папку (формата t.me/addlist/...): ").strip())
        slug = await extract_slug_from_url(addlist_url)

        print(f"\n→ Проверка папки со slug: {slug}")

        # Сначала получаем информацию о папке
        invite_info = await app.invoke(
            functions.chatlists.CheckChatlistInvite(
                slug=slug
            )
        )

        # Проверяем тип ответа
        if isinstance(invite_info, types.chatlists.ChatlistInviteAlready):
            # Папка уже добавлена, получаем filter_id
            print("⚠ Папка уже добавлена, используем существующую\n")
            filter_id = invite_info.filter_id

            # Получаем список чатов из уже добавленной папки
            chatlist = await app.invoke(
                functions.chatlists.GetChatlistUpdates(
                    chatlist=types.InputChatlistDialogFilter(filter_id=filter_id)
                )
            )

            # Используем чаты из GetChatlistUpdates
            chat_usernames = {}
            for chat in chatlist.chats:
                if isinstance(chat, types.Channel) and hasattr(chat, 'username') and chat.username:
                    chat_usernames[chat.id] = chat.username
                elif isinstance(chat, types.Chat):
                    chat_usernames[chat.id] = None

            chat_data = []
            for chat in chatlist.chats:
                if isinstance(chat, types.Chat):
                    chat_id = -chat.id
                    username = chat_usernames.get(chat.id)
                    chat_data.append((chat_id, username))
                elif isinstance(chat, types.Channel):
                    chat_id = -1000000000000 - chat.id
                    username = chat_usernames.get(chat.id)
                    chat_data.append((chat_id, username))
        else:
            # Папка не добавлена, добавляем её
            print(f"Найдено чатов в приглашении: {len(invite_info.peers)}\n")

            # Получаем полную информацию о чатах для access_hash
            chats_info = {}
            for chat in invite_info.chats:
                if isinstance(chat, types.Channel):
                    chats_info[chat.id] = chat.access_hash
                elif isinstance(chat, types.Chat):
                    chats_info[chat.id] = None

            # Создаём правильные InputPeer объекты
            correct_input_peers = []
            for peer in invite_info.peers:
                if isinstance(peer, types.PeerChannel):
                    access_hash = chats_info.get(peer.channel_id, 0)
                    correct_input_peers.append(types.InputPeerChannel(
                        channel_id=peer.channel_id,
                        access_hash=access_hash
                    ))
                elif isinstance(peer, types.PeerChat):
                    correct_input_peers.append(types.InputPeerChat(chat_id=peer.chat_id))

            # Добавление папки через Raw API
            result = await app.invoke(
                functions.chatlists.JoinChatlistInvite(
                    slug=slug,
                    peers=correct_input_peers
                )
            )

            print("✓ Папка успешно добавлена\n")

            # Получаем список всех папок чтобы найти filter_id добавленной папки
            dialogs_filters = await app.invoke(functions.messages.GetDialogFilters())

            # Ищем последнюю добавленную папку (она будет с типом DialogFilterChatlist)
            filter_id = None
            for f in dialogs_filters:
                if isinstance(f, types.DialogFilterChatlist):
                    filter_id = f.id
                    break

            if not filter_id:
                raise Exception("Не удалось найти ID добавленной папки")

            # Создаём словарь для быстрого доступа к username
            chat_usernames = {}
            for chat in invite_info.chats:
                if isinstance(chat, types.Channel) and hasattr(chat, 'username') and chat.username:
                    chat_usernames[chat.id] = chat.username
                elif isinstance(chat, types.Chat):
                    chat_usernames[chat.id] = None

            # Сбор всех чатов из папки
            chat_data = []
            for peer in invite_info.peers:
                if isinstance(peer, types.PeerChat):
                    chat_id = -peer.chat_id
                    username = chat_usernames.get(peer.chat_id)
                    chat_data.append((chat_id, username))
                elif isinstance(peer, types.PeerChannel):
                    chat_id = -1000000000000 - peer.channel_id
                    username = chat_usernames.get(peer.channel_id)
                    chat_data.append((chat_id, username))

        print(f"Найдено чатов в папке: {len(chat_data)}\n")
        print("=" * 60)
        keyb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_from_list")]
        ])
        # Параллельное получение ссылок для ускорения
        tasks = [get_chat_link(app, chat_id, username) for chat_id, username in chat_data]
        links = await asyncio.gather(*tasks)

        # Генерация имени файла с датой и временем
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"telegram_links_{timestamp}.txt"

        # Фильтруем только успешные ссылки (без ошибок)
        successful_links = []
        for idx, link in enumerate(links, 1):
            if not link.startswith("Ошибка"):
                successful_links.append(link)
                print(f"{idx}. {link}")
            else:
                print(f"{idx}. ⚠ {link} (пропущено)")

        # Сохранение в файл только успешных ссылок, без нумерации
        with open(filename, 'w', encoding='utf-8') as f:
            for link in successful_links:
                f.write(f"{link}\n")
        try:
            print('Отправляю документ...')

            await msg.delete()
            await bot.send_document(chat_id=int(user_id), document=FSInputFile(filename),
                                    caption='<b>📄Ссылки, которые удалось извлечь</b>\n\n'
                                            f'Удалось извлечь ссылок: <i>{len(successful_links)}</i>\n'
                                            'Здесь могут быть не все ссылки, так как возможно в папке были приватные чаты которые нельзя добавить', reply_markup=keyb
                                    )
            print('Файл успешно отправлен')

        except Exception as e:
            print(f'Ошибка: {e}')
            await msg.edit_text(text=f"Ошибка: {e}", reply_markup=keyb)
        print("=" * 60)
        print(f"✓ Сохранено ссылок: {len(successful_links)} из {len(links)}")
        print(f"✓ Файл: {filename}")

        # Выход из всех чатов папки
        print("→ Выход из чатов...")
        leave_count = 0
        for chat_id, username in chat_data:
            try:
                await app.leave_chat(chat_id)
                leave_count += 1
            except Exception as e:
                # Игнорируем ошибки выхода из чатов
                pass
        os.remove(filename)
        print(f"✓ Вышли из {leave_count} чатов")

        # Удаление папки
        print("\n→ Удаление папки...")
        await app.invoke(
            functions.chatlists.LeaveChatlist(
                chatlist=types.InputChatlistDialogFilter(filter_id=filter_id),
                peers=[]
            )
        )

        print("✓ Папка успешно удалена")

    except ValueError as e:
        print(f"Ошибка: {e}")
        try:
            await msg.edit_text(text=f"❌ Ошибка: {e}")
        except:
            pass
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        try:
            await msg.edit_text(text=f"❌ Произошла ошибка: {e}")
        except:
            pass
    finally:
        print("\n→ Завершение работы...")
        try:
            await app.stop()
            # Даём время для завершения фоновых задач
            await asyncio.sleep(1)
        except:
            pass

        # Восстанавливаем старый обработчик исключений
        try:
            loop.set_exception_handler(old_exception_handler)
        except:
            pass

# if __name__ == "__main__":
#     asyncio.run(main())