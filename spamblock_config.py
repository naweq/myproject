# ==========================================
# ФАЙЛ: spamblock_config.py
# ОПИСАНИЕ: Менеджер настроек автоснятия спамблока
# Хранение: users/{user_id}/spamblock_config.json
# ==========================================

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# ЗАГОТОВЛЕННЫЕ ТЕКСТЫ АПЕЛЛЯЦИИ
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_APPEAL_TEMPLATES = [
    {
        "id": "default_ru",
        "name": "Стандартный (RU)",
        "text": (
            "Здравствуйте! Я обнаружил, что мой аккаунт получил ограничения. "
            "Я использую Telegram исключительно в личных целях и не нарушал правила сервиса. "
            "Прошу снять ограничения с моего аккаунта. Спасибо."
        ),
        "builtin": True,
    },
    {
        "id": "default_business",
        "name": "Бизнес (RU)",
        "text": (
            "Добрый день! Мой аккаунт получил ограничения. "
            "Я веду легитимную деловую переписку с клиентами. "
            "Все мои действия соответствуют правилам использования Telegram. "
            "Прошу пересмотреть ограничения и восстановить полный доступ к аккаунту."
        ),
        "builtin": True,
    },
    {
        "id": "default_brief",
        "name": "Краткий (RU)",
        "text": (
            "Прошу снять ограничения. Я не нарушал правила Telegram и "
            "использую аккаунт для личного общения."
        ),
        "builtin": True,
    },
]

# Словарь: код страны → код языка (ISO 639-1)
PHONE_COUNTRY_LANG: Dict[str, str] = {
    # СНГ
    "7":   "ru",   # Россия, Казахстан
    "380": "uk",   # Украина
    "375": "be",   # Беларусь
    "374": "hy",   # Армения
    "994": "az",   # Азербайджан
    "995": "ka",   # Грузия
    "998": "uz",   # Узбекистан
    "992": "tg",   # Таджикистан
    "993": "tk",   # Туркменистан
    "996": "ky",   # Кыргызстан
    "373": "ro",   # Молдова
    # Европа
    "1":   "en",   # США, Канада
    "44":  "en",   # Великобритания
    "49":  "de",   # Германия
    "33":  "fr",   # Франция
    "34":  "es",   # Испания
    "39":  "it",   # Италия
    "31":  "nl",   # Нидерланды
    "48":  "pl",   # Польша
    "90":  "tr",   # Турция
    "30":  "el",   # Греция
    "36":  "hu",   # Венгрия
    "40":  "ro",   # Румыния
    "45":  "da",   # Дания
    "46":  "sv",   # Швеция
    "47":  "no",   # Норвегия
    "358": "fi",   # Финляндия
    "420": "cs",   # Чехия
    "421": "sk",   # Словакия
    "386": "sl",   # Словения
    "385": "hr",   # Хорватия
    "381": "sr",   # Сербия
    # Азия
    "86":  "zh",   # Китай
    "81":  "ja",   # Япония
    "82":  "ko",   # Корея
    "91":  "hi",   # Индия
    "92":  "ur",   # Пакистан
    "966": "ar",   # Саудовская Аравия
    "971": "ar",   # ОАЭ
    "972": "he",   # Израиль
    "62":  "id",   # Индонезия
    "60":  "ms",   # Малайзия
    "66":  "th",   # Таиланд
    "84":  "vi",   # Вьетнам
    "63":  "tl",   # Филиппины
    # Другие
    "55":  "pt",   # Бразилия
    "351": "pt",   # Португалия
    "52":  "es",   # Мексика
    "54":  "es",   # Аргентина
    "57":  "es",   # Колумбия
    "20":  "ar",   # Египет
    "234": "en",   # Нигерия
    "27":  "af",   # ЮАР
    "254": "sw",   # Кения
}

# Имена языков для UI
LANG_NAMES: Dict[str, str] = {
    "ru": "Русский", "uk": "Украинский", "be": "Белорусский",
    "en": "Английский", "de": "Немецкий", "fr": "Французский",
    "es": "Испанский", "it": "Итальянский", "tr": "Турецкий",
    "zh": "Китайский", "ja": "Японский", "ko": "Корейский",
    "ar": "Арабский", "hi": "Хинди", "pt": "Португальский",
    "pl": "Польский", "nl": "Нидерландский", "sv": "Шведский",
    "da": "Датский", "no": "Норвежский", "fi": "Финский",
    "cs": "Чешский", "sk": "Словацкий", "hu": "Венгерский",
    "ro": "Румынский", "hr": "Хорватский", "sr": "Сербский",
    "el": "Греческий", "he": "Иврит", "az": "Азербайджанский",
    "ka": "Грузинский", "hy": "Армянский", "uz": "Узбекский",
    "tg": "Таджикский", "tk": "Туркменский", "ky": "Кыргызский",
    "id": "Индонезийский", "ms": "Малайский", "th": "Тайский",
    "vi": "Вьетнамский", "tl": "Тагальский", "af": "Африкаанс",
    "sw": "Суахили",
}


def get_lang_for_phone(phone: str) -> str:
    """Определить язык по номеру телефона. Возвращает код языка (напр. 'ru')."""
    digits = phone.lstrip('+').replace(' ', '').replace('-', '')

    # Проверяем от длинного кода к короткому (3 → 2 → 1)
    for length in (3, 2, 1):
        prefix = digits[:length]
        if prefix in PHONE_COUNTRY_LANG:
            return PHONE_COUNTRY_LANG[prefix]

    return "en"  # по умолчанию английский


# ──────────────────────────────────────────────────────────────────────────────
# КОНФИГУРАЦИОННЫЙ КЛАСС
# ──────────────────────────────────────────────────────────────────────────────

