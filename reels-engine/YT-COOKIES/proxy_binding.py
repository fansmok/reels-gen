"""Прокси на аккаунт: сохранение, проверка, ввод с консоли."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from pc_parser import check_proxy

META_FILE = ".yt_proxy.json"
INPUT_FORMAT = "host:port:user:password"


@dataclass
class BoundProxy:
    raw: str
    server: str
    username: str = ""
    password: str = ""
    public_ip: str = ""
    bound_at: str = ""

    @property
    def playwright_proxy(self) -> dict[str, str]:
        out: dict[str, str] = {"server": self.server}
        if self.username:
            out["username"] = self.username
            out["password"] = self.password
        return out

    @property
    def safe_label(self) -> str:
        """Строка для логов: пароль никогда не печатается."""
        raw = (self.raw or "").strip()
        if raw.count(":") >= 3:
            parts = raw.split(":")
            return f"{parts[0]}:{parts[1]}:{parts[2]}:***"
        if self.username:
            text = self.server if "://" in self.server else f"http://{self.server}"
            parsed = urlparse(text)
            host = parsed.hostname or ""
            try:
                port = parsed.port or ""
            except ValueError:
                port = ""
            if not host:
                rest = text.split("://", 1)[-1]
                bits = rest.split(":")
                host = bits[0]
                if len(bits) > 1:
                    port = bits[1]
            return f"{host}:{port}:{self.username}:***"
        return self.raw or self.server

    @property
    def display(self) -> str:
        if self.public_ip:
            return f"{self.safe_label} → {self.public_ip}"
        return self.safe_label

    @property
    def info_line(self) -> str:
        base = self.server
        if self.public_ip:
            return f"{base} → {self.public_ip}"
        return base


def _meta_path(account_dir: Path) -> Path:
    return account_dir.resolve() / META_FILE


def load_bound_proxy(account_dir: Path) -> BoundProxy | None:
    path = _meta_path(account_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("server"):
            return None
        raw = str(data.get("raw", ""))
        host = ""
        port = ""
        if raw.count(":") >= 3:
            parts = raw.split(":")
            host, port = parts[0], parts[1]
        else:
            server = str(data.get("server") or "")
            text = server if "://" in server else f"http://{server}"
            parsed = urlparse(text)
            host = parsed.hostname or ""
            try:
                port = str(parsed.port or "")
            except ValueError:
                return None
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            return None
        if "." not in host:
            return None
        return BoundProxy(
            raw=str(data.get("raw", "")),
            server=str(data["server"]),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            public_ip=str(data.get("public_ip", "")),
            bound_at=str(data.get("bound_at", "")),
        )
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def save_bound_proxy(account_dir: Path, binding: BoundProxy) -> None:
    if not binding.bound_at:
        binding.bound_at = datetime.now(timezone.utc).isoformat()
    path = _meta_path(account_dir)
    data = asdict(binding)
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                for key, value in old.items():
                    if key not in data:
                        data[key] = value
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _normalize_server(host: str, port: str, scheme: str = "http") -> str:
    host = host.strip()
    port = port.strip()
    if not host or not port.isdigit() or not (1 <= int(port) <= 65535):
        raise ValueError(f"некорректный host:port — {host}:{port}")
    host_ok = bool(re.fullmatch(r"(?:\d{1,3}|\*)(?:\.(?:\d{1,3}|\*)){3}", host)) or (
        "." in host and not host.startswith(".") and " " not in host
    )
    if not host_ok:
        raise ValueError(f"некорректный host:port — {host}:{port}")
    return f"{scheme}://{host}:{port}"


def _from_host_port_user_pass(
    raw: str,
    host: str,
    port: str,
    user: str,
    passwd: str,
    *,
    scheme: str = "http",
) -> BoundProxy:
    if not user:
        raise ValueError("логин не может быть пустым (формат host:port:user:password)")
    return BoundProxy(
        raw=raw,
        server=_normalize_server(host, port, scheme=scheme),
        username=user,
        password=passwd,
    )


def _parse_scheme_host_port_user_pass(raw: str) -> BoundProxy | None:
    """
    http://host:port:user:password — частый формат 9Proxy; urlparse его не понимает.
    """
    m = re.match(r"^(https?|socks5?)://(.+)$", raw, re.I)
    if not m:
        return None
    scheme = m.group(1).lower()
    parts = m.group(2).split(":")
    if len(parts) < 4:
        return None
    host, port, user = parts[0], parts[1], parts[2]
    passwd = ":".join(parts[3:])
    return _from_host_port_user_pass(raw, host, port, user, passwd, scheme=scheme)


def parse_proxy_input(text: str) -> BoundProxy:
    """
    Основной формат: host:port:user:password
    Также: host:port (без авторизации), http://user:pass@host:port,
    http://host:port:user:password (9Proxy)
    """
    raw = text.strip()
    if not raw:
        raise ValueError("пустой ввод")

    scheme_binding = _parse_scheme_host_port_user_pass(raw)
    if scheme_binding is not None:
        return scheme_binding

    if "://" in raw:
        parsed = urlparse(raw)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if not parsed.hostname or not port:
            raise ValueError(f"не удалось разобрать URL: {raw}")
        scheme = parsed.scheme or "http"
        server = f"{scheme}://{parsed.hostname}:{port}"
        return BoundProxy(
            raw=raw,
            server=server,
            username=parsed.username or "",
            password=parsed.password or "",
        )

    if "@" in raw:
        auth, hostport = raw.rsplit("@", 1)
        if auth.count(":") != 1:
            raise ValueError(f"формат {INPUT_FORMAT}")
        user, passwd = auth.split(":", 1)
        if hostport.count(":") != 1:
            raise ValueError(f"формат {INPUT_FORMAT}")
        host, port = hostport.split(":", 1)
        return _from_host_port_user_pass(raw, host, port, user, passwd)

    parts = raw.split(":")

    # host:port:user:password — password может содержать двоеточия
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        passwd = ":".join(parts[3:])
        return _from_host_port_user_pass(raw, host, port, user, passwd)

    if len(parts) == 2:
        host, port = parts
        return BoundProxy(raw=raw, server=_normalize_server(host, port))

    raise ValueError(f"формат: {INPUT_FORMAT}")


from chromium_proxy import ChromiumProxySession, prepare_chromium_proxy


def chromium_launch_proxy(proxy: dict[str, str] | None) -> dict[str, str] | None:
    """Прокси для Playwright (логин/пароль отдельно)."""
    if not proxy:
        return None

    server = str(proxy.get("server", "")).strip()
    if not server:
        return None

    if "://" not in server:
        server = f"http://{server}"

    out: dict[str, str] = {"server": server}
    username = str(proxy.get("username", ""))
    if username:
        out["username"] = username
        out["password"] = str(proxy.get("password", ""))
    return out


def detect_direct_ip(timeout: float = 8.0) -> str:
    """Публичный IP этого ПК без прокси — чтобы поймать утечку в Chrome."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in (
        "https://api.ipify.org",
        "http://ip-api.com/json/?fields=query",
    ):
        try:
            with opener.open(url, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace").strip()
            if "ip-api.com" in url:
                ip = str(json.loads(body).get("query", ""))
            else:
                ip = body
            if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip):
                return ip
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
            continue
    return ""


