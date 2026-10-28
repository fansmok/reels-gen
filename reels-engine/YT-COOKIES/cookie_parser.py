"""Парсер Netscape / JSON cookies из лога (все дампы Google/YouTube)."""

from __future__ import annotations

import json
import time
from pathlib import Path

_HTTP_ONLY_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "LSID",
    "OSID",
    "ACCOUNT_CHOOSER",
    "LOGIN_INFO",
    "NID",
    "__Host-GAPS",
}

# YouTube считает SAPISIDHASH из document.cookie. HttpOnly → сайдбар «Login», шапка с каналом.
_JS_READABLE_AUTH = {
    "APISID",
    "SAPISID",
}

_MIRROR_TO_YOUTUBE = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
}

_YOUTUBE_WIDEN_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "studio.youtube.com",
}

_AUTH_NAMES = {
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LSID",
    "OSID",
    "LOGIN_INFO",
    "ACCOUNT_CHOOSER",
}

_SESSION_SCORE_NAMES = (
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LSID",
    "LOGIN_INFO",
    "ACCOUNT_CHOOSER",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Host-GAPS",
    "__Host-1PLSID",
    "__Host-3PLSID",
)

_HTTPONLY_PREFIXES = ("#httponly_",)
_STALE_EXTEND_SEC = 400 * 86400
# Playwright: expires < 0 только -1; верхняя граница ~ год 9999.
_MAX_EXPIRES = 253402300799


def is_auth_domain(domain: str) -> bool:
    """Любой хост Google/YouTube: country-TLD, mail/drive, blogger, gstatic…"""
    host = domain.lstrip(".").lower().rstrip(".")
    if not host:
        return False
    labels = host.split(".")
    if "google" in labels or "youtube" in labels or "youtube-nocookie" in labels:
        return True
    if labels and labels[0].startswith("google"):
        return True
    if host == "youtu.be" or host.endswith(".youtu.be"):
        return True
    if host == "blogger.com" or host.endswith(".blogger.com"):
        return True
    if host in {"ytimg.com", "ggpht.com", "gstatic.com", "googlevideo.com"}:
        return True
    if host.endswith((".ytimg.com", ".ggpht.com", ".gstatic.com", ".googlevideo.com")):
        return True
    return False


def _is_js_readable_auth(name: str) -> bool:
    n = str(name or "").strip()
    if n in _JS_READABLE_AUTH:
        return True
    return "PAPISID" in n


def _is_http_only(name: str, prefixed: bool = False) -> bool:
    if _is_js_readable_auth(name):
        return False
    if prefixed or name.startswith("__Host-"):
        return True
    if name.startswith("__Secure-") and any(
        token in name for token in ("PSIDTS", "PSIDCC", "PSID", "OSID")
    ):
        return True
    return name in _HTTP_ONLY_NAMES


def _is_youtube_cookie_host(domain: str) -> bool:
    host = str(domain or "").lstrip(".").lower()
    return host == "youtube.com" or host.endswith(".youtube.com")


def _is_google_cookie_host(domain: str) -> bool:
    host = str(domain or "").lstrip(".").lower()
    if not host:
        return False
    labels = host.split(".")
    return "google" in labels or (labels and labels[0].startswith("google"))


def _should_mirror_to_youtube(name: str) -> bool:
    n = str(name or "")
    if n in _MIRROR_TO_YOUTUBE:
        return True
    if n.startswith("__Secure-") and ("PSID" in n or "PAPISID" in n):
        return True
    return False


def _google_source_rank(domain: str) -> int:
    raw = str(domain or "").lower()
    host = raw.lstrip(".")
    if host == "google.com":
        return 0 if raw.startswith(".") else 1
    if host.startswith("www.google."):
        return 2
    if host.startswith("google."):
        return 3
    return 8


def widen_cookie_domain(name: str, domain: str) -> str:
    """Host-only www.youtube.com не уходит на studio.youtube.com — расширяем до .youtube.com."""
    d = str(domain or "").strip()
    n = str(name or "")
    if not d or n.startswith("__Host-"):
        return d
    host = d.lstrip(".").lower()
    if host in _YOUTUBE_WIDEN_HOSTS and (
        n in _AUTH_NAMES or n == "PREF" or _should_mirror_to_youtube(n)
    ):
        return ".youtube.com"
    if host in {"google.com", "www.google.com"} and (
        n in _AUTH_NAMES or _should_mirror_to_youtube(n)
    ):
        return ".google.com"
    return d


