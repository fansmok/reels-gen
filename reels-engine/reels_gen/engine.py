"""
Ядро генератора двойных рилсов.
Верх — видео из папки 1, низ — зацикленное из папки 2,
последние N сек низа — чёрный экран с QR и слоганом.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FOLDER_1 = ROOT / "1"
FOLDER_2 = ROOT / "2"
OUTPUT = ROOT / "output"
ASSETS = ROOT / "assets"
QR_DIR = ASSETS / "qr"
FONTS_DIR = ASSETS / "fonts"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
REEL_W, REEL_H = 1080, 1920
HALF_H = REEL_H // 2
CTA_SEC = 5.0
FPS = 30

BG = (0, 0, 0)
FG = (255, 255, 255)
ACCENT = (245, 245, 245)
LINE = (90, 90, 90)

ProgressCb = Callable[[str], None]


def _win_no_window_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        **_win_no_window_kwargs(),
    )


def ensure_dirs() -> None:
    for path in (FOLDER_1, FOLDER_2, OUTPUT, QR_DIR, FONTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def list_videos(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = run_cmd(cmd)
    data = json.loads(result.stdout or "{}")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError(f"Нулевая длительность: {path.name}")
    return duration


def probe_has_audio(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
    ]
    result = run_cmd(cmd, check=False)
    return bool((result.stdout or "").strip())


def pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[Path] = []
    if bold:
        candidates.extend(
            [
                FONTS_DIR / "Montserrat-SemiBold.ttf",
                FONTS_DIR / "Inter-SemiBold.ttf",
                Path(r"C:\Windows\Fonts\segoeuib.ttf"),
                Path(r"C:\Windows\Fonts\arialbd.ttf"),
                Path(r"C:\Windows\Fonts\calibrib.ttf"),
            ]
        )
    else:
        candidates.extend(
            [
                FONTS_DIR / "Montserrat-Regular.ttf",
                FONTS_DIR / "Inter-Regular.ttf",
                Path(r"C:\Windows\Fonts\segoeui.ttf"),
                Path(r"C:\Windows\Fonts\arial.ttf"),
                Path(r"C:\Windows\Fonts\calibri.ttf"),
            ]
        )
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap_text(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def make_qr_image(data: str, box_size: int = 12, border: int = 2) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def load_or_create_qr(
    qr_path: Path | None,
    qr_text: str | None,
    size: int = 340,
) -> Image.Image | None:
    if qr_path and qr_path.exists():
        img = Image.open(qr_path).convert("RGB")
    elif qr_text:
        img = make_qr_image(qr_text)
    else:
        return None

    pad = 18
    card = Image.new("RGB", (img.width + pad * 2, img.height + pad * 2), FG)
    card.paste(img, (pad, pad))
    return card.resize((size, size), Image.Resampling.LANCZOS)


def create_cta_frame(
    slogan: str | None,
    qr_path: Path | None,
    qr_text: str | None,
    out_path: Path,
    duration: float = CTA_SEC,
    style: str | None = None,
    tg_call: str | None = None,
    show_smileys: bool = True,
    sticker_frames=None,
) -> Path:
    """Превью-кадр анимированного CTA (для GUI)."""
    from cta_anim import create_cta_preview

    return create_cta_preview(
        slogan,
        qr_path,
        qr_text,
        out_path,
        duration=duration,
        style=style,
        tg_call=tg_call,
        show_smileys=show_smileys,
        sticker_frames=sticker_frames,
    )


CIRCLE_D = int(REEL_H * 0.20)
CIRCLE_MARGIN = 46
CIRCLE_RING = 16


def _write_circle_disc(path: Path, outer: int) -> None:
    img = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, outer - 1, outer - 1), fill=(255, 255, 255, 255))
    img.save(path)


def _write_circle_mask(path: Path, size: int) -> None:
    img = Image.new("L", (size, size), 0)
    ImageDraw.Draw(img).ellipse((1, 1, size - 2, size - 2), fill=255)
    img.save(path)


def _ffmpeg_filter_path(path: Path) -> str:
    text = path.resolve().as_posix().replace("'", "\\'")
    return text.replace(":", "\\:")


def _ass_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _caption_groups(words: list[dict]) -> list[tuple[float, float, str]]:
    cleaned: list[dict] = []
    for word in words:
        text = re.sub(r"\s+", "", str(word.get("t") or ""))
        text = text.strip(".,!?;:…\"'«»()[]")
        if not text:
            continue
        cleaned.append({"s": float(word.get("s") or 0), "e": float(word.get("e") or 0), "t": text})
    groups: list[tuple[float, float, str]] = []
    i = 0
    while i < len(cleaned):
        cur = cleaned[i]
        nxt = cleaned[i + 1] if i + 1 < len(cleaned) else None
        pair = bool(
            nxt
            and (nxt["s"] - cur["e"]) <= 0.42
            and len(cur["t"]) <= 12
            and len(nxt["t"]) <= 12
        )
        chunk = [cur, nxt] if pair and nxt else [cur]
        start = chunk[0]["s"]
        end = max(chunk[-1]["e"], start + 0.28)
        nxt_i = i + len(chunk)
        if nxt_i < len(cleaned):
            end = min(end, cleaned[nxt_i]["s"] - 0.02)
        groups.append((start, max(end, start + 0.22), " ".join(str(c["t"]) for c in chunk)))
        i = nxt_i
    return groups


def _repeat_words(words: list[dict], media_dur: float, total: float) -> list[dict]:
    cleaned: list[dict] = []
    for word in words:
        text = re.sub(r"\s+", " ", str(word.get("t") or "")).strip()
        if not text:
            continue
        start = float(word.get("s") or 0)
        end = max(float(word.get("e") or 0), start + 0.12)
        cleaned.append({"word": text, "start": round(start, 3), "end": round(end, 3)})
    if not cleaned:
        return []
    if media_dur <= 0.3 or media_dur >= total - 0.05:
        return [item for item in cleaned if item["start"] < total]
    out: list[dict] = []
    shift = 0.0
    while shift < total - 0.05:
        for item in cleaned:
            start = float(item["start"]) + shift
            if start >= total:
                break
            out.append(
                {
                    "word": item["word"],
                    "start": round(start, 3),
                    "end": round(min(total, float(item["end"]) + shift), 3),
                }
            )
        shift += media_dur
    return out


_CAPTION_PRESETS = {"karaoke", "kinetic", "pill", "weight", "neon", "editorial"}


def _hex_color(color: str, fallback: str) -> str:
    raw = str(color or "").strip()
    if not raw.startswith("#"):
        raw = "#" + raw
    if len(raw) == 7 and all(ch in "0123456789abcdefABCDEF" for ch in raw[1:]):
        return raw.upper()
    return fallback


def _render_caption_overlay(
    words: list[dict],
    style: dict | None,
    total: float,
    above_circle: bool,
    tmp_dir: Path,
    log: Callable[[str], None],
) -> Path | None:
    """Прозрачный WebM со стилями remotion-captions-kit. None — рисуем обычные субтитры."""
    script = os.environ.get("REELS_CAPTION_SCRIPT", "")
    exe = os.environ.get("REELS_ELECTRON_EXEC", "")
    bundle = os.environ.get("REELS_CAPTION_BUNDLE", "")
    if not script or not exe or not bundle or not Path(script).is_file() or not Path(bundle).is_dir():
        log("Анимированные субтитры недоступны — оставляю обычные")
        return None
    look = _caption_look(style)
    raw = style or {}
    preset = str(raw.get("preset") or "kinetic")
    if preset not in _CAPTION_PRESETS:
        preset = "kinetic"
    props_path = tmp_dir / "caption-props.json"
    out = tmp_dir / "captions.webm"
    props_path.write_text(
        json.dumps(
            {
                "words": words,
                "preset": preset,
                "uppercase": look["upper"],
                "duration": round(total, 3),
                "maxCharsPerPage": 18,
                "minWordsPerPage": 1,
                "maxDurationMs": 800,
                "theme": {
                    "fontFamily": look["font"],
                    "fontSize": look["size"],
                    "textColor": _hex_color(str(raw.get("color") or ""), "#FFFFFF"),
                    "activeColor": _hex_color(str(raw.get("activeColor") or ""), "#FFE14A"),
                    "pillColor": "#141414",
                    "position": "bottom",
                    "edgeOffset": 0.3 if above_circle else 0.12,
                    "maxWidth": 0.92,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        proc = subprocess.Popen(
            [exe, script, str(props_path), str(out), bundle],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_win_no_window_kwargs(),
        )
    except OSError as exc:
        log(f"Анимированные субтитры не запустились: {exc}")
        return None

    def _drain() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            text = line.strip()
            if text:
                log(text)

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=1200)
    except subprocess.TimeoutExpired:
        proc.kill()
        log("Анимированные субтитры слишком долго рисуются — оставляю обычные")
        return None
    reader.join(timeout=2)
    if code != 0 or not out.is_file() or out.stat().st_size < 1000:
        log("Анимированные субтитры не собрались — оставляю обычные")
        return None
    return out


def _repeat_groups(groups: list[tuple[float, float, str]], media_dur: float, total: float) -> list[tuple[float, float, str]]:
    if not groups or media_dur <= 0.3:
        return [(s, min(e, total), t) for s, e, t in groups if s < total]
    out: list[tuple[float, float, str]] = []
    shift = 0.0
    while shift < total - 0.05:
        for start, end, text in groups:
            s = start + shift
            if s >= total:
                break
            out.append((s, min(total, end + shift), text))
        shift += media_dur
    return out


_CAPTION_FONTS = {"Arial Black", "Impact", "Arial", "Georgia", "Comic Sans MS", "Times New Roman"}
_CIRCLE_PLACES = ("left", "center", "right")
_CIRCLE_PLACE_RU = {"left": "слева", "center": "по центру", "right": "справа"}


def _resolve_circle_place(place: str) -> str:
    raw = str(place or "center").strip().lower()
    if raw == "random":
        return random.choice(_CIRCLE_PLACES)
    return raw if raw in _CIRCLE_PLACES else "center"


def _circle_x(place: str) -> str:
    if place == "left":
        return str(CIRCLE_MARGIN)
    if place == "right":
        return f"W-w-{CIRCLE_MARGIN}"
    return "(W-w)/2"


def _ass_bgr(color: str, fallback: str) -> str:
    raw = str(color or "").strip().lstrip("#")
    if len(raw) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in raw):
        raw = fallback
    red, green, blue = raw[0:2], raw[2:4], raw[4:6]
    return f"&H00{blue}{green}{red}".upper()


def _caption_look(style: dict | None) -> dict:
    raw = style or {}
    font = str(raw.get("font") or "Arial Black")
    if font not in _CAPTION_FONTS:
        font = "Arial Black"
    try:
        size = int(raw.get("fontSize") or 82)
    except (TypeError, ValueError):
        size = 82
    try:
        outline = int(8 if raw.get("outline") is None else raw.get("outline"))
    except (TypeError, ValueError):
        outline = 8
    return {
        "font": font,
        "size": max(36, min(160, size)),
        "color": _ass_bgr(str(raw.get("color") or ""), "FFFFFF"),
        "outline_color": _ass_bgr(str(raw.get("outlineColor") or ""), "000000"),
        "outline": max(0, min(20, outline)),
        "bold": -1 if raw.get("bold", True) else 0,
        "italic": -1 if bool(raw.get("italic")) else 0,
        "upper": bool(raw.get("uppercase", True)),
    }


def _write_caption_ass(path: Path, groups: list[tuple[float, float, str]], *, margin_v: int, style: dict | None = None) -> None:
    look = _caption_look(style)
    events = []
    for start, end, text in groups:
        safe = text.replace("\\", "").replace("{", "").replace("}", "")
        if look["upper"]:
            safe = safe.upper()
        if not safe.strip():
            continue
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{safe}")
    body = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            (
                f"Style: Cap,{look['font']},{look['size']},{look['color']},&H000000FF,{look['outline_color']},"
                f"&H64000000,{look['bold']},{look['italic']},0,0,100,100,0,0,1,{look['outline']},2,2,48,48,{margin_v},1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")


def scale_crop_filter(label_in: str, label_out: str) -> str:
    return (
        f"[{label_in}]scale={REEL_W}:{HALF_H}:force_original_aspect_ratio=increase,"
        f"crop={REEL_W}:{HALF_H},setsar=1,fps={FPS},format=yuv420p,"
        f"settb=AVTB,setpts=PTS-STARTPTS[{label_out}]"
    )


def safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE)
    return cleaned.strip("_")[:60] or "reel"


def resolve_qr(qr_arg: str | None) -> tuple[Path | None, str | None]:
    if not qr_arg:
        return None, None
    raw = qr_arg.strip().strip('"').strip("'")
    if not raw:
        return None, None
    path = Path(raw)
    if path.exists() and path.is_file():
        return path.resolve(), None
    alt = QR_DIR / raw
    if alt.exists() and alt.is_file():
        return alt.resolve(), None
    return None, raw


def unique_out_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 2
    while True:
        alt = directory / f"{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


def build_reel(
    top_path: Path,
    bottom_path: Path,
    out_path: Path,
    slogan: str | None,
    qr_path: Path | None,
    qr_text: str | None,
    cta_seconds: float = CTA_SEC,
    cta_style: str | None = None,
    tg_call: str | None = None,
    show_smileys: bool = True,
    sticker_pack: str | None = None,
    sticker_selection: str | None = "random",
    sticker_frames=None,
    banner=None,
    audio_mix: int = 0,
    bottom_circle: bool = False,
    captions: bool = False,
    asr_model: str = "small",
    circle_place: str = "center",
    caption_style: dict | None = None,
    on_log: ProgressCb | None = None,
) -> Path:
    """Собрать рилс: верх + низ (vstack), опционально CTA в конце (низ) и
    опционально баннер на паузе (``banner`` — BannerOptions / dict / None).

    Баннер (``banner.place``):
    - ``mid`` — на секунде ``at_sec`` верх замирает (ч/б), баннер, потом верх продолжается;
    - ``end`` — баннер в конце, на последнем кадре верха;
    - ``both`` — оба: первый на секунде и второй в конце.
    Первый баннер длится столько, сколько задано в настройках (аудио обрезается или дополняется).
    Второй длится по аудио, если оно есть. Низ играет всё это время.
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    from banner_cta import BannerOptions

    banner_opts = BannerOptions.from_any(banner)

    top_path = top_path.resolve()
    bottom_path = bottom_path.resolve()
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(top_path)
    has_audio = probe_has_audio(top_path)
    has_bottom_audio = probe_has_audio(bottom_path)
    # 0 — только верх, 100 — только низ
    audio_mix = max(0, min(100, int(audio_mix)))
    use_cta = bool((slogan and slogan.strip()) or qr_path or qr_text)

    if use_cta and duration <= cta_seconds + 0.5:
        raise ValueError(
            f"Видео «{top_path.name}» слишком короткое "
            f"({duration:.1f} с). Нужно больше {cta_seconds + 0.5:.0f} с."
        )

    # --- баннер: на секунде, в конце или оба ------------------------------
    use_mid = bool(banner_opts.wants_mid and duration >= 1.0)
    use_end = bool(banner_opts.wants_end and duration >= 1.0)
    banner_at = 0.0
    banner_audio: Path | None = None
    if use_mid or use_end:
        banner_audio = banner_opts.audio_path
        if banner_opts.audio and banner_audio is None:
            log(f"Баннер: аудио не найдено ({banner_opts.audio}) — без звука")
    if use_mid:
        from banner_cta import default_banner_at

        # Длиннее 10 с — пауза на 10-й. Короче или ровно 10 с — за 3 с до конца.
        banner_at = default_banner_at(duration)
        log(f"Пауза первого баннера: {banner_at:.1f}с (верх {duration:.1f}с)")
        if duration <= 0.6:
            use_mid = False
            log("Первый баннер пропущен: верхнее видео слишком короткое")
    if not use_mid and not use_end and banner_opts.is_active:
        log("Баннер пропущен: верхнее видео слишком короткое")

    from banner_cta import configured_banner_duration, resolve_banner_duration

    # Первый баннер — всегда длительность из настроек, аудио только звучит внутри неё.
    # Второй (в конце) — по длине аудио, если оно есть, иначе тоже из настроек.
    mid_dur = round(configured_banner_duration(banner_opts.duration), 3) if use_mid else 0.0
    end_dur = round(resolve_banner_duration(banner_audio, banner_opts.duration), 3) if use_end else 0.0

    # После первой паузы низ пропадает, верх занимает весь кадр.
    drop_bottom = bool(banner_opts.drop_bottom and use_mid)
    if banner_opts.drop_bottom and not use_mid:
        log("«Убрать низ после паузы» пропущено: нет первого баннера")
    if drop_bottom and use_cta:
        log("После паузы остаётся только верх — CTA низа не ставится")
        use_cta = False

    cta_dur = round(cta_seconds, 3) if use_cta else 0.0
    total = round(duration + mid_dur + end_dur, 3)
    # Низ: основная часть + CTA (если есть). Округляем, чтобы concat не ломался на дробных кадрах
    main_dur = max(0.1, round(total - cta_dur, 3)) if use_cta else total

    with tempfile.TemporaryDirectory(prefix="reel_") as tmp:
        tmp_dir = Path(tmp)
        cta_mp4 = tmp_dir / "cta.mp4"
        banner_mid_mp4 = tmp_dir / "banner_mid.mp4"
        banner_end_mp4 = tmp_dir / "banner_end.mp4"

        def _render_banner_at(at_sec: float, out_mp4: Path, where: str, seg_dur: float) -> None:
            from banner_cta import BannerAnimator, pick_banner_style, resolve_banner_text

            frame_png = tmp_dir / f"freeze_{where}.png"
            grab = run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{at_sec}",
                    "-i",
                    str(top_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_png),
                ],
                check=False,
            )
            if grab.returncode != 0 or not frame_png.is_file():
                raise RuntimeError(
                    f"Не удалось взять кадр для баннера на {at_sec}с: "
                    f"{(grab.stderr or grab.stdout or '')[-600:]}"
                )
            b_style = pick_banner_style(banner_opts.style)
            b_text = resolve_banner_text(banner_opts.text, randomize=banner_opts.randomize_text)
            src = f", источник: {banner_opts.source}" if banner_opts.source else ""
            log(f"Баннер «{b_style.title}» {where}, {seg_dur:.1f}с, текст: {b_text}{src}")
            BannerAnimator(
                b_text,
                duration=seg_dur,
                fps=FPS,
                style=b_style.id,
                background=frame_png,
                source=banner_opts.source,
            ).render_segment(out_mp4, audio_path=banner_audio, on_log=log)

        if use_mid:
            _render_banner_at(banner_at, banner_mid_mp4, f"на {banner_at:.1f}с", mid_dur)
        if use_end:
            end_at = round(max(0.0, duration - 0.15), 3)
            _render_banner_at(end_at, banner_end_mp4, "в конце", end_dur)

        if use_cta:
            from cta_anim import CtaAnimator, pick_cta_style, resolve_tg_call

            style = pick_cta_style(cta_style)
            call = resolve_tg_call(tg_call, randomize=False) if tg_call else resolve_tg_call(randomize=True)
            frames = sticker_frames
            if frames is None and sticker_pack:
                try:
                    from stickers import load_sticker_frames_for_cta

                    # random → новый стикер на каждый рилс
                    frames = load_sticker_frames_for_cta(
                        sticker_pack, sticker_selection, size=320, on_log=log
                    )
                    if frames and on_log and str(sticker_selection) in ("random", "rand", "*", "случайный"):
                        log("Стикер: случайный из пака для этого рилса")
                except Exception as exc:
                    log(f"Стикер не загрузился: {exc}")
                    frames = None
            log(f"Рендер CTA «{style.title}» + переход в TG…")
            CtaAnimator(
                slogan,
                qr_path,
                qr_text,
                duration=cta_dur,
                fps=FPS,
                style=style,
                tg_call=call,
                show_smileys=False,
                sticker_frames=frames,
            ).render_video(cta_mp4)

        # Входы:
        # 0 — верх
        # 1 — низ (loop)
        # далее — анимированный CTA (если есть) и/или баннер (если есть)
        cmd: list[str] = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(top_path),
            "-stream_loop",
            "-1",
            "-i",
            str(bottom_path),
        ]

        cta_idx = -1
        mid_idx = -1
        end_idx = -1
        next_idx = 2
        if use_cta:
            cmd.extend(["-i", str(cta_mp4)])
            cta_idx = next_idx
            next_idx += 1
        if use_mid:
            cmd.extend(["-i", str(banner_mid_mp4)])
            mid_idx = next_idx
            next_idx += 1
        if use_end:
            cmd.extend(["-i", str(banner_end_mp4)])
            end_idx = next_idx
            next_idx += 1

        use_circle = bool(bottom_circle) and not drop_bottom
        if bottom_circle and drop_bottom:
            log("Кружок не ставлю: после паузы низ убирается")
        disc_idx = -1
        mask_idx = -1
        if use_circle:
            outer = CIRCLE_D + CIRCLE_RING * 2
            disc_png = tmp_dir / "disc.png"
            mask_png = tmp_dir / "mask.png"
            _write_circle_disc(disc_png, outer)
            _write_circle_mask(mask_png, CIRCLE_D)
            cmd.extend(["-loop", "1", "-i", str(disc_png)])
            disc_idx = next_idx
            next_idx += 1
            cmd.extend(["-loop", "1", "-i", str(mask_png)])
            mask_idx = next_idx
            next_idx += 1

        caption_ass: Path | None = None
        cap_idx = -1
        if captions:
            speech = bottom_path if audio_mix >= 50 else top_path
            try:
                from transcribe import transcribe_words_in_subprocess

                log(f"Субтитры: слушаю {speech.name}")
                words = transcribe_words_in_subprocess(speech, model=asr_model or "small", on_log=log)
                media_dur = probe_duration(speech)
                timed = _repeat_words(words, media_dur, total)
                overlay = _render_caption_overlay(timed, caption_style, total, use_circle, tmp_dir, log) if timed else None
                if overlay is not None:
                    # Без libvpx FFmpeg читает WebM как непрозрачный чёрный кадр и закрывает ролик.
                    cmd.extend(["-c:v", "libvpx", "-i", str(overlay)])
                    cap_idx = next_idx
                    next_idx += 1
                    log(f"Субтитры: анимация, {len(timed)} слов")
                elif timed:
                    groups = _repeat_groups(_caption_groups(words), media_dur, total)
                    if groups:
                        caption_ass = tmp_dir / "captions.ass"
                        margin = CIRCLE_MARGIN + CIRCLE_D + CIRCLE_RING * 2 + 28 if use_circle else HALF_H + 36
                        _write_caption_ass(caption_ass, groups, margin_v=margin, style=caption_style)
                        log(f"Субтитры: {len(groups)} появлений, по 1–2 слова")
                else:
                    log("Субтитры: речи не слышно")
            except Exception as exc:  # noqa: BLE001
                log(f"Субтитры пропущены: {exc}")

        def _fit_half(label_in: str, label_out: str) -> str:
            return (
                f"[{label_in}]scale={REEL_W}:{HALF_H}:force_original_aspect_ratio=decrease,"
                f"pad={REEL_W}:{HALF_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},"
                f"format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[{label_out}]"
            )

        def _fit_banner(label_in: str, label_out: str) -> str:
            if not use_circle:
                return _fit_half(label_in, label_out)
            return (
                f"[{label_in}]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease,"
                f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},"
                f"format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[{label_out}]"
            )

        _AFMT = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"

        filter_parts: list[str] = []
        tail_dur = round(max(0.1, duration - banner_at), 3) if use_mid else round(duration, 3)
        src_dur = round(duration, 3)
        _NORM = f"setsar=1,fps={FPS},format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS"

        if drop_bottom:
            # До конца первой паузы — как раньше (верх + низ).
            # Дальше низ убран, верх на весь кадр 1080x1920.
            pre_dur = round(banner_at + mid_dur, 3)
            post_dur = round(tail_dur + end_dur, 3)
            log(f"После паузы низ убран, верх на весь кадр ({post_dur:.1f}с)")
            filter_parts.append("[0:v]split=2[vhalf_src][vfull_src]")
            filter_parts.append(scale_crop_filter("vhalf_src", "top0"))
            filter_parts += [
                f"[top0]trim=duration={banner_at},setpts=PTS-STARTPTS[top_a]",
                _fit_half(f"{mid_idx}:v", "top_mid"),
                "[top_a][top_mid]concat=n=2:v=1:a=0[top_pre]",
                scale_crop_filter("1:v", "bot0"),
                f"[bot0]trim=duration={pre_dur},setpts=PTS-STARTPTS[bot_pre]",
                "[top_pre][bot_pre]vstack=inputs=2[pre_raw]",
                f"[pre_raw]trim=duration={pre_dur},{_NORM}[pre]",
                (
                    f"[vfull_src]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                    f"crop={REEL_W}:{REEL_H},setsar=1,fps={FPS},format=yuv420p,settb=AVTB,"
                    f"setpts=PTS-STARTPTS[topfull0]"
                ),
                (
                    f"[topfull0]trim=start={banner_at}:duration={tail_dur},"
                    f"setpts=PTS-STARTPTS[top_tail_full]"
                ),
            ]
            if use_end:
                filter_parts += [
                    _fit_half(f"{end_idx}:v", "end_half"),
                    (
                        f"[end_half]pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:black,"
                        f"{_NORM}[end_full]"
                    ),
                    "[top_tail_full][end_full]concat=n=2:v=1:a=0[post_raw]",
                    f"[post_raw]trim=duration={post_dur},{_NORM}[post]",
                ]
            else:
                filter_parts.append(f"[top_tail_full]trim=duration={tail_dur},{_NORM}[post]")
            filter_parts.append("[pre][post]concat=n=2:v=1:a=0[vbase]")
        else:
            if use_circle:
                filter_parts.append(
                    f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                    f"crop={REEL_W}:{REEL_H},setsar=1,fps={FPS},format=yuv420p,"
                    f"settb=AVTB,setpts=PTS-STARTPTS[top0]"
                )
            else:
                filter_parts.append(scale_crop_filter("0:v", "top0"))
            # ---- верх: куски исходника и баннеры в нужном порядке -----------
            v_pieces: list[str] = []
            if use_mid:
                filter_parts += [
                    "[top0]split=2[top_a_src][top_c_src]",
                    f"[top_a_src]trim=duration={banner_at},setpts=PTS-STARTPTS[top_a]",
                    f"[top_c_src]trim=start={banner_at},setpts=PTS-STARTPTS[top_c]",
                ]
                v_pieces.append("top_a")
                filter_parts.append(_fit_banner(f"{mid_idx}:v", "top_mid"))
                v_pieces.append("top_mid")
                v_pieces.append("top_c")
            else:
                filter_parts.append(f"[top0]trim=duration={src_dur},setpts=PTS-STARTPTS[top_full]")
                v_pieces.append("top_full")
            if use_end:
                filter_parts.append(_fit_banner(f"{end_idx}:v", "top_end"))
                v_pieces.append("top_end")
            if use_mid or use_end:
                joined = "".join(f"[{name}]" for name in v_pieces)
                filter_parts.append(
                    f"{joined}concat=n={len(v_pieces)}:v=1:a=0[topcat]"
                )
                filter_parts.append(f"[topcat]trim=duration={total},setpts=PTS-STARTPTS[topf]")
            else:
                filter_parts.append(f"[top_full]trim=duration={total},setpts=PTS-STARTPTS[topf]")

            if use_circle:
                circle_at = _resolve_circle_place(circle_place)
                circle_x = _circle_x(circle_at)
                outer = CIRCLE_D + CIRCLE_RING * 2
                filter_parts += [
                    f"[{disc_idx}:v]format=rgba,fps={FPS},setpts=PTS-STARTPTS[disc]",
                    (
                        f"[1:v]scale={CIRCLE_D}:{CIRCLE_D}:force_original_aspect_ratio=increase,"
                        f"crop={CIRCLE_D}:{CIRCLE_D},fps={FPS},format=rgba,setpts=PTS-STARTPTS[circsrc]"
                    ),
                    f"[{mask_idx}:v]scale={CIRCLE_D}:{CIRCLE_D},format=gray[circmask]",
                    "[circsrc][circmask]alphamerge[circ]",
                    f"[disc][circ]overlay=(W-w)/2:(H-h)/2:format=auto[badge0]",
                ]
                y = f"H-h-{CIRCLE_MARGIN}"
                if use_cta:
                    filter_parts += [
                        f"[badge0]trim=duration={main_dur},setpts=PTS-STARTPTS[badge]",
                        f"[topf][badge]overlay=x={circle_x}:y={y}:eof_action=pass[withbadge]",
                        _fit_half(f"{cta_idx}:v", "cta"),
                        f"[cta]setpts=PTS+{main_dur}/TB[cta_late]",
                        f"[withbadge][cta_late]overlay=x=0:y=H-h:enable='gte(t,{main_dur})'[vbase]",
                    ]
                else:
                    filter_parts.append(f"[topf][badge0]overlay=x={circle_x}:y={y}:eof_action=pass[vbase]")
                log(f"Низ: кружок {CIRCLE_D}px, около 20% высоты, внизу {_CIRCLE_PLACE_RU.get(circle_at, 'по центру')}")
            else:
                filter_parts.append(scale_crop_filter("1:v", "bot0"))
                if use_cta:
                    filter_parts += [
                        f"[bot0]trim=duration={main_dur},setpts=PTS-STARTPTS[botmain]",
                        _fit_half(f"{cta_idx}:v", "cta"),
                        "[botmain][cta]concat=n=2:v=1:a=0[bottom]",
                    ]
                else:
                    filter_parts.append(f"[bot0]trim=duration={total},setpts=PTS-STARTPTS[bottom]")
                filter_parts.append("[topf][bottom]vstack=inputs=2[vbase]")

        if cap_idx >= 0:
            filter_parts.append(f"[{cap_idx}:v]format=yuva420p,fps={FPS},setpts=PTS-STARTPTS[capv]")
            filter_parts.append("[vbase][capv]overlay=0:0:eof_action=pass:format=auto[vout]")
        elif caption_ass is not None:
            filter_parts.append(f"[vbase]subtitles='{_ffmpeg_filter_path(caption_ass)}'[vout]")
        else:
            filter_parts.append("[vbase]format=yuv420p[vout]")

        # ---- звук: микшер верхнего и нижнего ролика --------------------
        banner_has_audio = bool((use_mid or use_end) and banner_audio is not None)
        want_top = audio_mix < 100
        want_bot = audio_mix > 0
        top_w = (100 - audio_mix) / 100.0
        bot_w = audio_mix / 100.0
        top_audible = bool(has_audio or banner_has_audio)
        out_has_audio = bool((want_top and top_audible) or (want_bot and has_bottom_audio))
        if audio_mix <= 0:
            log("Звук: только верхний ролик")
        elif audio_mix >= 100:
            log("Звук: только нижний ролик")
        else:
            log(f"Звук: верх {100 - audio_mix}% · низ {audio_mix}%")
        if want_bot and not has_bottom_audio:
            log("У нижнего ролика нет звуковой дорожки — со стороны низа тишина")
        if want_top and not has_audio and not banner_has_audio:
            log("У верхнего ролика нет звуковой дорожки — со стороны верха тишина")

        def _silence(label: str, seg_dur: float) -> None:
            filter_parts.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={seg_dur},"
                f"asetpts=PTS-STARTPTS,{_AFMT}[{label}]"
            )

        def _banner_audio(idx: int, label: str, seg_dur: float) -> None:
            if banner_has_audio:
                filter_parts.append(
                    f"[{idx}:a]atrim=duration={seg_dur},asetpts=PTS-STARTPTS,"
                    f"apad=whole_dur={seg_dur},{_AFMT}[{label}]"
                )
            else:
                _silence(label, seg_dur)

        def _top_bed(label: str) -> None:
            if not top_audible:
                _silence(label, total)
                return
            if use_mid or use_end:
                a_pieces: list[str] = []
                if use_mid:
                    if has_audio:
                        filter_parts.extend(
                            [
                                "[0:a]asplit=2[aud_a_src][aud_c_src]",
                                f"[aud_a_src]atrim=duration={banner_at},asetpts=PTS-STARTPTS,{_AFMT}[aud_a]",
                                f"[aud_c_src]atrim=start={banner_at},asetpts=PTS-STARTPTS,{_AFMT}[aud_c]",
                            ]
                        )
                    else:
                        _silence("aud_a", banner_at)
                        _silence("aud_c", tail_dur)
                    a_pieces.append("aud_a")
                    _banner_audio(mid_idx, "aud_mid", mid_dur)
                    a_pieces += ["aud_mid", "aud_c"]
                elif has_audio:
                    filter_parts.append(
                        f"[0:a]atrim=duration={src_dur},asetpts=PTS-STARTPTS,{_AFMT}[aud_full]"
                    )
                    a_pieces.append("aud_full")
                else:
                    _silence("aud_full", src_dur)
                    a_pieces.append("aud_full")
                if use_end:
                    _banner_audio(end_idx, "aud_end", end_dur)
                    a_pieces.append("aud_end")
                joined_a = "".join(f"[{name}]" for name in a_pieces)
                filter_parts.extend(
                    [
                        f"{joined_a}concat=n={len(a_pieces)}:v=0:a=1[audcat]",
                        f"[audcat]atrim=duration={total},asetpts=PTS-STARTPTS[{label}]",
                    ]
                )
                return
            filter_parts.append(f"[0:a]atrim=duration={total},asetpts=PTS-STARTPTS,{_AFMT}[{label}]")

        def _bot_bed(label: str) -> None:
            if has_bottom_audio:
                filter_parts.append(
                    f"[1:a]atrim=duration={total},asetpts=PTS-STARTPTS,"
                    f"apad=whole_dur={total},{_AFMT}[{label}]"
                )
            else:
                _silence(label, total)

        if out_has_audio and want_top and want_bot:
            _top_bed("topbed")
            _bot_bed("botbed")
            filter_parts += [
                f"[topbed]volume={top_w:.4f}[topmix]",
                f"[botbed]volume={bot_w:.4f}[botmix]",
                "[topmix][botmix]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
            ]
        elif out_has_audio and want_top:
            _top_bed("aout")
        elif out_has_audio and want_bot:
            _bot_bed("aout")

        filter_complex = ";".join(filter_parts)

        cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]"])
        if out_has_audio:
            cmd.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.append("-an")

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(FPS),
                "-t",
                f"{total}",
                "-movflags",
                "+faststart",
                str(out_path),
            ]
        )

        log(f"Рендер: {out_path.name}")
        proc = run_cmd(cmd, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "unknown error")[-2500:]
            raise RuntimeError(f"FFmpeg ошибка для {out_path.name}:\n{err}")

        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise RuntimeError(f"Файл не создан или пустой: {out_path.name}")

    return out_path


