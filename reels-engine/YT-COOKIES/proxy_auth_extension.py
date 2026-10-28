"""Chrome MV2 extension: автоматический ввод логина/пароля прокси (407).

Patchright передаёт auth через CDP — JS/статика YouTube часто не догружаются (белый экран).
Расширение перехватывает onAuthRequired для всех запросов; Chrome for Testing остаётся.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProxyAuthExtension:
    path: Path

    def close(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def create_proxy_auth_extension(username: str, password: str) -> ProxyAuthExtension:
    root = Path(tempfile.mkdtemp(prefix="yt_proxy_auth_ext_"))
    manifest = {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "YT Proxy Auth",
        "permissions": [
            "webRequest",
            "webRequestBlocking",
            "proxy",
            "<all_urls>",
        ],
        "background": {
            "scripts": ["background.js"],
            "persistent": True,
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    background = f"""chrome.webRequest.onAuthRequired.addListener(
  function() {{
    return {{
      authCredentials: {{
        username: {json.dumps(username)},
        password: {json.dumps(password)},
      }},
    }};
  }},
  {{ urls: ["<all_urls>"] }},
  ["blocking"]
);
"""
    (root / "background.js").write_text(background, encoding="utf-8")
    return ProxyAuthExtension(path=root)


def extension_launch_args(ext: ProxyAuthExtension) -> list[str]:
    p = str(ext.path.resolve())
    return [
        f"--disable-extensions-except={p}",
        f"--load-extension={p}",
    ]