def ensure_youtube_auth_mirrors(cookies: list[dict]) -> list[dict]:
    """Domain=.google.com на youtube.com не отправляется. Недостающие auth копируем на .youtube.com."""
    have_yt: set[str] = set()
    google_src: dict[str, dict] = {}
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        if not _should_mirror_to_youtube(name):
            continue
        domain = str(cookie.get("domain") or "")
        if _is_youtube_cookie_host(domain):
            have_yt.add(name)
            continue
        if not _is_google_cookie_host(domain):
            continue
        prev = google_src.get(name)
        if prev is None or _google_source_rank(domain) < _google_source_rank(
            str(prev.get("domain") or "")
        ):
            google_src[name] = cookie
    extra: list[dict] = []
    for name, src in google_src.items():
        if name in have_yt:
            continue
        clone = dict(src)
        clone["domain"] = ".youtube.com"
        extra.append(clone)
    return cookies + extra


def _pref_with_hl_en(value: str) -> str:
    parts: list[str] = []
    seen_hl = False
    for part in str(value or "").split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0]
        if key == "hl":
            if not seen_hl:
                parts.append("hl=en")
                seen_hl = True
            continue
        parts.append(part)
    if not seen_hl:
        parts.insert(0, "hl=en")
    return "&".join(parts)


def ensure_youtube_english_pref(cookies: list[dict]) -> list[dict]:
    """PREF hl=en — YouTube сразу на английском, без кликов по меню аккаунта."""
    found = False
    out: list[dict] = []
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        domain = str(cookie.get("domain") or "")
        if name == "PREF" and _is_youtube_cookie_host(domain):
            item = dict(cookie)
            item["value"] = _pref_with_hl_en(str(item.get("value") or ""))
            out.append(item)
            found = True
            continue
        out.append(cookie)
    if found:
        return out
    now = int(time.time()) + _STALE_EXTEND_SEC
    out.append(
        _cookie_dict(
            domain=".youtube.com",
            cookie_path="/",
            is_secure=True,
            expires=now,
            name="PREF",
            value="hl=en",
            http_only_prefixed=False,
        )
    )
    return out


def finalize_youtube_cookies(cookies: list[dict]) -> list[dict]:
    widened: list[dict] = []
    for cookie in cookies:
        item = dict(cookie)
        domain = str(item.get("domain") or "")
        if domain:
            item["domain"] = widen_cookie_domain(str(item.get("name") or ""), domain)
        widened.append(item)
    return ensure_youtube_english_pref(
        ensure_youtube_auth_mirrors(collapse_last_wins(widened))
    )


def _same_site_and_secure(name: str, is_secure: bool) -> tuple[str, bool]:
    """__Secure-/__Host- всегда None+Secure. SID как в дампе — иначе Chrome режет пачку."""
    if name.startswith("__Host-") or name.startswith("__Secure-"):
        return "None", True
    if name in _AUTH_NAMES or "SID" in name or "PSID" in name:
        if is_secure:
            return "None", True
        return "Lax", False
    return "Lax", is_secure


def _normalize_expires(raw: int, now: int) -> int:
    if raw <= 0:
        return -1
    # Firefox / некоторые дампы пишут миллисекунды.
    if raw > 10_000_000_000:
        raw //= 1000
    if raw > _MAX_EXPIRES:
        raw = now + _STALE_EXTEND_SEC
    if raw < now:
        return now + _STALE_EXTEND_SEC
    return raw


def _line_http_only_prefix(line: str) -> tuple[str, bool]:
    lower = line.lower()
    for prefix in _HTTPONLY_PREFIXES:
        if lower.startswith(prefix):
            return line[len(prefix) :], True
    return line, False


def _split_netscape_line(line: str) -> list[str] | None:
    parts = line.split("\t")
    if len(parts) >= 6:
        if len(parts) == 6:
            parts.append("")
        else:
            parts = parts[:6] + ["\t".join(parts[6:])]
        return parts
    return None


def _cookie_dict(
    *,
    domain: str,
    cookie_path: str,
    is_secure: bool,
    expires: int,
    name: str,
    value: str,
    http_only_prefixed: bool,
) -> dict:
    same_site, is_secure = _same_site_and_secure(name, is_secure)
    is_host_prefix = name.startswith("__Host-")
    cookie: dict = {
        "name": name,
        "value": value,
        "path": cookie_path or "/",
        "expires": expires,
        "httpOnly": _is_http_only(name, http_only_prefixed),
        "secure": is_secure or is_host_prefix,
        "sameSite": same_site,
    }
    if not is_host_prefix:
        cookie["domain"] = domain
    else:
        cookie["domain"] = domain.lstrip(".") or "accounts.google.com"
    return cookie


