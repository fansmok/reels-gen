"""
Источник нижних видео: папка 2 или Instagram (профиль / ссылки на Reels).
Обход: собираем прямые /reel/<code>/ с аккаунта, рандом, скачиваем через yt-dlp/CDN.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from http.cookiejar import MozillaCookieJar

from engine import FOLDER_2, VIDEO_EXTS, ensure_dirs, list_videos, pick_random_bottoms

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache" / "instagram"
ProgressCb = Callable[[str], None]

REEL_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_-]+)/?",
    re.I,
)

IG_APP_ID = "936619743392459"


@dataclass
class ReelCandidate:
    code: str
    page_url: str
    direct_url: str | None = None


def normalize_instagram_input(raw: str) -> tuple[str, str]:
    """Возвращает (username, profile_url)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Укажите Instagram-профиль или ссылку")

    text = text.split("?")[0].strip().rstrip("/")
    if text.startswith("@"):
        text = text[1:]

    username = ""
    if "instagram.com" in text.lower():
        if not text.startswith("http"):
            text = "https://" + text
        path = urlparse(text).path.strip("/")
        parts = [p for p in path.split("/") if p]
        skip = {"reels", "reel", "p", "tv", "stories", "explore", "tags"}
        for part in parts:
            if part.lower() in skip:
                continue
            if re.fullmatch(r"[A-Za-z0-9._]+", part):
                username = part
                break
        if not username:
            raise ValueError(f"Не удалось понять профиль из ссылки: {raw}")
    else:
        if not re.fullmatch(r"[A-Za-z0-9._]+", text):
            raise ValueError("Некорректный Instagram username")
        username = text

    url = f"https://www.instagram.com/{username}/"
    return username, url


def parse_reel_urls(text: str) -> list[str]:
    """Достаёт прямые ссылки на reel/p/tv из многострочного текста."""
    found = REEL_URL_RE.findall(text or "")
    urls: list[str] = []
    seen: set[str] = set()
    for code in found:
        full = f"https://www.instagram.com/reel/{code}/"
        if code not in seen:
            seen.add(code)
            urls.append(full)
    for m in re.finditer(
        r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_-]+/?",
        text or "",
        re.I,
    ):
        u = m.group(0)
        if not u.endswith("/"):
            u += "/"
        code = u.rstrip("/").split("/")[-1]
        if code not in seen:
            seen.add(code)
            urls.append(f"https://www.instagram.com/reel/{code}/")
    return urls


def _ydl_opts(
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
    extra: dict | None = None,
) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "retries": 3,
    }
    if cookies_file and cookies_file.exists():
        opts["cookiefile"] = str(cookies_file)
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if extra:
        opts.update(extra)
    return opts


def _make_session(cookies_file: Path | None, username: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-IG-App-ID": IG_APP_ID,
            "X-ASBD-ID": "359341",
            "X-IG-WWW-Claim": "0",
            "Origin": "https://www.instagram.com",
            "Referer": (
                f"https://www.instagram.com/{username}/reels/"
                if username
                else "https://www.instagram.com/"
            ),
        }
    )
    if cookies_file and cookies_file.exists():
        jar = MozillaCookieJar(str(cookies_file))
        jar.load(ignore_discard=True, ignore_expires=True)
        for c in jar:
            try:
                session.cookies.set(c.name, c.value, domain=c.domain, path=c.path or "/")
            except Exception:
                continue
    csrf = None
    for c in session.cookies:
        if c.name == "csrftoken":
            csrf = c.value
            break
    if csrf:
        session.headers["X-CSRFToken"] = csrf
    return session


def _best_video_url(media: dict) -> str | None:
    versions = media.get("video_versions") or []
    if not versions and isinstance(media.get("carousel_media"), list):
        for item in media["carousel_media"]:
            if item.get("video_versions"):
                versions = item["video_versions"]
                break
    if not versions:
        return None
    best = max(versions, key=lambda v: (v.get("width") or 0) * (v.get("height") or 0))
    url = best.get("url")
    return url if isinstance(url, str) and url.startswith("http") else None


