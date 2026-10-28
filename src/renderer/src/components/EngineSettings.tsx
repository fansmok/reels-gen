import { useEffect, useState, type JSX } from 'react'
import { toast } from 'sonner'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Label } from '@renderer/components/ui/label'
import { Switch } from '@renderer/components/ui/switch'
import type { AppState, EnginePaths } from '@shared/types'

const isMac = window.api.platform === 'darwin'

const FIELDS: { key: keyof EnginePaths; label: string; hint: string; kind: 'file' | 'folder' }[] = [
  {
    key: 'pythonExe',
    label: isMac ? 'Python' : 'python.exe',
    hint: 'Пусто — ищем системный Python. Нужны пакеты из reels-engine/reels_gen/requirements.txt и Whisper',
    kind: 'file'
  },
  {
    key: 'tgRoot',
    label: 'Папка движка',
    hint: 'По умолчанию встроенный reels-engine (внутри reels_gen). Своя папка — только если подменяете движок',
    kind: 'folder'
  },
  {
    key: 'vkBot',
    label: 'Папка профилей',
    hint: 'По умолчанию reels-engine/profiles — сюда создаются аккаунты',
    kind: 'folder'
  },
  {
    key: 'ydaRoot',
    label: 'youtube-daily-agent',
    hint: 'Только если используете отдельный агент каналов. Иначе пусто',
    kind: 'folder'
  },
  {
    key: 'ytCookies',
    label: 'Папка отпечатка Chrome',
    hint: 'По умолчанию reels-engine/YT-COOKIES',
    kind: 'folder'
  }
]

export function EngineSettings({ state }: { state: AppState }): JSX.Element {
  const [paths, setPaths] = useState<EnginePaths>(state.enginePaths)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    setPaths(state.enginePaths)
  }, [state.enginePaths])

  function update(key: keyof EnginePaths, value: string): void {
    const next = { ...paths, [key]: value }
    setPaths(next)
    void window.api.saveEnginePaths(next)
  }

  async function pick(field: (typeof FIELDS)[number]): Promise<void> {
    const picked =
      field.kind === 'file'
        ? await window.api.pickFile(
            `Выберите ${field.label}`,
            isMac ? undefined : [{ name: 'Программа', extensions: ['exe'] }]
          )
        : await window.api.pickFolder(`Выберите: ${field.label}`)
    if (picked) update(field.key, picked)
  }

  async function check(): Promise<void> {
    setChecking(true)
    const result = await window.api.checkEngine()
    setChecking(false)
    if (result.ok) toast.success(`Движок подключён: Python ${result.python ?? ''}, Chrome найден`)
    else toast.error(result.problems[0] ?? 'Движок не отвечает')
  }

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Движок генератора</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          Движок склейки уже внутри программы. Ниже — Python и дополнительные пути, если они вам нужны.
        </p>
      </div>
      <Card className="space-y-4 p-5">
        {FIELDS.map((field) => (
          <div key={field.key} className="space-y-1.5">
            <Label>{field.label}</Label>
            <div className="flex gap-2">
              <Input value={paths[field.key]} spellCheck={false} onChange={(e) => update(field.key, e.target.value)} />
              <Button variant="outline" onClick={() => void pick(field)}>
                Обзор
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          </div>
        ))}
        <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
          <div className="text-xs">
            {state.engine.ok ? (
              <span className="text-emerald-700">Подключено{state.engine.python ? ` · Python ${state.engine.python}` : ''}</span>
            ) : (
              <span className="text-amber-700">{state.engine.problems[0] ?? 'Не проверено'}</span>
            )}
          </div>
          <Button variant="outline" disabled={checking} onClick={() => void check()}>
            {checking ? 'Проверяю…' : 'Проверить'}
          </Button>
        </div>
      </Card>
      <Card className="space-y-2 p-5">
        <div className="font-medium">Ключ Kie AI</div>
        <p className="text-xs text-muted-foreground">
          Для заголовков, описаний и хэштегов под каждую площадку. Без ключа автотексты Kie не работают — впишите свой с kie.ai.
        </p>
        <Input
          type="password"
          spellCheck={false}
          placeholder="ключ API kie.ai"
          value={state.settings.kieApiKey ?? ''}
          onChange={(e) => void window.api.saveSettings({ ...state.settings, kieApiKey: e.target.value.trim() })}
        />
      </Card>
      <Card className="flex items-center justify-between gap-4 p-5">
        <div>
          <div className="font-medium">Особый Chrome при заливке на YouTube</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Выключено — обычный Google Chrome с прокси профиля. Включено — отдельный Chrome с отпечатком профиля
            (нужны заполненные пути профилей выше).
          </p>
        </div>
        <Switch
          checked={state.settings.antidetectOnUpload}
          onCheckedChange={(v) => void window.api.saveSettings({ ...state.settings, antidetectOnUpload: v })}
        />
      </Card>
      <Card className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="font-medium">Пачка роликов на YouTube — без повторов</div>
            <p className="mt-1 text-xs text-muted-foreground">
              Включено — каждый ролик из пачки (генератор, автоматизация) уходит только в один отмеченный канал,
              по кругу. Выключено — каждый ролик во все отмеченные каналы.
            </p>
          </div>
          <Switch
            checked={state.settings.youtubeDistribute}
            onCheckedChange={(v) => void window.api.saveSettings({ ...state.settings, youtubeDistribute: v })}
          />
        </div>
        {state.settings.youtubeDistribute && (
          <div className="space-y-1.5">
            <Label>Не больше роликов на один канал за пачку</Label>
            <Input
              type="number"
              min={1}
              max={50}
              className="w-32"
              value={state.settings.youtubePerChannel}
              onChange={(e) =>
                void window.api.saveSettings({
                  ...state.settings,
                  youtubePerChannel: Math.max(1, Math.min(50, Number(e.target.value) || 1))
                })
              }
            />
            <p className="text-xs text-muted-foreground">Лишние ролики остаются без YouTube, на другие площадки уходят как обычно.</p>
          </div>
        )}
      </Card>
    </div>
  )
}
