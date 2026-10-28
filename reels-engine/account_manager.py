"""Менеджер аккаунтов YT-COOKIES: сканирование, открытие, смена прокси."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import buyer_core
import cliproxy_app
import plain_profiles
import proxy_diag

YT_COOKIES_DIR = Path(__file__).resolve().parent / 'YT-COOKIES'
ZIP_CACHE_DIR = YT_COOKIES_DIR / '_zip_cache'


def _normalize_dir(path: str | Path | None) -> Path:
    if path is None:
        return YT_COOKIES_DIR
    return Path(path)


_INFO_FILE_NAMES = (
    'information.txt',
    'UserInfo.txt',
    'userinfo.txt',
    'UserInformation.txt',
    'userinformation.txt',
    'info.txt',
    'system.txt',
    'system_info.txt',
    'System Information.txt',
    'system information.txt',
    'pc_info.txt',
    'pc_info.json',
)


def _find_info_file(account_dir: Path) -> Path | None:
    for name in _INFO_FILE_NAMES:
        path = account_dir / name
        if path.is_file():
            return path
    skip = {'browser_profile', 'Cookies', 'Passwords', 'GoogleAccounts', '__MACOSX', '_zip_cache'}
    try:
        children = list(account_dir.iterdir())
    except OSError:
        return None
    for sub in children:
        if not sub.is_dir() or sub.name in skip or sub.name.startswith('.'):
            continue
        for name in _INFO_FILE_NAMES:
            path = sub / name
            if path.is_file():
                return path
    return None


def _read_information_txt(path: Path) -> dict[str, str]:
    """information.txt / system_info.txt / UserInformation.txt: «- IP: …», GEO, пустой GPU на след. строке."""
    info: dict[str, str] = {}
    pending_key = ''
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith('- ') or line.startswith('* '):
                line = line[2:].strip()
            elif line.startswith('-') and len(line) > 1 and not line[1].isspace() and ':' not in line[:24]:
                # «-AMD Radeon …» после пустого GPU:
                line = line[1:].strip()
            if not line:
                pending_key = ''
                continue
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                if not key:
                    continue
                info[key] = val
                pending_key = key if not val else ''
                continue
            if pending_key and not info.get(pending_key):
                info[pending_key] = line
                pending_key = ''
    except Exception:
        pass
    if not info.get('Username') and info.get('UserName'):
        info['Username'] = info['UserName']
    # Country / GEO (UserInformation.txt пишет страну как GEO: RU)
    if not info.get('Country'):
        info['Country'] = (
            info.get('Country Name')
            or info.get('Country Code')
            or info.get('GEO')
            or info.get('Geo')
            or info.get('geo')
            or ''
        )
    if not info.get('Display') and info.get('Resolution'):
        info['Display'] = info['Resolution']
    if not info.get('Display') and info.get('Display Resolution'):
        info['Display'] = info['Display Resolution']
    return info


def _read_pc_info_json(path: Path) -> dict:
    """pc_info.json или pc_info.txt: JSON-объект, перед ним может быть текстовая шапка."""
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
        start = text.find('{')
        if start < 0:
            return {}
        data, _end = json.JSONDecoder().raw_decode(text[start:])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def same_account_ip(left: str, right: str) -> bool:
    """Один IP с учётом CIDR, IPv4-mapped и разного написания IPv6."""
    a, _va = normalize_account_ip(left)
    b, _vb = normalize_account_ip(right)
    if a and b:
        return a == b
    return str(left or '').strip() == str(right or '').strip()


def normalize_account_ip(raw: str) -> tuple[str, int | None]:
    """IP без CIDR. Возвращает (адрес, 4|6) или ('', None)."""
    text = str(raw or '').strip()
    if not text:
        return '', None
    text = text.split()[0]
    try:
        iface = ipaddress.ip_interface(text)
    except ValueError:
        return '', None
    addr = iface.ip
    mapped = getattr(addr, 'ipv4_mapped', None)
    if mapped is not None:
        return str(mapped), 4
    return str(addr), int(addr.version)


def _get_isp(ip: str) -> str:
    lookup, _ver = normalize_account_ip(ip)
    ip = lookup or str(ip or '').strip()
    if not ip:
        return ''
    try:
        url = f'http://ip-api.com/json/{quote(ip, safe=":")}?fields=isp'
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='replace'))
            return data.get('isp', '')
    except Exception:
        return ''


def _count_value(raw: object) -> int:
    digits = re.sub(r'[^\d]', '', str(raw or ''))
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def parse_youtube_channels(text: str) -> list[dict]:
    """Все каналы из YoutubeInfo.txt: ссылка, подписчики, просмотры, регистрация."""
    channels: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        link = str(current.get('channel') or '').strip()
        if link:
            channels.append(current)
        current = None

    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith('Ссылка:'):
            flush()
            current = {
                'channel': line.split(':', 1)[1].strip(),
                'email': '',
                'subscribers': '',
                'views': '',
                'registration': '',
            }
            continue
        if current is None:
            continue
        if line.startswith('Почта:'):
            current['email'] = line.split(':', 1)[1].strip()
        elif line.startswith('Число подписчиков:'):
            current['subscribers'] = line.split(':', 1)[1].strip()
        elif line.startswith('Число просмотров:'):
            current['views'] = line.split(':', 1)[1].strip()
        elif line.startswith('Регистрация:'):
            current['registration'] = line.split(':', 1)[1].strip()
    flush()
    return channels


def _pick_primary_channel(channels: list[dict]) -> dict:
    if not channels:
        return {}
    return max(
        channels,
        key=lambda item: (_count_value(item.get('subscribers')), _count_value(item.get('views'))),
    )


def _system_info_summary(data: dict[str, str]) -> str:
    """Короткая строка из System Information / information.txt."""
    parts = []
    os_name = data.get('OS') or data.get('Windows') or data.get('Operating System') or ''
    if os_name:
        parts.append(f'OS {os_name}' if not str(os_name).lower().startswith('windows') else str(os_name))
    cpu = data.get('CPU') or data.get('Processor') or ''
    if cpu:
        parts.append(str(cpu))
    gpu = data.get('GPU') or data.get('Video Card') or data.get('VideoCard') or ''
    if gpu:
        parts.append(str(gpu))
    ram = data.get('RAM') or data.get('Memory') or ''
    if ram:
        parts.append(f'RAM {ram}' if 'ram' not in str(ram).lower() else str(ram))
    display = data.get('Display') or data.get('Screen Resolution') or ''
    if display:
        parts.append(str(display))
    computer = data.get('Computer Name') or data.get('PC Name') or data.get('Computer') or ''
    user = data.get('Username') or data.get('User Name') or data.get('User') or ''
    if computer or user:
        who = ' / '.join(x for x in (computer, user) if x)
        parts.append(who)
    return ' · '.join(parts)


def format_channels_text(channels: list[dict] | None) -> str:
    """Текст для панели деталей: все каналы лога."""
    rows = []
    for item in channels or []:
        link = str(item.get('channel') or '').strip()
        if not link:
            continue
        bits = [link]
        subs = str(item.get('subscribers') or '').strip()
        views = str(item.get('views') or '').strip()
        reg = str(item.get('registration') or '').strip()
        if subs:
            bits.append(f'{subs} подп.')
        if views:
            bits.append(f'{views} просм.')
        if reg:
            bits.append(f'рег. {reg}')
        rows.append(' · '.join(bits))
    return '\n'.join(rows)


def read_account_info(account_dir: str | Path, fetch_isp: bool = True) -> dict:
    """Собирает информацию об аккаунте из YoutubeInfo.txt, information.txt и pc_info.json."""
    account_dir = Path(account_dir)
    info = {
        'name': account_dir.name,
        'path': str(account_dir),
        'email': '',
        'channel': '',
        'channels': [],
        'subscribers': '',
        'views': '',
        'registration': '',
        'system_info': '',
        'ip': '',
        'country': '',
        'city': '',
        'isp': '',
        'date_added': '',
        'date_added_ts': 0.0,
        'last_opened': '',
    }

    try:
        ctime = account_dir.stat().st_ctime
        info['date_added_ts'] = ctime
        info['date_added'] = datetime.fromtimestamp(ctime).strftime('%d.%m.%Y %H:%M')
    except Exception:
        pass

    yt_info_path = account_dir / 'YoutubeInfo.txt'
    if yt_info_path.is_file():
        try:
            text = yt_info_path.read_text(encoding='utf-8', errors='replace')
            channels = parse_youtube_channels(text)
            info['channels'] = channels
            primary = _pick_primary_channel(channels)
            if primary:
                info['channel'] = primary.get('channel') or ''
                info['subscribers'] = primary.get('subscribers') or ''
                info['views'] = primary.get('views') or ''
                info['registration'] = primary.get('registration') or ''
                if primary.get('email'):
                    info['email'] = primary['email']
            if not info['email']:
                for line in text.splitlines():
                    if 'Почта:' in line:
                        info['email'] = line.split(':', 1)[1].strip()
                        break
        except Exception:
            pass

    info_file = _find_info_file(account_dir)
    if info_file:
        if info_file.suffix.lower() == '.json' or info_file.name.lower() == 'pc_info.txt':
            data = _read_pc_info_json(info_file)
            info['ip'] = data.get('Ip', '') or data.get('IP', '') or data.get('ip', '')
            info['country'] = data.get('Country', '') or data.get('country', '')
            info['city'] = data.get('City', '') or data.get('city', '')
            flat = {str(k): str(v) for k, v in data.items() if v is not None}
            info['system_info'] = _system_info_summary(flat)
        else:
            data = _read_information_txt(info_file)
            raw_ip = data.get('IP') or data.get('IP Address') or data.get('External IP') or ''
            info['country'] = (
                data.get('Country')
                or data.get('Country Code')
                or data.get('Country Name')
                or data.get('GEO')
                or data.get('Geo')
                or data.get('geo')
                or ''
            )
            cc = re.search(r'\(([A-Za-z]{2})\)\s*$', raw_ip)
            if cc and not info['country']:
                info['country'] = cc.group(1).upper()
            info['ip'] = raw_ip
            info['city'] = data.get('City') or data.get('Location') or ''
            if not info['city'] and data.get('Region'):
                info['city'] = data.get('Region') or ''
            info['system_info'] = _system_info_summary(data)

    norm_ip, _ver = normalize_account_ip(info['ip'])
    if norm_ip:
        info['ip'] = norm_ip

    if info['ip'] and fetch_isp:
        info['isp'] = _get_isp(info['ip'])

    info['default_name'] = info.get('name') or ''
    apply_table_overrides(info)
    return info


def read_account_proxy(account_dir: str | Path) -> dict | None:
    """Читает сохранённый прокси из .yt_proxy.json."""
    path = Path(account_dir) / '.yt_proxy.json'
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get('raw') or '').strip()
    if raw.count(':') >= 3:
        try:
            parse_proxy_string_to_dict(raw)
        except Exception:
            return None
    return data


def _telegram_proxy_raw() -> str:
    path = Path(__file__).resolve().parent / 'buyer_settings.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return ''
    return str(data.get('proxy_string') or '').strip()


def is_cliproxy_proxy(proxy: dict | None) -> bool:
    """True только для прокси Cliproxy. Telegram и ручные строки не подходят."""
    if not isinstance(proxy, dict):
        return False
    raw = (proxy.get('raw') or proxy_dict_to_string(proxy) or '').strip()
    if not raw or raw.count(':') < 3:
        return False
    tg = _telegram_proxy_raw()
    if tg and raw == tg:
        return False
    source = str(proxy.get('source') or '').strip().lower()
    if source and source != 'cliproxy':
        return False
    return True


def has_account_proxy(proxy: dict | None) -> bool:
    """Есть сохранённый YouTube-прокси: Cliproxy или вручную, не строка Telegram."""
    if not isinstance(proxy, dict):
        return False
    raw = (proxy.get('raw') or proxy_dict_to_string(proxy) or '').strip()
    if not raw or raw.count(':') < 3:
        return False
    tg = _telegram_proxy_raw()
    if tg and raw == tg:
        return False
    return True


LABEL_FILE = '.yt_label.json'
AUTONOMOUS_FILE = '.yt_autonomous.json'
TABLE_FILE = '.yt_table.json'
TABLE_OVERRIDE_KEYS = (
    'name',
    'email',
    'ip',
    'country',
    'registration',
    'date_added',
    'proxy_status',
)


def _atomic_write_text(path: Path, text: str) -> None:
    """Записать runtime JSON без промежуточного битого файла."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.tmp-{os.getpid()}-{threading.get_ident()}')
    try:
        with tmp.open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def default_account_name(acc: dict | None = None, account_dir: str | Path | None = None) -> str:
    """Имя по папке / номеру профиля, без пользовательского переименования."""
    path = ''
    number = None
    if acc:
        path = str(acc.get('path') or '')
        number = acc.get('number')
        stored = str(acc.get('default_name') or '').strip()
        if stored:
            return stored
    if account_dir and not path:
        path = str(account_dir)
    folder = Path(path) if path else None
    if number is None and folder is not None:
        number = plain_profiles.profile_number_from_name(folder.name)
    if number:
        return f'YouTube #{int(number)}'
    if folder is not None and folder.name:
        return folder.name
    return ''


def read_table_overrides(account_dir: str | Path) -> dict:
    """Читает ручные правки таблицы из .yt_table.json."""
    path = Path(account_dir) / TABLE_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in TABLE_OVERRIDE_KEYS:
        if key not in data:
            continue
        text = str(data.get(key) or '').strip()
        if key == 'name' and not text:
            continue
        out[key] = text
    return out


def save_table_overrides(account_dir: str | Path, updates: dict | None) -> bool:
    """Пишет ручные правки таблицы. Пустое значение снимает переопределение."""
    path = Path(account_dir) / TABLE_FILE
    data = read_table_overrides(account_dir)
    for key, value in (updates or {}).items():
        if key not in TABLE_OVERRIDE_KEYS:
            continue
        text = '' if value is None else str(value).strip()
        if key == 'name':
            if text:
                data[key] = text
            else:
                data.pop(key, None)
        else:
            data[key] = text
    try:
        if data:
            _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        elif path.is_file():
            path.unlink()
        return True
    except Exception:
        return False


def apply_table_overrides(acc: dict) -> dict:
    """Накладывает сохранённые правки на словарь аккаунта."""
    if not acc:
        return acc
    if not str(acc.get('default_name') or '').strip():
        acc['default_name'] = str(acc.get('name') or '') or default_account_name(acc)
    data = read_table_overrides(acc.get('path') or '')
    if not data:
        return acc
    for key, value in data.items():
        acc[key] = value
    return acc


def read_account_label(account_dir: str | Path) -> str:
    """Читает сохранённую метку аккаунта из .yt_label.json."""
    path = Path(account_dir) / LABEL_FILE
    if not path.is_file():
        return ''
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
        return normalize_account_label((data.get('label') or '').strip())
    except Exception:
        return ''


def save_account_label(account_dir: str | Path, label: str) -> bool:
    """Сохраняет метку аккаунта в .yt_label.json."""
    path = Path(account_dir) / LABEL_FILE
    try:
        if label and label.strip():
            _atomic_write_text(
                path, json.dumps({'label': label.strip()}, indent=2, ensure_ascii=False) + '\n',
            )
        elif path.is_file():
            path.unlink()
        return True
    except Exception:
        return False


