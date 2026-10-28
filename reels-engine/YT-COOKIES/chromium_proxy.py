"""Прокси для Chrome for Testing (Windows + разные major CFT)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

from proxy_relay import ProxyRelay, chain_healthy, chain_label, chain_socks, start_local_relay

PROXY_ENGINE = "cft-native-proxy-v16"
_AUTO_BRIDGE_ENV = "YT_AUTO_NO_BRIDGE"


def chain_note() -> str:
    """Подпись для логов: как relay ходит к прокси аккаунта."""
    label = chain_label()
    return f" (relay → {label} → прокси)" if label else ""


def auto_no_bridge(no_bridge: bool, lan_bridge: str = "") -> bool:
    """LAN-мост (второй ПК) не нужен, если на этом ПК есть локальный SOCKS5 (v2rayN).

    Мост был нужен только потому, что второй ПК ходит к Cliproxy через VPN, а прямое TCP
    с этого ПК провайдер режет. Через relay → v2rayN путь тот же, что у второго ПК.
    Явный --lan-bridge URL уважаем. YT_AUTO_NO_BRIDGE=0 — вернуть старое поведение.
    """
    if no_bridge or sys.platform != "win32":
        return no_bridge
    if os.environ.get(_AUTO_BRIDGE_ENV, "1").strip().lower() in ("0", "off", "no", "false"):
        return no_bridge
    manual = (lan_bridge or "").strip()
    if manual and "127.0.0.1" not in manual and "localhost" not in manual:
        return no_bridge
    chain = chain_socks(refresh=True)
    if chain is None:
        return no_bridge
    if not chain_healthy():
        print(
            f"  ! {chain_label()} слушает, но в интернет не выпускает (VPN-сервер не отвечает) — "
            "оставляю LAN-мост. Проверьте v2rayN."
        )
        return no_bridge
    print(f"  · LAN-мост не нужен: прокси пойдёт relay → {chain_label()} (как VPN второго ПК)")
    return True
_STRIP_DISABLE_FEATURES = frozenset({
    "NetworkService",
    "NetworkServiceInProcess",
})

_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
_WIN_INET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def detect_windows_system_proxy() -> tuple[bool, str]:
    """Системный прокси Windows (VPN/Clash/v2ray «System Proxy»)."""
    if sys.platform != "win32":
        return False, ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET_SETTINGS) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return False, ""
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except OSError:
                server = "?"
            return True, str(server).strip()
    except OSError:
        return False, ""


def print_windows_proxy_warnings() -> None:
    from windows_proxy_isolate import print_v2ray_health

    print_v2ray_health()
    active, server = detect_windows_system_proxy()
    if active:
        print("=== Системный прокси Windows ===")
        print(f"  · v2rayN: {server}")
        print("  · На время сессии скрипт выключит его — Chrome только через прокси аккаунта.")
        print()


def compact_chrome_launch_args(args: list[str]) -> list[str]:
    """Слить повторяющиеся --disable-features; оставить последний экземпляр остальных флагов."""
    features: list[str] = []
    merged: list[str] = []
    for arg in args:
        if arg.startswith("--disable-features="):
            for part in arg.split("=", 1)[1].split(","):
                name = part.strip()
                if name and name not in features and name not in _STRIP_DISABLE_FEATURES:
                    features.append(name)
            continue
        key = arg.split("=", 1)[0]
        merged = [a for a in merged if not a.split("=", 1)[0] == key]
        merged.append(arg)
    if features:
        merged.append("--disable-features=" + ",".join(features))
    return merged


def _host_resolver_rules(*exclude: str) -> str:
    """Chrome не резолвит YouTube локально (РФ/DNS) — CONNECT идёт на имя через relay."""
    parts = ["MAP * ~NOTFOUND", "EXCLUDE 127.0.0.1", "EXCLUDE localhost", "EXCLUDE ::1"]
    seen = {"127.0.0.1", "localhost", "::1", ""}
    for host in exclude:
        name = str(host or "").strip().strip("[]")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        parts.append(f"EXCLUDE {name}")
    return "--host-resolver-rules=" + ", ".join(parts)


def _proxy_launch_extra(*exclude_hosts: str) -> list[str]:
    """Минимум флагов — не ломать HTTP/2/NetworkService (на других ПК работает без них)."""
    return [
        "--disable-restore-session-state",
        "--hide-crash-restore-bubble",
        _host_resolver_rules(*exclude_hosts),
    ]


@dataclass
class ChromiumProxySession:
    playwright_proxy: dict[str, str] | None
    extra_launch_args: list[str]
    launch_env: dict[str, str] | None = None
    label: str = ""
    _relay: ProxyRelay | None = field(default=None, repr=False)

    def close(self) -> None:
        if self._relay is not None:
            self._relay.close()
            self._relay = None

    def relay_tunnels(self) -> int:
        """Сколько CONNECT Chrome открыл через локальный relay; -1 если relay нет."""
        if self._relay is None:
            return -1
        return int(self._relay.connect_ok)

    def relay_recent_hosts(self) -> list[str]:
        if self._relay is None:
            return []
        return self._relay.recent_hosts()

    def relay_hello_sizes(self) -> list[int]:
        if self._relay is None:
            return []
        return self._relay.hello_sizes()

    def relay_server_hello_sizes(self) -> list[int]:
        if self._relay is None:
            return []
        return self._relay.server_hello_sizes()


def _env_without_proxy() -> dict[str, str]:
    env = dict(os.environ)
    for key in _PROXY_ENV_KEYS:
        env.pop(key, None)
    return env


def _relay_session(relay: ProxyRelay, upstream_label: str) -> ChromiumProxySession:
    local = relay.proxy_server_arg
    extra = [
        f"--proxy-server={local}",
        "--proxy-bypass-list=<-loopback>",
        *_proxy_launch_extra(),
    ]
    via = chain_label()
    return ChromiumProxySession(
        playwright_proxy=None,
        extra_launch_args=extra,
        launch_env=_env_without_proxy(),
        label=(
            f"прокси relay 127.0.0.1 → {via} → {upstream_label}"
            if via
            else f"прокси relay 127.0.0.1 → {upstream_label}"
        ),
        _relay=relay,
    )


def _start_relay_or_fail(pw: dict[str, str], upstream_label: str) -> ChromiumProxySession:
    relay = start_local_relay(pw)
    return _relay_session(relay, upstream_label)


def prepare_chromium_proxy(
    proxy: dict[str, str] | None,
    *,
    headless: bool = False,
    direct_verified: bool = False,
    lan_bridge: str = "",
    allow_bridge: bool = True,
) -> ChromiumProxySession:
    del headless

    if not proxy:
        return ChromiumProxySession(None, [], None, "")

    server = str(proxy.get("server", "")).strip()
    if not server:
        return ChromiumProxySession(None, [], None, "")
    if "://" not in server:
        server = f"http://{server}"

    parsed = urlparse(server)
    upstream_label = f"{parsed.hostname}:{parsed.port or 80}"
    username = str(proxy.get("username", ""))

    bridge = ""
    if allow_bridge:
        bridge = (
            lan_bridge or os.environ.get("YT_LAN_BRIDGE") or str(proxy.get("lan_bridge", ""))
        ).strip()
    if bridge:
        if "://" not in bridge:
            bridge = f"http://{bridge}"
        bridge_parsed = urlparse(bridge)
        bridge_server = f"{bridge_parsed.hostname}:{bridge_parsed.port or 8765}"
        bridge_extras = [
            f"--proxy-server={bridge_server}",
            "--proxy-bypass-list=<-loopback>",
            *_proxy_launch_extra(bridge_parsed.hostname or ""),
        ]
        return ChromiumProxySession(
            playwright_proxy=None,
            extra_launch_args=bridge_extras,
            launch_env=_env_without_proxy(),
            label=(
                f"локальный мост {bridge} → {upstream_label}"
                if "127.0.0.1" in bridge or "localhost" in bridge
                else f"LAN-мост {bridge} → {upstream_label}"
            ),
        )

    if not username:
        # Локальные порты CliProxy.exe / relay: без логина, схема socks5 сохраняется для Chrome.
        server_arg = f"{parsed.hostname}:{parsed.port or 80}"
        if parsed.scheme.lower().startswith("socks"):
            server_arg = f"{parsed.scheme.lower()}://{server_arg}"
        extra = [
            f"--proxy-server={server_arg}",
            "--proxy-bypass-list=<-loopback>",
            *_proxy_launch_extra(parsed.hostname or ""),
        ]
        return ChromiumProxySession(
            playwright_proxy=None,
            extra_launch_args=extra,
            launch_env=_env_without_proxy(),
            label=f"прокси {upstream_label}",
        )

    pw = {
        "server": server,
        "username": username,
        "password": str(proxy.get("password", "")),
    }

    if sys.platform == "win32":
        # Без LAN-моста Chrome должен идти через купленный IP.
        # Native Playwright-auth на CFT часто не применяет прокси (реальный IP) —
        # поэтому запасной путь запрещён: либо relay/--proxy-server, либо не стартуем.
        try:
            return _start_relay_or_fail(pw, upstream_label)
        except Exception as exc:
            raise RuntimeError(
                f"локальный relay не стартовал ({exc.__class__.__name__}) — "
                "Chrome без --proxy-server не открываю (риск реального IP)"
            ) from exc

    try:
        relay = start_local_relay(pw)
    except Exception:
        relay = None
    if relay is not None:
        if direct_verified:
            return _relay_session(relay, upstream_label)
        try:
            from pc_parser import check_proxy

            if check_proxy(relay.playwright_proxy, timeout=15.0)[0]:
                return _relay_session(relay, upstream_label)
        except Exception:
            pass
        relay.close()

    proxy_url = _proxy_env_url(pw)
    env = dict(os.environ)
    for key in _PROXY_ENV_KEYS:
        env[key] = proxy_url
    return ChromiumProxySession(
        playwright_proxy=None,
        extra_launch_args=[],
        launch_env=env,
        label=f"прокси HTTP_PROXY → {upstream_label}",
    )


def _proxy_env_url(proxy: dict[str, str]) -> str:
    server = proxy["server"]
    if "://" not in server:
        server = f"http://{server}"
    parsed = urlparse(server)
    user = quote(str(proxy.get("username", "")), safe="")
    passwd = quote(str(proxy.get("password", "")), safe="")
    host = parsed.hostname or ""
    port = parsed.port or 80
    scheme = parsed.scheme or "http"
    return f"{scheme}://{user}:{passwd}@{host}:{port}"
