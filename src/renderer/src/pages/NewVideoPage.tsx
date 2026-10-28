import { ChevronDown, ImagePlus, Sparkles, Trash2, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type JSX } from 'react'
import { toast } from 'sonner'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Checkbox } from '@renderer/components/ui/checkbox'
import { Input } from '@renderer/components/ui/input'
import { Label } from '@renderer/components/ui/label'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { Switch } from '@renderer/components/ui/switch'
import { Textarea } from '@renderer/components/ui/textarea'
import { cn, fileName } from '@renderer/lib/utils'
import { seedComposerText, textOverridesFromDefaults } from '@shared/content-defaults'
import { PLATFORMS, hasVideoTitle } from '@shared/platforms'
import { TIKTOK_CAPTION_MAX, TIKTOK_HASHTAG_MAX, parseTiktokHashtags, parseVkCommunityClipsUrl } from '@shared/publish-options'
import { enabledTargets, platformsOfTargets, targetId } from '@shared/targets'
import type { AppState, ComposerDraft, PlatformId, PlatformOverride, TargetId } from '@shared/types'

function CoverThumb({ src, onClick }: { src?: string; onClick: () => void }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative h-[88px] w-[62px] shrink-0 overflow-hidden rounded-lg border border-dashed border-border bg-muted/40 hover:bg-muted/70"
      title="Своя обложка"
    >
      {src ? (
        <img src={src} alt="" className="h-full w-full object-cover" />
      ) : (
        <span className="flex h-full flex-col items-center justify-center gap-1 text-[10px] text-muted-foreground">
          <ImagePlus className="size-4" />
          обложка
        </span>
      )}
    </button>
  )
}