def is_top_label(label) -> bool:
    return normalize_account_label(label) == LABEL_TOP


def default_autonomous(label='') -> bool:
    """По умолчанию все логи в автономном проходе, кроме ТОП."""
    return not is_top_label(label)


def read_autonomous(account_dir: str | Path, label=None) -> bool:
    """Галочка «Автономно». ТОП всегда вне очереди. Нет файла — включено."""
    if label is None:
        label = read_account_label(account_dir)
    if is_top_label(label):
        return False
    path = Path(account_dir) / AUTONOMOUS_FILE
    if not path.is_file():
        return True
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return True
    if isinstance(data, dict) and 'enabled' in data:
        return bool(data.get('enabled'))
    return True


def save_autonomous(account_dir: str | Path, enabled: bool) -> bool:
    path = Path(account_dir) / AUTONOMOUS_FILE
    try:
        _atomic_write_text(
            path, json.dumps({'enabled': bool(enabled)}, indent=2, ensure_ascii=False) + '\n',
        )
        return True
    except Exception:
        return False


STREAM_KEY_FILE = '.yt_stream_key.json'
ACTIVITY_FILE = '.yt_activity.json'
IDLE_CLOSE_SEC = 600
_last_stream_key = ''
_last_stream_keys: list[str] = []
PUSH_LINE_RE = re.compile(
    r'push\s+rtmp://a\.rtmp\.youtube\.com/live2/([a-z0-9-]+);?',
    re.I,
)


def read_last_stream_key(account_dir: str | Path = '') -> str:
    if account_dir:
        path = Path(account_dir) / STREAM_KEY_FILE
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
                return (data.get('key') or '').strip()
            except Exception:
                pass
    return _last_stream_key


def read_last_stream_keys() -> list[str]:
    return list(_last_stream_keys)


def format_rtmp_push(key: str) -> str:
    return f'push rtmp://a.rtmp.youtube.com/live2/{str(key or "").strip()};'


