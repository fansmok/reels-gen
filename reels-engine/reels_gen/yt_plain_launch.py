"""Запуск внешнего YouTube-профиля с отпечатком и прокси."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ProgressCb = Callable[[str], None]


def _default_tg_root() -> Path:
    env = str(os.environ.get("REELS_TG_ROOT") or "").strip()
    if env:
        return Path(env)
    # reels-engine/ — родитель reels_gen/
    return Path(__file__).resolve().parent.parent


TG_ROOT = _default_tg_root()
_yt_env = str(os.environ.get("REELS_YT_COOKIES") or "").strip()
YT_COOKIES = Path(_yt_env) if _yt_env else (TG_ROOT / "YT-COOKIES")


@dataclass
class PlainLaunchPrep:
    profile_dir: Path
    chrome_exe: Path
    args: list[str]
    env: dict[str, str]
    locale: str = "ru-RU"
    timezone_id: str = "Europe/Moscow"
    viewport: dict[str, int] = field(default_factory=lambda: {"width": 1280, "height": 720})
    user_agent: str = ""
    fingerprint_js: str = ""
    proxy_session: Any = None
    sys_proxy_guard: Any = None
    pc: Any = None
    proxy_label: str = ""


def _log(cb: ProgressCb | None, msg: str) -> None:
    text = str(msg)
    # cp1251 console (Python 3.14 default on RU Windows) breaks on arrows etc.
    try:
        if cb:
            cb(text)
        else:
            print(text, flush=True)
    except UnicodeEncodeError:
        safe = text.encode("ascii", "replace").decode("ascii")
        try:
            if cb:
                cb(safe)
            else:
                print(safe, flush=True)
        except Exception:
            pass


def _ensure_yt_path() -> Path:
    yt = YT_COOKIES
    if not yt.is_dir():
        raise FileNotFoundError(f"Нет YT-COOKIES: {yt}")
    s = str(yt.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)
    return yt


def close_prep(prep: PlainLaunchPrep | None) -> None:
    if prep is None:
        return
    try:
        if prep.proxy_session is not None:
            prep.proxy_session.close()
    except Exception:
        pass
    try:
        guard = prep.sys_proxy_guard
        if guard is not None and hasattr(guard, "restore"):
            guard.restore()
        elif guard is not None and hasattr(guard, "__exit__"):
            guard.__exit__(None, None, None)
    except Exception:
        pass


def prepare_plain_profile_launch(
    profile_dir: Path,
    *,
    on_log: ProgressCb | None = None,
    no_proxy: bool = False,
    lan_bridge: str = "",
    no_bridge: bool = False,
) -> PlainLaunchPrep:
    """Готовит Chrome exe + args + env как run_plain (без Studio-автоматизации)."""
    _ensure_yt_path()

    from browser_isolation import (
        apply_isolation_preferences,
        ensure_browser_identity,
        prepare_profile_for_relaunch,
        release_chrome_profile_lock,
    )
    from chrome_binary import (
        apply_chrome_version_to_profile,
        cft_windows_proxy_args,
        resolve_chrome_for_existing_profile,
        write_cft_proxy_tls_policies,
    )
    from chrome_cdp_launch import (
        clear_profile_proxy,
        extract_proxy_server_from_args,
        sync_profile_proxy,
    )
    from chromium_proxy import (
        auto_no_bridge,
        chain_note,
        compact_chrome_launch_args,
        print_windows_proxy_warnings,
    )
    from fingerprint import (
        build_fingerprint_script,
        build_launch_args,
        fingerprint_extension_args,
        write_fingerprint_extension,
    )
    from pc_parser import apply_exit_ip_geo, parse_pc_info
    from plain_fingerprint import assignment_label, ensure_assigned
    from proxy_binding import (
        _check_proxy_with_warmup,
        detect_direct_ip,
        detect_proxy_exit_ip,
        load_bound_proxy,
        prepare_chromium_proxy,
    )
    from windows_proxy_isolate import WindowsSystemProxyGuard, system_proxy_active

    PROFILE_DIR = Path(profile_dir).resolve()
    if not PROFILE_DIR.is_dir():
        raise FileNotFoundError(f"Профиль не найден: {PROFILE_DIR}")

    _log(on_log, f"[YT-PLAIN] Профиль: {PROFILE_DIR.name}")
    _log(on_log, "[YT-PLAIN] Антидетект как в программе: отпечаток + CFT + прокси")

    n_stale = prepare_profile_for_relaunch(PROFILE_DIR)
    if n_stale:
        _log(on_log, f"[YT-PLAIN] Закрыт зависший Chrome этого профиля ({n_stale})")
    release_chrome_profile_lock(PROFILE_DIR)

    bound = None
    proxy = None
    proxy_label = ""
    if no_proxy:
        _log(on_log, "[YT-PLAIN] --no-proxy: сохранённый прокси не использую")
    else:
        bound = load_bound_proxy(PROFILE_DIR)
        proxy = bound.playwright_proxy if bound else None
        if bound:
            proxy_label = str(getattr(bound, "safe_label", "") or "")
            _log(on_log, f"[YT-PLAIN] Прокси профиля: {proxy_label}")
        else:
            _log(on_log, "[YT-PLAIN] Прокси не привязан (.yt_proxy.json) — IP компьютера")

    proxy_session = None
    sys_proxy_guard = None
    proxy_extra: list[str] = []
    use_mac_bridge = False

    if proxy:
        try:
            print_windows_proxy_warnings()
        except Exception:
            pass
        no_bridge = auto_no_bridge(no_bridge, lan_bridge)
        use_mac_bridge = sys.platform == "win32" and not no_bridge
        if no_bridge:
            os.environ.pop("YT_LAN_BRIDGE", None)
            _log(on_log, f"[YT-PLAIN] Без моста: Chrome через .yt_proxy.json{chain_note()}")
        _log(on_log, "[YT-PLAIN] Проверяю прокси…")
        ok, detail = _check_proxy_with_warmup(proxy, fast=use_mac_bridge)
        if not ok:
            _log(on_log, f"[YT-PLAIN] Прокси непригоден ({detail}) — открываю без него")
            proxy = None
            bound = None
            proxy_label = ""
        else:
            _log(on_log, f"[YT-PLAIN] Прокси живой ({detail})")

    if proxy:
        bridge_url = ""
        effective_lan_bridge = ""
        proxy_blocked = False
        if use_mac_bridge:
            from lan_bridge import prepare_mac_bridge, print_mac_bridge_help, resolve_lan_bridge_url

            bridge_url = resolve_lan_bridge_url(lan_bridge)
            if not bridge_url:
                try:
                    print_mac_bridge_help()
                except Exception:
                    pass
                _log(on_log, "[YT-PLAIN] Мост не найден — без прокси")
                proxy_blocked = True
            elif not prepare_mac_bridge(bridge_url, proxy):
                _log(on_log, "[YT-PLAIN] Мост не поднял прокси — без прокси")
                proxy_blocked = True
            else:
                effective_lan_bridge = bridge_url
        elif (not no_bridge) and str(lan_bridge or "").strip():
            effective_lan_bridge = str(lan_bridge).strip()
            if "://" not in effective_lan_bridge:
                effective_lan_bridge = f"http://{effective_lan_bridge}"
        if not proxy_blocked:
            try:
                proxy_session = prepare_chromium_proxy(
                    proxy,
                    allow_bridge=not no_bridge,
                    lan_bridge=effective_lan_bridge,
                )
            except RuntimeError as exc:
                _log(on_log, f"[YT-PLAIN] Прокси не готов: {exc} — без прокси")
                proxy_blocked = True
        if proxy_session is not None and not proxy_blocked:
            proxy_extra = list(proxy_session.extra_launch_args or [])
            if not extract_proxy_server_from_args(proxy_extra):
                _log(on_log, "[YT-PLAIN] Нет --proxy-server — без прокси")
                proxy_session.close()
                proxy_session = None
                proxy_blocked = True
            else:
                if proxy_session.label:
                    _log(on_log, f"[YT-PLAIN] {proxy_session.label}")
                sync_profile_proxy(PROFILE_DIR, proxy_extra)
                sys_proxy_guard = WindowsSystemProxyGuard.suppress()
                if sys_proxy_guard is not None and getattr(sys_proxy_guard, "_active", False):
                    _log(on_log, "[YT-PLAIN] Системный прокси Windows временно выключен")
                elif system_proxy_active():
                    _log(on_log, "[YT-PLAIN] Системный прокси не трогаю — только --proxy-server")
        if proxy_blocked:
            proxy = None
            bound = None
            proxy_label = ""
            proxy_extra = []

    if not proxy:
        clear_profile_proxy(PROFILE_DIR)

    release_chrome_profile_lock(PROFILE_DIR)

    info_path = ensure_assigned(PROFILE_DIR)
    _log(on_log, f"[YT-PLAIN] {assignment_label(PROFILE_DIR)}")
    pc = parse_pc_info(info_path)

    exit_ip = ""
    if bound is not None and getattr(bound, "public_ip", ""):
        exit_ip = str(bound.public_ip or "")
    elif proxy:
        exit_ip = detect_proxy_exit_ip(proxy) or ""
    if exit_ip:
        applied, geo_note = apply_exit_ip_geo(pc, exit_ip, force=True)
        if applied:
            _log(
                on_log,
                f"[YT-PLAIN] Geo по Exit-IP {exit_ip}: "
                f"{pc.exit_city or '—'} → {pc.timezone}, {pc.locale}",
            )
        elif geo_note:
            _log(on_log, f"[YT-PLAIN] {geo_note}")

    acc_key = f"plain:{PROFILE_DIR.name}"
    daily = resolve_chrome_for_existing_profile(acc_key, PROFILE_DIR)
    apply_chrome_version_to_profile(pc, daily.binary.version)
    chrome_exe = Path(daily.binary.executable)
    _log(
        on_log,
        f"[YT-PLAIN] Chrome {daily.binary.version} (CFT"
        f"{'' if daily.is_new_today else ', закреплён'})",
    )

    cft_major = pc.chrome_major or ""
    if cft_major:
        major_marker = PROFILE_DIR / ".cft_major"
        if major_marker.is_file():
            prev = major_marker.read_text(encoding="utf-8").strip()
            if prev and prev != cft_major:
                _log(on_log, f"[YT-PLAIN] CFT major {prev} → {cft_major} (профиль не стираю)")
        major_marker.write_text(cft_major, encoding="utf-8")

    browser_id = ensure_browser_identity(PROFILE_DIR, acc_key, pc)
    apply_isolation_preferences(PROFILE_DIR, proxied=bool(proxy))
    _log(on_log, f"[YT-PLAIN] Browser ID: {browser_id.instance_id[:16]}…")

    host_ip = ""
    if proxy:
        host_ip = detect_direct_ip(timeout=4.0) or ""
    fingerprint_js = build_fingerprint_script(
        pc,
        instance_id=browser_id.instance_id,
        account_key=acc_key,
        proxied=bool(proxy),
        host_public_ip=host_ip,
    )

    base_args = build_launch_args(pc, proxied=bool(proxy))
    if proxy and chrome_exe.is_file():
        write_cft_proxy_tls_policies(chrome_exe)
        base_args = base_args + cft_windows_proxy_args(pc.chrome_major or "")
    if fingerprint_js:
        ext_dir = write_fingerprint_extension(PROFILE_DIR, fingerprint_js)
        base_args = base_args + fingerprint_extension_args(ext_dir)
        _log(on_log, "[YT-PLAIN] Fingerprint extension подключено")

    launch_args = compact_chrome_launch_args(list(base_args) + list(proxy_extra))
    if proxy and not extract_proxy_server_from_args(launch_args):
        _log(on_log, "[YT-PLAIN] Прокси-флаг потерян — открываю без прокси")
        if proxy_session is not None:
            proxy_session.close()
            proxy_session = None
        proxy = None
        proxy_label = ""
        clear_profile_proxy(PROFILE_DIR)
        launch_args = compact_chrome_launch_args(list(base_args))
    if proxy:
        sync_profile_proxy(PROFILE_DIR, launch_args)

    launch_env = dict(os.environ)
    if pc.timezone:
        launch_env["TZ"] = pc.timezone

    try:
        vw = int(pc.viewport.get("width") if isinstance(pc.viewport, dict) else pc.viewport["width"])
        vh = int(pc.viewport.get("height") if isinstance(pc.viewport, dict) else pc.viewport["height"])
    except Exception:
        try:
            vw, vh = int(pc.viewport[0]), int(pc.viewport[1])
        except Exception:
            vw, vh = 1280, 720

    return PlainLaunchPrep(
        profile_dir=PROFILE_DIR,
        chrome_exe=chrome_exe,
        args=launch_args,
        env=launch_env,
        locale=str(pc.locale or "ru-RU"),
        timezone_id=str(pc.timezone or "Europe/Moscow"),
        viewport={"width": vw, "height": vh},
        user_agent=str(pc.user_agent or ""),
        fingerprint_js=fingerprint_js or "",
        proxy_session=proxy_session,
        sys_proxy_guard=sys_proxy_guard,
        pc=pc,
        proxy_label=proxy_label,
    )


def apply_fingerprint_after_connect(context: Any, prep: PlainLaunchPrep, on_log: ProgressCb | None = None) -> None:
    """После CDP-подключения — тот же apply_cdp_profile, что в run_plain."""
    if prep is None or prep.pc is None:
        return
    _ensure_yt_path()
    try:
        from fingerprint import apply_cdp_profile, inject_fingerprint_into_page

        apply_cdp_profile(
            context,
            prep.pc,
            fingerprint_js=prep.fingerprint_js or None,
            inject_on_new_document=False,
        )
        pages = list(getattr(context, "pages", []) or [])
        if pages and prep.fingerprint_js:
            inject_fingerprint_into_page(pages[0], prep.fingerprint_js)
        _log(on_log, "[YT-PLAIN] CDP fingerprint применён")
    except Exception as exc:
        _log(on_log, f"[YT-PLAIN] CDP fingerprint: {exc}")


def start_chrome_cdp(
    prep: PlainLaunchPrep,
    *,
    port: int,
    open_url: str | None = None,
) -> Any:
    """Запускает подготовленный CFT с remote-debugging-port (как GUI, но CDP для vk-bot)."""
    import subprocess

    udir = prep.profile_dir.resolve()
    cmd: list[str] = [str(prep.chrome_exe)]
    # proxy flags first (CFT Windows quirk)
    proxy_args = [a for a in prep.args if a.startswith("--proxy-server") or a.startswith("--proxy-bypass")]
    other = [a for a in prep.args if a not in proxy_args]
    cmd.extend(proxy_args)
    cmd.extend(other)
    for flag in (
        f"--user-data-dir={udir}",
        f"--remote-debugging-port={int(port)}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ):
        if flag not in cmd and not any(flag.split("=", 1)[0] == c.split("=", 1)[0] for c in cmd if "=" in c and "=" in flag):
            # avoid duplicate user-data-dir if already in args
            key = flag.split("=", 1)[0]
            if any(str(c).startswith(key + "=") or str(c) == key for c in cmd):
                continue
            cmd.append(flag)
    if open_url:
        cmd.append(str(open_url))

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    proc = subprocess.Popen(
        cmd,
        cwd=str(prep.chrome_exe.parent),
        env=prep.env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return proc
