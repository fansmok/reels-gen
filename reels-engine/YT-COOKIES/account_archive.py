"""Распаковка профилей из .zip для запуска без ручной распаковки."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import stat
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

META_FILE = ".archive.json"
CACHE_DIR = "_zip_cache"
YOUTUBE_INFO_NAMES = ("YoutubeInfo.txt", "youtubeinfo.txt", "YT_info.txt")
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_FILE_SIZE = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000
_EXTRACT_LOCK = threading.RLock()
_WIN_RESERVED_STEM = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
_UNSAFE_STEM_CHARS = frozenset('\\/:\0<>|"?*')
# SAPISID/APISID/PAPISID привязаны к аккаунту и почти не ротируются.
# SID/PSID Google меняет — по ним нельзя решать, что это «другой» лог.
_STABLE_AUTH_NAMES = {
    "SAPISID",
    "APISID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
}
_FALLBACK_AUTH_NAMES = {
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
}


def _safe_member_path(name: str) -> PurePosixPath | None:
    """Нормализовать имя ZIP и отвергнуть выход из staging/служебные файлы."""
    text = str(name or "").replace("\\", "/")
    if not text or "\x00" in text:
        raise ValueError("ZIP содержит пустое или повреждённое имя")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Небезопасный путь в ZIP: {name}")
    if path.parts and (":" in path.parts[0] or path.parts[0].startswith("~")):
        raise ValueError(f"Небезопасный путь в ZIP: {name}")
    if any(part == "__MACOSX" for part in path.parts):
        return None
    if any(part == "browser_profile" for part in path.parts):
        return None
    # Архив — недоверенный вход. Runtime-файлы создаёт только наше приложение.
    if any(part.startswith(".yt_") or part == META_FILE for part in path.parts):
        return None
    if path.name.startswith("._"):
        return None
    return path


def _zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (int(info.external_attr) >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _youtube_info_name(name: str) -> bool:
    base = name.rstrip("/").split("/")[-1]
    return base in YOUTUBE_INFO_NAMES


def zip_has_youtube_info(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return any(_youtube_info_name(n) for n in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def is_account_archive(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".zip" and zip_has_youtube_info(path)


def safe_archive_stem(zip_path: Path) -> str:
    """Имя папки кэша: отвергнуть ..zip, зарезервированные имена Windows, путь в имени.

    Path.stem на Windows для '..zip' даёт '..zip' (суффикс пустой), на POSIX — '.'.
    Снимаем .zip сами, чтобы '..zip' всегда стал '..'.
    """
    name = str(getattr(zip_path, "name", "") or "").strip()
    if name.lower().endswith(".zip"):
        stem = name[:-4]
    else:
        stem = str(getattr(zip_path, "stem", "") or "").strip()
    stem = stem.strip()
    if not stem or stem in {".", ".."} or set(stem) <= {"."} or stem.startswith("."):
        raise ValueError(f"Небезопасное имя архива: {getattr(zip_path, 'name', zip_path)}")
    if any(ch in _UNSAFE_STEM_CHARS for ch in stem) or any(part in {"", ".", ".."} for part in Path(stem).parts):
        raise ValueError(f"Небезопасное имя архива: {getattr(zip_path, 'name', zip_path)}")
    if _WIN_RESERVED_STEM.fullmatch(stem):
        raise ValueError(f"Зарезервированное имя архива: {getattr(zip_path, 'name', zip_path)}")
    return stem


def cache_dir_for_archive(zip_path: Path, root: Path) -> Path:
    cache_root = root.resolve() / CACHE_DIR
    cache = (cache_root / safe_archive_stem(zip_path)).resolve()
    if cache.parent != cache_root:
        raise ValueError(f"Путь кэша выходит из {CACHE_DIR}: {zip_path.name}")
    return cache


def archive_meta_path(cache_dir: Path) -> Path:
    return cache_dir / META_FILE


def read_archive_meta(cache_dir: Path) -> dict | None:
    path = archive_meta_path(cache_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def is_extracted_from_archive(cache_dir: Path) -> bool:
    meta = read_archive_meta(cache_dir)
    return bool(meta and meta.get("source"))


def _zip_is_current(zip_path: Path, cache_dir: Path) -> bool:
    meta = read_archive_meta(cache_dir)
    if not meta or meta.get("source") != str(zip_path.resolve()):
        return False
    try:
        stat = zip_path.stat()
    except OSError:
        return False
    if meta.get("mtime") != stat.st_mtime or meta.get("size") != stat.st_size:
        return False
    return any(
        p.is_file() and p.name in YOUTUBE_INFO_NAMES
        for p in cache_dir.rglob("*")
    )


def _write_archive_meta(zip_path: Path, cache_dir: Path) -> None:
    stat = zip_path.stat()
    archive_meta_path(cache_dir).write_text(
        json.dumps(
            {
                "source": str(zip_path.resolve()),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _account_zip_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total_size = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = _safe_member_path(info.filename)
        if path is None:
            continue
        if _zip_entry_is_symlink(info):
            raise ValueError(f"ZIP содержит ссылку: {info.filename}")
        if info.file_size < 0 or info.file_size > MAX_ARCHIVE_FILE_SIZE:
            raise ValueError(f"Слишком большой файл в ZIP: {info.filename}")
        total_size += info.file_size
        if total_size > MAX_ARCHIVE_TOTAL_SIZE:
            raise ValueError("ZIP слишком большой после распаковки")
        if info.file_size and info.compress_size == 0:
            raise ValueError(f"Подозрительное сжатие ZIP: {info.filename}")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise ValueError(f"Подозрительный коэффициент сжатия ZIP: {info.filename}")
        members.append((info, path))
        if len(members) > MAX_ARCHIVE_FILES:
            raise ValueError("Слишком много файлов в ZIP")
    return members


def _extract_members(zf: zipfile.ZipFile, staging: Path) -> None:
    staging_resolved = staging.resolve()
    for info, relative in _account_zip_members(zf):
        dest = staging.joinpath(*relative.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if staging_resolved not in dest.resolve().parents:
            raise ValueError(f"Путь ZIP выходит из папки аккаунта: {info.filename}")
        with zf.open(info, "r") as source, dest.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)


def _runtime_items(cache: Path) -> list[Path]:
    if not cache.is_dir():
        return []
    items: list[Path] = []
    profile = cache / "browser_profile"
    if profile.exists():
        items.append(profile)
    for item in cache.iterdir():
        if item.name.startswith(".yt_") and item.name not in {
            ".yt_browser_alive",
            ".yt_attach_done",
            ".yt_create_streams.json",
        }:
            items.append(item)
    return items


def _validate_staging(staging: Path) -> None:
    if not any((staging / name).is_file() for name in YOUTUBE_INFO_NAMES):
        # Допускаем один вложенный каталог: он будет поднят _flatten_single_subfolder.
        nested = [
            p for p in staging.rglob("*")
            if p.is_file() and p.name in YOUTUBE_INFO_NAMES
        ]
        if not nested:
            raise ValueError("В ZIP нет YoutubeInfo.txt")


_PC_TEXT_INFO = (
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


def _has_info_at_root(folder: Path) -> bool:
    for name in (*_PC_TEXT_INFO, "pc_info.json"):
        if (folder / name).is_file():
            return True
    return False


def _has_account_marker_at_root(folder: Path) -> bool:
    return _has_info_at_root(folder) or any(
        (folder / name).is_file() for name in YOUTUBE_INFO_NAMES
    )


def _account_identity_tokens(folder: Path) -> dict[str, set[str]]:
    """Email + стабильные auth-cookie. SID не входит: Google ротирует его между выгрузками."""
    emails: set[str] = set()
    stable: set[str] = set()
    fallback: set[str] = set()
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "browser_profile" and not d.startswith(".yt_")]
        for name in files:
            if name.startswith(".yt_"):
                continue
            path = Path(base) / name
            try:
                if path.stat().st_size > 32 * 1024 * 1024:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                parts = stripped.split("\t")
                if len(parts) >= 7:
                    cookie_name = parts[-2].strip()
                    value = parts[-1].strip()
                    if value and cookie_name in _STABLE_AUTH_NAMES:
                        stable.add(f"{cookie_name}={value}")
                    elif value and cookie_name in _FALLBACK_AUTH_NAMES:
                        fallback.add(f"{cookie_name}={value}")
                if re.search(r"(?i)^\s*(?:почта|e-?mail|login)\s*[:=]", stripped):
                    match = re.search(r"([^\s]+@[^\s]+)", stripped)
                    if match:
                        emails.add(match.group(1).rstrip(".,;").lower())
                else:
                    match = re.search(r"(?i)\b(?:e-?mail|login)\s*[:=]\s*([^\s]+@[^\s]+)", stripped)
                    if match:
                        emails.add(match.group(1).rstrip(".,;").lower())
    return {"emails": emails, "stable": stable, "fallback": fallback}


def _account_identity(folder: Path) -> str:
    """Стабильный ID содержимого аккаунта для защиты от одинаковых имён ZIP."""
    tokens = _account_identity_tokens(folder)
    values = sorted(tokens["emails"] | tokens["stable"] | tokens["fallback"])
    if not values:
        return ""
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def same_account_identity(old: dict[str, set[str]] | None, new: dict[str, set[str]] | None) -> bool:
    """Один и тот же Google-аккаунт, даже если в новом ZIP уже другой SID."""
    old = old or {"emails": set(), "stable": set(), "fallback": set()}
    new = new or {"emails": set(), "stable": set(), "fallback": set()}
    if old["emails"] and new["emails"]:
        return bool(old["emails"] & new["emails"])
    if old["stable"] and new["stable"]:
        return bool(old["stable"] & new["stable"])
    if old["emails"] or new["emails"] or old["stable"] or new["stable"]:
        if old["fallback"] and new["fallback"]:
            return bool(old["fallback"] & new["fallback"])
        return False
    if old["fallback"] and new["fallback"]:
        return bool(old["fallback"] & new["fallback"])
    return False


def _cache_has_open_browser(cache: Path) -> bool:
    """Нельзя подменять папку, пока Chrome держит browser_profile."""
    if (cache / ".yt_browser_alive").is_file():
        return True
    profile = cache / "browser_profile"
    for name in ("SingletonLock", "SingletonCookie", "lockfile"):
        if (profile / name).exists():
            return True
    return False


def _flatten_single_subfolder(cache: Path) -> None:
    """Частая ручная/zip-структура: account/information.txt → поднять файлы в корень cache."""
    if _has_account_marker_at_root(cache):
        return
    skip = {"browser_profile", "__MACOSX"}
    subdirs = [d for d in cache.iterdir() if d.is_dir() and d.name not in skip]
    if len(subdirs) != 1:
        return
    inner = subdirs[0]
    if not _has_account_marker_at_root(inner):
        return
    for item in inner.iterdir():
        dest = cache / item.name
        if dest.exists():
            continue
        shutil.move(str(item), str(dest))
    try:
        inner.rmdir()
    except OSError:
        pass


def ensure_account_extracted(zip_path: Path, root: Path) -> Path:
    """Распаковать архив в _zip_cache/<имя>, сохранить browser_profile между обновлениями."""
    zip_path = zip_path.resolve()
    cache = cache_dir_for_archive(zip_path, root)
    cache.parent.mkdir(parents=True, exist_ok=True)

    with _EXTRACT_LOCK:
        if _zip_is_current(zip_path, cache):
            return cache
        if cache.is_dir() and _cache_has_open_browser(cache):
            # Повторный вход / список аккаунтов не должен сносить живой Chrome,
            # даже если mtime ZIP сдвинулся (антивирус, повторная скачка).
            return cache

        safe_stem = safe_archive_stem(zip_path)
        with tempfile.TemporaryDirectory(
            prefix=f".{safe_stem}.extract-", dir=str(cache.parent),
        ) as tmp_name:
            tmp = Path(tmp_name)
            staging = tmp / "payload"
            staging.mkdir()

            with zipfile.ZipFile(zip_path) as zf:
                _extract_members(zf, staging)
            _flatten_single_subfolder(staging)
            _validate_staging(staging)

            # Переносим только доверенное runtime-состояние из старого кэша.
            # Сравниваем email/SAPISID, не SID: новая выгрузка того же аккаунта
            # иначе уничтожит живой browser_profile.
            old_tokens = _account_identity_tokens(cache) if cache.is_dir() else None
            new_tokens = _account_identity_tokens(staging)
            preserve_runtime = bool(
                cache.is_dir() and same_account_identity(old_tokens, new_tokens)
            )
            for item in (_runtime_items(cache) if preserve_runtime else []):
                dest = staging / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            _write_archive_meta(zip_path, staging)
            backup = cache.with_name(f".{cache.name}.old-{os.getpid()}")
            if backup.exists():
                shutil.rmtree(backup)
            try:
                if cache.exists():
                    cache.replace(backup)
                staging.replace(cache)
            except Exception:
                if not cache.exists() and backup.exists():
                    backup.replace(cache)
                raise
            finally:
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)

    return cache


def find_info_file_in_zip(zip_path: Path) -> str | None:
    """Путь к information.txt или pc_info.json внутри архива (без распаковки)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info_name: str | None = None
            pc_info_name: str | None = None
            for name in zf.namelist():
                base = Path(name).name.lower()
                if base in {
                    "information.txt",
                    "info.txt",
                    "system.txt",
                    "system_info.txt",
                    "userinfo.txt",
                    "userinformation.txt",
                    "system information.txt",
                    "pc_info.txt",
                }:
                    info_name = name
                elif base == "pc_info.json":
                    pc_info_name = name
            return info_name or pc_info_name
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def read_text_from_zip(zip_path: Path, inner_path: str) -> str | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return zf.read(inner_path).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