def save_last_stream_key(account_dir: str | Path, key: str) -> None:
    global _last_stream_key, _last_stream_keys
    key = (key or '').strip()
    _last_stream_key = key
    if key and key not in _last_stream_keys:
        _last_stream_keys.append(key)
    if not key:
        return
    path = Path(account_dir) / STREAM_KEY_FILE
    try:
        path.write_text(json.dumps({'key': key}, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass

_current_proc = None
_current_account_dir = None
_last_chrome_started = False
_last_youtube_open = False
_last_proxy_dead = False
_last_proxy_mid = False
DEAD_PROXY_REPLACEMENTS = 2
# Обрыв уже идущей автоматизации: один другой прокси, потом следующий аккаунт.
MID_PROXY_REPLACEMENTS = 1
_stop_requested = False
_stop_kill_gen = 0
_work_gen = 0
_open_lock = threading.Lock()
_child_pids: set[int] = set()
_pids_lock = threading.Lock()
_idle_lock = threading.Lock()
_idle_sessions: dict[str, dict] = {}


def register_child_pid(pid) -> None:
    if not pid:
        return
    with _pids_lock:
        _child_pids.add(int(pid))


def unregister_child_pid(pid) -> None:
    if not pid:
        return
    with _pids_lock:
        _child_pids.discard(int(pid))


def _idle_key(account_dir) -> str:
    try:
        return str(Path(account_dir).resolve())
    except Exception:
        return str(account_dir or '')


def _remember_idle_browser(account_dir, proc, attach_event) -> None:
    with _idle_lock:
        _idle_sessions[_idle_key(account_dir)] = {
            'proc': proc,
            'attach_event': attach_event,
            'started': time.time(),
        }


def _forget_idle_browser(account_dir, proc=None) -> None:
    key = _idle_key(account_dir)
    with _idle_lock:
        sess = _idle_sessions.get(key)
        if not sess:
            return
        if proc is not None and sess.get('proc') is not proc:
            return
        _idle_sessions.pop(key, None)


def _pid_is_running(pid: int) -> bool:
    """True, если процесс жив. os.kill(pid, 0) на Windows даёт WinError 87 / SystemError."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            ERROR_ACCESS_DENIED = 5
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid & 0xFFFFFFFF,
            )
            if not handle:
                return int(kernel32.GetLastError() or 0) == ERROR_ACCESS_DENIED
            try:
                code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return int(code.value) == STILL_ACTIVE
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return False


def _account_chrome_dir(account_dir) -> Path:
    account_dir = Path(account_dir)
    if plain_profiles.is_plain_profile(account_dir):
        return account_dir
    return account_dir / 'browser_profile'


def _chrome_profile_in_use(profile_dir) -> bool:
    profile_dir = Path(profile_dir)
    if not profile_dir.is_dir():
        return False
    try:
        yt_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
        yt_dir_s = str(yt_dir)
        if yt_dir_s not in sys.path:
            sys.path.insert(0, yt_dir_s)
        from browser_isolation import chrome_profile_in_use
        return bool(chrome_profile_in_use(profile_dir))
    except Exception:
        lock = profile_dir / 'SingletonLock'
        try:
            return lock.exists()
        except Exception:
            return False


def _parse_alive_file(text: str) -> tuple[int, int | None]:
    parts = str(text or '').strip().split()
    if not parts:
        return 0, None
    try:
        pid = int(parts[0])
    except ValueError:
        return 0, None
    pages = None
    if len(parts) >= 2:
        try:
            pages = int(parts[1])
        except ValueError:
            pages = None
    return pid, pages


def _clear_alive_file(account_dir) -> None:
    path = Path(account_dir) / BROWSER_ALIVE_FILE
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        pass


def _drop_dead_idle_browser(account_dir) -> None:
    """Python-обёртка ещё жива, окна Chrome уже нет — не считаем браузер открытым."""
    proc = None
    with _idle_lock:
        sess = _idle_sessions.pop(_idle_key(account_dir), None)
        proc = (sess or {}).get('proc')
    if proc is not None and proc.poll() is None:
        pid = getattr(proc, 'pid', None)
        if pid:
            kill_pid_tree(pid)
            unregister_child_pid(pid)
    _clear_alive_file(account_dir)


def read_idle_browser_pid(account_dir) -> int:
    path = Path(account_dir) / BROWSER_ALIVE_FILE
    if not path.is_file():
        return 0
    try:
        pid, pages = _parse_alive_file(path.read_text(encoding='utf-8'))
    except Exception:
        return 0
    if pages == 0:
        _clear_alive_file(account_dir)
        return 0
    if pid and _pid_is_running(pid):
        return pid
    try:
        path.unlink()
    except Exception:
        pass
    return 0


def read_idle_browser_pages(account_dir) -> int | None:
    path = Path(account_dir) / BROWSER_ALIVE_FILE
    if not path.is_file():
        return None
    try:
        _pid, pages = _parse_alive_file(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    return pages


def _clear_attach_done(account_dir) -> None:
    path = Path(account_dir) / ATTACH_DONE_FILE
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        pass


IDLE_START_GRACE_SEC = 90.0


def idle_browser_alive(account_dir) -> bool:
    """True, если «Открыть выбранный» ещё держит видимое окно Chrome этого аккаунта."""
    try:
        key = _idle_key(account_dir)
        proc = None
        started = 0.0
        with _idle_lock:
            sess = _idle_sessions.get(key)
            proc = (sess or {}).get('proc')
            started = float((sess or {}).get('started') or 0)
            if proc is not None and proc.poll() is not None:
                _idle_sessions.pop(key, None)
                proc = None
                started = 0.0
        python_alive = proc is not None and proc.poll() is None
        pages = read_idle_browser_pages(account_dir)
        if started and (time.time() - started) < IDLE_START_GRACE_SEC:
            return True
        if _chrome_profile_in_use(_account_chrome_dir(account_dir)):
            return True
        if pages == 0:
            # Статус, не убийство: GUI часто зовёт это на все аккаунты.
            # pages=0 на миг при навигации — kill_pid_tree здесь закрывал Chrome.
            _clear_alive_file(account_dir)
            return False
        if not python_alive:
            python_alive = bool(read_idle_browser_pid(account_dir))
        if not python_alive:
            return False
        if pages and pages > 0:
            return True
        return bool(python_alive)
    except Exception:
        return False


def _can_attach_idle(account_dir) -> bool:
    """К открытому окну можно дописать автоматизацию только если youtube_browser ещё жив."""
    try:
        event = _idle_attach_event(account_dir)
        if event is not None:
            with _idle_lock:
                sess = _idle_sessions.get(_idle_key(account_dir)) or {}
            proc = sess.get('proc')
            if proc is not None and proc.poll() is None:
                return True
        return bool(read_idle_browser_pid(account_dir))
    except Exception:
        return False


def _idle_attach_event(account_dir):
    with _idle_lock:
        sess = _idle_sessions.get(_idle_key(account_dir))
        return (sess or {}).get('attach_event')


def wait_idle_automation(account_dir, timeout_sec: float = 3600) -> bool:
    if not _can_attach_idle(account_dir):
        return False
    event = _idle_attach_event(account_dir)
    done_path = Path(account_dir) / ATTACH_DONE_FILE
    deadline = time.time() + max(5.0, float(timeout_sec))
    while time.time() < deadline:
        if event is not None and event.is_set():
            return True
        if done_path.is_file():
            try:
                done_path.unlink()
            except Exception:
                pass
            return True
        if not idle_browser_alive(account_dir):
            return False
        if is_stop_requested():
            return False
        if event is not None:
            event.wait(timeout=0.5)
        else:
            time.sleep(0.5)
    return False


def kill_pid_tree(pid) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        if os.name == 'nt':
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True,
                **buyer_core.hidden_subprocess_kwargs(),
            )
        else:
            os.kill(pid, 15)
        return True
    except Exception:
        return False


def _kill_chrome_for_profile(profile_dir):
    if os.name != 'nt' or not profile_dir:
        return 0
    marker = json.dumps(os.path.abspath(str(profile_dir)))
    ps = (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"$marker = {marker}\n"
        "$names = @('chrome.exe','chromium.exe','msedge.exe','chromedriver.exe')\n"
        "Get-CimInstance Win32_Process | Where-Object {\n"
        "  $names -contains $_.Name -and $_.CommandLine -and $_.CommandLine.Contains($marker)\n"
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }\n"
    )
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps],
            capture_output=True,
            text=True,
            errors='replace',
            timeout=20,
            **buyer_core.hidden_subprocess_kwargs(),
        )
        return sum(1 for line in result.stdout.splitlines() if line.strip().isdigit())
    except Exception:
        return 0


def _kill_script_browsers():
    account_dir = _current_account_dir
    if account_dir:
        _kill_chrome_for_profile(Path(account_dir) / 'browser_profile')
    try:
        import cliproxy_playwright
        cliproxy_dir = cliproxy_playwright._cliproxy_profile_dir()
    except Exception:
        cliproxy_dir = Path(__file__).parent / 'cliproxy_profile'
    _kill_chrome_for_profile(cliproxy_dir)


def read_last_opened(account_dir: str | Path) -> str:
    """Читает дату последнего запуска аккаунта."""
    path = Path(account_dir) / ACTIVITY_FILE
    if not path.is_file():
        return ''
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
        return (data.get('last_opened') or '').strip()
    except Exception:
        return ''


def save_last_opened(account_dir: str | Path, stamp: str | None = None) -> str:
    """Записывает время последнего запуска. stamp=None — сейчас, пустая строка — стереть."""
    if stamp is None:
        stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    else:
        stamp = str(stamp or '').strip()
    path = Path(account_dir) / ACTIVITY_FILE
    try:
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
            except Exception:
                data = {}
        if stamp:
            data['last_opened'] = stamp
            data['last_action'] = time.time()
        else:
            data.pop('last_opened', None)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass
    return stamp


def touch_account_activity(account_dir: str | Path, note: str = '') -> None:
    """Пишет last_action — GUI и youtube_browser видят, что аккаунт живой."""
    path = Path(account_dir) / ACTIVITY_FILE
    try:
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data['last_action'] = time.time()
        if note:
            data['last_action_note'] = str(note)[:120]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def close_hung_account(account_dir: str | Path, proc=None, status_callback=None) -> bool:
    """Глушит зависший youtube_browser и Chrome этого аккаунта."""
    if status_callback:
        status_callback('Нет действий 10 минут — закрываю аккаунт')
    killed = False
    pid = getattr(proc, 'pid', None) if proc is not None else None
    if proc is not None and proc.poll() is None and pid:
        # Мягкая остановка (снять cookies, флеш Cookies DB), иначе разлогин.
        graceful = False
        try:
            graceful = idle_browser_alive(account_dir)
        except Exception:
            graceful = False
        if graceful and _graceful_stop_and_wait(account_dir, proc):
            killed = True
        elif kill_pid_tree(pid):
            killed = True
        unregister_child_pid(pid)
    account = Path(account_dir)
    _kill_chrome_for_profile(account / 'browser_profile')
    if plain_profiles.is_plain_profile(account):
        _kill_chrome_for_profile(account)
    _clear_alive_file(account)
    return killed


def request_stop() -> bool:
    """Глушит только текущие процессы. Новые запуски после clear_stop() не блокирует."""
    global _stop_requested, _work_gen
    _stop_requested = True
    _work_gen += 1
    gen = _stop_kill_gen
    account_dir = _current_account_dir
    killed = stop_current_account_process()
    killed = _kill_idle_browsers() or killed
    with _pids_lock:
        pids = tuple(_child_pids)
    for pid in pids:
        if kill_pid_tree(pid):
            killed = True
        unregister_child_pid(pid)
    if account_dir:
        _kill_chrome_for_profile(Path(account_dir) / 'browser_profile')
        if plain_profiles.is_plain_profile(account_dir):
            _kill_chrome_for_profile(Path(account_dir))
        _clear_alive_file(account_dir)
    try:
        import cliproxy_playwright
        cliproxy_dir = cliproxy_playwright._cliproxy_profile_dir()
    except Exception:
        cliproxy_dir = Path(__file__).parent / 'cliproxy_profile'
    if gen == _stop_kill_gen:
        _kill_chrome_for_profile(cliproxy_dir)
    return killed


def _kill_idle_session(key, sess) -> bool:
    killed = False
    proc = (sess or {}).get('proc')
    pid = getattr(proc, 'pid', None) if proc is not None else None
    if pid:
        unregister_child_pid(pid)
    if proc is not None and proc.poll() is None and pid:
        # Сначала мягко (только если есть живое окно, которое услышит флаг): даём
        # снять живые cookies и штатно закрыть Chrome, иначе force-kill теряет
        # свежие Google-токены → разлогин на след. входе.
        graceful = False
        try:
            graceful = idle_browser_alive(key)
        except Exception:
            graceful = False
        if graceful and _graceful_stop_and_wait(key, proc):
            killed = True
        elif kill_pid_tree(pid):
            killed = True
    _clear_alive_file(key)
    account_dir = Path(key)
    _kill_chrome_for_profile(account_dir / 'browser_profile')
    if plain_profiles.is_plain_profile(account_dir):
        _kill_chrome_for_profile(account_dir)
    return killed


def _kill_idle_browsers() -> bool:
    killed = False
    with _idle_lock:
        items = list(_idle_sessions.items())
        _idle_sessions.clear()
    for key, sess in items:
        killed = _kill_idle_session(key, sess) or killed
    return killed


def close_idle_browser(account_dir, status_callback=None) -> bool:
    """Закрывает окно «Открыть выбранный» этого аккаунта, чтобы зайти с новым прокси."""
    account_dir = Path(account_dir)
    if not idle_browser_alive(account_dir):
        return False
    key = _idle_key(account_dir)
    with _idle_lock:
        sess = _idle_sessions.pop(key, None)
    killed = _kill_idle_session(key, sess)
    if status_callback:
        status_callback('Старое окно закрыто — дальше зайду с новым прокси')
    return killed or True


def clear_stop() -> None:
    """Снимает стоп, чтобы можно было сразу запускать новые процессы."""
    global _stop_requested, _stop_kill_gen
    _stop_requested = False
    _stop_kill_gen += 1


def current_work_gen() -> int:
    return _work_gen


def is_stop_requested(work_id=None) -> bool:
    if work_id is not None and work_id != _work_gen:
        return True
    return bool(_stop_requested)


STOP_REQUEST_FILE = '.yt_stop_request'


def _graceful_stop_and_wait(account_dir, proc, *, timeout: float = 8.0) -> bool:
    """Просит youtube_browser снять живые cookies и выйти до жёсткого kill.

    Ставит флаг-файл .yt_stop_request в папке аккаунта. Цикл keep-open в
    youtube_browser видит его, делает финальный снимок cookies (последняя
    ротация Google-токенов) и закрывает Chrome штатно — с флешем Cookies DB.
    Без этого taskkill /F теряет свежие токены и аккаунт разлогинивается.
    """
    if not account_dir:
        return False
    try:
        flag = Path(account_dir) / STOP_REQUEST_FILE
        flag.write_text(str(time.time()), encoding='utf-8')
    except Exception:
        return False
    deadline = time.time() + max(0.5, float(timeout))
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                return True
            time.sleep(0.2)
    finally:
        try:
            flag.unlink()
        except OSError:
            pass
    return proc.poll() is not None


def stop_current_account_process() -> bool:
    """Останавливает текущий процесс открытия/прогрева аккаунта."""
    global _current_proc
    proc = _current_proc
    account_dir = _current_account_dir
    _current_proc = None
    if proc is None:
        return False
    pid = getattr(proc, 'pid', None)
    already_dead = proc.poll() is not None
    if pid:
        unregister_child_pid(pid)
    if already_dead or not pid:
        return False
    # Если открыто живое окно (keep-open) — сначала мягко, чтобы сохранить сессию.
    try:
        kept_open = bool(account_dir) and idle_browser_alive(account_dir)
    except Exception:
        kept_open = False
    if kept_open and _graceful_stop_and_wait(account_dir, proc):
        return True
    return kill_pid_tree(pid)


def parse_proxy_string_to_dict(proxy_string: str) -> dict:
    """Преобразует host:port:user:pass в формат .yt_proxy.json."""
    parts = proxy_string.strip().split(':')
    if len(parts) < 4:
        raise ValueError('Invalid proxy string format. Expected host:port:login:pass')
    host, port, user = parts[0], parts[1], parts[2]
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        raise ValueError(f'Invalid proxy port: {port}')
    host_ok = bool(re.fullmatch(r'(?:\d{1,3}|\*)(?:\.(?:\d{1,3}|\*)){3}', host)) or (
        '.' in host and not host.startswith('.') and ' ' not in host
    )
    if not host_ok:
        raise ValueError(f'Invalid proxy host: {host}')
    password = ':'.join(parts[3:])
    return {
        'raw': proxy_string,
        'server': f'http://{host}:{port}',
        'username': user,
        'password': password,
        'public_ip': '',
        'source': 'manual',
    }


def proxy_request_url(proxy: dict) -> str:
    """URL прокси для urllib: пароль с / @ # кодируется, иначе проверка врёт «Мёртв»."""
    if not isinstance(proxy, dict):
        return ''
    raw = str(proxy.get('raw') or '').strip()
    host = ''
    port = ''
    user = str(proxy.get('username') or '')
    password = str(proxy.get('password') or '')
    scheme = 'http'
    if raw.count(':') >= 3:
        parsed = parse_proxy_string_to_dict(raw)
        server = parsed.get('server') or ''
        user = str(parsed.get('username') or user)
        password = str(parsed.get('password') or password)
    else:
        server = str(proxy.get('server') or '').strip()
    if server and '://' not in server:
        server = f'http://{server}'
    if server:
        parsed = urlparse(server)
        scheme = parsed.scheme or 'http'
        host = parsed.hostname or ''
        try:
            port = str(parsed.port or '')
        except ValueError:
            port = ''
    if not host or not port:
        return ''
    if user:
        auth = f'{quote(user, safe="")}:{quote(password, safe="")}'
        return f'{scheme}://{auth}@{host}:{port}'
    return f'{scheme}://{host}:{port}'


def _yt_proxy_relay_module():
    """proxy_relay из YT-COOKIES (цепочка через v2rayN); None, если недоступен."""
    for candidate in (YT_COOKIES_DIR, Path(__file__).resolve().parent / 'YT-COOKIES'):
        if not (candidate / 'proxy_relay.py').is_file():
            continue
        yt_dir_s = str(candidate.resolve())
        if yt_dir_s not in sys.path:
            sys.path.insert(0, yt_dir_s)
        try:
            import proxy_relay

            return proxy_relay
        except Exception:
            return None
    return None


def local_proxy_chain_label() -> str:
    """'v2rayN 127.0.0.1:10808', если локальный SOCKS5 жив и выпускает в интернет; иначе ''.

    YT_AUTO_NO_BRIDGE=0 — не переключаться автоматически (старое поведение с мостом).
    """
    if os.environ.get('YT_AUTO_NO_BRIDGE', '1').strip().lower() in ('0', 'off', 'no', 'false'):
        return ''
    mod = _yt_proxy_relay_module()
    if mod is None:
        return ''
    try:
        if mod.chain_socks(refresh=True) is None or not mod.chain_healthy():
            return ''
        return str(mod.chain_label())
    except Exception:
        return ''


def proxy_check_url(proxy: dict) -> str:
    """URL для urllib-проверок: через локальный relay/цепочку (v2rayN), если она активна.

    Прямое TCP с этого ПК к Cliproxy провайдер режет после ~16–26 КБ, а Chrome ходит
    через relay → 127.0.0.1:10808 → Cliproxy. Проверять надо той же дорогой.
    """
    server_url = proxy_request_url(proxy)
    if not server_url:
        return ''
    mod = _yt_proxy_relay_module()
    if mod is None:
        return server_url
    try:
        parsed = urlparse(server_url)
        via = mod.relay_proxy_for_checks(
            {
                'server': f'{parsed.scheme}://{parsed.hostname}:{parsed.port}',
                'username': unquote(str(parsed.username or '')),
                'password': unquote(str(parsed.password or '')),
            }
        )
    except Exception:
        return server_url
    if via and str(via.get('server', '')).startswith('http://127.0.0.1:'):
        return str(via['server'])
    return server_url


def proxy_dict_to_string(proxy: dict) -> str:
    """Преобразует .yt_proxy.json обратно в host:port:user:pass."""
    server = proxy.get('server', '')
    if '://' in server:
        server = server.split('://', 1)[1]
    host_port = server.split(':')
    if len(host_port) != 2:
        return ''
    host, port = host_port
    user = proxy.get('username', '')
    pwd = proxy.get('password', '')
    if user:
        return f'{host}:{port}:{user}:{pwd}'
    return f'{host}:{port}'


def save_account_proxy(account_dir: str | Path, proxy: dict | str | None) -> bool:
    """Сохраняет прокси в .yt_proxy.json. proxy может быть dict или строкой host:port:user:pass."""
    if not proxy:
        return False
    path = Path(account_dir) / '.yt_proxy.json'
    try:
        if isinstance(proxy, str):
            proxy = parse_proxy_string_to_dict(proxy)
        else:
            raw = str(proxy.get('raw') or '').strip()
            if raw.count(':') >= 3:
                parse_proxy_string_to_dict(raw)
        data = dict(proxy)
        data.setdefault('source', 'manual')
        if not str(data.get('bound_at') or '').strip():
            data['bound_at'] = datetime.now().isoformat()
        _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        return True
    except Exception:
        return False


def clear_account_proxy(account_dir: str | Path) -> bool:
    """Удаляет .yt_proxy.json у аккаунта."""
    path = Path(account_dir) / '.yt_proxy.json'
    try:
        if path.is_file():
            path.unlink()
        return True
    except Exception:
        return False


DEAD_PROXIES_LOG = Path(__file__).resolve().parent / 'мертвые_прокси.txt'
_last_dead_proxy_log: tuple[str, str, float] = ('', '', 0.0)
_DEAD_PROXY_LINE_RE = re.compile(
    r'^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}\s+(.+)$'
)
_EXPORT_IP_IN_TEXT_RE = re.compile(
    r'(?:export(?:\s+ip)?|reachable)\s*[:=]?\s*\(?(\d{1,3}(?:\.\d{1,3}){3})\)?',
    re.I,
)


def _dead_proxy_key(raw: str) -> str:
    return str(raw or '').strip().lower()


def _host_port_from_proxy_raw(raw: str) -> str:
    parts = str(raw or '').strip().split(':')
    if len(parts) >= 2 and parts[1].isdigit():
        return f'{parts[0].lower()}:{parts[1]}'
    return ''


def _looks_exit_ip(token: str) -> bool:
    text = str(token or '').strip().lower()
    if not text or ':' in text:
        return False
    parts = text.split('.')
    if len(parts) != 4:
        return False
    return all(p == '*' or p.isdigit() for p in parts)


def export_ip_from_cliproxy_text(text: str) -> str:
    """Exit-IP из лога Cliproxy: (export IP …) / (export …) / reachable (…)."""
    last = ''
    for line in str(text or '').splitlines():
        for match in _EXPORT_IP_IN_TEXT_RE.finditer(line):
            last = match.group(1)
    return last


def _parse_dead_proxy_line(line: str) -> tuple[str, str, str]:
    """(raw_proxy, host_port, exit_ip) — все в lower."""
    text = str(line or '').strip()
    if not text:
        return '', '', ''
    match = _DEAD_PROXY_LINE_RE.match(text)
    rest = match.group(1).strip() if match else text
    bits = rest.split()
    exit_ip = ''
    if bits and _looks_exit_ip(bits[-1]):
        exit_ip = bits[-1].lower()
        bits = bits[:-1]
    raw = ' '.join(bits).lower()
    return raw, _host_port_from_proxy_raw(raw), exit_ip


def _proxy_from_dead_line(line: str) -> str:
    raw, host_port, _exit_ip = _parse_dead_proxy_line(line)
    return raw or host_port


def _dead_keys_for(raw: str, extra_ip: str = '') -> set[str]:
    keys: set[str] = set()
    text = _dead_proxy_key(raw)
    if text and text != '—':
        keys.add(text)
        host_port = _host_port_from_proxy_raw(text)
        if host_port:
            keys.add(host_port)
    ip = str(extra_ip or '').strip().lower()
    if _looks_exit_ip(ip):
        keys.add(ip)
    keys.discard('')
    return keys


def logged_dead_proxy_keys() -> set[str]:
    keys = _dead_keys_for(_last_dead_proxy_log[1], _last_dead_proxy_log[0])
    if not DEAD_PROXIES_LOG.is_file():
        return keys
    try:
        for line in DEAD_PROXIES_LOG.read_text(encoding='utf-8', errors='replace').splitlines():
            raw, host_port, exit_ip = _parse_dead_proxy_line(line)
            if raw:
                keys.add(raw)
            if host_port:
                keys.add(host_port)
            if exit_ip:
                keys.add(exit_ip)
    except Exception:
        return keys
    return keys


def dead_proxy_already_logged(raw: str, extra_ip: str = '') -> bool:
    """True, если этот слот (host:port) или exit-IP уже есть в мёртвые_прокси.txt."""
    incoming = _dead_keys_for(raw, extra_ip)
    if not incoming:
        return False
    return bool(incoming & logged_dead_proxy_keys())


def dead_proxy_exclude_tokens() -> list[str]:
    """host:port и exit-IP из журнала — чтобы Cliproxy не брал тот же мёртвый узел."""
    tokens: list[str] = []
    seen: set[str] = set()
    for key in logged_dead_proxy_keys():
        if key.count(':') == 1 and key.split(':')[1].isdigit():
            pass
        elif _looks_exit_ip(key):
            pass
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        tokens.append(key)
    return tokens


def log_dead_proxy(account_dir=None, detail='', proxy=None) -> bool:
    """Дописывает дату, host:port:login:pass и exit-IP. False, если слот/узел уже в журнале."""
    global _last_dead_proxy_log
    del detail
    folder = Path(account_dir) if account_dir else None
    if proxy is None and folder is not None:
        proxy = read_account_proxy(folder)
    raw = proxy_display(proxy) if has_account_proxy(proxy) else ''
    if raw == '—' or not raw:
        return False
    extra_ip = ''
    if isinstance(proxy, dict):
        extra_ip = str(proxy.get('public_ip') or '').strip()
    if dead_proxy_already_logged(raw, extra_ip):
        return False
    stamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    line = f'{stamp} {raw}'
    if extra_ip and extra_ip.lower() not in raw.lower() and _looks_exit_ip(extra_ip):
        line += f' {extra_ip}'
    DEAD_PROXIES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DEAD_PROXIES_LOG, 'a', encoding='utf-8') as handle:
        handle.write(line + '\n')
    _last_dead_proxy_log = (extra_ip, raw, time.time())
    return True


def record_dead_purchase_proxy(account_dir, detail='', status_callback=None) -> bool:
    """После неудачной покупки: если прокси мёртв — строка в файл."""
    proxy = read_account_proxy(account_dir)
    if not has_account_proxy(proxy):
        return False
    err = str(detail or '').strip()
    if not err:
        ok, err = check_proxy_status(proxy, timeout=8.0, tries=1)
        if ok:
            return False
    wrote = log_dead_proxy(account_dir, err, proxy)
    if wrote and status_callback:
        status_callback(f'Мёртвый прокси записан в {DEAD_PROXIES_LOG.name}')
    return wrote


def proxy_display(proxy: dict | None) -> str:
    """Полная строка прокси для локальной таблицы: host:port:login:pass."""
    if not isinstance(proxy, dict) or not proxy:
        return '—'
    raw = str(proxy.get('raw') or '').strip()
    if raw.count(':') >= 3:
        return raw
    username = str(proxy.get('username') or '')
    password = str(proxy.get('password') or '')
    host = ''
    port = ''
    server = str(proxy.get('server') or '').strip()
    if server:
        text = server if '://' in server else f'http://{server}'
        try:
            parsed = urlparse(text)
            host = parsed.hostname or ''
            try:
                port = str(parsed.port or '')
            except ValueError:
                port = ''
            if parsed.username and not username:
                username = unquote(parsed.username)
            if parsed.password and not password:
                password = unquote(parsed.password)
        except Exception:
            host = ''
        if not host:
            rest = server.split('://', 1)[-1]
            bits = rest.split(':')
            host = bits[0]
            if len(bits) > 1 and bits[1].isdigit():
                port = bits[1]
    if not host and raw:
        parts = raw.split(':')
        if parts:
            host = parts[0]
            if len(parts) > 1:
                port = parts[1]
    if not host:
        return '—'
    if username:
        return f'{host}:{port or "?"}:{username}:{password}'
    return f'{host}:{port}' if port else host


def proxy_log_display(proxy: dict | None) -> str:
    """Прокси для логов без пароля."""
    full = proxy_display(proxy)
    parts = full.split(':')
    if len(parts) >= 4:
        return f'{parts[0]}:{parts[1]}:{parts[2]}:***'
    return full


_TRANSIENT_PROXY_NEEDLES = (
    'unexpected_eof',
    'wrong_version_number',
    'eof occurred in violation',
    'timed out',
    'timeout',
    'timedout',
    'connection reset',
    'connection aborted',
    'connection refused',
    'temporarily unavailable',
    'tunnel connection failed',
    'broken pipe',
    'winerror 10054',
    'winerror 10060',
    'winerror 10053',
    'winerror 10061',
    'remote end closed',
    'remotedisconnected',
    'badstatusline',
    'incompleteread',
    'network is unreachable',
    'no route to host',
    'ssl:',
    'urlopen error',
)


def is_transient_proxy_error(detail: object) -> bool:
    """SSL EOF / timeout — типично для только что поднятого Cliproxy, не «мёртвый IP».

    Исключение — когда диагностика уже показала, что сервер Cliproxy сам закрыл туннель
    (exit-узел отказал): это не «ещё не поднялся», а мёртвый у провайдера IP.
    """
    low = str(detail or '').lower()
    if not low or low in ('нет прокси', 'прокси не сохранён'):
        return False
    if low.startswith('http ') and '407' in low:
        return False
    if proxy_diag.is_exit_refused_detail(detail) or 'cliproxy 407' in low:
        return False
    return any(n in low for n in _TRANSIENT_PROXY_NEEDLES)


def _with_tunnel_diagnosis(proxy: dict, detail: str, status_callback=None) -> str:
    """К urllib-ошибке добавляет реальную причину с TCP-уровня (CONNECT 200 + обрыв, 407…).

    Возвращает детальную строку для статуса; при exit_refused шлёт объяснение в лог.
    Запускается только для «мутных» ошибок (SSL EOF, BadStatusLine, timeout, URLError) —
    HTTP 407 и «нет прокси» и так понятны.
    """
    if not is_transient_proxy_error(detail):
        return detail
    try:
        code, low_detail = proxy_diag.diagnose_proxy_tunnel(proxy, timeout=6.0)
    except Exception:
        return detail
    if code in (proxy_diag.CODE_OK, proxy_diag.CODE_UNKNOWN):
        return detail
    short = proxy_diag.short(code)
    if status_callback:
        if code == proxy_diag.CODE_EXIT_REFUSED:
            status_callback(
                f'✗ {proxy_diag.human(code)}. Проверка шла напрямую: {low_detail}'
            )
        else:
            status_callback(f'Диагностика прокси: {proxy_diag.human(code)} ({low_detail})')
    return f'{detail} · {short}' if short else detail


def _check_proxy_status_once(proxy: dict, timeout: float = 12.0) -> tuple[bool, str]:
    """Одна попытка: сначала HTTP (как на сайте Online), потом HTTPS.

    Google generate_204 через urllib часто врёт «Мёртв» на ISP Cliproxy:
    медленный CONNECT, блокировка Google, пароль с «/» в URL.
    """
    if not proxy:
        return False, 'Нет прокси'
    direct = proxy_request_url(proxy)
    if not direct:
        return False, 'Нет прокси'
    if urlparse(direct).scheme.lower().startswith('socks5'):
        socks = 'socks5h://' + direct.split('://', 1)[-1]
        info = cliproxy_app.geo_lookup_socks5(socks, timeout=timeout)
        if info and info.get('ip'):
            return True, f'OK · {info["ip"]}'
        return False, 'SOCKS5 не ответил'
    server_url = proxy_check_url(proxy)
    if not server_url:
        return False, 'Нет прокси'
    handler = urllib.request.ProxyHandler({'http': server_url, 'https': server_url})
    opener = urllib.request.build_opener(handler)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    last = 'Нет ответа'
    probes = (
        ('http://ip-api.com/json/?fields=query', True),
        ('http://api.ipify.org', True),
        ('https://api.ipify.org', True),
        ('https://www.google.com/generate_204', False),
    )
    for url, want_ip in probes:
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                status = getattr(resp, 'status', 0) or 0
                body = resp.read().decode('utf-8', errors='replace').strip()
            if want_ip:
                ip = ''
                if body.startswith('{'):
                    try:
                        ip = str(json.loads(body).get('query') or '').strip()
                    except Exception:
                        ip = ''
                elif re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', body):
                    ip = body
                if ip:
                    return True, f'OK · {ip}'
                if status in (200, 204):
                    return True, 'OK'
                last = f'HTTP {status}'
                continue
            if status in (200, 204):
                return True, 'OK'
            last = f'HTTP {status}'
        except urllib.error.HTTPError as exc:
            if exc.code in (200, 204):
                return True, 'OK'
            last = f'HTTP {exc.code}'
        except Exception as exc:
            last = f'{exc.__class__.__name__}: {str(exc)[:40]}'
    return False, last


def check_proxy_status(
    proxy: dict,
    timeout: float = 12.0,
    tries: int = 1,
    pause: float = 1.5,
) -> tuple[bool, str]:
    """Живость прокси. tries>1 — повтор при обрыве SSL/timeout (новый туннель часто не сразу)."""
    last = 'Нет ответа'
    attempts = max(1, int(tries))
    wait = max(0.0, float(pause))
    for i in range(attempts):
        ok, last = _check_proxy_status_once(proxy, timeout=timeout)
        if ok:
            return True, last
        if i + 1 >= attempts or not is_transient_proxy_error(last):
            break
        if wait:
            time.sleep(wait)
    return False, _with_tunnel_diagnosis(proxy, last)


def wait_proxy_ready(
    proxy: dict,
    status_callback=None,
    *,
    tries: int = 4,
    pause: float = 2.5,
    settle: float = 3.0,
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """Cliproxy показывает Online раньше, чем HTTPS-туннель начинает отвечать."""
    if not proxy:
        return False, 'Нет прокси'
    wait_settle = max(0.0, float(settle))
    if wait_settle:
        if status_callback:
            status_callback(
                f'Новый прокси не всегда сразу доступен — жду {wait_settle:.0f} с…'
            )
        time.sleep(wait_settle)
    last = 'Нет ответа'
    attempts = max(1, int(tries))
    wait = max(0.0, float(pause))
    for i in range(attempts):
        ok, last = _check_proxy_status_once(proxy, timeout=timeout)
        if ok:
            if i > 0 and status_callback:
                status_callback(f'Прокси поднялся с {i + 1}-й попытки ({last})')
            return True, last
        if i + 1 >= attempts:
            break
        if status_callback:
            status_callback(
                f'Прокси ещё не ответил ({last}), повтор через {wait:.0f} с…'
            )
        if wait:
            time.sleep(wait)
    return False, _with_tunnel_diagnosis(proxy, last, status_callback)


def _check_account_proxy(acc: dict) -> dict:
    """Проверяет прокси аккаунта и записывает статус в dict."""
    proxy = read_account_proxy(acc['path'])
    if proxy:
        ok, detail = check_proxy_status(proxy, timeout=10.0, tries=2, pause=2.0)
        acc['proxy_status'] = 'OK' if ok else 'Мёртв'
        acc['proxy_status_detail'] = detail
    else:
        acc['proxy_status'] = 'Нет'
        acc['proxy_status_detail'] = 'Прокси не сохранён'
    return acc


def _apply_saved_proxy_status(acc: dict) -> dict:
    """Ставит статус прокси по .yt_proxy.json, без проверки сети."""
    if read_account_proxy(acc.get('path')):
        acc.setdefault('proxy_status', '…')
        acc.setdefault('proxy_status_detail', '')
    else:
        acc.setdefault('proxy_status', 'Нет')
        acc.setdefault('proxy_status_detail', 'Прокси не сохранён')
    return acc


def scan_accounts(
    yt_cookies_dir: str | Path | None = None,
    check_proxy: bool = False,
    yda_root: str | Path | None = None,
) -> list[dict]:
    """Возвращает обычные Chrome-профили daily-агента и логи из _zip_cache."""
    cache_dir = _normalize_dir(yt_cookies_dir) / '_zip_cache'
    cookies: list[dict] = []
    if cache_dir.is_dir():
        cookies = [
            read_account_info(item, fetch_isp=False)
            for item in cache_dir.iterdir() if item.is_dir()
        ]
    cookies.sort(key=lambda a: a.get('date_added_ts', 0), reverse=True)
    for acc in cookies:
        acc['kind'] = plain_profiles.KIND_COOKIES
        acc.setdefault('kind_label', 'Лог')
        acc['label'] = read_account_label(acc['path'])
        acc['last_opened'] = read_last_opened(acc['path'])
        acc['autonomous'] = read_autonomous(acc['path'], acc['label'])
        acc.setdefault('proxy_status', '…')
        acc.setdefault('proxy_status_detail', '')
        apply_table_overrides(acc)
    plains: list[dict] = []
    try:
        found_plains = plain_profiles.scan_plain_accounts(yda_root)
    except Exception:
        found_plains = []
    for acc in found_plains:
        try:
            acc['label'] = read_account_label(acc['path'])
            acc['last_opened'] = read_last_opened(acc['path'])
            acc['autonomous'] = read_autonomous(acc['path'], acc.get('label'))
            _apply_saved_proxy_status(acc)
            apply_table_overrides(acc)
        except Exception:
            acc.setdefault('label', '')
            acc.setdefault('last_opened', '')
        plains.append(acc)
    accounts = plains + cookies
    if check_proxy:
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(_check_account_proxy, accounts)
    return accounts


def read_account_snapshot(account_dir: str | Path) -> dict | None:
    account_dir = Path(account_dir)
    if not account_dir.is_dir():
        return None
    if plain_profiles.is_plain_profile(account_dir):
        number = plain_profiles.profile_number_from_name(account_dir.name) or 0
        acc = plain_profiles.read_plain_account(account_dir, number)
        acc['label'] = read_account_label(account_dir)
        acc['last_opened'] = read_last_opened(account_dir)
        acc['autonomous'] = read_autonomous(account_dir, acc.get('label'))
        _apply_saved_proxy_status(acc)
        apply_table_overrides(acc)
        return acc
    acc = read_account_info(account_dir, fetch_isp=False)
    acc['kind'] = plain_profiles.KIND_COOKIES
    acc.setdefault('kind_label', 'Лог')
    acc['label'] = read_account_label(account_dir)
    acc['last_opened'] = read_last_opened(account_dir)
    acc['autonomous'] = read_autonomous(account_dir, acc.get('label'))
    acc.setdefault('proxy_status', '…')
    acc.setdefault('proxy_status_detail', '')
    apply_table_overrides(acc)
    return acc


def _resolve_yt_cookies_dir(account_dir: str | Path) -> Path:
    """По пути аккаунта находит корневую папку YT-COOKIES."""
    account_dir = Path(account_dir).resolve()
    # account_dir: .../YT-COOKIES/_zip_cache/NAME
    return account_dir.parent.parent


def _ensure_bridge(yt_cookies_dir: Path, bridge_url: str, status_callback=None):
    """Проверяет/запускает мост. Возвращает (bridge_url, control_port, is_local)."""
    if not bridge_url:
        bridge_url, control_port = buyer_core._read_lan_bridge_config(str(yt_cookies_dir))
        if not bridge_url:
            bridge_url = 'http://127.0.0.1:8765'
            control_port = 8767
    else:
        control_port = 8767

    parsed = urlparse(bridge_url)
    bridge_host = parsed.hostname or '127.0.0.1'
    relay_port = parsed.port or 8765
    is_local = buyer_core._is_local_bridge(bridge_url)

    if is_local:
        buyer_core._write_lan_bridge(str(yt_cookies_dir), bridge_url, control_port, status_callback)
        if not buyer_core._check_bridge(bridge_host, relay_port, timeout=0.5) or not buyer_core._check_bridge(bridge_host, control_port, timeout=0.5):
            buyer_core._start_yt_cookies_bridge(str(yt_cookies_dir), status_callback)
            for _ in range(60):
                if buyer_core._check_bridge(bridge_host, relay_port, timeout=0.5) and buyer_core._check_bridge(bridge_host, control_port, timeout=0.5):
                    break
                time.sleep(0.5)
    else:
        if status_callback:
            status_callback(f'Using remote LAN bridge: {bridge_url}')
        if not buyer_core._check_bridge(bridge_host, relay_port, timeout=1.0) or not buyer_core._check_bridge(bridge_host, control_port, timeout=1.0):
            if status_callback:
                status_callback(f'LAN-мост {bridge_url} пока не отвечает, жду…')
            relay_ok = buyer_core._wait_bridge(
                bridge_host, relay_port, timeout=1.0, attempts=10, pause=0.4,
            )
            ctrl_ok = buyer_core._wait_bridge(
                bridge_host, control_port, timeout=1.0, attempts=6, pause=0.3,
            )
            if not (relay_ok and ctrl_ok) and status_callback:
                status_callback(
                    f'Remote LAN bridge {bridge_url} not reachable; youtube_browser повторит проверку'
                )

    return bridge_url, control_port, is_local


VERIFY_EXIT_CODE = 4
VERIFY_RETRY_MARKER = 'VERIFY_IDENTITY_RETRY'
LOGGED_OUT_EXIT_CODE = 5
LOGGED_OUT_MARKER = 'ACCOUNT_LOGGED_OUT'
STUDIO_FAIL_EXIT_CODE = 6
BROWSER_CLOSED_EXIT_CODE = 7
STREAM_KEY_MARKER = 'STREAM_KEY_COPIED'
RTMP_PUSH_DONE = 'RTMP_PUSH_DONE'
NO_LIVE_EXIT_CODE = 8
NO_LIVE_MARKER = 'NO_LIVESTREAM'
STUDIO_OPEN_ONLY_MARKER = 'STUDIO_OPEN_ONLY_DONE'
AUTOMATION_ATTACH_MARKER = 'AUTOMATION_ATTACH_DONE'
BROWSER_ALIVE_FILE = '.yt_browser_alive'
ATTACH_DONE_FILE = '.yt_attach_done'
LABEL_TOP = '⭐ ТОП'
LABEL_VERIFY = 'Verify'
LABEL_DEAD = '💀 Мертвый'
LABEL_NO_LIVE = '⚠ НЕТ ТРАНСЛЯЦИЙ'
LABEL_NOT_IN = 'НЕ ЗАШЕЛ'
LABEL_NOT_IN_LEGACY = '❌ Не зашел'
ACCOUNT_LABELS = (LABEL_TOP, LABEL_VERIFY, LABEL_DEAD, LABEL_NO_LIVE, LABEL_NOT_IN)


def normalize_account_label(label: str) -> str:
    text = str(label or '').strip()
    if text == LABEL_NOT_IN_LEGACY:
        return LABEL_NOT_IN
    return text


def label_hint_from_yt_line(line: str) -> str:
    """Метка по строке лога, пока youtube_browser ещё работает."""
    text = str(line or '')
    if VERIFY_RETRY_MARKER in text:
        return LABEL_VERIFY
    # Предупреждение «может показать Verify» — не диалог и не метка.
    if 'может показать' in text or 'высокий риск' in text:
        return ''
    stripped = text.lstrip()
    if stripped.startswith('✗') and (
        'Verify that it' in text or "Verify it's you" in text or 'Verify it’s you' in text
    ):
        return LABEL_VERIFY
    return ''


def _finish_no_livestream(account_dir, status_callback, *, delete: bool) -> bool:
    """Лог без эфиров удаляем. Обычный daily-профиль только помечаем."""
    if delete:
        if status_callback:
            status_callback('В Studio нет трансляций (Request access) — удаляю аккаунт')
        delete_account(account_dir, status_callback)
        return False
    save_account_label(account_dir, LABEL_NO_LIVE)
    if status_callback:
        status_callback('В Studio нет трансляций — метка «НЕТ ТРАНСЛЯЦИЙ»')
    return False


def _finish_logged_out(
    account_dir, status_callback, *, delete: bool, keys_saved: bool = False,
) -> bool:
    """Разлог: лог из _zip_cache удаляем. Обычный daily-профиль только помечаем."""
    save_autonomous(account_dir, False)
    if not delete:
        save_account_label(account_dir, LABEL_DEAD)
        if status_callback:
            status_callback(
                'Профиль разлогинен — метка «Мертвый». Папку не удаляю, это общий профиль daily-агента'
            )
        return False
    if status_callback:
        if keys_saved:
            status_callback(
                'Аккаунт разлогинен посреди автоматизации — ключи сохранены; '
                'удаляю лог и убираю из очереди'
            )
        else:
            status_callback('Аккаунт разлогинен — удаляю лог и убираю из очереди')
    try:
        close_idle_browser(account_dir)
    except Exception:
        pass
    try:
        _kill_chrome_for_profile(Path(account_dir) / 'browser_profile')
    except Exception:
        pass
    deleted = delete_account(account_dir, status_callback)
    if not deleted and Path(account_dir).is_dir():
        save_account_label(account_dir, LABEL_DEAD)
        if status_callback:
            status_callback(
                'Не удалось удалить лог — ставлю метку «Мертвый» и исключаю из очереди'
            )
    return False


def _proxy_is_random_country(proxy) -> bool:
    if not isinstance(proxy, dict):
        return False
    return bool(proxy.get('random_country'))


def _proxy_exclude_tokens(proxy) -> list[str]:
    """host:port и public_ip. Голый шлюз Cliproxy (один IP на все порты) не исключаем."""
    tokens: list[str] = []
    if not proxy:
        return tokens
    if isinstance(proxy, dict):
        raw = proxy.get('raw') or proxy_dict_to_string(proxy)
        public_ip = str(proxy.get('public_ip') or '').strip()
        if public_ip:
            tokens.append(public_ip)
    else:
        raw = str(proxy)
    raw = (raw or '').strip()
    if raw:
        parts = raw.split(':')
        if len(parts) >= 2 and parts[0] and parts[1]:
            host, port = parts[0], parts[1]
            host_ok = ('.' in host and ' ' not in host) or bool(
                re.fullmatch(r'(?:\d{1,3}|\*)(?:\.(?:\d{1,3}|\*)){3}', host)
            )
            if host_ok and port.isdigit() and 1 <= int(port) <= 65535:
                tokens.append(f'{host}:{port}')
        elif parts and parts[0] and '.' in parts[0]:
            tokens.append(parts[0])
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(token)
    return unique


def _proxy_in_excluded(proxy, excluded) -> bool:
    tokens = {t.lower() for t in _proxy_exclude_tokens(proxy)}
    excluded_l = {str(x).lower() for x in (excluded or []) if str(x).strip()}
    return bool(tokens and excluded_l and tokens & excluded_l)


def _push_account_proxy(account_dir, bridge_url, control_port, is_local, yt_cookies_dir, status_callback):
    proxy = read_account_proxy(account_dir)
    if not proxy:
        if status_callback:
            status_callback('У аккаунта нет сохранённого прокси; YT-COOKIES запросит его вручную')
        return None
    raw = proxy_dict_to_string(proxy)
    if status_callback:
        host = raw.split(':')[0]
        port = raw.split(':')[1] if raw.count(':') >= 1 else ''
        status_callback(f'Прокси аккаунта: {host}:{port}')
    pushed = buyer_core._push_proxy_to_bridge(
        bridge_url, raw, control_port=control_port,
        status_callback=status_callback, yt_cookies_dir=str(yt_cookies_dir),
    )
    if not pushed and is_local:
        if status_callback:
            status_callback('Proxy push failed, restarting bridge and retrying...')
        buyer_core._start_yt_cookies_bridge(str(yt_cookies_dir), status_callback)
        for _ in range(20):
            host = bridge_url.split('://')[-1].split(':')[0]
            if buyer_core._check_bridge(host, 8765, timeout=0.5) and buyer_core._check_bridge(host, control_port, timeout=0.5):
                break
            time.sleep(0.5)
        buyer_core._push_proxy_to_bridge(
            bridge_url, raw, control_port=control_port,
            status_callback=status_callback, yt_cookies_dir=str(yt_cookies_dir),
        )
    return proxy


def _chrome_bridge_plan(
    account_dir,
    yt_cookies_dir,
    bridge_url='',
    use_bridge=True,
    status_callback=None,
):
    """Как у логов: удалённый LAN-мост получает прокси, локальный общий мост не трогаем.

    Returns (bridge_url, chrome_use_bridge, control_port, is_local, proxy).
    """
    account_dir = Path(account_dir)
    yt_cookies_dir = Path(yt_cookies_dir)
    proxy = read_account_proxy(account_dir)
    if not has_account_proxy(proxy):
        if status_callback:
            status_callback('Прокси нет — Chrome с интернетом компьютера')
        return '', False, 8767, True, None
    if use_bridge and proxy:
        chain = local_proxy_chain_label()
        if chain:
            if status_callback:
                status_callback(
                    f'LAN-мост не нужен: Chrome пойдёт relay → {chain} → {proxy_display(proxy)} '
                    '(тот же VPN-путь, что у второго ПК)'
                )
            use_bridge = False
    if not use_bridge:
        if status_callback:
            if proxy:
                status_callback(
                    f'Без моста: привязываю {proxy_log_display(proxy)} и открываю Chrome напрямую'
                )
            else:
                status_callback('Без моста, но .yt_proxy.json нет — IP не к чему привязать')
        return '', False, 8767, True, proxy

    configured, _configured_port = buyer_core._read_lan_bridge_config(str(yt_cookies_dir))
    probe = (bridge_url or configured or 'http://127.0.0.1:8765').strip()
    if '://' not in probe:
        probe = f'http://{probe}'
    if buyer_core._is_local_bridge(probe):
        if status_callback:
            status_callback(
                'Локальный мост общий — Chrome этого аккаунта идёт через свой прокси, не через чужой'
            )
        return '', False, 8767, True, proxy

    bridge_url, control_port, is_local = _ensure_bridge(
        yt_cookies_dir, bridge_url, status_callback,
    )
    proxy = _push_account_proxy(
        account_dir, bridge_url, control_port, is_local, yt_cookies_dir, status_callback,
    )
    return bridge_url, True, control_port, is_local, proxy


def bind_saved_proxy_to_bridge(account_dir, status_callback=None, use_bridge=True, bridge_url='') -> bool:
    """После вставки прокси в профиль — сразу прокинуть его на LAN-мост, как у логов."""
    yt_cookies_dir = YT_COOKIES_DIR
    if not yt_cookies_dir.is_dir():
        yt_cookies_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
    url, chrome_use_bridge, _port, _local, proxy = _chrome_bridge_plan(
        account_dir,
        yt_cookies_dir,
        bridge_url=bridge_url,
        use_bridge=use_bridge,
        status_callback=status_callback,
    )
    return bool(chrome_use_bridge and url and proxy)


def _launch_yt_cookies(
    account_dir, yt_cookies_dir, project_root, bridge_url, force_audit, extra_args,
    status_callback, use_bridge=True, keep_verify=False, open_only=False,
    plain_profile=False, login_only=False,
) -> int:
    """Запускает youtube_browser.py напрямую, без cmd/run.bat."""
    global _current_proc, _current_account_dir, _last_stream_key, _last_stream_keys
    global _last_chrome_started, _last_youtube_open, _last_proxy_dead, _last_proxy_mid
    _last_chrome_started = False
    _last_youtube_open = False
    _last_proxy_dead = False
    _last_proxy_mid = False
    python = buyer_core._get_yt_cookies_python() or sys.executable
    script = str(Path(yt_cookies_dir) / 'youtube_browser.py')
    if plain_profile:
        cmd = [python, '-u', script, '--plain-profile', str(account_dir)]
    else:
        cmd = [python, '-u', script, '--dir', str(account_dir)]
    if force_audit and not plain_profile:
        cmd.append('--force-audit')
    if use_bridge and bridge_url:
        cmd += ['--lan-bridge', str(bridge_url)]
    else:
        cmd.append('--no-bridge')
    extra_list: list[str] = []
    if extra_args:
        if isinstance(extra_args, (list, tuple)):
            extra_list = [str(x) for x in extra_args if str(x)]
        else:
            extra_list = shlex.split(str(extra_args), posix=False)
    extra_blob = ' '.join(extra_list)
    if extra_list:
        cmd.extend(extra_list)
        if (
            '--create-streams' in extra_blob
            and '--studio-live' not in extra_list
            and '--studio-open-only' not in extra_list
            and not open_only
        ):
            cmd.append('--studio-live')
    elif open_only:
        cmd.append('--studio-open-only')
    elif login_only:
        cmd.append('--plain-login')
    else:
        cmd.append('--studio-live')
    if open_only and '--studio-open-only' not in cmd:
        cmd.append('--studio-open-only')
    if keep_verify:
        cmd.append('--keep-verify')

    if status_callback:
        prefix = 'Запуск обычного профиля' if plain_profile else 'Запуск YT-COOKIES'
        status_callback(f'{prefix}: {" ".join(cmd)}')
    try:
        run_log_path = Path(yt_cookies_dir) / 'yt_cookies_run.log'
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONFAULTHANDLER'] = '1'
        env['TG_SKACHKA_NOCONSOLE'] = '1'
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
            **buyer_core.hidden_subprocess_kwargs(),
        )
        _current_proc = proc
        _current_account_dir = str(account_dir)
        register_child_pid(proc.pid)
        attach_event = threading.Event()
        if open_only:
            _remember_idle_browser(account_dir, proc, attach_event)
        try:
            proc.stdin.write('1\n')
            proc.stdin.close()
        except Exception:
            pass
        _last_stream_keys = []
        verify_seen = False
        logged_out_seen = False
        stream_ok = False
        no_live_seen = False
        session_ok = False
        proxy_dead_detail = ''
        mid_proxy_seen = False
        studio_open_only_done = False
        chrome_started = False
        youtube_open_seen = False
        stream_key = ''
        last_out = {'t': time.monotonic()}
        idle_stop = threading.Event()

        def _note_account_line():
            last_out['t'] = time.monotonic()
            touch_account_activity(account_dir)

        def _parent_idle_watch():
            while not idle_stop.wait(15):
                if proc.poll() is not None:
                    return
                if time.monotonic() - last_out['t'] >= IDLE_CLOSE_SEC:
                    close_hung_account(account_dir, proc, status_callback)
                    return

        if not login_only:
            threading.Thread(target=_parent_idle_watch, name='idle-parent', daemon=True).start()
        with open(run_log_path, 'a', encoding='utf-8', errors='replace', buffering=1) as run_log_file:
            for line in proc.stdout:
                line = line.rstrip('\n')
                if line:
                    _note_account_line()
                    run_log_file.write(line + '\n')
                    # Ошибка обработки одной строки (метка, колбэк GUI) не должна
                    # рвать чтение stdout и возвращать код 1 с осиротевшим браузером.
                    try:
                        hint = label_hint_from_yt_line(line)
                        if hint:
                            save_account_label(account_dir, hint)
                        if hint == LABEL_VERIFY:
                            verify_seen = True
                        if LOGGED_OUT_MARKER in line:
                            logged_out_seen = True
                        if STREAM_KEY_MARKER in line:
                            stream_ok = True
                            parts = line.split(STREAM_KEY_MARKER, 1)[-1]
                            stream_key = parts.replace(':', '', 1).strip()
                            save_last_stream_key(account_dir, stream_key)
                        push_m = PUSH_LINE_RE.search(line)
                        if push_m:
                            stream_ok = True
                            save_last_stream_key(account_dir, push_m.group(1))
                        if NO_LIVE_MARKER in line:
                            no_live_seen = True
                        if 'YOUTUBE_SESSION_OK' in line:
                            session_ok = True
                        if 'Chrome запущен' in line:
                            chrome_started = True
                        if 'YouTube открыт' in line:
                            youtube_open_seen = True
                        low = line.lower()
                        if (
                            'прокси непригоден' in low
                            or 'прокси мёртв' in low
                            or 'прокси мертв' in low
                            or 'chrome не открываю' in low
                            or ('прокси не готов:' in low and 'ещё не готов' not in low)
                        ):
                            proxy_dead_detail = line.strip()
                            if 'во время автоматизации' in low:
                                mid_proxy_seen = True
                        if status_callback and buyer_core.is_yt_cookies_log_useful(line):
                            if STUDIO_OPEN_ONLY_MARKER not in line:
                                status_callback(line)
                    except Exception:
                        if 'Chrome запущен' in line:
                            chrome_started = True
                    if open_only and STUDIO_OPEN_ONLY_MARKER in line:
                        studio_open_only_done = True
                        break
        if studio_open_only_done:
            def _drain_open_only_stdout():
                try:
                    with open(run_log_path, 'a', encoding='utf-8', errors='replace', buffering=1) as drain_log:
                        for rest in proc.stdout:
                            rest = rest.rstrip('\n')
                            if rest:
                                _note_account_line()
                                drain_log.write(rest + '\n')
                                if STREAM_KEY_MARKER in rest:
                                    parts = rest.split(STREAM_KEY_MARKER, 1)[-1]
                                    save_last_stream_key(
                                        account_dir, parts.replace(':', '', 1).strip()
                                    )
                                push_m = PUSH_LINE_RE.search(rest)
                                if push_m:
                                    save_last_stream_key(account_dir, push_m.group(1))
                                if AUTOMATION_ATTACH_MARKER in rest:
                                    attach_event.set()
                                if status_callback and buyer_core.is_yt_cookies_log_useful(rest):
                                    if STUDIO_OPEN_ONLY_MARKER not in rest:
                                        status_callback(rest)
                except Exception:
                    pass
                finally:
                    _forget_idle_browser(account_dir, proc)
                    unregister_child_pid(proc.pid)
                    # Строки «Остановлено» / ACCOUNT_BROWSER_CLOSED уже ушли в лог из stdout.
                    # Повторно их не шлём — иначе GUI второй раз жмёт Стоп.

            threading.Thread(target=_drain_open_only_stdout, daemon=True).start()
            _current_proc = None
            _last_chrome_started = True
            _last_youtube_open = True
            _last_proxy_dead = False
            _last_proxy_mid = False
            return 0
        idle_stop.set()
        _forget_idle_browser(account_dir, proc)
        proc.wait()
        unregister_child_pid(proc.pid)
        _current_proc = None
        if stream_key:
            save_last_stream_key(account_dir, stream_key)
        _last_chrome_started = chrome_started
        _last_youtube_open = youtube_open_seen
        code = proc.returncode if proc.returncode is not None else 0
        _last_proxy_dead = bool(proxy_dead_detail) and code != 0
        _last_proxy_mid = bool(mid_proxy_seen) and _last_proxy_dead
        if _last_proxy_dead:
            wrote = log_dead_proxy(account_dir, proxy_dead_detail)
            if wrote and status_callback:
                status_callback(f'Мёртвый прокси записан в {DEAD_PROXIES_LOG.name}')
        expects_stream_result = (
            '--studio-live' in cmd
            and '--studio-open-only' not in cmd
            and '--create-streams' not in cmd
        )
        if code == 0 and expects_stream_result and not stream_ok and not no_live_seen:
            if status_callback:
                status_callback(
                    'YT-COOKIES завершился без результата Studio — код 0 не считаю успехом'
                )
            code = 1
        if code == 0 and '--session-check' in cmd and not session_ok:
            code = 1
        # Текст stdout — диагностический, решение принимает только exit code.
        # Иначе случайная/старая строка маркера уничтожала состояние аккаунта.
        if code == LOGGED_OUT_EXIT_CODE:
            return LOGGED_OUT_EXIT_CODE
        if stream_ok:
            return 0
        if no_live_seen:
            return NO_LIVE_EXIT_CODE
        if verify_seen and code != 0:
            return VERIFY_EXIT_CODE
        return code
    except Exception as e:
        try:
            idle_stop.set()
        except NameError:
            pass
        _current_proc = None
        _forget_idle_browser(account_dir)
        _last_chrome_started = False
        _last_youtube_open = False
        _last_proxy_dead = False
        _last_proxy_mid = False
        if status_callback:
            status_callback(f'Ошибка запуска YT-COOKIES: {e}')
        return 1


def open_account(
    account_dir: str | Path,
    bridge_url: str = '',
    force_audit: bool = True,
    status_callback=None,
    extra_args: str = '',
    proxy_retries: int = 2,
    use_bridge: bool = True,
    pick_new_proxy: bool = True,
    open_only: bool = False,
    keep_verify=None,
) -> bool:
    """Открывает аккаунт в YT-COOKIES.

    proxy_retries — сколько раз всего пробовать зайти с разным IP, включая исходный.
    pick_new_proxy=False — только текущий прокси, без подбора новых.
    use_bridge=False — Chrome напрямую через купленный IP, без LAN-моста.
    open_only=True — только зайти на YouTube и оставить браузер (без Studio).
    keep_verify=None — как раньше: оставить браузер на Verify, если новые IP не подбираем.
    keep_verify=False — закрыть Chrome и выйти (автономный проход).
    """
    with _open_lock:
        return _open_account_inner(
            account_dir, bridge_url, force_audit, status_callback, extra_args,
            proxy_retries, use_bridge, pick_new_proxy, open_only,
            keep_verify=keep_verify,
        )


def last_proxy_was_dead() -> bool:
    """Последний запуск youtube_browser отвалился на проверке прокси (Google/URLError)."""
    return bool(_last_proxy_dead)


def last_mid_proxy_failed() -> bool:
    """Прокси умер уже во время автоматизации, повторный IP тоже не вытянул сессию."""
    return bool(_last_proxy_mid)


def should_reset_profile_after_launch(
    code,
    extra_blob: str,
    *,
    chrome_started: bool,
    proxy_dead: bool,
) -> bool:
    """Сброс профиля — только если Chrome реально не поднялся, не из-за мёртвого прокси."""
    if proxy_dead or chrome_started:
        return False
    if code in (0, LOGGED_OUT_EXIT_CODE, BROWSER_CLOSED_EXIT_CODE):
        return False
    if '--reset-profile' in str(extra_blob or ''):
        return False
    return True


def should_replace_dead_proxy(
    proxy_dead: bool, replacements_used: int, *, mid_run: bool = False,
) -> bool:
    limit = MID_PROXY_REPLACEMENTS if mid_run else DEAD_PROXY_REPLACEMENTS
    return bool(proxy_dead) and replacements_used < limit


def _apply_picked_proxy(account_dir, new_proxy, chrome_use_bridge, bridge_url, control_port, is_local, yt_cookies_dir, status_callback):
    if chrome_use_bridge:
        _push_account_proxy(
            account_dir, bridge_url, control_port, is_local, yt_cookies_dir, status_callback,
        )
    return new_proxy


def _pick_other_proxy(account_dir, excluded, status_callback):
    new_proxy = set_proxy_auto(account_dir, status_callback=status_callback, exclude=excluded)
    if new_proxy and _proxy_in_excluded(new_proxy, excluded):
        if status_callback:
            status_callback('Cliproxy вернул то же прокси, исключаю и пробую ещё раз')
        excluded.extend(_proxy_exclude_tokens(new_proxy))
        new_proxy = set_proxy_auto(account_dir, status_callback=status_callback, exclude=excluded)
    if not new_proxy:
        if status_callback:
            status_callback('Не удалось подобрать другое прокси')
        return None
    if _proxy_in_excluded(new_proxy, excluded):
        if status_callback:
            status_callback('Cliproxy снова вернул то же прокси, пропускаю')
        excluded.extend(_proxy_exclude_tokens(new_proxy))
        return None
    excluded.extend(_proxy_exclude_tokens(new_proxy))
    return new_proxy


def _open_account_inner(
    account_dir, bridge_url, force_audit, status_callback, extra_args, proxy_retries,
    use_bridge=True, pick_new_proxy=True, open_only=False, keep_verify=None,
) -> bool:
    account_dir = Path(account_dir)
    if plain_profiles.is_plain_profile(account_dir):
        return _open_plain_account_inner(
            account_dir, status_callback, extra_args, open_only,
            use_bridge=use_bridge, bridge_url=bridge_url,
            keep_verify=keep_verify,
        )
    yt_cookies_dir = _resolve_yt_cookies_dir(account_dir)
    project_root = yt_cookies_dir.parent
    total_attempts = max(1, int(proxy_retries))
    if keep_verify is None:
        keep_verify = not pick_new_proxy
    keep_verify = bool(keep_verify)
    if not pick_new_proxy:
        total_attempts = 1

    work_id = current_work_gen()
    if is_stop_requested(work_id):
        if status_callback:
            status_callback('Остановлено')
        return False

    if not account_dir.is_dir():
        if status_callback:
            status_callback(f'Аккаунт не найден: {account_dir}')
        return False

    profile_dir = account_dir / 'browser_profile'
    if profile_dir.is_dir():
        if status_callback:
            status_callback(f'Профиль браузера уже существует ({profile_dir.name}), повторное скачивание не требуется')
    else:
        if status_callback:
            status_callback(f'Профиль браузера не найден, будет выполнено первичное скачивание для {account_dir.name}')

    existing = read_account_proxy(account_dir)
    ident = read_account_info(account_dir, fetch_isp=False)
    acc_ip = str(ident.get('ip') or '').strip()
    bound_ip = str((existing or {}).get('account_ip') or '').strip()
    bound_name = str((existing or {}).get('account_name') or '').strip()
    if is_cliproxy_proxy(existing) and bound_ip and acc_ip and not same_account_ip(bound_ip, acc_ip):
        if status_callback:
            status_callback(
                f'Прокси в .yt_proxy.json от другого IP ({bound_ip}'
                f'{f", {bound_name}" if bound_name else ""}), '
                f'у {account_dir.name} IP {acc_ip} — подбираю заново'
            )
        existing = None
    if has_account_proxy(existing):
        if status_callback and not is_cliproxy_proxy(existing):
            status_callback('Беру сохранённый прокси, Cliproxy не трогаю')
    else:
        if status_callback:
            status_callback('YouTube только через Cliproxy — подбираю прокси из кабинета...')
        existing = set_proxy_auto(account_dir, status_callback=status_callback)
        if not has_account_proxy(existing):
            if status_callback:
                status_callback('Cliproxy не дал прокси — аккаунт не открываю')
            return False

    stamp = save_last_opened(account_dir)
    if status_callback:
        status_callback(f'Последний запуск: {stamp}')

    bridge_url, chrome_use_bridge, control_port, is_local, proxy = _chrome_bridge_plan(
        account_dir,
        yt_cookies_dir,
        bridge_url=bridge_url,
        use_bridge=use_bridge,
        status_callback=status_callback,
    )

    excluded: list[str] = []
    excluded.extend(_proxy_exclude_tokens(proxy))

    random_fallback = _proxy_is_random_country(proxy)
    if random_fallback and pick_new_proxy:
        total_attempts = 1
        if status_callback:
            status_callback('Прокси с рандомной страны — Попыток IP не учитываю, вход один раз')

    is_watch = bool(extra_args and ('--warmup-hours' in extra_args or '--watch-hours' in extra_args))

    for attempt in range(1, total_attempts + 1):
        if is_stop_requested(work_id):
            if status_callback:
                status_callback('Остановлено')
            return False
        if attempt > 1:
            if not pick_new_proxy:
                break
            if status_callback:
                status_callback(
                    f'Verify that it\'s you — закрыл браузер, подбираю другой IP ({attempt}/{total_attempts})'
                )
            new_proxy = _pick_other_proxy(account_dir, excluded, status_callback)
            if not new_proxy:
                continue
            proxy = new_proxy
            if _proxy_is_random_country(new_proxy):
                random_fallback = True
                total_attempts = attempt
                if status_callback:
                    status_callback('Последняя стадия: рандомная страна, дальше IP не подбираю')
            if chrome_use_bridge:
                _push_account_proxy(
                    account_dir, bridge_url, control_port, is_local, yt_cookies_dir, status_callback,
                )
        elif status_callback:
            status_callback(f'Попытка входа {attempt}/{total_attempts}')

        code = _launch_yt_cookies(
            account_dir, yt_cookies_dir, project_root, bridge_url,
            force_audit, extra_args, status_callback, use_bridge=chrome_use_bridge,
            keep_verify=keep_verify,
            open_only=open_only,
        )
        extra_blob = extra_args if isinstance(extra_args, str) else ' '.join(
            str(x) for x in (extra_args or [])
        )
        replacements = 0
        while should_replace_dead_proxy(
            _last_proxy_dead, replacements, mid_run=_last_proxy_mid,
        ):
            if is_stop_requested(work_id):
                if status_callback:
                    status_callback('Остановлено')
                return False
            replacements += 1
            limit = MID_PROXY_REPLACEMENTS if _last_proxy_mid else DEAD_PROXY_REPLACEMENTS
            excluded.extend(_proxy_exclude_tokens(read_account_proxy(account_dir)))
            excluded.extend(dead_proxy_exclude_tokens())
            if status_callback:
                if _last_proxy_mid:
                    status_callback(
                        f'Прокси отвалился во время автоматизации — '
                        f'подбираю другой ({replacements}/{limit})'
                    )
                else:
                    status_callback(
                        f'Прокси не пускает Google — этот IP больше не проверяю, '
                        f'подбираю другой ({replacements}/{limit})'
                    )
            new_proxy = _pick_other_proxy(account_dir, excluded, status_callback)
            if not new_proxy:
                break
            proxy = _apply_picked_proxy(
                account_dir, new_proxy, chrome_use_bridge, bridge_url,
                control_port, is_local, yt_cookies_dir, status_callback,
            )
            if _proxy_is_random_country(new_proxy):
                random_fallback = True
                if status_callback:
                    status_callback('Последняя стадия: рандомная страна, дальше IP не подбираю')
            code = _launch_yt_cookies(
                account_dir, yt_cookies_dir, project_root, bridge_url,
                force_audit, extra_args, status_callback, use_bridge=chrome_use_bridge,
                keep_verify=keep_verify,
                open_only=open_only,
            )
            extra_blob = extra_args if isinstance(extra_args, str) else ' '.join(
                str(x) for x in (extra_args or [])
            )
            if random_fallback:
                break
        if should_reset_profile_after_launch(
            code, extra_blob,
            chrome_started=_last_chrome_started,
            proxy_dead=_last_proxy_dead,
        ):
            if status_callback:
                status_callback(
                    f'Chrome не запустился (код {code}) — сбрасываю browser_profile и пробую ещё раз'
                )
            retry_extra = []
            if extra_args:
                if isinstance(extra_args, (list, tuple)):
                    retry_extra = [str(x) for x in extra_args if str(x)]
                else:
                    retry_extra = shlex.split(str(extra_args), posix=False)
            retry_extra.append('--reset-profile')
            code = _launch_yt_cookies(
                account_dir, yt_cookies_dir, project_root, bridge_url,
                force_audit, retry_extra, status_callback, use_bridge=chrome_use_bridge,
                keep_verify=keep_verify,
                open_only=open_only,
            )
        if is_stop_requested(work_id):
            if status_callback:
                status_callback('Остановлено')
            return False
        is_create_streams = '--create-streams' in extra_blob
        is_session_check = '--session-check' in extra_blob
        if code == LOGGED_OUT_EXIT_CODE:
            keys = read_last_stream_keys() if is_create_streams else []
            return _finish_logged_out(
                account_dir, status_callback, delete=True, keys_saved=bool(keys),
            )
        if code == BROWSER_CLOSED_EXIT_CODE:
            if status_callback:
                status_callback('ACCOUNT_BROWSER_CLOSED')
            return False
        if open_only:
            if status_callback:
                if code == 0:
                    status_callback('YouTube открыт — браузер оставлен, «Автоматизация» продолжит здесь')
                elif code == 3:
                    status_callback('Chrome не подтвердил прокси — YouTube не открывал, метку не меняю')
                elif code == VERIFY_EXIT_CODE:
                    status_callback("Verify that it's you — браузер закрылся, метку не меняю")
                elif not _last_chrome_started:
                    status_callback(
                        f'Chrome не запустился (код {code}) — процесс упал до открытия окна, метку не меняю'
                    )
                elif _last_youtube_open:
                    status_callback(
                        f'YouTube открывался, но сеанс оборвался (код {code}) — метку не меняю'
                    )
                else:
                    status_callback(
                        f'YouTube не открылся (код {code}) — Chrome закрылся при переходе, метку не меняю'
                    )
            return code == 0
        if is_session_check:
            if code == 0:
                if status_callback:
                    status_callback('YouTube-сессия подтверждена, live-cookies сохранены')
                return True
            if status_callback:
                status_callback('YouTube-сессия не подтверждена')
            return False
        if is_create_streams:
            keys = read_last_stream_keys()
            if code == VERIFY_EXIT_CODE:
                save_account_label(account_dir, LABEL_VERIFY)
                if status_callback:
                    status_callback("Verify that it's you — метка «Verify»")
                return False
            if code == NO_LIVE_EXIT_CODE:
                return _finish_no_livestream(account_dir, status_callback, delete=True)
            if keys:
                save_account_label(account_dir, LABEL_TOP)
                if status_callback:
                    status_callback('Автоматизация: ключи собраны — метка «ТОП»')
                return True
            if status_callback:
                status_callback('Автоматизация не создала ключи, метку не меняю')
            return False
        if code == VERIFY_EXIT_CODE:
            save_account_label(account_dir, LABEL_VERIFY)
            if not pick_new_proxy:
                if status_callback:
                    status_callback("Verify that it's you — метка «Verify»")
                return False
            if random_fallback:
                if status_callback:
                    status_callback('Verify на рандомной стране — метка «Verify»')
                return False
            continue
        if code == NO_LIVE_EXIT_CODE:
            return _finish_no_livestream(account_dir, status_callback, delete=True)
        if is_watch:
            if code == 0:
                if status_callback:
                    status_callback('Просмотр видео завершён')
                return True
            save_account_label(account_dir, LABEL_DEAD)
            if status_callback:
                status_callback('Просмотр неуспешен — метка «Мертвый»')
            return False
        if code == 0:
            save_account_label(account_dir, LABEL_TOP)
            if status_callback:
                status_callback('Код трансляции скопирован — метка «ТОП»')
            return True
        save_account_label(account_dir, LABEL_NOT_IN)
        if status_callback:
            status_callback('Не удалось зайти в аккаунт — метка «НЕ ЗАШЕЛ»')
        return False

    save_account_label(account_dir, LABEL_VERIFY)
    if status_callback:
        status_callback(f'Исчерпаны попытки IP ({total_attempts}) — метка «Verify»')
    return False


def _open_plain_account_inner(
    account_dir, status_callback, extra_args, open_only=False,
    use_bridge=True, bridge_url='', keep_verify=None,
) -> bool:
    """Обычный Chrome-профиль youtube-daily-agent. Прокси — через LAN-мост, как у логов."""
    account_dir = Path(account_dir)
    work_id = current_work_gen()
    if is_stop_requested(work_id):
        if status_callback:
            status_callback('Остановлено')
        return False
    if not account_dir.is_dir():
        if status_callback:
            status_callback(f'Профиль не найден: {account_dir}')
        return False
    yt_cookies_dir = YT_COOKIES_DIR
    if not yt_cookies_dir.is_dir():
        yt_cookies_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
    project_root = Path(yt_cookies_dir).resolve().parent
    number = plain_profiles.profile_number_from_name(account_dir.name) or 0
    stamp = save_last_opened(account_dir)
    if status_callback:
        status_callback(f'Обычный YouTube-профиль #{number}: {account_dir.name}')
        status_callback(f'Последний запуск: {stamp}')
    bridge_url, chrome_use_bridge, _port, _local, proxy = _chrome_bridge_plan(
        account_dir,
        yt_cookies_dir,
        bridge_url=bridge_url,
        use_bridge=use_bridge,
        status_callback=status_callback,
    )
    if proxy and status_callback:
        status_callback(f'Прокси профиля: {proxy_display(proxy)}')
    elif status_callback:
        status_callback('Прокси не привязан — Chrome откроется с IP компьютера')
    if keep_verify is None:
        keep_verify = True
    code = _launch_yt_cookies(
        account_dir, yt_cookies_dir, project_root, bridge_url or '',
        False, extra_args, status_callback,
        use_bridge=chrome_use_bridge, keep_verify=bool(keep_verify), open_only=open_only,
        plain_profile=True,
    )
    if is_stop_requested(work_id):
        if status_callback:
            status_callback('Остановлено')
        return False
    extra_blob = extra_args if isinstance(extra_args, str) else ' '.join(
        str(x) for x in (extra_args or [])
    )
    is_create_streams = '--create-streams' in extra_blob
    is_watch = bool(extra_blob and ('--warmup-hours' in extra_blob or '--watch-hours' in extra_blob))
    if code == LOGGED_OUT_EXIT_CODE:
        keys = read_last_stream_keys() if is_create_streams else []
        return _finish_logged_out(
            account_dir, status_callback, delete=False, keys_saved=bool(keys),
        )
    if code == BROWSER_CLOSED_EXIT_CODE:
        if status_callback:
            status_callback('ACCOUNT_BROWSER_CLOSED')
        return False
    if open_only:
        if status_callback:
            if code == 0:
                status_callback('YouTube открыт — браузер оставлен, «Автоматизация» продолжит здесь')
            elif code == 3:
                status_callback('YouTube не открылся — смотрите строку выше, метку не меняю')
            elif code == VERIFY_EXIT_CODE:
                status_callback("Verify that it's you — браузер закрылся, метку не меняю")
            else:
                status_callback(
                    f'YouTube не открылся (код {code}) — Chrome закрылся при переходе, метку не меняю'
                )
        return code == 0
    if is_create_streams:
        keys = read_last_stream_keys()
        if code == VERIFY_EXIT_CODE:
            save_account_label(account_dir, LABEL_VERIFY)
            if status_callback:
                status_callback("Verify that it's you — метка «Verify»")
            return False
        if code == NO_LIVE_EXIT_CODE:
            return _finish_no_livestream(account_dir, status_callback, delete=False)
        if keys or code == 0:
            save_account_label(account_dir, LABEL_TOP)
            if status_callback:
                if keys:
                    status_callback('Автоматизация: ключи собраны — метка «ТОП»')
                else:
                    status_callback('Код трансляции скопирован — метка «ТОП»')
            return True
        if status_callback:
            status_callback('Автоматизация не создала ключи, метку не меняю')
        return False
    if code == VERIFY_EXIT_CODE:
        save_account_label(account_dir, LABEL_VERIFY)
        if status_callback:
            status_callback("Verify that it's you — метка «Verify»")
        return False
    if code == NO_LIVE_EXIT_CODE:
        return _finish_no_livestream(account_dir, status_callback, delete=False)
    if is_watch:
        if code == 0:
            if status_callback:
                status_callback('Просмотр видео завершён')
            return True
        if status_callback:
            status_callback('Просмотр неуспешен, метку не меняю')
        return False
    if code == 0:
        save_account_label(account_dir, LABEL_TOP)
        if status_callback:
            status_callback('Код трансляции скопирован — метка «ТОП»')
        return True
    save_account_label(account_dir, LABEL_NOT_IN)
    if status_callback:
        status_callback('Не удалось зайти в аккаунт — метка «НЕ ЗАШЕЛ»')
    return False


def warmup_account(
    account_dir: str | Path,
    hours: float = 1.0,
    bridge_url: str = '',
    status_callback=None,
    proxy_retries: int = 2,
    use_bridge: bool = True,
    pick_new_proxy: bool = True,
) -> bool:
    """Открывает аккаунт и смотрит одно длинное YouTube-видео заданное число часов."""
    hours = max(0.1, float(hours))
    if status_callback:
        status_callback(f'Просмотр видео {Path(account_dir).name}: {hours} ч')
    return open_account(
        account_dir,
        bridge_url=bridge_url,
        force_audit=True,
        status_callback=status_callback,
        extra_args=f'--warmup-hours {hours}',
        proxy_retries=proxy_retries,
        use_bridge=use_bridge,
        pick_new_proxy=pick_new_proxy,
    )


def write_create_streams_job(
    account_dir: str | Path,
    matches: list[dict],
    max_per_key: int = 3,
    nginx_conf: str = '',
    nginx_stop: str = '',
    nginx_start: str = '',
    status_callback=None,
) -> Path | None:
    """Пишет .yt_create_streams.json для входа в той же сессии, что и проверка Studio."""
    account_dir = Path(account_dir)
    job_path = account_dir / '.yt_create_streams.json'
    try:
        import match_sheet
        saved = {}
        settings_path = Path(__file__).resolve().parent / 'buyer_settings.json'
        try:
            if settings_path.is_file():
                loaded = json.loads(settings_path.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    saved = loaded
        except Exception:
            saved = {}
        matches = match_sheet.reroll_stream_titles(list(matches or []), saved)
    except Exception:
        matches = list(matches or [])
    payload = {
        'max_per_key': max(1, min(3, int(max_per_key or 3))),
        'nginx_conf': str(nginx_conf or r'C:\nginx\conf\nginx.conf').strip(),
        'nginx_stop': str(nginx_stop or r'C:\nginx\stop.bat').strip(),
        'nginx_start': str(nginx_start or r'C:\nginx\start_nginx.bat').strip(),
        'matches': [
            {
                'LIVE_TITLE': str(m.get('LIVE_TITLE') or m.get('title') or '').strip(),
                'STREAM_TITLE': str(m.get('STREAM_TITLE') or '').strip(),
                'MATCH_START': str(m.get('MATCH_START') or m.get('start') or '').strip(),
                'LIVE_DESC': str(m.get('LIVE_DESC') or m.get('description') or '').strip(),
                'CHAT_LINK': str(m.get('CHAT_LINK') or m.get('TG_LINK') or '').strip(),
                'LINK_URL': str(m.get('LINK_URL') or m.get('link_url') or '').strip(),
                'IMG': str(m.get('IMG') or '').strip(),
                'VIDEO': str(m.get('VIDEO') or '').strip(),
                'PHOTO': str(m.get('PHOTO') or '').strip(),
                'COVER_PATH': str(m.get('COVER_PATH') or '').strip(),
                'COVER_DEFAULT': bool(m.get('COVER_DEFAULT')),
                'DESC_FIRST': str(m.get('DESC_FIRST') or '').strip(),
                'match_start_dt': str(m.get('match_start_dt') or ''),
            }
            for m in (matches or [])
            if str(m.get('LIVE_TITLE') or m.get('title') or '').strip()
        ],
    }
    n = len(payload['matches'])
    if n == 0:
        if status_callback:
            status_callback('Нет матчей для автоматизации')
        return None
    groups = (n + payload['max_per_key'] - 1) // payload['max_per_key']
    try:
        _atomic_write_text(job_path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    except Exception as exc:
        if status_callback:
            status_callback(f'Не удалось записать задание: {exc}')
        return None
    if status_callback:
        status_callback(
            f'Автоматизация {account_dir.name}: {n} матчей, {groups} ключей '
            f'(по {payload["max_per_key"]} матча) → nginx → эфиры → «Начать эфир»'
        )
    return job_path


def create_account_streams(
    account_dir: str | Path,
    matches: list[dict],
    bridge_url: str = '',
    status_callback=None,
    use_bridge: bool = True,
    max_per_key: int = 3,
    nginx_conf: str = '',
    nginx_stop: str = '',
    nginx_start: str = '',
    keep_verify: bool = True,
    close_after: bool = False,
    force_fresh: bool = False,
) -> list[str]:
    """Создаёт трансляции по выбранным матчам и возвращает RTMP-ключи (в том числе частичные)."""
    global _last_stream_key, _last_stream_keys
    account_dir = Path(account_dir)
    attached = False if force_fresh else _can_attach_idle(account_dir)
    if attached:
        _last_stream_keys = []
        _last_stream_key = ''
        event = _idle_attach_event(account_dir)
        if event is not None:
            event.clear()
        _clear_attach_done(account_dir)
    job_path = write_create_streams_job(
        account_dir,
        matches,
        max_per_key=max_per_key,
        nginx_conf=nginx_conf,
        nginx_stop=nginx_stop,
        nginx_start=nginx_start,
        status_callback=status_callback,
    )
    if not job_path:
        return []

    def _launch_fresh():
        extra = ['--create-streams', str(job_path)]
        if close_after:
            extra.append('--close-after')
        open_account(
            account_dir,
            bridge_url=bridge_url,
            force_audit=True,
            status_callback=status_callback,
            extra_args=extra,
            proxy_retries=1,
            use_bridge=use_bridge,
            pick_new_proxy=False,
            open_only=False,
            keep_verify=keep_verify,
        )

    try:
        if attached:
            if status_callback:
                status_callback('Браузер уже открыт — запускаю автоматизацию в этом же окне')
            ok = wait_idle_automation(account_dir)
            if ok:
                pass
            elif is_stop_requested():
                if status_callback:
                    status_callback('Автоматизация в открытом окне не завершилась')
            else:
                if status_callback:
                    status_callback('Окно закрыто — запускаю заново')
                attached = False
                _launch_fresh()
        else:
            _launch_fresh()
    finally:
        try:
            if job_path.is_file() and not idle_browser_alive(account_dir):
                job_path.unlink()
        except Exception:
            pass
    keys = read_last_stream_keys()
    if status_callback:
        if keys:
            status_callback('Ключи RTMP:')
            for key in keys:
                status_callback(format_rtmp_push(key))
        else:
            status_callback('Ключи не получены')
    return keys


def set_proxy_manual(account_dir: str | Path, proxy_string: str, status_callback=None) -> bool:
    """Сохраняет прокси host:port:login:pass в .yt_proxy.json."""
    raw = str(proxy_string or '').strip()
    if not raw:
        if status_callback:
            status_callback('Пустая строка прокси')
        return False
    try:
        proxy = parse_proxy_string_to_dict(raw)
    except ValueError as e:
        if status_callback:
            status_callback(str(e))
        return False
    tg = _telegram_proxy_raw()
    if tg and str(proxy.get('raw') or '') == tg:
        if status_callback:
            status_callback('Это прокси Telegram — для YouTube не подходит')
        return False
    ident = read_account_info(account_dir, fetch_isp=False)
    proxy['account_ip'] = str(ident.get('ip') or '').strip()
    proxy['account_name'] = str(ident.get('name') or Path(account_dir).name)
    if save_account_proxy(account_dir, proxy):
        if status_callback:
            host_port = ':'.join(raw.split(':')[:2])
            status_callback(f'Прокси сохранён: {host_port}')
        if plain_profiles.is_plain_profile(account_dir):
            bind_saved_proxy_to_bridge(account_dir, status_callback=status_callback)
        return True
    if status_callback:
        status_callback('Не удалось записать .yt_proxy.json')
    return False


def read_buyer_settings() -> dict:
    """buyer_settings.json рядом с модулем (или в cwd). Пусто, если нет/битый."""
    here = Path(__file__).resolve().parent / 'buyer_settings.json'
    for path in (here, Path('buyer_settings.json')):
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding='utf-8'))
                return data if isinstance(data, dict) else {}
        except Exception:
            continue
    return {}


def proxy_pick_method(settings: dict | None = None) -> str:
    """'site' — кабинет dash.cliproxy.com через браузер; 'app' — приложение CliProxy.exe."""
    if settings is None:
        settings = read_buyer_settings()
    return cliproxy_app.normalize_method(settings.get(cliproxy_app.SETTINGS_KEYS['method']))


def _local_proxy_dict(proxy_str: str, proto: str = 'http') -> dict:
    """host:port[:user:pass] → .yt_proxy.json. Локальные порты CliProxy.exe идут без логина."""
    parts = proxy_str.strip().split(':')
    if len(parts) >= 4:
        data = parse_proxy_string_to_dict(proxy_str)
        if proto and proto != 'http':
            data['server'] = f"{proto}://{parts[0]}:{parts[1]}"
        return data
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError(f'Invalid proxy string: {proxy_str}')
    scheme = proto if proto in ('http', 'socks5') else 'http'
    return {
        'raw': f'{parts[0]}:{parts[1]}',
        'server': f'{scheme}://{parts[0]}:{parts[1]}',
        'username': '',
        'password': '',
        'public_ip': '',
        'source': 'cliproxy_app',
    }


def _set_proxy_auto_via_app(
    account_dir, info, ip, country, exclude_list, fresh, settings, status_callback,
) -> dict | None:
    """Тот же подбор, но через раздел Socks5 Proxy в CliProxy.exe (без браузера)."""
    if status_callback:
        status_callback(
            f'Подбор прокси через приложение CliProxy для {info["name"]} (IP: {ip}, {country or "any"})...'
        )
        if exclude_list:
            status_callback(f'Не беру предыдущие IP этого аккаунта: {", ".join(exclude_list)}')
    try:
        result, err = cliproxy_app.get_proxy_for_ip(
            ip or '', country or '', exclude=exclude_list, fresh=fresh,
            settings=settings, log=status_callback,
        )
    except Exception as e:
        result, err = None, f'{type(e).__name__}: {e}'
    if err or not result:
        if status_callback:
            status_callback(f'CliProxy app: {err or "прокси не получен"}')
        return None
    try:
        proxy = _local_proxy_dict(result['proxy'], 'socks5')
    except Exception as e:
        if status_callback:
            status_callback(f'Неверный формат прокси от приложения CliProxy: {e}')
        return None
    proxy['source'] = 'cliproxy_app'
    proxy['account_ip'] = ip
    proxy['account_name'] = info['name']
    if result.get('export_ip'):
        proxy['public_ip'] = result['export_ip']
    if result.get('random_country'):
        proxy['random_country'] = True
        if status_callback:
            status_callback('Рандомная страна — этот прокси только на одну попытку')
    if not save_account_proxy(account_dir, proxy):
        if status_callback:
            status_callback('Не удалось сохранить прокси')
        return None
    if status_callback:
        status_callback(
            f'Прокси сохранён для {info["name"]} (IP аккаунта {ip}) → {proxy_log_display(proxy)} '
            f'(exit {proxy.get("public_ip") or "?"}, через CliProxy.exe)'
        )
    ok, detail = wait_proxy_ready(
        proxy, status_callback=status_callback, tries=3, pause=2.0, settle=0, timeout=8.0,
    )
    if not ok and status_callback:
        status_callback(f'Локальный порт CliProxy пока не отвечает ({detail}) — оставил сохранённым')
    return proxy


def set_proxy_auto(
    account_dir: str | Path,
    headless: bool = False,
    status_callback=None,
    exclude=None,
    fresh: bool = True,
    settings_override: dict | None = None,
) -> dict | None:
    """Подбирает прокси через Cliproxy по IP аккаунта и сохраняет в .yt_proxy.json.
    fresh=True — не переиспользовать уже онлайн matching, искать новый IP в пуле."""
    del headless
    info = read_account_info(account_dir)
    ip = info.get('ip')
    country = info.get('country')
    if not ip and not country:
        if status_callback:
            status_callback('Не удалось определить IP/страну аккаунта')
        return None

    exclude_list = [str(x).strip() for x in (exclude or []) if str(x).strip()]
    exclude_list.extend(_proxy_exclude_tokens(read_account_proxy(account_dir)))
    exclude_list.extend(dead_proxy_exclude_tokens())
    seen = set()
    unique_exclude = []
    for token in exclude_list:
        key = token.lower()
        if not token or key in seen:
            continue
        seen.add(key)
        unique_exclude.append(token)
    exclude_list = unique_exclude

    settings = settings_override if settings_override is not None else read_buyer_settings()
    if proxy_pick_method(settings) == cliproxy_app.METHOD_APP:
        return _set_proxy_auto_via_app(
            account_dir, info, ip, country, exclude_list, fresh, settings, status_callback,
        )

    python = buyer_core.find_python_for_playwright()
    if not python:
        if status_callback:
            status_callback('Не найден Python с Playwright/Patchright для Cliproxy')
        return None

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'get_cliproxy_proxy.py')
    cmd = [python, script, '--ip', ip or '', '--country', country or '']
    if exclude_list:
        cmd += ['--exclude', ','.join(exclude_list)]
        if status_callback:
            status_callback(f'Не беру предыдущие IP этого аккаунта: {", ".join(exclude_list)}')
    if fresh:
        cmd += ['--fresh']
        if status_callback:
            status_callback('Ищу новый IP в пуле, этот аккаунт matching online не беру')
    if status_callback:
        status_callback(f'Подбор прокси для {info["name"]} (IP: {ip}, {country or "any"})...')

    try:
        proxy_str, random_country, stderr = buyer_core.run_cliproxy_with_relogin(cmd, status_callback)
    except Exception as e:
        if status_callback:
            status_callback(f'Cliproxy: {e}')
        return None

    host_port = ':'.join(proxy_str.split(':')[:2])
    if status_callback:
        status_callback(f'Найден прокси: {host_port}')

    try:
        proxy = parse_proxy_string_to_dict(proxy_str)
    except Exception as e:
        if status_callback:
            status_callback(f'Неверный формат прокси от Cliproxy: {e}')
        return None

    proxy['source'] = 'cliproxy'
    proxy['account_ip'] = ip
    proxy['account_name'] = info['name']
    export_ip = ''
    blob = stderr or ''
    export_ip = export_ip_from_cliproxy_text(blob)
    if not export_ip:
        for line in blob.splitlines():
            if 'export IP' in line:
                export_ip = line.rsplit('export IP', 1)[-1].strip(' )')
                break
            if 'Connecting to ' in line:
                maybe = line.split('Connecting to ', 1)[-1].split(' ', 1)[0].strip()
                if maybe:
                    export_ip = export_ip or maybe
    if export_ip:
        proxy['public_ip'] = export_ip
    if random_country or any('RANDOM_COUNTRY_PROXY' in line for line in (stderr or '').splitlines()):
        proxy['random_country'] = True
        if status_callback:
            status_callback('Рандомная страна — этот прокси только на одну попытку')

    if save_account_proxy(account_dir, proxy):
        if status_callback:
            status_callback(
                f'Прокси сохранён для {info["name"]} (IP аккаунта {ip}) → {host_port}'
            )
        ok, detail = wait_proxy_ready(
            proxy,
            status_callback=status_callback,
            tries=3,
            pause=2.0,
            settle=0,
            timeout=8.0,
        )
        if not ok and status_callback:
            if proxy_diag.is_exit_refused_detail(detail):
                status_callback(
                    'Прокси мёртв на стороне Cliproxy (сервер принял логин и сам закрыл туннель). '
                    'Оставил сохранённым как есть; при следующем запуске/автономном проходе он будет заменён'
                )
            else:
                status_callback(
                    f'Прокси пока не отвечает ({detail}) — оставил сохранённым, проверю ещё раз позже'
                )
        return proxy
    if status_callback:
        status_callback('Не удалось сохранить прокси')
    return None


