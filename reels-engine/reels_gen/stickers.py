"""Загрузка Telegram sticker-паков и подготовка кадров анимации для CTA.

Ссылка вида https://t.me/addstickers/Buddy_Bear → имя пака Buddy_Bear.
Скачивание через Bot API (REELS_TG_BOT_TOKEN или токен бота из настроек).
Анимация .tgs → PNG-кадры через pyrlottie; .webm → ffmpeg; статика → webp/png.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "stickers"
DEFAULT_STICKER_PACK_URL = "https://t.me/addstickers/Buddy_Bear"
DEFAULT_STICKER_PACK_NAME = "Buddy_Bear"

PACK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:addstickers/)?([A-Za-z0-9_]+)",
    re.IGNORECASE,
)


def parse_pack_name(url_or_name: str) -> str:
    raw = (url_or_name or "").strip()
    if not raw:
        raise ValueError("Укажите ссылку на стикерпак или имя")
    m = PACK_RE.search(raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_]+", raw):
        return raw
    raise ValueError(f"Не понял имя пака из: {raw}")


def resolve_bot_token() -> str:
    for key in ("REELS_TG_BOT_TOKEN", "YT_NOTIFY_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    raise RuntimeError(
        "Нет Telegram bot token для стикеров. Задайте REELS_TG_BOT_TOKEN "
        "или токен бота в настройках программы."
    )


def _api(token: str, method: str, **params) -> dict:
    q = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{token}/{method}?{q}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API {method}: HTTP {exc.code}\n{body[:400]}") from exc
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API {method}: {data.get('description') or data}")
    return data["result"]


def _download(token: str, file_id: str, dest: Path) -> Path:
    info = _api(token, "getFile", file_id=file_id)
    path = info.get("file_path")
    if not path:
        raise RuntimeError("getFile не вернул file_path")
    url = f"https://api.telegram.org/file/bot{token}/{path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest


@dataclass
class StickerInfo:
    index: int
    emoji: str
    file_id: str
    is_animated: bool
    is_video: bool
    thumb_path: Path | None
    source_path: Path | None
    frames_dir: Path

    @property
    def label(self) -> str:
        em = self.emoji or "▫️"
        kind = "anim" if self.is_animated else ("video" if self.is_video else "static")
        return f"{self.index + 1}. {em} ({kind})"


@dataclass
class StickerPack:
    name: str
    title: str
    stickers: list[StickerInfo]
    root: Path

    def pick(self, selection: str | int | None) -> StickerInfo:
        if not self.stickers:
            raise RuntimeError("В паке нет стикеров")
        if selection is None or selection == "" or selection == "random":
            return random.choice(self.stickers)
        if isinstance(selection, int):
            return self.stickers[selection % len(self.stickers)]
        s = str(selection).strip().lower()
        if s in {"random", "rand", "случайный", "*"}:
            return random.choice(self.stickers)
        if s.isdigit():
            return self.stickers[int(s) % len(self.stickers)]
        for st in self.stickers:
            if st.emoji == selection or st.label.lower() == s:
                return st
        return random.choice(self.stickers)


def pack_dir(name: str) -> Path:
    return CACHE / name


def load_cached_pack(name: str) -> StickerPack | None:
    root = pack_dir(name)
    meta_path = root / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    stickers: list[StickerInfo] = []
    for item in meta.get("stickers") or []:
        idx = int(item["index"])
        stickers.append(
            StickerInfo(
                index=idx,
                emoji=str(item.get("emoji") or ""),
                file_id=str(item.get("file_id") or ""),
                is_animated=bool(item.get("is_animated")),
                is_video=bool(item.get("is_video")),
                thumb_path=_maybe_path(item.get("thumb")),
                source_path=_maybe_path(item.get("source")),
                frames_dir=root / f"{idx:02d}_frames",
            )
        )
    return StickerPack(
        name=str(meta.get("name") or name),
        title=str(meta.get("title") or name),
        stickers=stickers,
        root=root,
    )


def _maybe_path(raw) -> Path | None:
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else None


def fetch_sticker_pack(url_or_name: str, *, on_log=None, force: bool = False) -> StickerPack:
    name = parse_pack_name(url_or_name)
    if not force:
        cached = load_cached_pack(name)
        if cached and cached.stickers:
            if on_log:
                on_log(f"Пак из кеша: {cached.title} ({len(cached.stickers)} шт.)")
            return cached

    token = resolve_bot_token()
    if on_log:
        on_log(f"Загружаю пак {name}…")
    result = _api(token, "getStickerSet", name=name)
    title = str(result.get("title") or name)
    raw_stickers = list(result.get("stickers") or [])
    if not raw_stickers:
        raise RuntimeError(f"Пак «{name}» пустой")

    root = pack_dir(name)
    root.mkdir(parents=True, exist_ok=True)
    stickers: list[StickerInfo] = []
    meta_items = []

    for i, st in enumerate(raw_stickers):
        emoji = str(st.get("emoji") or "")
        is_animated = bool(st.get("is_animated"))
        is_video = bool(st.get("is_video"))
        file_id = str(st.get("file_id") or "")
        ext = ".tgs" if is_animated else (".webm" if is_video else ".webp")
        source = root / f"{i:02d}{ext}"
        thumb_path = root / f"{i:02d}_thumb.webp"
        if on_log:
            on_log(f"Стикер {i + 1}/{len(raw_stickers)} {emoji}")
        try:
            _download(token, file_id, source)
        except Exception as exc:
            if on_log:
                on_log(f"  пропуск файла: {exc}")
            source = None  # type: ignore
        th = st.get("thumbnail") or st.get("thumb")
        if th and th.get("file_id"):
            try:
                _download(token, th["file_id"], thumb_path)
            except Exception:
                thumb_path = None  # type: ignore
        else:
            thumb_path = None  # type: ignore

        info = StickerInfo(
            index=i,
            emoji=emoji,
            file_id=file_id,
            is_animated=is_animated,
            is_video=is_video,
            thumb_path=thumb_path if thumb_path and Path(thumb_path).is_file() else None,
            source_path=source if source and Path(source).is_file() else None,
            frames_dir=root / f"{i:02d}_frames",
        )
        stickers.append(info)
        meta_items.append(
            {
                "index": i,
                "emoji": emoji,
                "file_id": file_id,
                "is_animated": is_animated,
                "is_video": is_video,
                "thumb": str(info.thumb_path) if info.thumb_path else "",
                "source": str(info.source_path) if info.source_path else "",
            }
        )

    meta = {"name": name, "title": title, "stickers": meta_items}
    (root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if on_log:
        on_log(f"Готово: {title} — {len(stickers)} стикеров")
    return StickerPack(name=name, title=title, stickers=stickers, root=root)


def _run_ffmpeg(cmd: list[str]) -> None:
    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **flags)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "")[-400:])


def _frames_from_tgs(tgs: Path, out_dir: Path, *, size: int = 256, fps: int = 20) -> list[Path]:
    from pyrlottie import LottieFile, convSingleLottieTransparentFrames

    out_dir.mkdir(parents=True, exist_ok=True)
    # frameSkip: исходный tgs часто 60fps → берём каждый 3-й ≈ 20fps
    skip = max(1, int(round(60 / max(1, fps))))
    scale = max(0.2, min(1.0, size / 512.0))
    lf = LottieFile(str(tgs))
    res = asyncio.run(convSingleLottieTransparentFrames(lf, frameSkip=skip, scale=scale))
    lfrm = next(iter(res.values()))
    frames = list(lfrm.frames or [])
    if not frames:
        raise RuntimeError("pyrlottie не вернул кадры")
    paths: list[Path] = []
    for i, img in enumerate(frames):
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        # добить до size
        if max(img.size) != size:
            img = img.copy()
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
            img = canvas
        path = out_dir / f"f_{i:04d}.png"
        img.save(path)
        paths.append(path)
    return paths


def _frames_from_webm(webm: Path, out_dir: Path, *, size: int = 256, fps: int = 20) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "f_%04d.png")
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    _run_ffmpeg(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(webm),
            "-vf", f"fps={fps},scale={size}:{size}:force_original_aspect_ratio=decrease,"
                   f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=0x00000000",
            "-pix_fmt", "rgba",
            pattern,
        ]
    )
    paths = sorted(out_dir.glob("f_*.png"))
    if not paths:
        raise RuntimeError("ffmpeg не извлёк кадры из webm")
    return paths


def _frames_from_static(src: Path, out_dir: Path, *, size: int = 256, n: int = 12) -> list[Path]:
    """Статика: несколько одинаковых кадров (лёгкий bounce делается в CTA)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    paths = []
    for i in range(n):
        path = out_dir / f"f_{i:04d}.png"
        canvas.save(path)
        paths.append(path)
    return paths


