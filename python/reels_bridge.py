"""Мост к генератору рилсов (reels_gen): генерация без загрузки, Whisper, Kie, превью.

Команды (все параметры — JSON-файл настроек мастера через --opts, ключи camelCase как в
src/shared/generator.ts; дополнительные поля: kieApiKey, files, force, video):
  info                       — папки 1/2/output, стили, значения по умолчанию
  generate --opts FILE       — сгенерировать рилсы и подготовить обложки/тексты → items
  transcribe --opts FILE     — Whisper по верхнему ролику → {text, phrases}
  kie-titles --opts FILE     — заголовки Kie по транскрипту → {titles, source}
  link-top --opts FILE       — скачать ролик по ссылке и собрать заголовок → {...}
  stickers --opts FILE       — загрузить стикер-пак Telegram → {name, title, stickers}
  preview-cta --opts FILE    — кадр CTA → {image}
  preview-banner --opts FILE — кадр баннера → {image, pauseAt, text}
  preview-cover --opts FILE  — обложка → {image, video, phrase}

Протокол: JSON-строки в stdout (см. bridge_common): log / progress / result / error.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import traceback
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bridge_common import emit, fail, log, result, run_main, setup_engine_paths  # noqa: E402


def progress(value: float) -> None:
    emit({"type": "progress", "value": max(0.0, min(1.0, float(value)))})


def load_opts(path: str | None) -> dict:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _lines(text: str | None) -> list[str]:
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]


def _file_info(path: Path) -> dict:
    try:
        st = path.stat()
        return {"name": path.name, "path": str(path), "size": st.st_size, "mtime": int(st.st_mtime * 1000)}
    except OSError:
        return {"name": path.name, "path": str(path), "size": 0, "mtime": 0}


# ---------------------------------------------------------------------------
# настройки мастера → opts движка (порт _collect_opts / _meta_for_opts из reels_tab.py)
# ---------------------------------------------------------------------------


def resolve_tops(s: dict) -> list[Path]:
    from engine import FOLDER_1, list_videos

    mode = str(s.get("topMode") or "latest")
    if mode == "telegram":
        return []
    if mode == "link":
        linked = str(s.get("linkedPath") or "")
        if linked and Path(linked).is_file():
            return [Path(linked)]
        return []
    videos = list_videos(FOLDER_1)
    if mode == "all":
        return list(videos)
    if mode == "random_one":
        return [random.choice(videos)] if videos else []
    if mode == "latest":
        return [max(videos, key=lambda p: p.stat().st_mtime)] if videos else []
    raw = str(s.get("topFile") or "")
    p = Path(raw) if raw else None
    if p and p.is_file():
        return [p]
    return [videos[0]] if videos else []


def _meta_opts(s: dict) -> dict:
    phrases = [p for p in (s.get("phrasesChecked") or s.get("phrases") or []) if str(p).strip()]
    title_base = str(s.get("titleBase") or "").strip() or (phrases[0] if phrases else None)
    triggers = [t for t in (s.get("triggers") or []) if str(t).strip()]
    tags = str(s.get("hashtags") or "").strip()
    permanent = str(s.get("permanentHashtags") or "").strip()
    use_custom = bool(s.get("useCustomMeta"))
    use_kie = bool(s.get("useKieTitles")) and not use_custom
    kie_titles = [t for t in (s.get("kieTitlesChecked") or s.get("kieTitles") or []) if str(t).strip()] if use_kie else []
    if use_kie and kie_titles:
        phrases = [str(t).upper() for t in kie_titles]
        title_base = phrases[0]
    apply_triggers = not use_kie and not use_custom
    custom_titles = [str(t).upper() for t in (s.get("customTitles") or []) if str(t).strip()]
    custom_descriptions = [str(t) for t in (s.get("customDescriptions") or []) if str(t).strip()]
    return {
        "title_base": str(title_base).upper() if title_base else None,
        "triggers_text": ("\n".join(triggers) if triggers and apply_triggers else None),
        "phrases": phrases or None,
        "manual_description": str(s.get("descManual") or "").strip() or None,
        "extra_hashtags": tags or None,
        "permanent_hashtags": permanent or None,
        "desc_hooks_text": None,
        "use_custom_meta": use_custom,
        "custom_titles": custom_titles if use_custom else None,
        "custom_descriptions": custom_descriptions if use_custom else None,
        "use_kie_titles": use_kie,
        "kie_titles": kie_titles or None,
        "apply_triggers": apply_triggers,
    }


def _qr(s: dict) -> tuple[Path | None, str | None]:
    from engine import resolve_qr

    qr_file = str(s.get("qrFile") or "").strip()
    qr_text = str(s.get("qr") or "").strip() or None
    if qr_file and Path(qr_file).is_file():
        return Path(qr_file), qr_text
    return resolve_qr(qr_text)


def _banner(s: dict) -> dict:
    b = dict(s.get("banner") or {})
    audio = str(b.get("audio") or "")
    return {
        "enabled": bool(b.get("enabled")),
        "text": str(b.get("text") or "").strip() or "ПОДПИШИСЬ",
        "style": str(b.get("style") or "random"),
        "duration": float(b.get("duration") or 4.0),
        "audio": audio if audio and Path(audio).is_file() else "",
        "randomize_text": True,
        "place": str(b.get("place") or "mid"),
        "source": str(b.get("source") or "").strip(),
        "drop_bottom": bool(b.get("dropBottom")),
    }


def _cover(s: dict) -> dict:
    c = dict(s.get("cover") or {})
    return {
        "enabled": bool(c.get("enabled", True)),
        "source": str(c.get("source") or "bottom"),
        "position": str(c.get("position") or "bottom"),
        "text_color": str(c.get("textColor") or "#FFFFFF"),
        "stroke_color": str(c.get("strokeColor") or "#000000"),
        "stroke_width": int(c.get("strokeWidth") or 0),
        "font_size": int(c.get("fontSize") or 0),
        "uppercase": bool(c.get("uppercase", True)),
        "phrases": str(c.get("phrases") or ""),
        "text_source": str(c.get("textSource") or "titles"),
    }


def build_opts(s: dict) -> dict:
    from_link = str(s.get("topMode") or "") == "link"
    tops = resolve_tops(s)
    qr_path, qr_text = _qr(s)
    rand_style = bool(s.get("randStyle", True))
    cta_on = bool(s.get("ctaEnabled", True))
    if not cta_on:
        qr_path, qr_text = None, None
    return {
        "tops": tops,
        "top_from_link": from_link,
        "top_url": str(s.get("topUrl") or "").strip() if from_link else "",
        "title_theme": (str(s.get("titleTheme") or "").strip() or "футбол топ момент") if from_link else "",
        "linked_titles_key": str(s.get("linkedKey") or "") if from_link else "",
        "count": max(1, int(s.get("count") or 1)),
        "source_mode": (
            "instagram"
            if str(s.get("sourceMode")) == "instagram"
            else "telegram"
            if str(s.get("sourceMode")) == "telegram"
            else "folder"
        ),
        "instagram": str(s.get("instagram") or "").strip(),
        "cookies_browser": "opera",
        "slogan": None,
        "slogans_text": str(s.get("slogans") or "").strip() if cta_on else "",
        "randomize_slogan": bool(s.get("randSlogan", True)) if cta_on else False,
        "randomize_style": rand_style,
        "randomize_tg_call": bool(s.get("randTg", True)),
        "show_smileys": False,
        "sticker_pack": (str(s.get("stickerUrl") or "").strip() or "https://t.me/addstickers/Buddy_Bear")
        if cta_on and s.get("stickerEnabled")
        else None,
        "sticker_selection": str(s.get("stickerSelection") or "random"),
        "tg_call": str(s.get("tgCalls") or "").strip() if cta_on else "",
        "qr_path": qr_path,
        "qr_text": qr_text,
        "cta_seconds": float(s.get("ctaSec") or 5) if cta_on else 0,
        "cta_enabled": cta_on,
        "cta_style": "random" if rand_style else (str(s.get("ctaStyle") or "random")),
        "banner": _banner(s),
        "do_upload": False,
        "tg_link": str(s.get("qr") or "").strip() or None,
        "cover_style": _cover(s),
        "auto_whisper": bool(s.get("autoWhisper")),
        "asr_model": str(s.get("asrModel") or "small"),
        "use_kie_titles": bool(s.get("useKieTitles")),
        "kie_api_key": str(s.get("kieApiKey") or "").strip() or None,
        "source_note": str(s.get("sourceNote") or "").strip(),
        **_meta_opts(s),
    }


# ---------------------------------------------------------------------------
# генерация (порт ReelsWorker.run без ветки загрузки)
# ---------------------------------------------------------------------------


def _prepare_link_top(opts: dict) -> None:
    from kie_titles import DEFAULT_TITLE_THEME, title_is_unclear, titles_from_source
    from link_top import canonical_video_url, download_linked_video
    from meta import hashtags_from_title, polish_title

    url = canonical_video_url(str(opts.get("top_url") or ""))
    theme = " ".join(str(opts.get("title_theme") or DEFAULT_TITLE_THEME).split()).strip() or DEFAULT_TITLE_THEME
    linked = download_linked_video(url, on_log=log)
    opts["tops"] = [linked.path]
    key = f"{linked.url}|{theme}"
    titles = [str(t).strip() for t in (opts.get("kie_titles") or []) if str(t).strip()]
    if opts.get("linked_titles_key") == key and titles:
        log(f"Заголовок по ссылке уже готов: {titles[0]}")
        opts["phrases"] = titles
        opts["title_base"] = titles[0]
        return
    count = max(1, int(opts.get("count") or 1))
    tags = ""
    try:
        titles, tags, mode = titles_from_source(
            title=linked.title,
            description=linked.description,
            theme=theme,
            count=count,
            api_key=opts.get("kie_api_key"),
            on_log=log,
        )
        log("Kie сама придумала заголовок: исходное название было случайным" if mode == "theme" else "Заголовок по названию шортса")
    except Exception as exc:  # noqa: BLE001
        log(f"Kie по ссылке пропущен: {exc}")
        from kie_titles import is_russian

        base = polish_title(linked.title).upper() if linked.title and not title_is_unclear(linked.title) else theme.upper()
        if not is_russian(base):
            log("Название шортса не на русском — в заголовок беру тему")
            base = theme.upper()
        titles = [base] * count
        tags = " ".join(hashtags_from_title(base))
    if titles:
        opts["phrases"] = titles
        opts["title_base"] = titles[0]
        opts["kie_titles"] = titles
        opts["use_kie_titles"] = True
        opts["linked_titles_key"] = key
    if tags:
        opts["extra_hashtags"] = tags


def _auto_whisper(opts: dict, tops: list[Path]) -> None:
    from meta import hashtags_from_title, polish_title
    from transcribe import build_description_from_transcript, transcribe_in_subprocess

    video = Path(tops[0])
    model = str(opts.get("asr_model") or "small")
    log(f"Авто-Whisper [{model}]: {video.name}")
    text, phrases = transcribe_in_subprocess(video, on_log=log, python_exe=sys.executable, model=model, force=False)
    phrases = [p for p in (phrases or []) if p and str(p).strip()]
    if phrases:
        opts["phrases"] = phrases
        base = polish_title(phrases[0])
        opts["title_base"] = base
        try:
            tags = " ".join(hashtags_from_title(base))
            if tags:
                opts["extra_hashtags"] = tags
        except Exception:
            pass
    if text:
        opts["manual_description"] = build_description_from_transcript(
            text, phrases, tg_link=opts.get("qr_text") or opts.get("tg_link")
        )
    if text:
        opts["transcript_text"] = text
        opts["transcript_video"] = str(video)
    log(f"Авто-Whisper: фраз={len(phrases)}, заголовок={opts.get('title_base') or '—'}")
    if opts.get("use_kie_titles") and text and not str(opts.get("source_note") or "").strip():
        try:
            from kie_titles import titles_with_fallback

            need = max(1, int(opts.get("count") or 1))
            titles, src = titles_with_fallback(
                text, count=need, fallback_phrases=phrases, api_key=opts.get("kie_api_key"), on_log=log
            )
            if titles:
                opts["phrases"] = titles
                opts["title_base"] = titles[0]
                opts["kie_titles"] = titles
                log(f"Kie заголовки ({src}): {len(titles)}")
        except Exception as kie_exc:  # noqa: BLE001
            log(f"Kie пропущен: {kie_exc}")
        from kie_titles import is_russian

        base_now = str(opts.get("title_base") or "")
        theme_now = str(opts.get("title_theme") or "").strip()
        if base_now and not is_russian(base_now) and theme_now and is_russian(theme_now):
            opts["title_base"] = theme_now.upper()
            opts["phrases"] = [theme_now.upper()]
            log("Заголовок был не на русском — беру тему")


def _titles_from_author_note(opts: dict) -> None:
    """Файл из Telegram без названия шортса: Kie пишет заголовок по тексту пользователя."""
    note = str(opts.get("source_note") or "").strip()
    if not note or opts.get("top_from_link") or opts.get("use_custom_meta"):
        return
    speech = str(opts.get("transcript_text") or "").strip()
    description = note if not speech else f"{note}\n\nРечь в ролике:\n{speech[:1800]}"
    opts["transcript_text"] = description
    opts["manual_description"] = note
    if not opts.get("use_kie_titles"):
        log("Описание из Telegram есть, Kie выключена — кладу его в текст ролика")
        return
    count = max(1, int(opts.get("count") or 1))
    try:
        from kie_titles import titles_from_source

        titles, tags, _mode = titles_from_source(
            title="",
            description=description,
            theme=note,
            count=count,
            api_key=opts.get("kie_api_key"),
            on_log=log,
        )
        if titles:
            opts["phrases"] = titles
            opts["title_base"] = titles[0]
            opts["kie_titles"] = titles
            opts["use_kie_titles"] = True
            log(f"Kie по описанию из Telegram: {titles[0]}")
        if tags:
            opts["extra_hashtags"] = tags
    except Exception as exc:  # noqa: BLE001
        log(f"Kie по описанию пропущен: {exc}")
        from kie_titles import is_russian

        if is_russian(note):
            base = " ".join(note.split()).upper()[:110]
            opts["title_base"] = base
            opts["phrases"] = [base]
            log("В заголовок беру само описание из Telegram")


def _stage(
    files: list[Path],
    opts: dict,
    cover_style: dict,
    cover_bottom_map: dict[str, str] | None,
    cover_top_map: dict[str, str] | None = None,
) -> list[dict]:
    from upload_bridge import stage_reels_for_upload

    staged = stage_reels_for_upload(
        files,
        tg_link=opts.get("qr_text") or opts.get("tg_link"),
        title_base=opts.get("title_base"),
        triggers_text=opts.get("triggers_text"),
        phrases=opts.get("phrases") or None,
        desc_hooks_text=opts.get("desc_hooks_text"),
        desc_template=opts.get("desc_template"),
        manual_description=opts.get("manual_description"),
        extra_hashtags=opts.get("extra_hashtags"),
        permanent_hashtags=opts.get("permanent_hashtags"),
        use_custom_meta=bool(opts.get("use_custom_meta")),
        custom_titles=opts.get("custom_titles"),
        custom_descriptions=opts.get("custom_descriptions"),
        apply_triggers=bool(opts.get("apply_triggers", True)),
        cover_style=cover_style,
        cover_bottom_map=cover_bottom_map,
        cover_top_map=cover_top_map,
        on_log=log,
    )
    items = []
    for it in staged:
        items.append(
            {
                "video": it.get("RELS") or it.get("VIDEO") or "",
                "cover": it.get("PHOTO") or "",
                "title": it.get("LIVE_TITLE") or "",
                "description": it.get("YT_DESC") or it.get("YOUTUBE_DESC") or "",
                "hashtags": it.get("hashtags") or "",
                "source": it.get("source") or "",
                "uid": it.get("uid") or "",
                "coverFrom": it.get("cover_from") or "",
            }
        )
    return items


def _install_split_cover() -> None:
    """Обложка из двух половин: верх кадра — видео 1, низ кадра — видео 2."""
    import cover

    if getattr(cover, "_split_installed", False):
        return
    orig = cover.make_cover_for_reel

    def wrapped(output_reel, out_jpg, style, *, top_hint=None, bottom_hint=None, phrase=None, rng=None, on_log=None):
        if str(getattr(style, "source", "") or "").lower() != "split":
            return orig(
                output_reel,
                out_jpg,
                style,
                top_hint=top_hint,
                bottom_hint=bottom_hint,
                phrase=phrase,
                rng=rng,
                on_log=on_log,
            )
        top = cover.resolve_source_video(output_reel, "top", top_hint=top_hint, bottom_hint=bottom_hint)
        bottom = cover.resolve_source_video(output_reel, "bottom", top_hint=top_hint, bottom_hint=bottom_hint)
        if on_log:
            on_log(
                "Обложка из двух частей: "
                + (Path(top).name if top else "—")
                + " + "
                + (Path(bottom).name if bottom else "—")
            )
        return _split_canvas(top, bottom, style, phrase, out_jpg)

    cover.make_cover_for_reel = wrapped
    cover._split_installed = True


def _split_canvas(top, bottom, style, phrase, out_path):
    import random

    from PIL import Image
    from cover import (
        REEL_H,
        REEL_W,
        _fit_cover_canvas,
        draw_cover_text,
        extract_frame,
        pick_cover_time,
        placeholder_frame,
        video_duration,
    )

    def frame(video):
        if not video or not Path(video).is_file():
            return None
        dur = video_duration(Path(video))
        tmp = Path(out_path).with_suffix(".split.jpg")
        extract_frame(Path(video), pick_cover_time(dur, random.Random(str(video))), tmp)
        try:
            img = Image.open(tmp).convert("RGB")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return _fit_cover_canvas(img)

    top_img = frame(top)
    bot_img = frame(bottom)
    if top_img is None and bot_img is None:
        canvas = placeholder_frame(note="Нет двух видео для обложки")
    else:
        top_img = top_img or bot_img
        bot_img = bot_img or top_img
        half = REEL_H // 2
        canvas = Image.new("RGB", (REEL_W, REEL_H))
        canvas.paste(top_img.crop((0, 0, REEL_W, half)), (0, 0))
        canvas.paste(bot_img.crop((0, REEL_H - half, REEL_W, REEL_H)), (0, half))
    result = draw_cover_text(canvas, phrase or "", style)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    result.save(out_path, quality=92, optimize=True)
    return Path(out_path)


def _pin_bottom(bottom_file: str, bottom_url: str) -> Path | None:
    """Нижний ролик, который пользователь прислал боту: файл или ссылка YouTube/Instagram."""
    if bottom_url:
        from link_top import canonical_video_url, download_linked_video

        url = canonical_video_url(bottom_url)
        if not url:
            raise RuntimeError("Нижняя ссылка должна вести на YouTube или Instagram")
        linked = download_linked_video(url, on_log=log)
        path = Path(getattr(linked, "path", "") or "")
        if not path.is_file():
            raise RuntimeError("Нижний ролик по ссылке не скачался")
        return path
    if bottom_file:
        path = Path(bottom_file)
        if not path.is_file():
            raise RuntimeError("Файл нижнего ролика не найден")
        return path
    return None


def _flag(s: dict, key: str, default: bool) -> bool:
    raw = s.get(key)
    if raw is None:
        return default
    return bool(raw)


def _audio_mix(s: dict) -> int:
    raw = s.get("audioMix")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 100
    return max(0, min(100, value))


def cmd_generate(args: argparse.Namespace) -> int:
    setup_engine_paths()
    _install_split_cover()
    from engine import allocate_bottoms_for_tops, ensure_dirs, ffmpeg_ok, generate_batch, generate_mass, list_videos

    if not ffmpeg_ok():
        return fail("FFmpeg / ffprobe не найдены в PATH")
    ensure_dirs()
    s = load_opts(args.opts)
    opts = build_opts(s)
    if not opts.get("cta_enabled", True):
        import cta_anim

        cta_anim.resolve_slogan = lambda *_a, **_k: None  # type: ignore[method-assign]
        opts["qr_path"] = None
        opts["qr_text"] = None
        opts["slogans_text"] = ""
        log("Призыв CTA выключен")

    # только подготовить готовые файлы (обложки + тексты), без генерации
    files_only = [Path(p) for p in (s.get("files") or []) if str(p).strip()]
    if files_only:
        files_only = [p for p in files_only if p.is_file()]
        if not files_only:
            return fail("Нет выбранных файлов")
        log(f"Подготовка готовых роликов: {len(files_only)}")
        progress(0.1)
        items = _stage(files_only, opts, dict(opts.get("cover_style") or {}), None)
        progress(1.0)
        result({"ok": len(items), "total": len(files_only), "items": items, "files": [str(p) for p in files_only]})
        return 0

    if opts.get("top_from_link"):
        if not opts.get("top_url"):
            return fail("Вставьте ссылку на ролик YouTube или Instagram")
        _prepare_link_top(opts)

    tops = [Path(p) for p in opts["tops"]]
    if str(s.get("topMode") or "") == "telegram" and not tops:
        return fail("Верхний ролик приходит из Telegram: пришлите боту ссылку или видео")
    if not tops:
        return fail("Добавьте видео в папку 1 / выберите верхний ролик")
    batch = max(1, int(opts["count"]))
    mode = opts["source_mode"]
    log(f"Генерация: {batch} роликов по отмеченным аккаунтам, верхних источников={len(tops)}")
    progress(0.02)

    if opts.get("auto_whisper") and not opts.get("use_custom_meta") and not opts.get("top_from_link"):
        try:
            _auto_whisper(opts, tops)
        except Exception as exc:  # noqa: BLE001
            log(f"Авто-Whisper пропущен: {exc}")
        progress(0.05)

    if str(opts.get("source_note") or "").strip() and not opts.get("top_from_link"):
        _titles_from_author_note(opts)

    try:
        pinned = _pin_bottom(str(s.get("bottomFile") or "").strip(), str(s.get("bottomUrl") or "").strip())
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))

    if pinned is not None:
        flat_bottoms = [pinned] * batch
        log(f"Нижний ролик задан: {pinned.name}")
    elif mode == "telegram":
        return fail("Нижний ролик приходит из Telegram: пришлите боту ссылку, видео или кружок")
    elif mode == "folder":
        from engine import FOLDER_2

        pool = list_videos(FOLDER_2)
        if not pool:
            return fail("Папка 2 пуста — добавьте видео или включите Instagram")
        flat_bottoms = allocate_bottoms_for_tops(1, batch, pool)[0]
    else:
        from instagram_source import resolve_bottom_videos

        log("Instagram: скачиваю ролики для низа…")
        flat_bottoms = resolve_bottom_videos(
            "instagram",
            batch,
            instagram=opts.get("instagram") or None,
            cookies_from_browser=opts.get("cookies_browser") or "opera",
            cookies_file=None,
            on_log=log,
        )
        if not flat_bottoms:
            return fail("Instagram: не удалось скачать ни одного ролика")
        if len(flat_bottoms) < batch:
            padded = list(flat_bottoms)
            i = 0
            while len(padded) < batch:
                padded.append(flat_bottoms[i % len(flat_bottoms)])
                i += 1
            flat_bottoms = padded
        flat_bottoms = list(flat_bottoms)[:batch]
        log(f"Instagram: готово {len(flat_bottoms)} роликов → папка 2")

    groups: dict[Path, list[Path]] = {}
    order: list[Path] = []
    for index, bottom in enumerate(flat_bottoms[:batch]):
        top = tops[index % len(tops)]
        if top not in groups:
            groups[top] = []
            order.append(top)
        groups[top].append(bottom)
    use_tops = order
    bottoms_per_top = [groups[top] for top in use_tops]

    def on_progress(p: float) -> None:
        progress(max(0.05, min(0.88, float(p) * 0.85)))

    common = dict(
        slogan=opts.get("slogan"),
        qr_path=opts.get("qr_path"),
        qr_text=opts.get("qr_text"),
        cta_seconds=float(opts.get("cta_seconds") or 5),
        cta_style=opts.get("cta_style") or "random",
        slogans_text=opts.get("slogans_text"),
        randomize_slogan=bool(opts.get("randomize_slogan", True)),
        randomize_style=bool(opts.get("randomize_style", True)),
        tg_call=opts.get("tg_call"),
        randomize_tg_call=bool(opts.get("randomize_tg_call", True)),
        show_smileys=False,
        sticker_pack=opts.get("sticker_pack"),
        sticker_selection=opts.get("sticker_selection") or "random",
        banner=opts.get("banner") or None,
        audio_mix=_audio_mix(s),
        bottom_circle=_flag(s, "bottomCircle", True),
        captions=_flag(s, "captions", True),
        asr_model=str(s.get("asrModel") or "small"),
        circle_place=str(s.get("circlePlace") or "center"),
        caption_style=s.get("captionStyle") if isinstance(s.get("captionStyle"), dict) else None,
        on_log=log,
        on_progress=on_progress,
    )
    b = opts.get("banner") or {}
    if b.get("enabled"):
        place = {"mid": "первый на паузе", "end": "второй в конце", "both": "оба"}.get(str(b.get("place") or "mid"), "первый на паузе")
        log(
            f"Баннер CTA: {place}, {float(b.get('duration') or 0):.1f} с, стиль={b.get('style') or 'random'}"
            + (f", источник: {b.get('source')}" if b.get("source") else "")
            + (", после паузы только верх" if b.get("drop_bottom") else "")
            + (f", аудио={Path(b['audio']).name}" if b.get("audio") else "")
        )

    if len(use_tops) == 1:
        ok, total, files = generate_batch(use_tops[0], bottoms_per_top[0], **common)
    else:
        ok, total, files = generate_mass(use_tops, bottoms_per_top, **common)
    log(f"Сгенерировано: {ok}/{total}")
    progress(0.9)

    cover_bottom_map: dict[str, str] = {}
    cover_top_map: dict[str, str] = {}
    try:
        from engine import safe_stem

        by_bot: dict[str, Path] = {}
        by_top: dict[str, Path] = {}
        for top in use_tops:
            by_top[safe_stem(Path(top).stem)] = Path(top)
        for bottoms in bottoms_per_top:
            for bot in bottoms:
                by_bot[safe_stem(Path(bot).stem)] = Path(bot)
        for out_path in files or []:
            resolved = str(Path(out_path).resolve())
            parts = Path(out_path).stem.split("__")
            if parts:
                top = by_top.get(parts[0])
                if top and top.is_file():
                    cover_top_map[resolved] = str(top.resolve())
            if len(parts) < 2:
                continue
            bot = by_bot.get(parts[1])
            if bot and bot.is_file():
                cover_bottom_map[resolved] = str(bot.resolve())
        log(f"Обложки: верхних {len(cover_top_map)}, нижних {len(cover_bottom_map)}")
    except Exception as map_exc:  # noqa: BLE001
        log(f"Обложки: карта роликов не собрана ({map_exc}) — найду по имени файла")

    cover_style = dict(opts.get("cover_style") or {})
    chosen = str(cover_style.get("source") or "").strip().lower()
    if chosen not in {"top", "bottom", "split"}:
        cover_style["source"] = "bottom"
        chosen = "bottom"
    source_label = {"top": "верхнего ролика", "split": "двух частей", "bottom": "нижнего ролика"}[chosen]
    log(f"Обложка: кадр из {source_label}")

    items: list[dict] = []
    if files:
        items = _stage([Path(f) for f in files], opts, cover_style, cover_bottom_map, cover_top_map)
    progress(1.0)
    result(
        {
            "ok": int(ok),
            "total": int(total),
            "items": items,
            "files": [str(f) for f in (files or [])],
            "titleBase": opts.get("title_base") or "",
            "phrases": list(opts.get("phrases") or []),
            "kieTitles": list(opts.get("kie_titles") or []),
            "hashtags": opts.get("extra_hashtags") or "",
            "description": opts.get("manual_description") or "",
            "linkedPath": str(opts["tops"][0]) if opts.get("top_from_link") and opts.get("tops") else "",
            "linkedKey": opts.get("linked_titles_key") or "",
            "transcript": opts.get("transcript_text") or "",
            "transcriptVideo": opts.get("transcript_video") or "",
        }
    )
    return 0


# ---------------------------------------------------------------------------
# вспомогательные команды
# ---------------------------------------------------------------------------


def cmd_info(_args: argparse.Namespace) -> int:
    setup_engine_paths()
    from banner_cta import list_banner_styles
    from cover import DEFAULT_PHRASES
    from cta_anim import DEFAULT_SLOGANS, DEFAULT_TG_CALLS, list_cta_styles
    from engine import FOLDER_1, FOLDER_2, OUTPUT, ensure_dirs, ffmpeg_ok, list_videos
    from meta import DEFAULT_TRIGGERS
    from upload_bridge import UPLOAD_STAGING

    ensure_dirs()
    outputs = sorted(list_videos(OUTPUT), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:60]
    result(
        {
            "folder1": str(FOLDER_1),
            "folder2": str(FOLDER_2),
            "output": str(OUTPUT),
            "uploadQueue": str(UPLOAD_STAGING),
            "tops": [_file_info(p) for p in list_videos(FOLDER_1)],
            "bottoms": [_file_info(p) for p in list_videos(FOLDER_2)],
            "outputs": [_file_info(p) for p in outputs],
            "ctaStyles": [{"id": st.id, "title": st.title} for st in list_cta_styles()],
            "bannerStyles": [{"id": st.id, "title": st.title} for st in list_banner_styles()],
            "defaultSlogans": list(DEFAULT_SLOGANS),
            "defaultTgCalls": list(DEFAULT_TG_CALLS),
            "defaultCoverPhrases": list(DEFAULT_PHRASES),
            "defaultTriggers": list(DEFAULT_TRIGGERS),
            "ffmpeg": bool(ffmpeg_ok()),
        }
    )
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    setup_engine_paths()
    from transcribe import transcribe_in_subprocess

    s = load_opts(args.opts)
    video = str(s.get("video") or "")
    tops = [Path(video)] if video and Path(video).is_file() else resolve_tops(s)
    if not tops:
        return fail("Нет верхнего ролика для распознавания")
    model = str(s.get("asrModel") or "small")
    log(f"Whisper [{model}]: {tops[0].name}")
    text, phrases = transcribe_in_subprocess(
        tops[0], on_log=log, python_exe=sys.executable, model=model, force=bool(s.get("force"))
    )
    result({"text": text or "", "phrases": [p for p in (phrases or []) if str(p).strip()], "video": str(tops[0])})
    return 0


def cmd_kie_titles(args: argparse.Namespace) -> int:
    setup_engine_paths()
    from kie_titles import titles_with_fallback

    s = load_opts(args.opts)
    transcript = str(s.get("transcript") or "").strip()
    if not transcript:
        return fail("Сначала распознайте речь (Whisper) — Kie работает по транскрипту")
    count = max(1, int(s.get("count") or 1))
    fallback = [p for p in (s.get("phrasesChecked") or s.get("phrases") or []) if str(p).strip()]
    titles, source = titles_with_fallback(
        transcript, count=max(count, 3), fallback_phrases=fallback, api_key=str(s.get("kieApiKey") or "") or None, on_log=log
    )
    result({"titles": list(titles or []), "source": source})
    return 0


def cmd_link_top(args: argparse.Namespace) -> int:
    setup_engine_paths()
    from kie_titles import DEFAULT_TITLE_THEME, titles_from_source
    from link_top import canonical_video_url, classify_video_url, download_linked_video

    s = load_opts(args.opts)
    url = str(s.get("topUrl") or "").strip()
    if not classify_video_url(url):
        return fail("Вставьте ссылку на ролик YouTube или Instagram")
    theme = str(s.get("titleTheme") or "").strip() or DEFAULT_TITLE_THEME
    count = max(1, int(s.get("count") or 1))
    linked = download_linked_video(url, on_log=log)
    titles, tags, mode = [], "", "none"
    try:
        titles, tags, mode = titles_from_source(
            title=linked.title,
            description=linked.description,
            theme=theme,
            count=count,
            api_key=str(s.get("kieApiKey") or "") or None,
            on_log=log,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"Kie по ссылке пропущен: {exc}")
    result(
        {
            "path": str(linked.path),
            "url": linked.url,
            "title": linked.title,
            "description": linked.description,
            "titles": list(titles or []),
            "tags": tags or "",
            "mode": mode,
            "theme": theme,
            "key": f"{canonical_video_url(url)}|{theme}",
        }
    )
    return 0


def cmd_stickers(args: argparse.Namespace) -> int:
    setup_engine_paths()
    from stickers import fetch_sticker_pack

    s = load_opts(args.opts)
    url = str(s.get("stickerUrl") or "").strip() or "https://t.me/addstickers/Buddy_Bear"
    pack = fetch_sticker_pack(url, on_log=log, force=bool(s.get("force")))
    result(
        {
            "name": pack.name,
            "title": pack.title,
            "count": len(pack.stickers),
            "stickers": [
                {
                    "index": st.index,
                    "emoji": st.emoji or "",
                    "label": st.label,
                    "thumb": str(st.thumb_path) if st.thumb_path and Path(st.thumb_path).is_file() else "",
                }
                for st in pack.stickers
            ],
        }
    )
    return 0


def cmd_preview_cta(args: argparse.Namespace) -> int:
    setup_engine_paths()
    from cta_anim import resolve_slogan, resolve_tg_call
    from engine import QR_DIR, create_cta_frame

    s = load_opts(args.opts)
    slogan = resolve_slogan(None, slogans_text=str(s.get("slogans") or ""), randomize=bool(s.get("randSlogan", True))) or "Ваш слоган"
    tg_call = resolve_tg_call(str(s.get("tgCalls") or ""), randomize=bool(s.get("randTg", True)))
    qr_path, qr_text = _qr(s)
    if not qr_path and not qr_text:
        qr_text = "https://t.me/example"
    style = "random" if s.get("randStyle", True) else (str(s.get("ctaStyle") or "random"))
    frames = None
    if s.get("stickerEnabled"):
        try:
            from stickers import load_sticker_frames_for_cta

            frames = load_sticker_frames_for_cta(
                str(s.get("stickerUrl") or "") or "https://t.me/addstickers/Buddy_Bear",
                str(s.get("stickerSelection") or "random"),
                on_log=log,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"Стикер для превью не загружен: {exc}")
    QR_DIR.mkdir(parents=True, exist_ok=True)
    out = QR_DIR / "cta_preview_electron.png"
    create_cta_frame(
        slogan,
        qr_path,
        qr_text,
        out,
        duration=float(s.get("ctaSec") or 5),
        style=style,
        tg_call=tg_call,
        show_smileys=False,
        sticker_frames=frames,
    )
    result({"image": str(out), "slogan": slogan, "tgCall": tg_call})
    return 0


def cmd_preview_banner(args: argparse.Namespace) -> int:
    setup_engine_paths()
    import subprocess

    from banner_cta import create_banner_preview, default_banner_at, resolve_banner_text
    from engine import QR_DIR, probe_duration

    s = load_opts(args.opts)
    b = _banner(s)
    text = resolve_banner_text(b.get("text"), randomize=False)
    background = None
    pause_at = 10.0
    try:
        tops = resolve_tops(s)
    except Exception:
        tops = []
    QR_DIR.mkdir(parents=True, exist_ok=True)
    if tops:
        try:
            top_dur = probe_duration(Path(tops[0]))
        except Exception:
            top_dur = 0.0
        if b.get("place") == "end":
            pause_at = max(0.0, top_dur - 0.15)
        elif top_dur > 0:
            pause_at = default_banner_at(top_dur)
        frame_png = QR_DIR / "banner_preview_frame_electron.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{pause_at:.2f}", "-i", str(tops[0]), "-frames:v", "1", str(frame_png)],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if frame_png.is_file():
            background = frame_png
    out = QR_DIR / "banner_preview_electron.png"
    create_banner_preview(
        text,
        out,
        style=b.get("style") or "random",
        duration=float(b.get("duration") or 4.0),
        background=background,
        source=b.get("source") or None,
    )
    result({"image": str(out), "pauseAt": round(pause_at, 1), "text": text})
    return 0


def cmd_preview_cover(args: argparse.Namespace) -> int:
    setup_engine_paths()
    _install_split_cover()
    from cover import COVER_DIR, CoverStyle, render_cover
    from engine import FOLDER_1, FOLDER_2, list_videos

    s = load_opts(args.opts)
    style = CoverStyle.from_dict(_cover(s))
    if not style.enabled:
        result({"image": "", "video": "", "phrase": "", "disabled": True})
        return 0
    video = None
    tops = []
    bottoms = list_videos(FOLDER_2)
    if style.source == "bottom":
        video = bottoms[0] if bottoms else None
    elif str(style.source).lower() == "split":
        try:
            tops = resolve_tops(s)
        except Exception:
            tops = list_videos(FOLDER_1)
        video = tops[0] if tops else None
    else:
        tops = resolve_tops(s)
        video = tops[0] if tops else (list_videos(FOLDER_1) or [None])[0]
    if str(getattr(style, "text_source", "titles")).lower() in {"templates", "template", "phrases"}:
        phrase = style.pick_phrase()
    else:
        phrase = str(s.get("titleBase") or "").strip()
        if not phrase:
            kt = [t for t in (s.get("kieTitlesChecked") or s.get("kieTitles") or []) if str(t).strip()]
            phrase = kt[0] if kt else ""
        if not phrase:
            pc = [t for t in (s.get("phrasesChecked") or s.get("phrases") or []) if str(t).strip()]
            phrase = pc[0] if pc else style.pick_phrase()
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    out = COVER_DIR / "cover_preview_electron.jpg"
    if str(style.source).lower() == "split":
        _split_canvas(video, bottoms[0] if bottoms else None, style, phrase, out)
    else:
        render_cover(video=video, out_path=out, style=style, phrase=phrase, at_sec=4.5 if video else None)
    result({"image": str(out), "video": str(video) if video else "", "phrase": phrase})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Мост генератора рилсов")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (
        ("info", cmd_info),
        ("generate", cmd_generate),
        ("transcribe", cmd_transcribe),
        ("kie-titles", cmd_kie_titles),
        ("link-top", cmd_link_top),
        ("stickers", cmd_stickers),
        ("preview-cta", cmd_preview_cta),
        ("preview-banner", cmd_preview_banner),
        ("preview-cover", cmd_preview_cover),
    ):
        p = sub.add_parser(name)
        p.add_argument("--opts", default=None, help="JSON-файл с настройками мастера")
        p.set_defaults(fn=fn)
    args = parser.parse_args()
    try:
        return int(args.fn(args) or 0)
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        return fail(str(exc))


if __name__ == "__main__":
    run_main(main)