def parse_json_cookies(text: str, auth_only: bool = True) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("cookies") or data.get("Cookies") or []
    if not isinstance(data, list):
        return []
    now = int(time.time())
    cookies: list[dict] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("Name") or "")
        domain = str(raw.get("domain") or raw.get("Domain") or "")
        if not name:
            continue
        if auth_only and not is_auth_domain(domain):
            continue
        expiry = raw.get("expires") or raw.get("expirationDate") or raw.get("expiry") or -1
        try:
            expiry_i = int(float(expiry))
        except (TypeError, ValueError):
            expiry_i = -1
        cookies.append(
            _cookie_dict(
                domain=domain,
                cookie_path=str(raw.get("path") or raw.get("Path") or "/"),
                is_secure=bool(raw.get("secure") or raw.get("Secure")),
                expires=_normalize_expires(expiry_i, now),
                name=name,
                value=str(raw.get("value") or raw.get("Value") or ""),
                http_only_prefixed=bool(raw.get("httpOnly") or raw.get("HttpOnly")),
            )
        )
    return cookies


def parse_netscape_cookies(path: str | Path, auth_only: bool = True) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip("\ufeff").lstrip()
    if stripped[:1] in "[{":
        return parse_json_cookies(stripped, auth_only=auth_only)

    cookies: list[dict] = []
    now = int(time.time())
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line, http_only_prefixed = _line_http_only_prefix(line)
        if not http_only_prefixed and line.startswith("#"):
            continue

        parts = _split_netscape_line(line)
        if not parts:
            continue

        domain, _flag, cookie_path, secure, expiry, name, value = parts
        domain = domain.strip()
        name = name.strip()
        if not domain or not name:
            continue
        if auth_only and not is_auth_domain(domain):
            continue

        is_secure = secure.upper() == "TRUE"
        expires = int(expiry) if expiry.lstrip("-").isdigit() else -1
        expires = _normalize_expires(expires, now)
        cookies.append(
            _cookie_dict(
                domain=domain,
                cookie_path=cookie_path or "/",
                is_secure=is_secure,
                expires=expires,
                name=name,
                value=value,
                http_only_prefixed=http_only_prefixed,
            )
        )
    return cookies


def cookie_identity(cookie: dict) -> tuple[str, str, str]:
    return (
        str(cookie.get("name") or ""),
        str(cookie.get("domain") or "").lower(),
        str(cookie.get("path") or "/"),
    )


def collapse_last_wins(cookies: list[dict]) -> list[dict]:
    """В одном дампе повтор name+domain+path — берём последнюю (обычно свежее)."""
    seen: dict[tuple[str, str, str], dict] = {}
    order: list[tuple[str, str, str]] = []
    for cookie in cookies:
        key = cookie_identity(cookie)
        if key not in seen:
            order.append(key)
        seen[key] = cookie
    return [seen[key] for key in order]


def merge_cookie_lists(groups: list[list[dict]]) -> list[dict]:
    """Первая группа — основа сессии; остальные только заполняют пробелы."""
    seen: dict[tuple[str, str, str], dict] = {}
    order: list[tuple[str, str, str]] = []
    for cookies in groups:
        for cookie in collapse_last_wins(cookies):
            key = cookie_identity(cookie)
            if key in seen:
                continue
            seen[key] = cookie
            order.append(key)
    return [seen[key] for key in order]


def session_cookie_score(cookies: list[dict]) -> tuple[int, int]:
    """(число ключевых auth-cookie, max expiry SID/LOGIN_INFO)."""
    names = {c.get("name") for c in cookies}
    score = sum(1 for name in _SESSION_SCORE_NAMES if name in names)
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        if name.startswith("__Secure-") and "PSID" in name:
            score += 1
    best_exp = 0
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        if name in {"SID", "LOGIN_INFO", "__Secure-1PSID", "__Host-GAPS"}:
            exp = int(cookie.get("expires") or 0)
            if exp > best_exp:
                best_exp = exp
    return score, best_exp


