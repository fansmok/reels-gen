import { useEffect, useState, type JSX } from 'react'
import { toast } from 'sonner'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Label } from '@renderer/components/ui/label'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { Switch } from '@renderer/components/ui/switch'
import { PLATFORMS } from '@shared/platforms'
import { formatProxyLine, isProxyConfigured, parseProxyLine } from '@shared/proxy'
import type { AppState } from '@shared/types'

export function ProxyPage({ state }: { state: AppState }): JSX.Element {
  const [line, setLine] = useState(formatProxyLine(state.proxy))
  const [testing, setTesting] = useState(false)
  const configured = isProxyConfigured(parseProxyLine(line))

  useEffect(() => {
    setLine(formatProxyLine(state.proxy))
  }, [state.proxy])

  function saveLine(next: string): void {
    setLine(next)
    void window.api.saveProxy(parseProxyLine(next))
  }

  async function test(): Promise<void> {
    setTesting(true)
    const result = await window.api.testProxy()
    setTesting(false)
    if (result.ok) toast.success(`Прокси работает. IP: ${result.ip}`)
    else toast.error(result.error ?? 'Прокси не отвечает')
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 py-5">
        <h1 className="text-xl font-semibold">Прокси</h1>
        <p className="text-sm text-muted-foreground">
          Одна строка на всех. Отметьте площадки — они зайдут через этот прокси уже при авторизации.
        </p>
      </header>
      <ScrollArea className="flex-1">
        <div className="grid gap-6 px-8 py-6 lg:grid-cols-2">
          <Card className="p-5 space-y-4">
            <div>
              <div className="font-medium">Прокси</div>
              <div className="text-xs text-muted-foreground">host:port:login:pass</div>
            </div>
            <div className="space-y-2">
              <Label>Строка</Label>
              <Input
                value={line}
                onChange={(e) => saveLine(e.target.value)}
                placeholder="77.105.14.39:45478:login:pass"
                spellCheck={false}
                autoComplete="off"
              />
              <p className="text-xs text-muted-foreground">
                Можно без логина: host:port. Для SOCKS5 добавьте в начало socks5://
              </p>
            </div>
            <Button variant="secondary" disabled={testing || !configured} onClick={() => void test()}>
              {testing ? 'Проверяем…' : 'Проверить прокси'}
            </Button>
          </Card>
          <Card className="p-5">
            <div className="mb-1 font-medium">Площадки через этот прокси</div>
            <p className="mb-4 text-xs text-muted-foreground">
              Включите только те площадки, которым прокси нужен. Остальные зайдут напрямую.
            </p>
            <div className="space-y-2">
              {PLATFORMS.map((platform) => (
                <div key={platform.id} className="flex items-center justify-between rounded-xl border border-border px-3 py-2.5">
                  <div className="flex items-center gap-3">
                    <span style={{ color: platform.color }}>
                      <PlatformIcon id={platform.id} className="size-4" />
                    </span>
                    <span className="text-sm">{platform.shortName}</span>
                  </div>
                  <Switch
                    checked={state.platforms[platform.id].useProxy}
                    disabled={!configured}
                    onCheckedChange={(useProxy) => void window.api.setPlatformProxy(platform.id, useProxy)}
                  />
                </div>
              ))}
            </div>
          </Card>
        </div>
      </ScrollArea>
    </div>
  )
}
