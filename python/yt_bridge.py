"""Мост к YouTube-профилям генератора (profiles_youtube_plain*).

Команды:
  check                        — проверка путей, python, ffmpeg, Chrome
  list                         — список профилей (JSON)
  launch --acc N --mode login|upload [--url URL]
        Готовит и запускает Chrome профиля с --remote-debugging-port,
        печатает {"type":"ready","port":...} и держит процесс, пока открыт stdin.
        При закрытии stdin (или строке "close") гасит Chrome и возвращает прокси/систему.
  kill --acc N                 — закрыть Chrome этого профиля и снять локи
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# Embedded Python (python312\python._pth) не добавляет папку скрипта в sys.path.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bridge_common import (  # noqa: E402
    emit,
    fail,
    log,
    result,
    run_main,
    setup_engine_paths,
    tg_root,
    yda_root,
    yt_cookies,
)

STUDIO_URL = "https://studio.youtube.com/"

PLATFORM_IDS = ("youtube", "rutube", "pinterest", "dzen", "tiktok", "vk", "instagram")
PLATFORM_NAMES = {
    "youtube": "YouTube",
    "rutube": "Rutube",
    "pinterest": "Pinterest",
    "dzen": "Дзен",
    "tiktok": "TikTok",
    "vk": "VK",
    "instagram": "Instagram",
}
OPEN_URL = {
    "youtube": STUDIO_URL,
    "rutube": "https://studio.rutube.ru",
    "pinterest": "https://www.pinterest.com",
    "dzen": "https://dzen.ru",
    "tiktok": "https://www.tiktok.com/login",
    "vk": "https://vk.ru",
    "instagram": "https://www.instagram.com/accounts/login/",
}


def _platform(raw: str) -> str:
    value = str(raw or "youtube").strip().lower()
    if value not in PLATFORM_IDS:
        raise ValueError(f"Неизвестная площадка: {raw}")
    return value


# Типовые разрешения отпечатка. Берём только те, что влезают в монитор.
_SCREEN_CHOICES = (
    (2560, 1440),
    (1920, 1080),
    (1680, 1050),
    (1600, 900),
    (1536, 864),
    (1440, 900),
    (1366, 768),
    (1280, 720),
)


def _screen_from_env() -> tuple[int, int, int] | None:
    """Размер от Electron (REELS_SCREEN_CSS / REELS_SCREEN_SCALE). На Windows переменные не задаются."""
    raw = str(os.environ.get("REELS_SCREEN_CSS") or "").strip().lower().replace(" ", "")
    parts = raw.split("x")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    css_w = max(800, int(parts[0]))
    css_h = max(640, int(parts[1]))
    scale_raw = str(os.environ.get("REELS_SCREEN_SCALE") or "").strip()
    scale = int(scale_raw) if scale_raw.isdigit() else 100
    scale = min((100, 125, 150, 175, 200), key=lambda step: abs(step - scale))
    return css_w, css_h, scale


def _real_css_screen() -> tuple[int, int, int]:
    """Рабочая область в CSS-пикселях и масштаб 100/125/150/…. Не больше реального монитора."""
    if sys.platform != "win32":
        return _screen_from_env() or (1280, 720, 100)
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        # PER_MONITOR_AWARE_V2 — размеры приходят в физических пикселях.
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    rect = wintypes.RECT()
    if user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
        phys_w = int(rect.right - rect.left)
        phys_h = int(rect.bottom - rect.top)
    else:
        phys_w = int(user32.GetSystemMetrics(0))
        phys_h = int(user32.GetSystemMetrics(1))
    hdc = user32.GetDC(0)
    dpi = int(ctypes.WinDLL("gdi32").GetDeviceCaps(hdc, 88) or 96)
    user32.ReleaseDC(0, hdc)
    raw = dpi / 96 * 100
    scale = min((100, 125, 150, 175, 200), key=lambda step: abs(step - raw))
    dpr = scale / 100
    css_w = max(800, int(phys_w / dpr))
    css_h = max(640, int(phys_h / dpr))
    return css_w, css_h, scale


def _pick_screen(css_w: int, css_h: int) -> tuple[int, int]:
    fit = [size for size in _SCREEN_CHOICES if size[0] <= css_w and size[1] <= css_h]
    if fit:
        return fit[0]
    width = css_w - (css_w % 2)
    height = css_h - (css_h % 2)
    return max(800, width), max(600, height)


def _fit_profile_screen(profile: Path) -> tuple[int, int, int]:
    """Экран отпечатка не больше реального ПК. Уже влезший размер не меняем — только ужимаем слишком большой."""
    css_w, css_h, scale = _real_css_screen()
    width, height = _pick_screen(css_w, css_h)
    pc_path = profile / "pc_info.json"
    data = None
    if pc_path.is_file():
        try:
            data = json.loads(pc_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            raw = str(data.get("ScreenSize") or "")
            parts = raw.lower().replace(" ", "").split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                have_w, have_h = int(parts[0]), int(parts[1])
                if have_w <= css_w and have_h <= css_h and have_w >= 800 and have_h >= 600:
                    width, height = have_w, have_h
            data["ScreenSize"] = f"{width}x{height}"
            data["Scale"] = scale
            pc_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assign = profile / ".yt_fp_assign.json"
    if assign.is_file():
        try:
            meta = json.loads(assign.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = None
        if isinstance(meta, dict):
            meta["screen"] = f"{width}x{height}"
            assign.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Экран профиля {width}x{height}, масштаб {scale}% — в пределах монитора {css_w}x{css_h}")
    return width, height, scale


def _window_args(width: int, height: int) -> list[str]:
    """Окно чуть ниже экрана: панель задач и шапка Chrome не прячут кнопку публикации."""
    inner_h = max(600, height - 80)
    return [f"--window-size={width},{inner_h}", "--window-position=0,0"]


def _sanitize_window_args(args: list[str], width: int, height: int) -> list[str]:
    cleaned = [
        str(item)
        for item in args
        if not str(item).startswith("--window-size=")
        and not str(item).startswith("--force-device-scale-factor")
        and str(item) != "--start-maximized"
    ]
    return cleaned + _window_args(width, height)


# ---------------------------------------------------------------- helpers


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_cdp(port: int, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                if isinstance(data, dict) and data.get("webSocketDebuggerUrl"):
                    return data
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(0.4)
    raise TimeoutError(f"Chrome не открыл CDP-порт {port}: {last}")


def _taskkill_tree(pid: int) -> None:
    if not pid:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        return
    try:
        pgid = os.getpgid(pid)
        if pgid == pid:
            os.killpg(pgid, 9)
            return
    except Exception:
        pass
    try:
        os.kill(pid, 9)
    except Exception:
        pass


def _folder_name(platform: str, number: int) -> str:
    import plain_profiles

    n = int(number)
    if n < 1:
        raise ValueError("Номер профиля должен быть >= 1")
    if platform == "youtube":
        return plain_profiles.profile_folder_name(n)
    if n == 1:
        return f"profiles_{platform}_plain"
    return f"profiles_{platform}_plain_{n}"


def _parse_number(platform: str, name: str) -> int | None:
    import plain_profiles

    if platform == "youtube":
        return plain_profiles.profile_number_from_name(name)
    match = re.fullmatch(rf"profiles_{re.escape(platform)}_plain(?:_(\d+))?", str(name or ""), re.I)
    if not match:
        return None
    raw = match.group(1)
    return 1 if raw is None else int(raw)


def _profile_dir(platform: str, acc: int) -> Path:
    import plain_profiles

    vk = plain_profiles.read_vk_bot_dir(yda_root())
    return Path(vk) / _folder_name(platform, int(acc))


def _hold_until_close(on_close) -> None:
    """Блокируется, пока Electron не закроет stdin или не пришлёт "close"."""
    try:
        for raw in sys.stdin:
            line = (raw or "").strip().lower()
            if line in {"close", "quit", "exit"}:
                break
    except Exception:
        pass
    finally:
        try:
            on_close()
        except Exception as exc:  # noqa: BLE001
            log(f"cleanup: {exc}")


# ---------------------------------------------------------------- commands


def cmd_check() -> int:
    data: dict = {
        "python": sys.version.split()[0],
        "pythonExe": sys.executable,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "tgRoot": "",
        "ytCookies": "",
        "vkBot": "",
        "chrome": "",
        "problems": [],
    }
    try:
        data["tgRoot"] = str(tg_root())
    except Exception as exc:  # noqa: BLE001
        data["problems"].append(str(exc))
    cookies = yt_cookies()
    data["ytCookies"] = str(cookies) if cookies else ""
    try:
        setup_engine_paths()
    except Exception as exc:  # noqa: BLE001
        data["problems"].append(str(exc))
    try:
        import plain_profiles

        vk_bot = plain_profiles.read_vk_bot_dir(yda_root())
        data["vkBot"] = str(vk_bot)
        try:
            data["chrome"] = str(plain_profiles.find_google_chrome())
        except Exception:
            pass
    except Exception:
        # внешние профили — не обязательны для склейки
        pass
    if not data["ffmpeg"]:
        data["problems"].append("ffmpeg не найден в PATH (нужен для генератора)")
    if not data["ffprobe"]:
        data["problems"].append("ffprobe не найден в PATH (нужен для генератора)")
    data["ok"] = not data["problems"]
    result(data)
    return 0


def _proxy_info(profile: Path) -> dict:
    info = {"proxyLabel": "", "proxyIp": ""}
    try:
        from proxy_binding import load_bound_proxy

        bound = load_bound_proxy(profile)
        if bound:
            info["proxyLabel"] = str(bound.safe_label or "")
            info["proxyIp"] = str(bound.public_ip or "")
    except Exception:
        pass
    return info


def _scan_platform(platform: str) -> list[dict]:
    import plain_profiles

    if platform == "youtube":
        try:
            import account_manager
        except Exception:  # noqa: BLE001
            account_manager = None  # type: ignore[assignment]
        accounts = plain_profiles.scan_plain_accounts(yda_root())
        out: list[dict] = []
        for acc in accounts:
            if account_manager is not None:
                try:
                    account_manager.apply_table_overrides(acc)
                except Exception:
                    pass
            number = int(acc.get("number") or 0)
            folder = Path(str(acc.get("path") or ""))
            item = {
                "platform": "youtube",
                "number": number,
                "name": str(acc.get("name") or f"YouTube #{number}").strip(),
                "path": str(folder),
                "bound": [str(b) for b in (acc.get("bound") or [])],
                "dateAdded": str(acc.get("date_added") or ""),
                "locked": (folder / "SingletonLock").exists() if folder.is_dir() else False,
            }
            item.update(_proxy_info(folder))
            out.append(item)
        return out

    vk = Path(plain_profiles.read_vk_bot_dir(yda_root()))
    out = []
    if not vk.is_dir():
        return out
    title = PLATFORM_NAMES[platform]
    try:
        children = list(vk.iterdir())
    except OSError:
        return out
    for item_path in children:
        if not item_path.is_dir():
            continue
        number = _parse_number(platform, item_path.name)
        if number is None:
            continue
        try:
            added = datetime.fromtimestamp(item_path.stat().st_ctime).strftime("%Y-%m-%d")
        except OSError:
            added = ""
        row = {
            "platform": platform,
            "number": number,
            "name": f"{title} #{number}",
            "path": str(item_path),
            "bound": [],
            "dateAdded": added,
            "locked": (item_path / "SingletonLock").exists(),
        }
        row.update(_proxy_info(item_path))
        out.append(row)
    out.sort(key=lambda row: int(row["number"]))
    return out


def cmd_list() -> int:
    setup_engine_paths()
    result(_scan_platform("youtube"))
    return 0


def cmd_list_all() -> int:
    setup_engine_paths()
    result({platform: _scan_platform(platform) for platform in PLATFORM_IDS})
    return 0


def _upload_proxy_args(profile: Path) -> tuple[list[str], object | None, dict | None, str]:
    """Прокси из .yt_proxy.json для обычного Chrome (как local_reels_upload: без моста, без CFT)."""
    try:
        from proxy_binding import load_bound_proxy

        bound = load_bound_proxy(profile)
    except Exception as exc:  # noqa: BLE001
        log(f"Прокси: не прочитан ({exc}) — IP компьютера")
        return [], None, None, ""
    if not bound:
        log("Прокси не привязан (.yt_proxy.json) — IP компьютера")
        return [], None, None, ""
    try:
        from chromium_proxy import prepare_chromium_proxy

        session = prepare_chromium_proxy(bound.playwright_proxy, allow_bridge=False, lan_bridge="")
        args = list(session.extra_launch_args or [])
        if not any(str(a).startswith("--proxy-server") for a in args):
            session.close()
            log("Прокси: нет --proxy-server — открываю без него")
            return [], None, None, ""
        label = str(getattr(session, "label", "") or bound.safe_label)
        log(f"Прокси: {label}")
        return args, session, dict(session.launch_env or {}) or None, label
    except Exception as exc:  # noqa: BLE001
        log(f"Прокси не поднялся ({exc}) — IP компьютера")
        return [], None, None, ""


def _launch_plain_chrome(
    profile: Path, port: int, url: str, window: tuple[int, int]
) -> tuple[subprocess.Popen, object | None, str]:
    import plain_profiles
    from upload_bridge import prepare_youtube_profile

    prepare_youtube_profile(profile, on_log=log)
    chrome = plain_profiles.find_google_chrome()
    proxy_args, session, env, label = _upload_proxy_args(profile)

    cmd: list[str] = [str(chrome), *proxy_args]
    cmd += [
        f"--user-data-dir={profile.resolve()}",
        f"--remote-debugging-port={int(port)}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=ru-RU",
        *_window_args(window[0], window[1]),
        "--disable-blink-features=AutomationControlled",
        "--disable-features=TranslateUI,Translate",
    ]
    if url:
        cmd.append(url)
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    launch_env = dict(env) if env else dict(os.environ)
    proc = subprocess.Popen(
        cmd,
        cwd=str(profile.parent),
        env=launch_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=(sys.platform != "win32"),
    )
    log(f"Google Chrome (обычный UI) | {profile.name}")
    return proc, session, label


def cmd_launch(platform: str, acc: int, mode: str, url: str) -> int:
    setup_engine_paths()
    try:
        platform = _platform(platform)
    except ValueError as exc:
        return fail(str(exc))
    profile = _profile_dir(platform, acc)
    if not profile.is_dir():
        return fail(f"Профиль {PLATFORM_NAMES[platform]} #{acc} не найден: {profile}")
    open_url = str(url or "").strip() or OPEN_URL[platform]
    try:
        win_w, win_h, _scale = _fit_profile_screen(profile)
    except Exception as exc:  # noqa: BLE001
        log(f"Экран не подогнал ({exc}) — окно 1280x720")
        win_w, win_h = 1280, 720

    port = _free_port()
    cleanup_fns: list = []
    meta: dict = {
        "type": "ready",
        "platform": platform,
        "acc": int(acc),
        "mode": mode,
        "port": port,
        "pid": 0,
        "profile": str(profile),
        "locale": "ru-RU",
        "timezoneId": "Europe/Moscow",
        "userAgent": "",
        "viewport": None,
        "proxyLabel": "",
        "antidetect": mode == "login",
    }

    if mode == "login":
        import yt_plain_launch

        prep = yt_plain_launch.prepare_plain_profile_launch(profile, on_log=log)
        if platform == "instagram" and "--disable-http3" not in prep.args:
            prep.args.append("--disable-http3")
        prep.args = _sanitize_window_args(list(prep.args), win_w, win_h)
        prep.viewport = {"width": win_w, "height": max(600, win_h - 80)}
        proc = yt_plain_launch.start_chrome_cdp(prep, port=port, open_url=open_url)
        cleanup_fns.append(lambda: yt_plain_launch.close_prep(prep))
        meta.update(
            {
                "locale": prep.locale,
                "timezoneId": prep.timezone_id,
                "userAgent": prep.user_agent,
                "viewport": prep.viewport,
                "proxyLabel": prep.proxy_label,
            }
        )
    else:
        proc, session, label = _launch_plain_chrome(profile, port, open_url, (win_w, win_h))
        if session is not None:
            cleanup_fns.append(session.close)
        meta["proxyLabel"] = label

    meta["pid"] = int(proc.pid)

    def _close_all() -> None:
        log(f"Закрываю Chrome профиля #{acc}")
        _taskkill_tree(int(proc.pid))
        try:
            from upload_bridge import _kill_chrome_using_profile

            _kill_chrome_using_profile(profile, on_log=None)
        except Exception:
            pass
        for fn in cleanup_fns:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                log(f"cleanup: {exc}")

    try:
        _wait_cdp(port, timeout=90.0)
    except Exception as exc:  # noqa: BLE001
        _close_all()
        return fail(str(exc))

    emit(meta)
    _hold_until_close(_close_all)
    emit({"type": "closed", "acc": int(acc)})
    return 0


def _create_other_profile(platform: str) -> tuple[int, Path]:
    import plain_profiles

    vk = Path(plain_profiles.read_vk_bot_dir(yda_root()))
    if not vk.is_dir():
        raise FileNotFoundError(f"Папка профилей не найдена: {vk}")
    numbers = [int(row["number"]) for row in _scan_platform(platform)]
    number = max(numbers, default=0) + 1
    profile = vk / _folder_name(platform, number)
    profile.mkdir(parents=True, exist_ok=False)
    title = PLATFORM_NAMES[platform]
    (profile / "ACCOUNT_NUMBER.txt").write_text(
        f"{title} #{number}\nЭта папка создана автоматически. Не переименовывайте её.\n",
        encoding="utf-8",
    )
    (profile / ".yt_plain.json").write_text(
        json.dumps(
            {"kind": "plain", "number": number, "platform": platform, "source": "reels-uploader"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return number, profile


def cmd_create(platform: str, proxy: str) -> int:
    """Новый профиль с уникальным отпечатком (create_plain_profile)."""
    setup_engine_paths()
    import account_manager

    try:
        platform = _platform(platform)
    except ValueError as exc:
        return fail(str(exc))
    raw = str(proxy or "").strip()
    parsed = None
    if raw:
        try:
            parsed = account_manager.parse_proxy_string_to_dict(raw)
        except Exception as exc:  # noqa: BLE001
            return fail(f"Прокси: {exc}. Нужен формат host:port:login:password")
    try:
        if platform == "youtube":
            number, profile = account_manager.create_plain_profile(yda_root(), status_callback=log, open_chrome=False)
        else:
            number, profile = _create_other_profile(platform)
            log(f"Создан профиль {PLATFORM_NAMES[platform]} #{number}: {profile}")
            account_manager._ensure_plain_fingerprint(profile, status_callback=log)
        _fit_profile_screen(profile)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))
    if parsed:
        if not account_manager.save_account_proxy(profile, parsed):
            return fail(f"Профиль #{number} создан, но прокси не записался в .yt_proxy.json")
        log(f"Прокси сохранён для #{number}")
    else:
        log(f"Прокси не задан — #{number} откроется с IP компьютера")
    result({"platform": platform, "number": int(number), "path": str(profile)})
    return 0


def cmd_delete(platform: str, acc: int) -> int:
    """Удаляет папку профиля даже если она привязана в daily-агенте. Chrome гасится перед этим."""
    setup_engine_paths()
    try:
        platform = _platform(platform)
    except ValueError as exc:
        return fail(str(exc))
    profile = _profile_dir(platform, acc)
    if not profile.is_dir():
        return fail(f"Профиль #{acc} не найден: {profile}")
    try:
        from upload_bridge import _kill_chrome_using_profile

        _kill_chrome_using_profile(profile, on_log=log)
    except Exception as exc:  # noqa: BLE001
        log(f"Chrome: {exc}")
    try:
        shutil.rmtree(profile)
    except Exception as exc:  # noqa: BLE001
        return fail(f"Не удалось удалить папку профиля #{acc}: {exc}")
    log(f"Профиль #{acc} удалён: {profile}")
    result({"number": int(acc), "deleted": True})
    return 0


def cmd_kill(platform: str, acc: int) -> int:
    setup_engine_paths()
    try:
        platform = _platform(platform)
    except ValueError as exc:
        return fail(str(exc))
    profile = _profile_dir(platform, acc)
    killed = 0
    try:
        from upload_bridge import _kill_chrome_using_profile, prepare_youtube_profile

        killed = _kill_chrome_using_profile(profile, on_log=log)
        try:
            prepare_youtube_profile(profile, on_log=log)
        except Exception as exc:  # noqa: BLE001
            log(str(exc))
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))
    result({"killed": killed})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube plain-profile bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("list")
    sub.add_parser("list-all")
    launch = sub.add_parser("launch")
    launch.add_argument("--platform", default="youtube")
    launch.add_argument("--acc", type=int, required=True)
    launch.add_argument("--mode", choices=("login", "upload"), default="login")
    launch.add_argument("--url", default="")
    kill = sub.add_parser("kill")
    kill.add_argument("--platform", default="youtube")
    kill.add_argument("--acc", type=int, required=True)
    create = sub.add_parser("create")
    create.add_argument("--platform", default="youtube")
    create.add_argument("--proxy", default="")
    delete = sub.add_parser("delete")
    delete.add_argument("--platform", default="youtube")
    delete.add_argument("--acc", type=int, required=True)
    args = parser.parse_args()

    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "list-all":
        return cmd_list_all()
    if args.cmd == "launch":
        return cmd_launch(str(args.platform), int(args.acc), str(args.mode), str(args.url or ""))
    if args.cmd == "kill":
        return cmd_kill(str(args.platform), int(args.acc))
    if args.cmd == "create":
        return cmd_create(str(args.platform), str(args.proxy or ""))
    if args.cmd == "delete":
        return cmd_delete(str(args.platform), int(args.acc))
    return fail(f"Неизвестная команда: {args.cmd}")


if __name__ == "__main__":
    run_main(main)
