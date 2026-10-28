"""Подготовка роликов и загрузка на YouTube Shorts через vk-bot."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from meta import meta_for_file

PACKAGE_ROOT = Path(__file__).resolve().parent
OUTPUT = PACKAGE_ROOT / "output"
UPLOAD_STAGING = PACKAGE_ROOT / "upload_queue"

ProgressCb = Callable[[str], None]

DEFAULT_VK_BOT = Path(str(os.environ.get("REELS_VK_BOT") or "").strip())
LOCAL_UPLOADER = "local_reels_upload.py"


def _log(cb: ProgressCb | None, msg: str) -> None:
    if cb:
        cb(msg)


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def make_reels_cover(video: Path, out_jpg: Path) -> Path:
    """Простой кадр без текста (fallback)."""
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", "0.4", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out_jpg),
    ]
    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **flags)
    if proc.returncode != 0 or not out_jpg.exists():
        from PIL import Image

        Image.new("RGB", (1080, 1920), (10, 14, 20)).save(out_jpg, quality=90)
    return out_jpg


def stage_reels_for_upload(
    videos: list[Path],
    *,
    tg_link: str | None = None,
    title_base: str | None = None,
    triggers_text: str | None = None,
    phrases: list[str] | None = None,
    desc_hooks_text: str | None = None,
    desc_template: str | None = None,
    manual_description: str | None = None,
    extra_hashtags: str | None = None,
    permanent_hashtags: str | None = None,
    use_custom_meta: bool = False,
    custom_titles: list[str] | None = None,
    custom_descriptions: list[str] | None = None,
    apply_triggers: bool = True,
    job_name: str | None = None,
    cover_style: dict | None = None,
    cover_bottom_map: dict[str, str] | None = None,
    cover_top_map: dict[str, str] | None = None,
    on_log: ProgressCb | None = None,
) -> list[dict]:
    import random

    from cover import CoverStyle, make_cover_for_reel, resolve_source_video

    stamp = time.strftime("%Y%m%d_%H%M%S")
    job = UPLOAD_STAGING / (job_name or f"job_{stamp}")
    job.mkdir(parents=True, exist_ok=True)
    phrase_pool = [p.strip() for p in (phrases or []) if p and str(p).strip()]
    style = CoverStyle.from_dict(cover_style) if cover_style else CoverStyle(enabled=False)
    if str(style.source or "").strip().lower() not in {"top", "bottom", "split"}:
        style.source = "bottom"
    bottom_map = {str(Path(k).resolve()): str(Path(v).resolve()) for k, v in (cover_bottom_map or {}).items()}
    top_map = {str(Path(k).resolve()): str(Path(v).resolve()) for k, v in (cover_top_map or {}).items()}

    items: list[dict] = []
    for i, src in enumerate(videos, 1):
        src = Path(src)
        if not src.exists():
            _log(on_log, f"Пропуск (нет файла): {src}")
            continue
        meta = meta_for_file(
            src.stem,
            tg_link=tg_link,
            base_title=title_base,
            triggers_text=triggers_text,
            phrases=phrase_pool,
            index=i - 1,
            desc_hooks_text=desc_hooks_text,
            desc_template=desc_template,
            manual_description=manual_description,
            extra_hashtags=extra_hashtags,
            permanent_hashtags=permanent_hashtags,
            use_custom_meta=bool(use_custom_meta),
            custom_titles=custom_titles,
            custom_descriptions=custom_descriptions,
            apply_triggers=bool(apply_triggers),
        )
        uid = meta["uid"]
        folder = job / f"reel_{i:02d}_{uid}"
        folder.mkdir(parents=True, exist_ok=True)
        video_name = f"{uid}_reels_{stamp}.mp4"
        video_dst = folder / video_name
        shutil.copy2(src, video_dst)
        cover = folder / f"{uid}_reels.jpg"
        cover_phrase = (meta.get("cover_phrase") or meta["title"] or "").strip().upper()
        # text_source: templates = заготовки из обложки; titles = заголовок рилса
        text_src = str(getattr(style, "text_source", "titles") or "titles").lower()
        if text_src in {"templates", "template", "phrases"}:
            cover_phrase = style.pick_phrase(random.Random(f"{uid}-cover-{i}")).strip().upper()
            if style.uppercase:
                cover_phrase = cover_phrase.upper()

        bottom_hint = None
        top_hint = None
        want = str(style.source or "bottom").lower()
        try:
            key = str(src.resolve())
        except Exception:
            key = ""
        if want in {"top", "split"} and key:
            mapped_top = top_map.get(key)
            if mapped_top and Path(mapped_top).is_file():
                top_hint = Path(mapped_top)
        if want in {"bottom", "split"} and key:
            mapped = bottom_map.get(key)
            if mapped and Path(mapped).is_file():
                bottom_hint = Path(mapped)
        if top_hint is None and want in {"top", "split"}:
            top_hint = resolve_source_video(src, "top")
        if bottom_hint is None and want in {"bottom", "split"}:
            bottom_hint = resolve_source_video(src, "bottom")

        if style.enabled:
            try:
                make_cover_for_reel(
                    src,
                    cover,
                    style,
                    top_hint=top_hint,
                    bottom_hint=bottom_hint,
                    phrase=cover_phrase,
                    rng=random.Random(f"{uid}-{i}"),
                    on_log=on_log,
                )
            except Exception as exc:  # noqa: BLE001
                _log(on_log, f"  обложка (fallback): {exc}")
                make_reels_cover(video_dst, cover)
        else:
            make_reels_cover(video_dst, cover)
        item = {
            "LIVE_TITLE": meta["title"],
            "YT_DESC": meta["description"],
            "YOUTUBE_DESC": meta["description"],
            "RELS": str(video_dst.resolve()),
            "VIDEO": str(video_dst.resolve()),
            "PHOTO": str(cover.resolve()),
            "source": str(src.resolve()),
            "uid": uid,
            "hashtags": meta.get("hashtags", ""),
            "cover_from": str(bottom_hint.resolve()) if bottom_hint and Path(bottom_hint).is_file() else "",
        }
        items.append(item)
        _log(on_log, f"Stage [{i}/{len(videos)}]: {video_name}")
        _log(on_log, f"  title: {meta['title']}")
        if bottom_hint and Path(bottom_hint).is_file():
            _log(on_log, f"  cover video: {Path(bottom_hint).name}")
        _log(on_log, f"  cover: {cover_phrase[:60]}")
        _log(on_log, f"  desc: {meta['description'][:80]}…")
    queue_path = job / "queue.json"
    queue_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(on_log, f"Очередь: {queue_path} ({len(items)} шт.)")
    return items


def resolve_vk_bot_dir(yda_root: str | Path | None = None) -> Path:
    try:
        import plain_profiles

        return plain_profiles.read_vk_bot_dir(yda_root)
    except Exception:
        return DEFAULT_VK_BOT


def youtube_plain_profile_dir(vk_bot: Path, acc: int) -> Path:
    """user-data Chrome для plain YouTube-профиля (#1 без суффикса)."""
    n = int(acc)
    if n <= 1:
        return Path(vk_bot) / "profiles_youtube_plain"
    return Path(vk_bot) / f"profiles_youtube_plain_{n}"


def _kill_chrome_using_profile(udir: Path, on_log: ProgressCb | None = None) -> int:
    """Закрыть только Chrome, запущенные с этим user-data-dir. Возвращает число PID."""
    if sys.platform != "win32":
        return 0
    udir = Path(udir)
    # Полный путь может отличаться кодировкой в CommandLine — ищем по имени папки профиля
    markers = {
        udir.name.lower(),
        str(udir.resolve()).lower(),
        str(udir).lower(),
    }
    killed = 0
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        raw = (proc.stdout or "").strip()
        if not raw:
            return 0
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        for row in data or []:
            cmd = str(row.get("CommandLine") or "").lower()
            pid = int(row.get("ProcessId") or 0)
            if not pid or not cmd:
                continue
            if not any(m and m in cmd for m in markers):
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                killed += 1
                _log(on_log, f"  закрыл Chrome PID {pid} (держил профиль)")
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        _log(on_log, f"  не удалось проверить Chrome: {exc}")
    if killed:
        time.sleep(1.5)
    return killed


def prepare_youtube_profile(udir: Path, on_log: ProgressCb | None = None) -> None:
    """Снять залипшие локи профиля перед Playwright launch_persistent_context."""
    udir = Path(udir)
    if not udir.is_dir():
        return
    killed = _kill_chrome_using_profile(udir, on_log=on_log)
    if killed:
        time.sleep(1.2)
    lock_names = (
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
        "lockfile",
        "DevToolsActivePort",
    )
    removed = 0
    for name in lock_names:
        p = udir / name
        if not p.exists():
            continue
        try:
            p.unlink()
            removed += 1
        except OSError:
            # ещё держит процесс — ещё раз попробуем убить и удалить
            _kill_chrome_using_profile(udir, on_log=on_log)
            time.sleep(0.8)
            try:
                p.unlink()
                removed += 1
            except OSError as exc:
                _log(on_log, f"  не снят лок {name}: {exc}")
    if removed or killed:
        _log(on_log, f"Профиль готов: снято локов={removed}, закрыто chrome={killed}")
    stuck = udir / "lockfile"
    if stuck.exists():
        raise RuntimeError(
            f"Профиль Chrome занят и не освободился: {udir}\n"
            "Закройте все окна YouTube/Chrome этого аккаунта и повторите загрузку."
        )


def distribute_exclusive(
    items: list[dict],
    account_numbers: list[int],
    per_account: int,
) -> dict[int, list[dict]]:
    """
    Каждый ролик — только в один аккаунт.
    На аккаунт не больше per_account штук.
    Лишние ролики не распределяются (остаются незалитыми).
    """
    if per_account < 1:
        per_account = 1
    buckets: dict[int, list[dict]] = {int(a): [] for a in account_numbers}
    accs = [int(a) for a in account_numbers]
    idx = 0
    for item in items:
        placed = False
        # ищем аккаунт с свободным слотом, начиная с текущего
        for offset in range(len(accs)):
            acc = accs[(idx + offset) % len(accs)]
            if len(buckets[acc]) < per_account:
                buckets[acc].append(item)
                idx = (accs.index(acc) + 1) % len(accs)
                placed = True
                break
        if not placed:
            break  # все аккаунты заполнены
    return buckets


def resolve_uploader_python(python_exe: str | Path | None = None) -> str:
    """Берём указанный Python или текущий интерпретатор."""
    if python_exe:
        p = Path(str(python_exe))
        if p.is_file():
            return str(p)
    return sys.executable


def _run_uploader(
    cmd: list[str],
    *,
    cwd: str,
    env: dict,
    on_log: ProgressCb | None = None,
) -> int:
    """Запуск загрузчика с живым логом в GUI (не ждём конца, чтобы не «молчало»)."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\r\n")
        if line:
            _log(on_log, line)
    return int(proc.wait())


def upload_staged_reels(
    items: list[dict],
    account_numbers: list[int],
    *,
    per_account: int = 1,
    delay_sec: float = 0.0,
    yda_root: str | Path | None = None,
    python_exe: str | Path | None = None,
    on_log: ProgressCb | None = None,
) -> tuple[int, int]:
    """
    Загрузка без повторов: ролик уходит только в один аккаунт.
    per_account — сколько рилсов максимум на один профиль.
    delay_sec — пауза перед переходом к следующему аккаунту.
    """
    if not items:
        raise ValueError("Нет роликов для загрузки")
    if not account_numbers:
        raise ValueError("Не выбран ни один профиль для загрузки")

    vk_bot = resolve_vk_bot_dir(yda_root)
    uploader = vk_bot / LOCAL_UPLOADER
    if not uploader.is_file():
        raise FileNotFoundError(f"Не найден {uploader}")

    py = resolve_uploader_python(python_exe)
    _log(on_log, f"Python загрузчика: {py}")
    buckets = distribute_exclusive(items, account_numbers, per_account)

    capacity = len(account_numbers) * max(1, int(per_account))
    if len(items) > capacity:
        _log(
            on_log,
            f"Внимание: роликов {len(items)}, слотов {capacity} "
            f"({len(account_numbers)} акк x {per_account}). Лишние не загрузятся.",
        )

    ok = 0
    total = 0
    ordered = [a for a in account_numbers if buckets.get(int(a))]
    for bi, acc in enumerate(ordered):
        chunk = buckets[int(acc)]
        if not chunk:
            continue
        if bi > 0 and delay_sec > 0:
            _log(on_log, f"Пауза {delay_sec:.0f} с перед аккаунтом #{acc}...")
            time.sleep(float(delay_sec))

        # Проверка файлов до запуска браузера
        for it in chunk:
            video = Path(str(it.get("RELS") or it.get("VIDEO") or ""))
            if not video.is_file():
                raise FileNotFoundError(f"Нет видео для загрузки: {video}")

        udir = youtube_plain_profile_dir(vk_bot, int(acc))
        _log(on_log, f"— Загрузка {len(chunk)} рилсов на профиль #{acc} —")
        _log(on_log, f"  Chrome profile: {udir}")
        _log(on_log, "  Режим: Google Chrome maximized + proxy (без CFT/кривого UI)")
        try:
            prepare_youtube_profile(udir, on_log=on_log)
        except Exception as exc:
            _log(on_log, f"Профиль #{acc}: недоступен ({exc}) — пропускаю")
            total += len(chunk)
            continue

        for it in chunk:
            _log(on_log, f"  -> {it.get('LIVE_TITLE', '')[:70]}")

        qpath = UPLOAD_STAGING / f"_upload_acc_{acc}_{int(time.time())}.json"
        qpath.write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding="utf-8")

        env = os.environ.copy()
        env["YOUTUBE_SKIP_ENTER"] = "1"
        env["YOUTUBE_ACC_NUMBER"] = str(acc)
        env["YOUTUBE_VIDEO_COLUMN"] = "RELS"
        env["YOUTUBE_RESULTS_SHEET_TAG"] = "reels_gen"
        env["YOUTUBE_MAX_UPLOADS"] = str(len(chunk))
        env["VIDEO_NO_WAIT_FOR_GENERATOR"] = "1"
        env["YOUTUBE_MANUAL_FIRST"] = "0"
        env["YOUTUBE_WIN_FORCE_CDP"] = "1"
        env["YOUTUBE_USE_PERSISTENT_LAUNCH"] = "0"
        env["REELS_LOCAL_QUEUE"] = str(qpath.resolve())
        env["YOUTUBE_BROWSER_LAUNCH_TIMEOUT_MS"] = "60000"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [py, "-u", str(uploader), "--queue", str(qpath), "--acc", str(acc)]

        code = _run_uploader(cmd, cwd=str(vk_bot), env=env, on_log=on_log)

        # Один повтор только если похоже на лок профиля
        if code != 0:
            _log(on_log, f"Профиль #{acc}: код {code} — очищаю лок и 1 повтор")
            try:
                prepare_youtube_profile(udir, on_log=on_log)
            except Exception as exc:
                _log(on_log, f"Профиль #{acc}: не освободился ({exc}) — следующий аккаунт")
                try:
                    _kill_chrome_using_profile(udir, on_log=on_log)
                except Exception:
                    pass
                total += len(chunk)
                continue
            time.sleep(1.0)
            code = _run_uploader(cmd, cwd=str(vk_bot), env=env, on_log=on_log)

        # После ошибки всегда гасим Chrome этого профиля, чтобы не копить окна
        if code != 0:
            try:
                _kill_chrome_using_profile(udir, on_log=on_log)
            except Exception:
                pass

        total += len(chunk)
        if code == 0:
            ok += len(chunk)
            _log(on_log, f"Профиль #{acc}: OK ({len(chunk)})")
        else:
            _log(
                on_log,
                f"Профиль #{acc}: недоступен/ошибка (код {code}) — перехожу к следующему",
            )
    return ok, total


def list_output_videos() -> list[Path]:
    if not OUTPUT.exists():
        return []
    return sorted(
        [p for p in OUTPUT.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
