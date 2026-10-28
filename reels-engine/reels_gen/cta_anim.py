"""
Анимированный CTA: 10 стилей + опциональный рандом слоганов.
"""

from __future__ import annotations

import math
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REEL_W = 1080
HALF_H = 960
FPS = 30
ROOT = Path(__file__).resolve().parent
SLOGANS_FILE = ROOT / "assets" / "slogans.txt"

DEFAULT_SLOGANS = [
    "Твой путь начинается здесь",
    "Жми и забирай доступ",
    "Сканируй QR — начни сегодня",
    "Один клик до результата",
    "Подпишись и забери бонус",
    "Твой следующий шаг — здесь",
    "Открой возможности сейчас",
    "Не упусти момент",
]

DEFAULT_TG_CALLS = [
    "Переходи в Telegram →",
    "Жми и пиши в TG →",
    "Залетай в Telegram →",
    "Ссылка в Telegram →",
    "Жду тебя в Telegram →",
    "Открой Telegram и забери →",
]


@dataclass(frozen=True)
class CtaStyle:
    id: str
    title: str
    bg_a: tuple[int, int, int]
    bg_b: tuple[int, int, int]
    orb1: tuple[int, int, int]
    orb2: tuple[int, int, int]
    text: tuple[int, int, int]
    line: tuple[int, int, int]
    particle: tuple[int, int, int]
    light_mode: bool = False


CTA_STYLES: list[CtaStyle] = [
    CtaStyle("noir_gold", "Noir Gold", (8, 10, 14), (22, 18, 14), (210, 170, 110), (90, 140, 155), (248, 246, 240), (220, 190, 140), (245, 240, 230)),
    CtaStyle("midnight_teal", "Midnight Teal", (6, 18, 22), (10, 40, 48), (40, 180, 170), (20, 90, 120), (230, 250, 248), (80, 210, 200), (180, 240, 235)),
    CtaStyle("ember", "Ember Night", (18, 8, 6), (40, 16, 10), (240, 120, 60), (160, 50, 30), (255, 236, 220), (255, 150, 90), (255, 200, 160)),
    CtaStyle("forest", "Deep Forest", (8, 16, 10), (14, 36, 20), (90, 170, 110), (40, 90, 60), (235, 250, 238), (140, 210, 150), (190, 230, 200)),
    CtaStyle("ocean", "Ocean Mist", (8, 14, 28), (18, 40, 70), (70, 140, 220), (30, 80, 140), (235, 245, 255), (120, 180, 255), (200, 220, 255)),
    CtaStyle("slate", "Slate Minimal", (18, 20, 24), (36, 40, 48), (140, 150, 165), (80, 90, 105), (245, 247, 250), (180, 190, 205), (220, 225, 235)),
    CtaStyle("ivory", "Soft Ivory", (245, 241, 232), (230, 222, 208), (210, 180, 140), (180, 160, 130), (35, 30, 25), (120, 95, 70), (90, 80, 70), True),
    CtaStyle("blush", "Blush Ink", (18, 10, 14), (42, 20, 30), (220, 120, 150), (140, 60, 90), (255, 235, 242), (240, 160, 185), (255, 200, 215)),
    CtaStyle("arctic", "Arctic Light", (236, 244, 250), (210, 228, 242), (140, 190, 220), (100, 150, 190), (20, 40, 55), (50, 110, 150), (60, 90, 120), True),
    CtaStyle("carbon", "Carbon Accent", (10, 12, 12), (24, 28, 28), (190, 230, 80), (80, 120, 60), (245, 250, 235), (200, 240, 90), (220, 255, 140)),
]

CTA_STYLE_BY_ID = {s.id: s for s in CTA_STYLES}


def list_cta_styles() -> list[CtaStyle]:
    return list(CTA_STYLES)


def pick_cta_style(style_id: str | None = None, rng: random.Random | None = None) -> CtaStyle:
    if style_id and style_id not in {"", "random", "auto", "случайный"}:
        if style_id in CTA_STYLE_BY_ID:
            return CTA_STYLE_BY_ID[style_id]
    r = rng or random
    return r.choice(CTA_STYLES)


def ensure_default_slogans_file() -> Path:
    SLOGANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SLOGANS_FILE.exists():
        SLOGANS_FILE.write_text("\n".join(DEFAULT_SLOGANS) + "\n", encoding="utf-8")
    return SLOGANS_FILE


