"""Уникальные названия, триггерные слова и описания для YouTube Shorts."""

from __future__ import annotations

import hashlib
import random
import re
import string
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
TRIGGERS_FILE = ASSETS / "trigger_words.txt"
DESC_FILE = ASSETS / "desc_templates.txt"

DEFAULT_TRIGGERS = [
    "Смотри до конца",
    "Не пропусти",
    "Только сейчас",
    "Жми и забирай",
    "Секретный разбор",
    "Быстрый лайфхак",
    "Внимание на экран",
    "Эксклюзив",
    "Разбор за 60 секунд",
    "Срочно к просмотру",
]

DEFAULT_DESC_TEMPLATES = [
    "СМОТРЕТЬ ПОЛНОСТЬЮ В ТГ",
    "ПОЛНЫЙ РАЗБОР В TELEGRAM",
    "ССЫЛКА В TELEGRAM",
    "ЗАЛЕТАЙ В ТГ ЗА БОНУСОМ",
    "ЖМИ И ПЕРЕХОДИ В TELEGRAM",
]

# стоп-слова для авто-хэштегов из заголовка (не из словаря тематик)
RU_STOP = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все",
    "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по",
    "только", "ее", "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из",
    "ему", "теперь", "когда", "даже", "ну", "ли", "если", "уже", "или", "ни",
    "быть", "был", "до", "вас", "вам", "ведь", "там", "потом", "себя", "ей",
    "может", "они", "тут", "где", "есть", "надо", "для", "мы", "тебя", "их",
    "чем", "была", "сам", "без", "раз", "тоже", "себе", "под", "будет", "кто",
    "этот", "того", "какой", "почти", "мой", "тем", "чтобы", "сейчас", "были",
    "это", "просто", "очень", "можно", "нужно", "сегодня", "всем", "которые",
    "который", "которая", "после", "перед", "через", "между", "также", "более",
    "смотри", "конца", "пропусти", "сейчас", "забирай", "экран", "внимание",
    "против", "подписал", "подписала", "больше", "вообще", "будешь", "будет",
    "была", "были", "этот", "этой", "этого", "того", "этим", "своей", "своих",
    "такой", "такая", "такие", "один", "одна", "самое", "самый", "самая",
}

# обрывки / мусор ASR — не пускать в заголовок
_TITLE_BAD_START = {
    "и", "а", "но", "что", "как", "это", "ну", "вот", "да", "нет", "типа", "короче",
    "то есть", "значит",
}
_TITLE_BAD_END = {
    "и", "а", "но", "что", "как", "на", "в", "с", "по", "к", "у", "из", "за", "от",
    "для", "чтобы", "если", "когда", "который", "которая", "которые", "это",
}


def ensure_meta_files() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    if not TRIGGERS_FILE.exists():
        TRIGGERS_FILE.write_text("\n".join(DEFAULT_TRIGGERS) + "\n", encoding="utf-8")
    if not DESC_FILE.exists():
        DESC_FILE.write_text("\n".join(DEFAULT_DESC_TEMPLATES) + "\n", encoding="utf-8")


def parse_lines(text: str | None) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def load_triggers(text: str | None = None) -> list[str]:
    ensure_meta_files()
    lines = parse_lines(text)
    if lines:
        return lines
    try:
        return parse_lines(TRIGGERS_FILE.read_text(encoding="utf-8")) or list(DEFAULT_TRIGGERS)
    except OSError:
        return list(DEFAULT_TRIGGERS)


def load_desc_hooks(text: str | None = None) -> list[str]:
    ensure_meta_files()
    lines = parse_lines(text)
    if lines:
        return lines
    try:
        return parse_lines(DESC_FILE.read_text(encoding="utf-8")) or list(DEFAULT_DESC_TEMPLATES)
    except OSError:
        return list(DEFAULT_DESC_TEMPLATES)


def _token(n: int = 5) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


def _stamp() -> str:
    return datetime.now().strftime("%m%d%H%M%S")


def _short_uid(seed: str | None = None) -> str:
    """Короткий хвост уникальности: 4 символа, удобно для YouTube title."""
    if seed:
        return hashlib.md5(seed.encode("utf-8", errors="ignore")).hexdigest()[:4].upper()
    return _token(4)


def _normalize_tag(raw: str) -> str:
    t = re.sub(r"[^\wа-яА-ЯёЁ0-9]", "", raw, flags=re.UNICODE)
    return t


