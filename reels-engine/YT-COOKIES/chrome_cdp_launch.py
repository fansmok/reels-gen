"""Запуск Chrome for Testing напрямую + Patchright connect_over_cdp (Windows + прокси)."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CdpLaunchHandle:
    browser: Any
    context: Any
    process: subprocess.Popen[bytes]
    cdp_port: int

    def close(self) -> None:
        # browser.close() для connect_over_cdp только ОТКЛЮЧАЕТСЯ от Chrome, а
        # process.terminate() на Windows = TerminateProcess: Chrome не успевает
        # сбросить Cookies (SQLite пишется пачками ~30 с) — свежие __Secure-*PSIDTS
        # теряются, и на следующем входе Google разлогинивает. Поэтому сначала
        # штатное Browser.close по CDP и ждём, пока процесс сам завершится.
        graceful = False
        if self.process.poll() is None:
            try:
                session = self.browser.new_browser_cdp_session()
                try:
                    session.send("Browser.close")
                    graceful = True
                finally:
                    try:
                        session.detach()
                    except Exception:
                        pass
            except Exception:
                graceful = False
        try:
            self.browser.close()
        except Exception:
            pass
        if self.process.poll() is None and graceful:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


def find_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def wait_cdp_ready(port: int, *, timeout: float = 60.0) -> bool:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.15)
    return False


def apply_proxy_preference(profile_dir: Path, proxy_server: str) -> None:
    default_dir = profile_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    prefs: dict = {}
    if prefs_path.is_file():
        try:
            loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(loaded, dict):
            return
        prefs = loaded
    prefs["proxy"] = {
        "mode": "fixed_servers",
        "server": proxy_server,
        "bypass_list": "<-loopback>",
    }
    prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def extract_proxy_server_from_args(launch_args: list[str]) -> str:
    for arg in launch_args:
        if arg.startswith("--proxy-server="):
            return arg.split("=", 1)[1]
    return ""


def clear_profile_proxy(profile_dir: Path) -> None:
    """Убрать stale relay из Preferences — прокси задаёт Playwright/Chromium."""
    default_dir = profile_dir / "Default"
    prefs_path = default_dir / "Preferences"
    if not prefs_path.is_file():
        return
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if prefs.pop("proxy", None) is not None:
        prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def sync_profile_proxy(profile_dir: Path, launch_args: list[str]) -> str:
    """Preferences хранят старый relay-порт → ERR_PROXY_CONNECTION_FAILED без синка."""
    proxy_server = extract_proxy_server_from_args(launch_args)
    if proxy_server:
        apply_proxy_preference(profile_dir, proxy_server)
    return proxy_server


def _split_proxy_args(launch_args: list[str]) -> tuple[list[str], list[str]]:
    proxy_args: list[str] = []
    other: list[str] = []
    for arg in launch_args:
        if arg.startswith("--proxy-server") or arg.startswith("--proxy-bypass"):
            proxy_args.append(arg)
        else:
            other.append(arg)
    return proxy_args, other


def should_use_direct_cdp(chrome_exe: Path | None, proxy: dict[str, str] | None) -> bool:
    """CDP subprocess зависает на browser_profile (белый экран). Используем launch_persistent + relay."""
    del chrome_exe, proxy
    return False


def launch_cft_over_cdp(
    playwright: Any,
    *,
    chrome_exe: Path,
    profile_dir: Path,
    launch_args: list[str],
    headless: bool,
    env: dict[str, str] | None,
    proxy_session,
) -> CdpLaunchHandle:
    proxy_args, other_args = _split_proxy_args(launch_args)
    proxy_server = ""
    for arg in proxy_args:
        if arg.startswith("--proxy-server="):
            proxy_server = arg.split("=", 1)[1]
    if proxy_server:
        apply_proxy_preference(profile_dir, proxy_server)

    cdp_port = find_free_port()
    # --proxy-server первым: CFT 118–148 на Windows иногда игнорирует proxy, если флаг не в начале.
    cmd: list[str] = [str(chrome_exe)]
    cmd.extend(proxy_args)
    cmd.extend(other_args)
    cmd.extend(
        [
            f"--user-data-dir={profile_dir.resolve()}",
            f"--remote-debugging-port={cdp_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
        ]
    )
    if headless:
        cmd.append("--headless=new")

    run_env = env if env is not None else None
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(chrome_exe.parent),
        env=run_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    if not wait_cdp_ready(cdp_port):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise RuntimeError(
            "Chrome for Testing не открыл CDP (проверьте прокси и что chrome.exe не заблокирован)"
        )

    browser = playwright.chromium.connect_over_cdp(
        f"http://127.0.0.1:{cdp_port}",
        is_local=True,
    )
    if not browser.contexts:
        browser.close()
        proc.terminate()
        raise RuntimeError("Chrome CDP: нет browser context")
    return CdpLaunchHandle(
        browser=browser,
        context=browser.contexts[0],
        process=proc,
        cdp_port=cdp_port,
    )
