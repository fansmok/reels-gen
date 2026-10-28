"""Сбор прямых /reel/ ссылок через headless Chromium + cookies сессии."""

from __future__ import annotations

import re
from collections.abc import Callable
from http.cookiejar import MozillaCookieJar
from pathlib import Path

ProgressCb = Callable[[str], None]


def collect_reel_links_playwright(
    username: str,
    cookies_file: Path,
    *,
    limit: int = 30,
    on_log: ProgressCb | None = None,
) -> list[str]:
    """
    Открывает https://instagram.com/<user>/reels/ в Chromium с cookies,
    скроллит ленту и забирает прямые ссылки /reel/<code>/.
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Нужен playwright: pip install playwright && python -m playwright install chromium"
        ) from exc

    if not cookies_file.exists():
        raise FileNotFoundError(f"Нет cookies файла: {cookies_file}")

    jar = MozillaCookieJar(str(cookies_file))
    jar.load(ignore_discard=True, ignore_expires=True)
    pw_cookies: list[dict] = []
    for c in jar:
        domain = c.domain or ".instagram.com"
        if "instagram" not in domain:
            continue
        item = {
            "name": c.name,
            "value": c.value,
            "domain": domain if domain.startswith(".") else domain,
            "path": c.path or "/",
        }
        # Playwright требует url или domain
        pw_cookies.append(item)

    if not any(c["name"] == "sessionid" for c in pw_cookies):
        raise RuntimeError("В cookies нет sessionid — подтяните cookies из Opera снова")

    log(f"Playwright: открываю reels @{username}…")
    urls: list[str] = []
    seen: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        try:
            context.add_cookies(pw_cookies)
            page = context.new_page()
            page.goto(
                f"https://www.instagram.com/{username}/reels/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3500)

            # если редирект на login — стоп
            if "accounts/login" in page.url:
                raise RuntimeError(
                    "Instagram просит логин — cookies устарели. "
                    "Закройте Opera и нажмите «Подтянуть cookies»."
                )

            for i in range(12):
                hrefs = page.eval_on_selector_all(
                    'a[href*="/reel/"]',
                    "els => els.map(e => e.href)",
                )
                for href in hrefs or []:
                    m = re.search(r"/reel/([A-Za-z0-9_-]+)/?", href or "")
                    if not m:
                        continue
                    code = m.group(1)
                    if code in seen:
                        continue
                    seen.add(code)
                    urls.append(f"https://www.instagram.com/reel/{code}/")
                    if len(urls) >= limit:
                        break
                if len(urls) >= limit:
                    break
                # скролл вниз — подгрузка сетки reels
                page.mouse.wheel(0, 2400)
                page.wait_for_timeout(1200)
                log(f"Playwright: скролл {i + 1}, ссылок {len(urls)}")

            # запасной парсинг HTML
            if len(urls) < max(3, limit // 3):
                html = page.content()
                for code in re.findall(r"/reel/([A-Za-z0-9_-]{5,})/", html):
                    if code in seen:
                        continue
                    seen.add(code)
                    urls.append(f"https://www.instagram.com/reel/{code}/")
                    if len(urls) >= limit:
                        break
        finally:
            context.close()
            browser.close()

    log(f"Playwright: собрано прямых ссылок {len(urls)}")
    return urls[:limit]
