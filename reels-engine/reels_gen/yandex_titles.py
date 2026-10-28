"""Заголовки из поиска Яндекса по транскрипту.

Основной канал — Yandex Suggest (стабильно, без капчи).
Дополнительно пробуем органическую выдачу yandex.ru/search;
если капча — остаёмся на suggest.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from html import unescape
from typing import Any

import requests

ProgressCb = Callable[[str], None]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_STOP_SHORT = {
    "и", "в", "во", "на", "не", "что", "как", "это", "для", "по", "из", "за",
    "от", "до", "но", "а", "то", "же", "бы", "ли", "или", "если", "когда",
    "тот", "та", "те", "там", "тут", "день", "раз", "уже", "ещё", "еще",
    "все", "всё", "они", "она", "оно", "мы", "вы", "его", "её", "их",
}


def _log(cb: ProgressCb | None, msg: str) -> None:
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": _UA,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Accept": "text/html,application/json,*/*;q=0.8",
        }
    )
    return s


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[.!?…\n]+", text or "")
    out: list[str] = []
    for p in parts:
        s = " ".join(p.split()).strip(" -,;:«»\"'")
        if len(s) >= 12:
            out.append(s)
    return out


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", (text or "").lower())
    return {w for w in words if w not in _STOP_SHORT}


def build_search_seeds(transcript: str, *, limit: int = 8) -> list[str]:
    """Сильные префиксы 3–6 слов (слабые вроде «в тот же день» отбрасываем)."""
    text = " ".join((transcript or "").split()).strip()
    if not text:
        return []
    seeds: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        s = " ".join(s.split()).strip(" -,;:")
        words = s.split()
        if len(words) < 3:
            return
        if len(words) > 6:
            s = " ".join(words[:6])
        if len(_content_words(s)) < 2:
            return
        key = s.casefold()
        if key in seen:
            return
        seen.add(key)
        seeds.append(s)

    for sent in _split_sentences(text)[:12]:
        words = sent.split()
        if len(words) < 3:
            continue
        add(" ".join(words[:4]))
        add(" ".join(words[:6]))
        if len(words) >= 7:
            add(" ".join(words[1:6]))
        i = 0
        while i < len(words) and words[i].casefold() in _STOP_SHORT:
            i += 1
        if i and len(words) - i >= 3:
            add(" ".join(words[i : i + 5]))

    if not seeds:
        toks = sorted(_content_words(text), key=len, reverse=True)[:6]
        if len(toks) >= 3:
            add(" ".join(toks[:5]))
    return seeds[:limit]


def _polish_title(raw: str) -> str:
    t = unescape(re.sub(r"<[^>]+>", "", raw or ""))
    t = " ".join(t.split()).strip(" ·-,;:«»\"'")
    t = re.sub(r"\s*[\|–—-]\s*(Яндекс|Yandex|Wikipedia|Википедия).*$", "", t, flags=re.I)
    if not t:
        return ""
    if t.isupper() and len(t) > 12:
        t = t.capitalize()
    else:
        t = t[0].upper() + t[1:]
    if len(t) > 110:
        t = t[:107].rsplit(" ", 1)[0].rstrip("-,;:") + "…"
    return t


def _relevant(title: str, context_words: set[str], seed_words: set[str] | None = None) -> bool:
    tw = _content_words(title)
    if len(tw) < 2:
        return False
    if seed_words and not (tw & seed_words):
        return False
    if not context_words:
        return True
    need = 2 if len(context_words) >= 6 else 1
    return len(tw & context_words) >= need


def _parse_suggest_payload(data: Any) -> list[str]:
    if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
        return [str(x) for x in data[1] if x]
    if isinstance(data, dict):
        for key in ("suggest", "results", "data"):
            val = data.get(key)
            if isinstance(val, list):
                return [str(x) for x in val if x]
    return []


def fetch_yandex_suggest(query: str, *, session: requests.Session | None = None, limit: int = 12) -> list[str]:
    sess = session or _session()
    r = sess.get(
        "https://suggest.yandex.ru/suggest-ya.cgi",
        params={
            "part": query[:120],
            "uil": "ru",
            "v": "4",
            "sn": str(max(limit, 10)),
            "n": str(max(limit, 10)),
            "lr": "213",
        },
        timeout=15,
    )
    r.raise_for_status()
    try:
        data = r.json()
    except Exception:
        m = re.search(r"\((.*)\)\s*$", r.text, flags=re.S)
        if not m:
            return []
        data = json.loads(m.group(1))
    out: list[str] = []
    for raw in _parse_suggest_payload(data):
        title = _polish_title(raw)
        if len(title) >= 12:
            out.append(title)
        if len(out) >= limit:
            break
    return out


def fetch_yandex_serp_titles(query: str, *, session: requests.Session | None = None, limit: int = 10) -> list[str]:
    sess = session or _session()
    r = sess.get(
        "https://yandex.ru/search/",
        params={"text": query[:180], "lr": "213"},
        timeout=20,
    )
    if r.status_code != 200:
        return []
    html = r.text
    low = html.lower()
    if "smartcaptcha" in low or "showcaptcha" in low or "captcha" in low[:2000]:
        return []

    titles: list[str] = []
    patterns = [
        r"OrganicTitleContentSpan[^>]*>([^<]+)",
        r'class="OrganicTitle[^"]*"[^>]*>.*?>([^<]{12,160})',
        r"<h2[^>]*>\s*<a[^>]*>(.*?)</a>",
    ]
    seen: set[str] = set()
    for pat in patterns:
        for raw in re.findall(pat, html, flags=re.I | re.S):
            title = _polish_title(raw)
            if len(title) < 12:
                continue
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
            if len(titles) >= limit:
                return titles
    return titles


def titles_from_transcript(
    transcript: str,
    *,
    limit: int = 10,
    on_log: ProgressCb | None = None,
) -> list[str]:
    """До `limit` заголовков по транскрипту: выдача Яндекса + Suggest."""
    text = " ".join((transcript or "").split()).strip()
    if len(text) < 20:
        raise ValueError("Сначала распознайте речь — нужен транскрипт")

    seeds = build_search_seeds(text, limit=8)
    if not seeds:
        raise ValueError("Не удалось собрать поисковые фразы из транскрипта")

    ctx = _content_words(text)
    sess = _session()
    found: list[str] = []
    seen: set[str] = set()

    def add_many(items: list[str], *, seed: str | None = None, strict: bool = True) -> None:
        sw = _content_words(seed) if seed else None
        for t in items:
            if len(t.split()) < 4 and strict:
                continue
            if strict and not _relevant(t, ctx, sw):
                continue
            key = t.casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append(t)
            if len(found) >= limit:
                return

    main_q = seeds[0]
    _log(on_log, f"Яндекс: пробую выдачу «{main_q[:60]}…»")
    try:
        serp = fetch_yandex_serp_titles(main_q, session=sess, limit=limit)
        if serp:
            _log(on_log, f"Яндекс: из выдачи {len(serp)} заголовков")
            add_many(serp, seed=main_q, strict=False)
        else:
            _log(on_log, "Яндекс: выдача недоступна (капча) — беру подсказки Suggest")
    except Exception as exc:  # noqa: BLE001
        _log(on_log, f"Яндекс: выдача не ответила ({exc}) — Suggest")

    for i, seed in enumerate(seeds, 1):
        if len(found) >= limit:
            break
        _log(on_log, f"Яндекс Suggest [{i}/{len(seeds)}]: «{seed}»")
        try:
            sug = fetch_yandex_suggest(seed, session=sess, limit=12)
            add_many(sug, seed=seed, strict=True)
        except Exception as exc:  # noqa: BLE001
            _log(on_log, f"  suggest ошибка: {exc}")

    if len(found) < min(5, limit):
        _log(on_log, "Яндекс: мало релевантных — ослабляю фильтр")
        for seed in seeds:
            if len(found) >= limit:
                break
            try:
                sug = fetch_yandex_suggest(seed, session=sess, limit=12)
                add_many(sug, seed=seed, strict=False)
            except Exception:
                pass

    if not found:
        raise RuntimeError(
            "Яндекс не вернул заголовки. Проверьте интернет / повторите позже "
            "(иногда мешает капча)."
        )
    _log(on_log, f"Готово: {len(found)} заголовков из Яндекса")
    return found[:limit]