def detect_proxy_exit_ip(proxy: dict[str, str], timeout: float = 15.0) -> str:
    try:
        from proxy_relay import relay_proxy_for_checks

        proxy = relay_proxy_for_checks(proxy) or proxy
    except Exception:
        pass
    server = proxy["server"]
    if "://" not in server:
        server = f"http://{server}"

    if proxy.get("username"):
        parsed = urlparse(server)
        auth = f"{quote(proxy['username'])}:{quote(proxy.get('password', ''))}"
        server = f"{parsed.scheme}://{auth}@{parsed.hostname}:{parsed.port}"

    handler = urllib.request.ProxyHandler({"http": server, "https": server})
    opener = urllib.request.build_opener(handler)
    for url in (
        "http://ip-api.com/json/?fields=query",
        "https://api.ipify.org",
    ):
        try:
            with opener.open(url, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace").strip()
            if url.endswith("ipify.org"):
                if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", body):
                    return body
            else:
                data = json.loads(body)
                ip = str(data.get("query", ""))
                if ip:
                    return ip
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
            continue
    return ""


def _proxy_check_is_transient(detail: object) -> bool:
    low = str(detail or "").lower()
    return any(
        n in low
        for n in (
            "eof",
            "timeout",
            "timed out",
            "reset",
            "ssl",
            "urlerror",
            "refused",
            "aborted",
        )
    )


def _check_proxy_with_warmup(proxy: dict, *, fast: bool = False, tries: int = 4) -> tuple[bool, str]:
    """Новый Cliproxy часто отвечает SSL EOF первые несколько секунд."""
    last = "fail"
    attempts = max(1, int(tries))
    for attempt in range(attempts):
        ok, last = check_proxy(proxy, timeout=12.0, fast=fast)
        if ok:
            if attempt:
                print(f"  ✓ Прокси поднялся с {attempt + 1}-й попытки ({last})", flush=True)
            return True, last
        if attempt + 1 >= attempts or not _proxy_check_is_transient(last):
            break
        print(f"  Прокси ещё не готов ({last}), жду 2 с...", flush=True)
        time.sleep(2.2)
    return False, last


def _verify_binding(binding: BoundProxy, *, fast: bool = False) -> tuple[bool, str]:
    ok, detail = _check_proxy_with_warmup(binding.playwright_proxy, fast=fast)
    if not ok:
        return False, detail
    if not binding.public_ip:
        binding.public_ip = detect_proxy_exit_ip(binding.playwright_proxy)
    return True, detail


def prompt_proxy_input(*, fast_check: bool = False) -> BoundProxy | None:
    print(f"  Формат: {INPUT_FORMAT}")
    print("  Пример: 152.59.200.35:8080:myuser:mypass")
    while True:
        try:
            line = input("  Прокси: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not line:
            print("  ! Введите прокси (поле не может быть пустым).")
            continue
        try:
            binding = parse_proxy_input(line)
        except ValueError as exc:
            print(f"  ! {exc}")
            continue
        print("  Проверяю прокси...")
        ok, detail = _verify_binding(binding, fast=fast_check)
        if ok:
            if binding.public_ip:
                print(f"  ✓ Работает ({detail}), exit-IP: {binding.public_ip}")
            else:
                print(f"  ✓ Работает ({detail})")
            _print_stream_warning(detail, lan_bridge=fast_check)
            return binding
        print(f"  ! Не прошёл проверку: {detail}")


def _print_stream_warning(detail: str, *, lan_bridge: bool = False) -> None:
    if lan_bridge:
        return
    if "⚠" not in detail and "обрывается" not in detail:
        return
    print("  ! YouTube с этого ПК может не качаться — используйте Mac-мост (.lan_bridge).")


def _prompt_keep_or_change(
    saved: BoundProxy, *, alive: bool, detail: str, lan_bridge: bool = False
) -> bool | None:
    """True — оставить, False — сменить, None — отмена (Ctrl+C)."""
    if alive:
        print(f"  ✓ Прокси живой ({detail})")
        _print_stream_warning(detail, lan_bridge=lan_bridge)
        if saved.public_ip:
            print(f"  Exit-IP: {saved.public_ip}")
        print("  1 — оставить этот прокси")
        print("  2 — ввести другой")
        while True:
            try:
                choice = input("  Выбор (1/2, Enter=оставить): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if choice in ("", "1", "да", "yes", "y", "о", "оставить"):
                return True
            if choice in ("2", "нет", "no", "n", "с", "сменить", "другой"):
                return False
            print("  ! Введите 1, 2 или Enter")
    else:
        print(f"  ✗ Прокси мёртв: {detail}")
        print("  Нужен другой прокси.")
        try:
            input("  Enter — ввести новый прокси… ")
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        return False


def _upstream_diagnosis(proxy: dict) -> str:
    """Прямая TCP-диагностика upstream (proxy_diag из корня проекта); '' если недоступна/ок."""
    try:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import proxy_diag

        return proxy_diag.explain_dead_proxy(proxy)
    except Exception:
        return ""


def resolve_account_proxy(
    account_dir: Path,
    *,
    use_proxy: bool,
    fast_check: bool = False,
    keep_saved: bool = False,
) -> tuple[dict[str, str] | None, str, BoundProxy | None]:
    if not use_proxy:
        return None, "отключён (--no-proxy)", None

    account_dir = account_dir.resolve()
    saved = load_bound_proxy(account_dir)
    auto_keep = bool(keep_saved) or (not sys.stdin.isatty())

    print("=== Прокси ===")
    if saved:
        print(f"  Привязан к аккаунту: {saved.display}")
        print("  Проверяю прокси...")
        ok, detail = _check_proxy_with_warmup(saved.playwright_proxy, fast=fast_check)
        if ok:
            ip = detect_proxy_exit_ip(saved.playwright_proxy)
            if ip:
                saved.public_ip = ip
            save_bound_proxy(account_dir, saved)

        if auto_keep:
            if ok:
                print(f"  ✓ Прокси живой ({detail})")
                if saved.public_ip:
                    print(f"  Exit-IP: {saved.public_ip}")
                print(f"  ✓ Использую сохранённый прокси из {META_FILE}")
                return saved.playwright_proxy, saved.info_line, saved
            print(f"  ✗ Прокси непригоден ({detail})")
            reason = _upstream_diagnosis(saved.playwright_proxy)
            try:
                from proxy_relay import chain_label

                via = chain_label()
            except Exception:
                via = ""
            if reason:
                print(f"  → {reason}")
                if via:
                    print(f"  · Проверка шла через {via}; прямая TCP-диагностика выше — без цепочки.")
            elif via:
                print(f"  → Проверка шла через {via}. Проверьте, что v2rayN подключён, или смените прокси.")
            else:
                print(
                    "  → С этого ПК Cliproxy напрямую не качает страницы. "
                    "Включите v2rayN (127.0.0.1:10808) или запустите через LAN-мост (без --no-bridge)."
                )
            return None, detail, saved

        choice = _prompt_keep_or_change(saved, alive=ok, detail=detail, lan_bridge=fast_check)
        if choice is None:
            return None, "прокси не выбран", None
        if choice:
            return saved.playwright_proxy, saved.info_line, saved

        print(f"  Введите новый прокси ({INPUT_FORMAT}).")
    else:
        print("  К аккаунту прокси не привязан.")
        if auto_keep:
            print(f"  ✗ Нет {META_FILE} — IP не к чему привязать")
            return None, "прокси не указан", None
        print(f"  Введите прокси ({INPUT_FORMAT}) перед запуском.")

    binding = prompt_proxy_input(fast_check=fast_check)
    if not binding:
        return None, "прокси не указан", None

    save_bound_proxy(account_dir, binding)
    print(f"  ✓ Прокси сохранён в {META_FILE}")
    return binding.playwright_proxy, binding.info_line, binding
