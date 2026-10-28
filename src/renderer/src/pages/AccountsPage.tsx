import { Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useState, type JSX } from 'react'
import { toast } from 'sonner'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Badge } from '@renderer/components/ui/badge'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Checkbox } from '@renderer/components/ui/checkbox'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { PLATFORMS, getPlatform } from '@shared/platforms'
import { targetId } from '@shared/targets'
import type { AppState, PlatformId, YoutubeProfileInfo } from '@shared/types'

const okBadge = 'border-emerald-200 bg-emerald-50 text-emerald-700'
const mutedBadge = 'border-zinc-200 bg-zinc-50 text-zinc-600'
const violetBadge = 'border-violet-200 bg-violet-50 text-violet-700'
const amberBadge = 'border-amber-200 bg-amber-50 text-amber-700'

function TargetToggle({
  id,
  enabled,
  label = 'Грузить сюда'
}: {
  id: string
  enabled: boolean
  label?: string
}): JSX.Element {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-sm">
      <Checkbox checked={enabled} onCheckedChange={(v) => void window.api.setTarget(id, v === true)} />
      <span className={enabled ? 'font-medium text-foreground' : 'text-muted-foreground'}>{label}</span>
    </label>
  )
}

function SessionCard({ platformId, state }: { platformId: PlatformId; state: AppState }): JSX.Element {
  const meta = getPlatform(platformId)
  const id = targetId(platformId)
  const enabled = state.targets[id] ?? false
  const account = state.accounts[platformId]
  const busy = state.runner !== 'idle'

  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <span
          className="flex size-11 items-center justify-center rounded-xl"
          style={{ background: `${meta.color}22`, color: meta.color }}
        >
          <PlatformIcon id={platformId} className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{meta.name}</div>
          <div className="text-xs text-muted-foreground">Прежний аккаунт — тот, куда уже входили</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge className={account.loggedIn ? okBadge : mutedBadge}>{account.loggedIn ? 'вход есть' : 'вход не проверен'}</Badge>
            <Badge className={account.browserOpen ? okBadge : mutedBadge}>{account.browserOpen ? 'Chrome открыт' : 'закрыт'}</Badge>
          </div>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
          {account.browserOpen ? (
            <Button size="sm" variant="outline" onClick={() => void window.api.closeBrowser(platformId)}>
              Закрыть
            </Button>
          ) : (
            <Button size="sm" disabled={busy} onClick={() => void window.api.login(platformId)}>
              Открыть
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={!account.browserOpen}
            onClick={() =>
              void window.api.confirmLogin(platformId).then((ok) => {
                if (ok) toast.success(`${meta.shortName}: вход сохранён`)
                else toast.info(`${meta.shortName}: вход пока не виден`)
              })
            }
          >
            Я вошёл
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => {
              const ok = window.confirm(
                `Удалить прежний аккаунт ${meta.shortName}? Сохранённый вход будет стёрт. Карточка останется — войти можно заново. Это нельзя отменить.`
              )
              if (!ok) return
              void window.api.deleteSession(platformId).then(
                () => toast.success(`Прежний аккаунт ${meta.shortName} удалён`),
                () => undefined
              )
            }}
          >
            <Trash2 className="size-3.5" />
            Удалить
          </Button>
        </div>
        <TargetToggle id={id} enabled={enabled} />
      </div>
    </Card>
  )
}

function ProfileCard({
  platformId,
  profile,
  state
}: {
  platformId: PlatformId
  profile: YoutubeProfileInfo
  state: AppState
}): JSX.Element {
  const id = targetId(platformId, profile.number)
  const enabled = state.targets[id] ?? false
  const isOpen = state.openAccountProfiles.includes(id)
  const meta = getPlatform(platformId)
  const busy = state.runner !== 'idle'

  async function open(): Promise<void> {
    toast.info(`Открываю ${meta.shortName} #${profile.number}: свой отпечаток и прокси`)
    await window.api.openAccount(platformId, profile.number)
  }

  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <span
          className="flex size-11 items-center justify-center rounded-xl"
          style={{ background: `${meta.color}22`, color: meta.color }}
        >
          <PlatformIcon id={platformId} className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-semibold">{profile.name}</span>
            <span className="text-xs text-muted-foreground">#{profile.number}</span>
          </div>
          <div className="truncate text-xs text-muted-foreground" title={profile.path}>
            {profile.proxyLabel ? `прокси ${profile.proxyLabel}` : 'без прокси — IP компьютера'}
            {profile.proxyIp ? ` → ${profile.proxyIp}` : ''}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge className={isOpen ? okBadge : mutedBadge}>{isOpen ? 'Chrome открыт' : 'закрыт'}</Badge>
            {profile.bound.map((b) => (
              <Badge key={b} className={violetBadge}>
                {b}
              </Badge>
            ))}
            {profile.locked && !isOpen && <Badge className={amberBadge}>занят другим Chrome</Badge>}
          </div>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
          {isOpen ? (
            <Button size="sm" variant="outline" onClick={() => void window.api.closeAccount(platformId, profile.number)}>
              Закрыть
            </Button>
          ) : (
            <Button size="sm" disabled={busy} onClick={() => void open()}>
              Открыть
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => {
              const ok = window.confirm(
                `Удалить ${meta.shortName} #${profile.number}? Папка профиля будет стёрта, даже если аккаунт используется в других программах. Это нельзя отменить.`
              )
              if (!ok) return
              void window.api.deleteAccount(platformId, profile.number).then(
                () => toast.success(`${meta.shortName} #${profile.number} удалён`),
                () => undefined
              )
            }}
          >
            <Trash2 className="size-3.5" />
            Удалить
          </Button>
        </div>
        <TargetToggle id={id} enabled={enabled} />
      </div>
    </Card>
  )
}