def prepare_sticker_frames(
    sticker: StickerInfo,
    *,
    size: int = 256,
    fps: int = 20,
    force: bool = False,
    on_log=None,
) -> list[Image.Image]:
    """Готовит список RGBA-кадров для CTA (с кешем на диске)."""
    out_dir = sticker.frames_dir
    marker = out_dir / "_ready.json"
    if not force and marker.is_file():
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        paths = sorted(out_dir.glob("f_*.png"))
        if paths and int(meta.get("size") or 0) == int(size):
            return [Image.open(p).convert("RGBA") for p in paths]

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = sticker.source_path
    if src and src.is_file():
        if on_log:
            on_log(f"Готовлю анимацию стикера {sticker.label}…")
        if sticker.is_animated and src.suffix.lower() == ".tgs":
            paths = _frames_from_tgs(src, out_dir, size=size, fps=fps)
        elif sticker.is_video or src.suffix.lower() == ".webm":
            paths = _frames_from_webm(src, out_dir, size=size, fps=fps)
        else:
            paths = _frames_from_static(src, out_dir, size=size)
    elif sticker.thumb_path and sticker.thumb_path.is_file():
        if on_log:
            on_log(f"Только превью (нет исходника): {sticker.label}")
        paths = _frames_from_static(sticker.thumb_path, out_dir, size=size)
    else:
        raise RuntimeError(f"Нет файла стикера: {sticker.label}")

    marker.write_text(
        json.dumps({"count": len(paths), "size": size, "fps": fps}, ensure_ascii=False),
        encoding="utf-8",
    )
    return [Image.open(p).convert("RGBA") for p in paths]


def load_sticker_frames_for_cta(
    url_or_name: str | None,
    selection: str | int | None = "random",
    *,
    size: int = 320,
    on_log=None,
) -> list[Image.Image] | None:
    """Удобный вход для CTA: None если пак не задан."""
    raw = (url_or_name or "").strip()
    if not raw:
        return None
    pack = fetch_sticker_pack(raw, on_log=on_log, force=False)
    sticker = pack.pick(selection)
    if on_log:
        on_log(f"Выбран стикер: {sticker.label}")
    return prepare_sticker_frames(sticker, size=size, on_log=on_log)
