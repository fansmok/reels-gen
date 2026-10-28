"""Случайный полный отпечаток обычного профиля.

Не копирует information.txt из логов. Первый запуск закрепляет свой ПК
(экран, видеокарта, процессор, память, Windows, язык, координаты).
Повторный запуск тот же файл не меняет.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from account_paths import INFO_NAMES, PC_INFO_JSON

ASSIGN_FILE = ".yt_fp_assign.json"

_GPUS = (
    "NVIDIA GeForce GTX 1650",
    "NVIDIA GeForce GTX 1660 SUPER",
    "NVIDIA GeForce RTX 3060",
    "NVIDIA GeForce RTX 4060",
    "AMD Radeon RX 580",
    "AMD Radeon RX 6600",
    "Intel(R) UHD Graphics 620",
    "Intel(R) UHD Graphics 630",
    "Intel(R) Iris Xe Graphics",
)
_CPUS = (
    ("Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz", 4, 8, 8192),
    ("Intel(R) Core(TM) i5-10400 CPU @ 2.90GHz", 6, 12, 16384),
    ("Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz", 6, 12, 16384),
    ("Intel(R) Core(TM) i3-10100 CPU @ 3.60GHz", 4, 8, 8192),
    ("AMD Ryzen 5 3600 6-Core Processor", 6, 12, 16384),
    ("AMD Ryzen 5 5600X 6-Core Processor", 6, 12, 16384),
    ("AMD Ryzen 7 5800H with Radeon Graphics", 8, 16, 16384),
)
_SCREENS = (
    (1920, 1080, 100),
    (1366, 768, 100),
    (1536, 864, 125),
    (1600, 900, 100),
    (2560, 1440, 100),
    (1440, 900, 100),
    (1680, 1050, 100),
)
_GEO = (
    ("US", "en-US", "America/New_York", "New York", 40.7128, -74.0060),
    ("US", "en-US", "America/Chicago", "Chicago", 41.8781, -87.6298),
    ("GB", "en-GB", "Europe/London", "London", 51.5074, -0.1278),
    ("DE", "de-DE", "Europe/Berlin", "Berlin", 52.5200, 13.4050),
    ("PL", "pl-PL", "Europe/Warsaw", "Warsaw", 52.2297, 21.0122),
    ("RU", "ru-RU", "Europe/Moscow", "Moscow", 55.7558, 37.6173),
    ("IN", "en-IN", "Asia/Kolkata", "Mumbai", 19.0760, 72.8777),
    ("BR", "pt-BR", "America/Sao_Paulo", "Sao Paulo", -23.5505, -46.6333),
)
_WINDOWS = (
    ("Windows 10 Pro Build 19045", "10.0.19045"),
    ("Windows 11 Pro Build 22631", "10.0.22631"),
    ("Windows 10 Home Build 19045", "10.0.19045"),
    ("Windows 11 Home Build 22631", "10.0.22631"),
)
_USERS = ("User", "Alex", "John", "Maria", "Admin", "Mike")


def _is_plain_tree(path: Path) -> bool:
    name = path.name.lower()
    if name == "profiles_youtube_plain" or name.startswith("profiles_youtube_plain_"):
        return True
    return (path / ".yt_plain.json").is_file()


def _read_meta(profile_dir: Path) -> dict:
    path = Path(profile_dir) / ASSIGN_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def assigned_file(profile_dir: Path) -> Path | None:
    profile_dir = Path(profile_dir)
    meta = _read_meta(profile_dir)
    name = str(meta.get("file_name") or "")
    if name:
        path = profile_dir / name
        if path.is_file():
            return path
    for candidate in (*INFO_NAMES, PC_INFO_JSON):
        path = profile_dir / candidate
        if path.is_file() and meta.get("source_key"):
            return path
    return None


def assignment_label(profile_dir: Path) -> str:
    meta = _read_meta(profile_dir)
    key = str(meta.get("source_key") or "")
    short = key[:8] if key else "—"
    gpu = str(meta.get("gpu") or "")
    screen = str(meta.get("screen") or "")
    bits = " ".join(part for part in (gpu, screen) if part)
    tail = f" {bits}" if bits else ""
    return f"случайный ПК [{short}]{tail}"


def _sibling_machine_ids(profile_dir: Path) -> set[str]:
    found: set[str] = set()
    parent = Path(profile_dir).parent
    if not parent.is_dir():
        return found
    own = Path(profile_dir).resolve()
    for item in parent.iterdir():
        if not item.is_dir() or item.resolve() == own or not _is_plain_tree(item):
            continue
        path = item / PC_INFO_JSON
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        machine = str((data or {}).get("MachineID") or "")
        if machine:
            found.add(machine)
    return found


def _pick(options: tuple, rng: secrets.SystemRandom):
    return options[rng.randrange(len(options))]


def _write_random(profile_dir: Path) -> Path:
    rng = secrets.SystemRandom()
    taken = _sibling_machine_ids(profile_dir)
    machine = ""
    for _ in range(8):
        machine = secrets.token_hex(16)
        if machine not in taken:
            break
    cpu, cores, threads, ram = _pick(_CPUS, rng)
    width, height, scale = _pick(_SCREENS, rng)
    country, locale, tz_name, city, lat, lon = _pick(_GEO, rng)
    windows, _build = _pick(_WINDOWS, rng)
    gpu = _pick(_GPUS, rng)
    data = {
        "Country": country,
        "City": city,
        "Latitude": lat,
        "Longitude": lon,
        "MachineID": machine,
        "GUID": secrets.token_hex(16),
        "HWID": secrets.token_hex(16),
        "Os": windows,
        "PcName": "DESKTOP-" + secrets.token_hex(4).upper(),
        "UserName": _pick(_USERS, rng),
        "CpuName": cpu,
        "CpuCores": cores,
        "CpuThreads": threads,
        "RAM": ram,
        "GPU": gpu,
        "ScreenSize": f"{width}x{height}",
        "Scale": scale,
        "Language": locale,
        "Timezone": tz_name,
    }
    dest = profile_dir / PC_INFO_JSON
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for stale in INFO_NAMES:
        other = profile_dir / stale
        if other.is_file():
            try:
                other.unlink()
            except OSError:
                pass
    key = hashlib.sha256(dest.read_bytes()).hexdigest()
    meta = {
        "source_key": key,
        "source_account": "random",
        "file_name": dest.name,
        "full": True,
        "local": True,
        "gpu": gpu,
        "screen": f"{width}x{height}",
        "reused": False,
        "assigned_at": datetime.now(timezone.utc).isoformat(),
    }
    (profile_dir / ASSIGN_FILE).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def ensure_assigned(profile_dir: Path, root: Path | None = None) -> Path:
    """Закрепить случайный отпечаток. Уже полный не перевыбирается."""
    del root
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    meta = _read_meta(profile_dir)
    current = assigned_file(profile_dir)
    if current is not None and meta.get("full") and current.name == PC_INFO_JSON:
        return current
    return _write_random(profile_dir)