_plain_chrome_relays: dict[str, object] = {}


def _plain_chrome_proxy_args(profile: Path, status_callback=None, use_bridge=True) -> list[str]:
    """LAN-мост как у логов; если моста нет — локальный relay для логина в Chrome."""
    proxy = read_account_proxy(profile)
    if not proxy:
        return []
    server = str(proxy.get('server') or '').strip()
    if not server:
        return []
    if '://' not in server:
        server = f'http://{server}'
    yt_cookies_dir = YT_COOKIES_DIR
    if not yt_cookies_dir.is_dir():
        yt_cookies_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
    bridge_url, chrome_use_bridge, _port, _local, proxy = _chrome_bridge_plan(
        profile,
        yt_cookies_dir,
        use_bridge=use_bridge,
        status_callback=status_callback,
    )
    if chrome_use_bridge and bridge_url and proxy:
        yt_dir_s = str(yt_cookies_dir)
        if yt_dir_s not in sys.path:
            sys.path.insert(0, yt_dir_s)
        from chromium_proxy import prepare_chromium_proxy
        session = prepare_chromium_proxy(
            {
                'server': str(proxy.get('server') or server),
                'username': str(proxy.get('username') or ''),
                'password': str(proxy.get('password') or ''),
            },
            lan_bridge=bridge_url,
            allow_bridge=True,
        )
        if status_callback:
            status_callback(f'Chrome через {session.label or bridge_url}')
        return list(session.extra_launch_args or [])
    key = str(profile.resolve())
    relay = _plain_chrome_relays.get(key)
    if relay is None:
        yt_dir_s = str(yt_cookies_dir)
        if yt_dir_s not in sys.path:
            sys.path.insert(0, yt_dir_s)
        from proxy_relay import start_local_relay
        relay = start_local_relay(
            {
                'server': server,
                'username': str(proxy.get('username') or ''),
                'password': str(proxy.get('password') or ''),
            }
        )
        _plain_chrome_relays[key] = relay
    if status_callback:
        status_callback(f'Chrome через прокси {proxy_display(proxy)}')
    return [
        f'--proxy-server={relay.proxy_server_arg}',
        '--proxy-bypass-list=<-loopback>',
    ]


