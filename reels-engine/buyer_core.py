"""Минимальные помощники для профилей Chrome (без кабинета закупки)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def hidden_subprocess_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def find_python_for_playwright() -> str | None:
    return sys.executable


def is_yt_cookies_log_useful(line: str) -> bool:
    return bool(str(line or "").strip())


def _get_yt_cookies_python() -> str | None:
    return sys.executable


def _read_lan_bridge_config(yt_cookies_dir: str):
    path = Path(yt_cookies_dir) / ".lan_bridge"
    if not path.is_file():
        return "", 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", 0
    url = ""
    port = 0
    for line in text.splitlines():
        if line.startswith("url="):
            url = line.split("=", 1)[1].strip()
        if line.startswith("control="):
            try:
                port = int(line.split("=", 1)[1].strip())
            except ValueError:
                port = 0
    return url, port


def _write_lan_bridge(yt_cookies_dir, bridge_url, control_port, status_callback=None):
    path = Path(yt_cookies_dir) / ".lan_bridge"
    path.write_text(f"url={bridge_url}\ncontrol={control_port}\n", encoding="utf-8")


def _is_local_bridge(url: str) -> bool:
    u = (url or "").lower()
    return "127.0.0.1" in u or "localhost" in u


def _check_bridge(host: str, port: int, timeout: float = 0.5) -> bool:
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_bridge(host: str, port: int, timeout: float = 5.0) -> bool:
    import time

    end = time.time() + timeout
    while time.time() < end:
        if _check_bridge(host, port, timeout=0.3):
            return True
        time.sleep(0.2)
    return False


def _start_yt_cookies_bridge(yt_cookies_dir: str, status_callback=None) -> None:
    if status_callback:
        status_callback("Локальный bridge не настроен — пропускаю")


def _push_proxy_to_bridge(*_a, **_k) -> bool:
    return False


def run_cliproxy_with_relogin(*_a, **_k):
    raise RuntimeError("Подбор прокси через внешний кабинет в этой сборке недоступен. Укажите прокси вручную: host:port:login:password")
