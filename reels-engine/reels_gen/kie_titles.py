"""Кликбейт-заголовки через Kie AI (Gemini 3.8 Flash).

API: https://docs.kie.ai/market/gemini/gemini-3-8-flash-openai
Модель: https://kie.ai/gemini-3-8-flash?model=gemini-3-8-flash
"""

from __future__ import annotations

import re
from collections.abc import Callable

import requests

ProgressCb = Callable[[str], None]

KIE_CHAT_URL = "https://api.kie.ai/gemini-3-8-flash-openai/v1/chat/completions"
KIE_MODEL = "gemini-3-8-flash"
DEFAULT_KIE_API_KEY = ""


def _log(cb: ProgressCb | None, msg: str) -> None:
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def _polish_title(raw: str) -> str:
    t = " ".join((raw or "").split()).strip()
    t = re.sub(r"^[\d]+[.)\-:—–\s]+", "", t)
    t = t.strip(" «»\"'*-•·")
    if not t:
        return ""
    if len(t) > 110:
        t = t[:107].rsplit(" ", 1)[0].rstrip("-,;:") + "…"
    return t.upper()


def _parse_titles(text: str, *, limit: int) -> list[str]:
    lines = []
    for raw in (text or "").splitlines():
        title = _polish_title(raw)
        if len(title) >= 8:
            lines.append(title)
    if len(lines) < limit:
        # иногда модель отдаёт через ; или •
        for chunk in re.split(r"[;\n•]+", text or ""):
            title = _polish_title(chunk)
            if len(title) >= 8 and title not in lines:
                lines.append(title)
    seen: set[str] = set()
    out: list[str] = []
    for t in lines:
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= limit:
            break
    return out


_RU_SYSTEM = (
    "Ты пишешь только на русском языке. Английские слова запрещены. "
    "Имена, команды и счёт передавай по-русски. Не объясняй, как ты это делаешь."
)