class SpamBlockConfig:
    """
    Настройки автоснятия спамблока для одного пользователя бота.

    JSON-структура (users/{user_id}/spamblock_config.json):
    {
        "enabled": bool,                # включено ли автоснятие
        "premium_retry_wait": int,      # секунды ожидания перед повтором (для premium-аккаунтов)
        "premium_retry_wait_max": int,  # верхняя граница диапазона ожидания
        "auto_translate": bool,         # переводить апелляцию на язык страны аккаунта
        "active_template_id": str,      # ID активного шаблона апелляции
        "custom_templates": [           # пользовательские шаблоны
            {"id": str, "name": str, "text": str, "builtin": false}
        ]
    }
    """

    DEFAULTS: Dict[str, Any] = {
        "enabled": False,
        "premium_retry_wait": 180,      # 3 минуты
        "premium_retry_wait_max": 240,  # 4 минуты
        "auto_translate": True,
        "active_template_id": "default_ru",
        "custom_templates": [],
    }

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._path = Path(f"users/{user_id}/spamblock_config.json")
        self._data: Dict[str, Any] = {}
        self._load()

    # ── Персистентность ──────────────────────────────────────────────────────

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"[SpamBlockConfig] Ошибка чтения конфига {self._path}: {e}")
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"[SpamBlockConfig] Ошибка записи конфига {self._path}: {e}")

    def _get(self, key: str) -> Any:
        return self._data.get(key, self.DEFAULTS[key])

    def _set(self, key: str, value: Any):
        self._data[key] = value
        self._save()

    # ── Свойства ─────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._get("enabled"))

    @enabled.setter
    def enabled(self, value: bool):
        self._set("enabled", value)

    @property
    def premium_retry_wait(self) -> int:
        return int(self._get("premium_retry_wait"))

    @premium_retry_wait.setter
    def premium_retry_wait(self, value: int):
        self._set("premium_retry_wait", max(60, min(600, value)))

    @property
    def premium_retry_wait_max(self) -> int:
        return int(self._get("premium_retry_wait_max"))

    @premium_retry_wait_max.setter
    def premium_retry_wait_max(self, value: int):
        self._set("premium_retry_wait_max", max(self.premium_retry_wait, min(600, value)))

    @property
    def auto_translate(self) -> bool:
        return bool(self._get("auto_translate"))

    @auto_translate.setter
    def auto_translate(self, value: bool):
        self._set("auto_translate", value)

    @property
    def active_template_id(self) -> str:
        return str(self._get("active_template_id"))

    @active_template_id.setter
    def active_template_id(self, value: str):
        self._set("active_template_id", value)

    # ── Шаблоны ──────────────────────────────────────────────────────────────

    def get_all_templates(self) -> List[Dict]:
        """Все доступные шаблоны: встроенные + пользовательские."""
        custom = self._get("custom_templates")
        return DEFAULT_APPEAL_TEMPLATES + custom

    def get_template(self, template_id: str) -> Optional[Dict]:
        for t in self.get_all_templates():
            if t["id"] == template_id:
                return t
        return None

    def get_active_template(self) -> Optional[Dict]:
        return self.get_template(self.active_template_id)

    def add_custom_template(self, name: str, text: str) -> str:
        """Добавить пользовательский шаблон. Возвращает его ID."""
        import time
        template_id = f"custom_{int(time.time())}"
        custom = list(self._get("custom_templates"))
        custom.append({
            "id": template_id,
            "name": name,
            "text": text,
            "builtin": False,
        })
        self._set("custom_templates", custom)
        return template_id

    def delete_custom_template(self, template_id: str) -> bool:
        """Удалить пользовательский шаблон. Возвращает True если удалён."""
        custom = list(self._get("custom_templates"))
        before = len(custom)
        custom = [t for t in custom if t["id"] != template_id]
        if len(custom) < before:
            self._set("custom_templates", custom)
            # Если удалили активный — сбросить на дефолт
            if self.active_template_id == template_id:
                self.active_template_id = "default_ru"
            return True
        return False

    def update_custom_template(self, template_id: str, name: str = None, text: str = None) -> bool:
        """Изменить имя или текст пользовательского шаблона."""
        custom = list(self._get("custom_templates"))
        for t in custom:
            if t["id"] == template_id:
                if name is not None:
                    t["name"] = name
                if text is not None:
                    t["text"] = text
                self._set("custom_templates", custom)
                return True
        return False

    def to_summary_dict(self) -> Dict[str, Any]:
        """Возвращает словарь с текущими настройками для отображения."""
        tpl = self.get_active_template()
        return {
            "enabled": self.enabled,
            "premium_retry_wait": self.premium_retry_wait,
            "premium_retry_wait_max": self.premium_retry_wait_max,
            "auto_translate": self.auto_translate,
            "active_template_id": self.active_template_id,
            "active_template_name": tpl["name"] if tpl else "—",
            "custom_templates_count": len(self._get("custom_templates")),
        }


# ──────────────────────────────────────────────────────────────────────────────
# КЭШ КОНФИГОВ (по user_id)
# ──────────────────────────────────────────────────────────────────────────────

_config_cache: Dict[int, SpamBlockConfig] = {}


def get_spamblock_config(user_id: int) -> SpamBlockConfig:
    """Получить конфиг автоснятия спамблока (с кэшированием)."""
    if user_id not in _config_cache:
        _config_cache[user_id] = SpamBlockConfig(user_id)
    return _config_cache[user_id]


def reload_spamblock_config(user_id: int) -> SpamBlockConfig:
    """Перезагрузить конфиг с диска (после изменений)."""
    cfg = SpamBlockConfig(user_id)
    _config_cache[user_id] = cfg
    return cfg