export function NewVideoPage({ state }: { state: AppState }): JSX.Element {
  const draft = state.composer
  const seeded = seedComposerText(draft, state.contentDefaults)
  const [videoPath, setVideoPath] = useState(draft.videoPath)
  const [coverPath, setCoverPath] = useState(draft.coverPath)
  const [title, setTitle] = useState(seeded.title)
  const [description, setDescription] = useState(seeded.description)
  const [hashtags, setHashtags] = useState(seeded.hashtags)
  // null — пользователь ещё не трогал список, берём галочки «грузить сюда» из «Аккаунтов»
  const [pickedTargets, setPickedTargets] = useState<TargetId[] | null>(draft.targets ?? null)
  const accountTargets = useMemo(
    () => enabledTargets(state.platformProfiles, state.targets).map((t) => t.id),
    [state.platformProfiles, state.targets]
  )
  const targets = pickedTargets ?? accountTargets
  const enabled = useMemo(() => platformsOfTargets(targets), [targets])
  const [overrides, setOverrides] = useState<Partial<Record<PlatformId, PlatformOverride>>>(seeded.overrides)
  const [openOverride, setOpenOverride] = useState<PlatformId | null>(null)
  const [scheduleOn, setScheduleOn] = useState(draft.scheduleOn)
  const [publishAt, setPublishAt] = useState(draft.publishAt)
  const [videoUrl, setVideoUrl] = useState('')
  const [kieBusy, setKieBusy] = useState(false)
  const [coverUrl, setCoverUrl] = useState('')
  const [overrideCoverUrls, setOverrideCoverUrls] = useState<Partial<Record<PlatformId, string>>>({})
  const skipSave = useRef(true)
  const latest = useRef<ComposerDraft>(draft)

  const canSubmit = videoPath && title.trim() && targets.length > 0

  const loggedOut = useMemo(
    () => enabled.filter((id) => id !== 'youtube' && !state.accounts[id]?.loggedIn),
    [enabled, state.accounts]
  )

  useEffect(() => {
    let cancelled = false
    void (async () => {
      if (videoPath) {
        const url = await window.api.previewUrl(videoPath).catch(() => '')
        if (!cancelled) setVideoUrl(url)
      }
      if (coverPath) {
        const url = await window.api.previewUrl(coverPath).catch(() => '')
        if (!cancelled) setCoverUrl(url)
      }
      const next: Partial<Record<PlatformId, string>> = {}
      for (const id of PLATFORMS.map((p) => p.id)) {
        const path = overrides[id]?.coverPath
        if (path) next[id] = await window.api.previewUrl(path).catch(() => '')
      }
      if (!cancelled) setOverrideCoverUrls(next)
    })()
    return () => {
      cancelled = true
    }
    // только первичная гидратация превью из сохранённого черновика
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    latest.current = {
      videoPath,
      coverPath,
      title,
      description,
      hashtags,
      enabledPlatforms: enabled,
      targets: pickedTargets ?? undefined,
      overrides,
      publishOptions: state.composer.publishOptions,
      scheduleOn,
      publishAt
    }
  }, [
    videoPath,
    coverPath,
    title,
    description,
    hashtags,
    enabled,
    pickedTargets,
    overrides,
    state.composer.publishOptions,
    scheduleOn,
    publishAt
  ])

  useEffect(() => {
    if (skipSave.current) {
      skipSave.current = false
      return
    }
    const timer = window.setTimeout(() => {
      void window.api.saveComposer(latest.current)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [videoPath, coverPath, title, description, hashtags, pickedTargets, overrides, state.composer.publishOptions, scheduleOn, publishAt])

  useEffect(() => {
    return () => {
      void window.api.saveComposer(latest.current)
    }
  }, [])

  async function pickVideo(): Promise<void> {
    const path = await window.api.pickVideo()
    if (!path) return
    setVideoPath(path)
    setVideoUrl(await window.api.previewUrl(path))
    if (!title) setTitle(fileName(path).replace(/\.[^.]+$/, ''))
  }

  async function pickCover(platform?: PlatformId): Promise<void> {
    const path = await window.api.pickImage()
    if (!path) return
    const url = await window.api.previewUrl(path)
    if (platform) {
      setOverrides((prev) => ({ ...prev, [platform]: { ...prev[platform], coverPath: path } }))
      setOverrideCoverUrls((prev) => ({ ...prev, [platform]: url }))
    } else {
      setCoverPath(path)
      setCoverUrl(url)
    }
  }

  function toggleTarget(id: TargetId): void {
    setPickedTargets(targets.includes(id) ? targets.filter((x) => x !== id) : [...targets, id])
  }

  async function kieFill(): Promise<void> {
    const list = enabled.length ? enabled : [...PLATFORMS.map((p) => p.id)]
    setKieBusy(true)
    try {
      const res = await window.api.kiePackOne({ title: title.trim(), description, hashtags }, list)
      setOverrides((prev) => {
        const next = { ...prev }
        for (const id of list) {
          const v = res.pack[id]
          if (!v) continue
          next[id] = {
            ...next[id],
            ...(v.title ? { title: v.title } : {}),
            ...(v.description ? { description: v.description } : {}),
            ...(v.hashtags ? { hashtags: v.hashtags } : {})
          }
        }
        return next
      })
      toast.success(res.source === 'kie' ? `Kie заполнила тексты для ${list.length} площадок` : 'Kie недоступна — тексты собраны из ваших полей')
    } catch {
      /* тост из main */
    } finally {
      setKieBusy(false)
    }
  }

  async function submit(): Promise<void> {
    if (!canSubmit) return
    let when: string | undefined
    if (scheduleOn) {
      if (!publishAt) {
        toast.error('Укажите дату и время отложенной публикации')
        return
      }
      const parsed = new Date(publishAt)
      if (Number.isNaN(parsed.getTime())) {
        toast.error('Некорректная дата отложенной публикации')
        return
      }
      if (parsed.getTime() <= Date.now()) {
        toast.error('Время публикации должно быть в будущем')
        return
      }
      when = parsed.toISOString()
    }
    await window.api.addJob({
      videoPath,
      title: title.trim(),
      description,
      hashtags,
      coverPath: coverPath || undefined,
      enabledPlatforms: enabled,
      targets,
      overrides,
      publishOptions: state.composer.publishOptions,
      publishAt: when
    })
    toast.success('Ролик добавлен в очередь')
    skipSave.current = true
    const defaults = state.contentDefaults
    const textOverrides = textOverridesFromDefaults(defaults)
    setVideoPath('')
    setCoverPath('')
    setVideoUrl('')
    setCoverUrl('')
    setTitle(defaults.title)
    setDescription(defaults.description)
    setHashtags(defaults.hashtags || defaults.platforms.tiktok?.hashtags || '')
    setOverrides(textOverrides)
    setOverrideCoverUrls({})
    setScheduleOn(false)
    setPublishAt('')
    await window.api.saveComposer({
      videoPath: '',
      coverPath: '',
      title: defaults.title,
      description: defaults.description,
      hashtags: defaults.hashtags || defaults.platforms.tiktok?.hashtags || '',
      enabledPlatforms: enabled,
      targets: pickedTargets ?? undefined,
      overrides: textOverrides,
      publishOptions: state.composer.publishOptions,
      scheduleOn: false,
      publishAt: ''
    })
    skipSave.current = false
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 py-5">
        <h1 className="text-xl font-semibold">Новый ролик</h1>
        <p className="text-sm text-muted-foreground">
          Ролик слева, площадки справа. Шаблон названия, описания и хэштегов — в «Настройки»
        </p>
      </header>
      <ScrollArea className="flex-1">
        <div className="space-y-6 px-8 py-6">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="space-y-6">
              <div
                role="button"
                tabIndex={0}
                onClick={() => void pickVideo()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') void pickVideo()
                }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  const file = e.dataTransfer.files[0]
                  if (!file) return
                  try {
                    const path = window.api.getPathForFile(file)
                    void (async () => {
                      setVideoPath(path)
                      setVideoUrl(await window.api.previewUrl(path))
                      if (!title) setTitle(fileName(path).replace(/\.[^.]+$/, ''))
                    })()
                  } catch {
                    toast.error('Не удалось прочитать файл. Выберите его через кнопку.')
                  }
                }}
                className="flex w-full cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-violet-300 bg-violet-50 px-6 py-10 text-center transition hover:bg-violet-100/80"
              >
                {videoPath ? (
                  <>
                    {videoUrl ? (
                      <video
                        src={videoUrl}
                        className="mb-3 max-h-56 rounded-xl"
                        controls
                        onClick={(e) => e.stopPropagation()}
                        onPointerDown={(e) => e.stopPropagation()}
                      />
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="mb-3"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        const generatedTitle = fileName(videoPath).replace(/\.[^.]+$/, '')
                        if (title === generatedTitle) setTitle('')
                        setVideoPath('')
                        setVideoUrl('')
                      }}
                    >
                      <Trash2 className="size-3.5" />
                      Удалить ролик
                    </Button>
                  </>
                ) : (
                  <Upload className="mb-3 size-8 text-violet-600" />
                )}
                <div className="font-medium">{videoPath ? fileName(videoPath) : 'Перетащите ролик или выберите файл'}</div>
                <div className="mt-1 text-xs text-muted-foreground">MP4, MOV, WebM · лучше 9:16</div>
              </div>

              <div className="space-y-3">
                <Label htmlFor="title">Название</Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={state.contentDefaults.title || 'Как назовём ролик'}
                />
              </div>
              <div className="space-y-3">
                <Label htmlFor="desc">Описание</Label>
                <Textarea
                  id="desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={state.contentDefaults.description || 'Текст, ссылки — шаблон можно сохранить в Настройках'}
                />
              </div>
              <div className="space-y-3">
                <Label htmlFor="hashtags">Хэштеги TikTok и Дзен</Label>
                <Input
                  id="hashtags"
                  value={hashtags}
                  onChange={(e) => setHashtags(e.target.value)}
                  placeholder={
                    state.contentDefaults.hashtags ||
                    state.contentDefaults.platforms.tiktok?.hashtags ||
                    'свет, интерьер, обзор'
                  }
                />
                <p className="text-[11px] text-muted-foreground">
                  До {TIKTOK_HASHTAG_MAX} через запятую. Одни теги — в TikTok и в Дзен (там бот жмёт Enter).{' '}
                  {parseTiktokHashtags(hashtags).length}/{TIKTOK_HASHTAG_MAX}
                </p>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-xl border border-violet-100 bg-violet-50/50 px-4 py-3">
                <div>
                  <div className="text-sm font-medium">Тексты под каждую площадку от Kie</div>
                  <div className="text-xs text-muted-foreground">
                    По названию, описанию и хэштегам выше — свои заголовок, описание и теги для каждой выбранной площадки, с её лимитами. Результат — в «ещё» у площадок.
                  </div>
                </div>
                <Button variant="outline" disabled={kieBusy || (!title.trim() && !description.trim())} onClick={() => void kieFill()}>
                  <Sparkles className="size-4" />
                  {kieBusy ? 'Думаю…' : 'Заполнить'}
                </Button>
              </div>
              <div className="space-y-3">
                <Label>Обложка для всех площадок</Label>
                <button
                  type="button"
                  onClick={() => void pickCover()}
                  className="flex h-36 w-28 items-center justify-center overflow-hidden rounded-xl border border-dashed border-border bg-muted/40"
                >
                  {coverUrl ? (
                    <img src={coverUrl} alt="Обложка" className="h-full w-full object-cover" />
                  ) : (
                    <span className="flex flex-col items-center gap-2 px-2 text-center text-xs text-muted-foreground">
                      <ImagePlus className="size-5" />
                      Выбрать кадр
                    </span>
                  )}
                </button>
              </div>

              <div className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
                <div>
                  <div className="text-sm font-medium">Отложенная публикация</div>
                  <div className="text-xs text-muted-foreground">Бот подождёт это время, затем начнёт загрузку</div>
                </div>
                <Switch checked={scheduleOn} onCheckedChange={setScheduleOn} />
              </div>
              {scheduleOn && (
                <Input type="datetime-local" value={publishAt} onChange={(e) => setPublishAt(e.target.value)} />
              )}
            </div>

            <div className="space-y-4">
              <Card className="p-4">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-sm font-medium">Куда загрузить</span>
                  {pickedTargets !== null && (
                    <button
                      type="button"
                      className="text-[11px] text-violet-700 hover:underline"
                      onClick={() => setPickedTargets(null)}
                    >
                      как в «Аккаунтах»
                    </button>
                  )}
                </div>
                <p className="mb-3 text-[11px] text-muted-foreground">
                  По умолчанию — галочки «грузить сюда» из «Аккаунтов». «ещё» — своя обложка и текст площадки.
                </p>
                <div className="space-y-2">
                  {PLATFORMS.map((platform) => {
                    const profiles = state.platformProfiles[platform.id] ?? []
                    const legacyId = platform.id === 'youtube' ? null : targetId(platform.id)
                    const channelIds = [...(legacyId ? [legacyId] : []), ...profiles.map((p) => targetId(platform.id, p.number))]
                    const pickedCount = channelIds.filter((id) => targets.includes(id)).length
                    const on = pickedCount > 0
                    const ownCover = overrideCoverUrls[platform.id]
                    const extraOpen = openOverride === platform.id
                    return (
                      <div key={platform.id} className={cn('rounded-xl border bg-white p-3', extraOpen ? 'border-violet-200' : 'border-border')}>
                        <div className="flex items-center gap-3">
                          <Checkbox
                            checked={channelIds.length > 0 && channelIds.every((id) => targets.includes(id)) ? true : on ? 'indeterminate' : false}
                            disabled={channelIds.length === 0}
                            onCheckedChange={() => {
                              const all = channelIds.every((id) => targets.includes(id))
                              const rest = targets.filter((id) => !channelIds.includes(id))
                              setPickedTargets(all ? rest : [...rest, ...channelIds])
                            }}
                          />
                          <span
                            className="flex size-8 items-center justify-center rounded-lg"
                            style={{ background: `${platform.color}22`, color: platform.color }}
                          >
                            <PlatformIcon id={platform.id} className="size-4" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium">{platform.shortName}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {channelIds.length === 0
                                ? `${platform.format} · аккаунтов нет`
                                : `${platform.format} · аккаунтов: ${pickedCount}/${channelIds.length}`}
                              {platform.id === 'vk'
                                ? parseVkCommunityClipsUrl(state.composer.publishOptions.vk.communityUrl)
                                  ? ` · сообщество`
                                  : ' · в профиль'
                                : ''}
                            </div>
                          </div>
                          {ownCover ? <img src={ownCover} alt="" className="h-9 w-6 rounded object-cover" /> : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="gap-1 px-2"
                            onClick={() => setOpenOverride(extraOpen ? null : platform.id)}
                          >
                            ещё
                            <ChevronDown className={cn('size-3.5 transition', extraOpen && 'rotate-180')} />
                          </Button>
                        </div>
                        {channelIds.length > 0 && (
                          <div className="mt-2 grid grid-cols-2 gap-1.5 pl-11">
                            {legacyId && (
                              <label className="flex cursor-pointer items-center gap-2 text-xs">
                                <Checkbox checked={targets.includes(legacyId)} onCheckedChange={() => toggleTarget(legacyId)} />
                                <span className={cn('truncate', targets.includes(legacyId) ? 'text-foreground' : 'text-muted-foreground')}>
                                  Прежний аккаунт
                                </span>
                              </label>
                            )}
                            {profiles.map((profile) => {
                              const id = targetId(platform.id, profile.number)
                              const checked = targets.includes(id)
                              return (
                                <label key={id} className="flex cursor-pointer items-center gap-2 text-xs">
                                  <Checkbox checked={checked} onCheckedChange={() => toggleTarget(id)} />
                                  <span className={cn('truncate', checked ? 'text-foreground' : 'text-muted-foreground')} title={profile.path}>
                                    {profile.name} <span className="opacity-60">#{profile.number}</span>
                                  </span>
                                </label>
                              )
                            })}
                          </div>
                        )}
                        {extraOpen && (
                          <div className="mt-3 space-y-3 border-t border-border pt-3">
                            <div className="flex gap-3">
                              <CoverThumb src={overrideCoverUrls[platform.id]} onClick={() => void pickCover(platform.id)} />
                              <div className="min-w-0 flex-1 space-y-2">
                                {hasVideoTitle(platform.id) && (
                                  <Input
                                    placeholder={
                                      state.contentDefaults.platforms[platform.id]?.title ||
                                      `Название для ${platform.shortName}`
                                    }
                                    value={overrides[platform.id]?.title ?? ''}
                                    onChange={(e) =>
                                      setOverrides((prev) => ({
                                        ...prev,
                                        [platform.id]: { ...prev[platform.id], title: e.target.value }
                                      }))
                                    }
                                  />
                                )}
                                <Textarea
                                  className="min-h-16"
                                  maxLength={platform.id === 'tiktok' ? TIKTOK_CAPTION_MAX : undefined}
                                  placeholder={
                                    platform.id === 'tiktok'
                                      ? `Описание для TikTok, до ${TIKTOK_CAPTION_MAX} символов. Название не используется.`
                                      : platform.id === 'vk'
                                        ? 'Описание клипа. В VK нет названия — только этот текст.'
                                        : platform.id === 'dzen'
                                          ? 'Описание ролика. В Дзене нет названия. Хэштеги — общее поле слева.'
                                          : platform.id === 'instagram'
                                            ? 'Описание рилса. В Instagram нет названия.'
                                            : state.contentDefaults.platforms[platform.id]?.description ||
                                              'Своё описание — или шаблон из Настроек'
                                  }
                                  value={overrides[platform.id]?.description ?? ''}
                                  onChange={(e) =>
                                    setOverrides((prev) => ({
                                      ...prev,
                                      [platform.id]: {
                                        ...prev[platform.id],
                                        description:
                                          platform.id === 'tiktok'
                                            ? e.target.value.slice(0, TIKTOK_CAPTION_MAX)
                                            : e.target.value
                                      }
                                    }))
                                  }
                                />
                                {platform.id === 'tiktok' && (
                                  <div className="text-[11px] text-muted-foreground">
                                    {(overrides.tiktok?.description ?? '').length}/{TIKTOK_CAPTION_MAX}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </Card>
              {loggedOut.length > 0 && (
                <p className="text-xs text-amber-700">Не все выбранные площадки авторизованы — зайдите в «Аккаунты».</p>
              )}
              {targets.length === 0 && (
                <p className="text-xs text-amber-700">Не выбрано ни одного направления. Отметьте каналы здесь или в «Аккаунтах».</p>
              )}
              <Button className="w-full" size="lg" disabled={!canSubmit} onClick={() => void submit()}>
                Добавить в очередь
              </Button>
            </div>
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