def is_russian(text: str) -> bool:
    """Большая часть букв — кириллица. Короткие строки без букв не считаем чужими."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return True
    cyr = sum(1 for ch in letters if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    return cyr / len(letters) >= 0.6


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return str(content or "")


def _kie_error(status: int, body: str) -> RuntimeError:
    if status == 401:
        return RuntimeError("Kie: неверный API-ключ")
    if status in (402, 429):
        return RuntimeError("Kie: нет баланса / лимит запросов")
    if status >= 500:
        return RuntimeError(f"Kie недоступен (HTTP {status})")
    return RuntimeError(f"Kie ошибка HTTP {status}: {body[:200]}")


def kie_complete(
    prompt: str,
    *,
    api_key: str | None = None,
    timeout: int = 120,
    on_log: ProgressCb | None = None,
) -> str:
    """Один ответ модели. Тело ошибки Kie бывает с HTTP 200 и полем code."""
    key = (api_key or DEFAULT_KIE_API_KEY).strip()
    if not key:
        raise ValueError("Не задан API-ключ Kie")

    def _post(messages: list[dict]) -> str:
        r = requests.post(
            KIE_CHAT_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": KIE_MODEL,
                "stream": False,
                "reasoning_effort": "low",
                "messages": messages,
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            raise _kie_error(r.status_code, r.text)
        try:
            data = r.json()
        except Exception as exc:
            raise RuntimeError(f"Kie: странный ответ — {exc}") from exc
        code = data.get("code") if isinstance(data, dict) else None
        if isinstance(code, int) and code not in (0, 200) and "choices" not in data:
            msg = str(data.get("msg") or code)
            if code == 401:
                raise RuntimeError("Kie: неверный API-ключ")
            if code in (402, 429):
                raise RuntimeError("Kie: нет баланса / лимит запросов")
            raise RuntimeError(f"Kie: {msg}")
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"Kie: странный ответ — {exc}") from exc
        text = _content_text(content).strip()
        if not text:
            raise RuntimeError("Kie вернул пустой ответ")
        return text

    array_messages = [
        {"role": "system", "content": [{"type": "text", "text": _RU_SYSTEM}]},
        {"role": "user", "content": [{"type": "text", "text": prompt}]},
    ]
    try:
        return _post(array_messages)
    except RuntimeError as exc:
        low = str(exc).lower()
        if "422" not in low and "validation" not in low and "content" not in low:
            raise
        _log(on_log, "Kie не принял формат сообщения — повторяю простым текстом")
        return _post(
            [
                {"role": "system", "content": _RU_SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )


def _rewrite_russian(text: str, *, api_key: str | None, timeout: int, on_log: ProgressCb | None) -> str:
    _log(on_log, "Kie ответила не по-русски — переписываю на русский")
    return kie_complete(
        "Перепиши текст ниже заново и только на русском языке. "
        "Сохрани число строк, нумерацию и строку ТЕГИ, если она есть. "
        "Хэштеги тоже русскими словами. Ни одного английского слова.\n\n"
        + text,
        api_key=api_key,
        timeout=timeout,
        on_log=on_log,
    )


def build_prompt(transcript: str, count: int) -> str:
    n = max(1, int(count))
    desc = " ".join((transcript or "").split()).strip()
    if len(desc) > 3500:
        desc = desc[:3500] + "…"
    return (
        f"Придумай {n} заголовков для рилса по тексту ниже.\n\n"
        f"Текст:\n{desc}\n\n"
        f"{_viral_title_rules(n)}"
    )


def generate_kie_titles(
    transcript: str,
    *,
    count: int = 5,
    api_key: str | None = None,
    on_log: ProgressCb | None = None,
    timeout: int = 120,
) -> list[str]:
    """Сгенерировать `count` заголовков. Бросает исключение при сбое API."""
    text = " ".join((transcript or "").split()).strip()
    if len(text) < 20:
        raise ValueError("Нужен транскрипт (минимум ~20 символов)")
    n = max(1, min(50, int(count)))
    key = (api_key or DEFAULT_KIE_API_KEY).strip()
    if not key:
        raise ValueError("Не задан API-ключ Kie")

    prompt = build_prompt(text, n)
    _log(on_log, f"Kie AI ({KIE_MODEL}): генерирую {n} заголовков…")
    content = kie_complete(prompt, api_key=key, timeout=timeout)
    titles = _parse_titles(content, limit=n)
    if not titles or any(not is_russian(t) for t in titles):
        content = _rewrite_russian(content, api_key=key, timeout=timeout, on_log=on_log)
        titles = _parse_titles(content, limit=n)
    if not titles or any(not is_russian(t) for t in titles):
        raise RuntimeError("Kie не дала заголовки на русском")
    _log(on_log, f"Kie: получено {len(titles)} заголовков")
    return titles


def titles_with_fallback(
    transcript: str,
    *,
    count: int,
    fallback_phrases: list[str] | None = None,
    api_key: str | None = None,
    on_log: ProgressCb | None = None,
) -> tuple[list[str], str]:
    """
    Возвращает (titles, source) где source = 'kie' | 'transcript'.
    При любой ошибке Kie — фразы из транскрипции.
    """
    try:
        titles = generate_kie_titles(
            transcript, count=count, api_key=api_key, on_log=on_log
        )
        return titles, "kie"
    except Exception as exc:  # noqa: BLE001
        _log(on_log, f"Kie недоступен ({exc}) — беру фразы транскрипции")
        fb = [p.strip() for p in (fallback_phrases or []) if p and str(p).strip() and is_russian(p)]
        if not fb:
            parts = re.split(r"[.!?…\n]+", transcript or "")
            fb = [
                " ".join(p.split()).strip()
                for p in parts
                if len(" ".join(p.split())) >= 12 and is_russian(" ".join(p.split()))
            ]
        n = max(1, int(count))
        if not fb:
            raise RuntimeError(f"Kie упал и нет запасных фраз: {exc}") from exc
        # дополним циклом до n
        out = list(fb[:n])
        i = 0
        while len(out) < n and fb:
            out.append(fb[i % len(fb)])
            i += 1
        return out[:n], "transcript"


DEFAULT_TITLE_THEME = "футбол топ момент"

_JUNK_TITLES = {
    "video",
    "untitled",
    "instagram",
    "reel",
    "reels",
    "shorts",
    "short",
    "youtube",
    "new video",
    "watch this",
    "check this",
    "follow",
    "fyp",
    "viral",
    "clip",
    "footage",
    "highlight",
    "highlights",
    "moment",
    "moments",
    "random",
    "test",
    "download",
    "watch",
    "full",
    "hd",
    "4k",
}

_FILLER_WORDS = _JUNK_TITLES | {
    "the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "my", "your",
    "new", "this", "that", "with", "from", "by", "at", "is", "it",
    "и", "в", "на", "с", "по", "это", "этот", "для",
}


def _word_ok(word: str) -> bool:
    body = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", word)
    if len(body) < 3 or body.casefold() in _FILLER_WORDS:
        return False
    return bool(re.search(r"[aeiouyаеёиоуыэюя]", body, flags=re.I))


def title_is_unclear(title: str) -> bool:
    """Название шортса — случайный набор, файл или пустышка, из него нельзя сделать заголовок."""
    t = " ".join((title or "").split()).strip()
    if len(t) < 4:
        return True
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", t)
    if len(letters) < 4:
        return True
    folded = t.casefold()
    if folded in _JUNK_TITLES or folded.startswith("untitled") or folded.startswith("video by"):
        return True
    if re.fullmatch(r"(img|vid|video|reel|short|dsc|mov|clip)[_\-\s]?\d+", t, flags=re.I):
        return True
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) == 1 and not re.search(r"[а-яё]", t, flags=re.I):
        token = re.sub(r"[^A-Za-z0-9]", "", words[0])
        if len(token) >= 12:
            return True
    content = [w for w in words if _word_ok(w)]
    return len(content) < 2


def _text_is_useful(text: str) -> bool:
    words = [w for w in re.split(r"\s+", text or "") if _word_ok(w) and not w.startswith("#")]
    return len(words) >= 4


def _viral_title_rules(n: int) -> str:
    """Формулы, которые в 2026 лучше набирают просмотры в Shorts / Reels.

    Источники разбора: curiosity gap (недосказанный исход), контраст, конкретная деталь,
    провокационное утверждение. Пустые «шок / смотри до конца / топ момент» почти не останавливают ленту.
    """
    return (
        "Как писать, чтобы ролик досматривали и репостили:\n"
        "- Недосказанный исход: факт есть, чем кончилось — нет. Зритель должен включить ролик.\n"
        "- Конфликт: судья, соперник, правило, камера, толпа. Кто-то неправ.\n"
        "- Слом ожидания: все ждали одно, вышло другое.\n"
        "- Одна конкретная деталь: минута, счёт, один жест. Без воды.\n"
        "- Провокация, с которой хочется поспорить: «так бить нельзя», «это не пенальти», «его за это удалили».\n"
        "- 4–9 слов, до 70 символов. Коротко, чтобы прочиталось в ленте.\n"
        "- Каждый заголовок — другая формула, не перефраз одного и того же.\n"
        "- Не выдавай развязку целиком. Не пиши «гол», если можно заставить досмотреть, чем это кончилось.\n"
        "Запрещено:\n"
        "- «СМОТРИ ДО КОНЦА», «ЖДИ», «ТОП МОМЕНТ», «НЕВЕРОЯТНО», «ШОК», «ПРОСТО ЖЕСТЬ», «ВЫНЕСЛО» как весь смысл.\n"
        "- Общие слова без картинки в голове.\n"
        "- Английский язык и дословный перевод.\n"
        "Примеры формы, не копируй имена из них:\n"
        "- ОН ПРОБИЛ — СУДЬЯ ДАЖЕ НЕ СВИСТНУЛ\n"
        "- 90+5. ВЕСЬ СТАДИОН УЖЕ ВСТАЛ\n"
        "- ТАКОЙ УДАР В ФУТБОЛЕ ЗАПРЕЩЁН\n"
        "- ВРАТАРЬ ПРЫГНУЛ НЕ В ТУ СТОРОНУ\n"
        "Правила ответа:\n"
        f"- ровно {n} заголовков\n"
        "- только русский язык\n"
        "- каждый заголовок на новой строке\n"
        "- нумерация 1. 2. 3. …\n"
        "- без кавычек и без пояснений\n"
        "- в строках заголовков хэштегов нет\n"
        "- ВСЕ ЗАГОЛОВКИ ЗАГЛАВНЫМИ БУКВАМИ\n"
        "- после заголовков одна строка: ТЕГИ: #тег1 #тег2 #тег3 #тег4 #тег5\n"
        "- ровно 5 хэштегов, только про этот ролик\n"
        "- без #shorts #reels #fyp #viral и без повторов"
    )


def build_source_prompt(
    title: str,
    description: str,
    theme: str,
    count: int,
    *,
    unclear: bool,
) -> str:
    n = max(1, int(count))
    theme_text = " ".join((theme or DEFAULT_TITLE_THEME).split()).strip() or DEFAULT_TITLE_THEME
    name = " ".join((title or "").split()).strip()
    desc = " ".join((description or "").split()).strip()
    if len(desc) > 1800:
        desc = desc[:1800] + "…"
    if unclear:
        # Случайное название модели не показываем: иначе она его «переводит».
        useful = desc if _text_is_useful(desc) else ""
        basis = (
            "Нормального названия у ролика нет — оно было случайным набором.\n"
            "Придумай заголовки сама, с нуля. Ничего не переводи и не цитируй.\n"
            f"Тема, внутри которой ты придумываешь: {theme_text}.\n"
        )
        if useful:
            basis += (
                "Ниже есть осмысленное описание. Возьми из него факт, но упакуй его как новый заголовок.\n\n"
                f"Описание:\n{useful}\n"
            )
        else:
            basis += (
                "Описания тоже нет. Не выдумывай имя реального игрока и точный счёт, "
                "которых ты не знаешь. Придумай ситуацию внутри темы.\n"
            )
        return f"{basis}\n{_viral_title_rules(n)}"
    return (
        "Есть настоящее название шортса. Сохрани, ЧТО произошло, но не переводи дословно.\n"
        "Упакуй этот момент в новый цепляющий заголовок.\n"
        f"Тему «{theme_text}» не подставляй вместо факта, если из названия уже ясно, о чём ролик.\n\n"
        f"Название шортса:\n{name}\n\n"
        f"Описание:\n{desc or '—'}\n\n"
        f"{_viral_title_rules(n)}"
    )


_TAG_SKIP = {"shorts", "reels", "fyp", "viral", "шортс", "reel"}


def _parse_tags(text: str, *, limit: int = 5) -> str:
    line = ""
    for raw in (text or "").splitlines():
        if re.match(r"^\s*(теги|хэштеги|хештеги|tags)\s*:", raw, flags=re.I):
            line = raw.split(":", 1)[1]
            break
    if not line:
        tail = [ln for ln in (text or "").splitlines() if "#" in ln]
        line = tail[-1] if tail else ""
    tags: list[str] = []
    seen: set[str] = set()
    for body in re.findall(r"#([\wа-яА-ЯёЁ]+)", line, flags=re.UNICODE):
        key = body.casefold()
        if len(body) < 3 or key in seen or key in _TAG_SKIP:
            continue
        seen.add(key)
        tags.append("#" + body)
        if len(tags) >= limit:
            break
    return " ".join(tags)


def titles_from_source(
    *,
    title: str,
    description: str,
    theme: str | None = None,
    count: int = 1,
    api_key: str | None = None,
    on_log: ProgressCb | None = None,
    timeout: int = 120,
) -> tuple[list[str], str, str]:
    """Заголовки на русском и строка тегов.

    Возвращает (titles, tags, mode), mode = 'theme' если исходное название мусорное,
    иначе 'source'.
    """
    theme_text = " ".join((theme or DEFAULT_TITLE_THEME).split()).strip() or DEFAULT_TITLE_THEME
    unclear = title_is_unclear(title)
    n = max(1, min(50, int(count)))
    key = (api_key or DEFAULT_KIE_API_KEY).strip()
    if not key:
        raise ValueError("Не задан API-ключ Kie")
    mode = "theme" if unclear else "source"
    prompt = build_source_prompt(title, description, theme_text, n, unclear=unclear)
    _log(
        on_log,
        "Kie сама придумывает заголовок: название ролика случайное"
        if unclear
        else "Kie: заголовок по названию шортса",
    )
    content = kie_complete(prompt, api_key=key, timeout=timeout)
    titles = _parse_titles(content, limit=n)
    if not titles or any(not is_russian(t) for t in titles):
        content = _rewrite_russian(content, api_key=key, timeout=timeout, on_log=on_log)
        titles = _parse_titles(content, limit=n)
    if not titles or any(not is_russian(t) for t in titles):
        raise RuntimeError("Kie не дала заголовки на русском")
    tags = _parse_tags(content)
    _log(on_log, f"Kie: {len(titles)} заголовков, тегов: {len(tags.split()) if tags else 0}")
    return titles, tags, mode
