"""Windows: v2rayN / системный прокси vs прокси аккаунта.

Chrome аккаунта всегда стартует с явным --proxy-server (relay) или --no-proxy-server,
поэтому системный прокси Windows (v2rayN «System proxy») ему не нужен и трогать его
нельзя: выключение ProxyEnable отрубало интернет всем остальным программам на ПК
(YouTube и т.п.), а при жёсткой остановке (taskkill) настройка не восстанавливалась.
Старое поведение (выключать на время сессии) — только через YT_SUPPRESS_SYSTEM_PROXY=1.
"""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass, field

_WIN_INET = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
_V2RAY_PORTS = (10808, 7890)
SUPPRESS_ENV = "YT_SUPPRESS_SYSTEM_PROXY"


def suppress_enabled() -> bool:
    """Выключать системный прокси Windows на время сессии — только по явному opt-in."""
    return os.environ.get(SUPPRESS_ENV, "").strip().lower() in ("1", "on", "yes", "true")
_REG_DWORD_KEYS = ("ProxyEnable", "AutoDetect")
_REG_SZ_KEYS = ("ProxyServer", "ProxyOverride", "AutoConfigURL")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


def v2ray_listening() -> bool:
    return any(_port_open(p) for p in _V2RAY_PORTS)


def read_proxy_enable() -> int:
    if sys.platform != "win32":
        return 0
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET) as key:
            return int(winreg.QueryValueEx(key, "ProxyEnable")[0])
    except OSError:
        return 0


def print_v2ray_health() -> None:
    """v2rayN: System Proxy ON, но xray не слушает → Chrome зависает на SYN_SENT."""
    if sys.platform != "win32":
        return
    if read_proxy_enable() and not v2ray_listening():
        print("=== v2rayN ===")
        print("  ! Системный прокси Windows включён (127.0.0.1:10808), но xray не запущен.")
        print("  ! Chrome/Edge могут зависать на белом экране (SYN_SENT к :10808).")
        print("  → В v2rayN нажмите «Run» / перезапустите ядро (настройки outbound не трогаем).")
        print("  · Системный прокси Windows скрипт не трогает — Chrome идёт со своим --proxy-server.")
        print()


def system_proxy_active() -> bool:
    """Системный прокси/PAC включён (v2rayN, Clash и т.п.)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET) as key:
            if int(winreg.QueryValueEx(key, "ProxyEnable")[0]):
                return True
            try:
                if int(winreg.QueryValueEx(key, "AutoDetect")[0]):
                    return True
            except OSError:
                pass
            try:
                if str(winreg.QueryValueEx(key, "AutoConfigURL")[0]).strip():
                    return True
            except OSError:
                pass
    except OSError:
        pass
    return False


@dataclass
class WindowsSystemProxyGuard:
    _saved: dict[str, int | str] = field(default_factory=dict)
    _active: bool = False

    @classmethod
    def suppress(cls) -> WindowsSystemProxyGuard | None:
        """По умолчанию ничего не меняет (guard неактивен) — см. докстринг модуля."""
        if sys.platform != "win32":
            return None
        if not suppress_enabled():
            return cls(_saved={}, _active=False)
        try:
            import winreg

            saved: dict[str, int | str] = {}
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET) as key:
                for name in _REG_DWORD_KEYS:
                    try:
                        saved[name] = int(winreg.QueryValueEx(key, name)[0])
                    except OSError:
                        pass
                for name in _REG_SZ_KEYS:
                    try:
                        saved[name] = str(winreg.QueryValueEx(key, name)[0])
                    except OSError:
                        pass

            guard = cls(_saved=saved, _active=False)
            if not saved.get("ProxyEnable") and not saved.get("AutoDetect") and not saved.get("AutoConfigURL"):
                return guard

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                winreg.SetValueEx(key, "AutoDetect", 0, winreg.REG_DWORD, 0)
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "")
                winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, "")
            guard._active = True
            return guard
        except OSError:
            return None

    def restore(self) -> None:
        if not self._active:
            return
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET, 0, winreg.KEY_SET_VALUE) as key:
                for name in _REG_DWORD_KEYS:
                    if name in self._saved:
                        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(self._saved[name]))
                for name in _REG_SZ_KEYS:
                    if name in self._saved:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(self._saved[name]))
        except OSError:
            pass
        self._active = False

    def __enter__(self) -> WindowsSystemProxyGuard:
        return self

    def __exit__(self, *_exc) -> None:
        self.restore()
