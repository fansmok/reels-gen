import { Bot, Link2Off } from 'lucide-react'
import { useEffect, useState, type JSX } from 'react'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Switch } from '@renderer/components/ui/switch'
import { cn } from '@renderer/lib/utils'
import { TG_EXTRA_UPLOADERS, telegramArmed, type TelegramTrigger } from '@shared/generator'
import { isProxyConfigured } from '@shared/proxy'
import { Field, Row, type StepProps } from './common'

export function TelegramCard({ s, set, state }: StepProps): JSX.Element {
  const tg = s.tg
  const live = state.telegram
  const armed = telegramArmed(s)
  const on = armed && tg.enabled
  const proxyOn = state.proxy.enabled && isProxyConfigured(state.proxy)
  const [tokenDraft, setTokenDraft] = useState(tg.token)
  const hint = s.sourceMode === 'telegram'
    ? 'Сначала боту присылают верхний рилс: ссылку или видео. Потом нижний: ссылку, видео или кружок. Дальше склейка и заливка по остальным настройкам.'
    : s.topMode === 'telegram'
      ? 'Бот принимает ссылку или видео — это верхний ролик. Низ берётся из выбранного пункта ниже.'
      : 'Заработает, когда у верхнего или нижнего ролика выбрана «Загрузка через Telegram».'

  useEffect(() => {
    setTokenDraft(tg.token)
  }, [tg.token])

  const commit = (patch: Partial<TelegramTrigger>): void => {
    const token = (patch.token ?? tokenDraft).trim()
    set({ tg: { ...tg, ...patch, token } })
  }

  return (
    <Card className={cn('space-y-4 p-5', on && 'border-violet-200 bg-violet-50/30')}>
      <Row title="Загрузка через Telegram" hint={hint}>
        <Switch checked={on} disabled={!armed} onCheckedChange={(v) => commit({ enabled: v })} />
      </Row>

      <Field label="Токен бота" hint="Уже вписан этот бот. Меняйте поле, только если подключаете другого.">
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={tokenDraft}
          onChange={(e) => setTokenDraft(e.target.value)}
          onBlur={() => {
            if (tokenDraft.trim() !== tg.token.trim()) commit({ token: tokenDraft })
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur()
          }}
        />
      </Field>

      <div className="space-y-1 rounded-xl border border-border bg-white px-4 py-3 text-xs">
        <div className="flex items-center gap-2 font-medium">
          <Bot
            className={cn(
              'size-4',
              live.listening ? 'text-emerald-600' : on && !live.lastError ? 'animate-pulse text-violet-600' : 'text-muted-foreground'
            )}
          />
          {live.listening && live.username ? `Слушает @${live.username}` : on ? (live.lastError ? 'Нет связи' : 'Подключаюсь…') : armed ? 'Выключен' : 'Ждёт выбор в «Источнике»'}
        </div>
        <div className="text-muted-foreground">
          {live.chatId ? `Чат закреплён: ${live.chatId}` : 'Чат закрепится за тем, кто первым напишет боту в личку.'}
          {live.queued ? ` · в очереди: ${live.queued}` : ''}
          {TG_EXTRA_UPLOADERS.length ? ` · ещё заливает: ${TG_EXTRA_UPLOADERS.join(', ')}` : ''}
        </div>
        {live.lastUrl && <div className="truncate text-muted-foreground">Последняя ссылка: {live.lastUrl}</div>}
        {live.lastText && <div className="text-muted-foreground">{live.lastText}</div>}
        {live.lastError && <div className="text-destructive">{live.lastError}</div>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          {proxyOn
            ? 'Запросы к Telegram идут через прокси из раздела «Прокси».'
            : 'Прокси выключен. С этой сети Telegram часто не открывается — включите его в разделе «Прокси».'}
        </p>
        <Button size="sm" variant="outline" disabled={!live.chatId} onClick={() => void window.api.telegramUnbind()}>
          <Link2Off className="size-3.5" /> Отвязать чат
        </Button>
      </div>
    </Card>
  )
}
