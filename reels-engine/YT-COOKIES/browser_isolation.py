"""Уникальный browser instance на аккаунт + изоляция Chrome profile."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pc_parser import PCProfile

META_FILE = ".yt_browser_id.json"


@dataclass
class BrowserIdentity:
    instance_id: str
    account_key: str
    fingerprint_seed: int


def _derive_instance_id(account_key: str, profile: PCProfile) -> str:
    parts = [
        account_key,
        profile.machine_id,
        profile.guid,
        profile.hwid,
        profile.ip,
        profile.computer_name,
        profile.user_name,
    ]
    raw = "|".join(p.strip() for p in parts if p and str(p).strip())
    return hashlib.sha256(raw.encode()).hexdigest()


def fingerprint_seed_from_identity(instance_id: str, profile: PCProfile) -> int:
    raw = f"{instance_id}|{profile.machine_id}|{profile.ip}|{profile.computer_name}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)


def ensure_browser_identity(
    profile_dir: Path,
    account_key: str,
    profile: PCProfile,
) -> BrowserIdentity:
    """Стабильный уникальный ID браузера на аккаунт (не меняется между запусками)."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    meta_path = profile_dir / META_FILE

    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            iid = str(data.get("instance_id", ""))
            if len(iid) >= 32:
                return BrowserIdentity(
                    instance_id=iid,
                    account_key=str(data.get("account_key", account_key)),
                    fingerprint_seed=int(data.get("fingerprint_seed", 0))
                    or fingerprint_seed_from_identity(iid, profile),
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    instance_id = _derive_instance_id(account_key, profile)
    seed = fingerprint_seed_from_identity(instance_id, profile)
    identity = BrowserIdentity(
        instance_id=instance_id,
        account_key=account_key,
        fingerprint_seed=seed,
    )
    meta_path.write_text(
        json.dumps(
            {
                "instance_id": identity.instance_id,
                "account_key": identity.account_key,
                "fingerprint_seed": identity.fingerprint_seed,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return identity


def write_fresh_browser_identity(profile_dir: Path, account_key: str) -> BrowserIdentity:
    """Новый случайный Browser ID — иначе после сброса ID снова считается из information.txt."""
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    instance_id = secrets.token_hex(32)
    seed = int(secrets.token_hex(4), 16)
    identity = BrowserIdentity(
        instance_id=instance_id,
        account_key=str(account_key or ""),
        fingerprint_seed=seed,
    )
    (profile_dir / META_FILE).write_text(
        json.dumps(
            {
                "instance_id": identity.instance_id,
                "account_key": identity.account_key,
                "fingerprint_seed": identity.fingerprint_seed,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rebuilt": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return identity


def _read_chrome_json(path: Path) -> tuple[dict | None, bool]:
    """(data, existed). data is None если файл есть, но битый — перезаписывать нельзя (os_crypt)."""
    if not path.is_file():
        return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, True
    if not isinstance(data, dict):
        return None, True
    return data, True


def apply_isolation_preferences(profile_dir: Path, *, proxied: bool = False) -> None:
    """Create only normal profile defaults; proxy privacy settings are conditional."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    first_run = profile_dir / "First Run"
    if not first_run.exists():
        try:
            first_run.write_bytes(b"")
        except OSError:
            pass

    default_dir = profile_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"

    prefs, prefs_existed = _read_chrome_json(prefs_path)
    if prefs_existed and prefs is None:
        print("  ! Preferences профиля битые — не перезаписываю (иначе Chrome снесёт cookies)", flush=True)
    else:
        prefs = prefs or {}
        prefs.setdefault("browser", {})["has_seen_welcome_page"] = True
        prefs.setdefault("browser", {})["check_default_browser"] = False
        prefs["enable_do_not_track"] = False
        prefs.setdefault("safebrowsing", {})["enabled"] = True
        if proxied:
            prefs["dns_over_https"] = {"mode": "off", "templates": ""}
            prefs["webrtc"] = {
                "ip_handling_policy": "disable_non_proxied_udp",
                "multiple_routes_enabled": False,
                "nonproxied_udp_enabled": False,
            }
            prefs["dns_prefetching"] = {"enabled": False}
            prefs.setdefault("net", {})["network_prediction_options"] = 2
            prefs.setdefault("alternate_error_pages", {})["enabled"] = False
        else:
            # Не сохранять прокси-ограничения в обычном профильном запуске.
            prefs.pop("dns_over_https", None)
            prefs.pop("webrtc", None)
        try:
            prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    local_state_path = profile_dir / "Local State"
    local, local_existed = _read_chrome_json(local_state_path)
    if local_existed and local is None:
        print("  ! Local State битый — не трогаю (там ключ шифрования cookies)", flush=True)
        return
    if local_existed:
        local = local or {}
        before = json.dumps(local, sort_keys=True)
        if proxied:
            local.setdefault("dns_over_https", {})["mode"] = "off"
        else:
            local.pop("dns_over_https", None)
        if json.dumps(local, sort_keys=True) == before:
            return
    else:
        local = {}
        if proxied:
            local.setdefault("dns_over_https", {})["mode"] = "off"
    try:
        local_state_path.write_text(json.dumps(local, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def kill_all_chrome_processes() -> int:
    """Больше не убивает все chrome.exe — это закрывало чужие скрипты и Cliproxy.

    Оставлен как заглушка на случай старых вызовов. Используйте kill_chrome_for_profile.
    """
    return 0


def _ps_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _win_no_window() -> dict:
    if sys.platform != "win32":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def _chrome_pids_for_profile(profile_dir: Path) -> list[int]:
    """PID chrome/chromium с этим user-data-dir."""
    if sys.platform != "win32":
        return []
    profile_dir = Path(profile_dir).resolve()
    needle = str(profile_dir).replace("/", "\\").lower()
    marker_path = None
    try:
        fd, raw = tempfile.mkstemp(prefix="yt_kill_chrome_", suffix=".txt")
        marker_path = Path(raw)
        with open(fd, "w", encoding="utf-8") as handle:
            handle.write(needle)
        ps = (
            "$ErrorActionPreference = 'SilentlyContinue'\n"
            "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n"
            f"$needle = (Get-Content -LiteralPath {_ps_single_quote(str(marker_path))} "
            "-Encoding UTF8 | Select-Object -First 1).Trim()\n"
            "if (-not $needle) { return }\n"
            "$names = @('chrome.exe','chromium.exe','msedge.exe','crashpad_handler.exe')\n"
            "Get-CimInstance Win32_Process | Where-Object {\n"
            "  $names -contains $_.Name -and $_.CommandLine -and\n"
            "  $_.CommandLine.ToLower().Replace('/','\\').Contains($needle)\n"
            "} | ForEach-Object { $_.ProcessId }\n"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=25,
            **_win_no_window(),
        )
        return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    finally:
        if marker_path is not None:
            try:
                marker_path.unlink()
            except OSError:
                pass


def _kill_pid_tree(pid: int) -> None:
    if sys.platform != "win32":
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=8,
            **_win_no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _close_pid_gracefully(pid: int) -> None:
    """taskkill без /F = WM_CLOSE: Chrome закрывается штатно и сбрасывает Cookies на диск."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid)],
            capture_output=True,
            timeout=8,
            **_win_no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def kill_chrome_for_profile(profile_dir: Path, *, graceful_wait_sec: float = 6.0) -> int:
    """Завершить chrome/chromium с этим user-data-dir (иначе ProcessSingleton).

    Сначала штатное закрытие (иначе Chrome теряет свежие cookies и Google разлогинивает
    при следующем входе), принудительно — только если процесс не вышел сам.
    """
    profile_dir = Path(profile_dir).resolve()
    pids = _chrome_pids_for_profile(profile_dir)
    if not pids:
        return 0
    if graceful_wait_sec > 0:
        for pid in pids:
            _close_pid_gracefully(pid)
        deadline = time.monotonic() + graceful_wait_sec
        while time.monotonic() < deadline:
            time.sleep(0.4)
            if not _chrome_pids_for_profile(profile_dir):
                break
    for pid in _chrome_pids_for_profile(profile_dir):
        _kill_pid_tree(pid)
    time.sleep(1.2)
    release_chrome_profile_lock(profile_dir)
    return len(pids)


def chrome_profile_in_use(profile_dir: Path) -> bool:
    """True, если Chrome ещё держит этот user-data-dir (окно или процесс)."""
    profile_dir = Path(profile_dir)
    if not profile_dir.is_dir():
        return False
    return _profile_files_locked(profile_dir)


def _profile_files_locked(profile_dir: Path) -> bool:
    """True если lock-файлы или DIPS ещё держатся другим процессом."""
    profile_dir = Path(profile_dir)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
        path = profile_dir / name
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError:
            return True
    dips = profile_dir / "Default" / "DIPS"
    if dips.is_file():
        try:
            fd = os.open(str(dips), os.O_RDWR)
            os.close(fd)
        except OSError:
            return True
    lock = profile_dir / "Default" / "LOCK"
    if lock.is_file():
        try:
            lock.unlink()
        except OSError:
            return True
    return False


def wait_profile_unlocked(profile_dir: Path, *, timeout_sec: float = 8.0) -> bool:
    """Убить хвосты Chrome и дождаться, пока Windows отпустит файлы профиля."""
    profile_dir = Path(profile_dir).resolve()
    deadline = time.monotonic() + max(0.4, timeout_sec)
    while True:
        pids = _chrome_pids_for_profile(profile_dir)
        if pids:
            for pid in pids:
                _kill_pid_tree(pid)
            time.sleep(0.45)
        release_chrome_profile_lock(profile_dir)
        if not pids and not _profile_files_locked(profile_dir):
            return True
        if time.monotonic() >= deadline:
            release_chrome_profile_lock(profile_dir)
            return False
        time.sleep(0.35)


def rmtree_retry(path: Path, *, attempts: int = 10) -> None:
    """shutil.rmtree с повторами — на Windows DIPS/LOCK часто заняты 1–3 сек."""
    path = Path(path)
    last_err: OSError | None = None
    for i in range(max(1, attempts)):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            if not path.exists():
                return
        except OSError as exc:
            last_err = exc
            kill_chrome_for_profile(path)
            release_chrome_profile_lock(path)
            time.sleep(0.4 + i * 0.25)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    if path.exists() and last_err is not None:
        raise last_err


def release_chrome_profile_lock(profile_dir: Path) -> None:
    """Снять lock после аварийного закрытия Chrome (иначе launch_persistent_context падает)."""
    profile_dir = profile_dir.resolve()
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
        path = profile_dir / name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
        except OSError:
            pass
    for sub in ("Default", "System Profile"):
        lock = profile_dir / sub / "LOCK"
        try:
            if lock.is_file():
                lock.unlink()
        except OSError:
            pass


def _set_pref_exit_clean(path: Path) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    profile = data.setdefault("profile", {})
    profile["exit_type"] = "Normal"
    profile["exited_cleanly"] = True
    session = data.setdefault("session", {})
    session["restore_on_startup"] = 5
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def clear_chrome_session_restore(profile_dir: Path) -> None:
    """Убрать restore вкладок — иначе повторный запуск зависает на about:blank."""
    profile_dir = profile_dir.resolve()
    default_dir = profile_dir / "Default"
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        path = default_dir / name
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    sessions = default_dir / "Sessions"
    if sessions.is_dir():
        for path in sessions.iterdir():
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
    _set_pref_exit_clean(default_dir / "Preferences")
    _set_pref_exit_clean(profile_dir / "Local State")


_ALT_SVC_FILES = (
    "Network Persistent State",
    "TransportSecurity",
    "Reporting and NEL",
    "Network Action Predictor",
    "SCT Auditing Pending Reports",
)


def clear_cached_alt_svc(profile_dir: Path) -> None:
    """Сброс Alt-Svc/HSTS — иначе Chrome ходит на закэшированные IP Google мимо прокси."""
    default = Path(profile_dir) / "Default"
    for folder in (default, default / "Network"):
        if not folder.is_dir():
            continue
        for name in _ALT_SVC_FILES:
            path = folder / name
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass


def prepare_profile_for_relaunch(profile_dir: Path) -> int:
    """Убить хвосты, снять lock, отключить crash-restore перед повторным launch_persistent."""
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    killed = kill_chrome_for_profile(profile_dir)
    wait_profile_unlocked(profile_dir, timeout_sec=8.0 if killed else 2.0)
    release_chrome_profile_lock(profile_dir)
    clear_chrome_session_restore(profile_dir)
    clear_cached_alt_svc(profile_dir)
    return killed


def reset_browser_profile(profile_dir: Path, *, keep_browser_id: bool = True) -> None:
    """Сброс повреждённого Chrome profile (Browser ID сохраняется)."""
    profile_dir = profile_dir.resolve()
    browser_id_data: str | None = None
    bid_path = profile_dir / META_FILE
    if keep_browser_id and bid_path.is_file():
        try:
            browser_id_data = bid_path.read_text(encoding="utf-8")
        except OSError:
            browser_id_data = None

    if profile_dir.exists():
        wait_profile_unlocked(profile_dir, timeout_sec=10.0)
        try:
            rmtree_retry(profile_dir, attempts=8)
        except OSError as exc:
            # Не роняем запуск: частичный профиль лучше, чем PermissionError на DIPS.
            print(f"  ! browser_profile не удалился полностью ({exc})", flush=True)

    profile_dir.mkdir(parents=True, exist_ok=True)

    if browser_id_data:
        try:
            bid_path.write_text(browser_id_data, encoding="utf-8")
        except OSError:
            pass

    apply_isolation_preferences(profile_dir)
    release_chrome_profile_lock(profile_dir)