def _code_from_media(media: dict) -> str | None:
    code = media.get("code") or media.get("shortcode")
    if isinstance(code, str) and code:
        return code
    return None


def _extract_candidates_from_clips_payload(data: dict) -> list[ReelCandidate]:
    out: list[ReelCandidate] = []
    seen: set[str] = set()

    def push(media: dict) -> None:
        if not isinstance(media, dict):
            return
        code = _code_from_media(media)
        if not code or code in seen:
            return
        # clips/user иногда отдаёт фото без video_versions — всё равно берём /reel/ ссылку
        seen.add(code)
        out.append(
            ReelCandidate(
                code=code,
                page_url=f"https://www.instagram.com/reel/{code}/",
                direct_url=_best_video_url(media),
            )
        )

    def walk(node: object, depth: int = 0) -> None:
        if depth > 8 or node is None:
            return
        if isinstance(node, dict):
            # типичные контейнеры media
            if any(k in node for k in ("video_versions", "code", "shortcode", "video_dash_manifest")):
                push(node)
            media = node.get("media")
            if isinstance(media, dict):
                push(media)
            clip = node.get("clip")
            if isinstance(clip, dict):
                if isinstance(clip.get("media"), dict):
                    push(clip["media"])
                else:
                    push(clip)
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node[:80]:
                walk(v, depth + 1)

    items = data.get("items")
    if isinstance(items, list) and items:
        for item in items:
            if isinstance(item, dict):
                media = item.get("media") if isinstance(item.get("media"), dict) else item
                push(media if isinstance(media, dict) else {})
    if not out:
        # пустой items или другая форма — обход всего JSON
        walk(data)
    return out