def polish_title(text: str) -> str:
    """Приводит фразу к виду нормального YouTube-заголовка без ИИ."""
    t = " ".join((text or "").split()).strip(" ·-,;:«»\"'")
    if not t:
        return ""
    # убрать хвостовой мусор / обрывы
    t = re.sub(r"\b(ну|вот|типа|короче|так вот|значит)\b\.?$", "", t, flags=re.I).strip()
    t = re.sub(r"[,:;…\-—]+\s*$", "", t).strip()
    t = re.sub(
        r"\b(и|а|но|что|как|это|на|в|с|по|к|у|из|за|от|для|чтобы|если|когда)\s*$",
        "",
        t,
        flags=re.I,
    ).strip(" ,;-—")
    # убрать двойные пробелы / странные ASR-хвосты в скобках
    t = re.sub(r"\([^)]{0,40}\)", "", t)
    t = " ".join(t.split()).strip(" ·-,;:")
    if not t:
        return ""
    # первая буква заглавная, остальное как есть (имена/аббревиатуры не ломаем)
    t = t[0].upper() + t[1:]
    return t


def title_is_garbage(text: str) -> bool:
    """Отсекает обрывки и типичную ерунду ASR для заголовка."""
    t = polish_title(text)
    words = t.split()
    if len(words) < 4 or len(t) < 18:
        return True
    if len(words) > 22:
        return True
    first = words[0].casefold().strip("«»\"'")
    last = re.sub(r"[^\wа-яё]", "", words[-1].casefold(), flags=re.I)
    if first in _TITLE_BAD_START or last in _TITLE_BAD_END:
        return True
    # слишком много крошечных слов — обычно обрыв мысли
    tiny = sum(1 for w in words if len(re.sub(r"[^\wа-яё]", "", w, flags=re.I)) <= 2)
    if tiny / len(words) > 0.4:
        return True
    # повтор одного слова подряд
    for a, b in zip(words, words[1:]):
        if a.casefold() == b.casefold() and len(a) > 2:
            return True
    content = [
        w for w in words
        if re.sub(r"[^\wа-яё]", "", w, flags=re.I).casefold() not in RU_STOP
        and len(re.sub(r"[^\wа-яё]", "", w, flags=re.I)) > 3
    ]
    if len(content) < 2:
        return True
    return False


def hashtags_from_title(title: str | None, *, limit: int = 10) -> list[str]:
    """Хэштеги только из слов заголовка (+ уже написанные #теги). Без словарей тематик."""
    return hashtags_from_text(title, limit=limit)


def hashtags_from_text(*parts: str | None, limit: int = 10) -> list[str]:
    """
    Только:
    1) уже написанные #теги в тексте
    2) значимые слова из переданных строк (ожидается заголовок)
    Без словаря #ставки/#betting и без тематических подмен.
    """
    text = " ".join(str(p or "") for p in parts).strip()
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        tag = tag.strip()
        if not tag.startswith("#"):
            tag = "#" + tag
        body = _normalize_tag(tag[1:])
        if len(body) < 4:  # короткие типа #тг/#fyp не тащим из авто
            return
        # отсекаем явный мусор/служебное
        junk = {
            "shorts", "viral", "fyp", "шортс", "reels", "youtube",
            "ставки", "betting", "казино", "casino", "смотри", "конца",
            # спортивные теги из режима трансляций vk-bot — не для рилсов
            "трансляция", "матч", "прогноз", "прямойэфир", "прямой", "эфир",
            "онлайн", "смотреть", "live", "livestream",
            "футбол", "хоккей", "теннис", "football", "hockey", "tennis",
            "soccer", "спорт", "sport", "sports",
        }
        if body.casefold() in junk:
            return
        tag = "#" + body
        key = tag.casefold()
        if key in seen:
            return
        seen.add(key)
        tags.append(tag)

    for raw in re.findall(r"#([\w\d_а-яА-ЯёЁ]+)", text, flags=re.UNICODE):
        add("#" + raw)

    # слова заголовка: длиннее и содержательнее
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", text)
    for word in tokens:
        low = word.casefold()
        if low in RU_STOP:
            continue
        add("#" + word)
        if len(tags) >= limit:
            break
    return tags[:limit]


