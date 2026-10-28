# Инструкция для ИИ (и разработчика)

Этот файл — карта репозитория **reels-gen** («Рилс Загрузка»).  
Читай его **перед** правками, сборкой и советами «как запустить».

Репозиторий: https://github.com/fansmok/reels-gen  
Общайся с владельцем проекта **на русском**.

---

## Что это за продукт

Десктоп-приложение (Electron + React + Python), которое:

1. **Склеивает** вертикальный рилс (верх + низ, кружок, баннеры, CTA, субтитры).
2. **Пишет** названия/описания через Kie (если задан ключ).
3. **Заливает** на YouTube, Rutube, Pinterest, Дзен, TikTok, VK, Instagram.
4. Может принимать верхний ролик из **Telegram-бота** (ссылка или файл + описание).
5. Создаёт **Chrome-профили с отпечатком** для входа в аккаунты («Добавить аккаунт»).

Это софт про **рилсы и заливку**. Не тащи в репозиторий и не описывай посторонние боты закупки логов и т.п.

---

## Как устроены слои

```
┌─────────────────────────────────────────────────────────┐
│  Electron UI (src/renderer) + main (src/main)           │
│  очередь заливок, Telegram-бот, настройки, Playwright   │
└───────────────────────────┬─────────────────────────────┘
                            │ spawn Python
┌───────────────────────────▼─────────────────────────────┐
│  python/*.py  — мосты (JSON по строкам stdout)            │
│  reels_bridge.py  → генерация                             │
│  yt_bridge.py     → профили / Chrome / CDP                │
│  kie_bridge.py    → тексты площадок                       │
└───────────────────────────┬─────────────────────────────┘
                            │ REELS_TG_ROOT
┌───────────────────────────▼─────────────────────────────┐
│  reels-engine/  (встроенный движок)                       │
│  ├── reels_gen/     склейка ffmpeg, whisper, kie, CTA     │
│  ├── profiles/      папки Chrome user-data аккаунтов       │
│  ├── YT-COOKIES/    отпечаток, прокси профиля, запуск CFT │
│  ├── account_manager.py, plain_profiles.py, …             │
└─────────────────────────────────────────────────────────┘
```

В **установщике** `reels-engine` лежит в `resources/reels-engine`.  
В **dev** — папка `reels-engine/` в корне репозитория.

Путь по умолчанию задаётся в `src/main/store.ts` → `defaultEnginePaths()`:

| Поле | По умолчанию |
|------|----------------|
| `tgRoot` | `reels-engine` (встроенный движок) |
| `vkBot` | `reels-engine/profiles` |
| `ytCookies` | `reels-engine/YT-COOKIES` |
| `pythonExe` | пусто → ищем системный Python (`src/main/python.ts`) |

Переменные для Python (ставит Electron):

- `REELS_TG_ROOT` — корень движка (должен содержать `reels_gen/`)
- `REELS_VK_BOT` — папка профилей
- `REELS_YT_COOKIES` — модули отпечатка
- `REELS_YDA_ROOT` — опционально
- для субтитров Remotion: `REELS_CAPTION_SCRIPT`, `REELS_CAPTION_BUNDLE`, `REELS_ELECTRON_EXEC`, `REELS_NODE_MODULES`

Протокол моста (`python/bridge_common.py`): каждая строка stdout — JSON с `"type"`: `log` | `ready` | `result` | `error` | `progress`.

---

## Карта важных папок

| Путь | Роль |
|------|------|
| `src/main/` | Electron main: генератор, очередь, Telegram, Playwright-заливки |
| `src/main/uploaders/` | Адаптеры площадок |
| `src/main/telegram.ts` | Бот: ссылка/файл, описание к файлу, очередь |
| `src/main/yt-plain.ts` | Открытие профиля Chrome по CDP |
| `src/renderer/` | UI |
| `src/shared/` | Типы, настройки генератора, площадки |
| `python/` | Мосты к движку (попадают в `resources/python`) |
| `reels-engine/reels_gen/` | **Склейка** (`engine.py`, `transcribe.py`, `kie_titles.py`, …) |
| `reels-engine/YT-COOKIES/` | Отпечаток / запуск Chrome |
| `reels-engine/profiles/` | Созданные аккаунты (не коммитить живые профили) |
| `captions/` | Remotion-субтитры (`index.tsx`, `render.cjs`) |
| `electron-builder.yml` | Что класть в установщик |

Не коммитить: `node_modules/`, `dist/`, `out/`, `captions-bundle/`, `state.json`, cookies, живые `profiles_youtube_plain*`, секреты.

---

## Запуск с нуля (Windows)

### 1. Системные зависимости

- Node.js 20+
- Python 3.11+ в PATH (`python` / `py -3`)
- FFmpeg **и** ffprobe в PATH
- Google Chrome

### 2. Клон и npm

```bash
git clone https://github.com/fansmok/reels-gen.git
cd reels-gen
npm install
```

### 3. Python-зависимости движка

```bash
pip install -r reels-engine/reels_gen/requirements.txt
```

В `requirements.txt` уже есть whisper/numpy/Pillow/yt-dlp и др. При ошибках Whisper — отдельно `pip install openai-whisper`.

### 4. Dev-режим

```bash
npm run dev
```

Откроется Electron. В настройках движка пути обычно уже на `reels-engine`.  
«Проверить» — смотрит Python, `reels_gen`, ffmpeg.

### 5. Что вписать в UI после первого запуска

