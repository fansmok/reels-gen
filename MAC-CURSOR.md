# Продолжи работу на Mac

Это десктопное приложение «Рилс Загрузка» (`reels-uploader`): Electron + React + Playwright.  
Загрузка роликов — через установленный Google Chrome. Генерация и профили — встроенный движок `reels-engine/` (Python).

Windows-версия должна остаться рабочей. Говори с пользователем по-русски.

Перед кодом библиотек (electron-builder, Electron, Playwright) сверяйся с Context7. Semgrep не запускай, пока он сам не попросит.

## Уже сделано — не переделывать

Ветки включаются только на `darwin`. На Windows код ведёт себя как раньше.

- `src/main/store.ts` — пути движка по умолчанию на встроенный `reels-engine`. Сохранённые пути в `state.json` не затираются.
- `src/preload/index.ts` — в API есть `platform`.
- `src/renderer/src/components/EngineSettings.tsx` — на Mac подпись «Python» и диалог без фильтра `.exe`. На Windows подпись `python.exe` и фильтр `.exe`.
- `src/main/generator.ts` — на Mac остановка через `pkill -P` и `SIGKILL`. На Windows `taskkill /T /F`.
- `src/main/python.ts` — на Mac в окружение моста пишутся `REELS_SCREEN_CSS` и `REELS_SCREEN_SCALE`. На Windows эти переменные не задаются.
- `python/yt_bridge.py` — WinAPI экрана только на `win32`. Иначе читается размер от Electron, иначе запас `1280×720`. Chrome на Mac стартует с `start_new_session=True`. `_taskkill_tree` на Windows — `taskkill`; на Mac — `os.killpg`, только если процесс сам лидер группы.
- `electron-builder.yml` — Mac target `dmg`, подпись выключена: `mac.sign.identity: null`. Блок `win` / `nsis` не менять.

Загрузка через Playwright (`channel: 'chrome'`) в `src/main/browser.ts` на Mac работает с установленным Google Chrome. Её заново не писать.

## Сразу после распаковки

1. Открыть эту папку в Cursor как проект.
2. Поставить Node.js 22, Google Chrome и Command Line Tools: `xcode-select --install`.
3. В корне: `npm install`.
4. Python 3.11+: `pip install -r reels-engine/reels_gen/requirements.txt`.
5. `brew install ffmpeg` — в PATH должны быть `ffmpeg` и `ffprobe`.
6. `uname -m` — архитектура для сборки.
7. `npm run build:mac`.
8. Отдать `dist/reels-uploader-{version}.dmg`.
9. Если macOS не пускает: правый клик → «Открыть», либо `xattr -dr com.apple.quarantine` на `.app`.

`npm run build:win` на Mac не запускать.

## Движок и профили на Mac

Движок уже в репозитории: `reels-engine/`.

1. Python той же архитектуры, что Mac; пакеты из `reels-engine/reels_gen/requirements.txt`.
2. `plain_profiles.find_google_chrome()` должен находить `/Applications/Google Chrome.app/...` и при необходимости Chrome for Testing под mac.
3. Профили Windows не копировать — аккаунты завести заново в `reels-engine/profiles`.
4. В настройках проверить пути: Python, папка движка (`reels-engine`), профили, `YT-COOKIES`.

## Что с Windows не переносится

- Сессии входов — на Mac войти заново (`~/Library/Application Support/reels-uploader/`).
- Пароль прокси в `state.json` (DPAPI) — вписать заново.
- `python.exe`, `.dll`, Windows Chrome for Testing.

## Дальше, когда правишь код

- Новые отличия Mac — в `process.platform === 'darwin'` / `sys.platform != "win32"`. Ветку `win32` не ломать.
- Патч / минор — в `package.json` и корне `package-lock.json`.
- На Mac после правок: `npm run build:mac`, отдать `.dmg`.
- Только `.md` / rules — версию не поднимать.