def rebuild_account_browser(account_dir: str | Path, status_callback=None) -> bool:
    """Сбрасывает Chrome-профиль, Browser ID и закреплённую версию CFT. Cookies/прокси не трогает."""
    account_dir = Path(account_dir)
    if not account_dir.is_dir():
        if status_callback:
            status_callback(f'Аккаунт не найден: {account_dir}')
        return False
    if plain_profiles.is_plain_profile(account_dir):
        if status_callback:
            status_callback(
                'Обычный профиль daily-агента не пересобираю — это и есть папка входа в Google'
            )
        return False
    if status_callback:
        status_callback(f'Пересобираю профиль {account_dir.name}: Chrome, Browser ID, fingerprint')
    close_idle_browser(account_dir, status_callback=status_callback)
    profile_dir = account_dir / 'browser_profile'
    _kill_chrome_for_profile(profile_dir)
    time.sleep(0.4)
    yt_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
    yt_dir_s = str(yt_dir)
    if yt_dir_s not in sys.path:
        sys.path.insert(0, yt_dir_s)
    old_ver = ''
    new_ver = ''
    try:
        from chrome_binary import reassign_daily_chrome

        old_ver, new_ver = reassign_daily_chrome(account_dir.name)
    except Exception as exc:
        if status_callback:
            status_callback(f'Версию Chrome не сменил ({exc.__class__.__name__}: {exc})')
    try:
        from browser_isolation import reset_browser_profile, write_fresh_browser_identity

        if profile_dir.exists():
            reset_browser_profile(profile_dir, keep_browser_id=False)
        identity = write_fresh_browser_identity(profile_dir, account_dir.name)
        (account_dir / '.yt_force_exit_geo').write_text('1\n', encoding='utf-8')
    except Exception as exc:
        if status_callback:
            status_callback(f'Не удалось сбросить browser_profile: {exc}')
        return False
    if status_callback:
        chrome_note = f'{old_ver or "—"} → {new_ver}' if new_ver else 'версия как будет при открытии'
        status_callback(
            f'Профиль пересобран: Chrome {chrome_note}, '
            f'Browser ID {identity.instance_id[:16]}… '
            f'При открытии timezone/locale/язык возьму с прокси, не из information.txt'
        )
    return True


