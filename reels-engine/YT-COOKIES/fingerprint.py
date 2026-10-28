"""Генерация init-скрипта и CDP-подмены fingerprint под данные ПК из information.txt."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any

from browser_isolation import fingerprint_seed_from_identity
from pc_parser import PCProfile


def _fingerprint_seed(profile: PCProfile, instance_id: str = "", account_key: str = "") -> int:
    if instance_id:
        return fingerprint_seed_from_identity(instance_id, profile)
    parts = [
        account_key,
        profile.machine_id,
        profile.guid,
        profile.hwid,
        profile.ip,
        profile.computer_name,
        profile.user_name,
    ]
    raw = "|".join(p for p in parts if p) or "yt-cookies"
    return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)


def _platform_label(profile: PCProfile) -> str:
    if profile.is_windows_11:
        return "Windows 11"
    if "Windows 10" in profile.windows:
        return "Windows 10"
    return profile.windows or "Windows"


def _webgl_renderer(profile: PCProfile) -> tuple[str, str]:
    card = profile.video_card.strip()
    if "NVIDIA" in card or "GeForce" in card:
        return (
            "Google Inc. (NVIDIA)",
            f"ANGLE (NVIDIA, {card or 'NVIDIA GeForce'} Direct3D11 vs_5_0 ps_5_0, D3D11)",
        )
    if "AMD" in card or "Radeon" in card:
        return (
            "Google Inc. (AMD)",
            f"ANGLE (AMD, {card or 'AMD Radeon'} Direct3D11 vs_5_0 ps_5_0, D3D11)",
        )
    if "Intel" in card or card:
        model = card if card else "Intel(R) UHD Graphics"
        return (
            "Google Inc. (Intel)",
            f"ANGLE (Intel, {model} Direct3D11 vs_5_0 ps_5_0, D3D11)",
        )
    return (
        "Google Inc. (Intel)",
        "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    )


def _gpu_webgl_limits(profile: PCProfile) -> dict[str, int | list[int]]:
    card = profile.video_card.upper()
    if any(x in card for x in ("NVIDIA", "GEFORCE", "RTX", "GTX")):
        return {
            "p3379": 32768,
            "p34024": 16384,
            "p34069": 32768,
            "p3386": [32767, 32767],
            "p34921": 16,
            "p36347": 4096,
            "p36348": 1024,
            "p35660": 16,
            "p35371": 32,
        }
    if any(x in card for x in ("AMD", "RADEON")):
        return {
            "p3379": 16384,
            "p34024": 16384,
            "p34069": 16384,
            "p3386": [16384, 16384],
            "p34921": 16,
            "p36347": 4096,
            "p36348": 1024,
            "p35660": 16,
            "p35371": 32,
        }
    # Intel UHD / Iris — типичные chrome://gpu лимиты
    return {
        "p3379": 16384,
        "p34024": 8192,
        "p34069": 8192,
        "p3386": [16384, 16384],
        "p34921": 16,
        "p36347": 4096,
        "p36348": 1024,
        "p35660": 16,
        "p35371": 16,
    }


def _webgpu_info(profile: PCProfile) -> dict[str, str]:
    card = (profile.video_card or "").upper()
    if any(x in card for x in ("NVIDIA", "GEFORCE", "RTX", "GTX")):
        arch = "ampere" if "RTX 30" in card or "RTX30" in card else (
            "ada" if "RTX 40" in card or "RTX40" in card else "generic"
        )
        return {"vendor": "nvidia", "architecture": arch}
    if any(x in card for x in ("AMD", "RADEON")):
        arch = "rdna2" if any(x in card for x in ("RX 6", "RX6", "RX 7", "RX7")) else "gcn"
        return {"vendor": "amd", "architecture": arch}
    if any(x in card for x in ("IRIS XE", "XE GRAPHICS", "ARC")):
        return {"vendor": "intel", "architecture": "xe-lpg"}
    if any(x in card for x in ("UHD", "HD GRAPHICS", "620", "630", "520", "530")):
        return {"vendor": "intel", "architecture": "gen-9"}
    if "INTEL" in card:
        return {"vendor": "intel", "architecture": "gen-12"}
    return {"vendor": "intel", "architecture": "gen-9"}


def _windows_fonts(profile: PCProfile) -> list[str]:
    fonts = [
        "Arial", "Arial Black", "Bahnschrift", "Calibri", "Cambria", "Cambria Math",
        "Candara", "Comic Sans MS", "Consolas", "Constantia", "Corbel", "Courier New",
        "Ebrima", "Franklin Gothic Medium", "Gabriola", "Gadugi", "Georgia", "Impact",
        "Ink Free", "Javanese Text", "Leelawadee UI", "Lucida Console",
        "Lucida Sans Unicode", "Malgun Gothic", "Microsoft Himalaya", "Microsoft JhengHei",
        "Microsoft New Tai Lue", "Microsoft PhagsPa", "Microsoft Sans Serif",
        "Microsoft Tai Le", "Microsoft YaHei", "Microsoft Yi Baiti", "Mongolian Baiti",
        "MS Gothic", "MV Boli", "Myanmar Text", "Nirmala UI", "Palatino Linotype",
        "Segoe MDL2 Assets", "Segoe Print", "Segoe Script", "Segoe UI", "Segoe UI Emoji",
        "Segoe UI Historic", "Segoe UI Symbol", "Segoe UI Variable", "SimSun",
        "Sitka Banner", "Sitka Text", "Sylfaen", "Symbol", "Tahoma",
        "Times New Roman", "Trebuchet MS", "Verdana", "Webdings", "Wingdings", "Yu Gothic",
    ]
    loc = (profile.locale or "en-US").lower()
    cc = (profile.country or "").upper()
    if loc.startswith("en-in") or cc == "IN" or loc.startswith("hi"):
        fonts.extend(["Utsaah", "Vrinda", "Mangal", "Kokila", "Aparajita", "Kartika"])
    if loc.startswith("ar") or cc in ("EG", "SA", "AE"):
        fonts.extend(["Traditional Arabic", "Simplified Arabic", "Aldhabi"])
    if loc.startswith("zh") or cc in ("CN", "TW", "HK"):
        fonts.extend(["Microsoft YaHei UI", "SimHei", "KaiTi", "FangSong"])
    if loc.startswith("ja") or cc == "JP":
        fonts.extend(["Yu Gothic UI", "Meiryo", "MS PGothic", "MS Mincho"])
    if loc.startswith("ko") or cc == "KR":
        fonts.extend(["Malgun Gothic Semilight", "Batang", "Gulim"])
    if loc.startswith("ru") or cc in ("RU", "UA", "BY"):
        fonts.extend(["Segoe UI", "Arial"])
    return sorted(set(fonts))


def _speech_voices(profile: PCProfile) -> list[dict[str, Any]]:
    loc = (profile.locale or "en-US").lower()
    cc = (profile.country or "").upper()

    if loc.startswith("ar") or cc in ("EG", "SA", "AE"):
        return [
            {"name": "Microsoft Hoda - Arabic (Egypt)", "lang": "ar-EG", "localService": True, "default": True, "voiceURI": "hoda"},
            {"name": "Microsoft Naayf - Arabic (Saudi Arabia)", "lang": "ar-SA", "localService": True, "default": False, "voiceURI": "naayf"},
        ]
    if loc.startswith("id") or cc == "ID":
        return [
            {"name": "Microsoft Gadis - Indonesian (Indonesia)", "lang": "id-ID", "localService": True, "default": True, "voiceURI": "gadis"},
            {"name": "Microsoft Andika - Indonesian (Indonesia)", "lang": "id-ID", "localService": True, "default": False, "voiceURI": "andika"},
        ]
    if loc.startswith("en-in") or cc == "IN":
        return [
            {"name": "Microsoft Heera - English (India)", "lang": "en-IN", "localService": True, "default": True, "voiceURI": "heera"},
            {"name": "Microsoft Hemant - English (India)", "lang": "en-IN", "localService": True, "default": False, "voiceURI": "hemant"},
        ]
    if loc.startswith("hi"):
        return [
            {"name": "Microsoft Hemant - Hindi (India)", "lang": "hi-IN", "localService": True, "default": True, "voiceURI": "hemant-hi"},
        ]
    return [
        {"name": "Microsoft David Desktop - English (United States)", "lang": "en-US", "localService": True, "default": True, "voiceURI": "david"},
        {"name": "Microsoft Zira Desktop - English (United States)", "lang": "en-US", "localService": True, "default": False, "voiceURI": "zira"},
    ]


def _heap_limit_mb(profile: PCProfile) -> int:
    gb = profile.device_memory_gb or 8
    return min(gb * 512, 4096)


def antidetect_report_lines(
    profile: PCProfile,
    proxy_info: str,
    *,
    instance_id: str = "",
) -> list[tuple[str, str]]:
    tz_src = {
        "exit_ip": "exit-IP (авто)",
        "identity": "identity IP / pc_info",
    }.get(profile.geo_source, "information.txt / geo")
    geo = profile.geolocation
    geo_txt = (
        f"{geo.get('latitude', 0):.4f}, {geo.get('longitude', 0):.4f}"
        if geo.get("latitude")
        else "—"
    )
    tls_src = (
        f"CFT major {profile.chrome_major} ({profile.chrome_version})"
        if "chrome_daily_binary" in profile._defaults_used
        else (profile.chrome_version or "—")
    )
    webrtc_mode = (
        "ограничен Chromium proxy policy"
        if profile.exit_ip
        else "нативный Chromium"
    )
    return [
        ("Browser ID", instance_id[:16] + "…" if len(instance_id) > 16 else instance_id or "—"),
        ("Платформа", _platform_label(profile)),
        ("UserAgent", profile.user_agent),
        ("TLS / Chrome", tls_src),
        ("Прокси", proxy_info),
        ("WebRTC", webrtc_mode),
        ("JS-патчи", "consistency-first: PCProfile + native Chromium"),
        ("Canvas / Audio", "sparse стабильный noise по Browser ID"),
        ("WebGL / WebGPU", f"VideoCard: {profile.video_card or 'Intel UHD fallback'}"),
        ("Шрифты / plugins", "Windows-набор профиля / Chrome PDF"),
        ("Часовой пояс", f"{profile.timezone} ({tz_src})"),
        ("Язык", profile.locale or "—"),
        ("Геолокация", f"{geo_txt} ({tz_src})"),
        ("Процессор", f"{profile.threads or profile.cores} ядер"),
        ("Память", f"{profile.device_memory_gb} ГБ (performance.memory)"),
        ("Экран", f"{profile.display_width}x{profile.display_height} DPR {profile.device_pixel_ratio}"),
        ("Workers / iframe", "нативная parity Chromium"),
        ("Automation", "Patchright + native Chromium surfaces"),
        ("Do not track", "Выкл"),
        ("Client Hints", profile.sec_ch_ua),
    ]


def _window_chrome_metrics(profile: PCProfile) -> tuple[int, int]:
    """Согласованные outerWidth/outerHeight: inner + scrollbar + chrome UI."""
    scrollbar = 16 if profile.display_width >= 1280 else 12
    chrome_ui = max(40, profile.avail_screen_height - profile.viewport["height"])
    return scrollbar, chrome_ui


def _worker_webgl_bootstrap(payload: dict[str, Any]) -> str:
    """Worker/SW parity: navigator, screen, WebGL, CH, memory, WebGPU, canvas/audio noise."""
    cfg_json = json.dumps(payload)
    return f"""(function(){{
  if (self.__ytCookiesWorker) return;
  self.__ytCookiesWorker = 1;
  const cfg = {cfg_json};
  const define = (obj, prop, value) => {{
    if (!obj) return;
    try {{ Object.defineProperty(obj, prop, {{ get: () => value, configurable: true }}); }} catch (_) {{}}
  }};
  const rand = (n) => {{ const x = Math.sin(cfg.noiseSeed + n) * 10000; return x - Math.floor(x); }};
  define(navigator, 'hardwareConcurrency', cfg.hardwareConcurrency);
  define(navigator, 'deviceMemory', cfg.deviceMemory);
  define(navigator, 'platform', cfg.platform);
  define(navigator, 'language', cfg.language);
  define(navigator, 'languages', cfg.languages);
  define(navigator, 'vendor', 'Google Inc.');
  define(navigator, 'maxTouchPoints', cfg.maxTouchPoints);
  if (navigator.userAgentData) {{
    const brands = [
      {{ brand: 'Google Chrome', version: cfg.chromeMajor }},
      {{ brand: 'Chromium', version: cfg.chromeMajor }},
      {{ brand: 'Not_A Brand', version: cfg.notABrandVersion }},
    ];
    const fullVersionList = [
      {{ brand: 'Google Chrome', version: cfg.chromeVersion }},
      {{ brand: 'Chromium', version: cfg.chromeVersion }},
      {{ brand: 'Not_A Brand', version: cfg.notABrandFullVersion }},
    ];
    define(navigator.userAgentData, 'mobile', false);
    define(navigator.userAgentData, 'platform', 'Windows');
    define(navigator.userAgentData, 'brands', brands);
    const origHigh = navigator.userAgentData.getHighEntropyValues?.bind(navigator.userAgentData);
    if (origHigh) {{
      navigator.userAgentData.getHighEntropyValues = (hints) =>
        origHigh(hints).then((values) => ({{
          ...values, brands, platform: 'Windows', platformVersion: cfg.platformVersion,
          architecture: 'x86', bitness: '64', model: '', wow64: false,
          uaFullVersion: cfg.chromeVersion, fullVersionList,
        }}));
    }}
  }}
  if (typeof screen !== 'undefined') {{
    define(screen, 'width', cfg.screenWidth);
    define(screen, 'height', cfg.screenHeight);
    define(screen, 'availWidth', cfg.availWidth);
    define(screen, 'availHeight', cfg.availHeight);
    define(screen, 'colorDepth', cfg.colorDepth);
    define(screen, 'pixelDepth', cfg.pixelDepth);
  }}
  const glParamMap = {{
    3379: cfg.webglLimits.p3379, 34024: cfg.webglLimits.p34024,
    34069: cfg.webglLimits.p34069, 3386: cfg.webglLimits.p3386,
    34921: cfg.webglLimits.p34921, 36347: cfg.webglLimits.p36347,
    36348: cfg.webglLimits.p36348, 35660: cfg.webglLimits.p35660,
    35371: cfg.webglLimits.p35371,
  }};
  const patchGl = (proto) => {{
    if (!proto?.getParameter) return;
    const orig = proto.getParameter;
    proto.getParameter = function(p) {{
      if (p === 37445) return cfg.webglVendor;
      if (p === 37446) return cfg.webglRenderer;
      if (glParamMap[p] !== undefined) return glParamMap[p];
      return orig.call(this, p);
    }};
    const origExt = proto.getExtension;
    if (origExt) proto.getExtension = function(n) {{
      const e = origExt.call(this, n);
      if (n === 'WEBGL_debug_renderer_info' && e)
        return {{ UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 }};
      return e;
    }};
  }};
  if (typeof WebGLRenderingContext !== 'undefined') patchGl(WebGLRenderingContext.prototype);
  if (typeof WebGL2RenderingContext !== 'undefined') patchGl(WebGL2RenderingContext.prototype);
  if (self.performance) {{
    const heap = cfg.heapLimitMb * 1024 * 1024;
    define(performance, 'memory', {{
      jsHeapSizeLimit: heap, totalJSHeapSize: Math.floor(heap * 0.08),
      usedJSHeapSize: Math.floor(heap * 0.05),
    }});
  }}
  if (navigator.gpu?.requestAdapter) {{
    const origGpu = navigator.gpu.requestAdapter.bind(navigator.gpu);
    navigator.gpu.requestAdapter = async (...args) => {{
      const adapter = await origGpu(...args);
      if (!adapter?.requestAdapterInfo) return adapter;
      const origInfo = adapter.requestAdapterInfo.bind(adapter);
      adapter.requestAdapterInfo = async () => {{
        const info = await origInfo();
        return {{ ...info, vendor: cfg.webgpuVendor, architecture: cfg.webgpuArchitecture,
          description: cfg.webglRenderer, device: cfg.mediaGroup }};
      }};
      return adapter;
    }};
  }}
  const canvasShift = {{
    r: Math.floor(rand(1) * 3) - 1, g: Math.floor(rand(2) * 3) - 1,
    b: Math.floor(rand(3) * 3) - 1,
  }};
  const noiseSparse = (img) => {{
    if (!img?.data || (img.width <= 16 && img.height <= 16)) return img;
    const step = Math.max(97, Math.floor(img.data.length / 64));
    for (let i = 0; i < img.data.length; i += step) {{
      img.data[i] = Math.max(0, Math.min(255, img.data[i] + canvasShift.r));
      if (i + 1 < img.data.length) img.data[i + 1] = Math.max(0, Math.min(255, img.data[i + 1] + canvasShift.g));
      if (i + 2 < img.data.length) img.data[i + 2] = Math.max(0, Math.min(255, img.data[i + 2] + canvasShift.b));
    }}
    return img;
  }};
  if (typeof OffscreenCanvas !== 'undefined' && OffscreenCanvas.prototype.convertToBlob) {{
    const origBlob = OffscreenCanvas.prototype.convertToBlob;
    OffscreenCanvas.prototype.convertToBlob = function(...args) {{
      try {{
        const ctx = this.getContext?.('2d');
        if (ctx?.getImageData) {{
          const img = ctx.getImageData(0, 0, this.width, this.height);
          ctx.putImageData(noiseSparse(img), 0, 0);
        }}
      }} catch (_) {{}}
      return origBlob.apply(this, args);
    }};
  }}
  if (typeof OffscreenCanvasRenderingContext2D !== 'undefined') {{
    const proto = OffscreenCanvasRenderingContext2D.prototype;
    if (proto.getImageData) {{
      const orig = proto.getImageData;
      proto.getImageData = function(...args) {{ return noiseSparse(orig.apply(this, args)); }};
    }}
  }}
  if (typeof AudioBuffer !== 'undefined' && AudioBuffer.prototype?.getChannelData) {{
    const orig = AudioBuffer.prototype.getChannelData;
    const audioNoise = (rand(20) - 0.5) * 1e-7;
    AudioBuffer.prototype.getChannelData = function(ch) {{
      const data = orig.call(this, ch);
      for (let i = 0; i < data.length; i += 127) data[i] += audioNoise;
      return data;
    }};
  }}
  Date.prototype.getTimezoneOffset = function() {{ return cfg.timezoneOffset; }};
  if (typeof Intl !== 'undefined' && Intl.DateTimeFormat) {{
    const OrigDTF = Intl.DateTimeFormat;
    Intl.DateTimeFormat = function(locales, options) {{
      options = {{ ...(options || {{}}) }};
      if (!options.timeZone) options.timeZone = cfg.timezone;
      return new OrigDTF(locales, options);
    }};
    Intl.DateTimeFormat.prototype = OrigDTF.prototype;
    Intl.DateTimeFormat.supportedLocalesOf = OrigDTF.supportedLocalesOf;
  }}
}})();"""


def _seeded_window_metrics(profile: PCProfile, seed: int) -> tuple[int, int]:
    base_sb, base_cu = _window_chrome_metrics(profile)
    scrollbar = max(8, base_sb + (seed % 5) - 2)
    chrome_ui = max(48, base_cu + ((seed >> 4) % 15) - 7)
    return scrollbar, chrome_ui


def _seeded_heap_mb(profile: PCProfile, seed: int) -> int:
    base = _heap_limit_mb(profile)
    return max(512, base + (seed % 127) - 63)


def _build_legacy_fingerprint_script(
    profile: PCProfile,
    *,
    instance_id: str = "",
    account_key: str = "",
    proxied: bool = False,
    host_public_ip: str = "",
) -> str:
    vendor, renderer = _webgl_renderer(profile)
    webgpu = _webgpu_info(profile)
    seed = _fingerprint_seed(profile, instance_id=instance_id, account_key=account_key)
    webgl_limits = _gpu_webgl_limits(profile)
    scrollbar, chrome_ui = _seeded_window_metrics(profile, seed)
    inner_w = profile.viewport["width"]
    inner_h = profile.viewport["height"]
    iid = instance_id or hashlib.md5(f"{seed}-{account_key}".encode()).hexdigest()
    payload = {
        "noiseSeed": seed,
        "instanceId": iid,
        "mediaGroup": hashlib.md5(f"{iid}-media".encode()).hexdigest()[:16],
        "hardwareConcurrency": max(2, int(profile.threads or profile.cores or 4)),
        "deviceMemory": min(8, max(2, int(profile.device_memory_gb or 8))),
        "platform": profile.platform,
        "languages": profile.languages,
        "language": profile.locale,
        "screenWidth": profile.display_width,
        "screenHeight": profile.display_height,
        "availWidth": profile.display_width,
        "availHeight": profile.avail_screen_height,
        "availTop": 0,
        "availLeft": 0,
        "colorDepth": 24,
        "pixelDepth": 24,
        "devicePixelRatio": profile.device_pixel_ratio,
        "innerWidth": inner_w,
        "innerHeight": inner_h,
        "outerWidth": inner_w + scrollbar,
        "outerHeight": inner_h + chrome_ui,
        "scrollbarWidth": scrollbar,
        "chromeUiHeight": chrome_ui,
        "webrtcPublicIp": profile.exit_ip or profile.ip or "",
        "webrtcRelayOnly": bool(proxied),
        "hostPublicIps": [ip for ip in (host_public_ip,) if ip],
        "maxTouchPoints": 0,
        "webglVendor": vendor,
        "webglRenderer": renderer,
        "webglLimits": webgl_limits,
        "webgpuVendor": webgpu["vendor"],
        "webgpuArchitecture": webgpu["architecture"],
        "fonts": _windows_fonts(profile),
        "voices": _speech_voices(profile),
        "heapLimitMb": _seeded_heap_mb(profile, seed),
        "windowsBuild": profile.windows_build,
        "platformVersion": profile.platform_version,
        "chromeVersion": profile.chrome_version or "131.0.0.0",
        "chromeMajor": profile.chrome_major or "131",
        "notABrandVersion": profile.not_a_brand_version,
        "notABrandFullVersion": f"{profile.not_a_brand_version}.0.0.0",
        "timezone": profile.timezone or "UTC",
        "timezoneOffset": profile.timezone_offset_minutes,
        "isWindows11": profile.is_windows_11,
        "geoLatitude": profile.geolocation.get("latitude", 0),
        "geoLongitude": profile.geolocation.get("longitude", 0),
        "geoAccuracy": 100,
    }
    worker_bootstrap = _worker_webgl_bootstrap(payload)

    return f"""
