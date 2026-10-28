"""Kie AI: тексты под каждую площадку (заголовок, описание, хэштеги) с лимитами.

  pack --opts FILE   — opts: {items:[{uid,title,description,hashtags}], transcript, platforms,
                       kieApiKey, tgLink, theme}
                       → result {packs: {uid: {platform: {title, description, hashtags}}, ...},
                                 sources: {uid: 'kie'|'local'}}

Одна модель и один URL с генератором (reels_gen/kie_titles.py). При сбое Kie пакет собирается
локально из базовых текстов — очередь не останавливается.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bridge_common import fail, log, result, run_main, setup_engine_paths  # noqa: E402

# те же лимиты, что в src/shared/kie-pack.ts
LIMITS: dict[str, dict[str, int]] = {
    "youtube": {"title": 100, "description": 5000, "hashtags": 5},
    "rutube": {"title": 100, "description": 5000, "hashtags": 5},
    "pinterest": {"title": 100, "description": 500, "hashtags": 3},
    "dzen": {"title": 0, "description": 1000, "hashtags": 5},
    "tiktok": {"title": 0, "description": 4000, "hashtags": 5},
    "vk": {"title": 0, "description": 500, "hashtags": 5},
    "instagram": {"title": 0, "description": 2200, "hashtags": 5},
}

PLATFORM_HINTS = {
    "youtube": "YouTube Shorts: цепляющий заголовок до 70 символов ЗАГЛАВНЫМИ, описание 2–4 строки, в конце ссылка (если дана) и 3–5 хэштегов, один из них #shorts.",
    "rutube": "Rutube Shorts: заголовок до 80 символов, спокойнее, чем для YouTube, без англицизмов; описание 2–3 строки с хэштегами в конце.",
    "pinterest": "Pinterest: заголовок до 60 символов как у идеи-пина, описание до 400 символов — что увидит зритель и зачем сохранять, 2–3 хэштега.",
    "dzen": "Дзен: без заголовка; описание 1–2 предложения, ровно 5 хэштегов по теме ролика.",
    "tiktok": "TikTok: без заголовка; подпись до 150 символов живым языком + ровно 5 хэштегов, без #fyp #viral.",
    "vk": "VK Клипы: без заголовка; подпись до 300 символов, 3–5 хэштегов.",
    "instagram": "Instagram Reels: без заголовка; подпись 1–3 строки с эмодзи по вкусу + до 5 хэштегов.",
}

_SKIP_TAGS = {"fyp", "foryou", "viral", "reels", "reel", "рек", "рекомендации"}
# площадки, где бот вводит хэштеги отдельным полем (src/shared/platforms.ts: usesHashtags)
TAGS_SEPARATE = {"tiktok", "dzen"}


def _lines(text: str) -> str:
    return " ".join(str(text or "").split())


def _parse_tags(raw, limit: int) -> str:
    if isinstance(raw, list):
        text = " ".join(str(t) for t in raw)
    else:
        text = str(raw or "")
    out: list[str] = []
    for tok in re.split(r"[\s,;]+", text):
        tag = tok.strip().lstrip("#").strip("«»\"'.,!?")
        if not tag or tag.lower() in _SKIP_TAGS:
            continue
        if not re.match(r"^[\w\d_]+$", tag, flags=re.UNICODE):
            continue
        if tag.lower() in {t.lower() for t in out}:
            continue
        out.append(tag)
        if len(out) >= limit:
            break
    return " ".join(f"#{t}" for t in out)


def _cut(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[-30:]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-—") + "…"


def _strip_tags_from(text: str) -> str:
    return re.sub(r"(^|\s)#[\w\d_]+", " ", str(text or "")).strip()


def local_pack(item: dict, platforms: list[str], tg_link: str) -> dict:
    """Пакет без нейросети — базовые тексты, подогнанные под лимиты."""
    title = _lines(item.get("title") or "")
    base_desc = str(item.get("description") or "").strip()
    tags_all = _parse_tags(item.get("hashtags") or "", 10)
    pack: dict[str, dict] = {}
    for p in platforms:
        lim = LIMITS.get(p)
        if not lim:
            continue
        tags = _parse_tags(tags_all + (" #shorts" if p == "youtube" else ""), lim["hashtags"])
        body = _strip_tags_from(base_desc) if base_desc else title
        if p in {"tiktok", "vk", "instagram", "dzen"}:
            body = (title + ("\n" + body if body and body != title else "")).strip()
        if tg_link and tg_link not in body and p in {"youtube", "rutube", "instagram", "pinterest"}:
            body = (body + f"\n\n{tg_link}").strip()
        desc = (_strip_tags_from(body) if p in TAGS_SEPARATE else body + ("\n\n" + tags if tags else "")).strip()
        pack[p] = {
            "title": _cut(title, lim["title"]) if lim["title"] else "",
            "description": _cut(desc, lim["description"]),
            "hashtags": tags,
        }
    return pack


def _prompt(item: dict, transcript: str, platforms: list[str], tg_link: str, theme: str) -> str:
    desc = _lines(transcript)
    if len(desc) > 3000:
        desc = desc[:3000] + "…"
    hints = "\n".join(f"- {p}: {PLATFORM_HINTS[p]}" for p in platforms if p in PLATFORM_HINTS)
    base = (
        f"Базовый заголовок: {item.get('title') or '—'}\n"
        f"Базовое описание: {_lines(item.get('description') or '') or '—'}\n"
        f"Базовые хэштеги: {item.get('hashtags') or '—'}\n"
        f"Ссылка для описания: {tg_link or 'нет'}\n"
        f"Тема: {theme or 'по тексту'}\n"
    )
    return (
        "Ты редактор коротких видео. Подготовь тексты для публикации ОДНОГО ролика на разных площадках.\n\n"
        f"Текст ролика (распознанная речь):\n{desc or '— нет текста, опирайся на базовый заголовок и тему —'}\n\n"
        f"{base}\n"
        "Правила для площадок:\n"
        f"{hints}\n\n"
        "Общие правила: только русский язык; заголовки — недосказанный исход, конфликт или конкретная деталь, "
        "без «ШОК», «СМОТРИ ДО КОНЦА», «ТОП МОМЕНТ»; описания живые, без воды; хэштеги только по теме ролика, "
        "без #fyp #viral #рек; если дана ссылка — добавь её в описание там, где уместно.\n\n"
        "Ответ — строго JSON без пояснений и без markdown, вида:\n"
        '{"youtube": {"title": "...", "description": "...", "hashtags": "#a #b"}, "tiktok": {"title": "", "description": "...", "hashtags": "#a #b #c #d #e"}}\n'
        f"Ключи — ровно эти площадки: {', '.join(platforms)}. У площадок без заголовка поле title пустое."
    )


def _extract_json(text: str) -> dict:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _pack_is_russian(data: dict, platforms: list[str]) -> bool:
    from kie_titles import is_russian

    for platform in platforms:
        block = data.get(platform)
        if not isinstance(block, dict):
            continue
        for key in ("title", "description"):
            text = str(block.get(key) or "").strip()
            if text and not is_russian(text):
                return False
    return True


def kie_pack(item: dict, transcript: str, platforms: list[str], api_key: str | None, tg_link: str, theme: str) -> dict:
    from kie_titles import is_russian, kie_complete

    key = str(api_key or "").strip()
    if not key:
        raise ValueError("Не задан API-ключ Kie — укажите его в настройках программы")
    content = kie_complete(_prompt(item, transcript, platforms, tg_link, theme), api_key=key, on_log=log)
    data = _extract_json(str(content))
    if not data:
        raise RuntimeError("Kie вернул не JSON")
    if not _pack_is_russian(data, platforms):
        log("Kie ответила не по-русски — переписываю тексты площадок")
        content = kie_complete(
            "Перепиши JSON ниже на русский язык. Ключи и структуру не меняй. "
            "Заголовки, описания и хэштеги — только по-русски, без английских слов.\n\n"
            + json.dumps(data, ensure_ascii=False),
            api_key=key,
            on_log=log,
        )
        rewritten = _extract_json(str(content))
        if rewritten and _pack_is_russian(rewritten, platforms):
            data = rewritten
    fallback = local_pack(item, platforms, tg_link)
    pack: dict[str, dict] = {}
    for p in platforms:
        lim = LIMITS.get(p)
        if not lim:
            continue
        got = data.get(p) if isinstance(data.get(p), dict) else {}
        fb = fallback.get(p, {})
        title = _lines(got.get("title") or "") if lim["title"] else ""
        if lim["title"] and not title:
            title = fb.get("title", "")
        if lim["title"] and title and not is_russian(title):
            title = _cut((theme or "смотри этот момент").upper(), lim["title"])
        tags = _parse_tags(got.get("hashtags") or fb.get("hashtags") or "", lim["hashtags"])
        if p == "youtube" and tags and "#shorts" not in tags.lower():
            tags = _parse_tags(tags + " #shorts", lim["hashtags"])
        desc = str(got.get("description") or "").strip() or fb.get("description", "")
        if desc and not is_russian(desc):
            desc = title or theme or ""
        if p in TAGS_SEPARATE:
            # у TikTok и Дзена хэштеги бот вводит отдельным полем — в описании их не дублируем
            desc = _strip_tags_from(desc)
        elif tags and not re.search(r"#[\w\d_]+", desc):
            desc = (desc + "\n\n" + tags).strip()
        if tg_link and tg_link not in desc and p in {"youtube", "rutube", "instagram", "pinterest"}:
            desc = (desc + f"\n\n{tg_link}").strip()
        pack[p] = {
            "title": _cut(title.upper() if p in {"youtube", "rutube"} else title, lim["title"]) if lim["title"] else "",
            "description": _cut(desc, lim["description"]),
            "hashtags": tags,
        }
    return pack


def cmd_pack(args: argparse.Namespace) -> int:
    setup_engine_paths()
    opts = json.loads(Path(args.opts).read_text(encoding="utf-8-sig"))
    items = [it for it in (opts.get("items") or []) if isinstance(it, dict)]
    if not items:
        return fail("Нет роликов для текстов")
    platforms = [p for p in (opts.get("platforms") or list(LIMITS)) if p in LIMITS]
    if not platforms:
        platforms = list(LIMITS)
    transcript = str(opts.get("transcript") or "")
    api_key = str(opts.get("kieApiKey") or "").strip() or None
    tg_link = str(opts.get("tgLink") or "").strip()
    theme = str(opts.get("theme") or "").strip()
    packs: dict[str, dict] = {}
    sources: dict[str, str] = {}
    for i, item in enumerate(items, 1):
        uid = str(item.get("uid") or item.get("video") or i)
        label = _lines(item.get("title") or "")[:60] or uid
        own = [p for p in (item.get("platforms") or []) if p in LIMITS]
        item_platforms = own or platforms
        names = ", ".join(item_platforms)
        try:
            log(f"Kie [{i}/{len(items)}] только {names}: {label}")
            packs[uid] = kie_pack(item, transcript, item_platforms, api_key, tg_link, theme)
            sources[uid] = "kie"
        except Exception as exc:  # noqa: BLE001
            log(f"Kie недоступен ({exc}) — собираю тексты из базовых")
            packs[uid] = local_pack(item, item_platforms, tg_link)
            sources[uid] = "local"
    result({"packs": packs, "sources": sources, "platforms": platforms})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Kie: тексты под площадки")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("--opts", required=True)
    p.set_defaults(fn=cmd_pack)
    args = parser.parse_args()
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    run_main(main)
