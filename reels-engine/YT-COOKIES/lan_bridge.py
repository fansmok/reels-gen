"""LAN-мост через второй ПК/Mac: чтение .lan_bridge и отправка прокси на --dynamic."""

from __future__ import annotations

import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DEFAULT_CONTROL_PORT = 8767


def proxy_upstream_line(proxy: dict) -> str:
    server = str(proxy.get("server", "")).strip()
    if "://" not in server:
        server = f"http://{server}"
    parsed = urlparse(server)
    host = parsed.hostname or ""
    try:
        port = parsed.port or 80
    except ValueError as e:
        raise ValueError(str(e)) from e
    if not host or not (1 <= int(port) <= 65535):
        raise ValueError("Port out of range 0-65535")
    user = str(proxy.get("username", ""))
    password = str(proxy.get("password", ""))
    return f"{host}:{port}:{user}:{password}"


def read_lan_bridge_config() -> tuple[str, int]:
    path = ROOT / ".lan_bridge"
    url = ""
    control = DEFAULT_CONTROL_PORT
    env_ctrl = os.environ.get("YT_LAN_BRIDGE_CONTROL", "").strip()
    if env_ctrl.isdigit():
        control = int(env_ctrl)
    env_url = os.environ.get("YT_LAN_BRIDGE", "").strip()
    if env_url:
        url = env_url if "://" in env_url else f"http://{env_url}"
    if not path.is_file():
        return url, control
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not url:
            url = line if "://" in line else f"http://{line}"
        elif line.isdigit():
            control = int(line)
    return url, control


def resolve_lan_bridge_url(cli_bridge: str = "") -> str:
    manual = cli_bridge.strip()
    if manual:
        return manual if "://" in manual else f"http://{manual}"
    url, _ = read_lan_bridge_config()
    return url


def control_port(cli_bridge: str = "") -> int:
    env = os.environ.get("YT_LAN_BRIDGE_CONTROL", "").strip()
    if env.isdigit():
        return int(env)
    _, from_file = read_lan_bridge_config()
    return from_file


def push_upstream(bridge_url: str, proxy: dict, *, control_port: int = DEFAULT_CONTROL_PORT) -> bool:
    parsed = urlparse(bridge_url if "://" in bridge_url else f"http://{bridge_url}")
    host = parsed.hostname or ""
    if not host:
        return False
    url = f"http://{host}:{control_port}/upstream"
    try:
        req = urllib.request.Request(
            url,
            data=proxy_upstream_line(proxy).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status in (200, 204)
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def bridge_reachable(bridge_url: str, timeout: float = 2.0) -> bool:
    """TCP-проверка IPv4. Control 8767 может быть жив, пока 8765 занят очередью Chrome."""
    parsed = urlparse(bridge_url if "://" in bridge_url else f"http://{bridge_url}")
    host = parsed.hostname or ""
    port = parsed.port or 8765
    if not host:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def wait_bridge_reachable(
    bridge_url: str,
    *,
    attempts: int = 12,
    timeout: float = 1.2,
    pause: float = 0.4,
    log=None,
) -> bool:
    """Повторять TCP-проверку: очередь accept на 8765 часто заполнена Chrome CONNECT."""
    total = max(1, int(attempts))
    for i in range(1, total + 1):
        if bridge_reachable(bridge_url, timeout=timeout):
            return True
        if i < total:
            if i == 1 and log:
                log(f"  · Мост {bridge_url} пока не принимает соединения, жду…")
            time.sleep(max(0.05, float(pause)))
    return False


def prepare_mac_bridge(bridge_url: str, proxy: dict) -> bool:
    """Отправить прокси на мост и проверить, что мост отвечает."""
    ctrl = control_port()
    pushed = False
    for i in range(1, 6):
        if push_upstream(bridge_url, proxy, control_port=ctrl):
            pushed = True
            break
        if i == 1:
            print("  · Не сразу передал прокси на мост, повторяю…")
        time.sleep(0.5)
    if not pushed:
        print("  ✗ Не удалось передать прокси на мост")
        print("    На втором ПК:  python proxy_lan_bridge.py")
        return False
    if not wait_bridge_reachable(bridge_url, attempts=12, timeout=1.2, pause=0.4, log=print):
        print(f"  ✗ Мост не отвечает на {bridge_url}")
        print("    На втором ПК:  python proxy_lan_bridge.py")
        return False
    parsed = urlparse(bridge_url)
    print(f"  ✓ LAN-мост {parsed.hostname}:{parsed.port or 8765}")
    return True


def print_mac_bridge_help() -> None:
    print()
    print("=== Нужен LAN-мост (второй ПК) или v2rayN на этом ПК ===")
    print("  Вариант А (один ПК): запустите v2rayN (SOCKS5 127.0.0.1:10808) — мост не нужен,")
    print("     relay сам пойдёт к прокси через него.")
    print("  Вариант Б (второй ПК):")
    print("  1) Второй ПК в той же Wi-Fi:  python proxy_lan_bridge.py")
    print("  2) Windows — файл .lan_bridge:")
    print("       http://192.168.1.69:8765")
    print("  3)  run.bat имя_аккаунта")
    print()
