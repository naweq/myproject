# ==========================================
# ФАЙЛ: task_manager.py
# ОПИСАНИЕ: Менеджер тасков — многозадачность рассылок
# ==========================================

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    RUNNING  = "running"
    PAUSED   = "paused"
    STOPPED  = "stopped"
    FINISHED = "finished"
    ERROR    = "error"


class TaskType(Enum):
    LINKS_MAILING    = "Рассылка по ссылкам"
    CONTACTS_MAILING = "Рассылка по контактам"
    DIALOG_MAILING   = "Рассылка по диалогам"
    ONE_MAILING      = "Отправка одному"
    SMM_SUB          = "Подписка на канал"
    SMM_CHAT         = "Вступление в чат"
    SMM_VIEWS        = "Накрутка просмотров"
    SMM_REACTIONS    = "Накрутка реакций"
    SMM_VOTE         = "Голосование"
    SMM_REF          = "Реф-ссылка"
    SMM_REPLY        = "Ответ на сообщение"
    SMM_GIVEAWAY     = "Розыгрыш (кнопка)"


def _gen_task_number() -> str:
    """Генерировать красивый 6-значный ID таска"""
    return str(random.randint(100000, 999999))


@dataclass
class TaskStats:
    """Текущая статистика таска"""
    sent:    int = 0
    failed:  int = 0
    joined:  int = 0
    cycles:  int = 0
    current_account: str = ""
    last_update: float = field(default_factory=time.time)

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.last_update = time.time()


@dataclass
class AccountMeta:
    """Метаданные аккаунта для отображения"""
    session_name: str       # имя файла сессии
    full_name:    str = "Загрузка..."
    phone:        str = ""
    username:     str = ""
    user_id:      int = 0

    def link(self) -> str:
        """Вернуть ссылку на аккаунт"""
        if self.username:
            return f"https://t.me/{self.username}"
        if self.phone:
            clean = self.phone.replace("+", "").replace(" ", "")
            return f"https://t.me/+{clean}"
        return ""

    def display_name(self) -> str:
        return self.full_name or self.session_name.replace(".session", "")

    def hyperlink(self) -> str:
        """Имя аккаунта в виде гиперссылки"""
        url = self.link()
        name = self.display_name()
        if url:
            return f'<a href="{url}">{name}</a>'
        return name

    def expandable_block(self) -> str:
        """Сворачиваемая цитата с полной инфой"""
        lines = [f"👤 {self.hyperlink()}"]
        if self.user_id:
            lines.append(f"  🆔 ID: <code>{self.user_id}</code>")
        if self.phone:
            lines.append(f"  📞 Номер: <code>{self.phone}</code>")
        if self.username:
            lines.append(f"  🔗 Username: @{self.username}")
        else:
            lines.append(f"  🔗 Username: отсутствует")
        return "\n".join(lines)


@dataclass
class Task:
    """Один таск — одна рассылка"""
    task_id:      str           # Короткий 6-значный номер
    user_id:      int
    task_type:    TaskType
    accounts:     List[str]     # Имена сессий
    message_text: str = ""
    message_delay: float = 5.0
    cycle_delay:   float = 60.0
    photo_path:   Optional[str] = None

    status:       TaskStatus = TaskStatus.RUNNING
    created_at:   datetime   = field(default_factory=datetime.now)
    started_at:   float      = field(default_factory=time.time)

    stats:        TaskStats  = field(default_factory=TaskStats)
    accounts_meta: List[AccountMeta] = field(default_factory=list)

    # Управляющие события
    stop_event:   asyncio.Event = field(default_factory=asyncio.Event)
    pause_event:  asyncio.Event = field(default_factory=asyncio.Event)  # set = пауза

    asyncio_task: Optional[asyncio.Task] = None

    # Пинг (мс) — обновляется периодически
    ping_ms:      Optional[float] = None
    ping_updated_at: float = 0.0

    def stop(self):
        self.stop_event.set()
        self.pause_event.clear()
        self.status = TaskStatus.STOPPED

    def pause(self):
        self.pause_event.set()
        self.status = TaskStatus.PAUSED

    def resume(self):
        self.pause_event.clear()
        self.status = TaskStatus.RUNNING

    @property
    def is_running(self) -> bool:
        return self.status == TaskStatus.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.status == TaskStatus.PAUSED

    @property
    def is_active(self) -> bool:
        return self.status in (TaskStatus.RUNNING, TaskStatus.PAUSED)

    def elapsed(self) -> str:
        secs = int(time.time() - self.started_at)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}ч {m}м {s}с"
        if m:
            return f"{m}м {s}с"
        return f"{s}с"

    def ping_str(self) -> str:
        if self.ping_ms is None:
            return "—"
        if self.ping_ms < 100:
            icon = "🟢"
        elif self.ping_ms < 300:
            icon = "🟡"
        else:
            icon = "🔴"
        return f"{icon} {self.ping_ms:.0f} мс"

    def status_icon(self) -> str:
        icons = {
            TaskStatus.RUNNING:  "🟢 Выполняется",
            TaskStatus.PAUSED:   "⏸ Приостановлен",
            TaskStatus.STOPPED:  "🔴 Остановлен",
            TaskStatus.FINISHED: "✅ Завершён",
            TaskStatus.ERROR:    "❌ Ошибка",
        }
        return icons[self.status]

    def short_info(self) -> str:
        return (
            f"#{self.task_id} · {self.task_type.value}\n"
            f"📱 {len(self.accounts)} акк. · ⏱ {self.elapsed()} · {self.status_icon()}"
        )


