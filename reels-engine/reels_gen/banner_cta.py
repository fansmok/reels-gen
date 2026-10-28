"""Mid-roll CTA banner: top video freezes, turns black & white, an animated
banner pops in front of it while the bottom video keeps playing.

Rendering model (same approach as cta_anim.py): every frame is drawn with PIL
on top of the frozen grayscale frame and then encoded with ffmpeg. The result
is a short "segment" clip (REEL_W x HALF_H) that engine.build_reel splices into
the top stream.

5 built-in styles + "random" (new style per reel).
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

REEL_W = 1080
HALF_H = 960
FPS = 30

DEFAULT_BANNER_TEXT = "ПОДПИШИСЬ"
DEFAULT_BANNER_DURATION = 4.0
MIN_BANNER_DURATION = 1.0
MAX_BANNER_DURATION = 20.0

_ASSETS = Path(__file__).resolve().parent / "assets"
_FONTS_DIR = _ASSETS / "fonts"


# --------------------------------------------------------------------------- styles
@dataclass(frozen=True)
class BannerStyle:
    id: str
    title: str
    kind: str  # glass | neon | gradient | minimal | pill
    accent: tuple[int, int, int]
    accent2: tuple[int, int, int]
    text: tuple[int, int, int]
    stroke: tuple[int, int, int]


BANNER_STYLES: tuple[BannerStyle, ...] = (
    BannerStyle(
        id="glass",
        title="Стекло (frosted glass)",
        kind="glass",
        accent=(255, 255, 255),
        accent2=(120, 190, 255),
        text=(255, 255, 255),
        stroke=(15, 20, 30),
    ),
    BannerStyle(
        id="neon",
        title="Неон (cyber glow)",
        kind="neon",
        accent=(0, 240, 255),
        accent2=(255, 0, 170),
        text=(255, 255, 255),
        stroke=(10, 0, 30),
    ),
    BannerStyle(
        id="gradient",
        title="Градиент (sweep)",
        kind="gradient",
        accent=(124, 58, 237),
        accent2=(236, 72, 153),
        text=(255, 255, 255),
        stroke=(40, 10, 60),
    ),
    BannerStyle(
        id="minimal",
        title="Минимал (black bar)",
        kind="minimal",
        accent=(255, 214, 10),
        accent2=(255, 255, 255),
        text=(255, 255, 255),
        stroke=(0, 0, 0),
    ),
    BannerStyle(
        id="pill",
        title="Пилюля (bouncy badge)",
        kind="pill",
        accent=(255, 69, 58),
        accent2=(255, 159, 10),
        text=(255, 255, 255),
        stroke=(70, 10, 10),
    ),
)

_STYLE_BY_ID = {s.id: s for s in BANNER_STYLES}


def list_banner_styles() -> list[BannerStyle]:
    return list(BANNER_STYLES)


def pick_banner_style(style: Optional[str], rng: Optional[random.Random] = None) -> BannerStyle:
    key = (style or "random").strip().lower()
    if key in _STYLE_BY_ID:
        return _STYLE_BY_ID[key]
    r = rng or random
    return r.choice(BANNER_STYLES)


# --------------------------------------------------------------------------- helpers
def _ease_out_back(t: float, s: float = 1.70158) -> float:
    t = max(0.0, min(1.0, t))
    t -= 1.0
    return t * t * ((s + 1) * t + s) + 1.0


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = _clamp01(t)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


_BOLD_CANDIDATES: tuple[str, ...] = (
    "Montserrat-ExtraBold.ttf",
    "Montserrat-Black.ttf",
    "Montserrat-Bold.ttf",
    "Inter-ExtraBold.ttf",
    "Inter-Bold.ttf",
    "Rubik-ExtraBold.ttf",
    "Rubik-Bold.ttf",
    "Unbounded-Bold.ttf",
)

_WIN_BOLD_FALLBACKS: tuple[str, ...] = (
    r"C:\Windows\Fonts\segoeuib.ttf",  # Segoe UI Bold
    r"C:\Windows\Fonts\seguibl.ttf",  # Segoe UI Black
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\tahomabd.ttf",
    r"C:\Windows\Fonts\verdanab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def pick_bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Heavy, high-quality font with Cyrillic support for banner text."""
    candidates: list[Path] = []
    if _FONTS_DIR.is_dir():
        for name in _BOLD_CANDIDATES:
            candidates.append(_FONTS_DIR / name)
        # anything bold-ish shipped in assets/fonts
        for p in sorted(_FONTS_DIR.glob("*.ttf")):
            low = p.name.lower()
            if any(k in low for k in ("black", "extrabold", "heavy", "bold")):
                candidates.append(p)
    candidates.extend(Path(p) for p in _WIN_BOLD_FALLBACKS)
    for cand in candidates:
        try:
            if cand.is_file():
                return ImageFont.truetype(str(cand), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    except Exception:
        return draw.textsize(text, font=font)  # type: ignore[attr-defined]


def _break_long_word(draw: ImageDraw.ImageDraw, word: str, font, max_w: int) -> list[str]:
    """Split a single word that is wider than max_w into chunks that fit."""
    parts: list[str] = []
    cur = ""
    for ch in word:
        if _text_size(draw, cur + ch, font)[0] <= max_w or not cur:
            cur += ch
        else:
            parts.append(cur)
            cur = ch
    if cur:
        parts.append(cur)
    return parts


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """Word-wrap the whole text into lines no wider than max_w. Nothing is cut off:
    explicit line breaks are kept, over-long words are broken by characters."""
    lines: list[str] = []
    for para in str(text).replace("\r", "").split("\n"):
        words = [w for w in para.split() if w]
        if not words:
            continue
        cur = ""
        for w in words:
            if _text_size(draw, w, font)[0] > max_w:
                if cur:
                    lines.append(cur)
                    cur = ""
                chunks = _break_long_word(draw, w, font, max_w)
                lines.extend(chunks[:-1])
                cur = chunks[-1] if chunks else ""
                continue
            trial = (cur + " " + w).strip()
            if _text_size(draw, trial, font)[0] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int, start: int = 96, min_size: int = 30):
    """Pick the largest bold font size such that the FULL wrapped text fits max_w x max_h.

    Font shrinks step by step; if even the minimum size does not fit, the text is still
    returned in full at min_size (the card grows / is clamped by the caller)."""
    size = start
    while size >= min_size:
        font = pick_bold_font(size)
        lines = _wrap_lines(draw, text, font, max_w)
        line_h = int(size * 1.16)
        fits_w = bool(lines) and all(_text_size(draw, ln, font)[0] <= max_w for ln in lines)
        if fits_w and line_h * len(lines) <= max_h:
            return font, lines, line_h
        size -= 4
    font = pick_bold_font(min_size)
    lines = _wrap_lines(draw, text, font, max_w)
    return font, lines, int(min_size * 1.16)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return m


