"""Локальный HTTP-прокси → upstream с логином (stdlib).

Цепочка через локальный SOCKS5 (v2rayN/Clash): с этого ПК прямое TCP к Cliproxy
режется провайдером (~16–26 КБ и стоп), а через VPN-туннель работает. Если
127.0.0.1:10808 слушает, upstream открывается так:
    relay → SOCKS5 127.0.0.1:10808 → Cliproxy (как SOCKS5 user/pass) → цель.
К Cliproxy идём по SOCKS5, а не HTTP CONNECT: xray со sniffing подменяет
назначение по заголовку Host и CONNECT зависает.

Управление: env YT_UPSTREAM_SOCKS = "off" | "auto" (по умолчанию) | "host:port".
"""

from __future__ import annotations

import base64
import os
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

CHAIN_ENV = "YT_UPSTREAM_SOCKS"
CHAIN_CANDIDATES: tuple[tuple[str, int], ...] = (("127.0.0.1", 10808), ("127.0.0.1", 7890))
_CHAIN_TTL = 5.0
_chain_lock = threading.Lock()
_chain_cache: tuple[float, tuple[str, int] | None] = (0.0, None)


def _parse_host_port(text: str, default_port: int = 10808) -> tuple[str, int] | None:
    raw = text.strip()
    if not raw:
        return None
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        try:
            port = parsed.port or default_port
        except ValueError:
            return None
        return (host, int(port)) if host else None
    host, _, port = raw.rpartition(":")
    if not host or not port.isdigit():
        return None
    return host, int(port)


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def chain_socks(*, refresh: bool = False) -> tuple[str, int] | None:
    """(host, port) локального SOCKS5, через который идём к upstream; None — напрямую."""
    global _chain_cache
    raw = os.environ.get(CHAIN_ENV, "auto").strip().lower()
    if raw in ("off", "0", "no", "false", "direct"):
        return None
    if raw not in ("", "auto", "1", "on", "yes", "true"):
        return _parse_host_port(raw)
    now = time.monotonic()
    with _chain_lock:
        ts, cached = _chain_cache
        if not refresh and now - ts < _CHAIN_TTL:
            return cached
    found: tuple[str, int] | None = None
    for host, port in CHAIN_CANDIDATES:
        if _port_open(host, port):
            found = (host, port)
            break
    with _chain_lock:
        _chain_cache = (now, found)
    return found


def chain_healthy(timeout: float = 6.0) -> bool:
    """Локальный SOCKS5 не просто слушает, а реально выпускает в интернет (VPN-сервер жив)."""
    chain = chain_socks()
    if chain is None:
        return False
    try:
        sock = _tcp_connect(chain[0], chain[1], timeout=timeout)
    except OSError:
        return False
    try:
        sock.settimeout(timeout)
        _socks5_connect(sock, "www.gstatic.com", 80)
        sock.sendall(b"HEAD /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\nConnection: close\r\n\r\n")
        return sock.recv(64).startswith(b"HTTP/1.")
    except OSError:
        return False
    finally:
        sock.close()


def chain_label() -> str:
    chain = chain_socks()
    if chain is None:
        return ""
    name = "v2rayN" if chain[1] == 10808 else "SOCKS5"
    return f"{name} {chain[0]}:{chain[1]}"


class TunnelRefused(OSError):
    """Upstream ответил не 200 — ответ надо отдать клиенту как есть."""

    def __init__(self, response: bytes):
        super().__init__(response[:120].decode("latin1", "replace"))
        self.response = response


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("SOCKS5: соединение закрыто")
        buf += chunk
    return buf


def _socks5_connect(sock: socket.socket, host: str, port: int, user: str = "", password: str = "") -> None:
    """SOCKS5 CONNECT на уже открытом сокете (RFC 1928/1929)."""
    sock.sendall(b"\x05\x02\x00\x02" if user else b"\x05\x01\x00")
    rep = _recv_exact(sock, 2)
    if rep[0] != 0x05:
        raise OSError(f"не SOCKS5: {rep!r}")
    if rep[1] == 0x02:
        u, p = user.encode("utf-8")[:255], password.encode("utf-8")[:255]
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        auth = _recv_exact(sock, 2)
        if auth[1] != 0x00:
            raise OSError("SOCKS5: логин/пароль отклонены")
    elif rep[1] != 0x00:
        raise OSError(f"SOCKS5: метод {rep[1]} не поддержан")
    try:
        addr = socket.inet_aton(host)
        req = b"\x05\x01\x00\x01" + addr
    except OSError:
        hb = host.encode("idna")
        req = b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb
    sock.sendall(req + int(port).to_bytes(2, "big"))
    head = _recv_exact(sock, 4)
    if head[1] != 0x00:
        raise OSError(f"SOCKS5: connect отказ {head[1]} ({host}:{port})")
    if head[3] == 0x01:
        _recv_exact(sock, 6)
    elif head[3] == 0x03:
        n = _recv_exact(sock, 1)[0]
        _recv_exact(sock, n + 2)
    elif head[3] == 0x04:
        _recv_exact(sock, 18)