class TaskManager:
    """
    Глобальный синглтон-менеджер тасков.

    Правило: один аккаунт занят только в ОДНОМ активном таске.
    Пользователь может параллельно запускать несколько тасков
    на разных аккаунтах.
    """

    _instance: Optional["TaskManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: Dict[str, Task] = {}
        self._busy_accounts: Dict[str, str] = {}   # acc_name → task_id
        self._lock = asyncio.Lock()
        logger.info("✅ TaskManager инициализирован")

    # ─────────────────────────────────────────
    # СОЗДАНИЕ / ЗАВЕРШЕНИЕ
    # ─────────────────────────────────────────

    async def try_create_task(
        self,
        user_id: int,
        task_type: TaskType,
        accounts: List[str],
        message_text: str = "",
        message_delay: float = 5.0,
        cycle_delay: float = 60.0,
        photo_path: Optional[str] = None,
    ) -> tuple[Optional[Task], List[tuple]]:
        """
        Попытаться создать таск.
        Возвращает (task, []) при успехе.
        Возвращает (None, [(acc, task_type_name, task_id), ...]) при конфликте.
        """
        async with self._lock:
            conflicts = []
            for acc in accounts:
                if acc in self._busy_accounts:
                    busy_tid = self._busy_accounts[acc]
                    busy_task = self._tasks.get(busy_tid)
                    tname = busy_task.task_type.value if busy_task else "неизвестный"
                    conflicts.append((acc, tname, busy_tid))

            if conflicts:
                return None, conflicts

            # Генерируем уникальный 6-значный номер
            while True:
                tid = _gen_task_number()
                if tid not in self._tasks:
                    break

            task = Task(
                task_id=tid,
                user_id=user_id,
                task_type=task_type,
                accounts=list(accounts),
                message_text=message_text,
                message_delay=message_delay,
                cycle_delay=cycle_delay,
                photo_path=photo_path,
            )

            self._tasks[tid] = task
            for acc in accounts:
                self._busy_accounts[acc] = tid

            logger.info(f"✅ Таск #{tid} создан | user {user_id} | {task_type.value} | {len(accounts)} акк.")
            return task, []

    async def finish_task(self, task_id: str, status: TaskStatus = TaskStatus.FINISHED):
        """Завершить таск и освободить аккаунты"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = status
            for acc in task.accounts:
                if self._busy_accounts.get(acc) == task_id:
                    del self._busy_accounts[acc]
            logger.info(f"🏁 Таск #{task_id} → {status.value}")

    async def stop_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.is_active:
            task.stop()
            await self.finish_task(task_id, TaskStatus.STOPPED)
            return True
        return False

    async def pause_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.is_running:
            task.pause()
            logger.info(f"⏸ Таск #{task_id} поставлен на паузу")
            return True
        return False

    async def resume_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.is_paused:
            task.resume()
            logger.info(f"▶️ Таск #{task_id} возобновлён")
            return True
        return False

    def update_task_params(
        self,
        task_id: str,
        message_text: Optional[str] = None,
        message_delay: Optional[float] = None,
        cycle_delay: Optional[float] = None,
    ):
        """Обновить параметры таска (текст, задержки) — для паузы с редактированием"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if message_text is not None:
            task.message_text = message_text
        if message_delay is not None:
            task.message_delay = message_delay
        if cycle_delay is not None:
            task.cycle_delay = cycle_delay
        logger.info(f"✏️ Таск #{task_id} параметры обновлены")
        return True

    # ─────────────────────────────────────────
    # ГЕТТЕРЫ
    # ─────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_user_tasks(self, user_id: int, only_active: bool = False) -> List[Task]:
        tasks = [t for t in self._tasks.values() if t.user_id == user_id]
        if only_active:
            tasks = [t for t in tasks if t.is_active]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def get_running_count(self, user_id: int) -> int:
        return len(self.get_user_tasks(user_id, only_active=True))

    def is_account_busy(self, acc: str) -> bool:
        return acc in self._busy_accounts

    def set_account_meta(self, task_id: str, meta_list: List[AccountMeta]):
        task = self._tasks.get(task_id)
        if task:
            task.accounts_meta = meta_list

    def update_ping(self, task_id: str, ping_ms: float):
        task = self._tasks.get(task_id)
        if task:
            task.ping_ms = ping_ms
            task.ping_updated_at = time.time()

    def cleanup_old_tasks(self, max_finished: int = 30):
        finished = [
            t for t in self._tasks.values()
            if t.status in (TaskStatus.FINISHED, TaskStatus.ERROR, TaskStatus.STOPPED)
        ]
        to_delete = sorted(finished, key=lambda t: t.created_at)[:-max_finished]
        for t in to_delete:
            del self._tasks[t.task_id]

    # ─────────────────────────────────────────
    # ФОРМАТИРОВАНИЕ
    # ─────────────────────────────────────────

    @staticmethod
    def format_conflict_message(conflicts: List[tuple]) -> str:
        lines = ["⚠️ <b>Аккаунты заняты в другом таске:</b>\n"]
        for acc, tname, tid in conflicts:
            lines.append(f"  • <code>{acc}</code> → <i>{tname}</i> (#{tid})")
        lines.append(
            "\n💡 <i>Дождитесь завершения или выберите свободные аккаунты.\n"
            "Просмотр тасков: /tasks</i>"
        )
        return "\n".join(lines)


# Глобальный синглтон
task_manager = TaskManager()
