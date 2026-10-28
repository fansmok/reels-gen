"""Chrome for Testing: уникальный бинарник на аккаунт, закреплён на календарные сутки."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE_ROOT = Path(__file__).resolve().parent / "_chrome_cache"
POOL_FILE = CACHE_ROOT / "win64_by_major.json"
ASSIGNMENTS_FILE = CACHE_ROOT / "daily_assignments.json"
POOL_TTL = timedelta(hours=24)

CFT_KNOWN_GOOD = (
    "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
)
MAJOR_MIN = 118


@dataclass(frozen=True)
class ChromeBinary:
    version: str
    major: str
    executable: Path


@dataclass(frozen=True)
class DailyChromeResult:
    binary: ChromeBinary
    is_new_today: bool
    is_new_calendar_day: bool
    date_key: str
    accounts_today: int
    major_collision: bool


def _today_key() -> str:
    """Календарный день на этой машине — в полночь назначения сбрасываются."""
    return datetime.now().strftime("%Y-%m-%d")


def _win64_url(entry: dict) -> str | None:
    for item in entry.get("downloads", {}).get("chrome", []):
        if item.get("platform") == "win64":
            return str(item["url"])
    return None


def _refresh_major_pool() -> dict[str, dict[str, str]]:
    with urllib.request.urlopen(CFT_KNOWN_GOOD, timeout=90) as resp:
        data = json.loads(resp.read().decode())

    by_major: dict[str, dict[str, str]] = {}
    for entry in data.get("versions", []):
        version = str(entry.get("version", ""))
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
            continue
        major = version.split(".")[0]
        try:
            if int(major) < MAJOR_MIN:
                continue
        except ValueError:
            continue
        url = _win64_url(entry)
        if url:
            by_major[major] = {"version": version, "url": url}

    if len(by_major) < 5:
        raise RuntimeError("Chrome for Testing: слишком мало win64 версий в каталоге")

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(json.dumps(by_major, indent=2), encoding="utf-8")
    return by_major


def _load_major_pool() -> dict[str, dict[str, str]]:
    if POOL_FILE.is_file():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            POOL_FILE.stat().st_mtime, tz=timezone.utc
        )
        if age < POOL_TTL:
            try:
                pool = json.loads(POOL_FILE.read_text(encoding="utf-8"))
                if isinstance(pool, dict) and len(pool) >= 5:
                    return pool
            except json.JSONDecodeError:
                pass
    return _refresh_major_pool()


def _load_daily_state() -> tuple[str, dict[str, dict[str, str]], bool]:
    """date_key, assignments, is_new_calendar_day (файл был за вчера)."""
    today = _today_key()
    if not ASSIGNMENTS_FILE.is_file():
        return today, {}, False

    try:
        data = json.loads(ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return today, {}, False

    file_date = data.get("date", "")
    is_new_day = bool(file_date and file_date != today)
    assignments = data.get("assignments", {})
    if not isinstance(assignments, dict):
        return today, {}, is_new_day
    # Chrome закрепляем за аккаунтом: смена major каждый день сносит профиль и разлогинивает.
    return today, assignments, is_new_day


def _duplicate_majors(assignments: dict[str, dict[str, str]]) -> list[str]:
    by_major: dict[str, list[str]] = {}
    for acc, entry in assignments.items():
        major = str(entry.get("major", ""))
        by_major.setdefault(major, []).append(acc)
    dups: list[str] = []
    for major, accs in sorted(by_major.items()):
        if len(accs) > 1:
            dups.append(f"Chrome {major}: {', '.join(accs)}")
    return dups


def _major_load_stats(assignments: dict[str, dict[str, str]]) -> tuple[int, int]:
    """(уникальные major, max аккаунтов на один major)."""
    by_major: dict[str, int] = {}
    for entry in assignments.values():
        major = str(entry.get("major", ""))
        by_major[major] = by_major.get(major, 0) + 1
    max_load = max(by_major.values()) if by_major else 0
    return len(by_major), max_load


def _save_daily_state(date_key: str, assignments: dict[str, dict[str, str]]) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    ASSIGNMENTS_FILE.write_text(
        json.dumps({"date": date_key, "assignments": assignments}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _major_pick_index(account_key: str, date_key: str, salt: int, pool_size: int) -> int:
    raw = f"{date_key}|{account_key}|{salt}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return int(digest[:8], 16) % pool_size


def _pick_major_for_account(
    pool: dict[str, dict[str, str]],
    account_key: str,
    date_key: str,
    used_majors: set[str],
) -> tuple[str, bool]:
    """Детерминированный major per account+day; при исчерпании пула — least-loaded."""
    majors = sorted(pool.keys(), key=int)
    n = len(majors)
    for salt in range(n):
        major = majors[_major_pick_index(account_key, date_key, salt, n)]
        if major not in used_majors:
            return major, False

    counts: dict[str, int] = {m: 0 for m in majors}
    for major in used_majors:
        if major in counts:
            counts[major] += 1
    min_used = min(counts.values())
    candidates = [m for m, c in counts.items() if c == min_used]
    tie = _major_pick_index(account_key, date_key, 999, len(candidates))
    return candidates[tie], True


def _chrome_exe(version: str) -> Path:
    return CACHE_ROOT / version / "chrome-win64" / "chrome.exe"


def _download_chrome(version: str, url: str) -> Path:
    exe = _chrome_exe(version)
    if exe.is_file():
        return exe

    dest_dir = CACHE_ROOT / version
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "chrome-win64.zip"

    print(f"  … Скачиваю Chrome for Testing {version} (~150 MB, кэш _chrome_cache/)")
    urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    zip_path.unlink(missing_ok=True)

    if not exe.is_file():
        raise RuntimeError(f"chrome.exe не найден после распаковки: {exe}")

    return exe


def reassign_daily_chrome(account_key: str) -> tuple[str, str]:
    """Снять закреплённый Chrome и выбрать другой major. (old_version, new_version)."""
    key = str(account_key or "").strip()
    if not key:
        raise ValueError("account_key пустой")
    date_key, assignments, is_new_day = _load_daily_state()
    if is_new_day and assignments:
        _save_daily_state(date_key, assignments)
    old_entry = assignments.pop(key, None) or {}
    old_version = str(old_entry.get("version") or "")
    old_major = str(old_entry.get("major") or "")
    pool = _load_major_pool()
    used = {str(a.get("major") or "") for a in assignments.values()}
    if old_major:
        used.add(old_major)
    pick_day = f"{date_key}|rebuild|{old_major or 'none'}"
    major, _collision = _pick_major_for_account(pool, key, pick_day, used)
    if major == old_major and len(pool) > 1:
        used.add(old_major)
        others = {m: 0 for m in pool if m != old_major}
        for acc_major in (str(a.get("major") or "") for a in assignments.values()):
            if acc_major in others:
                others[acc_major] += 1
        major = min(others, key=lambda m: (others[m], int(m)))
    version = pool[major]["version"]
    url = pool[major]["url"]
    assignments[key] = {"version": version, "major": major, "url": url}
    _save_daily_state(date_key, assignments)
    return old_version, version


def version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(text or "").strip().split("."):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            break
    return tuple(parts)


def version_at_least(version: str, minimum: str) -> bool:
    """True, если version не старше minimum. Пустой minimum — ограничение не нужно."""
    if not str(minimum or "").strip():
        return True
    return version_tuple(version) >= version_tuple(minimum)


def profile_last_chrome_version(profile_dir: Path) -> str:
    path = Path(profile_dir) / "Last Version"
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _result_from_pool_entry(
    *,
    account_key: str,
    date_key: str,
    assignments: dict,
    major: str,
    info: dict,
    is_new: bool,
    is_new_day: bool,
    major_collision: bool,
) -> DailyChromeResult:
    version = info["version"]
    url = info["url"]
    assignments[account_key] = {"version": version, "major": major, "url": url}
    _save_daily_state(date_key, assignments)
    exe = _download_chrome(version, url)
    binary = ChromeBinary(version=version, major=major, executable=exe)
    return DailyChromeResult(
        binary=binary,
        is_new_today=is_new,
        is_new_calendar_day=is_new_day,
        date_key=date_key,
        accounts_today=len(assignments),
        major_collision=major_collision,
    )


def _cached_chrome_versions() -> list[tuple[tuple[int, ...], str, Path]]:
    found: list[tuple[tuple[int, ...], str, Path]] = []
    if not CACHE_ROOT.is_dir():
        return found
    for child in CACHE_ROOT.iterdir():
        if not child.is_dir():
            continue
        parsed = version_tuple(child.name)
        exe = child / "chrome-win64" / "chrome.exe"
        if parsed and exe.is_file():
            found.append((parsed, child.name, exe))
    found.sort(key=lambda item: item[0])
    return found


def resolve_chrome_for_existing_profile(account_key: str, profile_dir: Path) -> DailyChromeResult:
    """Chrome не старше Last Version профиля: иначе Chrome сразу закрывается."""
    minimum = profile_last_chrome_version(profile_dir)
    result = resolve_daily_chrome(account_key)
    if version_at_least(result.binary.version, minimum):
        return result

    date_key, assignments, is_new_day = _load_daily_state()
    used = {
        str(entry.get("major") or "")
        for key, entry in assignments.items()
        if key != account_key
    }
    cached = [
        item for item in _cached_chrome_versions()
        if version_at_least(item[1], minimum)
    ]
    if cached:
        _parsed, version, exe = cached[0]
        major = version.split(".")[0]
        print(
            f"  · Профиль уже на Chrome {minimum}, закреплённый {result.binary.version} "
            f"его не откроет — беру {version}",
            flush=True,
        )
        assignments[account_key] = {"version": version, "major": major, "url": ""}
        _save_daily_state(date_key, assignments)
        return DailyChromeResult(
            binary=ChromeBinary(version=version, major=major, executable=exe),
            is_new_today=True,
            is_new_calendar_day=is_new_day,
            date_key=date_key,
            accounts_today=len(assignments),
            major_collision=major in used,
        )

    pool = _load_major_pool()
    eligible = [
        (version_tuple(info["version"]), major, info)
        for major, info in pool.items()
        if version_at_least(str(info.get("version") or ""), minimum)
    ]
    if not eligible:
        raise RuntimeError(
            f"В пуле нет Chrome for Testing >= {minimum} — профиль открыт более новым Chrome"
        )
    eligible.sort(key=lambda item: item[0])
    _version, major, info = eligible[0]
    print(
        f"  · Профиль уже на Chrome {minimum}, закреплённый {result.binary.version} "
        f"его не откроет — беру {info['version']}",
        flush=True,
    )
    return _result_from_pool_entry(
        account_key=account_key,
        date_key=date_key,
        assignments=assignments,
        major=str(major),
        info=info,
        is_new=True,
        is_new_day=is_new_day,
        major_collision=str(major) in used,
    )


def resolve_daily_chrome(account_key: str) -> DailyChromeResult:
    """
    Уникальный Chrome на аккаунт. Версия закрепляется и не меняется в полночь:
    смена major сносит browser_profile и Google разлогинивает.
    """
    if not account_key.strip():
        raise ValueError("account_key пустой")

    date_key, assignments, is_new_day = _load_daily_state()
    if is_new_day and assignments:
        _save_daily_state(date_key, assignments)
    is_new = account_key not in assignments
    major_collision = False

    if account_key in assignments:
        entry = assignments[account_key]
        version = entry["version"]
        major = entry.get("major") or version.split(".")[0]
        url = entry.get("url") or _load_major_pool().get(major, {}).get("url", "")
        if not url:
            pool = _load_major_pool()
            url = pool[major]["url"]
    else:
        pool = _load_major_pool()
        used = {str(a.get("major", "")) for a in assignments.values()}
        major, major_collision = _pick_major_for_account(pool, account_key, date_key, used)
        version = pool[major]["version"]
        url = pool[major]["url"]
        assignments[account_key] = {"version": version, "major": major, "url": url}
        _save_daily_state(date_key, assignments)

    exe = _download_chrome(version, url)
    binary = ChromeBinary(version=version, major=major, executable=exe)
    return DailyChromeResult(
        binary=binary,
        is_new_today=is_new,
        is_new_calendar_day=is_new_day,
        date_key=date_key,
        accounts_today=len(assignments),
        major_collision=major_collision,
    )


def daily_assignment_report() -> tuple[list[str], list[str]]:
    """(ok lines, warnings) для аудита."""
    ok: list[str] = []
    warns: list[str] = []
    date_key, assignments, is_new_day = _load_daily_state()
    if is_new_day:
        ok.append(f"Новый день {date_key} — Chrome аккаунтов закреплён, не сбрасываю")
    if not assignments:
        ok.append("Нет назначений Chrome на сегодня (появятся при запуске аккаунтов)")
        return ok, warns

    ok.append(f"Chrome на {date_key}: {len(assignments)} аккаунт(ов)")
    pool = _load_major_pool()
    unique_majors, max_load = _major_load_stats(assignments)
    ok.append(f"Уникальные major: {unique_majors}/{len(pool)} в пуле CFT")
    if len(assignments) > len(pool):
        warns.append(
            f"Аккаунтов ({len(assignments)}) больше, чем major в пуле ({len(pool)}) — "
            f"TLS-коллизии неизбежны (max {max_load} акк./major)"
        )
    elif max_load > 1:
        warns.append(f"До {max_load} аккаунтов делят один major — TLS может совпадать")
    dups = _duplicate_majors(assignments)
    if dups:
        warns.append("Collision major (TLS не уникален): " + "; ".join(dups))
    return ok, warns


# Эти флаги ломают HTTP/2 и fetch(): белый YouTube, Google не открывается,
# IP-check из Chrome возвращает пусто. Прокси идёт через локальный relay
# (--proxy-server=127.0.0.1) — NetworkService его уважает.
_CFT_BREAKS_YOUTUBE = frozenset({
    "NetworkService",
    "NetworkServiceInProcess",
})


def cft_windows_proxy_args(chrome_major: str) -> list[str]:
    """Флаги CFT+прокси. NetworkService НЕ отключаем — YouTube без него белый."""
    _ = chrome_major
    return []


def write_cft_proxy_tls_policies(chrome_exe: Path) -> None:
    """CFT: выключить PQ/ECH — большой ClientHello зависает на дешёвых HTTP-прокси."""
    chrome_exe = Path(chrome_exe)
    if not chrome_exe.is_file():
        return
    managed = chrome_exe.parent / "policies" / "managed"
    try:
        managed.mkdir(parents=True, exist_ok=True)
        (managed / "yt-proxy-tls.json").write_text(
            json.dumps({
                "PostQuantumKeyAgreementEnabled": False,
                "EncryptedClientHelloEnabled": False,
            }),
            encoding="utf-8",
        )
    except OSError:
        pass


def apply_chrome_version_to_profile(profile, version: str) -> None:
    from pc_parser import _rebuild_user_agent

    profile.chrome_version = version
    profile.chrome_major = version.split(".")[0]
    profile._defaults_used.discard("chrome_version")
    profile._defaults_used.add("chrome_daily_binary")
    _rebuild_user_agent(profile)


def prune_cache(max_unassigned: int = 10) -> None:
    """Удалить старые версии Chrome, не используемые сегодня (кроме max_unassigned свежих)."""
    _, assignments, _ = _load_daily_state()
    keep = {a["version"] for a in assignments.values()}

    if not CACHE_ROOT.is_dir():
        return

    dirs = [
        d for d in CACHE_ROOT.iterdir()
        if d.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", d.name)
    ]
    dirs.sort(key=lambda p: tuple(int(x) for x in p.name.split(".")), reverse=True)

    unassigned = [d for d in dirs if d.name not in keep]
    for d in unassigned[max_unassigned:]:
        shutil.rmtree(d, ignore_errors=True)