def unique_title(
    *,
    triggers_text: str | None = None,
    base: str | None = None,
    phrases: list[str] | None = None,
    index: int = 0,
    seed: str | None = None,
    apply_triggers: bool = True,
) -> str:
    """
    Ядро — фраза из пула по index (у каждого рилса своя).
    Триггер (начало/конец) — только если apply_triggers=True.
    """
    rng = random.Random(seed) if seed else random
    pool: list[str] = []
    for p in (phrases or []):
        if not p or not str(p).strip():
            continue
        cleaned = polish_title(str(p))
        if cleaned and not title_is_garbage(cleaned):
            pool.append(cleaned)
        elif cleaned and cleaned not in pool:
            # для Kie/готовых кликбейтов не режем «мусором» слишком строго
            if len(cleaned.split()) >= 3 and len(cleaned) >= 12:
                pool.append(cleaned)
    if base and base.strip():
        b = polish_title(base)
        if b and b not in pool:
            if (not title_is_garbage(b)) or (len(b.split()) >= 3 and len(b) >= 12):
                pool = [b] + pool

    if not pool:
        if apply_triggers:
            triggers = parse_lines(triggers_text) or load_triggers(None) or list(DEFAULT_TRIGGERS)
            raw = (triggers[index % len(triggers)] if triggers else "Shorts")[:95]
        else:
            raw = (polish_title(base or "") or "Shorts")[:95]
        return raw.upper()

    core = pool[index % len(pool)]

    if not apply_triggers:
        return core[:100].strip().upper()

    triggers = parse_lines(triggers_text) or load_triggers(None)
    if not triggers:
        triggers = list(DEFAULT_TRIGGERS)
    trig = triggers[index % len(triggers)].strip()
    max_core = max(55, 95 - len(trig) - 3)
    if len(core) > max_core:
        cut = core[: max_core - 1].rsplit(" ", 1)[0].strip(" ·-,;:")
        core = polish_title(cut or core[:max_core])

    if trig.casefold() in core.casefold():
        return core[:100].strip().upper()

    if rng.random() < 0.5:
        title = f"{trig} — {core}"
    else:
        title = f"{core} — {trig}"
    return title[:100].strip().upper()


def unique_hashtags_for_title(
    title: str | None,
    *,
    extra_hashtags: str | None = None,
    permanent_hashtags: str | None = None,
    index: int = 0,
    seed: str | None = None,
    limit: int = 16,
) -> str:
    """Хэштеги: основные (permanent) + текущие из UI (extra). Без авто из title и без спорт-тегов."""
    _ = (title, index, seed)
    return merge_hashtags(
        extra_hashtags,
        permanent_first=permanent_hashtags,
        limit=limit,
    )


