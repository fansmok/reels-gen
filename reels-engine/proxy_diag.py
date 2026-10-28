"""Низкоуровневая диагностика HTTP-прокси Cliproxy (stdlib, без urllib-магии).

urllib показывает только следствие: BadStatusLine, SSL: UNEXPECTED_EOF, URLError.
Здесь смотрим, что реально происходит на TCP: дошли ли до сервера, принял ли он логин
(CONNECT → 200 / 407), и что было после. Типичная поломка на стороне Cliproxy:

    HTTP/1.1 200 Connection established\\r\\n\\r\\n \\x01\\x01  <закрыто через ~0.2 с>

`\\x01\\x01` — ответ SOCKS5-подавторизации «версия 1, статус 1 = отказ», который
фронт-сервер Cliproxy получает от своего выходного узла и пробрасывает клиенту.
То есть логин наш верный, порт «Online», но exit-IP не принимает сессию — прокси
мёртв у провайдера, менять способ подключения бессмысленно, нужен другой IP.
"""

from __future__ import annotations

import base64
import socket
import time
from urllib.parse import unquote, urlparse

CODE_OK = 'ok'
CODE_AUTH = 'auth'                 # 407 — порт освобождён / логин не подходит
CODE_EXIT_REFUSED = 'exit_refused'  # 200, затем сервер сам закрыл туннель
CODE_TCP_FAIL = 'tcp_fail'          # до сервера Cliproxy не достучались
CODE_TIMEOUT = 'timeout'            # сервер молчит
CODE_BAD_REPLY = 'bad_reply'        # не HTTP-прокси / мусор
CODE_UNKNOWN = 'unknown'

EXIT_REFUSED_MARK = 'выходной узел Cliproxy отказал'

_HUMAN = {
    CODE_OK: 'туннель работает',
    CODE_AUTH: 'Cliproxy отвечает 407 — порт освобождён или логин/пароль не подходят, нужен новый прокси',
    CODE_EXIT_REFUSED: (
        f'{EXIT_REFUSED_MARK}: сервер принял логин (CONNECT 200), но сам закрыл туннель. '
        'Это поломка на стороне Cliproxy (IP «Online», но не пропускает трафик) — '
        'проверьте баланс/срок IP в кабинете и возьмите другой IP'
    ),
    CODE_TCP_FAIL: 'до сервера Cliproxy нет TCP-соединения — сеть/провайдер/фаервол',
    CODE_TIMEOUT: 'сервер Cliproxy не отвечает на CONNECT — перегружен или путь режется',
    CODE_BAD_REPLY: 'сервер ответил не как HTTP-прокси — проверьте host:port',
    CODE_UNKNOWN: 'причина не определена',
}


_SHORT = {
    CODE_OK: 'ок',
    CODE_AUTH: 'Cliproxy 407 — порт освобождён',
    CODE_EXIT_REFUSED: f'{EXIT_REFUSED_MARK} (проблема у провайдера)',
    CODE_TCP_FAIL: 'нет TCP до Cliproxy',
    CODE_TIMEOUT: 'Cliproxy не отвечает',
    CODE_BAD_REPLY: 'ответ не от HTTP-прокси',
    CODE_UNKNOWN: '',
}


def human(code: str) -> str:
    return _HUMAN.get(code, _HUMAN[CODE_UNKNOWN])


def short(code: str) -> str:
    """Короткая причина для колонки/статуса."""
    return _SHORT.get(code, '')


def _split_proxy(proxy) -> tuple[str, int, str, str]:
    """dict (.yt_proxy.json / server+username+password) или строка host:port[:user:pass] / URL."""
    if isinstance(proxy, dict):
        raw = str(proxy.get('raw') or '').strip()
        if raw.count(':') >= 3:
            return _split_proxy(raw)
        server = str(proxy.get('server') or '').strip()
        if server and '://' not in server:
            server = f'http://{server}'
        parsed = urlparse(server) if server else None
        host = (parsed.hostname if parsed else '') or ''
        try:
            port = int((parsed.port if parsed else 0) or 0)
        except ValueError:
            port = 0
        return host, port, str(proxy.get('username') or ''), str(proxy.get('password') or '')
    text = str(proxy or '').strip()
    if '://' in text:
        parsed = urlparse(text)
        try:
            port = int(parsed.port or 0)
        except ValueError:
            port = 0
        return parsed.hostname or '', port, unquote(parsed.username or ''), unquote(parsed.password or '')
    parts = text.split(':')
    if len(parts) < 2 or not parts[1].isdigit():
        return '', 0, '', ''
    user = parts[2] if len(parts) >= 3 else ''
    password = ':'.join(parts[3:]) if len(parts) >= 4 else ''
    return parts[0], int(parts[1]), user, password


def _recv_some(sock: socket.socket, limit: int = 2048, budget: float = 1.5) -> tuple[bytes, bool]:
    """Читает до тишины/закрытия. Возвращает (данные, сервер_закрыл)."""
    data = b''
    deadline = time.monotonic() + budget
    closed = False
    while time.monotonic() < deadline and len(data) < limit:
        remaining = max(0.05, deadline - time.monotonic())
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        except OSError:
            closed = True
            break
        if not chunk:
            closed = True
            break
        data += chunk
        if b'\r\n\r\n' in data and not data.endswith(b'\r\n\r\n'):
            # заголовки уже есть, немного подождём хвост (\x01\x01 приходит сразу)
            deadline = min(deadline, time.monotonic() + 0.4)
    return data, closed


