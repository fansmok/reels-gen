"""Playwright или Patchright (CDP-leak fix) — drop-in импорт."""

from __future__ import annotations

try:
    from patchright.sync_api import Error as PlaywrightError
    from patchright.sync_api import Page
    from patchright.sync_api import TimeoutError as PlaywrightTimeoutError
    from patchright.sync_api import sync_playwright

    ENGINE = "patchright"
except ImportError:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Page
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    ENGINE = "playwright"


def warn_if_not_patchright(*, strict: bool = False) -> None:
    """Patchright отключает CDP Runtime.enable leak; без него — громкое предупреждение."""
    if ENGINE == "patchright":
        return
    print(
        "\n!!! ВНИМАНИЕ: Patchright не установлен — активен CDP Runtime.enable leak.\n"
        "    Установите: pip install patchright && patchright install chrome\n"
        "    Без Patchright fingerprint легче детектируется на CreepJS / DataDome.\n",
        flush=True,
    )
    if strict:
        raise SystemExit(2)
