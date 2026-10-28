"""Скачивание одного ролика YouTube / Instagram и его название с описанием.

Файл кладётся в папку 1 и используется как верхнее видео рилса.
Обычное горизонтальное видео сразу собирается в шортс 1080×1920.
Повторная ссылка не качается заново.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine import FOLDER_1, REEL_H, REEL_W, VIDEO_EXTS, ensure_dirs, run_cmd

ProgressCb = Callable[[str], None]

_YT_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{6,})",
    re.I,
)
_IG_CODE = re.compile(
    r"instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_-]+)",
    re.I,
)


@dataclass
class LinkedVideo:
    path: Path
    title: str
    description: str
    url: str
    platform: str


def classify_video_url(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if _YT_ID.search(text):
        return "youtube"
    if _IG_CODE.search(text):
        return "instagram"
    return None


def canonical_video_url(raw: str) -> str:
    text = (raw or "").strip()
    platform = classify_video_url(text)
    if platform == "youtube":
        vid = _YT_ID.search(text).group(1)  # type: ignore[union-attr]
        return f"https://www.youtube.com/watch?v={vid}"
    if platform == "instagram":
        code = _IG_CODE.search(text).group(1)  # type: ignore[union-attr]
        return f"https://www.instagram.com/reel/{code}/"
    raise ValueError("Нужна ссылка на ролик YouTube или Instagram, не на канал и не на профиль")


def _file_has_audio(path: Path) -> bool:
    try:
        from engine import probe_has_audio

        return probe_has_audio(path)
    except Exception:
        return False


def _video_size(path: Path) -> tuple[int, int]:
    result = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=False,
    )
    line = (result.stdout or "").strip().splitlines()
    if not line or "," not in line[0]:
        return 0, 0
    width, height = line[0].split(",", 1)
    try:
        return int(width), int(height)
    except ValueError:
        return 0, 0


def _as_shorts(path: Path, log) -> Path:
    """Горизонтальное и квадратное видео → шортс 1080×1920, звук сохраняется.

    Уже вертикальный ролик только доводится до 1080×1920 без размытого фона.
    """
    width, height = _video_size(path)
    if width == REEL_W and height == REEL_H:
        return path
    if width <= 0 or height <= 0:
        raise RuntimeError("Не удалось прочитать размер видео")
    portrait = height > width * 1.15
    if portrait:
        log(f"Вертикальное {width}×{height} → шортс {REEL_W}×{REEL_H}")
        graph = (
            f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
            f"crop={REEL_W}:{REEL_H},setsar=1,fps=30,format=yuv420p[v]"
        )
    else:
        log(f"Обычное видео {width}×{height} → шортс {REEL_W}×{REEL_H}")
        graph = (
            f"[0:v]split[a][b];"
            f"[a]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
            f"crop={REEL_W}:{REEL_H},gblur=sigma=24,setsar=1[bg];"
            f"[b]scale={REEL_W}:-2:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p[v]"
        )
    tmp = path.with_name(f".{path.stem}.shorts.mp4")
    try:
        result = run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-filter_complex",
                graph,
                "-map",
                "[v]",
                "-map",
                "0:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            check=False,
        )
        if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 10_000:
            tail = (result.stderr or result.stdout or "").strip().splitlines()
            detail = tail[-1] if tail else "ffmpeg не собрал шортс"
            raise RuntimeError(f"Не удалось собрать шортс: {detail}")
        if not _file_has_audio(tmp):
            raise RuntimeError("Шортс собрался без звука")
        dest = path.with_suffix(".mp4")
        tmp.replace(dest)
        if path.exists() and path.resolve() != dest.resolve():
            path.unlink()
        return dest
    finally:
        if tmp.exists():
            tmp.unlink()


def _cache_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _read_cache(meta_path: Path, url: str) -> LinkedVideo | None:
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(data.get("url") or "") != url:
        return None
    path = Path(str(data.get("path") or ""))
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
        return None
    return LinkedVideo(
        path=path,
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
        url=url,
        platform=str(data.get("platform") or ""),
    )


def _write_cache(meta_path: Path, item: LinkedVideo) -> None:
    meta_path.write_text(
        json.dumps(
            {
                "url": item.url,
                "path": str(item.path),
                "title": item.title,
                "description": item.description,
                "platform": item.platform,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def download_linked_video(
    raw_url: str,
    *,
    out_dir: Path | None = None,
    on_log: ProgressCb | None = None,
) -> LinkedVideo:
    """Скачать ролик в папку 1. Если эта ссылка уже скачана — вернуть готовый файл."""
    import yt_dlp

    from cookies_util import COOKIES_FILE, cookies_file_ok

    url = canonical_video_url(raw_url)
    platform = classify_video_url(url) or ""
    ensure_dirs()
    folder = out_dir or FOLDER_1
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / f"link_{_cache_key(url)}.json"

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    cached = _read_cache(meta_path, url)
    if cached and _file_has_audio(cached.path):
        path = _as_shorts(cached.path, log)
        if path != cached.path:
            cached = LinkedVideo(
                path=path,
                title=cached.title,
                description=cached.description,
                url=cached.url,
                platform=cached.platform,
            )
            _write_cache(meta_path, cached)
        if on_log:
            on_log(f"Верх уже скачан: {cached.path.name}")
        return cached
    if cached:
        if on_log:
            on_log("Прошлый файл без звука — скачиваю заново")
        try:
            cached.path.unlink()
        except OSError:
            pass

    log(f"Скачиваю верх ({'YouTube' if platform == 'youtube' else 'Instagram'}): {url}")
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "outtmpl": str(folder / "link_%(id)s.%(ext)s"),
        # bv*+ba склеивает картинку и звук. Голый mp4 у YouTube часто без аудио.
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "format_sort": ["vcodec:h264", "acodec:aac", "res", "fps"],
        "overwrites": True,
    }
    if cookies_file_ok(COOKIES_FILE):
        opts["cookiefile"] = str(COOKIES_FILE)
    elif platform == "instagram":
        opts["cookiesfrombrowser"] = ("opera",)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
            filepath = ""
            downloads = info.get("requested_downloads") or []
            if downloads and isinstance(downloads[0], dict):
                filepath = str(downloads[0].get("filepath") or "")
            if not filepath:
                filepath = ydl.prepare_filename(info)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Не удалось скачать ролик: {exc}") from exc

    path = Path(filepath)
    if path.suffix.lower() not in VIDEO_EXTS or not path.is_file():
        vid = str(info.get("id") or "")
        found = None
        if vid:
            for cand in folder.glob(f"link_{vid}.*"):
                if cand.suffix.lower() in VIDEO_EXTS and cand.is_file():
                    found = cand
                    break
        if found is None:
            raise RuntimeError("Ролик скачался, но файл видео не найден")
        path = found

    if not _file_has_audio(path):
        raise RuntimeError("Ролик скачался без звуковой дорожки")

    path = _as_shorts(path, log)

    item = LinkedVideo(
        path=path,
        title=" ".join(str(info.get("title") or "").split()),
        description=" ".join(str(info.get("description") or "").split()),
        url=url,
        platform=platform,
    )
    _write_cache(meta_path, item)
    log(f"Верх сохранён со звуком: {path.name}")
    if item.title:
        log(f"Название источника: {item.title[:140]}")
    return item
