"""Живые cookies аккаунта после сессии.

Google ротирует __Secure-*PSIDTS / SIDCC прямо во время работы. Если при следующем
запуске снова залить старый дамп из лога поверх профиля, Google видит устаревший
токен и разлогинивает аккаунт. Поэтому после сессии снимаем актуальные cookies,
а при повторном входе не трогаем живую сессию профиля и не открываем google.com.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

from cookie_parser import is_auth_domain

LIVE_COOKIES_NAME = ".yt_live_cookies.json"
LIVE_COOKIES_BACKUP_NAME = ".yt_live_cookies.prev.json"
_SESSION_NAMES = ("SID", "__Secure-1PSID", "__Secure-3PSID")
ROTATING_AUTH_NAMES = (
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
    "SIDCC",
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "HSID",
    "SSID",
    "LOGIN_INFO",
)


def live_cookies_path(account_dir) -> Path | None:
    if not account_dir:
        return None
    return Path(account_dir) / LIVE_COOKIES_NAME


def profile_has_cookie_store(profile_dir) -> bool:
    """В профиле уже есть база cookies Chrome — это не первый заход."""
    if not profile_dir:
        return False
    base = Path(profile_dir) / "Default"
    for folder in (base / "Network", base):
        try:
            cookies = folder / "Cookies"
            if cookies.is_file() and cookies.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def cdp_cookie_jar(context) -> list[dict]:
    """Все cookies профиля: CDP (HttpOnly) или Playwright context.cookies()."""
    pages: list = []
    try:
        pages = list(getattr(context, "pages", None) or [])
    except Exception:
        pages = []
    for page in pages:
        try:
            session = context.new_cdp_session(page)
            data = session.send("Network.getAllCookies")
        except Exception:
            continue
        jar = data.get("cookies") if isinstance(data, dict) else None
        if isinstance(jar, list) and jar:
            return [c for c in jar if isinstance(c, dict)]
    cookies_fn = getattr(context, "cookies", None)
    if callable(cookies_fn):
        try:
            jar = cookies_fn()
        except Exception:
            jar = None
        if isinstance(jar, list) and jar:
            return [c for c in jar if isinstance(c, dict)]
    return []


def wait_cdp_session_jar(context, *, timeout_sec: float = 4.0) -> list[dict]:
    """Chrome поднимает Cookies SQLite не мгновенно — ждём SID, иначе ложно «пусто»."""
    deadline = time.monotonic() + max(0.4, timeout_sec)
    last: list[dict] = []
    while True:
        last = cdp_cookie_jar(context)
        if jar_has_google_session(last):
            return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(0.35)


def jar_has_google_session(jar: list[dict]) -> bool:
    """В профиле уже есть залогиненная сессия Google (SID на google.com)."""
    for cookie in jar or []:
        name = str(cookie.get("name") or "")
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if name in _SESSION_NAMES and "google" in domain.split(".") and str(cookie.get("value") or ""):
            return True
    return False


def jar_to_cookies(jar: list[dict]) -> list[dict]:
    """CDP-cookie → формат cookie_parser (для inject_cookies)."""
    out: list[dict] = []
    for raw in jar or []:
        name = str(raw.get("name") or "")
        domain = str(raw.get("domain") or "")
        if not name or not is_auth_domain(domain):
            continue
        expires = raw.get("expires", -1)
        try:
            expires_i = int(float(expires))
        except (TypeError, ValueError):
            expires_i = -1
        if raw.get("session"):
            expires_i = -1
        same = str(raw.get("sameSite") or "Lax")
        if same.lower() in {"no_restriction", "unspecified"}:
            same = "None" if same.lower() == "no_restriction" else "Lax"
        item = {
            "name": name,
            "value": str(raw.get("value") or ""),
            "domain": domain,
            "path": str(raw.get("path") or "/") or "/",
            "expires": expires_i,
            "httpOnly": bool(raw.get("httpOnly", False)),
            "secure": bool(raw.get("secure", False)),
            "sameSite": same,
        }
        if name.startswith("__Host-"):
            item["domain"] = domain.lstrip(".")
        out.append(item)
    return out


def _read_snapshot(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    items = data.get("cookies") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [c for c in items if isinstance(c, dict) and c.get("name")]


def load_live_cookies(account_dir) -> list[dict]:
    return _read_snapshot(live_cookies_path(account_dir))


def load_live_cookies_backup(account_dir) -> list[dict]:
    if not account_dir:
        return []
    return _read_snapshot(Path(account_dir) / LIVE_COOKIES_BACKUP_NAME)


def live_cookies_mtime(account_dir) -> float:
    path = live_cookies_path(account_dir)
    try:
        return path.stat().st_mtime if path is not None and path.is_file() else 0.0
    except OSError:
        return 0.0


def profile_cookie_store_mtime(profile_dir) -> float:
    """Когда Chrome последний раз записал cookies на диск (Default/Network/Cookies)."""
    if not profile_dir:
        return 0.0
    base = Path(profile_dir) / "Default"
    best = 0.0
    for folder in (base / "Network", base):
        for name in ("Cookies", "Cookies-journal", "Cookies-wal"):
            path = folder / name
            try:
                if path.is_file():
                    best = max(best, path.stat().st_mtime)
            except OSError:
                pass
    return best


def rotating_auth_state(cookies: list[dict]) -> dict[str, str]:
    """{name@domain: value} для ротируемых auth-cookie на google.com/youtube.com."""
    state: dict[str, str] = {}
    for cookie in cookies or []:
        name = str(cookie.get("name") or "")
        if name not in ROTATING_AUTH_NAMES:
            continue
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if not (domain.endswith("google.com") or domain.endswith("youtube.com")):
            continue
        state[f"{name}@{domain}"] = str(cookie.get("value") or "")
    return state


def profile_behind_snapshot(jar: list[dict], snapshot: list[dict]) -> list[str]:
    """Какие ротируемые токены в профиле отличаются от снимка (или отсутствуют)."""
    if not snapshot:
        return []
    have = rotating_auth_state(jar)
    want = rotating_auth_state(snapshot)
    return sorted(key for key, value in want.items() if have.get(key) != value)


def snapshot_is_fresher(account_dir, profile_dir, *, slack_sec: float = 3.0) -> bool:
    """Снимок сделан не раньше, чем Chrome последний раз сохранил cookies на диск.

    После launch Chrome сразу трогает Cookies — mtime профиля новее снимка почти всегда.
    Для решения «восстанавливать ли» используйте snapshot_stronger_than_jar.
    """
    snap = live_cookies_mtime(account_dir)
    if snap <= 0:
        return False
    store = profile_cookie_store_mtime(profile_dir)
    return snap + slack_sec >= store


def snapshot_stronger_than_jar(snapshot: list[dict], jar: list[dict]) -> bool:
    """Снимок полнее/свежее того, что Chrome загрузил (неполный WAL, убитый процесс)."""
    if not snapshot or not jar_has_google_session(snapshot):
        return False
    # Если профиль уже отдал SID, он является источником истины: Chrome/Google
    # могли ротировать PSIDTS после снимка, а направление по значениям определить
    # нельзя. Старый снимок поверх живого jar — прямой путь к разлогину.
    return not jar_has_google_session(jar)


def snapshot_weaker_than(new_cookies: list[dict], old_cookies: list[dict]) -> bool:
    """Новый снимок хуже старого — не затираем хорошее состояние разлогином.

    Google при ротации меняет значение токена, но не удаляет его. Пропавший
    auth-cookie на google.com/youtube.com — признак, что сессию начали сносить
    (например, после «Verify it's you»).
    """
    if not old_cookies:
        return False
    if not jar_has_google_session(new_cookies):
        return True
    old_rot = rotating_auth_state(old_cookies)
    new_rot = rotating_auth_state(new_cookies)
    missing = [key for key in old_rot if key not in new_rot]
    if missing:
        return True
    return len(new_cookies) + 15 < len(old_cookies)


def same_cookie_set(a: list[dict], b: list[dict]) -> bool:
    """Одинаковые cookies (без учёта времени снимка)."""
    def key(c: dict) -> tuple:
        return (
            str(c.get("name") or ""),
            str(c.get("domain") or "").lstrip(".").lower(),
            str(c.get("path") or "/"),
            str(c.get("value") or ""),
        )
    return sorted(key(c) for c in a or []) == sorted(key(c) for c in b or [])


def decide_cookie_action(
    profile_jar: list[dict],
    live: list[dict],
    *,
    has_cookie_store: bool,
) -> tuple[str, list[dict], list[dict]]:
    """Что делать при входе: reuse / restore_live / probe_profile / inject_dump.

    reuse — в Chrome уже есть SID (повторный вход), лог не трогаем.
    restore_live — снимок прошлой сессии сильнее того, что в Chrome.
    inject_dump — ни сессии в Chrome, ни снимка: самый первый заход, льём файл лога.
    probe_profile — до запуска уже была Cookies DB, но SID ещё не прочитан. Сначала
    открываем YouTube без очистки; исходный дамп используем только после guest-probe.
    """
    recover = live if jar_has_google_session(live) else []
    if jar_has_google_session(profile_jar):
        return "reuse", [], recover
    if recover:
        return "restore_live", live, recover
    if has_cookie_store:
        return "probe_profile", [], recover
    return "inject_dump", [], recover


def save_live_cookies(account_dir, context, *, reason: str = "") -> int:
    """Снимок живых cookies. Если сессии нет или снимок слабее старого — не портим файл."""
    path = live_cookies_path(account_dir)
    if path is None:
        return 0
    jar = cdp_cookie_jar(context)
    if not jar_has_google_session(jar):
        return 0
    cookies = jar_to_cookies(jar)
    if not cookies:
        return 0
    old = _read_snapshot(path)
    if snapshot_weaker_than(cookies, old):
        return 0
    if old and same_cookie_set(cookies, old):
        # Ничего не поменялось — не трогаем ни снимок, ни резерв (иначе резерв
        # каждую минуту становится копией текущего и теряет старое хорошее состояние).
        return len(cookies)
    payload = {
        "saved_at": time.time(),
        "reason": str(reason or ""),
        "cookies": cookies,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    backup = path.with_name(LIVE_COOKIES_BACKUP_NAME)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if old and path.is_file():
            shutil.copy2(path, backup)
        os.replace(tmp, path)
    except Exception:
        return 0
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return len(cookies)