def parse_slogans(text: str | None) -> list[str]:
    lines = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s:
            lines.append(s)
    return lines


def load_slogans_from_file() -> list[str]:
    ensure_default_slogans_file()
    try:
        return parse_slogans(SLOGANS_FILE.read_text(encoding="utf-8"))
    except OSError:
        return list(DEFAULT_SLOGANS)


def resolve_slogan(
    slogan: str | None,
    *,
    slogans_text: str | None = None,
    randomize: bool = False,
    rng: random.Random | None = None,
) -> str | None:
    """
    Если randomize=True — берём случайный из списка (textbox или файл/дефолт).
    Иначе — обычный slogan, либо первая строка списка.
    """
    r = rng or random
    pool = parse_slogans(slogans_text)
    if not pool:
        pool = load_slogans_from_file()
    if randomize:
        return r.choice(pool) if pool else (slogan.strip() if slogan else None)
    if slogan and slogan.strip():
        multi = parse_slogans(slogan)
        return multi[0] if multi else slogan.strip()
    if pool:
        return pool[0]
    return None


def resolve_tg_call(
    text: str | None = None,
    *,
    randomize: bool = True,
    rng: random.Random | None = None,
) -> str:
    r = rng or random
    lines = parse_slogans(text)
    if lines:
        return r.choice(lines) if randomize else lines[0]
    return r.choice(DEFAULT_TG_CALLS) if randomize else DEFAULT_TG_CALLS[0]


def short_link_label(qr_text: str | None) -> str | None:
    """Короткая подпись ссылки под призывом (t.me / @user)."""
    if not qr_text:
        return None
    raw = qr_text.strip()
    low = raw.lower()
    if "t.me/" in low:
        part = raw.split("t.me/", 1)[-1].split("?")[0].strip("/")
        if part:
            return f"t.me/{part}"
    if raw.startswith("@") and len(raw) > 1:
        return raw
    if low.startswith("https://") or low.startswith("http://"):
        host = raw.split("//", 1)[-1]
        if len(host) > 36:
            host = host[:33] + "…"
        return host
    if len(raw) <= 40:
        return raw
    return raw[:37] + "…"


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )


def _clamp_byte(v: float) -> int:
    return max(0, min(255, int(v)))


def _pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts_dir = ROOT / "assets" / "fonts"
    if bold:
        candidates = [
            fonts_dir / "Montserrat-SemiBold.ttf",
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
        ]
    else:
        candidates = [
            fonts_dir / "Montserrat-Regular.ttf",
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    probe = Image.new("RGB", (8, 8))
    draw = ImageDraw.Draw(probe)
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


def _make_qr_card(qr_path: Path | None, qr_text: str | None, size: int = 320) -> Image.Image | None:
    import qrcode

    if qr_path and qr_path.exists():
        img = Image.open(qr_path).convert("RGB")
    elif qr_text:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=12,
            border=2,
        )
        qr.add_data(qr_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    else:
        return None

    pad = 18
    card = Image.new("RGB", (img.width + pad * 2, img.height + pad * 2), (255, 255, 255))
    card.paste(img, (pad, pad))
    card = card.resize((size, size), Image.Resampling.LANCZOS)
    rgba = card.convert("RGBA")
    mask = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, rgba.width - 1, rgba.height - 1), radius=22, fill=255)
    rgba.putalpha(mask)
    return rgba


def _make_orb(radius: int, color: tuple[int, int, int], strength: float = 1.0) -> Image.Image:
    size = int(radius * 2.6)
    orb = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(orb)
    for i in range(7, 0, -1):
        r = radius * (i / 7)
        alpha = int(strength * (1 - i / 8) * 60)
        inset = size / 2 - r
        draw.ellipse(
            (inset, inset, size - inset, size - inset),
            fill=(color[0], color[1], color[2], alpha),
        )
    return orb.filter(ImageFilter.GaussianBlur(radius=max(10, radius * 0.4)))


