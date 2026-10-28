"""Парсер information.txt — извлекает параметры ПК для fingerprint браузера."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# locale по коду страны (если в файле нет явного Language/Locale)
COUNTRY_LOCALE: dict[str, str] = {
    "IN": "en-IN",
    "US": "en-US",
    "GB": "en-GB",
    "UK": "en-GB",
    "AU": "en-AU",
    "CA": "en-CA",
    "RU": "ru-RU",
    "DE": "de-DE",
    "FR": "fr-FR",
    "ES": "es-ES",
    "IT": "it-IT",
    "BR": "pt-BR",
    "MX": "es-MX",
    "JP": "ja-JP",
    "KR": "ko-KR",
    "CN": "zh-CN",
    "TW": "zh-TW",
    "PL": "pl-PL",
    "NL": "nl-NL",
    "TR": "tr-TR",
    "UA": "uk-UA",
    "ID": "id-ID",
    "PH": "en-PH",
    "PK": "en-PK",
    "BD": "en-BD",
    "VN": "vi-VN",
    "TH": "th-TH",
    "SA": "ar-SA",
    "AE": "ar-AE",
    "EG": "ar-EG",
    "NG": "en-NG",
    "ZA": "en-ZA",
}

# типичный DPR Windows для известных разрешений (если Scale не указан в файле)
# GREASE Not_A Brand version по major Chrome (Client Hints)
NOT_A_BRAND_BY_MAJOR: tuple[tuple[int, str], ...] = (
    (131, "24"),
    (110, "8"),
    (0, "99"),
)


def not_a_brand_version_for_major(major: int | str) -> str:
    try:
        m = int(major)
    except (ValueError, TypeError):
        return "8"
    for threshold, version in NOT_A_BRAND_BY_MAJOR:
        if m >= threshold:
            return version
    return "99"


def build_client_hints_brands(profile: "PCProfile") -> list[dict[str, str]]:
    major = profile.chrome_major or "131"
    nab = not_a_brand_version_for_major(major)
    return [
        {"brand": "Google Chrome", "version": major},
        {"brand": "Chromium", "version": major},
        {"brand": "Not_A Brand", "version": nab},
    ]


def build_client_hints_full_brands(profile: "PCProfile") -> list[dict[str, str]]:
    full = profile.chrome_version or "131.0.0.0"
    nab = not_a_brand_version_for_major(profile.chrome_major or "131")
    return [
        {"brand": "Google Chrome", "version": full},
        {"brand": "Chromium", "version": full},
        {"brand": "Not_A Brand", "version": f"{nab}.0.0.0"},
    ]


def build_client_hints_metadata(profile: "PCProfile") -> dict:
    """Единый источник Client Hints для HTTP-заголовков, CDP и JS userAgentData."""
    return {
        "brands": build_client_hints_brands(profile),
        "fullVersionList": build_client_hints_full_brands(profile),
        "fullVersion": profile.chrome_version or "131.0.0.0",
        "platform": "Windows",
        "platformVersion": profile.platform_version,
        "architecture": "x86",
        "model": "",
        "mobile": False,
        "bitness": "64",
        "wow64": False,
    }


RESOLUTION_DPR: dict[tuple[int, int], float] = {
    (1920, 1080): 1.0,
    (1280, 1024): 1.0,
    (1280, 800): 1.25,
    (1366, 768): 1.0,
    (1440, 900): 1.0,
    (1600, 900): 1.0,
    (1680, 1050): 1.0,
    (1536, 864): 1.25,
    (2560, 1440): 1.0,
    (2560, 1600): 1.0,
    (3840, 2160): 1.0,
}


@dataclass
class ProfileAudit:
    """Отчёт: что взято из information.txt, что из geo API, что — fallback."""

    info_path: str = ""
    account_ip: str = ""
    warnings: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.warnings and not self.critical

    @property
    def blocking(self) -> bool:
        """Критичные противоречия — не запускать сессию без --force-audit."""
        return bool(self.critical)

    def lines(self) -> list[str]:
        name = Path(str(self.info_path)).name
        if name.lower() == "pc_info.json":
            label = "pc_info.json"
        else:
            label = name or "information.txt"
        out = [f"{label}: {self.info_path}", f"IP аккаунта (identity): {self.account_ip}"]
        for key in (
            "ip", "country", "state", "city", "windows", "display", "cpu", "gpu",
            "ram", "chrome", "timezone", "geolocation", "locale", "accept_language",
            "client_hints", "tls",
        ):
            if key in self.sources:
                out.append(f"  {key}: {self.sources[key]}")
        for w in self.critical:
            out.append(f"  ✗ CRITICAL: {w}")
        for w in self.warnings:
            out.append(f"  ! {w}")
        return out


@dataclass
class PCProfile:
    ip: str = ""
    country: str = ""
    city: str = ""
    state: str = ""
    region: str = ""
    isp: str = ""
    zip_code: str = ""
    machine_id: str = ""
    guid: str = ""
    hwid: str = ""
    windows: str = ""
    windows_build: str = ""
    computer_name: str = ""
    user_name: str = ""
    display_width: int = 0
    display_height: int = 0
    scale_percent: float = 0.0
    local_time: str = ""
    antivirus: str = ""
    processor: str = ""
    cores: int = 0
    threads: int = 0
    ram_mb: int = 0
    video_card: str = ""
    timezone: str = ""
    locale: str = ""
    user_agent: str = ""
    chrome_version: str = ""
    chrome_major: str = ""
    software: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    geolocation: dict = field(default_factory=dict)
    exit_ip: str = ""
    exit_city: str = ""
    exit_state: str = ""
    exit_isp: str = ""
    geo_source: str = ""
    _defaults_used: set[str] = field(default_factory=set, repr=False)

    @property
    def is_windows_11(self) -> bool:
        return "Windows 11" in self.windows

    @property
    def device_pixel_ratio(self) -> float:
        if self.scale_percent > 0:
            return round(self.scale_percent / 100.0, 2)
        if self.display_width and self.display_height:
            key = (self.display_width, self.display_height)
            if key in RESOLUTION_DPR:
                return RESOLUTION_DPR[key]
            if self.display_width <= 1536 and self.display_height <= 900:
                return 1.25
        return 1.0

    @property
    def avail_screen_height(self) -> int:
        h = self.display_height or 1080
        return max(600, h - 48)

    @property
    def languages(self) -> list[str]:
        loc = self.locale or "en-US"
        short = loc.split("-")[0]
        langs = [loc, short]
        if short != "en":
            langs.append("en")
        return langs

    @property
    def accept_language_header(self) -> str:
        loc = self.locale or "en-US"
        short = loc.split("-")[0]
        if short == "en":
            return f"{loc},{short};q=0.9"
        return f"{loc},{short};q=0.9,en;q=0.8"

    @property
    def not_a_brand_version(self) -> str:
        return not_a_brand_version_for_major(self.chrome_major or "0")

    @property
    def timezone_offset_minutes(self) -> int:
        if not self.timezone:
            return 0
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(self.timezone))
            if now.utcoffset() is not None:
                return -int(now.utcoffset().total_seconds() // 60)
        except Exception:
            pass
        return 0

    @property
    def device_memory_gb(self) -> int:
        if not self.ram_mb:
            return 8
        gb = self.ram_mb / 1024
        for cap in (8, 4, 2, 1):
            if gb >= cap * 0.75:
                return cap
        return 1

    @property
    def platform(self) -> str:
        return "Win32"

    @property
    def platform_version(self) -> str:
        build = int(self.windows_build) if str(self.windows_build).isdigit() else 0
        if "Windows 11" in self.windows or build >= 22000:
            return "19.0.0"
        if "Windows 10" in self.windows or build >= 10240:
            return "10.0.0"
        if "Windows 8" in self.windows:
            return "6.3.0"
        return "10.0.0"

    @property
    def win_nt_string(self) -> str:
        return "10.0"

    @property
    def ip_prefix(self) -> str:
        parts = self.ip.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else self.ip

    @property
    def screen(self) -> dict:
        w = self.display_width or 1920
        h = self.display_height or 1080
        return {"width": w, "height": h}

    @property
    def viewport(self) -> dict:
        w = self.display_width or 1920
        h = self.display_height or 1080
        return {"width": w, "height": max(600, h - 80)}

    @property
    def sec_ch_ua(self) -> str:
        parts = []
        for entry in build_client_hints_brands(self):
            parts.append(f'"{entry["brand"]}";v="{entry["version"]}"')
        return ", ".join(parts)

    @property
    def extra_http_headers(self) -> dict[str, str]:
        """Headers that are safe to override at context scope.

        Chromium itself emits Client Hints.  Manually forcing them here made
        every request look unlike the browser's TLS/UA-CH implementation
        (notably the GREASE order and high-entropy hints sent before Accept-CH).
        """
        return {
            "Accept-Language": self.accept_language_header,
        }


def _is_empty_geo(value: str) -> bool:
    v = (value or "").strip().lower()
    return not v or v in ("unknown", "n/a", "na", "-", "—", "0", "none")


def _normalize_log_text(text: str) -> str:
    """Mops и похожие логи пишут поля как «- IP Address: …». Дефис в начале не часть ключа."""
    lines = []
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            stripped = stripped[2:]
        lines.append(stripped)
    return "\n".join(lines)


def _pick(text: str, pattern: str, group: int = 1) -> str:
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    return match.group(group).strip() if match else ""


_SHORT_LANG = {
    "ru": "ru-RU",
    "en": "en-US",
    "es": "es-ES",
    "pt": "pt-BR",
    "de": "de-DE",
    "fr": "fr-FR",
    "it": "it-IT",
    "pl": "pl-PL",
    "nl": "nl-NL",
    "tr": "tr-TR",
    "uk": "uk-UA",
    "id": "id-ID",
    "vi": "vi-VN",
    "th": "th-TH",
    "ar": "ar-SA",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "zh-CN",
}


def _split_ip_country(raw: str) -> tuple[str, str]:
    """«84.54.71.17 (UZ)» → IP и код страны. Обычный «IP: 1.2.3.4» остаётся без страны."""
    text = (raw or "").strip()
    match = re.match(r"^(?P<ip>\S+?)(?:\s*\((?P<cc>[A-Za-z]{2})\))?\s*$", text)
    if not match:
        token = text.split()[0] if text else ""
    else:
        token = match.group("ip")
        cc = (match.group("cc") or "").upper()
    token = token.split("/", 1)[0]
    return token, cc if match else ""


def _normalize_user_locale(raw: str, country: str) -> str:
    """User Language: ru + страна UZ → ru-UZ; полный en-US не трогаем."""
    text = (raw or "").strip().replace("_", "-")
    if not text:
        return ""
    full = re.fullmatch(r"([A-Za-z]{2,3})-([A-Za-z]{2})", text)
    if full:
        return f"{full.group(1).lower()}-{full.group(2).upper()}"
    lang = text.lower()
    cc = (country or "").strip().upper()
    if re.fullmatch(r"[a-z]{2}", lang) and re.fullmatch(r"[A-Z]{2}", cc):
        mapped = COUNTRY_LOCALE.get(cc, "")
        if mapped.lower().startswith(f"{lang}-"):
            return mapped
        return f"{lang}-{cc}"
    return _SHORT_LANG.get(lang, text)


def _normalize_windows(raw: str) -> str:
    """«11 (10.0.26200)» из System Information.txt → «Windows 11 (10.0.26200)»."""
    text = (raw or "").strip()
    match = re.fullmatch(r"(10|11)\s*\((10\.0\.\d+)\)", text)
    if match:
        return f"Windows {match.group(1)} ({match.group(2)})"
    return text


def _normalize_timezone(raw: str) -> str:
    """UTC+5 / GMT-3 / UTC1 → Etc/GMT (знак POSIX обратный). IANA-имя оставляем как есть."""
    text = (raw or "").strip()
    match = re.fullmatch(
        r"(?:UTC|GMT)\s*([+-])?\s*(\d{1,2})(?::\d{2})?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    sign, hours = match.group(1) or "+", int(match.group(2))
    if hours == 0:
        return "UTC"
    etc_sign = "-" if sign == "+" else "+"
    return f"Etc/GMT{etc_sign}{hours}"


def _pick_graphics_card(text: str) -> str:
    inline = _pick_first(
        text,
        r"^VideoCard:\s*(.+)$",
        r"^GPU:\s*(.+)$",
        r"^Video Card:\s*(.+)$",
        r"^Graphics Card:\s*(.+)$",
    )
    if inline:
        return inline.lstrip("-").strip()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^(?:Graphics Card|GPU|Video Card|VideoCard):\s*$", line.strip(), re.IGNORECASE):
            continue
        for nxt in lines[index + 1:]:
            cand = nxt.strip().lstrip("-").strip()
            if not cand:
                break
            if ":" in cand and not re.match(r"^(AMD|NVIDIA|Intel|Radeon|GeForce)\b", cand, re.I):
                break
            return cand
    return ""


def _resolve_geo(ip: str) -> dict:
    if not ip:
        return {}
    url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,zip,isp,lat,lon,timezone"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                return data
    except Exception:
        pass
    return {}


def _pick_first(text: str, *patterns: str, group: int = 1) -> str:
    for pattern in patterns:
        value = _pick(text, pattern, group)
        if value:
            return value
    return ""


def _load_json_object(text: str) -> dict | None:
    """JSON-объект из файла. У pc_info.txt перед «{» бывает текстовая шапка."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _is_pc_info_json(path: str | Path) -> bool:
    return Path(path).name.lower() in {"pc_info.json", "pc_info.txt"}


def _json_str(data: dict, *keys: str) -> str:
    for key in keys:
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            text = val.strip()
        else:
            text = str(val).strip()
        if text:
            return text
    return ""


def _parse_pc_info_json(data: dict) -> PCProfile:
    profile = PCProfile()

    profile.ip = _json_str(data, "Ip", "IP", "ip")
    profile.country = _json_str(data, "Country", "CountryCode", "country")
    profile.city = _json_str(data, "City", "city")
    profile.state = _json_str(data, "State", "Region", "Province", "state")
    profile.region = profile.state
    profile.zip_code = _json_str(data, "ZipCode", "Zip", "PostalCode")
    profile.machine_id = _json_str(data, "MachineID", "MachineId", "machine_id")
    profile.guid = _json_str(data, "GUID", "Guid", "guid")
    profile.hwid = _json_str(data, "Hwid", "HWID", "hwid")
    if not profile.machine_id and profile.hwid:
        profile.machine_id = profile.hwid

    profile.windows = _json_str(data, "Os", "OS", "Windows", "os")
    profile.computer_name = _json_str(data, "PcName", "ComputerName", "Hostname", "pc_name")
    profile.user_name = _json_str(data, "UserName", "User", "username")
    profile.processor = _json_str(data, "CpuName", "Processor", "CPU", "cpu")
    profile.local_time = _json_str(data, "LocalTime", "Date", "local_time")
    profile.antivirus = _json_str(data, "Antivirus", "antivirus")
    profile.isp = _json_str(data, "ISP", "Isp", "Provider")
    profile.locale = _json_str(data, "Language", "Locale", "locale")
    profile.timezone = _json_str(data, "Timezone", "TimeZone", "TZ")

    gpu = data.get("GPU") or data.get("Gpu") or data.get("VideoCard")
    if isinstance(gpu, list):
        profile.video_card = str(gpu[0]).strip() if gpu else ""
    elif isinstance(gpu, str):
        profile.video_card = gpu.strip()

    ram = data.get("RAM") or data.get("Ram") or data.get("ram")
    if ram is not None:
        try:
            profile.ram_mb = int(ram)
        except (TypeError, ValueError):
            pass

    screen = _json_str(data, "ScreenSize", "Screen", "Resolution", "DisplayResolution")
    if screen and "x" in screen.lower():
        parts = screen.lower().split("x", 1)
        try:
            profile.display_width = int(parts[0])
            profile.display_height = int(parts[1])
        except ValueError:
            pass

    cores = data.get("CpuCores") or data.get("Cores") or data.get("cores")
    if cores is not None:
        try:
            profile.cores = int(cores)
        except (TypeError, ValueError):
            pass

    threads = data.get("CpuThreads") or data.get("Threads") or data.get("threads")
    if threads is not None:
        try:
            profile.threads = int(threads)
        except (TypeError, ValueError):
            pass
    elif profile.cores:
        profile.threads = profile.cores

    scale = data.get("Scale") or data.get("DpiScale")
    if scale is not None:
        try:
            profile.scale_percent = float(scale)
        except (TypeError, ValueError):
            pass

    build_match = re.search(r"Build\s+(\d+)", profile.windows)
    if build_match:
        profile.windows_build = build_match.group(1)
    elif data.get("OsBuild") or data.get("WindowsBuild"):
        profile.windows_build = str(data.get("OsBuild") or data.get("WindowsBuild"))

    processes = data.get("ProcessList") or data.get("Processes") or []
    if isinstance(processes, list):
        profile.processes = [str(x) for x in processes if str(x).strip()]

    software = data.get("InstalledSoftware") or data.get("Software") or []
    if isinstance(software, list):
        profile.software = [str(x) for x in software if str(x).strip()]

    lat = data.get("Latitude") if data.get("Latitude") is not None else data.get("Lat")
    lon = data.get("Longitude") if data.get("Longitude") is not None else data.get("Lon")
    if lat is not None and lon is not None:
        try:
            profile.geolocation = {"latitude": float(lat), "longitude": float(lon)}
        except (TypeError, ValueError):
            pass

    return profile


def _finalize_pc_profile(profile: PCProfile, *, source_text: str = "") -> PCProfile:
    _apply_country_defaults(profile)

    major, version = _detect_chrome_version(source_text, profile.software, profile.processes)
    if version:
        profile.chrome_major = major
        profile.chrome_version = version
        if version.endswith(".0.0.0") and _parse_log_date(source_text or profile.local_time):
            profile._defaults_used.add("chrome_estimated")
        elif version == "131.0.0.0":
            profile._defaults_used.add("chrome_version")

    geo = _resolve_geo(profile.ip)
    if geo:
        if _is_empty_geo(profile.city):
            profile.city = geo.get("city", "") or profile.city
        if _is_empty_geo(profile.state):
            profile.state = geo.get("regionName", "") or profile.state
            profile.region = profile.state
        if not profile.isp:
            profile.isp = geo.get("isp", "")
        profile.zip_code = geo.get("zip", profile.zip_code) or profile.zip_code
        if geo.get("timezone"):
            profile.timezone = geo["timezone"]
        if geo.get("lat") is not None and geo.get("lon") is not None:
            profile.geolocation = {"latitude": geo["lat"], "longitude": geo["lon"]}
        if len(profile.country) != 2 and geo.get("countryCode"):
            profile.country = geo["countryCode"]
        if not profile.locale and geo.get("countryCode"):
            profile.locale = COUNTRY_LOCALE.get(geo["countryCode"].upper(), profile.locale)

    _finalize_profile(profile)
    profile._defaults_used.discard("locale")
    if geo and profile.timezone == geo.get("timezone"):
        profile._defaults_used.discard("timezone")
    if geo and profile.geolocation.get("latitude"):
        profile._defaults_used.discard("geolocation")
    return profile


def read_identity_from_pc_info_json(data: dict, *, use_geo: bool = True) -> tuple[str, str, str]:
    ip = _json_str(data, "Ip", "IP", "ip")
    country = _json_str(data, "Country", "CountryCode", "country")
    state = _json_str(data, "State", "Region", "Province", "state")
    city = _json_str(data, "City", "city")
    isp = _json_str(data, "ISP", "Isp", "Provider")

    if use_geo and ip and (_is_empty_geo(city) or _is_empty_geo(state) or not isp):
        geo = _resolve_geo(ip)
        if geo:
            if _is_empty_geo(state):
                state = geo.get("regionName", "")
            if _is_empty_geo(city):
                city = geo.get("city", "")
            if not isp:
                isp = geo.get("isp", "")

    origin_parts: list[str] = []
    if country:
        origin_parts.append(country)
    if city:
        origin_parts.append(city)
    if state and state not in origin_parts:
        origin_parts.append(state)

    return ip, ", ".join(origin_parts) if origin_parts else "—", isp


def read_identity_summary(path: str | Path, *, use_geo: bool = True) -> tuple[str, str, str]:
    """
    IP, регион и ISP из information.txt / pc_info.json для меню выбора аккаунта.
    origin: «IN, Bhubaneswar, Odisha»; isp — из файла или geo по IP.
    """
    path = Path(path)
    if _is_pc_info_json(path):
        data = _load_json_object(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            return read_identity_from_pc_info_json(data, use_geo=use_geo)

    text = _normalize_log_text(path.read_text(encoding="utf-8", errors="replace"))
    raw_ip = _pick_first(text, r"^IP:\s*(.+)$", r"^IP Address:\s*(.+)$", r"^External IP:\s*(.+)$")
    ip, ip_cc = _split_ip_country(raw_ip)
    country = _pick_first(text, r"^Country:\s*(.+)$", r"^Country Code:\s*(.+)$") or ip_cc
    state = _pick_first(text, r"^State:\s*(.+)$", r"^Region:\s*(.+)$", r"^Province:\s*(.+)$")
    city = _pick_first(text, r"^City:\s*(.+)$", r"^Location:\s*(.+)$")
    isp = _pick_first(text, r"^ISP:\s*(.+)$", r"^Provider:\s*(.+)$", r"^Internet:\s*(.+)$")

    if use_geo and ip and (_is_empty_geo(city) or _is_empty_geo(state) or not isp):
        geo = _resolve_geo(ip)
        if geo:
            if _is_empty_geo(state):
                state = geo.get("regionName", "")
            if _is_empty_geo(city):
                city = geo.get("city", "")
            if not isp:
                isp = geo.get("isp", "")

    origin_parts: list[str] = []
    if country:
        origin_parts.append(country)
    if city:
        origin_parts.append(city)
    if state and state not in origin_parts:
        origin_parts.append(state)

    return ip, ", ".join(origin_parts) if origin_parts else "—", isp


def _detect_chrome_version(text: str, software: list[str], processes: list[str]) -> tuple[str, str]:
    """Версия Chrome из software, путей, даты лога или процессов."""
    patterns = [
        r"Chrome\\Application\\(\d+\.\d+\.\d+\.\d+)\\chrome\.exe",
        r"Google\\Chrome\\Application\\(\d+\.\d+\.\d+\.\d+)\\",
        r"Google Chrome[^\d]*(\d+\.\d+\.\d+\.\d+)",
        r"Google Chrome[^\d]*(\d+)\.(\d+\.\d+\.\d+)",
        r"Chrome[/\s]+(\d+\.\d+\.\d+\.\d+)",
        r"(?:Last Version|Chrome Version|Version):\s*(\d+\.\d+\.\d+\.\d+)",
        r"chrome\.exe[^\n\\]*\\Application\\(\d+\.\d+\.\d+\.\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if match.lastindex and match.lastindex >= 2:
                major, rest = match.group(1), match.group(2)
                return major, f"{major}.{rest}"
            ver = match.group(1)
            major = ver.split(".")[0]
            if len(ver.split(".")) >= 4:
                return major, ver
            return major, f"{major}.0.0.0"

    for entry in software:
        if re.search(r"google chrome", entry, re.I):
            m = re.search(r"(\d+)\.(\d+\.\d+\.\d+)", entry)
            if m:
                return m.group(1), f"{m.group(1)}.{m.group(2)}"
            m = re.search(r"(\d{2,3})\.(\d+)\.(\d+\.\d+)", entry)
            if m:
                ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                return m.group(1), ver
            m = re.search(r"(\d{2,3})", entry)
            if m:
                major = m.group(1)
                return major, f"{major}.0.0.0"

    has_chrome_proc = any(
        re.search(r"(?:^|\\/)chrome\.exe$", p, re.I) for p in processes
    ) or bool(re.search(r"chrome\.exe", text, re.I))

    if has_chrome_proc:
        major, version = _estimate_chrome_from_log_date(text)
        if version:
            return major, version

    return "", ""


def _parse_log_date(text: str) -> datetime | None:
    raw = _pick_first(
        text,
        r"^Date:\s*(.+)$",
        r"^Local Time:\s*(.+)$",
        r"^Local Date:\s*(.+)$",
        r"^Server Time:\s*(.+)$",
        r"^Log Created:\s*(.+)$",
        r"^Time Save Log:\s*(.+)$",
    )
    if not raw:
        return None
    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y, %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y, %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _estimate_chrome_from_log_date(text: str) -> tuple[str, str]:
    """Оценка major Chrome по дате снятия лога (~новая major каждые 28 дней)."""
    dt = _parse_log_date(text)
    if not dt:
        return "", ""
    anchor = date(2024, 11, 12)  # Chrome 131 stable
    days = max(0, (dt.date() - anchor).days)
    major = min(131 + days // 28, 200)
    return str(major), f"{major}.0.0.0"


def detect_installed_chrome_version() -> tuple[str, str]:
    """Версия Chrome/Chromium на машине, где запускается Playwright."""
    if sys.platform == "win32":
        reg = _chrome_version_from_registry()
        if reg[1]:
            return reg
        folder = _chrome_version_from_app_folder()
        if folder[1]:
            return folder

    commands: list[list[str]] = []

    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if not base:
                continue
            chrome = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if chrome.is_file():
                commands.append([str(chrome), "--version"])
                break
    elif sys.platform == "darwin":
        mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if mac_chrome.is_file():
            commands.append([str(mac_chrome), "--version"])

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            commands.append([name, "--version"])

    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=5)
            m = re.search(r"(\d+)\.(\d+\.\d+\.\d+)", out)
            if m:
                return m.group(1), f"{m.group(1)}.{m.group(2)}"
        except Exception:
            continue
    return "", ""


def _chrome_version_from_registry() -> tuple[str, str]:
    if sys.platform != "win32":
        return "", ""
    try:
        import winreg

        for hive, sub in (
            (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as key:
                    ver = str(winreg.QueryValueEx(key, "version")[0])
                    if re.match(r"\d+\.", ver):
                        return ver.split(".")[0], ver
            except OSError:
                continue
    except ImportError:
        pass
    return "", ""


def _chrome_version_from_app_folder() -> tuple[str, str]:
    if sys.platform != "win32":
        return "", ""
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        app_dir = Path(base) / "Google" / "Chrome" / "Application"
        if not app_dir.is_dir():
            continue
        versions = sorted(
            (d.name for d in app_dir.iterdir() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", d.name)),
            key=lambda v: tuple(int(x) for x in v.split(".")),
            reverse=True,
        )
        if versions:
            ver = versions[0]
            return ver.split(".")[0], ver
    return "", ""


def _rebuild_user_agent(profile: PCProfile) -> None:
    profile.user_agent = (
        f"Mozilla/5.0 (Windows NT {profile.win_nt_string}; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{profile.chrome_version} Safari/537.36"
    )


def sync_profile_chrome_with_launch_browser(profile: PCProfile) -> bool:
    """Если версии нет в логе — подставить установленный Chrome (совпадение с реальным браузером)."""
    major, version = detect_installed_chrome_version()
    if not version:
        return False
    profile.chrome_major = major
    profile.chrome_version = version
    profile._defaults_used.discard("chrome_version")
    profile._defaults_used.add("chrome_launch_sync")
    _rebuild_user_agent(profile)
    return True


def apply_exit_ip_geo(profile: PCProfile, exit_ip: str, *, force: bool = False) -> tuple[bool, str]:
    """Timezone/geolocation/locale по exit-IP.

    force=True — после «Пересобрать профиль»: брать tz/locale/страну с прокси,
    даже если information.txt из другой страны.
    """
    if not exit_ip:
        return False, ""

    geo = _resolve_geo(exit_ip)
    profile.exit_ip = exit_ip
    if not geo:
        return False, f"Не удалось определить geo для exit-IP {exit_ip}"

    profile.exit_city = geo.get("city", "")
    profile.exit_state = geo.get("regionName", "")
    profile.exit_isp = geo.get("isp", "")

    account_cc = (profile.country or "").upper()
    if not account_cc and profile.ip:
        id_geo = _resolve_geo(profile.ip)
        if id_geo:
            account_cc = str(id_geo.get("countryCode", "")).upper()

    exit_cc = str(geo.get("countryCode", "")).upper()
    if account_cc and exit_cc and account_cc != exit_cc and not force:
        profile.geo_source = "identity"
        note = (
            f"Exit-IP {exit_ip} → {geo.get('country', exit_cc)} ({profile.exit_city}), "
            f"аккаунт {account_cc}: tz/locale/geo из identity IP "
            f"({profile.timezone or '—'}, {profile.locale or '—'})"
        )
        return False, note
    if force and exit_cc:
        profile.country = exit_cc
        if geo.get("city"):
            profile.city = str(geo.get("city") or "")
        if geo.get("regionName"):
            profile.state = str(geo.get("regionName") or "")
            profile.region = profile.state

    profile.geo_source = "exit_ip"
    if geo.get("timezone"):
        profile.timezone = geo["timezone"]
        profile._defaults_used.discard("timezone")
    if geo.get("lat") is not None and geo.get("lon") is not None:
        profile.geolocation = {"latitude": geo["lat"], "longitude": geo["lon"]}
        profile._defaults_used.discard("geolocation")

    if exit_cc and exit_cc in COUNTRY_LOCALE:
        loc_cc = ""
        if profile.locale and "-" in profile.locale:
            tail = profile.locale.split("-", 1)[1]
            if len(tail) == 2:
                loc_cc = tail.upper()
        if "locale" in profile._defaults_used or not profile.locale or loc_cc != exit_cc:
            profile.locale = COUNTRY_LOCALE[exit_cc]
            profile._defaults_used.discard("locale")

    return True, ""


def cookies_note_invalid(note: str) -> bool:
    n = note.lower()
    return any(
        x in n
        for x in ("невалид", "invalid", "не валид", "dead", "просроч", "expired", "устар")
    )


def _apply_country_defaults(profile: PCProfile) -> None:
    code = profile.country.upper() if profile.country else ""
    if code in COUNTRY_LOCALE and not profile.locale:
        profile.locale = COUNTRY_LOCALE[code]


def _mark_default(profile: PCProfile, field_name: str) -> None:
    profile._defaults_used.add(field_name)


def _finalize_profile(profile: PCProfile) -> None:
    if not profile.locale:
        profile.locale = COUNTRY_LOCALE.get(profile.country.upper(), "en-US")
        _mark_default(profile, "locale")
    if not profile.timezone and profile.country.upper() == "IN":
        profile.timezone = "Asia/Kolkata"
        _mark_default(profile, "timezone")
    if not profile.timezone:
        profile.timezone = "UTC"
        _mark_default(profile, "timezone")
    if not profile.chrome_version:
        profile.chrome_major, profile.chrome_version = "131", "131.0.0.0"
        _mark_default(profile, "chrome_version")
    if not profile.chrome_major:
        profile.chrome_major = profile.chrome_version.split(".")[0]
    if not profile.display_width:
        profile.display_width = 1920
        _mark_default(profile, "display_width")
    if not profile.display_height:
        profile.display_height = 1080
        _mark_default(profile, "display_height")
    if not profile.cores:
        profile.cores = profile.threads or 4
        _mark_default(profile, "cores")
    if not profile.threads:
        profile.threads = profile.cores or 4
        _mark_default(profile, "threads")
    if not profile.ram_mb:
        profile.ram_mb = 8192
        _mark_default(profile, "ram_mb")
    if not profile.geolocation:
        profile.geolocation = {"latitude": 0.0, "longitude": 0.0}
        _mark_default(profile, "geolocation")

    if not profile.geo_source and profile.ip:
        profile.geo_source = "identity"

    _rebuild_user_agent(profile)


def audit_profile(
    profile: PCProfile,
    text: str,
    info_path: str | Path = "",
    *,
    require_ip: bool = True,
    chrome_exe: Path | None = None,
) -> ProfileAudit:
    """Сверка fingerprint с полями information.txt / pc_info.json."""
    audit = ProfileAudit(
        info_path=str(info_path),
        account_ip=profile.ip,
    )
    is_json = _is_pc_info_json(info_path)
    json_data: dict = {}
    if is_json:
        json_data = _load_json_object(text) or {}
        if not json_data and info_path:
            try:
                json_data = _load_json_object(Path(info_path).read_text(encoding="utf-8", errors="replace")) or {}
            except OSError:
                json_data = {}

    def from_file(label: str, raw: str, applied: str) -> None:
        if raw:
            audit.sources[label] = f"файл → {applied}"
        elif applied:
            audit.sources[label] = f"geo/API → {applied}"

    if is_json:
        from_file("ip", _json_str(json_data, "Ip", "IP"), profile.ip)
        from_file("country", _json_str(json_data, "Country"), profile.country)
        from_file("state", _json_str(json_data, "State", "Region"), profile.state)
        from_file("city", _json_str(json_data, "City"), profile.city)
        win_raw = _json_str(json_data, "Os", "OS", "Windows")
        audit.sources["windows"] = f"файл → {profile.windows}" if win_raw else f"? → {profile.windows}"
        screen_raw = _json_str(json_data, "ScreenSize", "Screen", "Resolution")
        audit.sources["display"] = (
            f"файл → {profile.display_width}x{profile.display_height} DPR={profile.device_pixel_ratio}"
            if screen_raw
            else f"fallback → {profile.display_width}x{profile.display_height}"
        )
        proc = _json_str(json_data, "CpuName", "Processor", "CPU")
        audit.sources["cpu"] = (
            f"файл → {profile.processor} ({profile.cores}c/{profile.threads}t)"
            if proc or json_data.get("CpuCores")
            else f"? → {profile.cores}c/{profile.threads}t"
        )
        gpu_list = json_data.get("GPU")
        gpu_raw = gpu_list[0] if isinstance(gpu_list, list) and gpu_list else _json_str(json_data, "VideoCard")
        audit.sources["gpu"] = f"файл → {profile.video_card}" if gpu_raw else "?"
        ram_raw = json_data.get("RAM")
        audit.sources["ram"] = (
            f"файл → {profile.ram_mb} MB (deviceMemory={profile.device_memory_gb})"
            if ram_raw is not None
            else f"fallback → {profile.ram_mb} MB"
        )
        has_chrome = any("google chrome" in s.lower() for s in profile.software) or any(
            re.search(r"chrome\.exe", p, re.I) for p in profile.processes
        )
    else:
        raw_ip = _pick_first(text, r"^IP:\s*(.+)$", r"^IP Address:\s*(.+)$", r"^External IP:\s*(.+)$")
        _ip, ip_cc = _split_ip_country(raw_ip)
        from_file("ip", _ip, profile.ip)
        from_file(
            "country",
            _pick_first(text, r"^Country:\s*(.+)$", r"^Country Code:\s*(.+)$") or ip_cc,
            profile.country,
        )
        from_file("state", _pick_first(text, r"^State:\s*(.+)$", r"^Region:\s*(.+)$"), profile.state)
        from_file("city", _pick_first(text, r"^City:\s*(.+)$"), profile.city)

        win_raw = _pick_first(
            text,
            r"^Windows:\s*(.+)$",
            r"^OS:\s*(.+)$",
            r"^Operation System:\s*(.+)$",
            r"^Operating System:\s*(.+)$",
        )
        audit.sources["windows"] = f"файл → {profile.windows}" if win_raw else f"? → {profile.windows}"

        res = re.search(
            r"^(?:Display Resolution|Resolution|Screen|Display):\s*(\d+)x(\d+)$",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
        if res:
            audit.sources["display"] = f"файл → {profile.display_width}x{profile.display_height} DPR={profile.device_pixel_ratio}"
        else:
            audit.sources["display"] = f"fallback → {profile.display_width}x{profile.display_height}"

        proc = _pick_first(text, r"^Processor:\s*(.+)$")
        audit.sources["cpu"] = (
            f"файл → {profile.processor} ({profile.cores}c/{profile.threads}t)"
            if proc
            else f"? → {profile.cores}c/{profile.threads}t"
        )

        gpu = _pick_graphics_card(text)
        audit.sources["gpu"] = f"файл → {profile.video_card}" if gpu else "?"

        ram = _pick_first(text, r"^RAM:\s*(\d+)\s*MB$", r"^Installed RAM:\s*(\d+)\s*MB$")
        audit.sources["ram"] = (
            f"файл → {profile.ram_mb} MB (deviceMemory={profile.device_memory_gb})"
            if ram
            else f"fallback → {profile.ram_mb} MB"
        )

        has_chrome = bool(re.search(r"chrome\.exe", text, re.I)) or bool(
            re.search(r"Google Chrome", text, re.I)
        )

    if "chrome_daily_binary" in profile._defaults_used:
        audit.sources["chrome"] = (
            f"Chrome for Testing (сутки, уникальный бинарник) → {profile.chrome_version}"
        )
        exe_note = ""
        if chrome_exe is not None:
            if chrome_exe.is_file():
                exe_note = f" @ {chrome_exe.parent.name}/chrome.exe"
            else:
                audit.warnings.append(
                    f"CFT бинарник не найден: {chrome_exe} — TLS может не совпасть с UA"
                )
        audit.sources["tls"] = (
            f"CFT major {profile.chrome_major} — TLS = {profile.chrome_version}{exe_note}"
        )
    elif "chrome_launch_sync" in profile._defaults_used:
        audit.sources["chrome"] = f"установленный Chrome → {profile.chrome_version}"
        audit.sources["tls"] = f"TLS = системный Chrome {profile.chrome_version} (все аккаунты одинаковые)"
        audit.warnings.append(
            f"Точная версия Chrome не в логе — синхронизировано с установленным ({profile.chrome_version})"
        )
    elif "chrome_estimated" in profile._defaults_used:
        audit.sources["chrome"] = f"оценка по Date лога → {profile.chrome_version}"
        audit.sources["tls"] = f"TLS ≠ UA — нужен CFT или --sync-host-chrome"
        audit.warnings.append(
            f"Точная версия Chrome не в логе — оценка по Date: {profile.chrome_version}"
        )
    elif "chrome_version" in profile._defaults_used:
        audit.sources["chrome"] = f"fallback Chrome/{profile.chrome_version}"
        audit.sources["tls"] = f"TLS ≠ UA — нужен CFT или --sync-host-chrome"
        if not has_chrome:
            audit.warnings.append(
                "Chrome не найден в логе ПК — версия 131.0.0.0 по умолчанию"
            )
        else:
            audit.warnings.append(
                f"Версия Chrome не извлечена из файла — используется {profile.chrome_version}"
            )
    else:
        audit.sources["chrome"] = f"файл → {profile.chrome_version}"
        audit.sources["tls"] = (
            f"TLS = системный Chrome (--fixed-chrome), UA {profile.chrome_version}"
        )

    ua_major = ""
    ua_match = re.search(r"Chrome/(\d+)", profile.user_agent or "")
    if ua_match:
        ua_major = ua_match.group(1)
    ch_major = next(
        (e["version"] for e in build_client_hints_brands(profile) if e["brand"] == "Google Chrome"),
        "",
    )
    if profile.chrome_major and ua_major and profile.chrome_major != ua_major:
        audit.critical.append(
            f"UA major Chrome/{ua_major} ≠ CFT major {profile.chrome_major} — TLS/Client Hints mismatch"
        )
    if ch_major and profile.chrome_major and ch_major != profile.chrome_major:
        audit.critical.append(
            f"sec-ch-ua major {ch_major} ≠ chrome_major {profile.chrome_major}"
        )
    if ua_major and ch_major and ua_major != ch_major:
        audit.critical.append(f"UA major {ua_major} ≠ sec-ch-ua major {ch_major}")

    audit.sources["client_hints"] = profile.sec_ch_ua
    audit.sources["accept_language"] = profile.accept_language_header

    if profile.geo_source == "exit_ip" and profile.exit_ip:
        audit.sources["geolocation"] = (
            f"exit-IP {profile.exit_ip} → {profile.geolocation} "
            f"({profile.exit_city or '—'}, tz={profile.timezone})"
        )
        if profile.ip and profile.exit_ip.split(".")[:2] != profile.ip.split(".")[:2]:
            audit.warnings.append(
                f"Geo/timezone по exit-IP {profile.exit_ip}, identity IP {profile.ip} — префиксы различаются"
            )
    elif profile.exit_ip and profile.geo_source == "identity":
        audit.sources["geolocation"] = (
            f"identity IP {profile.ip} → {profile.geolocation} (tz={profile.timezone})"
        )
        exit_geo = _resolve_geo(profile.exit_ip)
        if exit_geo:
            ex_cc = str(exit_geo.get("countryCode", "")).upper()
            ac_cc = (profile.country or "").upper()
            if ac_cc and ex_cc and ac_cc != ex_cc:
                audit.critical.append(
                    f"Exit-IP {profile.exit_ip} → {ex_cc}, identity {ac_cc} — "
                    f"timezone/locale/Accept-Language противоречат exit IP"
                )
    elif "geolocation" in profile._defaults_used:
        audit.sources["geolocation"] = "fallback 0,0"
        audit.warnings.append("Geolocation не получена — проверьте IP в information.txt")
    elif profile.ip and not _pick_first(text, r"^City:\s*(.+)$"):
        audit.sources["geolocation"] = f"geo по IP {profile.ip} → {profile.geolocation}"
    else:
        audit.sources["geolocation"] = f"файл/geo → {profile.geolocation}"

    geo = profile.geolocation or {}
    if float(geo.get("latitude") or 0) == 0.0 and float(geo.get("longitude") or 0) == 0.0:
        if profile.exit_ip or profile.ip:
            audit.warnings.append("Geolocation 0,0 при известном IP — риск geo mismatch")

    if "timezone" in profile._defaults_used:
        audit.warnings.append(f"Timezone fallback: {profile.timezone}")
    elif profile.timezone:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(profile.timezone))
            if now.utcoffset() is not None:
                expected = -int(now.utcoffset().total_seconds() // 60)
                if profile.timezone_offset_minutes != expected:
                    audit.warnings.append(
                        f"Intl offset {profile.timezone_offset_minutes} мин ≠ "
                        f"{profile.timezone} ({expected} мин) — проверьте tz/exit-IP"
                    )
        except Exception:
            audit.warnings.append(f"Timezone {profile.timezone} — не удалось сверить Intl offset")

    if profile.state and not _pick_first(text, r"^State:\s*(.+)$", r"^Region:\s*(.+)$"):
        audit.sources["state"] = f"geo по IP → {profile.state}"

    if profile.city and not _pick_first(text, r"^City:\s*(.+)$"):
        audit.sources["city"] = f"geo по IP → {profile.city}"

    audit.sources["locale"] = profile.locale
    if "locale" in profile._defaults_used:
        audit.warnings.append(f"Locale по country: {profile.locale}")

    # locale ↔ country (грубая согласованность цепочки Accept-Language)
    loc = (profile.locale or "").upper()
    cc = (profile.country or "").upper()
    if loc and cc and "-" in (profile.locale or ""):
        loc_cc = (profile.locale or "").split("-")[-1].upper()
        if len(loc_cc) == 2 and loc_cc != cc and COUNTRY_LOCALE.get(cc, "").upper() != (profile.locale or "").upper():
            expected_loc = COUNTRY_LOCALE.get(cc, "")
            if expected_loc and expected_loc.upper() != (profile.locale or "").upper():
                audit.warnings.append(
                    f"Locale {profile.locale} слабо стыкуется с country {cc} (ожидалось ~{expected_loc})"
                )

    if not profile.video_card:
        audit.warnings.append("VideoCard пуст — WebGL/WebGPU уйдут в Intel UHD fallback")
    elif "gpu" not in audit.sources:
        audit.sources["gpu"] = f"файл → {profile.video_card}"

    if not profile.display_width or not profile.display_height:
        audit.critical.append("Display Resolution отсутствует — viewport/screen будут fallback")

    if not profile.cores and not profile.threads:
        audit.warnings.append("CPU cores/threads не заданы — hardwareConcurrency = fallback")

    for field in profile._defaults_used:
        if field in (
            "chrome_version", "chrome_estimated", "chrome_launch_sync",
            "chrome_daily_binary", "geolocation", "timezone", "locale",
        ):
            continue
        audit.warnings.append(f"Поле «{field}» — значение по умолчанию, нет в information.txt")

    if require_ip and not profile.ip:
        audit.critical.append("IP отсутствует — прокси и geo не привязаны к аккаунту")

    if not profile.machine_id:
        src = "pc_info.json" if is_json else "information.txt"
        audit.warnings.append(f"MachineID не найден в {src}")

    return audit


def parse_pc_info(path: str | Path) -> PCProfile:
    info_path = Path(path)
    if _is_pc_info_json(info_path):
        text = info_path.read_text(encoding="utf-8", errors="replace")
        data = _load_json_object(text)
        if not isinstance(data, dict):
            raise ValueError(f"pc_info должен быть JSON-объектом: {info_path}")
        profile = _parse_pc_info_json(data)
        return _finalize_pc_profile(profile, source_text=profile.local_time)

    text = _normalize_log_text(info_path.read_text(encoding="utf-8", errors="replace"))
    profile = PCProfile()

    raw_ip = _pick_first(
        text,
        r"^IP:\s*(.+)$",
        r"^IP Address:\s*(.+)$",
        r"^External IP:\s*(.+)$",
    )
    profile.ip, ip_cc = _split_ip_country(raw_ip)
    profile.country = _pick_first(
        text,
        r"^Country:\s*(.+)$",
        r"^Country Code:\s*(.+)$",
        r"^Geo:\s*(.+)$",
    ) or ip_cc
    profile.city = _pick_first(text, r"^City:\s*(.+)$", r"^Location:\s*(.+)$")
    profile.state = _pick_first(
        text,
        r"^State:\s*(.+)$",
        r"^Region:\s*(.+)$",
        r"^Province:\s*(.+)$",
    )
    profile.region = profile.state
    profile.machine_id = _pick(text, r"^MachineID:\s*(.+)$")
    profile.guid = _pick(text, r"^GUID:\s*(.+)$")
    profile.hwid = _pick(text, r"^HWID:\s*(.+)$")
    if not profile.machine_id and profile.hwid:
        profile.machine_id = profile.hwid
    profile.windows = _pick_first(
        text,
        r"^Windows:\s*(.+)$",
        r"^OS Version:\s*(.+)$",
        r"^OS:\s*(.+)$",
        r"^Operation System:\s*(.+)$",
        r"^Operating System:\s*(.+)$",
    )
    profile.windows = _normalize_windows(profile.windows)
    profile.computer_name = _pick_first(
        text,
        r"^Computer Name:\s*(.+)$",
        r"^Hostname:\s*(.+)$",
        r"^PC Name:\s*(.+)$",
        r"^Computer:\s*(.+)$",
    )
    profile.user_name = _pick_first(
        text,
        r"^User Name:\s*(.+)$",
        r"^Username:\s*(.+)$",
        r"^UserName:\s*(.+)$",
        r"^User:\s*(.+)$",
    )
    profile.processor = _pick_first(
        text, r"^Processor:\s*(.+)$", r"^CPU Name:\s*(.+)$", r"^CPU:\s*(.+)$"
    )
    profile.video_card = _pick_graphics_card(text)
    profile.local_time = _pick_first(
        text,
        r"^Local Time:\s*(.+)$",
        r"^Local Date:\s*(.+)$",
        r"^Date:\s*(.+)$",
        r"^Server Time:\s*(.+)$",
        r"^Log Created:\s*(.+)$",
        r"^Time Save Log:\s*(.+)$",
    )
    profile.antivirus = _pick_first(
        text, r"^Antivirus:\s*(.+)$", r"^Anti Virus:\s*(.+)$"
    )
    profile.isp = _pick_first(text, r"^ISP:\s*(.+)$", r"^Provider:\s*(.+)$")
    profile.locale = _normalize_user_locale(
        _pick_first(
            text,
            r"^Language:\s*(.+)$",
            r"^Locale:\s*(.+)$",
            r"^System Language:\s*(.+)$",
            r"^User Language:\s*(.+)$",
        ),
        profile.country,
    )
    profile.timezone = _normalize_timezone(
        _pick_first(
            text,
            r"^Timezone:\s*(.+)$",
            r"^Time Zone:\s*(.+)$",
            r"^TZ:\s*(.+)$",
        )
    )

    scale = _pick_first(
        text,
        r"^Scale:\s*(\d+)\s*%$",
        r"^Display Scale:\s*(\d+)\s*%$",
        r"^DPI Scale:\s*(\d+)\s*%$",
    )
    if scale:
        profile.scale_percent = float(scale)

    build_match = re.search(r"Build\s+(\d+)", profile.windows)
    if not build_match:
        build_match = re.search(r"\b\d+\.\d+\.(\d{4,5})\b", profile.windows)
    if build_match:
        profile.windows_build = build_match.group(1)

    res_match = re.search(
        r"^(?:Display Resolution|Resolution|Screen|Display):\s*(\d+)x(\d+)$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if res_match:
        profile.display_width = int(res_match.group(1))
        profile.display_height = int(res_match.group(2))

    cores = _pick_first(
        text,
        r"^Cores:\s*(\d+)$",
        r"^Processor Cores:\s*(\d+)$",
        r"^CPU Cores:\s*(\d+)$",
    )
    if cores:
        profile.cores = int(cores)

    threads = _pick_first(
        text,
        r"^Threads:\s*(\d+)$",
        r"^Processor Threads:\s*(\d+)$",
        r"^CPU Threads:\s*(\d+)$",
    )
    if threads:
        profile.threads = int(threads)

    ram = _pick_first(
        text,
        r"^RAM:\s*(\d+)\s*MB$",
        r"^Installed RAM:\s*(\d+)\s*MB$",
        r"^RAM Size:\s*(\d+)\s*MB$",
    )
    if ram:
        profile.ram_mb = int(ram)
    else:
        ram_gb = _pick_first(
            text,
            r"^RAM Size:\s*(\d+(?:[.,]\d+)?)\s*GB$",
            r"^RAM:\s*(\d+(?:[.,]\d+)?)\s*GB$",
        )
        if ram_gb:
            profile.ram_mb = int(round(float(ram_gb.replace(",", ".")) * 1024))

    in_software = False
    in_processes = False
    for line in text.splitlines():
        if line.strip() == "[Software]":
            in_software, in_processes = True, False
            continue
        if line.strip() == "[Processes]":
            in_processes, in_software = True, False
            continue
        if line.startswith("[") and line.endswith("]"):
            in_software = in_processes = False
            continue
        if in_software and line.strip() and not line.startswith("|"):
            profile.software.append(line.strip())
        if in_processes:
            proc = re.search(r"\]\s*(.+)$", line.strip())
            if proc:
                profile.processes.append(proc.group(1))

    _apply_country_defaults(profile)

    major, version = _detect_chrome_version(text, profile.software, profile.processes)
    if version:
        profile.chrome_major = major
        profile.chrome_version = version
        if version.endswith(".0.0.0") and _parse_log_date(text):
            profile._defaults_used.add("chrome_estimated")
        elif version == "131.0.0.0":
            profile._defaults_used.add("chrome_version")

    return _finalize_pc_profile(profile, source_text=text)


def _proxy_for_checks(proxy: dict) -> dict:
    """Если прокси идёт через локальную цепочку (v2rayN) — проверять тем же путём, что Chrome."""
    try:
        from proxy_relay import relay_proxy_for_checks

        return relay_proxy_for_checks(proxy) or proxy
    except Exception:
        return proxy


def probe_youtube_download(proxy: dict, timeout: float = 12.0) -> int:
    """Сколько байт HTML YouTube удалось скачать через прокси (0 = ошибка)."""
    import urllib.error
    from urllib.parse import urlparse

    proxy = _proxy_for_checks(proxy)
    server = str(proxy.get("server", "")).strip()
    if not server:
        return 0
    if "://" not in server:
        server = f"http://{server}"
    if proxy.get("username"):
        parsed = urlparse(server)
        auth = f"{proxy['username']}:{proxy.get('password', '')}"
        server = f"{parsed.scheme}://{auth}@{parsed.hostname}:{parsed.port}"

    handler = urllib.request.ProxyHandler({"http": server, "https": server})
    opener = urllib.request.build_opener(handler)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    nbytes, _ = _youtube_stream_probe(opener, headers, timeout=timeout)
    return nbytes


def _youtube_stream_probe(
    opener: urllib.request.OpenerDirector,
    headers: dict[str, str],
    *,
    timeout: float = 12.0,
) -> tuple[int, str]:
    """Сколько байт HTML YouTube читается; предупреждение, если поток обрывается раньше времени."""
    import time
    import urllib.error

    req = urllib.request.Request(
        "https://www.youtube.com/",
        headers={
            **headers,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    body = b""
    try:
        with opener.open(req, timeout=timeout) as resp:
            if resp.status not in (200, 301, 302, 303, 307, 308):
                return 0, ""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    chunk = resp.read(4096)
                except TimeoutError:
                    break
                if not chunk:
                    break
                body += chunk
                if len(body) >= 50_000 or b"</html>" in body:
                    return len(body), ""
    except (urllib.error.HTTPError, TimeoutError, OSError):
        return len(body), ""

    if len(body) >= 50_000 or b"</html>" in body:
        return len(body), ""
    if len(body) == 0:
        return 0, ""
    kb = max(1, len(body) // 1024)
    return (
        len(body),
        f"прокси обрывает HTTPS после ~{kb} КБ — YouTube будет белым экраном",
    )


# jquery.min.js ~87 КБ; живой прокси докачивает целиком, «обрезанный» стопорится на ~16 КБ.
STREAM_PROBE_URL = "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"
STREAM_PROBE_MIN_BYTES = 40_000


def proxy_https_body_too_small(nbytes: int) -> bool:
    return 0 < nbytes < STREAM_PROBE_MIN_BYTES


def probe_proxy_https_body(
    proxy: dict,
    *,
    url: str = STREAM_PROBE_URL,
    timeout: float = 10.0,
) -> int:
    """Сколько байт тела отдаёт CONNECT+TLS. 0 — ошибка соединения."""
    import base64
    import socket
    import ssl
    import time
    from urllib.parse import urlparse

    server = str(proxy.get("server", "")).strip()
    if not server:
        return 0
    if "://" not in server:
        server = f"http://{server}"
    parsed_proxy = urlparse(server)
    phost = parsed_proxy.hostname or ""
    pport = parsed_proxy.port or 80
    user = str(proxy.get("username", ""))
    password = str(proxy.get("password", ""))
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    auth = b""
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        auth = f"Proxy-Authorization: Basic {token}\r\n".encode()
    sock = None
    try:
        sock = socket.create_connection((phost, pport), timeout=min(12.0, timeout + 4))
        sock.sendall(
            f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n".encode()
            + auth
            + b"\r\n"
        )
        hdr = b""
        while b"\r\n\r\n" not in hdr:
            chunk = sock.recv(4096)
            if not chunk:
                break
            hdr += chunk
        if b"200" not in hdr.split(b"\r\n", 1)[0]:
            return 0
        tls = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        tls.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
                "User-Agent: Mozilla/5.0\r\nAccept: */*\r\n\r\n"
            ).encode()
        )
        tls.settimeout(1.5)
        body = b""
        t0 = time.perf_counter()
        last = t0
        # «Обрезанный» прокси — поток встал (4 с тишины). Медленный residential
        # (3–5 КБ/с через VPN-цепочку) — не обрыв: ждём дольше, пока байты идут.
        hard_cap = max(float(timeout) * 3.0, 30.0)
        while True:
            try:
                chunk = tls.recv(16384)
            except TimeoutError:
                if time.perf_counter() - last >= 4.0:
                    break
                if time.perf_counter() - t0 >= hard_cap:
                    break
                continue
            if not chunk:
                break
            body += chunk
            last = time.perf_counter()
            if len(body) >= STREAM_PROBE_MIN_BYTES:
                break
            if time.perf_counter() - t0 >= hard_cap:
                break
        return len(body)
    except Exception:
        return 0
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def check_proxy(proxy: dict, timeout: float = 20.0, *, fast: bool = False) -> tuple[bool, str]:
    """Проверка прокси. fast=True — только Google (для Windows + Mac-мост)."""
    import urllib.error
    from urllib.parse import urlparse

    proxy = _proxy_for_checks(proxy)
    server = proxy["server"]
    if "://" not in server:
        server = f"http://{server}"

    if proxy.get("username"):
        parsed = urlparse(server)
        auth = f"{proxy['username']}:{proxy.get('password', '')}"
        server = f"{parsed.scheme}://{auth}@{parsed.hostname}:{parsed.port}"

    handler = urllib.request.ProxyHandler({"http": server, "https": server})
    opener = urllib.request.build_opener(handler)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    req = urllib.request.Request(
        "https://www.google.com/generate_204", method="GET", headers=headers
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            if resp.status not in (200, 204):
                return False, f"Google: HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code not in (200, 204):
            return False, f"Google: HTTP {exc.code}"
    except Exception as exc:
        return False, f"Google: {exc.__class__.__name__}"

    if fast:
        return True, "Google OK"

    nbytes = probe_proxy_https_body(proxy, timeout=min(10.0, timeout))
    if proxy_https_body_too_small(nbytes):
        kb = max(1, nbytes // 1024)
        return False, (
            f"прокси обрывает HTTPS после ~{kb} КБ — "
            "YouTube/Studio будут белым экраном, нужен LAN-мост"
        )
    if nbytes >= STREAM_PROBE_MIN_BYTES:
        return True, f"Google OK, поток {nbytes} байт"

    nhtml, stream_warn = _youtube_stream_probe(opener, headers, timeout=min(12.0, timeout))
    if stream_warn:
        return False, stream_warn
    if nhtml >= 50_000:
        return True, "Google + YouTube OK"
    return False, "прокси не отдаёт большой HTTPS — YouTube не откроется"