def _ensure_plain_fingerprint(profile: Path, status_callback=None) -> bool:
    """Назначает профилю случайный полный отпечаток, если своего ещё нет."""
    yt_dir = YT_COOKIES_DIR
    if not yt_dir.is_dir():
        yt_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
    yt_dir_s = str(yt_dir)
    if yt_dir_s not in sys.path:
        sys.path.insert(0, yt_dir_s)
    from plain_fingerprint import assignment_label, ensure_assigned

    try:
        ensure_assigned(Path(profile))
    except Exception as exc:
        if status_callback:
            status_callback(f'Отпечаток не назначен: {exc}')
        return False
    if status_callback:
        status_callback(f'Отпечаток профиля: {assignment_label(profile)}')
    return True


def open_plain_profile_chrome(profile: str | Path, status_callback=None, use_bridge=True) -> int:
    """Вход в Google в профиле с тем же антидетектом, что у логов."""
    profile = Path(profile)
    if not _ensure_plain_fingerprint(profile, status_callback):
        return 3
    yt_cookies_dir = YT_COOKIES_DIR
    if not yt_cookies_dir.is_dir():
        yt_cookies_dir = Path(__file__).resolve().parent / 'YT-COOKIES'
    project_root = Path(yt_cookies_dir).resolve().parent
    bridge_url, chrome_use_bridge, _port, _local, proxy = _chrome_bridge_plan(
        profile,
        yt_cookies_dir,
        use_bridge=use_bridge,
        status_callback=status_callback,
    )
    if proxy and status_callback:
        status_callback(f'Прокси профиля: {proxy_display(proxy)}')
    elif status_callback:
        status_callback('Прокси не привязан — Chrome откроется с IP компьютера')
    if status_callback:
        status_callback('Открываю антидетект Chrome — войдите в Google в этом окне')
    code = _launch_yt_cookies(
        profile, yt_cookies_dir, project_root, bridge_url or '',
        False, None, status_callback,
        use_bridge=chrome_use_bridge, keep_verify=True, open_only=False,
        plain_profile=True, login_only=True,
    )
    save_last_opened(profile)
    return int(code)