def generate_batch(
    top: Path,
    bottoms: list[Path],
    slogan: str | None,
    qr_path: Path | None,
    qr_text: str | None,
    cta_seconds: float = CTA_SEC,
    cta_style: str | None = None,
    slogans_text: str | None = None,
    randomize_slogan: bool = False,
    randomize_style: bool = False,
    tg_call: str | None = None,
    randomize_tg_call: bool = True,
    show_smileys: bool = True,
    sticker_pack: str | None = None,
    sticker_selection: str | None = "random",
    banner=None,
    audio_mix: int = 0,
    bottom_circle: bool = False,
    captions: bool = False,
    asr_model: str = "small",
    circle_place: str = "center",
    caption_style: dict | None = None,
    on_log: ProgressCb | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, int, list[Path]]:
    """Возвращает (ok, total, список готовых файлов)."""
    from cta_anim import resolve_slogan, resolve_tg_call

    ensure_dirs()
    total = len(bottoms)
    ok = 0
    produced: list[Path] = []

    for i, bottom in enumerate(bottoms, 1):
        name = f"{safe_stem(top.stem)}__{safe_stem(bottom.stem)}__{i:02d}.mp4"
        out = unique_out_path(OUTPUT, name)
        job_slogan = resolve_slogan(
            slogan,
            slogans_text=slogans_text,
            randomize=randomize_slogan,
        )
        job_style = "random" if randomize_style else cta_style
        job_tg = resolve_tg_call(tg_call, randomize=randomize_tg_call)
        if on_log:
            on_log(f"[{i}/{total}] верх={top.name} | низ={bottom.name}")
            if job_slogan:
                on_log(f"  слоган: {job_slogan}")
            on_log(f"  TG: {job_tg}")
        try:
            build_reel(
                top,
                bottom,
                out,
                job_slogan,
                qr_path,
                qr_text,
                cta_seconds=cta_seconds,
                cta_style=job_style,
                tg_call=job_tg,
                show_smileys=show_smileys,
                sticker_pack=sticker_pack,
                sticker_selection=sticker_selection,
                banner=banner,
                audio_mix=audio_mix,
                bottom_circle=bottom_circle,
                captions=captions,
                asr_model=asr_model,
                circle_place=circle_place,
                caption_style=caption_style,
                on_log=on_log,
            )
            ok += 1
            produced.append(out)
            if on_log:
                on_log(f"Готово: {out.name}")
        except Exception as exc:  # noqa: BLE001
            if on_log:
                on_log(f"Ошибка: {exc}")
        if on_progress:
            on_progress(i / total)

    return ok, total, produced


