"""
Точка входа.
Без аргументов — GUI. С --top/--count — CLI.
"""

from __future__ import annotations

import argparse
import sys

from engine import (
    FOLDER_2,
    OUTPUT,
    QR_DIR,
    create_cta_frame,
    ensure_dirs,
    ffmpeg_ok,
    generate_batch,
    pick_random_bottoms,
    resolve_qr,
)


def _fix_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Генератор двойных рилсов")
    parser.add_argument("--gui", action="store_true", help="Запустить GUI")
    parser.add_argument("--top", type=str, help="Видео сверху (имя или путь)")
    parser.add_argument("--count", type=int, help="Сколько рилсов")
    parser.add_argument("--slogan", type=str, default=None)
    parser.add_argument("--qr", type=str, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--cta", type=float, default=5.0, help="Секунды CTA")
    parser.add_argument("--preview-cta", action="store_true")
    # баннер на паузе (опционально)
    parser.add_argument("--banner", action="store_true", help="Включить баннер на паузе")
    parser.add_argument("--banner-text", type=str, default="ПОДПИШИСЬ", help="Текст баннера (варианты через |)")
    parser.add_argument("--banner-style", type=str, default="random", help="glass|neon|gradient|minimal|pill|random")
    parser.add_argument("--banner-at", type=float, default=3.0, help="Секунда паузы верхнего видео")
    parser.add_argument("--banner-dur", type=float, default=4.0, help="Длительность баннера (без аудио)")
    parser.add_argument("--banner-audio", type=str, default=None, help="Аудио для баннера (длина = длине трека)")
    parser.add_argument("--banner-place", type=str, default="mid", help="mid | end | both")
    parser.add_argument("--preview-banner", action="store_true", help="Сохранить кадр баннера")
    return parser.parse_args()


def banner_opts_from_args(args: argparse.Namespace) -> dict:
    return {
        "enabled": bool(args.banner),
        "text": str(args.banner_text or "").replace("|", "\n"),
        "style": args.banner_style or "random",
        "at_sec": float(args.banner_at or 0),
        "duration": float(args.banner_dur or 0),
        "audio": args.banner_audio or "",
        "place": args.banner_place or "mid",
    }


def resolve_top(top_arg: str):
    from pathlib import Path
    from engine import FOLDER_1

    path = Path(top_arg)
    if path.exists() and path.is_file():
        return path.resolve()
    candidate = FOLDER_1 / top_arg
    if candidate.exists() and candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"Видео сверху не найдено: {top_arg}")


def main() -> None:
    _fix_stdio()
    ensure_dirs()
    args = parse_args()

    # GUI по умолчанию, если нет CLI-аргументов
    wants_cli = any(
        [
            args.top is not None,
            args.count is not None,
            args.preview_cta,
            args.preview_banner,
        ]
    )
    if args.gui or not wants_cli:
        if not ffmpeg_ok():
            print("Нужны ffmpeg и ffprobe в PATH.")
        from app import main as gui_main

        gui_main()
        return

    if not ffmpeg_ok():
        print("Нужны ffmpeg и ffprobe в PATH.")
        sys.exit(1)

    if args.preview_cta:
        qr_path, qr_text = resolve_qr(args.qr)
        out = QR_DIR / "cta_preview.png"
        create_cta_frame(
            args.slogan or "Ваш слоган здесь",
            qr_path,
            qr_text or "https://example.com",
            out,
        )
        print(f"Превью CTA: {out}")
        return

    if args.preview_banner:
        from banner_cta import create_banner_preview, resolve_banner_text

        b = banner_opts_from_args(args)
        out = QR_DIR / "banner_preview.png"
        create_banner_preview(
            resolve_banner_text(b["text"], randomize=False),
            out,
            style=b["style"],
            duration=b["duration"] or 4.0,
        )
        print(f"Превью баннера: {out}")
        return

    if not args.top or not args.count:
        print("Нужны --top и --count, либо запуск без аргументов (GUI).")
        sys.exit(2)

    top = resolve_top(args.top)
    bottoms = pick_random_bottoms(args.count, seed=args.seed)
    qr_path, qr_text = resolve_qr(args.qr)

    print(f"Верх: {top.name}")
    print(f"Рилсов: {args.count}")
    ok, total, files = generate_batch(
        top,
        bottoms,
        args.slogan,
        qr_path,
        qr_text,
        cta_seconds=args.cta,
        banner=banner_opts_from_args(args),
        on_log=print,
    )
    print(f"Готово: {ok}/{total}. Папка: {OUTPUT}")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
