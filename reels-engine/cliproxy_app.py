"""Заглушка: внешний кабинет прокси в публичной сборке не подключен."""
from __future__ import annotations

METHOD_APP = "app"
SETTINGS_KEYS = {"method": "cliproxy_method"}


def normalize_method(raw) -> str:
    return str(raw or "site").strip().lower() or "site"


def geo_lookup_socks5(*_a, **_k):
    return {}


def get_proxy_for_ip(*_a, **_k):
    return None, "Укажите прокси вручную (host:port:login:password)"
