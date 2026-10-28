"""Обычные Chrome-профили YouTube из экосистемы youtube-daily-agent.

Профили живут в vk_bot (`profiles_youtube_plain*`), на них смотрят оба агента.
Сюда ничего не копируем — список всегда читается с диска daily-агента.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

DEFAULT_YDA_ROOT = Path(__file__).resolve().parent
KIND_PLAIN = "plain"
KIND_COOKIES = "cookies"
PLAIN_MARKER = ".yt_plain.json"
_PROFILE_RE = re.compile(r"^profiles_youtube_plain(?:_(\d+))?$", re.I)
_CHANNEL_LABELS = (
    ("classic_mini", "MINI"),
    ("prognoz", "PROGNOZ"),
    ("reels", "REELS"),
)


def default_yda_root() -> Path:
    return DEFAULT_YDA_ROOT


def resolve_yda_root(raw: str | Path | None = None) -> Path:
    text = str(raw or "").strip()
    path = Path(text) if text else DEFAULT_YDA_ROOT
    return path.expanduser()


def _strip_yaml_scalar(raw: str) -> str:
    value = str(raw or "").strip()
    if value[:1] in {"'", '"'} and value[-1:] == value[:1] and len(value) >= 2:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value.strip()


def read_vk_bot_dir(yda_root: str | Path | None = None) -> Path:
    """Папка vk_bot из config.yaml daily-агента — там лежат profiles_youtube_plain*."""
    root = resolve_yda_root(yda_root)
    config_path = root / "config.yaml"
    vk_bot = None
    if config_path.is_file():
        in_paths = False
        try:
            text = config_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        for line in text.splitlines():
            if re.match(r"^paths:\s*$", line):
                in_paths = True
                continue
            if in_paths:
                if line and not line[:1].isspace() and not line.startswith("#"):
                    break
                m = re.match(r"^\s+vk_bot:\s*(.+)$", line)
                if m:
                    vk_bot = Path(_strip_yaml_scalar(m.group(1)))
                    break
    if vk_bot and str(vk_bot).strip():
        return vk_bot
    sibling = root.parent / "vk_multi_packV2"
    if sibling.is_dir():
        return sibling
    return Path(__file__).resolve().parent / 'profiles'
def profile_folder_name(number: int) -> str:
    n = int(number)
    if n < 1:
        raise ValueError("Номер профиля должен быть >= 1")
    if n == 1:
        return "profiles_youtube_plain"
    return f"profiles_youtube_plain_{n}"


def profile_number_from_name(name: str) -> int | None:
    m = _PROFILE_RE.match(str(name or ""))
    if not m:
        return None
    raw = m.group(1)
    return 1 if raw is None else int(raw)


def profile_dir(number: int, yda_root: str | Path | None = None) -> Path:
    return read_vk_bot_dir(yda_root) / profile_folder_name(number)


def is_plain_profile(path: str | Path | None) -> bool:
    if not path:
        return False
    folder = Path(path)
    if profile_number_from_name(folder.name) is None:
        return False
    if (folder / PLAIN_MARKER).is_file():
        return True
    if (folder / "ACCOUNT_NUMBER.txt").is_file():
        return True
    # Живой Chrome user-data daily-агента.
    return (folder / "Default").is_dir() or folder.is_dir()


def discover_numbers(yda_root: str | Path | None = None) -> list[int]:
    vk_bot = read_vk_bot_dir(yda_root)
    if not vk_bot.is_dir():
        return []
    found: set[int] = set()
    try:
        children = list(vk_bot.iterdir())
    except OSError:
        return []
    for item in children:
        if not item.is_dir():
            continue
        number = profile_number_from_name(item.name)
        if number is not None:
            found.add(number)
    return sorted(found)


def bound_channel_labels(number: int, yda_root: str | Path | None = None) -> list[str]:
    """Какие каналы daily-агента сидят на этом номере (MINI / PROGNOZ / REELS)."""
    root = resolve_yda_root(yda_root)
    config_path = root / "config.yaml"
    if not config_path.is_file():
        return []
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    current = ""
    in_channels = False
    bound: list[str] = []
    wanted = {key: label for key, label in _CHANNEL_LABELS}
    for line in text.splitlines():
        if re.match(r"^channels:\s*$", line):
            in_channels = True
            current = ""
            continue
        if in_channels:
            if line and not line[:1].isspace() and not line.startswith("#"):
                break
            m_key = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*$", line)
            if m_key:
                current = m_key.group(1)
                continue
            m_acc = re.match(r"^\s+youtube_acc:\s*(\d+)\s*$", line)
            if m_acc and current in wanted:
                try:
                    selected = int(m_acc.group(1))
                except Exception:
                    selected = 0
                if selected == int(number):
                    bound.append(wanted[current])
    return bound


def find_google_chrome() -> Path:
    candidates: list[str] = []
    for env_key in ("YOUTUBE_CHROME_PATH", "CHROME_PATH", "GOOGLE_CHROME_BIN"):
        raw = str(os.environ.get(env_key) or "").strip().strip('"')
        if raw:
            candidates.append(raw)
    if os.name == "nt":
        candidates.extend(
            [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
        )
    else:
        candidates.extend(["google-chrome", "google-chrome-stable"])
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return path
    raise FileNotFoundError("Google Chrome не найден — нужен именно он для обычных профилей")


def create_profile(yda_root: str | Path | None = None) -> tuple[int, Path]:
    """Следующий номер без дыр: max(существующие)+1, как в youtube-daily-agent."""
    numbers = discover_numbers(yda_root)
    number = max(numbers, default=0) + 1
    profile = profile_dir(number, yda_root)
    profile.mkdir(parents=True, exist_ok=False)
    (profile / "ACCOUNT_NUMBER.txt").write_text(
        f"YouTube Daily Agent account #{number}\n"
        "Эта папка создана автоматически. Не переименовывайте её.\n",
        encoding="utf-8",
    )
    (profile / PLAIN_MARKER).write_text(
        json.dumps(
            {
                "kind": KIND_PLAIN,
                "number": number,
                "source": "youtube-daily-agent",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return number, profile


def delete_profile(number: int, yda_root: str | Path | None = None) -> Path:
    n = int(number)
    bound = bound_channel_labels(n, yda_root)
    if bound:
        raise RuntimeError(
            f"Профиль #{n} привязан в youtube-daily-agent к {' и '.join(bound)}. "
            "Сначала назначьте другой аккаунт в Tray daily-агента."
        )
    profile = profile_dir(n, yda_root)
    if not profile.is_dir():
        raise FileNotFoundError(f"Профиль аккаунта #{n} не найден")
    if _profile_lock_present(profile):
        raise RuntimeError(
            f"Профиль #{n} сейчас открыт в Chrome. Закройте окно и повторите удаление."
        )
    import shutil

    shutil.rmtree(profile)
    return profile


def _profile_lock_present(profile: Path) -> bool:
    lock = profile / "SingletonLock"
    try:
        return lock.exists()
    except Exception:
        return False


def open_chrome_login(
    profile: Path,
    url: str = "https://www.youtube.com/",
    extra_args: list[str] | None = None,
) -> int:
    """Открывает установленный Google Chrome с этим user-data. Playwright не трогает."""
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    chrome = find_google_chrome()
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    cmd = [
        str(chrome),
        f"--user-data-dir={profile.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=ru-RU",
    ]
    for arg in extra_args or []:
        if str(arg).strip():
            cmd.append(str(arg))
    cmd.append(url)
    proc = subprocess.Popen(
        cmd,
        cwd=str(profile.parent),
        close_fds=True,
        creationflags=creationflags,
    )
    return int(proc.pid)


def _account_ctime(path: Path) -> tuple[float, str]:
    try:
        ctime = path.stat().st_ctime
        return ctime, datetime.fromtimestamp(ctime).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return 0.0, ""


def read_plain_account(profile: Path, number: int) -> dict:
    ctime, added = _account_ctime(profile)
    return {
        "kind": KIND_PLAIN,
        "kind_label": "Профиль",
        "number": int(number),
        "name": f"YouTube #{int(number)}",
        "default_name": f"YouTube #{int(number)}",
        "path": str(profile),
        "email": "",
        "channel": "youtube-daily-agent",
        "subscribers": "",
        "views": "",
        "registration": "",
        "ip": "",
        "country": "",
        "city": "",
        "isp": "",
        "date_added": added,
        "date_added_ts": ctime,
        "last_opened": "",
        "proxy_status": "Нет",
        "proxy_status_detail": "Прокси не сохранён",
        "bound": [],
    }


def scan_plain_accounts(yda_root: str | Path | None = None) -> list[dict]:
    root = resolve_yda_root(yda_root)
    accounts: list[dict] = []
    for number in discover_numbers(root):
        folder = profile_dir(number, root)
        if not folder.is_dir():
            continue
        acc = read_plain_account(folder, number)
        acc["bound"] = bound_channel_labels(number, root)
        if acc["bound"]:
            acc["channel"] = " · ".join(acc["bound"])
        accounts.append(acc)
    accounts.sort(key=lambda a: int(a.get("number") or 0))
    return accounts


def selected_is_plain(acc: dict | None) -> bool:
    if not acc:
        return False
    if acc.get("kind") == KIND_PLAIN:
        return True
    return is_plain_profile(acc.get("path"))