def generate_mass(
    tops: list[Path],
    bottoms_per_top: list[list[Path]],
    slogan: str | None,
    qr_path: Path | None,
    qr_text: str | None,
    cta_seconds: float = CTA_SEC,
    cta_style: str | None = None,
    slogans_text: str | None = None,
    randomize_slogan: bool = False,
    randomize_style: bool = False,
    tg_call: str | None = None,
    randomize_tg_call: bool = True,
    show_smileys: bool = True,
    sticker_pack: str | None = None,
    sticker_selection: str | None = "random",
    banner=None,
    audio_mix: int = 0,
    bottom_circle: bool = False,
    captions: bool = False,
    asr_model: str = "small",
    circle_place: str = "center",
    caption_style: dict | None = None,
    on_log: ProgressCb | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, int, list[Path]]:
    """Массовая генерация: для каждого верхнего видео — свой набор нижних."""
    from cta_anim import resolve_slogan, resolve_tg_call

    ensure_dirs()
    if len(tops) != len(bottoms_per_top):
        raise ValueError("tops и bottoms_per_top должны быть одной длины")

    jobs: list[tuple[Path, Path]] = []
    for top, bottoms in zip(tops, bottoms_per_top, strict=True):
        for bottom in bottoms:
            jobs.append((top, bottom))

    total = len(jobs)
    if total == 0:
        return 0, 0, []

    ok = 0
    produced: list[Path] = []
    for i, (top, bottom) in enumerate(jobs, 1):
        name = f"{safe_stem(top.stem)}__{safe_stem(bottom.stem)}__{i:03d}.mp4"
        out = unique_out_path(OUTPUT, name)
        job_slogan = resolve_slogan(
            slogan,
            slogans_text=slogans_text,
            randomize=randomize_slogan,
        )
        job_style = "random" if randomize_style else cta_style
        job_tg = resolve_tg_call(tg_call, randomize=randomize_tg_call)
        if on_log:
            on_log(f"[{i}/{total}] верх={top.name} | низ={bottom.name}")
            if job_slogan:
                on_log(f"  слоган: {job_slogan}")
            on_log(f"  TG: {job_tg}")
        try:
            build_reel(
                top,
                bottom,
                out,
                job_slogan,
                qr_path,
                qr_text,
                cta_seconds=cta_seconds,
                cta_style=job_style,
                tg_call=job_tg,
                show_smileys=show_smileys,
                sticker_pack=sticker_pack,
                sticker_selection=sticker_selection,
                banner=banner,
                audio_mix=audio_mix,
                bottom_circle=bottom_circle,
                captions=captions,
                asr_model=asr_model,
                circle_place=circle_place,
                caption_style=caption_style,
                on_log=on_log,
            )
            ok += 1
            produced.append(out)
            if on_log:
                on_log(f"Готово: {out.name}")
        except Exception as exc:  # noqa: BLE001
            if on_log:
                on_log(f"Ошибка: {exc}")
        if on_progress:
            on_progress(i / total)

    return ok, total, produced


