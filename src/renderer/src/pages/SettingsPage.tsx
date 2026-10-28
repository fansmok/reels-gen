import { useEffect, useRef, useState, type JSX } from 'react'
import { ContentDefaultsEditor } from '@renderer/components/ContentDefaultsEditor'
import { EngineSettings } from '@renderer/components/EngineSettings'
import { PublishOptionsEditor } from '@renderer/components/PublishOptionsEditor'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Label } from '@renderer/components/ui/label'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { mergeContentDefaults } from '@shared/content-defaults'
import type { AppState } from '@shared/types'

export function SettingsPage({ state }: { state: AppState }): JSX.Element {
  const [platformSec, setPlatformSec] = useState(String(Math.round(state.settings.delayBetweenPlatformsMs / 1000)))
  const [videoSec, setVideoSec] = useState(String(Math.round(state.settings.delayBetweenVideosMs / 1000)))
  const [publishOptions, setPublishOptions] = useState(state.composer.publishOptions)
  const [contentDefaults, setContentDefaults] = useState(() => {
    const merged = mergeContentDefaults(state.contentDefaults)
    const tiktok = state.composer.publishOptions.tiktok
    if (!merged.hashtags && tiktok?.hashtags) merged.hashtags = tiktok.hashtags
    if (!merged.platforms.tiktok.description && tiktok?.description) {
      merged.platforms.tiktok.description = tiktok.description
    }
    if (!merged.platforms.tiktok.hashtags && tiktok?.hashtags) {
      merged.platforms.tiktok.hashtags = tiktok.hashtags
    }
    return merged
  })
  const skipContentSave = useRef(true)
  const latestContent = useRef(contentDefaults)
  latestContent.current = contentDefaults

  useEffect(() => {
    setPlatformSec(String(Math.round(state.settings.delayBetweenPlatformsMs / 1000)))
    setVideoSec(String(Math.round(state.settings.delayBetweenVideosMs / 1000)))
  }, [state.settings])

  useEffect(() => {
    setPublishOptions(state.composer.publishOptions)
  }, [state.composer.publishOptions])

  useEffect(() => {
    if (skipContentSave.current) {
      skipContentSave.current = false
      return
    }
    const timer = window.setTimeout(() => {
      void window.api.saveContentDefaults(latestContent.current)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [contentDefaults])

  useEffect(() => {
    return () => {
      void window.api.saveContentDefaults(latestContent.current)
    }
  }, [])

  function save(nextPlatform = platformSec, nextVideo = videoSec): void {
    const platform = Math.max(0, Number(nextPlatform) || 0)
    const video = Math.max(0, Number(nextVideo) || 0)
    void window.api.saveSettings({
      ...state.settings,
      delayBetweenPlatformsMs: platform * 1000,
      delayBetweenVideosMs: video * 1000,
      headed: true
    })
  }

  const engineBlock = <EngineSettings state={state} />

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 py-5">
        <h1 className="text-xl font-semibold">Настройки</h1>
        <p className="text-sm text-muted-foreground">
          Текст роликов, паузы и галочки публикации. Сохраняются сразу и действуют на каждый новый ролик
        </p>
      </header>
      <ScrollArea className="flex-1">
        <div className="max-w-4xl space-y-6 px-8 py-6">
          {engineBlock}
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">Название, описание и хэштеги</h2>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Один раз напишите текст и хэштеги. На экране «Новый ролик» они уже будут в полях — для конкретного
                видео их можно поправить, шаблон здесь не изменится. Хэштеги общие для TikTok и Дзена.
              </p>
            </div>
            <ContentDefaultsEditor value={contentDefaults} onChange={setContentDefaults} />
          </div>
          <Card className="space-y-3 p-5">
            <Label>Пауза между площадками, секунды</Label>
            <Input
              type="number"
              min={0}
              value={platformSec}
              onChange={(e) => {
                setPlatformSec(e.target.value)
                save(e.target.value, videoSec)
              }}
            />
            <p className="text-xs text-muted-foreground">После YouTube бот подождёт, затем откроет Rutube и так далее</p>
          </Card>
          <Card className="space-y-3 p-5">
            <Label>Пауза между роликами, секунды</Label>
            <Input
              type="number"
              min={0}
              value={videoSec}
              onChange={(e) => {
                setVideoSec(e.target.value)
                save(platformSec, e.target.value)
              }}
            />
            <p className="text-xs text-muted-foreground">Когда первый ролик ушёл на все площадки, ждём перед вторым</p>
          </Card>
          <Card className="p-5 text-sm text-muted-foreground">
            Браузер всегда видимый: так можно пройти 2FA, капчу или поправить шаг руками, если сайт изменил кнопки.
          </Card>
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">Как публиковать на каждой площадке</h2>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Эти тумблеры бот проставит сам, когда будет заливать ролик. Менять их на экране «Новый ролик» не нужно:
                один раз настроили здесь — и все следующие ролики уходят с этими правилами.
              </p>
            </div>
            <PublishOptionsEditor
              options={publishOptions}
              onChange={(next) => {
                setPublishOptions(next)
                void window.api.savePublishOptions(next)
              }}
            />
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