1. **Kie API** — ключ с kie.ai (иначе автозаголовки/паки текстов не будут).
2. **Telegram** — токен бота от BotFather; в «Источнике» включить загрузку через Telegram. Программа должна быть **открыта**.
3. **Аккаунты** — «Добавить аккаунт», при желании прокси `host:port:login:password`, войти в открывшемся Chrome.
4. Не клади чужие токены/cookies в git.

### 6. Сборка установщика Windows

```bash
npm run build:win
```

Артефакт: `dist/reels-uploader-{version}-setup.exe`  
Скрипт: `bundle:captions` → typecheck/vite → electron-builder.

На **Mac**: `npm run build:mac` → `.dmg`. Команду `build:win` с Mac не запускай.  
Поведение `win32` (python.exe, taskkill, WinAPI в `yt_bridge`) не ломай без нужды.

---

## Типовые сценарии работы программы

### Генерация рилса

1. UI сохраняет настройки генератора.
2. `generateToQueue` → `reels_bridge.py` с JSON opts.
3. `setup_engine_paths()` → импорт `engine`, `kie_titles`, …
4. `build_reel` / batch: ffmpeg, опционально Remotion WebM субтитров.
5. Готовые файлы → очередь заливки.

**Субтитры Remotion:** прозрачный VP8 WebM. При наложении в ffmpeg вход WebM открывать с **`-c:v libvpx`**, иначе альфа теряется и ролик становится чёрным (звук и текст остаются).

**Telegram файл (не ссылка):** нужно текстовое описание (подпись или отдельное сообщение). Уходит как `sourceNote` → Kie для названия. Ссылке описание не обязательно.

### Добавить аккаунт

1. UI → `yt_bridge.py create` → `account_manager.create_plain_profile` + отпечаток.
2. Папка в `reels-engine/profiles/profiles_youtube_plain[_N]`.
3. Chrome в режиме `login` (отпечаток) через `yt_plain_launch` + модули `YT-COOKIES`.
4. Заливка по умолчанию — обычный Chrome + прокси профиля; тумблер в настройках включает «особый» Chrome с отпечатком и для аплоада.

Прокси для нового аккаунта — **вручную**. Автоподбор из внешних кабинетов в этой сборке не используется.

---

## Правила правок (обязательно)

1. **Язык с пользователем — русский.**
2. После правок **кода программы** (не только `.md` / rules):
   - поднять версию в `package.json` и корневые поля `package-lock.json`;
   - Windows: `npm run build:win`, отдать `dist/reels-uploader-{version}-setup.exe`;
   - патч `1.0.x` — фиксы; минор `1.x.0` — новые возможности;
   - не спрашивать «собрать?»; не предлагать вместо установщика только `npm run dev`.
3. Только документация / `.cursor` rules — **версию не поднимать и установщик не собирать**.
4. Секреты в код **не вшивать** (токен бота, Kie, пароли). Дефолты пустые.
5. Не коммитить `dist/`, профили Chrome, cookies, `state.json`.
6. Движок править в `reels-engine/` этого репозитория. Посторонние папки с диска в git не тащить.
7. Commits — только если пользователь попросил (или явно идёт выкладка на GitHub по его задаче).

---

## Частые поломки

| Симптом | Куда смотреть |
|---------|----------------|
| «Не найден Python» | `pythonExe` в настройках / PATH / `resolvePythonExe` |
| «Нет reels_gen» | `tgRoot` должен указывать на папку с `reels_gen/` |
| Нет ffmpeg | PATH |
| Чёрный ролик, есть звук и субтитры | ffmpeg overlay captions без `libvpx` |
| Kie молчит / английский | ключ в настройках; `kie_titles.py` / `kie_bridge.py` |
| Бот не принимает файл | нет описания; или файл > 20 МБ |
| «Добавить аккаунт» падает | нет `account_manager` / `YT-COOKIES` в `tgRoot`; Python-пакеты |
| Remotion / Chrome Headless | кэш в `%LOCALAPPDATA%\reels-caption-browser`; путь без сюрпризов для распаковки |

---

## Полезные команды

```bash
npm run dev                 # разработка
npm run typecheck           # TS
npm run build:win           # установщик Windows
npm run build:mac           # dmg (только на Mac)
pip install -r reels-engine/reels_gen/requirements.txt
python -m py_compile python/reels_bridge.py python/yt_bridge.py
```

Проверка импорта движка профилей:

```bash
python -c "import sys; from pathlib import Path; r=Path('reels-engine').resolve(); sys.path[:0]=[str(r), str(r/'YT-COOKIES'), str(r/'reels_gen')]; import account_manager, plain_profiles; print(plain_profiles.read_vk_bot_dir(''))"
```

---

## Чего ИИ не должна делать

- Вшивать токены, ключи API, пароли прокси.
- Коммитить пользовательские профили и cookies.
- Переписывать win32-специфику «заодно» без задачи.
- Разворачивать посторонние проекты закупки аккаунтов в этот репозиторий.
- Утверждать, что движок «где-то снаружи» — он уже в `reels-engine/`.

---

## Краткий чеклист «поднял с гита»

1. `npm install`
2. `pip install -r reels-engine/reels_gen/requirements.txt`
3. FFmpeg + Chrome + Python в системе
4. `npm run dev`
5. Ключ Kie, при необходимости токен бота
6. Добавить аккаунт и войти
7. Сгенерировать тестовый рилс и проверить заливку

Если задача — выкладка для людей: правки → версия → `build:win` → при необходимости `git push` (если пользователь просит).