def _parse_hashtag_list(text: str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    # спорт/трансляции из vk-bot — никогда не тащим в рилсы
    sports_junk = {
        "трансляция", "матч", "прогноз", "шортс", "shorts", "прямойэфир",
        "прямой", "эфир", "онлайн", "смотреть", "live", "livestream",
        "прямаятрансляция", "смотретьонлайн",
        "футбол", "хоккей", "теннис", "football", "hockey", "tennis",
        "soccer", "спорт", "sport", "sports",
    }
    for part in re.split(r"[\s,;]+", (text or "").strip()):
        part = part.strip()
        if not part:
            continue
        if not part.startswith("#"):
            part = f"#{part}"
        body = _normalize_tag(part[1:])
        if len(body) < 2:
            continue
        if body.casefold() in sports_junk:
            continue
        tag = "#" + body
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def merge_hashtags(
    *parts: str | None,
    auto_from: list[str | None] | None = None,
    limit: int = 20,
    permanent_first: str | None = None,
) -> str:
    """
    Склеивает теги без дублей.
    permanent_first всегда в начале и никогда не вытесняется лимитом.
    auto_from — только заголовок (слова из title), без словарей тематик.
    """
    merged: list[str] = []
    seen: set[str] = set()

    def add_many(tags: list[str], *, reserved: bool = False) -> None:
        for t in tags:
            k = t.casefold()
            if k in seen:
                continue
            if not reserved and len(merged) >= limit:
                break
            seen.add(k)
            merged.append(t)

    perm = _parse_hashtag_list(permanent_first) if permanent_first is not None else []
    add_many(perm, reserved=True)

    for part in parts:
        add_many(_parse_hashtag_list(part))
    if auto_from:
        # берём только непустые куски; ожидается title
        auto_limit = max(3, limit - len(merged))
        add_many(hashtags_from_text(*auto_from, limit=auto_limit))
    return " ".join(merged[: max(limit, len(perm))])


def description_title_and_tags(
    title: str | None,
    *,
    extra_hashtags: str | None = None,
    permanent_hashtags: str | None = None,
    index: int = 0,
    seed: str | None = None,
) -> str:
    """Заголовок + хэштеги пользователя (основные + текущие). Без спорт-тегов vk-bot."""
    head = " ".join(str(title or "").split()).strip()
    tags_line = unique_hashtags_for_title(
        head,
        extra_hashtags=extra_hashtags,
        permanent_hashtags=permanent_hashtags,
        index=index,
        seed=(seed or "") + "h",
        limit=20,
    ).strip()
    if head and tags_line:
        return f"{head}\n\n{tags_line}"
    return head or tags_line


def unique_description(
    *,
    title: str | None = None,
    tg_link: str | None = None,
    desc_template: str | None = None,
    desc_hooks_text: str | None = None,
    extra_hashtags: str | None = None,
    permanent_hashtags: str | None = None,
    manual_body: str | None = None,
    phrases: list[str] | None = None,
    index: int = 0,
    seed: str | None = None,
) -> str:
    """Описание = заголовок + хэштеги (остальные аргументы сохранены для совместимости)."""
    _ = (tg_link, desc_template, desc_hooks_text, manual_body, phrases)
    phrase = " ".join(str(title or "").split()).strip()
    if not phrase and phrases:
        for p in phrases:
            if p and str(p).strip():
                phrase = str(p).strip()
                break
    return description_title_and_tags(
        phrase,
        extra_hashtags=extra_hashtags,
        permanent_hashtags=permanent_hashtags,
        index=index,
        seed=seed,
    )


def compose_custom_description(
    body: str,
    *,
    title: str | None = None,
    tg_link: str | None = None,
    extra_hashtags: str | None = None,
    permanent_hashtags: str | None = None,
    index: int = 0,
    seed: str | None = None,
) -> str:
    """Как unique_description: только заголовок + хэштеги (body/tg_link игнорируются)."""
    _ = (body, tg_link)
    return description_title_and_tags(
        title,
        extra_hashtags=extra_hashtags,
        permanent_hashtags=permanent_hashtags,
        index=index,
        seed=seed,
    )


def meta_for_file(
    path_stem: str,
    *,
    tg_link: str | None = None,
    base_title: str | None = None,
    triggers_text: str | None = None,
    phrases: list[str] | None = None,
    index: int = 0,
    desc_hooks_text: str | None = None,
    desc_template: str | None = None,
    manual_description: str | None = None,
    extra_hashtags: str | None = None,
    permanent_hashtags: str | None = None,
    use_custom_meta: bool = False,
    custom_titles: list[str] | None = None,
    custom_descriptions: list[str] | None = None,
    apply_triggers: bool = True,
) -> dict[str, str]:
    digest = hashlib.md5(
        f"{path_stem}-{index}-{time.time_ns()}".encode("utf-8", errors="ignore")
    ).hexdigest()[:10]
    phrase_pool = list(phrases or [])

    custom_titles = [t.strip() for t in (custom_titles or []) if t and str(t).strip()]
    custom_descriptions = [
        d.strip() for d in (custom_descriptions or []) if d and str(d).strip()
    ]

    if use_custom_meta and custom_titles:
        title = custom_titles[index % len(custom_titles)].strip().upper()
    else:
        title = unique_title(
            triggers_text=triggers_text,
            base=base_title,
            phrases=phrase_pool,
            index=index,
            seed=digest + "t",
            apply_triggers=bool(apply_triggers),
        )

    if use_custom_meta and custom_descriptions:
        description = compose_custom_description(
            custom_descriptions[index % len(custom_descriptions)],
            title=title,
            tg_link=tg_link,
            extra_hashtags=extra_hashtags,
            permanent_hashtags=permanent_hashtags,
            index=index,
            seed=digest + "d",
        )
    else:
        description = unique_description(
            title=title,
            tg_link=tg_link,
            desc_template=desc_template,
            desc_hooks_text=desc_hooks_text,
            extra_hashtags=extra_hashtags,
            permanent_hashtags=permanent_hashtags,
            manual_body=manual_description,
            phrases=phrase_pool,
            index=index,
            seed=digest + "d",
        )

    tags = unique_hashtags_for_title(
        title,
        extra_hashtags=extra_hashtags,
        permanent_hashtags=permanent_hashtags,
        index=index,
        seed=digest + "h",
        limit=16,
    )
    cover_phrase = (
        phrase_pool[index % len(phrase_pool)] if phrase_pool else title
    )
    return {
        "title": title,
        "description": description,
        "hashtags": tags,
        "uid": digest,
        "cover_phrase": str(cover_phrase or title).strip().upper(),
    }


def preview_unique_titles(
    *,
    base: str | None = None,
    phrases: list[str] | None = None,
    triggers_text: str | None = None,
    count: int = 3,
    apply_triggers: bool = True,
) -> list[str]:
    out = []
    for i in range(count):
        out.append(
            unique_title(
                base=base,
                phrases=phrases,
                triggers_text=triggers_text,
                index=i,
                seed=f"preview-{i}-{base}-{time.time_ns()}",
                apply_triggers=apply_triggers,
            )
        )
    return out
