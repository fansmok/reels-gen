"""Пакет генератора двойных рилсов (reels_gen)."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
FOLDER_1 = PACKAGE_ROOT / "1"
FOLDER_2 = PACKAGE_ROOT / "2"
OUTPUT = PACKAGE_ROOT / "output"
ASSETS = PACKAGE_ROOT / "assets"
UPLOAD_STAGING = PACKAGE_ROOT / "upload_queue"
