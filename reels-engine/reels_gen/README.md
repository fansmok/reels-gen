# Генератор рилсов (reels_gen)

Папки:
- `1/` — верхние видео
- `2/` — нижние (в т.ч. скачанные с Instagram)
- `output/` — готовые двойные рилсы
- `upload_queue/` — стейджинг перед заливкой на YouTube Shorts

Вкладка GUI: **Генератор рилсов**
1. Сгенерировать рилсы
2. Сгенерировать и загрузить — на отмеченные plain-профили YouTube
   (через `vk_multi_packV2/local_reels_upload.py` + тот же пайплайн, что youtube-daily-agent)

У каждого ролика при загрузке уникальные title и description (`meta.py`).