def _linear_gradient(size: tuple[int, int], c1, c2, angle_shift: float = 0.0) -> Image.Image:
    """Horizontal gradient c1 -> c2 with optional phase shift (0..1) for sweep animation."""
    w, h = size
    strip = Image.new("RGB", (w, 1))
    px = strip.load()
    for x in range(w):
        t = (x / max(1, w - 1) + angle_shift) % 1.0
        # ping-pong so the sweep loops seamlessly
        tt = t * 2 if t < 0.5 else (1 - t) * 2
        px[x, 0] = _mix(c1, c2, tt)
    return strip.resize((w, h))


def prepare_frozen_background(src: Image.Image | Path | str, *, dim: float = 0.62) -> Image.Image:
    """Scale/crop a frame to REEL_W x HALF_H, make it black & white and dim it a little
    so the banner reads well. Mirrors engine.scale_crop_filter (cover + center crop)."""
    img = src if isinstance(src, Image.Image) else Image.open(src)
    img = img.convert("RGB")
    img = ImageOps.fit(img, (REEL_W, HALF_H), method=Image.LANCZOS, centering=(0.5, 0.5))
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray_rgb = gray.convert("RGB")
    # dim + vignette
    dimmed = Image.eval(gray_rgb, lambda v: int(v * dim))
    vign = Image.new("L", (REEL_W, HALF_H), 0)
    vd = ImageDraw.Draw(vign)
    vd.ellipse((-REEL_W * 0.25, -HALF_H * 0.35, REEL_W * 1.25, HALF_H * 1.35), fill=255)
    vign = vign.filter(ImageFilter.GaussianBlur(160))
    black = Image.new("RGB", (REEL_W, HALF_H), (0, 0, 0))
    return Image.composite(dimmed, black, vign.point(lambda v: 90 + int(v * 0.65)))


def _default_background() -> Image.Image:
    """Smooth dark radial gradient used when no frozen frame is supplied (previews)."""
    small = Image.new("L", (64, 56), 0)
    ImageDraw.Draw(small).ellipse((8, 4, 56, 52), fill=255)
    small = small.filter(ImageFilter.GaussianBlur(14))
    light = small.resize((REEL_W, HALF_H), Image.BICUBIC)
    base = Image.new("RGB", (REEL_W, HALF_H), (14, 15, 20))
    top = Image.new("RGB", (REEL_W, HALF_H), (74, 78, 96))
    return Image.composite(top, base, light)