def _read_headers(sock: socket.socket, initial: bytes = b"") -> tuple[bytes, bytes]:
    buf = initial
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def _inject_auth(header: bytes, auth_line: bytes) -> bytes:
    if b"Proxy-Authorization:" in header or not auth_line:
        return header
    return header + b"\r\n" + auth_line


def _connect_target(head: bytes) -> str:
    first = head.split(b"\r\n", 1)[0]
    parts = first.split()
    if len(parts) >= 2:
        return parts[1].decode("latin1", "replace")[:200]
    return "?"


def _split_host_port(target: str, default_port: int) -> tuple[str, int]:
    """'host:443' / '[::1]:443' / 'host' → (host, port)."""
    text = target.strip()
    if text.startswith("["):
        host, _, tail = text[1:].partition("]")
        port = tail[1:] if tail.startswith(":") else ""
    else:
        host, _, port = text.rpartition(":")
        if not host:
            host, port = port, ""
    if not port.isdigit():
        return host, default_port
    return host, int(port)


def _tune_socket(sock: socket.socket) -> None:
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass


def _tcp_connect(host: str, port: int, timeout: float = 25) -> socket.socket:
    """IPv4-only — меньше сюрпризов с v6/маршрутизацией на Windows."""
    last_err: OSError | None = None
    for info in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        fam, socktype, proto, _, addr = info
        sock = socket.socket(fam, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(addr)
            return sock
        except OSError as exc:
            last_err = exc
            sock.close()
    if last_err:
        raise last_err
    raise OSError(f"не удалось подключиться к {host}:{port}")


def _sendall_mtu(sock: socket.socket, data: bytes, mtu: int) -> None:
    view = memoryview(data)
    for i in range(0, len(data), mtu):
        sock.sendall(view[i : i + mtu])


def _pipe(src: socket.socket, dst: socket.socket, *, first_mtu: int = 0, on_first=None) -> None:
    first = True
    try:
        while True:
            data = src.recv(262144)
            if not data:
                break
            if first:
                first = False
                if on_first is not None:
                    try:
                        on_first(len(data))
                    except Exception:
                        pass
                if first_mtu > 0:
                    _sendall_mtu(dst, data, first_mtu)
                else:
                    dst.sendall(data)
            else:
                dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _tunnel(client: socket.socket, upstream: socket.socket, srv: "_RelayServer | None" = None) -> None:
    client.settimeout(None)
    upstream.settimeout(None)

    def on_client(n: int) -> None:
        if srv is not None:
            srv.note_hello_size(n)

    def on_up(n: int) -> None:
        if srv is not None:
            srv.note_server_hello_size(n)

    t1 = threading.Thread(
        target=_pipe,
        args=(client, upstream),
        kwargs={"first_mtu": 1200, "on_first": on_client},
        daemon=True,
    )
    t2 = threading.Thread(
        target=_pipe,
        args=(upstream, client),
        kwargs={"on_first": on_up},
        daemon=True,
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()


class UpstreamStore:
    """Потокобезопасный upstream для LAN-моста (--dynamic)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._host = ""
        self._port = 0
        self._auth = b""
        self._user = ""
        self._password = ""
        self._label = ""
        # None — не знаем; True/False — умеет ли этот upstream SOCKS5 (для цепочки)
        self._socks_ok: bool | None = None

    @property
    def label(self) -> str:
        with self._lock:
            return self._label

    def configured(self) -> bool:
        with self._lock:
            return bool(self._host)

    def set_from_proxy(self, proxy: dict[str, str]) -> str:
        server_url = str(proxy.get("server", "")).strip()
        if "://" not in server_url:
            server_url = f"http://{server_url}"
        parsed = urlparse(server_url)
        host = parsed.hostname or ""
        port = parsed.port or 80
        user = str(proxy.get("username", ""))
        password = str(proxy.get("password", ""))
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        auth_line = f"Proxy-Authorization: Basic {token}".encode()
        label = f"{host}:{port}:{user}:{password}" if user else f"{host}:{port}"
        with self._lock:
            changed = (host, port) != (self._host, self._port)
            self._host, self._port, self._auth, self._label = host, port, auth_line, label
            self._user, self._password = user, password
            if changed:
                self._socks_ok = None
        return label

    def credentials(self) -> tuple[str, str]:
        with self._lock:
            return self._user, self._password

    def socks_supported(self) -> bool | None:
        with self._lock:
            return self._socks_ok

    def note_socks(self, ok: bool) -> None:
        with self._lock:
            self._socks_ok = ok

    def open_tunnel(self, target_host: str, target_port: int, *, timeout: float = 20.0) -> tuple[socket.socket, bytes]:
        """TCP-туннель до target через upstream. Возвращает (сокет, «хвост» после ответа upstream).

        Напрямую: TCP → upstream, HTTP CONNECT + Proxy-Authorization.
        Через локальный SOCKS5 (v2rayN): SOCKS5 → upstream, затем к upstream по SOCKS5
        (user/pass); если upstream SOCKS5 не умеет — HTTP CONNECT через ту же цепочку.
        """
        host, port, auth_line = self.get()
        user, password = self.credentials()
        chain = chain_socks()
        if chain is None:
            upstream = _tcp_connect(host, port, timeout=timeout)
            try:
                return upstream, _http_connect(upstream, target_host, target_port, auth_line, timeout=timeout)
            except BaseException:
                upstream.close()
                raise

        if self.socks_supported() is not False:
            upstream = _tcp_connect(chain[0], chain[1], timeout=timeout)
            try:
                _tune_socket(upstream)
                upstream.settimeout(timeout)
                _socks5_connect(upstream, host, port)
                _socks5_connect(upstream, target_host, target_port, user, password)
                self.note_socks(True)
                return upstream, b""
            except OSError as exc:
                upstream.close()
                # Отказ именно рукопожатия с upstream (не SOCKS5) — запомнить и идти CONNECT.
                text = str(exc)
                if "не SOCKS5" in text or "метод" in text or "закрыто" in text:
                    self.note_socks(False)
                else:
                    raise
        upstream = _tcp_connect(chain[0], chain[1], timeout=timeout)
        try:
            _tune_socket(upstream)
            upstream.settimeout(timeout)
            _socks5_connect(upstream, host, port)
            return upstream, _http_connect(upstream, target_host, target_port, auth_line, timeout=timeout)
        except BaseException:
            upstream.close()
            raise

    def open_plain(self, *, timeout: float = 20.0) -> socket.socket:
        """Сокет до самого upstream (HTTP-прокси без туннеля) — напрямую или через цепочку."""
        host, port, _ = self.get()
        chain = chain_socks()
        if chain is None:
            return _tcp_connect(host, port, timeout=timeout)
        upstream = _tcp_connect(chain[0], chain[1], timeout=timeout)
        try:
            _tune_socket(upstream)
            upstream.settimeout(timeout)
            _socks5_connect(upstream, host, port)
            return upstream
        except BaseException:
            upstream.close()
            raise

    def set_from_line(self, line: str) -> str:
        raw = line.strip()
        parts = raw.split(":")
        if len(parts) < 4:
            raise ValueError("формат: host:port:user:password")
        host, port, user = parts[0], parts[1], parts[2]
        passwd = ":".join(parts[3:])
        if not port.isdigit():
            raise ValueError(f"некорректный порт: {port}")
        return self.set_from_proxy(
            {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": passwd,
            }
        )

    def get(self) -> tuple[str, int, bytes]:
        with self._lock:
            if not self._host:
                raise RuntimeError("upstream not configured")
            return self._host, self._port, self._auth


def _http_connect(upstream: socket.socket, host: str, port: int, auth_line: bytes, *, timeout: float) -> bytes:
    """HTTP CONNECT на открытом сокете; возвращает байты после заголовков ответа."""
    _tune_socket(upstream)
    upstream.settimeout(timeout)
    head = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}".encode("idna")
    upstream.sendall(_inject_auth(head, auth_line) + b"\r\n\r\n")
    up_head, up_rest = _read_headers(upstream)
    status = up_head.split(b"\r\n", 1)[0] if up_head else b""
    if b"200" not in status:
        raise TunnelRefused(up_head + b"\r\n\r\n" + up_rest)
    return up_rest


class _RelayHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        srv: _RelayServer = self.server  # type: ignore[assignment]
        try:
            _tune_socket(self.request)
            # Короткий первый recv: TCP-проверка моста сразу закрывает сокет.
            self.request.settimeout(8)
            first = self.request.recv(65536)
            if not first:
                return
            if first.startswith(b"CONNECT"):
                self._connect(first, srv)
            else:
                self._forward(first, srv)
        except OSError:
            pass

    def _resolve_upstream(self, srv: "_RelayServer") -> tuple[str, int, bytes] | None:
        try:
            return srv.upstream_store.get()
        except RuntimeError:
            try:
                self.request.sendall(b"HTTP/1.1 503 Upstream Not Set\r\n\r\n")
            except OSError:
                pass
            return None

    def _connect(self, data: bytes, srv: "_RelayServer") -> None:
        resolved = self._resolve_upstream(srv)
        if resolved is None:
            return
        head, rest = _read_headers(self.request, data)
        target = _connect_target(head)
        srv.note_connect_host(target)
        t_host, t_port = _split_host_port(target, 443)
        if not t_host:
            self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        try:
            # CONNECT без раннего TLS: ClientHello только после 200 от upstream.
            upstream, up_rest = srv.upstream_store.open_tunnel(t_host, t_port, timeout=20)
        except TunnelRefused as exc:
            srv.note_connect(False)
            self.request.sendall(exc.response)
            return
        except OSError:
            srv.note_connect(False)
            try:
                self.request.sendall(b"HTTP/1.1 502 Upstream Unreachable\r\n\r\n")
            except OSError:
                pass
            return
        try:
            srv.note_connect(True)
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if up_rest:
                self.request.sendall(up_rest)
            if rest:
                srv.note_hello_size(len(rest))
                _sendall_mtu(upstream, rest, 1200)
            _tunnel(self.request, upstream, srv)
        finally:
            upstream.close()

    def _forward(self, data: bytes, srv: "_RelayServer") -> None:
        resolved = self._resolve_upstream(srv)
        if resolved is None:
            return
        _up_host, _up_port, auth_line = resolved
        head, rest = _read_headers(self.request, data)
        srv.note_connect_host("HTTP")
        if chain_socks() is not None:
            # Через цепочку upstream — SOCKS5, а не HTTP-прокси: сами идём на origin.
            self._forward_origin(head, rest, srv)
            return
        try:
            upstream = srv.upstream_store.open_plain(timeout=20)
        except OSError:
            srv.note_connect(False)
            try:
                self.request.sendall(b"HTTP/1.1 502 Upstream Unreachable\r\n\r\n")
            except OSError:
                pass
            return
        try:
            _tune_socket(upstream)
            upstream.settimeout(45)
            srv.note_connect(True)
            upstream.sendall(_inject_auth(head, auth_line) + b"\r\n\r\n" + rest)
            _tunnel(self.request, upstream, srv)
        finally:
            upstream.close()

    def _forward_origin(self, head: bytes, rest: bytes, srv: "_RelayServer") -> None:
        """Обычный http:// запрос: absolute-URI → origin-form, туннель до host:port."""
        lines = head.split(b"\r\n")
        parts = lines[0].split()
        if len(parts) < 3 or not parts[1].lower().startswith(b"http://"):
            self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        url = parts[1].decode("latin1")
        parsed = urlparse(url)
        t_host = parsed.hostname or ""
        try:
            t_port = parsed.port or 80
        except ValueError:
            t_port = 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        new_lines = [b" ".join([parts[0], path.encode("latin1"), parts[2]])]
        for line in lines[1:]:
            low = line.lower()
            if low.startswith(b"proxy-authorization:") or low.startswith(b"proxy-connection:"):
                continue
            new_lines.append(line)
        try:
            upstream, up_rest = srv.upstream_store.open_tunnel(t_host, t_port, timeout=20)
        except OSError:
            srv.note_connect(False)
            try:
                self.request.sendall(b"HTTP/1.1 502 Upstream Unreachable\r\n\r\n")
            except OSError:
                pass
            return
        try:
            upstream.settimeout(45)
            srv.note_connect(True)
            upstream.sendall(b"\r\n".join(new_lines) + b"\r\n\r\n" + rest)
            if up_rest:
                self.request.sendall(up_rest)
            _tunnel(self.request, upstream, srv)
        finally:
            upstream.close()


class _RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 512

    def __init__(
        self,
        local_port: int,
        upstream_store: UpstreamStore,
        bind_host: str = "127.0.0.1",
    ) -> None:
        self.upstream_store = upstream_store
        self._stats_lock = threading.Lock()
        self.connect_ok = 0
        self.connect_fail = 0
        self.last_hosts: list[str] = []
        self.hello_sizes: list[int] = []
        self.server_hello_sizes: list[int] = []
        super().__init__((bind_host, local_port), _RelayHandler)

    def note_connect(self, ok: bool) -> None:
        with self._stats_lock:
            if ok:
                self.connect_ok += 1
            else:
                self.connect_fail += 1

    def note_connect_host(self, host: str) -> None:
        name = (host or "?").strip() or "?"
        with self._stats_lock:
            self.last_hosts.append(name)
            if len(self.last_hosts) > 40:
                self.last_hosts = self.last_hosts[-40:]

    def note_hello_size(self, size: int) -> None:
        with self._stats_lock:
            self.hello_sizes.append(int(size))
            if len(self.hello_sizes) > 20:
                self.hello_sizes = self.hello_sizes[-20:]

    def note_server_hello_size(self, size: int) -> None:
        with self._stats_lock:
            self.server_hello_sizes.append(int(size))
            if len(self.server_hello_sizes) > 20:
                self.server_hello_sizes = self.server_hello_sizes[-20:]


@dataclass
class ProxyRelay:
    local_port: int
    _server: _RelayServer
    _thread: threading.Thread

    @property
    def playwright_proxy(self) -> dict[str, str]:
        return {"server": f"http://127.0.0.1:{self.local_port}"}

    @property
    def proxy_server_arg(self) -> str:
        return f"http://127.0.0.1:{self.local_port}"

    @property
    def connect_ok(self) -> int:
        return int(self._server.connect_ok)

    @property
    def connect_fail(self) -> int:
        return int(self._server.connect_fail)

    def recent_hosts(self) -> list[str]:
        with self._server._stats_lock:
            return list(self._server.last_hosts)

    def hello_sizes(self) -> list[int]:
        with self._server._stats_lock:
            return list(self._server.hello_sizes)

    def server_hello_sizes(self) -> list[int]:
        with self._server._stats_lock:
            return list(self._server.server_hello_sizes)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _serve_forever_resilient(srv: _RelayServer) -> None:
    """accept() на Windows иногда падает при полной очереди — не убивать весь мост."""
    restarts = 0
    while True:
        try:
            srv.serve_forever()
            return
        except OSError:
            restarts += 1
            if restarts > 40:
                return
            time.sleep(0.2)


def start_local_relay(
    proxy: dict[str, str],
    *,
    bind_host: str = "127.0.0.1",
    fixed_port: int = 0,
    upstream_store: UpstreamStore | None = None,
) -> ProxyRelay:
    store = upstream_store or UpstreamStore()
    store.set_from_proxy(proxy)
    srv = _RelayServer(fixed_port, store, bind_host=bind_host)
    local_port = srv.server_address[1]
    thread = threading.Thread(target=_serve_forever_resilient, args=(srv,), name="proxy-relay", daemon=True)
    thread.start()
    return ProxyRelay(local_port=local_port, _server=srv, _thread=thread)


_check_relays: dict[tuple[str, int, str, str], ProxyRelay] = {}
_check_relays_lock = threading.Lock()


def relay_proxy_for_checks(proxy: dict | None) -> dict | None:
    """Прокси для urllib-проверок.

    Если активна цепочка через локальный SOCKS5 — возвращает адрес общего локального relay
    (без логина), который идёт к upstream той же дорогой, что и Chrome. Иначе — исходный.
    """
    if not proxy or chain_socks() is None:
        return proxy
    server = str(proxy.get("server", "")).strip()
    if not server:
        return proxy
    if "://" not in server:
        server = f"http://{server}"
    parsed = urlparse(server)
    host = parsed.hostname or ""
    try:
        port = parsed.port or 80
    except ValueError:
        return proxy
    if host in ("127.0.0.1", "localhost", "::1"):
        return proxy
    key = (host, int(port), str(proxy.get("username", "")), str(proxy.get("password", "")))
    with _check_relays_lock:
        relay = _check_relays.get(key)
        if relay is None:
            try:
                relay = start_local_relay(
                    {"server": f"http://{host}:{port}", "username": key[2], "password": key[3]}
                )
            except OSError:
                return proxy
            _check_relays[key] = relay
    return relay.playwright_proxy


def start_dynamic_relay(
    *,
    bind_host: str = "0.0.0.0",
    fixed_port: int = 8765,
) -> tuple[ProxyRelay, UpstreamStore]:
    store = UpstreamStore()
    srv = _RelayServer(fixed_port, store, bind_host=bind_host)
    local_port = srv.server_address[1]
    thread = threading.Thread(
        target=_serve_forever_resilient, args=(srv,), name="proxy-relay", daemon=True
    )
    thread.start()
    return ProxyRelay(local_port=local_port, _server=srv, _thread=thread), store
