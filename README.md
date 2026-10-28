# Shorts Generator / Рилс Загрузка

Десктоп-приложение для сборки вертикальных рилсов и загрузки на YouTube, Rutube, Pinterest, Дзен, TikTok, VK и Instagram.

Репозиторий: [github.com/fansmok/reels-gen](https://github.com/fansmok/reels-gen)

Для ИИ и разработчиков: подробная карта проекта, запуск и правила правок — **[AGENTS.md](./AGENTS.md)**.

## Что внутри

- Оболочка Electron и мосты `python/`
- Движок `reels-engine/reels_gen` — склейка, баннеры, CTA, субтитры, Kie, обложки, стикеры
- Профили аккаунтов и отпечаток Chrome — `reels-engine/profiles` и `reels-engine/YT-COOKIES`

## Ключи и данные

Токен Telegram-бота, API-ключ Kie и прокси каждый вписывает сам в настройках. Не коммитьте `state.json`, `.env` и пароли.

## Что нужно на компьютере

- Windows 10/11 или macOS
- [Node.js](https://nodejs.org/) 20+ (если собираете из исходников)
- Python 3.11+ в PATH
- [FFmpeg](https://ffmpeg.org/) и `ffprobe` в PATH
- Google Chrome
- Зависимости Python:

```bash
pip install -r reels-engine/reels_gen/requirements.txt
```

## Быстрый старт

```bash
git clone https://github.com/fansmok/reels-gen.git
cd reels-gen
npm install
npm run dev
```

Движок по умолчанию — папка `reels-engine` (в установщике уже внутри `resources`).

Сборка Windows:

```bash
npm run build:win
```

Файл: `dist/reels-uploader-*-setup.exe`  
На Mac: `npm run build:mac` → `.dmg`.

## Настройки после запуска

1. **Python** — если пусто, программа ищет системный. Иначе укажите путь к `python.exe`.
2. **Kie API** — ключ с [kie.ai](https://kie.ai) для автозаголовков и текстов площадок.
3. **Telegram-бот** — токен от [@BotFather](https://t.me/BotFather). Программа должна быть открыта.
4. **Прокси** — по желанию.
5. **Аккаунты** — «Добавить аккаунт» создаёт профиль с отпечатком и открывает Chrome для входа. Прокси можно указать вручную (`host:port:login:password`).

### Telegram: файл без ссылки

Верхний ролик **файлом** сопроводите текстом, о чём видео (подпись или отдельное сообщение). По нему Kie пишет название и описание. Ссылку YouTube/Instagram можно без описания. Файлы через Bot API — до 20 МБ.

## Структура

| Путь | Назначение |
|------|------------|
| `src/` | Интерфейс и заливки |
| `python/` | Мосты к движку |
| `reels-engine/reels_gen/` | Склейка рилсов |
| `reels-engine/profiles/` | Папки Chrome-профилей |
| `reels-engine/YT-COOKIES/` | Отпечаток и запуск Chrome |
| `captions/` | Анимированные субтитры |

## Лицензия

Используйте и дорабатывайте по своему усмотрению. Не публикуйте чужие токены и пароли.
