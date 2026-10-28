"""Общие помощники для мостов Electron <-> Python-движок генератора.

Пути к движку приходят через переменные окружения (их задаёт Electron из настроек):
  REELS_TG_ROOT    — корень движка (внутри должен быть reels_gen/)
  REELS_VK_BOT     — папка профилей YouTube (если используется)
  REELS_YDA_ROOT   — youtube-daily-agent (если используется)
  REELS_YT_COOKIES — доп. данные профилей (если используются)

Протокол: каждая строка stdout — JSON-объект с полем "type":
  log    {"type":"log","message":"..."}
  ready  {"type":"ready", ...}
  result {"type":"result","data":...}
  error  {"type":"error","message":"..."}
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def fix_stdio() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def emit(obj: dict) -> None:
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def log(message: str) -> None:
    emit({"type": "log", "message": str(message)})


def fail(message: str, *, code: int = 1) -> int:
    emit({"type": "error", "message": str(message)})
    return code


def result(data) -> None:
    emit({"type": "result", "data": data})


def env_path(key: str) -> Path | None:
    raw = str(os.environ.get(key) or "").strip().strip('"')
    if not raw:
        return None
    return Path(raw).expanduser()


def tg_root() -> Path:
    path = env_path("REELS_TG_ROOT")
    if path is None or not path.is_dir():
        raise FileNotFoundError(f"Папка движка не найдена: {path or '(не задана)'}")
    if not (path / "reels_gen").is_dir():
        raise FileNotFoundError(f"В движке нет reels_gen: {path}")
    return path


def yt_cookies() -> Path | None:
    path = env_path("REELS_YT_COOKIES")
    if path is None:
        path = tg_root() / "YT-COOKIES"
    return path if path.is_dir() else None


def yda_root() -> str:
    path = env_path("REELS_YDA_ROOT")
    return str(path) if path else ""


def vk_bot() -> Path | None:
    path = env_path("REELS_VK_BOT")
    return path if path and path.is_dir() else None


def _add_sys_path(path: Path) -> None:
    text = str(path.resolve())
    if text not in sys.path:
        sys.path.insert(0, text)


def setup_engine_paths() -> None:
    """Подключает reels_gen и дополнительные пути профилей к sys.path."""
    root = tg_root()
    _add_sys_path(root)
    _add_sys_path(root / "reels_gen")
    cookies = yt_cookies()
    if cookies is not None:
        _add_sys_path(cookies)

    try:
        import plain_profiles  # noqa: WPS433
    except ImportError:
        plain_profiles = None  # type: ignore[assignment]

    forced_vk_bot = vk_bot()
    if plain_profiles is not None and forced_vk_bot is not None:
        plain_profiles.read_vk_bot_dir = lambda *_a, **_k: forced_vk_bot  # type: ignore[assignment]

    try:
        import yt_plain_launch  # noqa: WPS433

        yt_plain_launch.TG_ROOT = root
        if cookies is not None:
            yt_plain_launch.YT_COOKIES = cookies
    except Exception:
        pass


def run_main(fn) -> None:
    fix_stdio()
    try:
        code = fn()
    except SystemExit as exc:  # argparse
        code = int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        code = fail(str(exc))
    sys.exit(int(code or 0))
