# ==========================================
# ФАЙЛ: config.py
# ОПИСАНИЕ: Конфигурация бота
# ==========================================
import json
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ─────────────────────────────────────────
# ТОКЕНЫ И КЛЮЧИ
# ─────────────────────────────────────────

# TOKEN = '8563206991:AAHwmGDuglTywleV6Rr4j0csrn0GMD10Pt0'
TOKEN = "8359360061:AAFjRpM_AEqE9ck248QQRyVXk8zddQTbV74"  # Главный бот
#TOKEN = "7724530575:AAHGD2YcNGIz7oBGZ66gVjz4yIu7JkyEer8"

# Токен CryptoBot
CRYPTO_TOKEN = "521332:AAe8rpN9gmaGEiAsmm2fIxCwUdWNtyb6y5S"

# ─────────────────────────────────────────
# API-ПАРЫ HYDROGRAM
# ─────────────────────────────────────────

API_PAIRS = [
    {"api_id": 39570078, "api_hash": "85ceca89723bc96e921e5ae0ef8477d8"},
    {"api_id": 32893035, "api_hash": "593a972d31a2ed96c00734596a6798be"},
]

# ─────────────────────────────────────────
# ДИРЕКТОРИИ
# ─────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"        # <-- все JSON-настройки сюда
SESSIONS_DIR = BASE_DIR / "users"
TEMP_DIR    = BASE_DIR / "temp"
LOGS_DIR    = BASE_DIR / "logs"
DOWNLOADS_DIR = BASE_DIR / "downloads"

# Создаём директории при старте
for _d in (DATA_DIR, SESSIONS_DIR, TEMP_DIR, LOGS_DIR, DOWNLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────
# ПУТИ К JSON-ФАЙЛАМ (все в data/)
# ─────────────────────────────────────────

ADMINS_FILE          = DATA_DIR / "admins.json"
DATABASE_PATH        = DATA_DIR / "users_data.json"
PROMO_FILE           = DATA_DIR / "promo.json"
SELECTED_ACCS_FILE   = DATA_DIR / "selected_accounts.json"   # выбранные аккаунты
USER_DELAYS_FILE     = DATA_DIR / "user_delays.json"          # задержки пользователей

# Для core.py (сессионные настройки и API)
session_settings = str(DATA_DIR / "session_settings.json")
api_settings     = str(DATA_DIR / "api_settings.json")
current_api      = str(DATA_DIR / "current_api.json")

# ─────────────────────────────────────────
# НАСТРОЙКИ КАНАЛА
# ─────────────────────────────────────────

CHANNEL_ID   = "@senders_channel"
CHANNEL_LINK = "https://t.me/senders_channel"
user_confirm = "https://telegra.ph/Polzovatelskoe-soglashenie-12-28-15"

# ─────────────────────────────────────────
# ПОДПИСКИ
# ─────────────────────────────────────────

SUBSCRIPTION_PRICES = {
    "test":    {"days": 1,     "stars": 0},
    "3_days":  {"days": 3,     "stars": 25},
    "week":    {"days": 7,     "stars": 50},
    "month":   {"days": 30,    "stars": 100},
    "forever": {"days": 36500, "stars": 150},
}
OFFER_LINKS = {
    "3_days": "https://funpay.com/lots/offer?id=64563427",
    "week": "https://funpay.com/lots/offer?id=64563591",
    "month": "https://funpay.com/lots/offer?id=64563653",
    "forever": "https://funpay.com/lots/offer?id=64563710"

}
# ─────────────────────────────────────────
# ЛИМИТЫ И ЗАДЕРЖКИ
# ─────────────────────────────────────────

DEFAULT_MESSAGE_DELAY  = 10   # секунд между сообщениями
DEFAULT_CYCLE_DELAY    = 300  # секунд между циклами
MAX_PARALLEL_ACCOUNTS  = 5    # максимум одновременных аккаунтов
MAX_ACCOUNTS_PER_USER  = 1000
MAX_ZIP_SIZE_MB        = 10

# ─────────────────────────────────────────
# АДМИНИСТРАТОРЫ
# ─────────────────────────────────────────

def _init_admins_file():
    if not ADMINS_FILE.exists():
        ADMINS_FILE.write_text(
            json.dumps({"admins": ["8142259218", "8251022893"]}, indent=2),
            encoding="utf-8"
        )

_init_admins_file()


def get_admins() -> list[int]:
    try:
        data = json.loads(ADMINS_FILE.read_text(encoding="utf-8"))
        return [int(uid) for uid in data.get("admins", [])]
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def add_admins(user_id: int) -> bool:
    global ADMIN_IDS
    uid_str = str(user_id)
    try:
        data = json.loads(ADMINS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {"admins": []}

    if uid_str not in data["admins"]:
        data["admins"].append(uid_str)
        ADMINS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✅ Добавлен админ {uid_str}")
        ADMIN_IDS = get_admins()
        return True

    print(f"ℹ️ Админ {uid_str} уже в списке!")
    return False


ADMIN_IDS       = get_admins()
ADMIN_NOTIFY_ID = ADMIN_IDS[0] if ADMIN_IDS else None

# ─────────────────────────────────────────
# БОТ
# ─────────────────────────────────────────

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# ─────────────────────────────────────────
# ПРОКСИ
# ─────────────────────────────────────────

PYROGRAM_PROXIES = []

TELETHON_PROXIES = [
    ('socks5', 'pool.proxys.io', 10000 + i, True, 'user329936o11597r949702', 'zemtyf')
    for i in range(350)
]
