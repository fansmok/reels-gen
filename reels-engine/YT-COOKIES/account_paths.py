"""Поиск файлов аккаунта (cookies, information) в папке yt-cookies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from account_archive import (
    CACHE_DIR,
    ensure_account_extracted,
    is_account_archive,
    is_extracted_from_archive,
    read_text_from_zip,
    zip_has_youtube_info,
)


def cookies_root() -> Path:
    """Корень yt-cookies/ где лежат папки аккаунтов s73_..., s371_..."""
    here = Path(__file__).resolve().parent
    for path in here.iterdir():
        if path.is_dir() and path.name != CACHE_DIR and (path / "YoutubeInfo.txt").is_file():
            return here
        if path.suffix.lower() == ".zip" and zip_has_youtube_info(path):
            return here
    return here.parent


INFO_NAMES = (
    "information.txt",
    "info.txt",
    "Information.txt",
    "system.txt",
    "system_info.txt",
    "UserInfo.txt",
    "userinfo.txt",
    "UserInformation.txt",
    "userinformation.txt",
    "System Information.txt",
    "system information.txt",
    "pc_info.txt",
)
PC_INFO_JSON = "pc_info.json"
YOUTUBE_INFO_NAMES = ("YoutubeInfo.txt", "youtubeinfo.txt", "YT_info.txt")
COOKIE_NAMES = ("YT_cookies.txt", "yt_cookies.txt", "cookies.txt", "Cookies.txt")
PASSWORD_NAMES = ("AllPasswords.txt", "passwords_unique.txt", "Brute.txt")

PORT_SLOT_START = 30000
SLOTS_FILE = "profile_slots.json"

PATH_LINE_RE = re.compile(
    r"^(?:Путь|Path|Cookie(?:s)?(?:\s+file)?):\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
PATH_COMMENT_RE = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass
class YoutubeInfo:
    path: Path
    cookies_rel: str = ""
    cookies_note: str = ""
    channel_url: str = ""
    email: str = ""
    subscribers: str = ""
    views: str = ""
    registration: str = ""


def find_youtube_info_file(folder: Path) -> Path | None:
    for name in YOUTUBE_INFO_NAMES:
        path = folder / name
        if path.is_file():
            return path
    return None


def parse_youtube_info(folder: Path) -> YoutubeInfo | None:
    yt_file = find_youtube_info_file(folder)
    if not yt_file:
        return None

    text = yt_file.read_text(encoding="utf-8", errors="replace")
    info = YoutubeInfo(path=yt_file)

    for pattern, attr in (
        (r"^Ссылка:\s*(.+)$", "channel_url"),
        (r"^Почта:\s*(.+)$", "email"),
        (r"^Число подписчиков:\s*(.+)$", "subscribers"),
        (r"^Число просмотров:\s*(.+)$", "views"),
        (r"^Регистрация:\s*(.+)$", "registration"),
    ):
        m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if m:
            setattr(info, attr, m.group(1).strip())

    m = PATH_LINE_RE.search(text)
    if m:
        raw = m.group(1).strip()
        note_match = PATH_COMMENT_RE.search(raw)
        if note_match:
            info.cookies_note = note_match.group(0).strip(" ()")
            raw = PATH_COMMENT_RE.sub("", raw).strip()
        info.cookies_rel = raw.replace("\\", "/")

    return info


def cookies_path_from_youtube_info(folder: Path) -> Path | None:
    """Берёт путь к cookies из YoutubeInfo.txt → строка «Путь: ...»."""
    info = parse_youtube_info(folder)
    if not info or not info.cookies_rel:
        return None

    rel = info.cookies_rel
    candidates = [
        folder / rel,
        folder / Path(rel).name,
    ]
    cookies_sub = folder / "Cookies" / Path(rel).name
    if cookies_sub not in candidates:
        candidates.append(cookies_sub)

    for path in candidates:
        if path.is_file():
            return path.resolve()

    return None


def find_info_file(folder: Path) -> Path | None:
    """information.txt / UserInfo.txt / pc_info.json в корне папки или на один уровень глубже."""
    for name in INFO_NAMES:
        path = folder / name
        if path.is_file():
            return path
    pc_info = folder / PC_INFO_JSON
    if pc_info.is_file():
        return pc_info

    skip = {"browser_profile", "Cookies", "Passwords", "GoogleAccounts", "__MACOSX", CACHE_DIR}
    for sub in sorted(folder.iterdir()):
        if not sub.is_dir() or sub.name in skip or sub.name.startswith("."):
            continue
        for name in INFO_NAMES:
            path = sub / name
            if path.is_file():
                return path
        pc_info = sub / PC_INFO_JSON
        if pc_info.is_file():
            return pc_info
    return None


def _folder_listing_hint(folder: Path, limit: int = 12) -> str:
    """Краткий список файлов в папке — для сообщения об ошибке."""
    try:
        names = sorted(p.name for p in folder.iterdir() if p.is_file())
    except OSError:
        return ""
    if not names:
        subdirs = sorted(p.name for p in folder.iterdir() if p.is_dir())
        if subdirs:
            return f"  Подпапки: {', '.join(subdirs[:limit])}"
        return "  (папка пуста)"
    extra = f" … +{len(names) - limit}" if len(names) > limit else ""
    return f"  Файлы: {', '.join(names[:limit])}{extra}"


def is_pc_info_json(path: Path) -> bool:
    return path.name.lower() in {PC_INFO_JSON, "pc_info.txt"}


def list_cookie_dump_files(folder: Path) -> list[Path]:
    """Все дампы cookies из лога: Cookies/*.txt, путь из YoutubeInfo, корневые cookies.txt."""
    seen: set[Path] = set()
    files: list[Path] = []

    def add(path: Path | None) -> None:
        if not path or not path.is_file():
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        files.append(resolved)

    cookies_dir = folder / "Cookies"
    if cookies_dir.is_dir():
        for path in sorted(
            cookies_dir.glob("*.txt"),
            key=lambda p: (-p.stat().st_size, p.name.lower()),
        ):
            add(path)

    add(cookies_path_from_youtube_info(folder))
    for name in COOKIE_NAMES:
        add(folder / name)
    return files


def _browser_rank(path: Path) -> int:
    name = path.name.lower()
    if "chrome" in name:
        return 0
    if "edge" in name:
        return 1
    if "firefox" in name:
        return 2
    if "opera" in name:
        return 3
    if "brave" in name:
        return 4
    return 5


def find_cookies_file(folder: Path, explicit: Path | None = None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit.resolve()

    # «Путь: Cookies/Chrome_Profile4.txt» в YoutubeInfo.txt — куки этого YouTube-канала.
    from_yt = cookies_path_from_youtube_info(folder)
    if from_yt:
        return from_yt

    dumps = list_cookie_dump_files(folder)
    if dumps:
        from cookie_parser import parse_netscape_cookies, session_cookie_score

        ranked: list[tuple[int, int, int, Path]] = []
        for path in dumps:
            try:
                parsed = parse_netscape_cookies(path, auth_only=True)
            except Exception:
                continue
            score, freshness = session_cookie_score(parsed)
            ranked.append((score, freshness, -_browser_rank(path), path))
        ranked.sort(reverse=True)
        if ranked and ranked[0][0] > 0:
            return ranked[0][3].resolve()
        return dumps[0].resolve()

    for name in COOKIE_NAMES:
        path = folder / name
        if path.is_file():
            return path.resolve()

    for path in sorted(folder.glob("*.txt"), key=lambda p: -p.stat().st_size):
        if path.name.lower() in {n.lower() for n in INFO_NAMES + YOUTUBE_INFO_NAMES}:
            continue
        if path.name.lower() in {
            n.lower() for n in PASSWORD_NAMES
        } | {"channels.txt", "proxy.txt", "passwords.txt"}:
            continue
        try:
            first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            if "\t" in first and ("google.com" in first or "youtube.com" in first):
                return path.resolve()
        except Exception:
            pass

    return None


def find_passwords_file(folder: Path, explicit: Path | None = None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit.resolve()
    for name in PASSWORD_NAMES:
        path = folder / name
        if path.is_file():
            return path.resolve()
    return None


def list_password_sources(folder: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for name in PASSWORD_NAMES:
        path = folder / name
        if path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
    return files


def resolve_account(
    account_dir: Path,
    *,
    info: Path | None = None,
    cookies: Path | None = None,
    profile: Path | None = None,
) -> tuple[Path, Path, Path, YoutubeInfo | None]:
    """
    Возвращает (information.txt, cookies.txt, browser_profile_dir, youtube_info).
    """
    account_dir = account_dir.resolve()
    yt_info = parse_youtube_info(account_dir)

    info_path = info or find_info_file(account_dir)
    if not info_path or not info_path.is_file():
        hint = _folder_listing_hint(account_dir)
        raise FileNotFoundError(
            f"Не найден information.txt, UserInfo.txt, UserInformation.txt, System Information.txt, pc_info.txt или {PC_INFO_JSON} в {account_dir}\n"
            f"  Нужен один из: {', '.join(INFO_NAMES)} или {PC_INFO_JSON} "
            f"(в корне папки аккаунта или в одной подпапке)\n"
            f"{hint}\n"
            f"  Укажите явно: --info \"C:\\path\\to\\information.txt\""
        )

    cookies_path = find_cookies_file(account_dir, cookies)
    if not cookies_path:
        hint = ""
        if yt_info and yt_info.cookies_rel:
            hint = f"\n  YoutubeInfo.txt указывает: {yt_info.cookies_rel}"
            if yt_info.cookies_note:
                hint += f" ({yt_info.cookies_note})"
        raise FileNotFoundError(
            f"Не найден файл cookies в {account_dir}{hint}\n"
            f"  Проверьте строку «Путь:» в YoutubeInfo.txt или укажите --cookies"
        )

    profile_dir = profile if profile else account_dir / "browser_profile"
    return info_path, cookies_path, profile_dir, yt_info


def account_key(account_dir: Path) -> str:
    """Ключ профиля для слотов (имя папки или stem архива)."""
    return account_dir.name


def _list_account_archives(base: Path) -> list[Path]:
    archives: list[Path] = []
    for path in sorted(base.glob("*.zip")):
        if zip_has_youtube_info(path):
            archives.append(path)
    return archives


def resolve_account_workdir(account: Path, root: Path | None = None) -> Path:
    """Папка аккаунта или распакованный кэш для .zip."""
    account = account.expanduser()
    if account.is_dir():
        return account.resolve()
    if is_account_archive(account):
        return ensure_account_extracted(account, root or cookies_root())
    raise FileNotFoundError(f"Не профиль: {account}")


def list_accounts(root: Path | None = None) -> list[Path]:
    """Все профили: папки и .zip (возвращает рабочие каталоги)."""
    base = (root or cookies_root()).resolve()
    folders: list[Path] = []
    for path in sorted(base.iterdir()):
        if not path.is_dir() or path.name.startswith(".") or path.name == CACHE_DIR:
            continue
        if find_youtube_info_file(path):
            folders.append(path)

    folder_names = {path.name for path in folders}
    accounts = list(folders)
    for archive in _list_account_archives(base):
        if archive.stem in folder_names:
            continue
        accounts.append(ensure_account_extracted(archive, base))
    return accounts


def _slots_file(root: Path | None = None) -> Path:
    return (root or cookies_root()).resolve() / SLOTS_FILE


def _load_slots(root: Path | None = None) -> dict[str, int]:
    path = _slots_file(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("slots", data) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            return {}
        return {str(name): int(idx) for name, idx in raw.items()}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _save_slots(slots: dict[str, int], root: Path | None = None) -> None:
    path = _slots_file(root)
    ordered = dict(sorted(slots.items(), key=lambda x: (x[1], x[0])))
    path.write_text(
        json.dumps({"slots": ordered}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _first_free_slot(used: set[int]) -> int:
    slot = 0
    while slot in used:
        slot += 1
    return slot


def sync_profile_slots(root: Path | None = None) -> dict[str, int]:
    """
    Реестр «мест» профилей → слот 9Proxy (0 = :30000, 1 = :30001…).

    - У каждого профиля слот сохраняется в profile_slots.json
    - Удалённый профиль освобождает слот
    - Новый профиль занимает первый свободный слот
    """
    base = (root or cookies_root()).resolve()
    accounts = list_accounts(base)
    names = {account_key(acc) for acc in accounts}

    slots = _load_slots(base)
    before = dict(slots)

    slots = {name: idx for name, idx in slots.items() if name in names}
    used = set(slots.values())

    if not before and accounts:
        for i, acc in enumerate(accounts):
            slots[account_key(acc)] = i
            used.add(i)
    else:
        for acc in accounts:
            key = account_key(acc)
            if key in slots:
                continue
            free = _first_free_slot(used)
            slots[key] = free
            used.add(free)

    if slots != before:
        _save_slots(slots, base)
    return slots


def list_accounts_by_slot(root: Path | None = None) -> list[Path]:
    """Профили, отсортированные по закреплённому слоту (:30000, :30001…)."""
    slots = sync_profile_slots(root)
    accounts = list_accounts(root)
    return sorted(accounts, key=lambda acc: (slots.get(account_key(acc), 9999), account_key(acc)))


def account_slot_index(account_dir: Path, root: Path | None = None) -> int:
    """Номер слота профиля (0 = порт 30000)."""
    target = resolve_account_workdir(account_dir, root)
    slots = sync_profile_slots(root)
    key = account_key(target)
    if key in slots:
        return slots[key]
    return _first_free_slot(set(slots.values()))


def port_for_account(account_dir: Path, root: Path | None = None) -> int:
    """Свой локальный порт 9Proxy: 30000, 30001, 30002…"""
    return PORT_SLOT_START + account_slot_index(account_dir, root)


def port_for_menu_index(menu_index: int, root: Path | None = None) -> int:
    """menu_index — номер в меню (1-based) → порт выбранного профиля."""
    accounts = list_accounts_by_slot(root)
    if 1 <= menu_index <= len(accounts):
        return port_for_account(accounts[menu_index - 1], root)
    return PORT_SLOT_START + menu_index - 1


def port_range_for_accounts(root: Path | None = None) -> int:
    """Сколько портов резервировать в 9Proxy (по максимальному занятому слоту)."""
    slots = sync_profile_slots(root)
    max_idx = max(slots.values()) if slots else 0
    return max(max_idx + 1, len(list_accounts(root)), 15)


def resolve_account_dir(name_or_path: str | Path, root: Path | None = None) -> Path:
    """
    Имя папки, .zip или путь → рабочая папка аккаунта.
    s159_r2017_v5k_32  →  папка или s159_r2017_v5k_32.zip
    """
    p = Path(name_or_path).expanduser()
    base = (root or cookies_root()).resolve()

    if p.is_dir():
        return p.resolve()
    if is_account_archive(p):
        return ensure_account_extracted(p, base)

    if p.suffix.lower() != ".zip":
        zip_candidate = base / f"{p.name}.zip"
        if zip_candidate.is_file() and zip_has_youtube_info(zip_candidate):
            return ensure_account_extracted(zip_candidate, base)

    candidate = base / p.name if p.name == str(name_or_path) else base / name_or_path
    if candidate.is_dir():
        return candidate.resolve()
    if is_account_archive(candidate):
        return ensure_account_extracted(candidate, base)

    needle = str(name_or_path).lower().removesuffix(".zip")
    for acc in list_accounts(base):
        key = account_key(acc)
        if key.lower() == needle or needle in key.lower():
            return acc.resolve()

    archives = ", ".join(a.stem for a in _list_account_archives(base)) or "—"
    raise FileNotFoundError(
        f"Аккаунт не найден: {name_or_path}\n"
        f"  Корень: {base}\n"
        f"  Папки/архивы: {', '.join(account_key(a) for a in list_accounts(base)) or '—'}\n"
        f"  Только .zip: {archives}"
    )
