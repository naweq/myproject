# ==========================================
# ФАЙЛ: main.py
# ОПИСАНИЕ: Главный файл запуска бота
# ==========================================

import asyncio
import logging
from pathlib import Path
from aiogram import Dispatcher

from config import bot
from modules.database import Database
from handlers.user_handlers import router as user_router
from handlers.inviting_handlers import router as inv_router
from handlers.admin_handlers import router as admin_router
from handlers.account_handlers import router as account_router
from modules.payment import router as payment_router
from SMM_service import router as smm_router
from handlers.task_handlers import router as task_router
from modules.text_temp import router as temp_router
from handlers.spamblock_handlers import router as spamblock_router
# ==========================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================================
from modules.payment import cryptopay
# Создаём папку для логов
Path("logs").mkdir(exist_ok=True)

# Основной логгер
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logging.getLogger("hydrogram").setLevel(logging.CRITICAL)
logging.getLogger("hydrogram.session").setLevel(logging.CRITICAL)
logging.getLogger("hydrogram.connection").setLevel(logging.CRITICAL)

# Убираем дублирование в консоль

logger = logging.getLogger(__name__)
dp = Dispatcher()

 # ← закрыть при остановке


# ==========================================
# ИНИЦИАЛИЗАЦИЯ
# ==========================================

async def main():
    """Главная функция запуска бота"""

    logger.info("🚀 Запуск бота...")

    # Создаём необходимые папки
    Path("users").mkdir(exist_ok=True)
    Path("temp").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    # Инициализация базы данных
    db = Database()
    await db.init()
    logger.info("✅ База данных инициализирована")

    # Создаём диспетчер
    dp.include_router(spamblock_router)
    # dp.include_router(folder_mailing_handlers.router)
    # Подключаем роутеры
    dp.include_router(router=temp_router)
    dp.include_router(router=task_router)
    dp.include_router(router=account_router)
    dp.include_router(router=user_router)
    dp.include_router(router=inv_router)
    dp.include_router(router=admin_router)
    dp.include_router(router=payment_router)
    dp.include_router(router=smm_router)
    # dp.include_router(router=qr_router)

    logger.info("✅ Роутеры подключены")

    # Запуск polling
    try:
        logger.info("✅ Бот запущен и работает!")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        await cryptopay.close()
        await bot.session.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔️ Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")