def create_plain_profile(
    yda_root: str | Path | None = None,
    status_callback=None,
    *,
    open_chrome: bool = True,
) -> tuple[int, Path]:
    """Создаёт следующий profiles_youtube_plain_N в папке vk_bot daily-агента."""
    number, profile = plain_profiles.create_profile(yda_root)
    if status_callback:
        status_callback(f'Создан общий профиль YouTube #{number}: {profile}')
    _ensure_plain_fingerprint(profile, status_callback)
    if open_chrome:
        try:
            open_plain_profile_chrome(profile, status_callback=status_callback)
        except Exception as exc:
            if status_callback:
                status_callback(f'Папка создана, но Chrome не открылся: {exc}')
            save_last_opened(profile)
    else:
        save_last_opened(profile)
    return number, profile


def delete_account(
    account_dir: str | Path,
    status_callback=None,
    yda_root: str | Path | None = None,
) -> bool:
    """Удаляет лог из _zip_cache или общий Chrome-профиль daily-агента."""
    account_dir = Path(account_dir)
    if not account_dir.is_dir():
        if status_callback:
            status_callback(f'Аккаунт не найден: {account_dir}')
        return False
    if plain_profiles.is_plain_profile(account_dir):
        number = plain_profiles.profile_number_from_name(account_dir.name)
        if number is None:
            if status_callback:
                status_callback(f'Не понял номер профиля: {account_dir.name}')
            return False
        relay = _plain_chrome_relays.pop(str(account_dir.resolve()), None)
        if relay is not None:
            try:
                relay.close()
            except Exception:
                pass
        try:
            deleted = plain_profiles.delete_profile(number, yda_root)
        except Exception as e:
            if status_callback:
                status_callback(f'Профиль не удалён: {e}')
            return False
        if status_callback:
            status_callback(f'Удалён общий профиль #{number}: {deleted}')
        return True
    resolved = account_dir.resolve()
    if resolved.parent.name != '_zip_cache':
        if status_callback:
            status_callback(
                f'Отказ удалять {resolved.name}: удаляю только папку аккаунта в _zip_cache'
            )
        return False
    try:
        shutil.rmtree(resolved)
        if status_callback:
            status_callback(f'Аккаунт удалён: {resolved.name}')
        return True
    except Exception as e:
        if status_callback:
            status_callback(f'Ошибка удаления: {e}')
        return False