def _collect_via_ytdlp_flat(
    username: str,
    cookies_file: Path | None,
    *,
    limit: int,
    on_log: ProgressCb | None = None,
) -> list[ReelCandidate]:
    """Фолбэк: yt-dlp --flat-playlist по /reels/ профиля."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    try:
        import yt_dlp
    except ImportError:
        log("yt-dlp flat: пакет не установлен")
        return []

    url = f"https://www.instagram.com/{username}/reels/"
    opts = _ydl_opts(
        cookies_file=cookies_file,
        extra={
            "extract_flat": True,
            "skip_download": True,
            "playlistend": max(limit, 20),
        },
    )
    out: list[ReelCandidate] = []
    seen: set[str] = set()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        log(f"yt-dlp flat: {exc}")
        return []

    entries = []
    if isinstance(info, dict):
        entries = info.get("entries") or []
        if not entries and info.get("id"):
            entries = [info]
    for ent in entries or []:
        if not isinstance(ent, dict):
            continue
        code = (
            ent.get("id")
            or ent.get("display_id")
            or ent.get("shortcode")
            or ""
        )
        code = str(code).strip()
        webpage = str(ent.get("url") or ent.get("webpage_url") or "")
        m = re.search(r"/(?:reel|p|tv)/([A-Za-z0-9_-]+)", webpage)
        if m:
            code = m.group(1)
        if not code or code in seen or len(code) < 5:
            continue
        seen.add(code)
        out.append(
            ReelCandidate(
                code=code,
                page_url=f"https://www.instagram.com/reel/{code}/",
            )
        )
        if len(out) >= limit:
            break
    if out:
        log(f"yt-dlp flat: +{len(out)}")
    return out


def _resolve_user_id(
    session: requests.Session,
    username: str,
    on_log: ProgressCb | None = None,
) -> str | None:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    # 1) web search — самый стабильный JSON-эндпоинт
    try:
        r = session.get(
            "https://www.instagram.com/web/search/topsearch/",
            params={"query": username},
            timeout=30,
        )
        if r.status_code == 200:
            for u in r.json().get("users") or []:
                user = u.get("user") or u
                if (user.get("username") or "").lower() == username.lower():
                    uid = str(user.get("pk") or user.get("pk_id") or user.get("id") or "")
                    if uid and uid not in {"0", "1"}:
                        log(f"user_id из search: {uid}")
                        return uid
    except Exception as exc:  # noqa: BLE001
        log(f"search user_id: {exc}")

    # 2) HTML — только безопасные паттерны (не userID/fbid)
    try:
        html = session.get(f"https://www.instagram.com/{username}/", timeout=30).text
        for pat in (
            rf'"username":"{re.escape(username)}".{{0,200}}"id":"(\d+)"',
            rf'"id":"(\d+)".{{0,200}}"username":"{re.escape(username)}"',
            r"profilePage_(\d+)",
            r'"profile_id":"(\d+)"',
        ):
            m = re.search(pat, html, re.I | re.S)
            if m and m.group(1) not in {"0", "1"} and len(m.group(1)) >= 5:
                log(f"user_id из HTML: {m.group(1)}")
                return m.group(1)
    except Exception as exc:  # noqa: BLE001
        log(f"HTML user_id: {exc}")

    return None


def collect_reel_candidates(
    username: str,
    cookies_file: Path | None,
    *,
    limit: int = 40,
    on_log: ProgressCb | None = None,
) -> list[ReelCandidate]:
    """
    Обход: сначала Playwright (прямые /reel/ ссылки с страницы аккаунта),
    потом API-фолбэки.
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    collected: list[ReelCandidate] = []
    seen: set[str] = set()

    def add_many(items: list[ReelCandidate], source: str) -> None:
        added = 0
        for c in items:
            if c.code in seen:
                continue
            seen.add(c.code)
            collected.append(c)
            added += 1
            if len(collected) >= limit:
                break
        if added:
            log(f"{source}: +{added} (всего {len(collected)})")

    # --- Главный обход: headless браузер с cookies ---
    if cookies_file and cookies_file.exists():
        try:
            from ig_playwright import collect_reel_links_playwright

            links = collect_reel_links_playwright(
                username, cookies_file, limit=limit, on_log=on_log
            )
            add_many(
                [
                    ReelCandidate(
                        code=u.rstrip("/").split("/")[-1],
                        page_url=u,
                    )
                    for u in links
                ],
                "playwright",
            )
        except Exception as exc:  # noqa: BLE001
            log(f"Playwright обход: {exc}")

    if len(collected) >= max(3, min(limit, 8)):
        log(f"Итого прямых ссылок на рилсы: {len(collected)}")
        return collected[:limit]

    session = _make_session(cookies_file, username)
    user_id = _resolve_user_id(session, username, on_log=on_log)

    # clips/user POST
    if user_id:
        for attempt in range(2):
            try:
                resp = session.post(
                    "https://www.instagram.com/api/v1/clips/user/",
                    data={
                        "target_user_id": str(user_id),
                        "page_size": str(min(limit, 12)),
                        "include_feed_video": "true",
                    },
                    headers={
                        **session.headers,
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                    timeout=30,
                )
                log(f"clips/user: HTTP {resp.status_code}")
                if resp.status_code == 429:
                    time.sleep(6 * (attempt + 1))
                    continue
                if resp.status_code == 200 and resp.text.strip().startswith("{"):
                    payload = resp.json()
                    found = _extract_candidates_from_clips_payload(payload)
                    if not found:
                        keys = list(payload.keys())[:12] if isinstance(payload, dict) else []
                        n_items = len(payload.get("items") or []) if isinstance(payload, dict) else 0
                        log(f"clips/user: JSON ok, но 0 рилсов (keys={keys}, items={n_items})")
                    add_many(found, "clips/user")
                break
            except Exception as exc:  # noqa: BLE001
                log(f"clips/user: {exc}")
                break

    # web_profile_info
    if len(collected) < limit:
        try:
            resp = session.get(
                f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
                timeout=30,
                headers={**session.headers, "X-Requested-With": "XMLHttpRequest"},
            )
            log(f"web_profile_info: HTTP {resp.status_code}")
            if resp.status_code == 200 and resp.text.strip().startswith("{"):
                user = resp.json().get("data", {}).get("user", {})
                edges = (
                    user.get("edge_owner_to_timeline_media", {}).get("edges")
                    or user.get("edge_felix_video_timeline", {}).get("edges")
                    or []
                )
                tmp: list[ReelCandidate] = []
                for edge in edges:
                    node = (edge or {}).get("node") or {}
                    code = node.get("shortcode")
                    if code and node.get("is_video"):
                        tmp.append(
                            ReelCandidate(
                                code=code,
                                page_url=f"https://www.instagram.com/reel/{code}/",
                            )
                        )
                add_many(tmp, "web_profile_info")
        except Exception as exc:  # noqa: BLE001
            log(f"web_profile_info media: {exc}")

    # yt-dlp flat playlist — если API/Playwright почти ничего не дали
    if len(collected) < max(3, min(limit, 8)):
        add_many(
            _collect_via_ytdlp_flat(
                username, cookies_file, limit=limit, on_log=on_log
            ),
            "yt-dlp",
        )

    log(f"Итого прямых ссылок на рилсы: {len(collected)}")
    return collected[:limit]


def _download_direct_mp4(url: str, out_path: Path, session: requests.Session) -> Path | None:
    try:
        with session.get(url, stream=True, timeout=120) as resp:
            if resp.status_code != 200:
                return None
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        if out_path.exists() and out_path.stat().st_size > 10_000:
            return out_path
    except Exception:
        return None
    return None


def _download_one(
    url: str,
    out_dir: Path,
    *,
    cookies_from_browser: str | None,
    cookies_file: Path | None,
    on_log: ProgressCb | None,
) -> Path | None:
    import yt_dlp

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in out_dir.glob("*") if p.suffix.lower() in VIDEO_EXTS}
    opts = _ydl_opts(
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        extra={
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "format": "mp4/best",
            "noplaylist": True,
        },
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    after = [p for p in out_dir.glob("*") if p.suffix.lower() in VIDEO_EXTS]
    new_files = [p for p in after if p.name not in before]
    if new_files:
        return max(new_files, key=lambda p: p.stat().st_mtime)

    m = re.search(r"/(?:reel|p|tv)/([^/]+)", url)
    if m:
        vid = m.group(1)
        for ext in VIDEO_EXTS:
            cand = out_dir / f"{vid}{ext}"
            if cand.exists():
                return cand
    log(f"  не скачалось: {url}")
    return None


def fetch_from_reel_urls(
    urls: list[str],
    count: int,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
    on_log: ProgressCb | None = None,
    seed: int | None = None,
) -> list[Path]:
    if not urls:
        raise ValueError("Нет ссылок на Instagram Reels")
    rng = random.Random(seed)
    pool = urls[:]
    rng.shuffle(pool)
    chosen = pool[: max(count, 1)]
    ensure_dirs()
    out_dir = FOLDER_2
    downloaded: list[Path] = []
    for i, url in enumerate(chosen, 1):
        if on_log:
            on_log(f"Скачивание Reel [{i}/{len(chosen)}]: {url}")
        path = _download_one(
            url,
            out_dir,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            on_log=on_log,
        )
        if path:
            downloaded.append(path)
            if on_log:
                on_log(f"  OK → папка 2: {path.name}")
    if not downloaded:
        raise RuntimeError(
            "Не удалось скачать Reels.\n"
            "Проверьте cookies (закройте Opera и нажмите «Подтянуть cookies»)."
        )
    return downloaded[:count] if count else downloaded


def fetch_instagram_videos(
    profile: str,
    count: int,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
    on_log: ProgressCb | None = None,
    seed: int | None = None,
) -> list[Path]:
    """Собирает рандомные прямые ссылки на рилсы аккаунта и скачивает их."""
    if count < 1:
        raise ValueError("Количество рилсов должно быть >= 1")

    # Пользователь сам вставил прямые ссылки
    reel_urls = parse_reel_urls(profile)
    if reel_urls:
        if on_log:
            on_log(f"Найдено прямых ссылок на Reels: {len(reel_urls)}")
        return fetch_from_reel_urls(
            reel_urls,
            count,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            on_log=on_log,
            seed=seed,
        )

    username, url = normalize_instagram_input(profile)
    ensure_dirs()
    out_dir = FOLDER_2
    out_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    log(f"Instagram: @{username}")
    log("Обход: собираю прямые /reel/... с аккаунта, затем рандомное скачивание")
    log(f"Сохранение в папку 2: {out_dir}")

    cached = list_videos(out_dir)
    # Старый кэш (если был) — тоже учитываем как запас
    legacy = list_videos(CACHE_DIR / username) if (CACHE_DIR / username).exists() else []

    candidates = collect_reel_candidates(
        username,
        cookies_file,
        limit=max(40, count * 5),
        on_log=on_log,
    )

    if not candidates:
        pool = cached or legacy
        if pool:
            log(f"Ссылки не собрались — беру из папки 2 / кэша ({len(pool)})")
            rng = random.Random(seed)
            return rng.sample(pool, min(count, len(pool)))
        raise RuntimeError(
            "Не удалось собрать прямые ссылки на рилсы аккаунта.\n"
            "Частые причины: 429 (подождите), устаревшие cookies, закрытый профиль.\n"
            "Можно вставить прямые ссылки на Reels вручную."
        )

    rng = random.Random(seed)
    rng.shuffle(candidates)
    chosen = candidates[:count]
    log(f"Выбрано случайных рилсов: {len(chosen)} из {len(candidates)}")
    for c in chosen:
        log(f"  → {c.page_url}")

    session = _make_session(cookies_file, username)
    downloaded: list[Path] = []
    for i, cand in enumerate(chosen, 1):
        log(f"Скачивание [{i}/{len(chosen)}]: {cand.page_url}")
        path: Path | None = None

        # Уже есть в папке 2?
        existing = out_dir / f"{cand.code}.mp4"
        if existing.exists() and existing.stat().st_size > 10_000:
            path = existing
            log(f"  уже в папке 2: {path.name}")

        # 1) Прямой CDN, если API отдал video_versions
        if path is None and cand.direct_url:
            dest = out_dir / f"{cand.code}.mp4"
            path = _download_direct_mp4(cand.direct_url, dest, session)
            if path:
                log(f"  OK (CDN) → папка 2: {path.name}")

        # 2) yt-dlp по прямой ссылке на reel
        if path is None:
            path = _download_one(
                cand.page_url,
                out_dir,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                on_log=on_log,
            )
            if path:
                log(f"  OK (yt-dlp) → папка 2: {path.name}")

        if path:
            downloaded.append(path)

    if not downloaded:
        pool = cached or legacy
        if pool:
            log("Скачивание не удалось — беру из папки 2 / кэша")
            return rng.sample(pool, min(count, len(pool)))

    if not downloaded:
        raise RuntimeError(
            "Ссылки собрал, но скачать видео не удалось.\n"
            "Обновите cookies и повторите."
        )

    if len(downloaded) < count:
        log(f"Внимание: скачано {len(downloaded)} из {count}")
    return downloaded


def resolve_bottom_videos(
    mode: str,
    count: int,
    *,
    instagram: str | None = None,
    cookies_from_browser: str | None = None,
    cookies_file: str | Path | None = None,
    seed: int | None = None,
    on_log: ProgressCb | None = None,
) -> list[Path]:
    ensure_dirs()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cookie_path = Path(cookies_file) if cookies_file else None
    if cookie_path and not cookie_path.exists():
        raise FileNotFoundError(f"Файл cookies не найден: {cookie_path}")

    if mode == "folder":
        videos = pick_random_bottoms(count, seed=seed)
        if on_log:
            on_log(f"Источник низа: папка 2 ({len(list_videos(FOLDER_2))} файлов)")
        return videos

    if mode == "instagram":
        if not instagram:
            raise ValueError("Укажите Instagram-профиль, ссылку или список Reels")

        from cookies_util import resolve_cookie_settings

        browser, auto_file = resolve_cookie_settings(
            cookies_from_browser=cookies_from_browser
            if cookies_from_browser is not None
            else "auto",
            cookies_file=cookie_path,
            on_log=on_log,
            auto_pull=True,
        )
        cookie_final = auto_file or cookie_path

        # Несколько аккаунтов (по строкам) → рандомно берём с разных
        accounts = _parse_ig_accounts(instagram)
        if len(accounts) > 1:
            return fetch_from_many_accounts(
                accounts,
                count,
                cookies_from_browser=browser,
                cookies_file=cookie_final,
                on_log=on_log,
                seed=seed,
            )

        return fetch_instagram_videos(
            accounts[0] if accounts else instagram,
            count,
            cookies_from_browser=browser,
            cookies_file=cookie_final,
            on_log=on_log,
            seed=seed,
        )

    raise ValueError(f"Неизвестный режим источника: {mode}")


def _parse_ig_accounts(raw: str) -> list[str]:
    """Список IG-аккаунтов / блоков: строки без прямых reel-ссылок считаются профилями.
    Если есть только reel-ссылки — возвращаем один «блок» всего текста.
    """
    text = (raw or "").strip()
    if not text:
        return []
    if parse_reel_urls(text) and not any(
        ln.strip() and "instagram.com/reel" not in ln.lower() and "instagram.com/p/" not in ln.lower()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ):
        return [text]

    accounts: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if REEL_URL_RE.search(s):
            # одиночная ссылка на reel — отдельный «источник»
            accounts.append(s)
            continue
        try:
            username, _url = normalize_instagram_input(s)
            accounts.append(username)
        except ValueError:
            accounts.append(s)
    # unique keep order
    seen: set[str] = set()
    out: list[str] = []
    for a in accounts:
        key = a.lower().lstrip("@")
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out or [text]


def fetch_from_many_accounts(
    accounts: list[str],
    count: int,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
    on_log: ProgressCb | None = None,
    seed: int | None = None,
) -> list[Path]:
    """Скачивает count рилсов, стараясь брать с разных аккаунтов (round-robin + shuffle)."""
    if count < 1:
        raise ValueError("count >= 1")
    rng = random.Random(seed)
    pool = list(accounts)
    rng.shuffle(pool)
    if on_log:
        on_log(f"Instagram: {len(pool)} аккаунтов → рандомно по разным")

    # Сколько с каждого (равномерно, остаток раскидываем)
    base = count // len(pool)
    rem = count % len(pool)
    plan: list[tuple[str, int]] = []
    for i, acc in enumerate(pool):
        n = base + (1 if i < rem else 0)
        if n > 0:
            plan.append((acc, n))

    downloaded: list[Path] = []
    for acc, n in plan:
        if on_log:
            on_log(f"→ @{acc if 'instagram.com' not in acc.lower() else acc}: нужно {n}")
        try:
            part = fetch_instagram_videos(
                acc,
                n,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                on_log=on_log,
                seed=None if seed is None else seed + hash(acc) % 10_000,
            )
            downloaded.extend(part)
        except Exception as exc:  # noqa: BLE001
            if on_log:
                on_log(f"  пропуск {acc}: {exc}")

    if len(downloaded) < count:
        # добираем с случайных аккаунтов по 1
        extra_needed = count - len(downloaded)
        if on_log:
            on_log(f"Добираю ещё {extra_needed}…")
        for acc in rng.sample(pool, k=len(pool)):
            if extra_needed <= 0:
                break
            try:
                part = fetch_instagram_videos(
                    acc,
                    1,
                    cookies_from_browser=cookies_from_browser,
                    cookies_file=cookies_file,
                    on_log=on_log,
                )
                downloaded.extend(part)
                extra_needed -= len(part)
            except Exception:
                continue

    rng.shuffle(downloaded)
    return downloaded[:count]