def _make_smiley(kind: str, size: int = 72) -> Image.Image:
    """Цветной смайл (рисуем сами — эмодзи-шрифт на Windows монохромный)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 2
    faces = {
        "happy": ((255, 214, 90), (255, 190, 50)),
        "wink": ((255, 196, 110), (255, 168, 70)),
        "heart": ((255, 150, 170), (255, 110, 140)),
        "cool": ((120, 210, 255), (70, 170, 230)),
        "fire": ((255, 140, 70), (255, 90, 40)),
    }
    c1, _c2 = faces.get(kind, faces["happy"])
    d.ellipse((pad + 3, pad + 5, size - pad + 1, size - pad + 3), fill=(0, 0, 0, 55))
    d.ellipse((pad, pad, size - pad, size - pad), fill=(*c1, 255))
    d.ellipse(
        (pad + size * 0.18, pad + size * 0.12, pad + size * 0.42, pad + size * 0.34),
        fill=(255, 255, 255, 70),
    )

    eye_y = size * 0.38
    eye_r = size * 0.07
    left_x, right_x = size * 0.33, size * 0.67
    dark = (40, 30, 20, 255)

    if kind == "wink":
        d.ellipse((left_x - eye_r, eye_y - eye_r, left_x + eye_r, eye_y + eye_r), fill=dark)
        d.arc(
            (right_x - eye_r * 1.6, eye_y - eye_r * 0.6, right_x + eye_r * 1.6, eye_y + eye_r * 1.4),
            start=200,
            end=340,
            fill=dark,
            width=max(2, size // 22),
        )
    elif kind == "heart":
        for cx in (left_x, right_x):
            hx, hy = cx, eye_y
            s = size * 0.09
            d.ellipse((hx - s, hy - s * 0.6, hx, hy + s * 0.5), fill=(220, 40, 70, 255))
            d.ellipse((hx, hy - s * 0.6, hx + s, hy + s * 0.5), fill=(220, 40, 70, 255))
            d.polygon(
                [(hx - s, hy), (hx + s, hy), (hx, hy + s * 1.15)],
                fill=(220, 40, 70, 255),
            )
    elif kind == "cool":
        d.rounded_rectangle(
            (size * 0.18, eye_y - eye_r * 1.2, size * 0.82, eye_y + eye_r * 1.4),
            radius=size // 10,
            fill=(25, 30, 40, 240),
        )
        d.line(
            (size * 0.48, eye_y, size * 0.52, eye_y),
            fill=(80, 90, 110, 255),
            width=max(2, size // 28),
        )
    else:
        d.ellipse((left_x - eye_r, eye_y - eye_r, left_x + eye_r, eye_y + eye_r), fill=dark)
        d.ellipse((right_x - eye_r, eye_y - eye_r, right_x + eye_r, eye_y + eye_r), fill=dark)
        d.ellipse(
            (left_x - eye_r * 0.2, eye_y - eye_r * 0.55, left_x + eye_r * 0.35, eye_y - eye_r * 0.05),
            fill=(255, 255, 255, 200),
        )
        d.ellipse(
            (right_x - eye_r * 0.2, eye_y - eye_r * 0.55, right_x + eye_r * 0.35, eye_y - eye_r * 0.05),
            fill=(255, 255, 255, 200),
        )

    mx1, mx2 = size * 0.30, size * 0.70
    my1, my2 = size * 0.48, size * 0.78
    d.arc((mx1, my1, mx2, my2), start=20, end=160, fill=dark, width=max(3, size // 18))
    if kind in {"happy", "heart"}:
        d.chord((mx1 + 4, my1 + 8, mx2 - 4, my2 - 2), start=10, end=170, fill=(255, 120, 120, 180))

    if kind in {"happy", "wink", "heart"}:
        br = size * 0.08
        by = size * 0.55
        d.ellipse(
            (size * 0.18 - br, by - br * 0.6, size * 0.18 + br, by + br * 0.6),
            fill=(255, 120, 140, 90),
        )
        d.ellipse(
            (size * 0.82 - br, by - br * 0.6, size * 0.82 + br, by + br * 0.6),
            fill=(255, 120, 140, 90),
        )
    return img


def _make_sparkle(size: int = 48) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2

    def star(r: float, color: tuple[int, int, int, int]) -> None:
        pts = []
        for i in range(8):
            ang = i * math.pi / 4 - math.pi / 2
            rr = r if i % 2 == 0 else r * 0.35
            pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
        d.polygon(pts, fill=color)

    star(size * 0.42, (255, 230, 120, 255))
    star(size * 0.22, (255, 255, 240, 230))
    return img


def _make_tg_plane(size: int = 78) -> Image.Image:
    """Бумажный самолётик в духе Telegram."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=(34, 158, 217, 255))
    d.ellipse((6, 6, size - 6, size - 6), fill=(42, 171, 238, 255))
    s = size
    plane = [
        (s * 0.22, s * 0.55),
        (s * 0.78, s * 0.28),
        (s * 0.48, s * 0.72),
        (s * 0.40, s * 0.58),
        (s * 0.28, s * 0.68),
    ]
    d.polygon(plane, fill=(255, 255, 255, 255))
    d.line(
        [(s * 0.40, s * 0.58), (s * 0.62, s * 0.42)],
        fill=(34, 158, 217, 220),
        width=max(2, size // 28),
    )
    return img


def _make_arrow_chip(size: int = 56) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=(255, 255, 255, 40))
    mid = size / 2
    d.line(
        [(size * 0.35, size * 0.28), (size * 0.62, mid), (size * 0.35, size * 0.72)],
        fill=(255, 255, 255, 230),
        width=max(3, size // 14),
    )
    return img


class CtaAnimator:
    def __init__(
        self,
        slogan: str | None,
        qr_path: Path | None,
        qr_text: str | None,
        duration: float = 5.0,
        fps: int = FPS,
        style: CtaStyle | str | None = None,
        tg_call: str | None = None,
        show_smileys: bool = True,
        sticker_frames: list[Image.Image] | None = None,
    ) -> None:
        self.duration = max(1.0, float(duration))
        self.fps = fps
        self.total_frames = max(1, int(round(self.duration * self.fps)))
        self.slogan = (slogan or "").strip()
        self.qr_text = (qr_text or "").strip() or None
        self.sticker_frames = [f.convert("RGBA") for f in (sticker_frames or []) if f is not None]
        self.use_sticker = bool(self.sticker_frames)
        # Крупнее QR / текст / стикер в режиме стикерпака
        qr_size = 370 if self.use_sticker else 300
        self.qr = _make_qr_card(qr_path, qr_text, size=qr_size)
        self.show_smileys = show_smileys
        self.tg_call = (tg_call or "").strip() or resolve_tg_call(randomize=True)
        self.link_label = short_link_label(self.qr_text)
        self.sticker_size = 250 if self.use_sticker else 200
        self.sticker_anim_fps = 18.0  # цикл анимации tgs

        if isinstance(style, CtaStyle):
            self.style = style
        else:
            self.style = pick_cta_style(style)

        self.c_bg_a = self.style.bg_a
        self.c_bg_b = self.style.bg_b
        self.c_text = self.style.text
        self.c_line = self.style.line
        self.c_particle = self.style.particle

        self.orb_warm = _make_orb(180, self.style.orb1, 1.0)
        self.orb_cool = _make_orb(210, self.style.orb2, 0.9)
        soft = (255, 255, 255) if not self.style.light_mode else (255, 250, 240)
        self.orb_soft = _make_orb(120, soft, 0.28 if self.style.light_mode else 0.35)

        rng = random.Random(hash(self.style.id) % 10_000)
        self.particles = [
            {
                "x": rng.uniform(0, REEL_W),
                "y": rng.uniform(0, HALF_H),
                "r": rng.uniform(1.2, 2.8),
                "speed": rng.uniform(10, 26),
                "phase": rng.uniform(0, math.tau),
                "alpha": rng.randint(40, 120),
            }
            for _ in range(36)
        ]

        self.title_font = _pick_font(52 if self.use_sticker else 44, bold=True)
        self.call_font = _pick_font(40 if self.use_sticker else 34, bold=True)
        self.link_font = _pick_font(28 if self.use_sticker else 26, bold=False)
        self.slogan_lines = (
            _wrap_text(self.slogan, self.title_font, REEL_W - 160)[:2 if self.use_sticker else 3]
            if self.slogan
            else []
        )
        self._grad_cache: dict[int, Image.Image] = {}

        # Иконки перехода в Telegram
        self.icon_plane = _make_tg_plane(78)
        self.icon_arrow = _make_arrow_chip(52)
        self.icon_sparkle = _make_sparkle(44)
        self.smileys = [
            _make_smiley("happy", 70),
            _make_smiley("wink", 66),
            _make_smiley("heart", 70),
            _make_smiley("cool", 66),
            _make_smiley("fire", 68),
        ]
        # Параметры подпрыгивания для каждой иконки внизу
        self.bounce_items = [
            {"kind": "smiley", "idx": 0, "phase": 0.0, "amp": 14},
            {"kind": "sparkle", "phase": 0.7, "amp": 10},
            {"kind": "smiley", "idx": 1, "phase": 1.2, "amp": 16},
            {"kind": "plane", "phase": 1.8, "amp": 12},
            {"kind": "smiley", "idx": 2, "phase": 2.4, "amp": 15},
            {"kind": "sparkle", "phase": 3.0, "amp": 9},
            {"kind": "smiley", "idx": 3, "phase": 3.5, "amp": 14},
            {"kind": "arrow", "phase": 4.1, "amp": 11},
            {"kind": "smiley", "idx": 4, "phase": 4.6, "amp": 16},
        ]

    def _gradient(self, t: float) -> Image.Image:
        key = int(t * 8)
        if key in self._grad_cache:
            return self._grad_cache[key].copy()

        pulse = 0.5 + 0.5 * math.sin(t * 1.1)
        if self.style.light_mode:
            top = _mix(self.c_bg_a, self.c_bg_b, pulse * 0.25)
            bot = _mix(self.c_bg_b, self.c_bg_a, pulse * 0.2)
        else:
            top = _mix(self.c_bg_a, self.c_bg_b, pulse * 0.35)
            bot = _mix(self.c_bg_b, self.c_bg_a, pulse * 0.4)
        strip = Image.new("RGB", (2, 64))
        px = strip.load()
        for y in range(64):
            col = _mix(top, bot, y / 63)
            px[0, y] = col
            px[1, y] = col
        img = strip.resize((REEL_W, HALF_H), Image.Resampling.BICUBIC)
        self._grad_cache[key] = img.copy()
        return img

    def _paste(self, canvas: Image.Image, overlay: Image.Image, xy: tuple[int, int], opacity: float = 1.0) -> None:
        if opacity <= 0.01:
            return
        img = overlay if overlay.mode == "RGBA" else overlay.convert("RGBA")
        if opacity < 0.999:
            a = img.split()[-1].point(lambda p: int(p * opacity))
            img = img.copy()
            img.putalpha(a)
        canvas.alpha_composite(img, (int(xy[0]), int(xy[1])))

    def render_frame(self, frame_idx: int) -> Image.Image:
        t = frame_idx / self.fps
        u = frame_idx / max(1, self.total_frames - 1)

        base = self._gradient(t).convert("RGBA")

        ox1 = REEL_W * (0.26 + 0.05 * math.sin(t * 0.75))
        oy1 = HALF_H * (0.32 + 0.06 * math.cos(t * 0.55))
        ox2 = REEL_W * (0.74 + 0.04 * math.cos(t * 0.65))
        oy2 = HALF_H * (0.64 + 0.05 * math.sin(t * 0.85))
        ox3 = REEL_W * 0.5
        oy3 = HALF_H * (0.12 + 0.03 * math.sin(t * 1.05))

        for orb, cx, cy in (
            (self.orb_warm, ox1, oy1),
            (self.orb_cool, ox2, oy2),
            (self.orb_soft, ox3, oy3),
        ):
            self._paste(base, orb, (cx - orb.width / 2, cy - orb.height / 2), 1.0)

        pdraw = ImageDraw.Draw(base)
        pr, pg, pb = self.c_particle
        for p in self.particles:
            x = (p["x"] + math.sin(t * 0.55 + p["phase"]) * 26) % REEL_W
            y = (p["y"] - t * p["speed"]) % HALF_H
            a = int(p["alpha"] * (0.5 + 0.5 * math.sin(t * 2.1 + p["phase"])))
            r = p["r"]
            pdraw.ellipse((x - r, y - r, x + r, y + r), fill=(pr, pg, pb, a))

        vig = Image.new("RGBA", (REEL_W, HALF_H), (0, 0, 0, 0))
        v = ImageDraw.Draw(vig)
        outline_a = 70 if self.style.light_mode else 160
        v.rectangle((0, 0, REEL_W, HALF_H), outline=(0, 0, 0, outline_a), width=90)
        vig = vig.filter(ImageFilter.GaussianBlur(40))
        base.alpha_composite(vig)

        qr_appear = _ease_out_back((t - 0.12) / 0.55) if t > 0.12 else 0.0
        line_appear = _ease_out_cubic((t - 0.5) / 0.35) if t > 0.5 else 0.0
        text_appear = _ease_out_cubic((t - 0.7) / 0.55) if t > 0.7 else 0.0
        bottom_appear = _ease_out_cubic((t - 0.95) / 0.55) if t > 0.95 else 0.0

        # Вертикальный ритм: сверху QR → слоган → стикер → призыв
        y = 48 if self.use_sticker else 90
        draw = ImageDraw.Draw(base)
        line_h = 58 if self.use_sticker else 54
        gap_after_qr = 28 if self.use_sticker else 36

        if self.qr is not None and qr_appear > 0:
            breath = 1.0 + 0.012 * math.sin(t * 2.3)
            scale = (0.86 + 0.14 * qr_appear) * breath
            w = max(1, int(self.qr.width * scale))
            h = max(1, int(self.qr.height * scale))
            qr_scaled = self.qr.resize((w, h), Image.Resampling.LANCZOS)
            qx = (REEL_W - w) // 2
            shadow = Image.new("RGBA", (w + 50, h + 50), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(
                (10, 14, w + 40, h + 44),
                radius=24,
                fill=(0, 0, 0, int((70 if self.style.light_mode else 120) * qr_appear)),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            self._paste(base, shadow, (qx - 25, y - 16), 1.0)
            self._paste(base, qr_scaled, (qx, y), qr_appear)
            y += h + gap_after_qr
        else:
            y = 220 if self.use_sticker else 250

        if self.slogan_lines:
            full_w = 110 if self.use_sticker else 96
            cur_w = max(0, int(full_w * line_appear))
            if cur_w > 0:
                lx1 = (REEL_W - cur_w) // 2
                draw.line((lx1, y, lx1 + cur_w, y), fill=(*self.c_line, int(230 * line_appear)), width=3)
            y += 26 if self.use_sticker else 28

            for i, line in enumerate(self.slogan_lines):
                local = _ease_out_cubic(text_appear - i * 0.12)
                if local <= 0:
                    continue
                tw = draw.textlength(line, font=self.title_font)
                tx = (REEL_W - tw) / 2
                rise = int((1 - local) * 26)
                shimmer = 0.93 + 0.07 * math.sin(t * 2.8 + i)
                col = (
                    _clamp_byte(self.c_text[0] * shimmer),
                    _clamp_byte(self.c_text[1] * shimmer),
                    _clamp_byte(self.c_text[2] * shimmer),
                    int(255 * local),
                )
                shadow_col = (255, 255, 255, int(100 * local)) if self.style.light_mode else (0, 0, 0, int(130 * local))
                draw.text((tx + 2, y + i * line_h + rise + 2), line, font=self.title_font, fill=shadow_col)
                draw.text((tx, y + i * line_h + rise), line, font=self.title_font, fill=col)
            y += len(self.slogan_lines) * line_h + (18 if self.use_sticker else 8)

        # === Стикер (смайлы отключены) ===
        if bottom_appear > 0.01 and self.use_sticker:
            self._draw_sticker_block(base, frame_idx, t, bottom_appear, y)

        if u < 0.07:
            fade = _ease_out_cubic(u / 0.07)
            fade_rgb = (245, 241, 232) if self.style.light_mode else (0, 0, 0)
            overlay = Image.new("RGBA", (REEL_W, HALF_H), (*fade_rgb, int(255 * (1 - fade))))
            base.alpha_composite(overlay)

        return base.convert("RGB")

    def _draw_sticker_block(
        self,
        base: Image.Image,
        frame_idx: int,
        t: float,
        appear: float,
        content_y: float,
    ) -> None:
        """Анимированный стикер по центру + призыв TG с нормальными отступами."""
        draw = ImageDraw.Draw(base)
        n = len(self.sticker_frames)
        # Зацикленная анимация (не растягивать на всю длительность CTA)
        idx = int(t * self.sticker_anim_fps) % n
        sticker = self.sticker_frames[idx]

        bounce = math.sin(t * 5.0) * 8
        pulse_scale = 0.96 + 0.04 * abs(math.sin(t * 3.4))
        target = self.sticker_size
        sw = max(1, int(target * pulse_scale))
        sh = max(1, int(target * pulse_scale * sticker.height / max(1, sticker.width)))
        scaled = sticker.resize((sw, sh), Image.Resampling.LANCZOS)

        # место под стикер + тексты снизу
        call_h = 52
        link_h = 40 if self.link_label else 0
        bottom_pad = 28
        block_h = sh + 16 + call_h + link_h + bottom_pad
        # не наложиться на слоган: берём max(content_y, низ экрана - block)
        sy = max(float(content_y), float(HALF_H - block_h - 8)) + bounce
        # если всё же тесно — чуть уменьшим стикер
        if sy + sh + call_h + link_h + bottom_pad > HALF_H - 8:
            scale_fit = max(0.7, (HALF_H - 8 - sy - call_h - link_h - bottom_pad) / max(1, sh))
            sw = max(1, int(sw * scale_fit))
            sh = max(1, int(sh * scale_fit))
            scaled = sticker.resize((sw, sh), Image.Resampling.LANCZOS)

        sx = (REEL_W - sw) // 2

        # лёгкая подложка только под стикер+текст
        band_top = int(sy - 14)
        band_h = int(HALF_H - band_top - 10)
        if band_h > 40:
            band = Image.new("RGBA", (REEL_W, band_h), (0, 0, 0, 0))
            bd = ImageDraw.Draw(band)
            fill = (
                (255, 255, 255, int(150 * appear))
                if self.style.light_mode
                else (8, 12, 18, int(130 * appear))
            )
            bd.rounded_rectangle(
                (56, 0, REEL_W - 56, band_h - 4),
                radius=30,
                fill=fill,
            )
            if not self.style.light_mode:
                bd.rounded_rectangle(
                    (56, 0, REEL_W - 56, band_h - 4),
                    radius=30,
                    outline=(42, 171, 238, int(140 * appear)),
                    width=2,
                )
            base.alpha_composite(band, (0, max(0, band_top)))

        self._paste(base, scaled, (sx, int(sy)), appear)

        call = self.tg_call
        pulse = 0.94 + 0.06 * math.sin(t * 3.6)
        call_col = (
            _clamp_byte(self.c_text[0] * pulse),
            _clamp_byte(self.c_text[1] * pulse),
            _clamp_byte(self.c_text[2] * pulse),
            int(255 * appear),
        )
        tw = draw.textlength(call, font=self.call_font)
        tx = (REEL_W - tw) / 2
        ty = int(sy + sh + 14)
        shadow = (0, 0, 0, int(140 * appear)) if not self.style.light_mode else (255, 255, 255, int(160 * appear))
        draw.text((tx + 2, ty + 2), call, font=self.call_font, fill=shadow)
        draw.text((tx, ty), call, font=self.call_font, fill=call_col)

        if self.link_label:
            link = self.link_label
            lw = draw.textlength(link, font=self.link_font)
            lx = (REEL_W - lw) / 2
            ly = ty + 46
            tg_blue = (90, 190, 245, int(230 * appear)) if not self.style.light_mode else (20, 130, 190, int(240 * appear))
            draw.text((lx, ly), link, font=self.link_font, fill=tg_blue)

    def _draw_transition_footer(self, base: Image.Image, t: float, appear: float) -> None:
        """Анимированные смайлы + призыв перейти в Telegram (fallback)."""
        draw = ImageDraw.Draw(base)
        footer_top = HALF_H - 210

        # мягкая подложка-плашка
        band = Image.new("RGBA", (REEL_W, 210), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        if self.style.light_mode:
            bd.rounded_rectangle(
                (48, 8, REEL_W - 48, 198),
                radius=28,
                fill=(255, 255, 255, int(170 * appear)),
            )
        else:
            bd.rounded_rectangle(
                (48, 8, REEL_W - 48, 198),
                radius=28,
                fill=(8, 12, 18, int(150 * appear)),
            )
            # тонкая бирюзовая обводка (Telegram vibe)
            bd.rounded_rectangle(
                (48, 8, REEL_W - 48, 198),
                radius=28,
                outline=(42, 171, 238, int(160 * appear)),
                width=2,
            )
        base.alpha_composite(band, (0, footer_top))

        # ряд прыгающих иконок
        n = len(self.bounce_items)
        span = REEL_W - 180
        start_x = 90
        icon_y = footer_top + 28
        for i, item in enumerate(self.bounce_items):
            bounce = math.sin(t * 5.2 + item["phase"]) * item["amp"]
            wobble = math.sin(t * 3.4 + item["phase"] * 1.3) * 4
            scale = 0.88 + 0.12 * abs(math.sin(t * 4.0 + item["phase"]))
            local = _ease_out_back(appear - i * 0.04)
            if local <= 0:
                continue

            if item["kind"] == "smiley":
                icon = self.smileys[item["idx"]]
            elif item["kind"] == "plane":
                # самолётик «летит» вправо-влево
                fly = math.sin(t * 2.2) * 10
                icon = self.icon_plane
                wobble += fly
            elif item["kind"] == "sparkle":
                icon = self.icon_sparkle.rotate(
                    (t * 80 + i * 40) % 360,
                    resample=Image.Resampling.BICUBIC,
                    expand=True,
                )
            else:
                icon = self.icon_arrow

            iw = max(1, int(icon.width * scale))
            ih = max(1, int(icon.height * scale))
            scaled = icon.resize((iw, ih), Image.Resampling.LANCZOS)
            cx = start_x + (span * i / max(1, n - 1)) + wobble
            cy = icon_y + bounce
            self._paste(base, scaled, (cx - iw / 2, cy), local)

        # текст призыва
        call = self.tg_call
        pulse = 0.94 + 0.06 * math.sin(t * 3.6)
        call_col = (
            _clamp_byte(self.c_text[0] * pulse),
            _clamp_byte(self.c_text[1] * pulse),
            _clamp_byte(self.c_text[2] * pulse),
            int(255 * appear),
        )
        tw = draw.textlength(call, font=self.call_font)
        tx = (REEL_W - tw) / 2
        ty = footer_top + 112
        # лёгкий бегущий акцент — стрелки «перехода»
        shift = int((math.sin(t * 4.5) * 0.5 + 0.5) * 8)
        shadow = (0, 0, 0, int(140 * appear)) if not self.style.light_mode else (255, 255, 255, int(160 * appear))
        draw.text((tx + 2, ty + 2), call, font=self.call_font, fill=shadow)
        draw.text((tx + shift * 0.15, ty), call, font=self.call_font, fill=call_col)

        # ссылка / @username под призывом
        if self.link_label:
            link = self.link_label
            lw = draw.textlength(link, font=self.link_font)
            lx = (REEL_W - lw) / 2
            ly = ty + 42
            tg_blue = (90, 190, 245, int(230 * appear)) if not self.style.light_mode else (20, 130, 190, int(240 * appear))
            draw.text((lx, ly), link, font=self.link_font, fill=tg_blue)

        # бегущие точечки-«переход» по низу плашки
        for k in range(7):
            px = 120 + k * 130 + math.sin(t * 3 + k) * 8
            py = footer_top + 188 + math.cos(t * 4 + k * 0.7) * 3
            a = int((90 + 80 * abs(math.sin(t * 2.5 + k))) * appear)
            r = 2.5 + abs(math.sin(t * 3 + k))
            draw.ellipse((px - r, py - r, px + r, py + r), fill=(42, 171, 238, a))

    def render_preview_png(self, out_path: Path, at_time: float | None = None) -> Path:
        if at_time is None:
            at_time = min(self.duration * 0.75, max(0.0, self.duration - 0.05))
        idx = max(0, min(self.total_frames - 1, int(at_time * self.fps)))
        frame = self.render_frame(idx)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frame.save(out_path, format="PNG")
        return out_path

    def render_video(self, out_path: Path) -> Path:
        from engine import run_cmd

        out_path = out_path.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames_dir = out_path.parent / f"_cta_frames_{out_path.stem}"
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        try:
            for i in range(self.total_frames):
                self.render_frame(i).save(frames_dir / f"f_{i:04d}.png")

            pattern = str(frames_dir / "f_%04d.png")
            cmd = [
                "ffmpeg", "-y", "-hide_banner",
                "-framerate", str(self.fps),
                "-i", pattern,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(self.fps),
                "-t", f"{self.duration:.3f}", "-an",
                str(out_path),
            ]
            proc = run_cmd(cmd, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"CTA ffmpeg:\n{(proc.stderr or '')[-2000:]}")
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)
        return out_path


def create_cta_preview(
    slogan: str | None,
    qr_path: Path | None,
    qr_text: str | None,
    out_path: Path,
    duration: float = 5.0,
    style: str | None = None,
    tg_call: str | None = None,
    show_smileys: bool = True,
    sticker_frames: list[Image.Image] | None = None,
) -> Path:
    return CtaAnimator(
        slogan,
        qr_path,
        qr_text,
        duration=duration,
        style=style,
        tg_call=tg_call,
        show_smileys=show_smileys,
        sticker_frames=sticker_frames,
    ).render_preview_png(out_path)