# --------------------------------------------------------------------------- animator
class BannerAnimator:
    """Draws a full REEL_W x HALF_H frame: frozen grayscale background + animated banner."""

    def __init__(
        self,
        text: str,
        *,
        duration: float = DEFAULT_BANNER_DURATION,
        fps: int = FPS,
        style: Optional[str] = None,
        background: Image.Image | Path | str | None = None,
        source: Optional[str] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.text = (text or DEFAULT_BANNER_TEXT).strip() or DEFAULT_BANNER_TEXT
        self.source = " ".join(str(source or "").replace("\n", " ").split())
        self.duration = float(max(MIN_BANNER_DURATION, min(MAX_BANNER_DURATION, duration)))
        self.fps = int(fps)
        self.rng = rng or random.Random()
        self.style = pick_banner_style(style, self.rng)
        if background is None:
            self.bg = _default_background()
        else:
            self.bg = prepare_frozen_background(background)
        self.total_frames = max(1, int(round(self.duration * self.fps)))
        self._particles = [
            (
                self.rng.random(),
                self.rng.random(),
                self.rng.uniform(3, 9),
                self.rng.uniform(0.2, 1.0),
                self.rng.uniform(0, math.tau),
            )
            for _ in range(28)
        ]
        self._layout_cache: Optional[tuple] = None

    # ----- timing -----------------------------------------------------------
    def _phases(self, t: float) -> tuple[float, float]:
        """Return (enter 0..1, exit 0..1) progress values for time t."""
        enter_len = min(0.55, self.duration * 0.25)
        exit_len = min(0.45, self.duration * 0.2)
        enter = _clamp01(t / enter_len) if enter_len > 0 else 1.0
        exit_ = _clamp01((t - (self.duration - exit_len)) / exit_len) if exit_len > 0 else 0.0
        return enter, exit_

    # ----- layout -----------------------------------------------------------
    def _layout(self) -> tuple:
        if self._layout_cache is not None:
            return self._layout_cache
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        # Короткий текст — крупно; длинный — шрифт уменьшается, строк становится больше,
        # карточка растёт по высоте (до ~80% кадра), текст помещается целиком.
        max_w = int(REEL_W * 0.82)
        # место под плашку источника, если она есть
        reserve = 110 if self.source else 0
        max_h = int(HALF_H * 0.66) - reserve
        font, lines, line_h = _fit_font(probe, self.text.upper(), max_w, max_h, start=104, min_size=30)
        widths = [_text_size(probe, ln, font)[0] for ln in lines] or [0]
        text_w = max(widths)
        text_h = line_h * max(1, len(lines))
        self._layout_cache = (font, lines, line_h, text_w, text_h)
        return self._layout_cache

    def _pad(self) -> tuple[int, int]:
        """Card paddings that shrink for tall multi-line text so the card fits the frame."""
        _font, lines, _lh, _tw, text_h = self._layout()
        n = max(1, len(lines))
        pad_x = 90 if n <= 2 else 64
        free_h = HALF_H * 0.88 - self._content_h()
        pad_y = int(max(28, min(70, free_h / 2)))
        return pad_x, pad_y

    def _source_chip(self) -> Optional[tuple]:
        """Font and pixel size of the source badge under the main text."""
        if not self.source:
            return None
        _font, _lines, _lh, _tw, _th = self._layout()
        base = int(getattr(_font, "size", 64) or 64)
        size = max(36, min(66, int(base * 0.64)))
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        font = pick_bold_font(size)
        max_w = int(REEL_W * 0.72)
        tw, th = _text_size(probe, self.source, font)
        while size > 30 and tw > max_w:
            size -= 2
            font = pick_bold_font(size)
            tw, th = _text_size(probe, self.source, font)
        pad_x, pad_y = 40, 18
        return font, tw, th, tw + pad_x * 2, th + pad_y * 2

    def _content_h(self) -> int:
        _font, _lines, _lh, _tw, text_h = self._layout()
        chip = self._source_chip()
        if not chip:
            return text_h
        return text_h + 26 + chip[4]

    def _chip_phase(self, t: float) -> tuple[float, float]:
        """Плашка источника живёт по своему времени: появляется после текста.

        Возвращает (enter 0..1, idle_t) — прогресс появления и время с момента появления.
        """
        delay = min(0.45, self.duration * 0.2)
        enter_len = min(0.5, self.duration * 0.2)
        local = t - delay
        enter = _clamp01(local / enter_len) if enter_len > 0 else 1.0
        return enter, max(0.0, local)

    def _chip_colors(self) -> tuple[tuple[int, int, int, int], tuple[int, int, int], tuple[int, int, int]]:
        """Fill, text, stroke for the source badge."""
        st = self.style
        kind = st.kind
        if kind == "glass":
            return (16, 20, 30, 235), (255, 255, 255), st.accent2
        if kind == "neon":
            return (6, 4, 18, 240), (255, 255, 255), st.accent
        if kind == "gradient":
            return (255, 255, 255, 245), (42, 16, 72), (255, 255, 255)
        if kind == "minimal":
            return (*st.accent, 255), (12, 12, 12), (0, 0, 0)
        return (255, 255, 255, 245), st.accent, (255, 255, 255)

    # ----- drawing primitives ----------------------------------------------
    def _draw_text_block(
        self,
        canvas: Image.Image,
        center: tuple[float, float],
        alpha: float,
        *,
        glow: Optional[tuple[int, int, int]] = None,
        reveal: float = 1.0,
        t: float = 0.0,
    ) -> None:
        font, lines, line_h, text_w, text_h = self._layout()
        st = self.style
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = center
        block_h = self._content_h()
        y0 = cy - block_h / 2
        total_chars = sum(len(ln) for ln in lines) or 1
        shown = int(round(total_chars * _clamp01(reveal)))
        stroke_w = max(3, int(font.size * 0.07)) if hasattr(font, "size") else 3
        for i, ln in enumerate(lines):
            if shown <= 0:
                break
            part = ln[:shown]
            shown -= len(ln)
            w = _text_size(d, ln, font)[0]
            x = cx - w / 2
            y = y0 + i * line_h
            d.text((x + 4, y + 6), part, font=font, fill=(0, 0, 0, int(140 * alpha)), stroke_width=stroke_w, stroke_fill=(0, 0, 0, int(140 * alpha)))
            d.text(
                (x, y),
                part,
                font=font,
                fill=(*st.text, int(255 * alpha)),
                stroke_width=stroke_w,
                stroke_fill=(*st.stroke, int(255 * alpha)),
            )
        if glow is not None and alpha > 0:
            glow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            shown = int(round(total_chars * _clamp01(reveal)))
            for i, ln in enumerate(lines):
                if shown <= 0:
                    break
                part = ln[:shown]
                shown -= len(ln)
                w = _text_size(gd, ln, font)[0]
                gd.text((cx - w / 2, y0 + i * line_h), part, font=font, fill=(*glow, int(200 * alpha)), stroke_width=stroke_w + 6, stroke_fill=(*glow, int(200 * alpha)))
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(18))
            canvas.alpha_composite(glow_layer)
        canvas.alpha_composite(layer)
        self._draw_source_chip(canvas, cx, y0 + text_h + 26, alpha, t)

    def _draw_source_chip(self, canvas: Image.Image, cx: float, top: float, alpha: float, t: float) -> None:
        """Плашка источника: отскок при появлении, пульс, блик, мигающая обводка
        и стрелка, которая тянется к ней."""
        chip = self._source_chip()
        if not chip or alpha <= 0:
            return
        font, tw, th, cw, ch = chip
        fill, text_c, stroke = self._chip_colors()
        enter, idle = self._chip_phase(t)
        if enter <= 0:
            return
        a_chip = alpha * _ease_out_cubic(enter)
        # отскок при появлении, затем «дыхание» ~1 раз в секунду
        pop = 0.55 + 0.45 * _ease_out_back(enter, 2.8)
        beat = 1.0 + 0.045 * max(0.0, math.sin(idle * 6.2)) ** 3 if enter >= 1 else 1.0
        scale = pop * beat
        radius = ch // 2
        cy = top + ch / 2

        # внешнее кольцо-пульс расходится от плашки
        if enter >= 1:
            ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            rd = ImageDraw.Draw(ring)
            ph = (idle * 0.9) % 1.0
            grow = ph * 46
            ring_a = int(200 * a_chip * (1 - ph))
            rd.rounded_rectangle(
                (cx - cw / 2 - grow, cy - ch / 2 - grow, cx + cw / 2 + grow, cy + ch / 2 + grow),
                radius=int(radius + grow),
                outline=(*stroke, ring_a),
                width=4,
            )
            canvas.alpha_composite(ring.filter(ImageFilter.GaussianBlur(1.5)))

        # сама плашка
        pad = 28
        badge = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.rounded_rectangle((pad + 2, pad + 6, pad + cw + 2, pad + ch + 6), radius=radius, fill=(0, 0, 0, 150))
        badge = badge.filter(ImageFilter.GaussianBlur(7))
        bd = ImageDraw.Draw(badge)
        # обводка мигает между цветом стиля и белым
        blink = 0.5 + 0.5 * math.sin(idle * 7.0)
        outline = _mix(stroke, (255, 255, 255), blink * 0.85)
        bd.rounded_rectangle(
            (pad, pad, pad + cw, pad + ch),
            radius=radius,
            fill=(*fill[:3], fill[3]),
            outline=(*outline, 255),
            width=6,
        )
        # внутренняя тонкая линия для глубины
        bd.rounded_rectangle(
            (pad + 7, pad + 7, pad + cw - 7, pad + ch - 7),
            radius=max(4, radius - 7),
            outline=(*_mix(fill[:3], (255, 255, 255), 0.35), 110),
            width=2,
        )
        # бегущий блик слева направо каждые ~1.6 с — под буквами, чтобы не засвечивать их
        if enter >= 1:
            sweep_ph = (idle * 0.62) % 1.0
            sx = pad + int((sweep_ph * 1.5 - 0.25) * cw)
            shine = Image.new("RGBA", badge.size, (0, 0, 0, 0))
            ImageDraw.Draw(shine).polygon(
                [(sx, pad), (sx + 42, pad), (sx + 18, pad + ch), (sx - 24, pad + ch)],
                fill=(255, 255, 255, 150),
            )
            shine = shine.filter(ImageFilter.GaussianBlur(5))
            mask = Image.new("L", badge.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((pad, pad, pad + cw, pad + ch), radius=radius, fill=255)
            shine.putalpha(ImageChops.multiply(shine.getchannel("A"), mask))
            badge.alpha_composite(shine)
        self._paste_card(canvas, badge, (int(cx), int(cy)), a_chip, scale)
        # буквы рисуем отдельно, уже в итоговом размере: масштабирование плашки их не мылит
        base_size = int(getattr(font, "size", 40) or 40)
        draw_size = max(18, int(round(base_size * scale)))
        draw_font = font if draw_size == base_size else pick_bold_font(draw_size)
        letters = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(letters).text(
            (cx, cy),
            self.source,
            font=draw_font,
            fill=(*text_c, int(255 * a_chip)),
            anchor="mm",
        )
        canvas.alpha_composite(letters)

        # стрелка слева: три шеврона, бегущие к плашке
        if enter >= 1:
            self._draw_chevrons(canvas, cx - cw / 2 * scale, cy, a_chip, idle, stroke)

    def _draw_chevrons(
        self,
        canvas: Image.Image,
        edge_x: float,
        cy: float,
        alpha: float,
        idle: float,
        color: tuple[int, int, int],
    ) -> None:
        """Три шеврона слева от плашки, бегущие к ней."""
        a = int(255 * alpha)
        d = ImageDraw.Draw(canvas)
        if edge_x - 70 <= 16:
            return
        for k in range(3):
            phk = (idle * 2.2 - k * 0.3) % 1.0
            ca = int(a * (1 - phk) * 0.95)
            xx = edge_x - 70 + phk * 36
            d.line(
                [(xx - 16, cy - 16), (xx + 2, cy), (xx - 16, cy + 16)],
                fill=(*color, ca),
                width=6,
            )

    def _paste_card(self, canvas: Image.Image, card: Image.Image, box: tuple[int, int], alpha: float, scale: float) -> None:
        if scale != 1.0:
            nw = max(2, int(card.width * scale))
            nh = max(2, int(card.height * scale))
            card = card.resize((nw, nh), Image.LANCZOS)
        if alpha < 1.0:
            a = card.getchannel("A").point(lambda v: int(v * alpha))
            card.putalpha(a)
        x = int(box[0] - card.width / 2)
        y = int(box[1] - card.height / 2)
        canvas.alpha_composite(card, (max(-card.width, x), max(-card.height, y)))

    def _particles_layer(self, t: float, alpha: float, color: tuple[int, int, int]) -> Image.Image:
        layer = Image.new("RGBA", (REEL_W, HALF_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for px, py, r, speed, phase in self._particles:
            yy = (py - t * 0.08 * speed) % 1.0
            xx = (px + math.sin(t * 1.3 + phase) * 0.02) % 1.0
            a = int(alpha * 150 * (0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 3 + phase))))
            X, Y = xx * REEL_W, yy * HALF_H
            d.ellipse((X - r, Y - r, X + r, Y + r), fill=(*color, a))
        return layer.filter(ImageFilter.GaussianBlur(2))

    # ----- style renderers --------------------------------------------------
    def _card_size(self) -> tuple[int, int]:
        _font, _lines, _lh, text_w, _text_h = self._layout()
        pad_x, pad_y = self._pad()
        w = min(REEL_W - 60, max(text_w, (self._source_chip() or (0, 0, 0, 0, 0))[3]) + pad_x * 2)
        h = min(HALF_H - 40, self._content_h() + pad_y * 2)
        return int(w), int(h)

    def _render_glass(self, canvas: Image.Image, t: float, enter: float, exit_: float) -> None:
        st = self.style
        alpha = _ease_out_cubic(enter) * (1 - _ease_in_out(exit_))
        scale = 0.85 + 0.15 * _ease_out_back(enter)
        float_y = math.sin(t * 2.0) * 6
        cw, ch = self._card_size()
        cx, cy = REEL_W / 2, HALF_H / 2 + float_y + (1 - _ease_out_cubic(enter)) * 80
        # frosted card: blurred background crop + white tint
        card_box = (int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))
        bg_crop = self.bg.crop((max(0, card_box[0]), max(0, card_box[1]), min(REEL_W, card_box[2]), min(HALF_H, card_box[3])))
        bg_crop = bg_crop.resize((cw, ch)).filter(ImageFilter.GaussianBlur(22))
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        base = Image.blend(bg_crop, Image.new("RGB", (cw, ch), (255, 255, 255)), 0.28).convert("RGBA")
        card = Image.composite(base, card, _rounded_mask((cw, ch), 42))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((1, 1, cw - 2, ch - 2), radius=42, outline=(255, 255, 255, 170), width=3)
        # accent top light line
        sweep = (t * 0.35) % 1.0
        d.rounded_rectangle((int(cw * sweep) - 120, 6, int(cw * sweep) + 120, 10), radius=3, fill=(*st.accent2, 230))
        shadow = Image.new("RGBA", (cw + 80, ch + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((40, 50, cw + 40, ch + 50), radius=46, fill=(0, 0, 0, int(140 * alpha)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(28))
        canvas.alpha_composite(shadow, (int(cx - shadow.width / 2), int(cy - shadow.height / 2)))
        self._paste_card(canvas, card, (int(cx), int(cy)), alpha, scale)
        self._draw_text_block(canvas, (cx, cy), alpha, t=t)

    def _render_neon(self, canvas: Image.Image, t: float, enter: float, exit_: float) -> None:
        st = self.style
        alpha = _ease_out_cubic(enter) * (1 - _ease_in_out(exit_))
        scale = 0.6 + 0.4 * _ease_out_back(enter, 2.2)
        pulse = 0.5 + 0.5 * math.sin(t * 5.0)
        cw, ch = self._card_size()
        cx, cy = REEL_W / 2, HALF_H / 2
        canvas.alpha_composite(self._particles_layer(t, alpha, st.accent))
        # glow border
        glow = Image.new("RGBA", (cw + 120, ch + 120), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        col = _mix(st.accent, st.accent2, 0.5 + 0.5 * math.sin(t * 2.2))
        gd.rounded_rectangle((60, 60, cw + 60, ch + 60), radius=36, outline=(*col, int(255 * alpha)), width=10)
        glow = glow.filter(ImageFilter.GaussianBlur(14 + 8 * pulse))
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=36, fill=(10, 8, 24, 215))
        d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=36, outline=(*col, 255), width=5)
        self._paste_card(canvas, glow, (int(cx), int(cy)), alpha, scale)
        self._paste_card(canvas, card, (int(cx), int(cy)), alpha, scale)
        self._draw_text_block(canvas, (cx, cy), alpha, glow=col, t=t)

    def _render_gradient(self, canvas: Image.Image, t: float, enter: float, exit_: float) -> None:
        st = self.style
        alpha = _ease_out_cubic(enter) * (1 - _ease_in_out(exit_))
        slide = (1 - _ease_out_cubic(enter)) * REEL_W  # slide in from the right
        cw = REEL_W - 80
        _px, pad_y = self._pad()
        ch = int(min(HALF_H - 40, self._content_h() + pad_y * 2 + 40))  # +40 под шевроны
        cx, cy = REEL_W / 2 + slide, HALF_H / 2
        grad = _linear_gradient((cw, ch), st.accent, st.accent2, angle_shift=t * 0.25).convert("RGBA")
        # moving light sweep
        sweep = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sx = int(((t * 0.6) % 1.4 - 0.2) * cw)
        ImageDraw.Draw(sweep).polygon([(sx, 0), (sx + 140, 0), (sx + 60, ch), (sx - 80, ch)], fill=(255, 255, 255, 110))
        sweep = sweep.filter(ImageFilter.GaussianBlur(18))
        grad.alpha_composite(sweep)
        card = Image.composite(grad, Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), _rounded_mask((cw, ch), 30))
        shadow = Image.new("RGBA", (cw + 80, ch + 80), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((40, 58, cw + 40, ch + 58), radius=34, fill=(0, 0, 0, int(170 * alpha)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(26))
        canvas.alpha_composite(shadow, (int(cx - shadow.width / 2), int(cy - shadow.height / 2)))
        self._paste_card(canvas, card, (int(cx), int(cy)), alpha, 1.0)
        # small animated arrow/chevrons under text
        self._draw_text_block(canvas, (cx, cy - 18), alpha, t=t)
        d = ImageDraw.Draw(canvas)
        for k in range(3):
            ph = (t * 2.0 - k * 0.25) % 1.0
            a = int(255 * alpha * (1 - ph))
            yy = cy + ch / 2 - 34 + ph * 20
            xx = cx
            d.line([(xx - 18, yy - 10), (xx, yy + 2), (xx + 18, yy - 10)], fill=(255, 255, 255, a), width=5)

    def _render_minimal(self, canvas: Image.Image, t: float, enter: float, exit_: float) -> None:
        st = self.style
        alpha = _ease_out_cubic(enter) * (1 - _ease_in_out(exit_))
        _font, lines, line_h, text_w, text_h = self._layout()
        _px, pad_y = self._pad()
        ch = int(min(HALF_H - 20, self._content_h() + pad_y * 2 + 30))  # +30 под подчёркивание
        cw = REEL_W
        cx, cy = REEL_W / 2, HALF_H / 2
        # bar grows from the center line
        bar_h = int(ch * _ease_out_cubic(enter))
        bar = Image.new("RGBA", (cw, max(2, bar_h)), (8, 8, 10, int(235 * alpha)))
        canvas.alpha_composite(bar, (0, int(cy - bar_h / 2)))
        # accent underline that draws itself left->right then idles with a shimmer
        reveal = _clamp01((t - 0.15) / max(0.3, min(1.0, self.duration * 0.35)))
        ul_w = int(text_w * _ease_out_cubic(reveal))
        d = ImageDraw.Draw(canvas)
        uy = int(cy - 10 + self._content_h() / 2 + 14)
        d.rounded_rectangle((cx - text_w / 2, uy, cx - text_w / 2 + ul_w, uy + 10), radius=5, fill=(*st.accent, int(255 * alpha)))
        # typewriter reveal of text
        self._draw_text_block(canvas, (cx, cy - 10), alpha, reveal=reveal if enter >= 0.3 else 0.0, t=t)
        # side ticks
        tick_a = int(255 * alpha * (0.5 + 0.5 * math.sin(t * 4)))
        d.rectangle((0, cy - bar_h / 2, 16, cy + bar_h / 2), fill=(*st.accent, tick_a))
        d.rectangle((cw - 16, cy - bar_h / 2, cw, cy + bar_h / 2), fill=(*st.accent, tick_a))

    def _render_pill(self, canvas: Image.Image, t: float, enter: float, exit_: float) -> None:
        st = self.style
        alpha = _ease_out_cubic(enter) * (1 - _ease_in_out(exit_))
        scale = 0.3 + 0.7 * _ease_out_back(enter, 2.6)
        breathe = 1.0 + 0.025 * math.sin(t * 4.5)
        _font, lines, line_h, text_w, text_h = self._layout()
        pad_x, pad_y = self._pad()
        chip_w = (self._source_chip() or (0, 0, 0, 0, 0))[3]
        # у пилюли закруглённые торцы «съедают» ширину — добавляем запас по бокам
        cw = min(REEL_W - 60, int(max(text_w, chip_w) + pad_x * 2 + 60))
        ch = int(min(HALF_H - 40, self._content_h() + pad_y * 2))
        # для 1–2 строк — настоящая пилюля, для высокого текста — скруглённая карточка
        if len(lines) <= 2:
            # торцы не должны наезжать на текст, если карточка упёрлась в ширину кадра
            radius = int(min(ch // 2, max(40, (REEL_W - 60 - max(text_w, chip_w)) // 2 - 10)))
        else:
            radius = min(ch // 2, 70)
        cx, cy = REEL_W / 2, HALF_H / 2 + math.sin(t * 2.4) * 8
        canvas.alpha_composite(self._particles_layer(t, alpha * 0.8, st.accent2))
        # rings expanding outward
        d = ImageDraw.Draw(canvas)
        for k in range(2):
            ph = (t * 0.9 + k * 0.5) % 1.0
            rw = cw / 2 + ph * 120
            rh = ch / 2 + ph * 120
            a = int(140 * alpha * (1 - ph))
            d.rounded_rectangle((cx - rw, cy - rh, cx + rw, cy + rh), radius=int(min(rh, radius + ph * 120)), outline=(*st.accent2, a), width=4)
        grad = _linear_gradient((cw, ch), st.accent, st.accent2, angle_shift=t * 0.2).convert("RGBA")
        card = Image.composite(grad, Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), _rounded_mask((cw, ch), radius))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((3, 3, cw - 4, ch - 4), radius=radius, outline=(255, 255, 255, 200), width=4)
        # glossy highlight
        gloss = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(gloss).ellipse((cw * 0.1, -ch * 0.5, cw * 0.9, ch * 0.45), fill=(255, 255, 255, 70))
        gloss = Image.composite(gloss, Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), _rounded_mask((cw, ch), radius))
        card.alpha_composite(gloss.filter(ImageFilter.GaussianBlur(10)))
        shadow = Image.new("RGBA", (cw + 100, ch + 100), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((50, 62, cw + 50, ch + 62), radius=radius, fill=(0, 0, 0, int(160 * alpha)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(26))
        canvas.alpha_composite(shadow, (int(cx - shadow.width / 2), int(cy - shadow.height / 2)))
        self._paste_card(canvas, card, (int(cx), int(cy)), alpha, scale * breathe)
        self._draw_text_block(canvas, (cx, cy), alpha, t=t)

    # ----- public -----------------------------------------------------------
    def render_frame(self, index: int) -> Image.Image:
        t = index / float(self.fps)
        enter, exit_ = self._phases(t)
        canvas = self.bg.convert("RGBA")
        kind = self.style.kind
        if kind == "glass":
            self._render_glass(canvas, t, enter, exit_)
        elif kind == "neon":
            self._render_neon(canvas, t, enter, exit_)
        elif kind == "gradient":
            self._render_gradient(canvas, t, enter, exit_)
        elif kind == "minimal":
            self._render_minimal(canvas, t, enter, exit_)
        else:
            self._render_pill(canvas, t, enter, exit_)
        return canvas.convert("RGB")

    def render_preview(self, out_path: Path, *, at: float = 0.6) -> Path:
        idx = max(0, min(self.total_frames - 1, int(self.duration * at * self.fps)))
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.render_frame(idx).save(out_path, "PNG")
        return out_path

    def render_segment(
        self,
        out_path: Path,
        *,
        audio_path: Optional[Path] = None,
        on_log=None,
    ) -> Path:
        """Render the banner clip (REEL_W x HALF_H, self.duration seconds).

        If audio_path is given it is muxed in (cut/padded to the banner length);
        otherwise the clip has no audio stream (engine fills silence).
        """
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="banner_cta_"))
        try:
            for i in range(self.total_frames):
                self.render_frame(i).save(tmp / f"f_{i:05d}.png", "PNG", compress_level=1)
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                str(self.fps),
                "-i",
                str(tmp / "f_%05d.png"),
            ]
            has_audio = bool(audio_path and Path(audio_path).is_file())
            if has_audio:
                cmd += ["-i", str(audio_path)]
            cmd += [
                "-t",
                f"{self.duration:.3f}",
                "-map",
                "0:v:0",
            ]
            if has_audio:
                cmd += [
                    "-map",
                    "1:a:0",
                    "-af",
                    "aformat=sample_rates=44100:channel_layouts=stereo,apad",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                ]
            else:
                cmd += ["-an"]
            cmd += [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(self.fps),
                str(out_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
            if res.returncode != 0:
                raise RuntimeError(f"ffmpeg banner render failed: {res.stderr.strip()[:800]}")
            if on_log:
                on_log(f"Баннер: {self.style.title}, {self.duration:.1f}с, аудио={'да' if has_audio else 'нет'}")
            return out_path
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- utilities
def probe_audio_duration(path: Path | str) -> float:
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            errors="ignore",
        )
        return float((res.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def default_banner_at(duration: float) -> float:
    """Where the first banner freezes the top video.

    Longer than 10 seconds → pause at 10.0s.
    10 seconds or shorter → pause 3 seconds before the end.
    """
    try:
        duration = float(duration or 0)
    except Exception:
        duration = 0.0
    if duration > 10.0:
        at = 10.0
    else:
        at = duration - 3.0
    hi = max(0.3, duration - 0.3)
    return round(max(0.3, min(at, hi)), 3)


def configured_banner_duration(configured: Optional[float]) -> float:
    """Length from the duration setting. Audio does not change it."""
    try:
        c = float(configured or 0)
    except Exception:
        c = 0.0
    if c <= 0:
        c = DEFAULT_BANNER_DURATION
    return float(max(MIN_BANNER_DURATION, min(MAX_BANNER_DURATION, c)))


def resolve_banner_duration(audio_path: Optional[Path | str], configured: Optional[float]) -> float:
    """End-banner length: attached audio length, otherwise the configured value."""
    if audio_path and Path(audio_path).is_file():
        d = probe_audio_duration(audio_path)
        if d > 0:
            return float(max(MIN_BANNER_DURATION, min(MAX_BANNER_DURATION, d)))
    return configured_banner_duration(configured)


def resolve_banner_text(text: Optional[str], *, rng: Optional[random.Random] = None, randomize: bool = True) -> str:
    """Banner text may contain several variants (one per line); pick one."""
    lines = [ln.strip() for ln in str(text or "").replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        return DEFAULT_BANNER_TEXT
    if len(lines) == 1 or not randomize:
        return lines[0]
    return (rng or random).choice(lines)


@dataclass
class BannerOptions:
    """Settings of the optional mid-roll banner (all optional, OFF by default)."""

    enabled: bool = False
    text: str = DEFAULT_BANNER_TEXT  # may hold several variants, one per line
    style: str = "random"  # style id or "random"
    at_sec: float = 3.0  # second of the TOP video where it freezes
    duration: float = DEFAULT_BANNER_DURATION  # used when no audio is attached
    audio: Optional[str] = None  # path to an audio file or None
    randomize_text: bool = True
    place: str = "mid"  # mid — на секунде, end — в конце, both — оба
    source: str = ""  # плашка под текстом: куда ведём
    drop_bottom: bool = False  # после первой паузы убрать низ, верх на весь кадр

    @classmethod
    def from_any(cls, value) -> "BannerOptions":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            d = dict(value)
            opts = cls()
            opts.enabled = bool(d.get("enabled", False))
            opts.text = str(d.get("text") or DEFAULT_BANNER_TEXT)
            opts.style = str(d.get("style") or "random")
            try:
                opts.at_sec = float(d.get("at_sec", opts.at_sec) or 0)
            except Exception:
                pass
            try:
                opts.duration = float(d.get("duration", opts.duration) or 0)
            except Exception:
                pass
            audio = d.get("audio")
            opts.audio = str(audio) if audio else None
            opts.randomize_text = bool(d.get("randomize_text", True))
            opts.place = cls.normalize_place(d.get("place"))
            opts.source = " ".join(str(d.get("source") or "").replace("\n", " ").split())
            opts.drop_bottom = bool(d.get("drop_bottom", False))
            return opts
        raise TypeError(f"Unsupported banner options: {type(value)!r}")

    def to_dict(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "text": self.text,
            "style": self.style,
            "at_sec": float(self.at_sec),
            "duration": float(self.duration),
            "audio": self.audio or "",
            "randomize_text": bool(self.randomize_text),
            "place": self.place_norm,
            "source": self.source,
            "drop_bottom": bool(self.drop_bottom),
        }

    @staticmethod
    def normalize_place(value) -> str:
        key = str(value or "mid").strip().lower()
        if key in {"end", "конец", "second", "2", "last"}:
            return "end"
        if key in {"both", "оба", "two", "1+2", "all"}:
            return "both"
        return "mid"

    @property
    def place_norm(self) -> str:
        return self.normalize_place(self.place)

    @property
    def audio_path(self) -> Optional[Path]:
        if not self.audio:
            return None
        p = Path(str(self.audio).strip().strip('"'))
        return p if p.is_file() else None

    @property
    def is_active(self) -> bool:
        return bool(self.enabled and str(self.text or "").strip())

    @property
    def wants_mid(self) -> bool:
        return self.is_active and self.place_norm in {"mid", "both"}

    @property
    def wants_end(self) -> bool:
        return self.is_active and self.place_norm in {"end", "both"}


def create_banner_preview(
    text: str,
    out_path: Path,
    *,
    style: Optional[str] = None,
    duration: float = DEFAULT_BANNER_DURATION,
    background: Image.Image | Path | str | None = None,
    source: Optional[str] = None,
) -> Path:
    anim = BannerAnimator(text, duration=duration, style=style, background=background, source=source)
    return anim.render_preview(out_path)


__all__ = [
    "BannerAnimator",
    "BannerOptions",
    "BannerStyle",
    "BANNER_STYLES",
    "DEFAULT_BANNER_DURATION",
    "DEFAULT_BANNER_TEXT",
    "create_banner_preview",
    "default_banner_at",
    "list_banner_styles",
    "pick_banner_style",
    "pick_bold_font",
    "prepare_frozen_background",
    "configured_banner_duration",
    "probe_audio_duration",
    "resolve_banner_duration",
    "resolve_banner_text",
]