(() => {{
  if (window.__ytCookiesFp) return;
  try {{
    Object.defineProperty(window, '__ytCookiesFp', {{
      value: 1, enumerable: false, configurable: false, writable: false,
    }});
  }} catch (_) {{
    window.__ytCookiesFp = 1;
  }}
  const cfg = {json.dumps(payload)};

  // --- stealth: маскировка Function.prototype.toString (puppeteer-extra-stealth) ---
  const _nativeStore = new Map();
  const _origFnToString = Function.prototype.toString;
  Function.prototype.toString = function toString() {{
    if (_nativeStore.has(this)) return _nativeStore.get(this);
    return _origFnToString.call(this);
  }};
  _nativeStore.set(Function.prototype.toString, 'function toString() {{ [native code] }}');
  const nativeFn = (fn, name) => {{
    _nativeStore.set(fn, `function ${{name || fn.name || ''}}() {{ [native code] }}`);
    return fn;
  }};

  const define = (obj, prop, value) => {{
    if (!obj) return;
    try {{
      Object.defineProperty(obj, prop, {{ get: () => value, configurable: true }});
    }} catch (_) {{}}
  }};
  const defineNav = (prop, value) => define(navigator, prop, value);

  const rand = (n) => {{
    const x = Math.sin(cfg.noiseSeed + n) * 10000;
    return x - Math.floor(x);
  }};

  // --- automation / headless markers ---
  // Intoli WebDriver(New): свойство webdriver не должно присутствовать ('webdriver' in navigator === false)
  try {{
    const navProto = Object.getPrototypeOf(navigator);
    if (navProto && 'webdriver' in navProto) delete navProto.webdriver;
    if ('webdriver' in navigator) {{
      try {{ delete navigator.webdriver; }} catch (_) {{ Reflect.deleteProperty(navigator, 'webdriver'); }}
    }}
  }} catch (_) {{}}
  const scrubAutomationGlobals = (root) => {{
    if (!root) return;
    for (const key of Object.keys(root)) {{
      if (/^cdc_|\\$cdc_|__pw|__playwright|__webdriver|__selenium|__fx|__driver/i.test(key)) {{
        try {{ delete root[key]; }} catch (_) {{}}
      }}
    }}
  }};
  scrubAutomationGlobals(window);
  scrubAutomationGlobals(document);
  try {{ delete window.__playwright; delete window.__pwInitScripts; delete window.__playwright__binding__; }} catch (_) {{}}

  // --- navigator ---
  defineNav('hardwareConcurrency', cfg.hardwareConcurrency);
  defineNav('deviceMemory', cfg.deviceMemory);
  defineNav('platform', cfg.platform);
  defineNav('languages', cfg.languages);
  defineNav('language', cfg.language);
  defineNav('maxTouchPoints', cfg.maxTouchPoints);
  defineNav('vendor', 'Google Inc.');
  defineNav('vendorSub', '');
  defineNav('productSub', '20030107');
  defineNav('product', 'Gecko');
  defineNav('appCodeName', 'Mozilla');
  defineNav('appName', 'Netscape');
  defineNav('pdfViewerEnabled', true);
  defineNav('cookieEnabled', true);
  defineNav('doNotTrack', null);
  defineNav('globalPrivacyControl', undefined);
  defineNav('oscpu', undefined);
  defineNav('buildID', undefined);
  if (navigator.queryLocalFonts) {{
    const origFonts = navigator.queryLocalFonts.bind(navigator);
    navigator.queryLocalFonts = nativeFn(async function queryLocalFonts() {{
      try {{
        const real = await origFonts();
        if (real && real.length) return real;
      }} catch (_) {{}}
      return (cfg.fonts || []).map((family) => ({{
        family, fullName: family, postscriptName: family, style: 'Regular',
      }}));
    }}, 'queryLocalFonts');
  }}
  try {{
    const navProto = Object.getPrototypeOf(navigator);
    if (navProto) {{
      navProto.getGamepads = nativeFn(function getGamepads() {{ return []; }}, 'getGamepads');
    }}
  }} catch (_) {{}}
  defineNav('javaEnabled', () => false);

  // --- screen ---
  define(screen, 'width', cfg.screenWidth);
  define(screen, 'height', cfg.screenHeight);
  define(screen, 'availWidth', cfg.availWidth);
  define(screen, 'availHeight', cfg.availHeight);
  define(screen, 'availTop', cfg.availTop);
  define(screen, 'availLeft', cfg.availLeft);
  define(screen, 'colorDepth', cfg.colorDepth);
  define(screen, 'pixelDepth', cfg.pixelDepth);
  define(screen, 'orientation', {{
    type: 'landscape-primary', angle: 0, onchange: null,
    addEventListener: () => {{}}, removeEventListener: () => {{}},
  }});
  define(window, 'devicePixelRatio', cfg.devicePixelRatio);
  define(window, 'outerWidth', cfg.outerWidth);
  define(window, 'outerHeight', cfg.outerHeight);
  define(window, 'innerWidth', cfg.innerWidth);
  define(window, 'innerHeight', cfg.innerHeight);
  define(window, 'screenX', 0);
  define(window, 'screenY', 0);
  define(window, 'screenLeft', 0);
  define(window, 'screenTop', 0);

  // --- visualViewport (согласован с innerWidth/Height и DPR) ---
  const visualViewportObj = {{
    width: cfg.innerWidth,
    height: cfg.innerHeight,
    scale: cfg.devicePixelRatio,
    offsetLeft: 0,
    offsetTop: 0,
    pageLeft: 0,
    pageTop: 0,
    onresize: null,
    onscroll: null,
    addEventListener: nativeFn(function addEventListener() {{}}, 'addEventListener'),
    removeEventListener: nativeFn(function removeEventListener() {{}}, 'removeEventListener'),
    dispatchEvent: nativeFn(function dispatchEvent() {{ return true; }}, 'dispatchEvent'),
  }};
  try {{
    Object.defineProperty(window, 'visualViewport', {{
      get: () => visualViewportObj,
      configurable: true,
    }});
  }} catch (_) {{}}

  // --- WebGL (vendor + GPU limits) ---
  const glParamMap = {{
    3379: cfg.webglLimits.p3379,
    34024: cfg.webglLimits.p34024,
    34069: cfg.webglLimits.p34069,
    3386: cfg.webglLimits.p3386,
    34921: cfg.webglLimits.p34921,
    36347: cfg.webglLimits.p36347,
    36348: cfg.webglLimits.p36348,
    35660: cfg.webglLimits.p35660,
    35371: cfg.webglLimits.p35371,
  }};
  const patchWebGL = (proto) => {{
    if (!proto?.getParameter) return;
    const original = proto.getParameter;
    proto.getParameter = nativeFn(function getParameter(param) {{
      if (param === 37445) return cfg.webglVendor;
      if (param === 37446) return cfg.webglRenderer;
      if (glParamMap[param] !== undefined) return glParamMap[param];
      return original.call(this, param);
    }}, 'getParameter');
    const origExt = proto.getExtension;
    if (origExt) {{
      proto.getExtension = nativeFn(function getExtension(name) {{
        const ext = origExt.call(this, name);
        if (name === 'WEBGL_debug_renderer_info' && ext) {{
          return {{ UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 }};
        }}
        return ext;
      }}, 'getExtension');
    }}
    // readPixels: sparse noise (не трогаем каждый пиксель — ломает YouTube/Studio)
    if (proto.readPixels) {{
      const origRead = proto.readPixels;
      proto.readPixels = nativeFn(function readPixels(...args) {{
        origRead.apply(this, args);
        try {{
          const pixels = args[6];
          if (pixels && pixels.length > 64) {{
            const n = Math.floor(rand(55) * 3) - 1;
            const step = Math.max(64, Math.floor(pixels.length / 32));
            for (let i = 0; i < pixels.length; i += step) pixels[i] = (pixels[i] + n) & 255;
          }}
        }} catch (_) {{}}
      }}, 'readPixels');
    }}
  }};
  patchWebGL(WebGLRenderingContext?.prototype);
  patchWebGL(WebGL2RenderingContext?.prototype);

  // --- Canvas / OffscreenCanvas: sparse noise по Browser ID (не ломает video canvas) ---
  const canvasShift = {{
    r: Math.floor(rand(1) * 3) - 1, g: Math.floor(rand(2) * 3) - 1,
    b: Math.floor(rand(3) * 3) - 1,
  }};
  const noiseImageData = (img) => {{
    if (!img?.data || (img.width <= 16 && img.height <= 16)) return img;
    if (img.width * img.height > 512 * 512) return img;
    const step = Math.max(97, Math.floor(img.data.length / 64));
    for (let i = 0; i < img.data.length; i += step) {{
      img.data[i]     = Math.max(0, Math.min(255, img.data[i]     + canvasShift.r));
      if (i + 1 < img.data.length)
        img.data[i + 1] = Math.max(0, Math.min(255, img.data[i + 1] + canvasShift.g));
      if (i + 2 < img.data.length)
        img.data[i + 2] = Math.max(0, Math.min(255, img.data[i + 2] + canvasShift.b));
    }}
    return img;
  }};
  const applyCanvasNoise = (ctx, w, h) => {{
    if (!ctx || w <= 0 || h <= 0 || w * h > 512 * 512) return;
    try {{
      const img = CanvasRenderingContext2D.prototype.getImageData.call(ctx, 0, 0, w, h);
      ctx.putImageData(noiseImageData(img), 0, 0);
    }} catch (_) {{}}
  }};
  const patchCanvasProto = (Cls) => {{
    if (!Cls?.prototype) return;
    const orig = Cls.prototype.toDataURL;
    if (orig) Cls.prototype.toDataURL = nativeFn(function toDataURL(...args) {{
      const ctx = this.getContext?.('2d');
      if (ctx) applyCanvasNoise(ctx, this.width, this.height);
      return orig.apply(this, args);
    }}, 'toDataURL');
    const origBlob = Cls.prototype.toBlob;
    if (origBlob) Cls.prototype.toBlob = nativeFn(function toBlob(...args) {{
      const ctx = this.getContext?.('2d');
      if (ctx) applyCanvasNoise(ctx, this.width, this.height);
      return origBlob.apply(this, args);
    }}, 'toBlob');
  }};
  patchCanvasProto(HTMLCanvasElement);
  if (typeof OffscreenCanvas !== 'undefined') patchCanvasProto(OffscreenCanvas);

  const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = nativeFn(function getImageData(...args) {{
    return noiseImageData(origGetImageData.apply(this, args));
  }}, 'getImageData');

  const fontNoise = (rand(30) - 0.5) * 0.00005;
  const origMeasure = CanvasRenderingContext2D.prototype.measureText;
  CanvasRenderingContext2D.prototype.measureText = nativeFn(function measureText(text) {{
    const m = origMeasure.call(this, text);
    const w = m.width + fontNoise;
    try {{
      return new Proxy(m, {{ get: (t, p) => (p === 'width' ? w : t[p]) }});
    }} catch (_) {{
      return {{ ...m, width: w }};
    }}
  }}, 'measureText');

  // --- ClientRects: микросдвиг (стабильный по seed) ---
  const rectNoise = (rand(10) - 0.5) * 0.0001;
  const patchRect = (obj, name) => {{
    if (!obj?.[name]) return;
    const orig = obj[name];
    obj[name] = nativeFn(function(...args) {{
      const rect = orig.apply(this, args);
      if (!rect) return rect;
      if (name === 'getClientRects') {{
        const list = [];
        for (let i = 0; i < rect.length; i++) {{
          const r = rect[i];
          list.push(new DOMRect(r.x + rectNoise, r.y + rectNoise, r.width, r.height));
        }}
        list.item = (i) => list[i] || null;
        return list;
      }}
      return new DOMRect(rect.x + rectNoise, rect.y + rectNoise, rect.width, rect.height);
    }}, name);
  }};
  patchRect(Element.prototype, 'getBoundingClientRect');
  patchRect(Element.prototype, 'getClientRects');
  patchRect(Range.prototype, 'getBoundingClientRect');
  patchRect(Range.prototype, 'getClientRects');

  // --- Fonts: не форсировать true (ломает check↔measure); резать экзотику вне профиля ---
  if (document.fonts) {{
    const fontSet = new Set(cfg.fonts.map((f) => f.toLowerCase()));
    const extractFamily = (spec) => {{
      const m = String(spec).match(/(?:^|\\s)(?:\\d+px\\s+)?["']?([^"']+?)["']?\\s*$/i)
        || String(spec).match(/["']([^"']+)["']/);
      return (m ? m[1] : String(spec)).trim().toLowerCase().split(',')[0].trim();
    }};
    if (document.fonts.check) {{
      const origCheck = document.fonts.check.bind(document.fonts);
      document.fonts.check = nativeFn(function check(font, text) {{
        const fam = extractFamily(font);
        if (fam && !fontSet.has(fam) && ![...fontSet].some((f) => fam.includes(f) || f.includes(fam))) {{
          if (!/^(serif|sans-serif|monospace|cursive|fantasy|system-ui|emoji|math|fangsong)$/i.test(fam))
            return false;
        }}
        return origCheck(font, text);
      }}, 'check');
    }}
    if (document.fonts.values) {{
      const OrigValues = document.fonts.values.bind(document.fonts);
      document.fonts.values = nativeFn(function values() {{
        const it = OrigValues();
        const kept = [];
        for (const face of it) {{
          const fam = String(face.family || '').replace(/["']/g, '').toLowerCase();
          if (!fam || fontSet.has(fam) || [...fontSet].some((f) => fam.includes(f))) kept.push(face);
        }}
        return kept[Symbol.iterator]();
      }}, 'values');
    }}
  }}

  // --- Audio noise ---
  if (AudioBuffer?.prototype?.getChannelData) {{
    const orig = AudioBuffer.prototype.getChannelData;
    const audioNoise = (rand(20) - 0.5) * 1e-7;
    AudioBuffer.prototype.getChannelData = nativeFn(function getChannelData(ch) {{
      const data = orig.call(this, ch);
      for (let i = 0; i < data.length; i += 127) data[i] += audioNoise;
      return data;
    }}, 'getChannelData');
  }}
  if (AnalyserNode?.prototype?.getFloatFrequencyData) {{
    const orig = AnalyserNode.prototype.getFloatFrequencyData;
    const freqNoise = (rand(21) - 0.5) * 0.01;
    AnalyserNode.prototype.getFloatFrequencyData = function(arr) {{
      orig.call(this, arr);
      for (let i = 0; i < arr.length; i += 53) arr[i] += freqNoise;
    }};
  }}
  if (AnalyserNode?.prototype?.getByteFrequencyData) {{
    const orig = AnalyserNode.prototype.getByteFrequencyData;
    AnalyserNode.prototype.getByteFrequencyData = nativeFn(function getByteFrequencyData(arr) {{
      orig.call(this, arr);
      for (let i = 0; i < arr.length; i += 67) arr[i] = (arr[i] + Math.floor(rand(22) * 3)) & 255;
    }}, 'getByteFrequencyData');
  }}

  // --- OfflineAudioContext (CreepJS / fingerprintjs) ---
  if (typeof OfflineAudioContext !== 'undefined') {{
    const OrigOff = OfflineAudioContext;
    const audioNoise = (rand(23) - 0.5) * 1e-7;
    const OffCtx = nativeFn(function OfflineAudioContext(...args) {{
      const ctx = new OrigOff(...args);
      const origStart = ctx.startRendering.bind(ctx);
      ctx.startRendering = nativeFn(function startRendering() {{
        return origStart().then((buf) => {{
          try {{
            const ch = buf.getChannelData(0);
            for (let i = 0; i < ch.length; i += 131) ch[i] += audioNoise;
          }} catch (_) {{}}
          return buf;
        }});
      }}, 'startRendering');
      return ctx;
    }}, 'OfflineAudioContext');
    OffCtx.prototype = OrigOff.prototype;
    window.OfflineAudioContext = OffCtx;
  }}

  // --- WebGPU (согласован с VideoCard / WebGL) ---
  if (navigator.gpu?.requestAdapter) {{
    const origGpu = navigator.gpu.requestAdapter.bind(navigator.gpu);
    navigator.gpu.requestAdapter = nativeFn(async function requestAdapter(...args) {{
      const adapter = await origGpu(...args);
      if (!adapter?.requestAdapterInfo) return adapter;
      const origInfo = adapter.requestAdapterInfo.bind(adapter);
      adapter.requestAdapterInfo = nativeFn(async function requestAdapterInfo() {{
        const info = await origInfo();
        return {{
          ...info,
          vendor: cfg.webgpuVendor,
          architecture: cfg.webgpuArchitecture,
          description: cfg.webglRenderer,
          device: cfg.mediaGroup,
        }};
      }}, 'requestAdapterInfo');
      return adapter;
    }}, 'requestAdapter');
  }}

  // --- Media devices (всегда подмена без реальных label) ---
  if (navigator.mediaDevices?.enumerateDevices) {{
    const gid = cfg.mediaGroup;
    const did = (suffix) => (cfg.instanceId ? cfg.instanceId.slice(0, 12) + suffix : gid + suffix);
    const fake = [
      {{ deviceId: did('a1'), kind: 'audioinput', label: '', groupId: gid }},
      {{ deviceId: did('a2'), kind: 'audioinput', label: '', groupId: gid }},
      {{ deviceId: did('o1'), kind: 'audiooutput', label: '', groupId: gid }},
      {{ deviceId: did('v1'), kind: 'videoinput', label: '', groupId: gid }},
    ];
    navigator.mediaDevices.enumerateDevices = async () => fake;
  }}
  if (navigator.mediaDevices?.getUserMedia) {{
    const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = (c) => orig(c).catch(() => Promise.reject(new DOMException('NotAllowedError')));
  }}

  // --- Speech synthesis voices ---
  if (window.speechSynthesis) {{
    const voices = cfg.voices.map((v, i) => ({{
      voiceURI: v.voiceURI || String(i), name: v.name, lang: v.lang,
      localService: !!v.localService, default: !!v.default,
    }}));
    speechSynthesis.getVoices = () => voices;
    define(speechSynthesis, 'getVoices', () => voices);
  }}

  // --- Battery (desktop: charging) ---
  if (navigator.getBattery) {{
    navigator.getBattery = () => Promise.resolve({{
      charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1.0,
      addEventListener: () => {{}}, removeEventListener: () => {{}},
    }});
  }}

  // --- performance.memory ---
  if (performance) {{
    const heap = cfg.heapLimitMb * 1024 * 1024;
    define(performance, 'memory', {{
      jsHeapSizeLimit: heap, totalJSHeapSize: Math.floor(heap * 0.08),
      usedJSHeapSize: Math.floor(heap * 0.05),
    }});
  }}

  // --- storage.estimate ---
  if (navigator.storage?.estimate) {{
    navigator.storage.estimate = () => Promise.resolve({{
      quota: cfg.deviceMemory * 1024 * 1024 * 1024 * 0.4,
      usage: Math.floor(rand(40) * 1024 * 1024),
      usageDetails: {{}},
    }});
  }}

  // --- matchMedia consistency ---
  const origMatch = window.matchMedia?.bind(window);
  if (origMatch) {{
    window.matchMedia = (query) => {{
      const m = origMatch(query);
      const q = String(query);
      if (/prefers-color-scheme:\\s*light/i.test(q)) {{
        define(m, 'matches', true);
      }}
      if (/prefers-reduced-motion:\\s*no/i.test(q)) {{
        define(m, 'matches', true);
      }}
      return m;
    }};
  }}

  // --- chrome.runtime / csi / loadTimes (как у реального Chrome, без extension id) ---
  if (!window.chrome) window.chrome = {{}};
  const chromeRuntime = {{
    connect: nativeFn(function connect() {{
      return {{
        onMessage: {{ addListener: nativeFn(function addListener() {{}}, 'addListener') }},
        onDisconnect: {{ addListener: nativeFn(function addListener() {{}}, 'addListener') }},
        postMessage: nativeFn(function postMessage() {{}}, 'postMessage'),
        disconnect: nativeFn(function disconnect() {{}}, 'disconnect'),
      }};
    }}, 'connect'),
    sendMessage: nativeFn(function sendMessage() {{}}, 'sendMessage'),
    id: undefined,
    OnInstalledReason: {{ CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' }},
    OnRestartRequiredReason: {{ APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }},
    PlatformArch: {{ ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }},
    PlatformNaclArch: {{ ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' }},
    PlatformOs: {{ ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' }},
    RequestUpdateCheckStatus: {{ NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }},
  }};
  window.chrome.runtime = window.chrome.runtime || chromeRuntime;
  window.chrome.app = window.chrome.app || {{
    isInstalled: false,
    InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
    RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }},
    getDetails: nativeFn(function getDetails() {{ return null; }}, 'getDetails'),
    getIsInstalled: nativeFn(function getIsInstalled() {{ return false; }}, 'getIsInstalled'),
  }};
  const navStart = (performance?.timing?.navigationStart) || (Date.now() - Math.floor(rand(60) * 800 + 200));
  window.chrome.csi = nativeFn(function csi() {{
    const now = Date.now();
    return {{ onloadT: now, startE: navStart, pageT: now - navStart, tran: 15 }};
  }}, 'csi');
  window.chrome.loadTimes = nativeFn(function loadTimes() {{
    const t = performance?.timing || {{}};
    const toSec = (ms) => (ms && ms > 0 ? ms / 1000 : Date.now() / 1000);
    return {{
      requestTime: toSec(t.navigationStart || navStart),
      startLoadTime: toSec(t.navigationStart || navStart),
      commitLoadTime: toSec(t.responseStart || navStart + 40),
      finishDocumentLoadTime: toSec(t.domContentLoadedEventEnd || navStart + 120),
      finishLoadTime: toSec(t.loadEventEnd || navStart + 180),
      firstPaintTime: toSec((t.domContentLoadedEventEnd || navStart + 100) + 10),
      firstPaintAfterLoadTime: 0,
      navigationType: 'Other',
      wasFetchedViaSpdy: true,
      wasNpnNegotiated: true,
      npnNegotiatedProtocol: 'h2',
      wasAlternateProtocolAvailable: false,
      connectionInfo: 'h2',
    }};
  }}, 'loadTimes');

  // --- User-Agent Client Hints ---
  if (navigator.userAgentData) {{
    const brands = [
      {{ brand: 'Google Chrome', version: cfg.chromeMajor }},
      {{ brand: 'Chromium', version: cfg.chromeMajor }},
      {{ brand: 'Not_A Brand', version: cfg.notABrandVersion }},
    ];
    const fullVersionList = [
      {{ brand: 'Google Chrome', version: cfg.chromeVersion }},
      {{ brand: 'Chromium', version: cfg.chromeVersion }},
      {{ brand: 'Not_A Brand', version: cfg.notABrandFullVersion }},
    ];
    define(navigator.userAgentData, 'mobile', false);
    define(navigator.userAgentData, 'platform', 'Windows');
    define(navigator.userAgentData, 'brands', brands);
    const origHigh = navigator.userAgentData.getHighEntropyValues?.bind(navigator.userAgentData);
    navigator.userAgentData.getHighEntropyValues = nativeFn(function getHighEntropyValues(hints) {{
      const base = origHigh ? origHigh(hints) : Promise.resolve({{}});
      return base.then((values) => ({{
        ...values,
        brands,
        platform: 'Windows',
        platformVersion: cfg.platformVersion,
        architecture: 'x86',
        bitness: '64',
        model: '',
        wow64: false,
        uaFullVersion: cfg.chromeVersion,
        fullVersionList,
      }}));
    }}, 'getHighEntropyValues');
  }}

  // --- timezone / Intl ---
  Date.prototype.getTimezoneOffset = nativeFn(function getTimezoneOffset() {{
    return cfg.timezoneOffset;
  }}, 'getTimezoneOffset');
  const withProfileTz = (options) => {{
    const o = {{ ...(options || {{}}) }};
    if (!o.timeZone) o.timeZone = cfg.timezone;
    return o;
  }};
  for (const m of ['toLocaleString', 'toLocaleDateString', 'toLocaleTimeString']) {{
    const orig = Date.prototype[m];
    if (orig) {{
      Date.prototype[m] = nativeFn(function(...args) {{
        const locales = args.length > 0 ? args[0] : cfg.language;
        const opts = withProfileTz(args.length > 1 ? args[1] : undefined);
        return orig.call(this, locales, opts);
      }}, m);
    }}
  }}
  const OrigDTF = Intl.DateTimeFormat;
  Intl.DateTimeFormat = nativeFn(function DateTimeFormat(locales, options) {{
    options = {{ ...(options || {{}}) }};
    if (!options.timeZone) options.timeZone = cfg.timezone;
    return new OrigDTF(locales, options);
  }}, 'DateTimeFormat');
  Intl.DateTimeFormat.prototype = OrigDTF.prototype;
  Intl.DateTimeFormat.supportedLocalesOf = OrigDTF.supportedLocalesOf;
  const origResolved = OrigDTF.prototype.resolvedOptions;
  if (origResolved) {{
    OrigDTF.prototype.resolvedOptions = nativeFn(function resolvedOptions() {{
      const o = origResolved.call(this);
      return {{ ...o, timeZone: cfg.timezone, locale: o.locale || cfg.language }};
    }}, 'resolvedOptions');
  }}
  const OrigNumber = Intl.NumberFormat;
  Intl.NumberFormat = nativeFn(function NumberFormat(locales, options) {{
    if (!(this instanceof Intl.NumberFormat)) return OrigNumber(locales || cfg.language, options);
    return new OrigNumber(locales || cfg.language, options);
  }}, 'NumberFormat');
  Intl.NumberFormat.prototype = OrigNumber.prototype;
  Intl.NumberFormat.supportedLocalesOf = OrigNumber.supportedLocalesOf;

  // --- network ---
  if (navigator.connection) {{
    define(navigator.connection, 'effectiveType', '4g');
    define(navigator.connection, 'rtt', 50);
    define(navigator.connection, 'downlink', 10);
    define(navigator.connection, 'saveData', false);
    define(navigator.connection, 'type', 'wifi');
  }}

  // --- geolocation (из профиля, не реальный GPS) ---
  if (navigator.geolocation) {{
    const geoPos = {{
      coords: {{
        latitude: cfg.geoLatitude,
        longitude: cfg.geoLongitude,
        accuracy: cfg.geoAccuracy,
        altitude: null,
        altitudeAccuracy: null,
        heading: null,
        speed: null,
      }},
      timestamp: Date.now(),
    }};
    navigator.geolocation.getCurrentPosition = nativeFn(function getCurrentPosition(success, _error, _options) {{
      if (typeof success === 'function') success(geoPos);
    }}, 'getCurrentPosition');
    navigator.geolocation.watchPosition = nativeFn(function watchPosition(success, _error, _options) {{
      if (typeof success === 'function') success(geoPos);
      return 1;
    }}, 'watchPosition');
  }}

  // --- Notification.permission согласован с permissions.query('notifications') ---
  // Рассинхрон (permission='denied', query='prompt') — известный сигнал ботоловов.
  try {{
    if (typeof Notification !== 'undefined') {{
      Object.defineProperty(Notification, 'permission', {{ get: () => 'default', configurable: true }});
    }}
  }} catch (_) {{}}

  // --- permissions (Intoli: notifications !== denied) ---
  const originalQuery = navigator.permissions?.query;
  if (originalQuery) {{
    navigator.permissions.query = nativeFn(function query(parameters) {{
      const n = parameters?.name;
      if (n === 'notifications') return Promise.resolve({{ state: 'prompt', onchange: null }});
      if (n === 'push') return Promise.resolve({{ state: 'prompt', onchange: null }});
      if (n === 'geolocation') return Promise.resolve({{ state: 'prompt', onchange: null }});
      if (['camera', 'microphone', 'midi'].includes(n)) return Promise.resolve({{ state: 'prompt', onchange: null }});
      return originalQuery(parameters);
    }}, 'query');
  }}

  // --- plugins / mimeTypes (PluginArray + MimeTypeArray, puppeteer-extra magicArray) ---
  const createMagicArray = (dataList, proto, itemProto, mainProp) => {{
    const defineProp = (obj, prop, value) =>
      Object.defineProperty(obj, prop, {{ value, writable: false, enumerable: false, configurable: true }});
    const items = dataList.map((data) => {{
      const desc = {{}};
      for (const k of Object.keys(data)) {{
        if (k.startsWith('__')) continue;
        desc[k] = {{ value: data[k], writable: false, enumerable: false, configurable: true }};
      }}
      if (itemProto === Plugin.prototype && data.__mimeTypes) {{
        desc.length = {{ value: data.__mimeTypes.length, writable: false, enumerable: false, configurable: true }};
      }}
      const item = Object.create(itemProto, desc);
      const skip = [...Object.keys(data), 'length', 'enabledPlugin'];
      return new Proxy(item, {{
        ownKeys() {{ return Reflect.ownKeys(item).filter((k) => !skip.includes(k)); }},
        getOwnPropertyDescriptor(t, p) {{
          if (skip.includes(p)) return undefined;
          return Reflect.getOwnPropertyDescriptor(t, p);
        }},
      }});
    }});
    const arr = Object.create(proto, {{
      ...Object.getOwnPropertyDescriptors(items),
      length: {{ value: items.length, writable: false, enumerable: false, configurable: true }},
    }});
    items.forEach((entry) => defineProp(arr, entry[mainProp], entry));
    const typeKeys = items.map((e) => e[mainProp]);
    return new Proxy(arr, {{
      get(target, key = '') {{
        if (key === 'item') {{
          return nativeFn(function item(i) {{
            if (arguments.length === 0) throw new TypeError('1 argument required');
            const n = Number(i);
            return (Number.isInteger(n) ? items[n] : items[0]) || null;
          }}, 'item');
        }}
        if (key === 'namedItem') {{
          return nativeFn(function namedItem(name) {{
            if (arguments.length === 0) throw new TypeError('1 argument required');
            return items.find((e) => e[mainProp] === name) || null;
          }}, 'namedItem');
        }}
        if (proto === PluginArray.prototype && key === 'refresh') {{
          return nativeFn(function refresh() {{}}, 'refresh');
        }}
        return Reflect.get(target, key);
      }},
      ownKeys() {{
        const keys = [];
        typeKeys.forEach((_, i) => keys.push(String(i)));
        typeKeys.forEach((k) => keys.push(k));
        return keys;
      }},
      getOwnPropertyDescriptor(target, prop) {{
        if (prop === 'length') return undefined;
        return Reflect.getOwnPropertyDescriptor(target, prop);
      }},
    }});
  }};

  const pdfMimeData = {{
    type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format',
  }};
  const pdfPluginData = {{
    name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
    __mimeTypes: [pdfMimeData],
  }};
  const pdfViewerData = {{
    name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: 'Portable Document Format',
    __mimeTypes: [pdfMimeData],
  }};
  const mimeTypes = createMagicArray([pdfMimeData], MimeTypeArray.prototype, MimeType.prototype, 'type');
  const pdfMime = mimeTypes.item(0);
  if (pdfMime) {{
    try {{ Object.defineProperty(pdfMime, 'enabledPlugin', {{ get: () => null, configurable: true }}); }} catch (_) {{}}
  }}
  const plugins = createMagicArray(
    [pdfPluginData, pdfViewerData], PluginArray.prototype, Plugin.prototype, 'name'
  );
  defineNav('plugins', plugins);
  defineNav('mimeTypes', mimeTypes);

  // --- WebRTC: в прямом запуске нативный Chromium; через proxy — relay-only. ---
  if (cfg.webrtcRelayOnly) {{
  const hostIps = new Set((cfg.hostPublicIps || []).filter(Boolean));
  const isPrivateIp = (m) => /^(127\\.|10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|0\\.0\\.0\\.0|169\\.254\\.|100\\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\\.)/.test(m);
  const isHostLeak = (m) => hostIps.has(String(m || ''));
  const isLocalIce = (cand) => {{
    const c = String(cand || '');
    if (!c || c.trim() === '') return true;
    if (/\\.local/i.test(c)) return true;
    if (/ typ host /i.test(c)) return true;
    if (/ (192\\.168\\.|10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|127\\.)/.test(c)) return true;
    for (const hip of hostIps) {{
      if (hip && c.includes(hip)) return true;
    }}
    return false;
  }};
  const spoofIp = (m) => {{
    if (isHostLeak(m) || isPrivateIp(m)) return cfg.webrtcPublicIp || '0.0.0.0';
    return m;
  }};
  const scrubSdp = (sdp) => String(sdp || '')
    .replace(/(?:[0-9]{{1,3}}\\.){{3}}[0-9]{{1,3}}/g, spoofIp)
    .replace(/[a-f0-9-]+\\.local/gi, 'hidden.local');
  const scrubCandidateStr = (cand) => scrubSdp(cand).replace(/ typ host /gi, ' typ srflx ');
  const wrapIceCandidate = (candidate) => {{
    if (!candidate) return null;
    const raw = typeof candidate === 'string' ? candidate : candidate.candidate;
    if (isLocalIce(raw)) return null;
    const fixed = scrubCandidateStr(raw);
    if (typeof candidate === 'string') return fixed;
    try {{
      return new RTCIceCandidate({{ ...candidate, candidate: fixed }});
    }} catch (_) {{
      return {{ ...candidate, candidate: fixed }};
    }}
  }};
  const patchPeerConnection = (Base) => {{
    if (!Base) return;
    const Orig = Base;
    const Patched = function(...args) {{
      if (cfg.webrtcRelayOnly) {{
        const cfg0 = args[0] && typeof args[0] === 'object' ? {{ ...args[0] }} : {{}};
        cfg0.iceTransportPolicy = 'relay';
        args[0] = cfg0;
      }}
      if (args[0]?.iceServers) {{
        args[0].iceServers = args[0].iceServers.filter(
          (s) => !String(s.urls || s.url || '').startsWith('stun:')
        );
      }}
      const pc = new Orig(...args);
      const wrapDesc = (desc) => desc?.sdp ? {{ ...desc, sdp: scrubSdp(desc.sdp) }} : desc;
      const co = Orig.prototype.createOffer.bind(pc);
      pc.createOffer = (...a) => co(...a).then(wrapDesc);
      const ca = Orig.prototype.createAnswer.bind(pc);
      pc.createAnswer = (...a) => ca(...a).then(wrapDesc);
      const sl = Orig.prototype.setLocalDescription.bind(pc);
      pc.setLocalDescription = (d) => sl(wrapDesc(d));
      const ai = Orig.prototype.addIceCandidate?.bind(pc);
      if (ai) {{
        pc.addIceCandidate = (c) => {{
          const sanitized = wrapIceCandidate(c);
          if (!sanitized) return Promise.resolve();
          return ai(sanitized);
        }};
      }}
      pc.addEventListener('icecandidate', (ev) => {{
        const raw = ev.candidate?.candidate || '';
        if (isLocalIce(raw)) {{
          ev.stopImmediatePropagation();
          try {{ Object.defineProperty(ev, 'candidate', {{ value: null }}); }} catch (_) {{}}
          return;
        }}
        const fixed = wrapIceCandidate(ev.candidate);
        if (fixed && fixed !== ev.candidate) {{
          try {{ Object.defineProperty(ev, 'candidate', {{ value: fixed }}); }} catch (_) {{}}
        }}
      }}, true);
      if (Orig.prototype.getStats) {{
        const gs = Orig.prototype.getStats.bind(pc);
        const scrubReport = (report) => {{
          try {{
            if (report?.forEach) {{
              report.forEach((stat) => {{
                if (stat.ip && (isPrivateIp(stat.ip) || isHostLeak(stat.ip))) stat.ip = cfg.webrtcPublicIp || '0.0.0.0';
                if (stat.address && (isPrivateIp(stat.address) || isHostLeak(stat.address))) stat.address = cfg.webrtcPublicIp || '0.0.0.0';
                if (stat.ipAddress && (isPrivateIp(stat.ipAddress) || isHostLeak(stat.ipAddress))) stat.ipAddress = cfg.webrtcPublicIp || '0.0.0.0';
                if (stat.candidateType === 'host') {{
                  try {{ stat.candidateType = 'srflx'; }} catch (_) {{}}
                }}
              }});
            }}
          }} catch (_) {{}}
          return report;
        }};
        pc.getStats = nativeFn(function getStats(...a) {{
          const result = gs(...a);
          if (result && typeof result.then === 'function') return result.then(scrubReport);
          return scrubReport(result);
        }}, 'getStats');
      }}
      return pc;
    }};
    Patched.prototype = Orig.prototype;
    window[Base.name] = Patched;
  }};
  patchPeerConnection(window.RTCPeerConnection);
  patchPeerConnection(window.webkitRTCPeerConnection);
  }}

  // --- focus / visibility (headless markers) ---
  if (document.hasFocus) {{
    document.hasFocus = nativeFn(() => true, 'hasFocus');
  }}
  try {{
    Object.defineProperty(document, 'visibilityState', {{ get: () => 'visible', configurable: true }});
    Object.defineProperty(document, 'hidden', {{ get: () => false, configurable: true }});
  }} catch (_) {{}}

  // --- Worker / SharedWorker: WebGL patch (CreepJS ServiceWorker GPU leak) ---
  const __workerPre = {json.dumps(worker_bootstrap)};
  const workerUrlStr = (u) => {{
    if (typeof u === 'string') return u;
    try {{ if (u instanceof URL) return u.href; }} catch (_) {{}}
    try {{ if (u && typeof u.href === 'string') return u.href; }} catch (_) {{}}
    return '';
  }};
  const resolveWorkerUrl = (u) => {{
    const s = workerUrlStr(u);
    if (!s || s.startsWith('blob:') || s.startsWith('data:')) return s;
    try {{
      return new URL(s, document.baseURI).href;
    }} catch (_) {{
      return s;
    }}
  }};
  const skipWorkerPatch = (u) => {{
    const s = workerUrlStr(u);
    if (!s || s.startsWith('blob:') || s.startsWith('data:')) return true;
    return /youtube\\.com|youtubei\\/|\\/s\\/desktop\\/|googlesyndication|gstatic\\.com\\/youtube/i.test(s);
  }};
  const hookWorker = (Ctor, name) => {{
    if (!Ctor) return;
    const Orig = Ctor;
    window[name] = nativeFn(function(...args) {{
      const opts = args[1];
      if (opts && opts.type === 'module') {{
        return new Orig(...args);
      }}
      if (skipWorkerPatch(args[0])) {{
        return new Orig(...args);
      }}
      const u = resolveWorkerUrl(args[0]);
      if (u && !u.startsWith('blob:') && !u.startsWith('data:')) {{
        const code = __workerPre + ';importScripts(' + JSON.stringify(u) + ');';
        args[0] = URL.createObjectURL(new Blob([code], {{ type: 'application/javascript' }}));
      }}
      return new Orig(...args);
    }}, name);
  }};
  hookWorker(window.Worker, 'Worker');
  hookWorker(window.SharedWorker, 'SharedWorker');

  if (navigator.serviceWorker?.register) {{
    const origSwReg = navigator.serviceWorker.register.bind(navigator.serviceWorker);
    navigator.serviceWorker.register = nativeFn(function register(scriptURL, options) {{
      if (options && options.type === 'module') {{
        return origSwReg(scriptURL, options);
      }}
      if (skipWorkerPatch(scriptURL)) {{
        return origSwReg(scriptURL, options);
      }}
      let url = resolveWorkerUrl(scriptURL) || workerUrlStr(scriptURL) || scriptURL;
      if (typeof url === 'string' && !url.startsWith('blob:') && !url.startsWith('data:')) {{
        const code = __workerPre + ';importScripts(' + JSON.stringify(url) + ');';
        url = URL.createObjectURL(new Blob([code], {{ type: 'application/javascript' }}));
      }}
      return origSwReg(url, options);
    }}, 'register');
  }}

  // --- iframe / about:blank: Playwright init покрывает frames; дублируем ключевые nav props ---
  const patchFrameWindow = (win) => {{
    if (!win || win === window) return;
    try {{
      if (win.__ytCookiesFp) return;
      const wp = Object.getPrototypeOf(win.navigator);
      if (wp && 'webdriver' in wp) delete wp.webdriver;
      if ('webdriver' in win.navigator) {{
        try {{ delete win.navigator.webdriver; }} catch (_) {{ Reflect.deleteProperty(win.navigator, 'webdriver'); }}
      }}
      const d = (prop, value) => {{
        try {{ Object.defineProperty(win.navigator, prop, {{ get: () => value, configurable: true }}); }} catch (_) {{}}
      }};
      d('hardwareConcurrency', cfg.hardwareConcurrency);
      d('deviceMemory', cfg.deviceMemory);
      d('platform', cfg.platform);
      d('languages', cfg.languages);
      d('language', cfg.language);
      d('maxTouchPoints', cfg.maxTouchPoints);
      if (win.navigator.userAgentData) {{
        const brands = [
          {{ brand: 'Google Chrome', version: cfg.chromeMajor }},
          {{ brand: 'Chromium', version: cfg.chromeMajor }},
          {{ brand: 'Not_A Brand', version: cfg.notABrandVersion }},
        ];
        try {{
          Object.defineProperty(win.navigator.userAgentData, 'brands', {{ get: () => brands, configurable: true }});
          Object.defineProperty(win.navigator.userAgentData, 'platform', {{ get: () => 'Windows', configurable: true }});
          Object.defineProperty(win.navigator.userAgentData, 'mobile', {{ get: () => false, configurable: true }});
        }} catch (_) {{}}
      }}
      if (win.screen) {{
        try {{
          Object.defineProperty(win.screen, 'width', {{ get: () => cfg.screenWidth, configurable: true }});
          Object.defineProperty(win.screen, 'height', {{ get: () => cfg.screenHeight, configurable: true }});
        }} catch (_) {{}}
      }}
    }} catch (_) {{}}
  }};
  const watchIframes = () => {{
    try {{
      document.querySelectorAll('iframe').forEach((el) => {{
        try {{
          const src = String(el.src || el.getAttribute('src') || '');
          if (!src || src === 'about:blank' || src.startsWith('about:') || src.startsWith('chrome')) return;
          patchFrameWindow(el.contentWindow);
        }} catch (_) {{}}
      }});
    }} catch (_) {{}}
  }};
  if (typeof MutationObserver !== 'undefined') {{
    try {{
      new MutationObserver(watchIframes).observe(document.documentElement || document, {{
        childList: true, subtree: true,
      }});
    }} catch (_) {{}}
  }}
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watchIframes);
  else watchIframes();
}})();
"""


def build_fingerprint_script(
    profile: PCProfile,
    *,
    instance_id: str = "",
    account_key: str = "",
    proxied: bool = False,
    host_public_ip: str = "",
) -> str:
    """Собрать согласованный init-script по PCProfile.

    Нативными остаются сеть, TLS и HTTP Client Hints: их создаёт фактически
    запущенный CFT-бинарник. Скрипт меняет лишь JS-поверхности, которые должны
    отражать удалённый ПК, а не GPU/CPU хоста.
    """
    return _build_legacy_fingerprint_script(
        profile,
        instance_id=instance_id,
        account_key=account_key,
        proxied=proxied,
        host_public_ip=host_public_ip,
    )


def apply_cdp_profile(
    context: Any,
    profile: PCProfile,
    *,
    fingerprint_js: str = "",
    inject_on_new_document: bool = True,
) -> None:
    """
    Fingerprint без per-page CDP Emulation.*.

    Accept-Language задаётся на уровне context для всех запросов/iframe.
    Client Hints не подменяются: их формирует запущенный Chromium.
    JS init-script на новый документ — только если явно разрешено.
    Через HTTP-прокси add_init_script (Fetch intercept) зависает на HTML YouTube/Google.
    """
    try:
        context.set_extra_http_headers(profile.extra_http_headers)
    except Exception:
        pass
    if not fingerprint_js or not inject_on_new_document:
        return
    context.add_init_script(fingerprint_js)


def _privileged_page_url(url: str) -> bool:
    href = str(url or "").strip().lower()
    return (
        (not href)
        or href == "about:blank"
        or href.startswith("about:")
        or href.startswith("chrome")
        or href.startswith("devtools:")
        or href.startswith("data:")
    )


def _extension_inject_source(fingerprint_js: str) -> str:
    """Не исполнять fingerprint в about:blank — sandboxed blank роняет вкладку Chrome."""
    return (
        "(() => {\n"
        "  try {\n"
        "    const href = String((typeof location !== 'undefined' && location && location.href) || '');\n"
        "    if (!href || href === 'about:blank' || href.startsWith('about:') ||\n"
        "        href.startsWith('chrome') || href.startsWith('devtools:') ||\n"
        "        href.startsWith('chrome-error:') || href.startsWith('data:')) {\n"
        "      return;\n"
        "    }\n"
        "  } catch (e) { return; }\n"
        "  try {\n"
        f"{fingerprint_js}\n"
        "  } catch (e) {}\n"
        "})();\n"
    )


def inject_fingerprint_into_page(page: Any, fingerprint_js: str) -> bool:
    """Патч MAIN world уже открытой страницы. Patchright по умолчанию пишет в isolated world."""
    if not fingerprint_js or page is None:
        return False
    try:
        if page.is_closed():
            return False
        try:
            if _privileged_page_url(str(page.url or "")):
                return False
        except Exception:
            return False
        try:
            page.evaluate(fingerprint_js, isolated_context=False)
        except TypeError:
            page.evaluate(fingerprint_js)
        return True
    except Exception:
        return False


def write_fingerprint_extension(profile_dir: Any, fingerprint_js: str) -> Any:
    """Распакованное MV3-расширение: inject в MAIN world на document_start, до скриптов Google."""
    from pathlib import Path

    if not fingerprint_js:
        return None
    # Chrome 121 падает на --load-extension с кириллицей в пути.
    digest = hashlib.sha256(fingerprint_js.encode("utf-8")).hexdigest()[:16]
    ascii_root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "yt-fp-ext"
    try:
        ascii_root.mkdir(parents=True, exist_ok=True)
        ext_dir = ascii_root / digest
        ext_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        ext_dir = Path(profile_dir).resolve().parent / ".yt_fp_ext"
        ext_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": "yt-fp",
        "version": "1.0.1",
        "content_scripts": [
            {
                "matches": ["http://*/*", "https://*/*"],
                "js": ["inject.js"],
                "run_at": "document_start",
                "all_frames": True,
                "world": "MAIN",
            }
        ],
    }
    (ext_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    (ext_dir / "inject.js").write_text(
        _extension_inject_source(fingerprint_js),
        encoding="utf-8",
    )
    return ext_dir


def fingerprint_extension_args(ext_dir: Any) -> list[str]:
    if not ext_dir:
        return []
    path = str(ext_dir)
    return [
        f"--load-extension={path}",
        "--disable-features=DisableLoadExtensionCommandLineSwitch",
    ]


def build_launch_args(profile: PCProfile, *, proxied: bool = False) -> list[str]:
    lang = profile.locale or "en-US"
    accept = profile.accept_language_header
    # Минимум флагов: меньше automation-smell, больше native CFT
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--exclude-switches=enable-automation",
        f"--window-size={profile.viewport['width']},{profile.viewport['height']}",
        f"--lang={lang}",
        f"--accept-lang={accept}",
    ]
    if proxied:
        # QUIC/IPv6 мимо HTTP-прокси; DoH и WebRTC ограничены только с proxy.
        args.extend([
            "--webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--enforce-webrtc-ip-permission-check",
            "--disable-quic",
            "--disable-ipv6",
            "--disable-sync",
            "--disable-features=DnsOverHttps,QuicTransport,UseDnsHttpsSvcb,AsyncDns,PostQuantumKyber,UseMLKEM,EncryptedClientHello,TLSTrustAnchorIDs,MediaRouter,OptimizationHints",
        ])
    return args