# Значения этих cookie — секрет конкретного Google-аккаунта. Совпало хотя бы одно
# между дампами → это точно один и тот же аккаунт, куки можно объединять безопасно.
_IDENTITY_NAMES = (
    "SAPISID",
    "__Secure-3PAPISID",
    "__Secure-1PAPISID",
    "APISID",
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
)


def account_identity_values(cookies: list[dict]) -> set[str]:
    """Секретные значения auth-cookie, однозначно привязанные к Google-аккаунту."""
    values: set[str] = set()
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        if name in _IDENTITY_NAMES:
            value = str(cookie.get("value") or "").strip()
            if value:
                values.add(value)
    return values


def load_cookies_from_files(
    files: list[Path],
    *,
    auth_only: bool = True,
    same_account_only: bool = False,
) -> tuple[list[dict], list[tuple[Path, int]]]:
    """Первый файл — основа сессии (куки этого канала из YoutubeInfo).

    Остальные дампы только заполняют пробелы (rotating __Secure-*PSIDTS, LOGIN_INFO,
    __Host-GAPS и т.п.). При same_account_only соседний дамп берётся, только если у него
    совпадает секретное значение auth-cookie с основой — чтобы не подмешать чужой аккаунт
    из стилер-лога, где бывает несколько Google-профилей.
    """
    groups: list[list[dict]] = []
    stats: list[tuple[Path, int]] = []
    for path in files:
        parsed = parse_netscape_cookies(path, auth_only=auth_only)
        groups.append(parsed)
        stats.append((path, len(parsed)))
    if same_account_only and groups:
        base = groups[0]
        base_values = account_identity_values(base)
        if base_values:
            filtered = [base]
            for grp in groups[1:]:
                if account_identity_values(grp) & base_values:
                    filtered.append(grp)
            groups = filtered
        else:
            # У основы нет опознавательного cookie — не рискуем чужими дампами.
            groups = [base]
    return finalize_youtube_cookies(merge_cookie_lists(groups)), stats


def prepare_playwright_cookie(cookie: dict) -> dict | None:
    """url XOR (domain+path). Иначе Playwright отбрасывает всю пачку."""
    name = str(cookie.get("name") or "")
    if not name:
        return None
    domain = widen_cookie_domain(name, str(cookie.get("domain") or "").strip())
    path = str(cookie.get("path") or "/") or "/"
    expires = cookie.get("expires", -1)
    try:
        expires_i = int(expires)
    except (TypeError, ValueError):
        expires_i = -1
    if expires_i < 0 or expires_i > _MAX_EXPIRES:
        expires_i = -1

    http_only = bool(cookie.get("httpOnly", False))
    if _is_js_readable_auth(name):
        http_only = False

    item: dict = {
        "name": name,
        "value": cookie.get("value", ""),
        "expires": expires_i,
        "httpOnly": http_only,
        "secure": bool(cookie.get("secure", False)),
        "sameSite": cookie.get("sameSite") or "Lax",
    }
    if item["sameSite"] == "None":
        item["secure"] = True

    if name.startswith("__Host-"):
        host = domain.lstrip(".") or "accounts.google.com"
        item["url"] = f"https://{host}/"
        item["secure"] = True
        return item

    if not domain:
        return None

    if domain.startswith("."):
        item["domain"] = domain
        item["path"] = path
        return item

    host = domain.lstrip(".")
    if path in {"", "/"}:
        item["url"] = f"https://{host}/"
        return item

    item["domain"] = host
    item["path"] = path
    return item


def critical_cookie_flags(cookies: list[dict]) -> dict[str, bool]:
    names = {str(c.get("name") or "") for c in cookies}
    return {
        "SID": "SID" in names,
        "HSID": "HSID" in names,
        "SSID": "SSID" in names,
        "LOGIN_INFO": "LOGIN_INFO" in names,
        "SAPISID": "SAPISID" in names,
        "__Secure-3PAPISID": "__Secure-3PAPISID" in names,
        "__Secure-1PSID": "__Secure-1PSID" in names,
        "__Host-GAPS": "__Host-GAPS" in names,
        # accounts.google.com login-сессия: без 1PLSID/3PLSID Google чаще кидает на
        # accountchooser (наш триггер «разлогина»), даже если YouTube-куки живые.
        "__Host-1PLSID": "__Host-1PLSID" in names,
        "__Host-3PLSID": "__Host-3PLSID" in names,
        "LSID": "LSID" in names,
        "ACCOUNT_CHOOSER": "ACCOUNT_CHOOSER" in names,
    }
