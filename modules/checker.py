import threading
import queue
import time
import requests


from concurrent.futures import ThreadPoolExecutor, as_completed

PROXY_FILE = "proxy.txt"
MAX_RTT_MS = 2000  # Максимальный отклик
TIMEOUT = 10  # Таймаут соединения
THREADS = 50  # Количество потоков для проверки
proxy_queue = queue.Queue()
PX = []




def load_proxies():
    """Загружает прокси из файла в очередь"""
    try:
        with open(PROXY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and ':' in line:
                    proxy_queue.put(line)
        print(f"Загружено {proxy_queue.qsize()} прокси из {PROXY_FILE}")
    except FileNotFoundError:
        print(f"Файл {PROXY_FILE} не найден! TELETHON_PROXIES останется пустым.")
    except Exception as e:
        print(f"Ошибка чтения прокси: {e}")


def check_proxy(proxy_str: str):
    """Проверяет один SOCKS5 прокси пингом Google"""
    ip, port_str = proxy_str.split(':')
    port = int(port_str)

    proxy_url = f"socks5://{ip}:{port}"
    proxies = {"http": proxy_url, "https": proxy_url}

    try:
        start = time.time()
        response = requests.get("https://www.google.com", proxies=proxies, timeout=TIMEOUT)
        rtt = (time.time() - start) * 1000  # в мс

        if response.status_code == 200 and rtt <= MAX_RTT_MS:
            # Добавляем в формате для Telethon (без авторизации)
            ZX.append(('socks5', ip, port))
            print(f"[+] РАБОЧИЙ: {proxy_str} | {rtt:.0f} мс")
            return True
    except Exception:
        pass  # Тихо пропускаем мёртвые

    print(f"[-] МЁРТВЫЙ: {proxy_str}")
    return False


def check_all_proxies():
    """Запускает проверку всех прокси при старте бота"""
    global ZX
    ZX = []  # Очищаем на всякий случай

    load_proxies()

    if proxy_queue.empty():
        print("Нет прокси для проверки.")
        return

    print(f"Начинаю проверку прокси (макс. отклик {MAX_RTT_MS} мс)...\n")
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(check_proxy, proxy_queue.get()) for _ in range(proxy_queue.qsize())]
        for future in as_completed(futures):
            future.result()  # Ждём завершения

    elapsed = round(time.time() - start_time, 2)
    print(f"\nГотово за {elapsed} сек! Рабочих прокси: {len(ZX)}")

    if ZX:
        print("TELETHON_PROXIES заполнен:")
        for p in ZX:
            print(f"    {p},")
    else:
        print("Ни одного рабочего прокси не найдено.")