def diagnose_proxy_tunnel(
    proxy,
    *,
    target: str = 'api.ipify.org',
    target_port: int = 80,
    timeout: float = 8.0,
) -> tuple[str, str]:
    """Прямое TCP → CONNECT с логином. Возвращает (код, подробность для лога)."""
    host, port, user, password = _split_proxy(proxy)
    if not host or not port:
        return CODE_UNKNOWN, 'нет host:port'
    if host in ('127.0.0.1', 'localhost', '::1'):
        # локальный relay/CliProxy.exe — смотреть надо на upstream, а не на него
        return CODE_UNKNOWN, 'локальный порт — диагностика upstream не применима'
    started = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except socket.timeout:
        return CODE_TCP_FAIL, f'TCP {host}:{port} timeout {timeout:.0f}s'
    except OSError as exc:
        return CODE_TCP_FAIL, f'TCP {host}:{port}: {exc.__class__.__name__}: {str(exc)[:60]}'
    try:
        sock.settimeout(timeout)
        head = f'CONNECT {target}:{target_port} HTTP/1.1\r\nHost: {target}:{target_port}\r\n'
        if user:
            token = base64.b64encode(f'{user}:{password}'.encode('utf-8')).decode('ascii')
            head += f'Proxy-Authorization: Basic {token}\r\n'
        head += 'Proxy-Connection: Keep-Alive\r\n\r\n'
        sock.sendall(head.encode('utf-8'))
        data, closed = _recv_some(sock, budget=min(timeout, 6.0))
        if not data:
            if closed:
                return CODE_BAD_REPLY, 'сервер закрыл соединение без ответа на CONNECT'
            return CODE_TIMEOUT, f'нет ответа на CONNECT за {time.monotonic() - started:.1f}s'
        status_line = data.split(b'\r\n', 1)[0]
        if not status_line.startswith(b'HTTP/'):
            return CODE_BAD_REPLY, f'ответ не HTTP: {status_line[:40]!r}'
        try:
            status = int(status_line.split()[1])
        except (IndexError, ValueError):
            return CODE_BAD_REPLY, f'странная строка статуса: {status_line[:60]!r}'
        if status == 407:
            msg = ''
            if b'\n\n' in data or b'\r\n\r\n' in data:
                tail = data.replace(b'\r\n', b'\n').split(b'\n\n', 1)[-1]
                msg = tail.decode('utf-8', 'replace').strip()[:60]
            return CODE_AUTH, f'407 {msg}'.strip()
        if status != 200:
            return CODE_BAD_REPLY, f'CONNECT → HTTP {status}'
        tail = data.replace(b'\r\n', b'\n').split(b'\n\n', 1)[-1] if b'\n\n' in data.replace(b'\r\n', b'\n') else b''
        if closed or tail:
            elapsed = time.monotonic() - started
            what = f'после 200 пришло {tail[:8]!r} и ' if tail else 'после 200 '
            return CODE_EXIT_REFUSED, f'{what}сервер закрыл туннель через {elapsed:.1f}s'
        # Туннель открыт и молчит — отправим минимальный запрос и посмотрим, ответит ли цель.
        sock.sendall(
            f'GET / HTTP/1.1\r\nHost: {target}\r\nConnection: close\r\nUser-Agent: Mozilla/5.0\r\n\r\n'.encode()
        )
        body, closed2 = _recv_some(sock, budget=min(timeout, 6.0))
        if body.startswith(b'HTTP/'):
            return CODE_OK, f'цель ответила через туннель за {time.monotonic() - started:.1f}s'
        if closed2 and not body:
            return CODE_EXIT_REFUSED, (
                f'туннель открыт, но на первый же запрос сервер закрыл соединение '
                f'({time.monotonic() - started:.1f}s)'
            )
        if not body:
            return CODE_TIMEOUT, 'туннель открыт, цель молчит (exit-узел не отвечает)'
        return CODE_BAD_REPLY, f'через туннель пришёл мусор: {body[:16]!r}'
    except socket.timeout:
        return CODE_TIMEOUT, f'timeout {timeout:.0f}s внутри CONNECT'
    except OSError as exc:
        return CODE_UNKNOWN, f'{exc.__class__.__name__}: {str(exc)[:60]}'
    finally:
        try:
            sock.close()
        except OSError:
            pass


def explain_dead_proxy(proxy, *, timeout: float = 6.0) -> str:
    """Короткая человекочитаемая причина для логов GUI (пустая строка, если всё ок)."""
    code, detail = diagnose_proxy_tunnel(proxy, timeout=timeout)
    if code == CODE_OK:
        return ''
    text = human(code)
    if detail and code not in (CODE_EXIT_REFUSED,):
        text = f'{text} ({detail})'
    return text


def is_exit_refused_detail(detail) -> bool:
    return EXIT_REFUSED_MARK in str(detail or '')


if __name__ == '__main__':  # pragma: no cover
    import sys

    for arg in sys.argv[1:]:
        code, det = diagnose_proxy_tunnel(arg)
        print(f'{arg.split(":")[0]}:{arg.split(":")[1]} → {code}: {det}')
        print(f'   {human(code)}')