def pick_random_bottoms(count: int, seed: int | None = None) -> list[Path]:
    bottoms = list_videos(FOLDER_2)
    if not bottoms:
        raise FileNotFoundError(f"Папка «2» пуста: {FOLDER_2}")
    if count < 1:
        raise ValueError("Количество рилсов должно быть >= 1")
    if seed is not None:
        random.seed(seed)
    if count <= len(bottoms):
        return random.sample(bottoms, count)
    # Если нужно больше, чем есть — добираем с повторами
    picked = bottoms[:]
    random.shuffle(picked)
    while len(picked) < count:
        picked.append(random.choice(bottoms))
    return picked[:count]


def allocate_bottoms_for_tops(
    tops_count: int,
    per_top: int,
    pool: list[Path],
    seed: int | None = None,
) -> list[list[Path]]:
    """Раздаёт нижние видео по верхним без сильного пересечения, с повторами при нехватке."""
    if tops_count < 1 or per_top < 1:
        raise ValueError("Нужно хотя бы 1 верхнее и 1 нижнее на ролик")
    if not pool:
        raise FileNotFoundError("Нет доступных нижних видео")
    rng = random.Random(seed)
    bag = pool[:]
    rng.shuffle(bag)
    result: list[list[Path]] = []
    idx = 0
    for _ in range(tops_count):
        chunk: list[Path] = []
        for _j in range(per_top):
            if idx >= len(bag):
                bag = pool[:]
                rng.shuffle(bag)
                idx = 0
            chunk.append(bag[idx])
            idx += 1
        result.append(chunk)
    return result
