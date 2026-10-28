"""Транскрибация рилса + ключевые фразы для title/description.

Аудио: ffmpeg → wav 16kHz mono → numpy (без PyAV).
Модель по умолчанию: small (намного точнее tiny), с fallback base→tiny.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "transcripts"
MODELS_DIR = ROOT / "cache" / "whisper_models"

# Качество: small ≈ хороший баланс скорость/смысл на CPU.
# Можно переопределить: REELS_WHISPER_MODEL=base|small|medium
# Устройство: REELS_WHISPER_DEVICE=cpu|cuda (пусто = авто-проверка)
DEFAULT_MODEL = os.environ.get("REELS_WHISPER_MODEL", "small").strip() or "small"
MODEL_FALLBACKS = ("small", "base", "tiny")

# None = ещё не проверяли; True/False = результат probe
_CUDA_OK: bool | None = None

# меньше шума от HF на Windows без symlink
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

RU_INITIAL_PROMPT = (
    "Русская разговорная речь. Короткое видео, рилс. "
    "Тема: обзор, лайфхак, разбор, советы, новости."
)

HALLUCINATION_RE = re.compile(
    r"(субтитры\s+создал|редактор\s+субтитров|продолжение\s+следует|"
    r"подписывайтесь\s+на\s+канал|ставьте\s+лайк|thanks\s+for\s+watching|"
    r"♪+|\[\s*музыка\s*\]|\(\s*музыка\s*\))",
    re.IGNORECASE,
)

RU_STOP = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все",
    "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по",
    "только", "ее", "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из",
    "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли", "если", "уже", "или",
    "ни", "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж", "вам",
    "ведь", "там", "потом", "себя", "ничего", "ей", "может", "они", "тут", "где",
    "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам",
    "чтоб", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет",
    "ж", "тогда", "кто", "этот", "того", "потому", "этого", "какой", "совсем",
    "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее",
    "сейчас", "были", "куда", "почему", "сказать", "это", "просто",
    "очень", "можно", "нужно", "сегодня", "завтра", "привет", "всем",
    "которые", "который", "которая", "после", "перед", "через", "между",
    "также", "более", "этот", "эта", "эти", "была", "были", "будет",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **flags
    )


def extract_audio_wav(video: Path, out_wav: Path, *, max_seconds: float = 120.0) -> Path:
    """Вытаскивает речь: mono 16kHz + лёгкая нормализация громкости."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    # dynaudnorm помогает тихим рилсам; при ошибке — без фильтра
    af = "dynaudnorm=f=75:g=15,highpass=f=80,lowpass=f=8000"
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-t", str(max_seconds),
        "-vn", "-ac", "1", "-ar", "16000",
        "-af", af,
        str(out_wav),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not out_wav.exists():
        cmd_plain = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video),
            "-t", str(max_seconds),
            "-vn", "-ac", "1", "-ar", "16000",
            str(out_wav),
        ]
        proc = _run(cmd_plain)
    if proc.returncode != 0 or not out_wav.exists():
        raise RuntimeError(f"Не удалось извлечь аудио:\n{(proc.stderr or '')[-500:]}")
    return out_wav


