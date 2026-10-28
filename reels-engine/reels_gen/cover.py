"""Обложки для YouTube Shorts: кадр 3–6 с + жирный заголовок в стиле modern YT."""

from __future__ import annotations

import random
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
COVER_DIR = ROOT / "assets" / "covers"
FOLDER_1 = ROOT / "1"
FOLDER_2 = ROOT / "2"

REEL_W, REEL_H = 1080, 1920
DEFAULT_PHRASES = [
    "ДАЖЕ ОНА ЗАРАБОТАЛА НА КРИПТЕ",
    "ЭТО МЕНЯЕТ ВСЁ",
    "СМОТРИ ДО КОНЦА",
    "НИКТО НЕ ОЖИДАЛ ЭТОГО",
]


@dataclass
class CoverStyle:
    """Сохраняемые настройки текста обложки."""

    enabled: bool = True
    source: str = "bottom"  # top | bottom — bottom = уникальный низ на каждый рилс
    position: str = "bottom"  # bottom | center | top
    text_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 8
    font_size: int = 0  # 0 = авто
    uppercase: bool = True
    phrases: str = "\n".join(DEFAULT_PHRASES)
    text_source: str = "titles"  # titles | templates

    def phrase_list(self) -> list[str]:
        lines = [ln.strip() for ln in (self.phrases or "").splitlines() if ln.strip()]
        return lines or list(DEFAULT_PHRASES)

    def pick_phrase(self, rng: random.Random | None = None) -> str:
        r = rng or random
        return r.choice(self.phrase_list())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> CoverStyle:
        if not isinstance(data, dict):
            return cls()
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in data.items() if k in known}
        if "text_source" in kwargs:
            ts = str(kwargs["text_source"] or "titles").strip().lower()
            kwargs["text_source"] = "templates" if ts in {"templates", "template", "phrases"} else "titles"
        try:
            return cls(**kwargs)
        except Exception:
            return cls()


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def _win_flags() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _hex_to_rgb(value: str, fallback: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return fallback
    try:
        return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return fallback


def _pick_cover_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Жирный «ютубный» шрифт с кириллицей: Segoe Black / Arial Bold / Impact."""
    fonts_dir = ROOT / "assets" / "fonts"
    candidates = [
        fonts_dir / "Montserrat-Black.ttf",
        fonts_dir / "Montserrat-Bold.ttf",
        Path(r"C:\Windows\Fonts\seguibl.ttf"),  # Segoe UI Black — кириллица
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\arialblack.ttf"),
        Path(r"C:\Windows\Fonts\comicbd.ttf"),
        fonts_dir / "Impact.ttf",
        Path(r"C:\Windows\Fonts\impact.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def video_duration(path: Path) -> float:
    cmd = [
        _ffprobe(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_win_flags(),
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return max(0.1, float(proc.stdout.strip()))
    except Exception:
        pass
    return 10.0


def pick_cover_time(duration: float, rng: random.Random | None = None) -> float:
    """Случайный момент между 3 и 6 сек (с ужатием под длину ролика)."""
    r = rng or random
    lo, hi = 3.0, 6.0
    if duration <= 1.0:
        return max(0.0, duration * 0.4)
    if duration < hi + 0.3:
        # короткое видео — берём середину безопасного окна
        lo = min(1.0, duration * 0.25)
        hi = max(lo + 0.2, duration * 0.75)
    t = r.uniform(lo, hi)
    return max(0.0, min(t, max(0.05, duration - 0.15)))


def extract_frame(video: Path, at_sec: float, out_jpg: Path) -> Path:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{at_sec:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_jpg),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_win_flags(),
    )
    if proc.returncode != 0 or not out_jpg.is_file():
        raise RuntimeError(f"Не удалось взять кадр: {(proc.stderr or '')[-400:]}")
    return out_jpg


def _fit_cover_canvas(img: Image.Image, size: tuple[int, int] = (REEL_W, REEL_H)) -> Image.Image:
    """Cover crop в 9:16."""
    tw, th = size
    src = img.convert("RGB")
    sw, sh = src.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _wrap_lines(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _auto_font_and_lines(
    text: str,
    *,
    max_width: int,
    max_height: int,
    preferred: int,
    stroke: int,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    probe = Image.new("RGB", (8, 8))
    draw = ImageDraw.Draw(probe)
    size = preferred if preferred > 0 else 96
    size = max(36, min(140, size))
    best_font = _pick_cover_font(size)
    best_lines = [text]
    for try_size in range(size, 35, -4):
        font = _pick_cover_font(try_size)
        lines = _wrap_lines(text, font, max_width, draw)
        if len(lines) > 4:
            continue
        heights = []
        widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
            widths.append(bbox[2] - bbox[0])
            heights.append(bbox[3] - bbox[1])
        total_h = sum(heights) + max(0, len(lines) - 1) * int(try_size * 0.12)
        if max(widths, default=0) <= max_width and total_h <= max_height:
            return font, lines, try_size
        best_font, best_lines = font, lines
    return best_font, best_lines, 36


def draw_cover_text(
    base: Image.Image,
    text: str,
    style: CoverStyle,
) -> Image.Image:
    """Накладывает крупный заголовок: жирный + обводка, позиция bottom/center/top."""
    img = base.convert("RGBA")
    w, h = img.size
    phrase = (text or "").strip()
    if style.uppercase:
        phrase = phrase.upper()
    if not phrase:
        return img.convert("RGB")

    stroke = max(0, int(style.stroke_width))
    fill = _hex_to_rgb(style.text_color, (255, 255, 255)) + (255,)
    stroke_fill = _hex_to_rgb(style.stroke_color, (0, 0, 0)) + (255,)
    max_w = int(w * 0.90)
    max_h = int(h * 0.38)
    font, lines, size = _auto_font_and_lines(
        phrase,
        max_width=max_w,
        max_height=max_h,
        preferred=int(style.font_size or 0),
        stroke=stroke,
    )

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    line_gap = int(size * 0.12)
    line_boxes = [
        draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines
    ]
    line_heights = [b[3] - b[1] for b in line_boxes]
    block_h = sum(line_heights) + line_gap * max(0, len(lines) - 1)

    pos = (style.position or "bottom").lower()
    if pos == "top":
        y0 = int(h * 0.08)
    elif pos == "center":
        y0 = (h - block_h) // 2
    else:
        # выше прежнего 8% — иначе нижние строки уезжают за safe-area Shorts
        y0 = h - int(h * 0.16) - block_h
        y0 = max(int(h * 0.55), y0)

    # лёгкая затемняющая подложка под текстом — читаемость как у YT
    pad_x, pad_y = 28, 18
    band = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    y1 = y0 + block_h
    bd.rectangle(
        (0, max(0, y0 - pad_y - 10), w, min(h, y1 + pad_y + 20)),
        fill=(0, 0, 0, 90),
    )
    band = band.filter(ImageFilter.GaussianBlur(12))
    img = Image.alpha_composite(img, band)

    y = y0
    for i, line in enumerate(lines):
        bbox = line_boxes[i]
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2 - bbox[0]
        # тень
        draw.text(
            (x + 3, y + 4),
            line,
            font=font,
            fill=(0, 0, 0, 160),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 160),
        )
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke,
            stroke_fill=stroke_fill,
        )
        y += line_heights[i] + line_gap

    out = Image.alpha_composite(img, overlay)
    return out.convert("RGB")


def placeholder_frame(size: tuple[int, int] = (REEL_W, REEL_H), note: str = "") -> Image.Image:
    img = Image.new("RGB", size, (18, 24, 38))
    draw = ImageDraw.Draw(img)
    font = _pick_cover_font(42)
    msg = note or "Кадр появится после скачивания низа"
    lines = _wrap_lines(msg, font, int(size[0] * 0.8), draw)
    total_h = len(lines) * 52
    y = (size[1] - total_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((size[0] - tw) // 2, y), line, font=font, fill=(160, 175, 200))
        y += 52
    return img


def render_cover(
    *,
    video: Path | None,
    out_path: Path,
    style: CoverStyle,
    phrase: str | None = None,
    at_sec: float | None = None,
    rng: random.Random | None = None,
) -> Path:
    """
    Делает обложку: кадр из video (или placeholder) + текст.
    Если video нет — рисует плейсхолдер (для превью, когда низ ещё не скачан).
    """
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = rng or random
    text = phrase if phrase is not None else style.pick_phrase(r)

    if video and Path(video).is_file():
        dur = video_duration(Path(video))
        t = at_sec if at_sec is not None else pick_cover_time(dur, r)
        tmp = out_path.with_suffix(".frame.jpg")
        try:
            extract_frame(Path(video), t, tmp)
            base = Image.open(tmp).convert("RGB")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        canvas = _fit_cover_canvas(base)
    else:
        canvas = placeholder_frame(
            note="Низ ещё не скачан — настройки сохранятся"
            if (style.source or "").lower() == "bottom"
            else "Нет видео для кадра"
        )

    result = draw_cover_text(canvas, text, style)
    result.save(out_path, quality=92, optimize=True)
    return out_path


def safe_stem(name: str) -> str:
    import re

    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE)
    return s.strip("_")[:80] or "clip"


def resolve_source_video(
    output_reel: Path,
    source: str,
    *,
    top_hint: Path | None = None,
    bottom_hint: Path | None = None,
) -> Path | None:
    """
    Находит верхнее/нижнее исходное видео для готового рилса.
    Имя файла: {top}__{bottom}__NN.mp4
    """
    src = (source or "bottom").lower()
    if top_hint and src == "top" and Path(top_hint).is_file():
        return Path(top_hint)
    if bottom_hint and src == "bottom" and Path(bottom_hint).is_file():
        return Path(bottom_hint)

    stem = Path(output_reel).stem
    parts = stem.split("__")
    if len(parts) >= 2:
        top_key, bot_key = parts[0], parts[1]
        want = top_key if src == "top" else bot_key
        search_dirs: list[Path] = [FOLDER_1 if src == "top" else FOLDER_2]
        if src == "bottom":
            cache = ROOT / "cache" / "instagram"
            if cache.is_dir():
                search_dirs.append(cache)

        def _iter_videos(folder: Path):
            if not folder.is_dir():
                return
            it = folder.rglob("*") if folder.name == "instagram" else folder.iterdir()
            for p in it:
                if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
                    yield p

        for folder in search_dirs:
            for p in _iter_videos(folder):
                if safe_stem(p.stem) == want:
                    return p
        for folder in search_dirs:
            for p in _iter_videos(folder):
                key = safe_stem(p.stem)
                if key.startswith(want[:40]) or want.startswith(key[:40]):
                    return p

    if Path(output_reel).is_file():
        return Path(output_reel)
    return None


def make_cover_for_reel(
    output_reel: Path,
    out_jpg: Path,
    style: CoverStyle,
    *,
    top_hint: Path | None = None,
    bottom_hint: Path | None = None,
    phrase: str | None = None,
    rng: random.Random | None = None,
    on_log=None,
) -> Path:
    video = resolve_source_video(
        output_reel,
        style.source,
        top_hint=top_hint,
        bottom_hint=bottom_hint,
    )
    if on_log:
        src_name = video.name if video else "—"
        on_log(f"Обложка ← {style.source}: {src_name}")
    return render_cover(
        video=video,
        out_path=out_jpg,
        style=style,
        phrase=(phrase or "").upper() if phrase else phrase,
        rng=rng,
    )