export function AccountsPage({ state }: { state: AppState }): JSX.Element {
  const engine = state.engine
  const enabledCount = Object.values(state.targets).filter(Boolean).length
  const [adding, setAdding] = useState<PlatformId | null>(null)
  const [proxy, setProxy] = useState('')
  const [creating, setCreating] = useState<PlatformId | null>(null)

  async function createAccount(platformId: PlatformId): Promise<void> {
    const meta = getPlatform(platformId)
    setCreating(platformId)
    try {
      const created = await window.api.createAccount(platformId, proxy.trim())
      setProxy('')
      setAdding(null)
      toast.success(`${meta.shortName} #${created.number} создан. Войдите в аккаунт в открывшемся Chrome.`)
    } catch {
      /* тост из main */
    } finally {
      setCreating(null)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-border px-8 py-5">
        <div>
          <h1 className="text-xl font-semibold">Аккаунты</h1>
          <p className="text-sm text-muted-foreground">
            Галочка «Грузить сюда» — куда уйдёт ролик. Отмечено направлений: {enabledCount}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Карточка «прежний аккаунт» — тот вход, который уже был. Новые аккаунты добавляются отдельно, каждый со своим
            отпечатком и прокси. Размер окна не больше экрана этого компьютера.
          </p>
        </div>
        <Button
          variant="outline"
          disabled={state.youtubeProfilesLoading}
          onClick={() => void window.api.refreshYoutubeProfiles()}
        >
          <RefreshCw className={`size-3.5 ${state.youtubeProfilesLoading ? 'animate-spin' : ''}`} />
          Обновить
        </Button>
      </header>
      <ScrollArea className="flex-1">
        <div className="space-y-8 px-8 py-6">
          {!engine.ok && (
            <Card className="border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <div className="font-medium">Движок генератора не подключён</div>
              <ul className="mt-1 list-disc pl-5 text-xs">
                {engine.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
              <div className="mt-2 text-xs">Без него новый аккаунт с отпечатком не создать. Пути — в «Настройках».</div>
            </Card>
          )}
          {PLATFORMS.map((platform) => {
            const profiles = state.platformProfiles[platform.id] ?? []
            const formOpen = adding === platform.id
            return (
              <section key={platform.id} className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold">{platform.name}</h2>
                    <p className="text-xs text-muted-foreground">
                      {platform.id === 'youtube'
                        ? profiles.length === 0
                          ? 'Аккаунтов пока нет.'
                          : `Аккаунтов: ${profiles.length}`
                        : `Прежний аккаунт на месте. Новых профилей: ${profiles.length}`}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    disabled={!engine.ok || creating !== null}
                    onClick={() => {
                      setProxy('')
                      setAdding(formOpen ? null : platform.id)
                    }}
                  >
                    <Plus className="size-3.5" />
                    Добавить аккаунт
                  </Button>
                </div>
                {formOpen && (
                  <Card className="space-y-3 p-4">
                    <div>
                      <div className="text-sm font-medium">Новый аккаунт {platform.shortName}</div>
                      <p className="text-xs text-muted-foreground">
                        У каждого аккаунта свой профиль Chrome, отпечаток и свой прокси. Прокси можно не указывать. Формат:
                        host:port:login:password
                      </p>
                    </div>
                    <Input
                      value={proxy}
                      spellCheck={false}
                      placeholder="host:port:login:password — пусто, если прокси не нужен"
                      onChange={(e) => setProxy(e.target.value)}
                    />
                    <div className="flex gap-2">
                      <Button size="sm" disabled={creating !== null} onClick={() => void createAccount(platform.id)}>
                        {creating === platform.id ? 'Создаю отпечаток…' : 'Создать и открыть'}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={creating !== null} onClick={() => setAdding(null)}>
                        Отмена
                      </Button>
                    </div>
                  </Card>
                )}
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {platform.id !== 'youtube' && <SessionCard platformId={platform.id} state={state} />}
                  {profiles.map((profile) => (
                    <ProfileCard key={profile.number} platformId={platform.id} profile={profile} state={state} />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}