def load_wav_f32(wav: Path) -> np.ndarray:
    with wave.open(str(wav), "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise RuntimeError(f"Неподдерживаемый sample width: {sw}")
    if nch > 1:
        data = data.reshape(-1, nch).mean(axis=1)
    # лёгкий peak-norm, если слишком тихо
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if 1e-4 < peak < 0.08:
        data = np.clip(data * (0.25 / peak), -1.0, 1.0)
    return np.ascontiguousarray(data, dtype=np.float32)


def _is_cuda_runtime_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    keys = (
        "cublas",
        "cudnn",
        "cuda",
        "nvrtc",
        "cublas64",
        "cudnn64",
        "cannot be loaded",
        "no kernel image",
        "out of memory",
    )
    return any(k in msg for k in keys)


def _probe_cuda(on_log=None) -> bool:
    """Реальная проверка: device count != рабочий cublas. Кешируем результат."""
    global _CUDA_OK
    if _CUDA_OK is not None:
        return _CUDA_OK
    forced = (os.environ.get("REELS_WHISPER_DEVICE") or "").strip().lower()
    if forced == "cpu":
        _CUDA_OK = False
        return False
    if forced == "cuda":
        _CUDA_OK = True
        return True
    try:
        import ctranslate2

        if int(ctranslate2.get_cuda_device_count() or 0) <= 0:
            _CUDA_OK = False
            return False
    except Exception:
        _CUDA_OK = False
        return False

    _log(on_log, "Проверяю GPU (cublas)…")
    try:
        from faster_whisper import WhisperModel

        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        # 2 сек тона — VAD не выбросит, encode точно вызовется
        t = np.arange(16000 * 2, dtype=np.float32) / 16000.0
        audio = (0.05 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        model = WhisperModel(
            "tiny",
            device="cuda",
            compute_type="float16",
            download_root=str(MODELS_DIR),
        )
        segments, _info = model.transcribe(
            audio,
            language="ru",
            beam_size=1,
            best_of=1,
            vad_filter=False,
            temperature=0.0,
            without_timestamps=True,
        )
        # ошибка cublas часто только при итерации
        for _ in segments:
            break
        _CUDA_OK = True
        _log(on_log, "GPU OK (cuda/float16)")
    except Exception as exc:  # noqa: BLE001
        _CUDA_OK = False
        _log(on_log, f"GPU недоступен → CPU: {exc}")
    return bool(_CUDA_OK)


def _pick_device(*, on_log=None) -> tuple[str, str]:
    """(device, compute_type). Без рабочего cublas всегда CPU/int8."""
    if _probe_cuda(on_log):
        return "cuda", "float16"
    return "cpu", "int8"


def _force_cpu(reason: str = "", on_log=None) -> None:
    global _CUDA_OK
    _CUDA_OK = False
    if reason:
        _log(on_log, f"Переключаюсь на CPU: {reason}")


def _model_candidates(preferred: str | None = None) -> list[str]:
    pref = (preferred or DEFAULT_MODEL).strip().lower()
    order = [pref] + [m for m in MODEL_FALLBACKS if m != pref]
    # medium только если явно попросили — тяжелее
    if pref == "medium":
        order = ["medium", "small", "base", "tiny"]
    return order


def _clean_transcript(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    # убрать типичные галлюцинации whisper
    parts = re.split(r"(?<=[.!?…])\s+", text)
    kept = []
    for p in parts:
        if HALLUCINATION_RE.search(p):
            continue
        kept.append(p)
    text = " ".join(kept) if kept else text
    text = HALLUCINATION_RE.sub(" ", text)
    return " ".join(text.split()).strip()


def _fmt_time(seconds: float | int) -> str:
    """1205 → '20 мин 5 сек'."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s} сек"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m} мин {sec} сек"
    h, m = divmod(m, 60)
    return f"{h} ч {m} мин"


def _log(on_log, msg: str) -> None:
    if not on_log:
        return
    try:
        on_log(str(msg))
    except Exception:
        pass


class _Heartbeat:
    """Пишет в лог понятное время ожидания."""

    def __init__(self, on_log, label: str, *, interval: float = 10.0):
        self.on_log = on_log
        self.label = label
        self.interval = interval
        self._stop = threading.Event()
        self._t0 = time.monotonic()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if not self.on_log:
            return self

        def _loop() -> None:
            while not self._stop.wait(self.interval):
                elapsed = time.monotonic() - self._t0
                _log(
                    self.on_log,
                    f"⏳ Ещё идёт: {self.label} — прошло {_fmt_time(elapsed)}",
                )

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


def _load_whisper_model(model_size: str, device: str, compute: str, *, on_log=None):
    from faster_whisper import WhisperModel

    cpu_threads = max(4, min(8, (os.cpu_count() or 4))) if device == "cpu" else 0
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    _log(on_log, f"[3/4] Загрузка весов {model_size} ({device}/{compute})…")
    with _Heartbeat(on_log, f"загрузка {model_size}", interval=7.0):
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute,
            download_root=str(MODELS_DIR),
            cpu_threads=cpu_threads,
        )
    _log(on_log, f"[3/4] Веса {model_size} в памяти ✓")
    return model


def _run_whisper_segments(
    model,
    audio: np.ndarray,
    *,
    model_size: str,
    sec: float,
    on_log=None,
) -> tuple[str, int, object]:
    # temperature=0 — без ретраев; иначе на битом CUDA/медленном CPU может висеть
    beam = 3 if model_size in ("tiny", "base", "small") else 5
    if model_size == "medium":
        beam = 3
    _log(
        on_log,
        f"[4/4] Распознаю речь (~{_fmt_time(sec)} аудио, beam={beam})…",
    )
    with _Heartbeat(on_log, "распознавание сегментов", interval=8.0):
        segments, info = model.transcribe(
            audio,
            language="ru",
            task="transcribe",
            beam_size=beam,
            best_of=beam,
            patience=1.0,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 350,
                "speech_pad_ms": 200,
            },
            condition_on_previous_text=False,
            initial_prompt=RU_INITIAL_PROMPT,
            without_timestamps=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )
        parts: list[str] = []
        n_seg = 0
        t0 = time.monotonic()
        last_audio_end = 0.0
        for seg in segments:
            n_seg += 1
            try:
                last_audio_end = float(getattr(seg, "end", 0) or 0)
            except Exception:
                pass
            t = (seg.text or "").strip()
            if not t:
                continue
            if seg.no_speech_prob is not None and seg.no_speech_prob > 0.85:
                continue
            if seg.avg_logprob is not None and seg.avg_logprob < -1.2:
                continue
            if HALLUCINATION_RE.search(t):
                continue
            parts.append(t)
            if n_seg == 1 or n_seg % 2 == 0:
                wall = _fmt_time(time.monotonic() - t0)
                audio_pos = _fmt_time(last_audio_end)
                audio_total = _fmt_time(sec)
                pct = min(100, int(100 * last_audio_end / sec)) if sec > 0 else 0
                snippet = t[:50] + ("…" if len(t) > 50 else "")
                _log(
                    on_log,
                    f"  речь {audio_pos} из {audio_total} (~{pct}%) · "
                    f"жду уже {wall} · «{snippet}»",
                )

    text = _clean_transcript(" ".join(parts))
    elapsed = time.monotonic() - t0
    _log(
        on_log,
        f"[4/4] Готово за {_fmt_time(elapsed)} · сегментов={n_seg} · символов={len(text)}",
    )
    if on_log and info is not None:
        try:
            _log(
                on_log,
                f"  язык={getattr(info, 'language', '?')} "
                f"p={getattr(info, 'language_probability', 0):.2f} "
                f"длит={getattr(info, 'duration', 0):.1f}с",
            )
        except Exception:
            pass
    return text, n_seg, info


def _transcribe_faster_whisper(wav: Path, *, model_size: str, on_log=None) -> str:
    _log(on_log, "[1/4] Читаю wav…")
    audio = load_wav_f32(wav)
    if audio.size < 1600:
        return ""

    device, compute = _pick_device(on_log=on_log)
    sec = audio.size / 16000.0
    _log(
        on_log,
        f"[2/4] Модель={model_size} · {device}/{compute} · речь ~{sec:.0f} с",
    )

    try:
        model = _load_whisper_model(model_size, device, compute, on_log=on_log)
        text, _n, _info = _run_whisper_segments(
            model, audio, model_size=model_size, sec=sec, on_log=on_log
        )
        return text
    except Exception as exc:  # noqa: BLE001
        if device == "cuda" and _is_cuda_runtime_error(exc):
            _force_cpu(str(exc), on_log=on_log)
            model = _load_whisper_model(model_size, "cpu", "int8", on_log=on_log)
            text, _n, _info = _run_whisper_segments(
                model, audio, model_size=model_size, sec=sec, on_log=on_log
            )
            return text
        raise


def _transcribe_openai_whisper(wav: Path, *, model_size: str = "small", on_log=None) -> str:
    import whisper

    if on_log:
        on_log(f"openai-whisper · {model_size}…")
    model = whisper.load_model(model_size)
    result = model.transcribe(
        str(wav),
        language="ru",
        fp16=False,
        beam_size=5,
        best_of=5,
        temperature=0.0,
        condition_on_previous_text=True,
        initial_prompt=RU_INITIAL_PROMPT,
    )
    return _clean_transcript(str(result.get("text") or ""))


def _cache_path(video: Path, model_size: str) -> Path:
    dig = hashlib.md5(f"{video.resolve()}|{model_size}|v2".encode()).hexdigest()[:10]
    return CACHE / f"{video.stem}_{model_size}_{dig}.txt"


def transcribe_video(
    video: Path,
    *,
    on_log=None,
    model: str | None = None,
    force: bool = False,
) -> str:
    """Распознаёт речь. По умолчанию модель small (+ fallback)."""
    video = Path(video)
    if not video.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video}")

    CACHE.mkdir(parents=True, exist_ok=True)
    preferred = (model or DEFAULT_MODEL).strip().lower()
    candidates = _model_candidates(preferred)

    if not force:
        for m in candidates:
            cache_txt = _cache_path(video, m)
            try:
                if cache_txt.exists() and cache_txt.stat().st_mtime >= video.stat().st_mtime:
                    text = cache_txt.read_text(encoding="utf-8").strip()
                    if text:
                        if on_log:
                            on_log(f"Транскрипт из кеша ({m})")
                        return text
            except OSError:
                pass

    with tempfile.TemporaryDirectory(prefix="reel_asr_") as tmp:
        wav = Path(tmp) / "audio.wav"
        _log(on_log, "Этап: извлечение и нормализация аудио (ffmpeg)…")
        extract_audio_wav(video, wav)
        try:
            sz = wav.stat().st_size
            _log(on_log, f"Аудио готово ({sz // 1024} КБ)")
        except OSError:
            pass

        text = ""
        errors: list[str] = []
        used_model = preferred

        for m in candidates:
            used_model = m
            _log(on_log, f"Этап: faster-whisper / {m}")
            try:
                text = _transcribe_faster_whisper(wav, model_size=m, on_log=on_log)
                if text:
                    break
                errors.append(f"faster-whisper/{m}: пустой результат")
                _log(on_log, f"Пустой результат на {m}, пробую следующую…")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"faster-whisper/{m}: {exc}")
                _log(on_log, f"Модель {m} не вышла: {exc}")

        if not text:
            # последний шанс — openai-whisper small/base
            for m in (preferred if preferred in ("tiny", "base", "small") else "small", "base"):
                try:
                    text = _transcribe_openai_whisper(wav, model_size=m, on_log=on_log)
                    used_model = f"openai-{m}"
                    if text:
                        break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"openai-whisper/{m}: {exc}")

        if not text:
            hint = (
                "Не удалось распознать речь.\n"
                "Нужен: pip install faster-whisper\n"
                + ("\n".join(errors[-4:]) if errors else "Пустой результат (нет речи?)")
            )
            raise RuntimeError(hint)

    cache_txt = _cache_path(video, used_model.replace("openai-", ""))
    try:
        cache_txt.write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass
    return text


def split_sentences(text: str) -> list[str]:
    raw = re.split(r"[.!?…\n]+", text or "")
    out = []
    for part in raw:
        s = " ".join(part.split()).strip(" -,;:")
        if len(s) >= 8:
            out.append(s)
    return out


def _content_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", (text or "").lower())
    return [t for t in tokens if t not in RU_STOP and len(t) > 3]


def _score_phrase(phrase: str) -> float:
    """Выше = полезнее для title: хуки в начале + конкретика, без обрывков."""
    words = phrase.split()
    n = len(words)
    if n < 4:
        return 0.1
    content = _content_tokens(phrase)
    # живые заголовки Shorts обычно 5–14 слов
    if 5 <= n <= 14:
        length_score = 1.25
    elif 4 <= n <= 18:
        length_score = 0.95
    else:
        length_score = 0.45
    density = len(content) / max(n, 1)
    if density < 0.22:
        return 0.15
    bonus = 0.4 if re.search(r"\d", phrase) else 0.0
    bonus += 0.25 if any(len(w) >= 6 for w in content) else 0.0
    # имена/заглавные внутри (кроме первого слова)
    if any(w[:1].isupper() and i > 0 for i, w in enumerate(words)):
        bonus += 0.2
    return length_score * 2.4 + density * 3.0 + bonus + min(len(content), 8) * 0.12


def _phrase_looks_garbage(text: str) -> bool:
    """Эвристики без ИИ: обрывки ASR, вода, хвосты союзов."""
    clean = " ".join((text or "").split()).strip(" -,;:«»\"'")
    words = clean.split()
    if len(words) < 4 or len(clean) < 18:
        return True
    first = words[0].casefold()
    last = re.sub(r"[^\wа-яё]", "", words[-1].casefold(), flags=re.I)
    bad_start = {"и", "а", "но", "что", "как", "это", "ну", "вот", "да", "типа", "короче"}
    bad_end = {
        "и", "а", "но", "что", "как", "на", "в", "с", "по", "к", "у", "из", "за",
        "от", "для", "чтобы", "если", "когда", "это",
    }
    if first in bad_start or last in bad_end:
        return True
    tiny = sum(1 for w in words if len(re.sub(r"[^\wа-яё]", "", w, flags=re.I)) <= 2)
    if tiny / len(words) > 0.4:
        return True
    # явные ASR-глюки / вода
    low = clean.casefold()
    junk_bits = ("продолжение следует", "субтитры", "редактор субтитров", "неразборчиво")
    if any(j in low for j in junk_bits):
        return True
    return False


def extract_key_phrases(transcript: str, *, limit: int = 10) -> list[str]:
    """
    Ключевые фразы = целые предложения-хуки.
    Без ИИ: сильнее весим первые фразы ролика, режем ASR-мусор.
    """
    text = _clean_transcript(transcript)
    if not text:
        return []

    scored: list[tuple[float, str, int]] = []
    seen: set[str] = set()

    def consider(p: str, mult: float, order: int) -> None:
        clean = " ".join(p.split()).strip(" -,;:«»\"'")
        if _phrase_looks_garbage(clean):
            return
        if len(clean) > 140:
            clean = clean[:137].rsplit(" ", 1)[0].rstrip("-,;:")
            if _phrase_looks_garbage(clean):
                return
        if HALLUCINATION_RE.search(clean):
            return
        key = clean.casefold()
        if key in seen:
            return
        sc = _score_phrase(clean) * mult
        if sc < 0.85:
            return
        seen.add(key)
        # первая буква как в заголовке
        clean = clean[0].upper() + clean[1:] if clean else clean
        scored.append((sc, clean, order))

    sents = split_sentences(text)
    for i, sent in enumerate(sents):
        # хук почти всегда в первых предложениях
        if i == 0:
            boost = 1.85
        elif i == 1:
            boost = 1.55
        elif i == 2:
            boost = 1.25
        else:
            boost = 1.0
        consider(sent, boost, i)

    # мало точек — крупные куски по паузам, но не короткие обрывки
    if len([x for x in scored if x[2] < 100]) < 3:
        chunks = re.split(r"(?<=[,;])\s+", text)
        for j, ch in enumerate(chunks):
            piece = ch.strip(" -,;:")
            if len(piece.split()) >= 6:
                consider(piece, 0.95, 100 + j)

    if len(scored) < 2:
        words = text.split()
        # окна ближе к длине живого заголовка
        for i in range(0, max(1, len(words) - 7), 5):
            consider(" ".join(words[i : i + 11]), 0.7, 200 + i)

    scored.sort(key=lambda x: (-x[0], x[2], len(x[1])))
    return [p for _sc, p, _ord in scored[:limit]]


def build_title_from_phrases(phrases: list[str], *, uniq_tail: bool = False) -> str:
    core = " · ".join(phrases[:2]) if phrases else "Рилс"
    return core[:95].strip()


def build_description_from_transcript(
    transcript: str,
    phrases: list[str],
    *,
    tg_link: str | None = None,
) -> str:
    """Шаблон описания без хэштегов — теги собираются отдельно."""
    lines: list[str] = []
    if phrases:
        lines.append(phrases[0])
    snippet = " ".join((transcript or "").split())
    if len(snippet) > 220:
        snippet = snippet[:217] + "…"
    if snippet:
        lines.append(snippet)
    if tg_link:
        lines.append(tg_link.strip())
    return "\n\n".join(lines)


def _words_cache_path(video: Path, model_size: str) -> Path:
    dig = hashlib.md5(f"{video.resolve()}|{model_size}|words-v1".encode()).hexdigest()[:10]
    return CACHE / f"{video.stem}_{model_size}_{dig}.words.json"


def _words_faster_whisper(wav: Path, *, model_size: str, on_log=None) -> list[dict]:
    audio = load_wav_f32(wav)
    if audio.size < 1600:
        return []
    device, compute = _pick_device(on_log=on_log)
    sec = audio.size / 16000.0

    def _collect(dev: str, comp: str) -> list[dict]:
        model = _load_whisper_model(model_size, dev, comp, on_log=on_log)
        beam = 3 if model_size in ("tiny", "base", "small", "medium") else 5
        segments, _info = model.transcribe(
            audio,
            language="ru",
            task="transcribe",
            beam_size=beam,
            best_of=beam,
            patience=1.0,
            temperature=0.0,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
            initial_prompt=RU_INITIAL_PROMPT,
            without_timestamps=False,
        )
        found: list[dict] = []
        for seg in segments:
            if seg.no_speech_prob is not None and seg.no_speech_prob > 0.85:
                continue
            for word in getattr(seg, "words", None) or []:
                text = str(getattr(word, "word", "") or "").strip()
                if not text:
                    continue
                found.append(
                    {
                        "s": round(float(getattr(word, "start", 0) or 0), 3),
                        "e": round(float(getattr(word, "end", 0) or 0), 3),
                        "t": text,
                    }
                )
        return found

    try:
        return _collect(device, compute)
    except Exception as exc:  # noqa: BLE001
        if device == "cuda" and _is_cuda_runtime_error(exc):
            _force_cpu(str(exc), on_log=on_log)
            return _collect("cpu", "int8")
        raise


def transcribe_words(
    video: Path,
    *,
    on_log=None,
    model: str | None = None,
    force: bool = False,
) -> list[dict]:
    """Слова с таймкодами для субтитров по 1–2 слова."""
    video = Path(video)
    if not video.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video}")
    CACHE.mkdir(parents=True, exist_ok=True)
    preferred = (model or DEFAULT_MODEL).strip().lower()
    cache_path = _words_cache_path(video, preferred)
    if not force:
        try:
            if cache_path.exists() and cache_path.stat().st_mtime >= video.stat().st_mtime:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    if on_log:
                        on_log(f"Слова субтитров из кеша ({preferred})")
                    return cached
        except (OSError, json.JSONDecodeError):
            pass

    with tempfile.TemporaryDirectory(prefix="reel_words_") as tmp:
        wav = Path(tmp) / "audio.wav"
        _log(on_log, "Субтитры: достаю аудио…")
        extract_audio_wav(video, wav)
        words = _words_faster_whisper(wav, model_size=preferred, on_log=on_log)
    try:
        cache_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    _log(on_log, f"Субтитры: слов {len(words)}")
    return words


def transcribe_words_in_subprocess(
    video: Path,
    *,
    on_log=None,
    python_exe: str | None = None,
    model: str | None = None,
) -> list[dict]:
    video = Path(video)
    out_json = Path(tempfile.gettempdir()) / f"reel_words_{video.stem}_{os_getpid()}.json"
    py = python_exe or sys.executable
    cmd = [
        py,
        "-u",
        str(ROOT / "transcribe.py"),
        str(video),
        "--out",
        str(out_json),
        "--model",
        (model or DEFAULT_MODEL),
        "--words",
    ]

    def _safe_log(msg: str) -> None:
        if not on_log:
            return
        try:
            on_log(msg)
        except Exception:
            pass

    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        **flags,
    )
    err_tail: list[str] = []

    def _read_stream(stream, *, to_log: bool) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if to_log:
                    _safe_log(line)
                err_tail.append(line)
                if len(err_tail) > 80:
                    del err_tail[:20]
        except Exception:
            pass

    t_err = threading.Thread(target=_read_stream, args=(proc.stderr,), kwargs={"to_log": True}, daemon=True)
    t_out = threading.Thread(target=_read_stream, args=(proc.stdout,), kwargs={"to_log": False}, daemon=True)
    t_err.start()
    t_out.start()
    while proc.poll() is None:
        time.sleep(2.0)
    t_err.join(timeout=2.0)
    t_out.join(timeout=2.0)
    code = proc.returncode if proc.returncode is not None else -1
    if code != 0 or not out_json.is_file():
        err = "\n".join(err_tail[-8:]) or f"код {code}"
        raise RuntimeError(f"Субтитры не распознались:\n{err[-600:]}")
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        try:
            out_json.unlink(missing_ok=True)
        except OSError:
            pass
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    words = data.get("words") or []
    return words if isinstance(words, list) else []


def transcribe_in_subprocess(
    video: Path,
    *,
    on_log=None,
    python_exe: str | None = None,
    model: str | None = None,
    force: bool = False,
) -> tuple[str, list[str]]:
    """ASR в отдельном процессе — логи стримятся в GUI построчно."""
    video = Path(video)
    out_json = Path(tempfile.gettempdir()) / f"reel_asr_{video.stem}_{os_getpid()}.json"
    py = python_exe or sys.executable
    cmd = [
        py,
        "-u",  # без буфера stdout/stderr — логи сразу
        str(ROOT / "transcribe.py"),
        str(video),
        "--out",
        str(out_json),
        "--model",
        (model or DEFAULT_MODEL),
    ]
    if force:
        cmd.append("--force")

    def _safe_log(msg: str) -> None:
        if not on_log:
            return
        try:
            on_log(msg)
        except Exception:
            pass

    _safe_log(f"Запуск распознавания ({model or DEFAULT_MODEL})…")
    flags = {}
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.CREATE_NO_WINDOW

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    # если CUDA уже известна как битая — не трогаем; иначе probe сам уйдёт на CPU
    # Явный override: REELS_WHISPER_DEVICE=cpu|cuda

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        **flags,
    )

    err_tail: list[str] = []

    def _read_stream(stream, *, to_log: bool) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if to_log:
                    _safe_log(line)
                err_tail.append(line)
                if len(err_tail) > 80:
                    del err_tail[:20]
        except Exception:
            pass

    t_err = threading.Thread(target=_read_stream, args=(proc.stderr,), kwargs={"to_log": True}, daemon=True)
    t_out = threading.Thread(target=_read_stream, args=(proc.stdout,), kwargs={"to_log": False}, daemon=True)
    t_err.start()
    t_out.start()

    # родительский статус раз в 30 сек (без дубля «тиков»)
    t0 = time.monotonic()
    last_ping = 0
    while proc.poll() is None:
        time.sleep(5.0)
        elapsed = int(time.monotonic() - t0)
        if elapsed - last_ping >= 30:
            last_ping = elapsed
            _safe_log(f"⏳ Распознавание ещё идёт — прошло {_fmt_time(elapsed)}")

    t_err.join(timeout=2.0)
    t_out.join(timeout=2.0)
    code = proc.returncode if proc.returncode is not None else -1

    if code != 0:
        err = "\n".join(err_tail[-12:]) or f"код {code}"
        raise RuntimeError(f"Распознавание упало:\n{err[-800:]}")
    if not out_json.is_file():
        raise RuntimeError("Распознавание не вернуло результат")
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        try:
            out_json.unlink(missing_ok=True)
        except OSError:
            pass
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    text = str(data.get("text") or "").strip()
    phrases = list(data.get("phrases") or [])
    if not text:
        raise RuntimeError("Пустой транскрипт (в видео нет речи?)")
    return text, phrases


def os_getpid() -> int:
    return os.getpid()


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Транскрибация видео → JSON")
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="tiny|base|small|medium")
    parser.add_argument("--force", action="store_true", help="игнорировать кеш")
    parser.add_argument("--words", action="store_true", help="слова с таймкодами для субтитров")
    args = parser.parse_args()

    def on_log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        if args.words:
            _log(on_log, f"CLI words · model={args.model}")
            words = transcribe_words(args.video, on_log=on_log, model=args.model, force=args.force)
            payload = {"words": words, "text": " ".join(str(w.get("t") or "") for w in words), "model": args.model}
            args.out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return 0
        _log(on_log, f"CLI ASR start · model={args.model} · force={args.force}")
        text = transcribe_video(args.video, on_log=on_log, model=args.model, force=args.force)
        _log(on_log, "Этап: ключевые фразы…")
        phrases = extract_key_phrases(text)
        _log(on_log, f"Фраз: {len(phrases)}")
        payload = {"text": text, "phrases": phrases, "model": args.model}
    except Exception as exc:  # noqa: BLE001
        payload = {"error": str(exc), "text": "", "phrases": []}
        args.out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    args.out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
