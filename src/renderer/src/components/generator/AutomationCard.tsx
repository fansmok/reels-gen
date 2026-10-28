import { Bot, Play, Square } from 'lucide-react'
import { useState, type JSX } from 'react'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Switch } from '@renderer/components/ui/switch'
import { cn, formatDate } from '@renderer/lib/utils'
import type { AutoMode, GeneratorAutomation } from '@shared/generator'
import { Field, NativeSelect, Row, type StepProps } from './common'

export function AutomationCard({ s, set, state, run }: StepProps): JSX.Element {
  const auto = s.auto
  const status = state.automation
  const [starting, setStarting] = useState(false)
  const patch = (p: Partial<GeneratorAutomation>): void => set({ auto: { ...auto, ...p } })

  async function runNow(): Promise<void> {
    setStarting(true)
    try {
      await window.api.automationRunNow()
    } catch {
      /* тост из main */
    } finally {
      setStarting(false)
    }
  }

  return (
    <Card className={cn('space-y-4 p-5', auto.enabled && 'border-violet-200 bg-violet-50/30')}>
      <Row
        title="Автоматизация"
        hint="По расписанию: новый верхний ролик → генерация → тексты Kie → очередь → заливка во все отмеченные направления из «Аккаунтов»"
      >
        <Switch checked={auto.enabled} onCheckedChange={(v) => patch({ enabled: v })} />
      </Row>

      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Как часто">
          <NativeSelect value={auto.mode} onChange={(e) => patch({ mode: e.target.value as AutoMode })}>
            <option value="daily">Каждый день в указанное время</option>
            <option value="interval">Каждые N часов</option>
            <option value="days">Раз в N дней</option>
          </NativeSelect>
        </Field>
        {auto.mode === 'interval' && (
          <Field label="Интервал, часов">
            <Input type="number" min={1} max={168} value={auto.intervalH} onChange={(e) => patch({ intervalH: Math.max(1, Math.min(168, Number(e.target.value) || 1)) })} />
          </Field>
        )}
        {auto.mode === 'daily' && (
          <Field label="Время">
            <Input type="time" value={auto.time} onChange={(e) => patch({ time: e.target.value || '10:00' })} />
          </Field>
        )}
        {auto.mode === 'days' && (
          <>
            <Field label="Каждые N дней">
              <Input type="number" min={1} max={60} value={auto.days} onChange={(e) => patch({ days: Math.max(1, Math.min(60, Number(e.target.value) || 1)) })} />
            </Field>
            <Field label="Время">
              <Input type="time" value={auto.daysTime} onChange={(e) => patch({ daysTime: e.target.value || '10:00' })} />
            </Field>
          </>
        )}
      </div>

      <label className="flex items-center gap-2 text-xs">
        <Switch checked={auto.onlyNew} onCheckedChange={(v) => patch({ onlyNew: v })} />
        только если в папке 1 появился новый верхний ролик (или сменилась ссылка)
      </label>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-white px-4 py-3">
        <div className="space-y-0.5 text-xs">
          <div className="flex items-center gap-2 font-medium">
            <Bot className={cn('size-4', status.cycleRunning ? 'animate-pulse text-violet-600' : auto.enabled ? 'text-emerald-600' : 'text-muted-foreground')} />
            {status.cycleRunning ? 'Цикл идёт' : auto.enabled ? 'Включена' : 'Выключена'}
          </div>
          <div className="text-muted-foreground">
            {auto.enabled && status.nextRun ? `следующий запуск: ${formatDate(status.nextRun)}` : 'следующий запуск: —'}
            {status.lastRun ? ` · последний: ${formatDate(status.lastRun)}` : ''}
            {status.lastResult ? ` · ${status.lastResult}` : ''}
          </div>
          {status.lastError && <div className="text-destructive">{status.lastError}</div>}
          {!status.lastError && status.lastMessage && <div className="text-muted-foreground">{status.lastMessage}</div>}
        </div>
        <div className="flex gap-2">
          {status.cycleRunning || run.running ? (
            <Button size="sm" variant="destructive" onClick={() => void window.api.automationStop()}>
              <Square className="size-3.5" /> Остановить цикл
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled={starting || !state.engine.ok} onClick={() => void runNow()}>
              <Play className="size-3.5" /> Запустить цикл сейчас
            </Button>
          )}
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Пропущенный запуск (программа была закрыта) выполняется один раз при старте. Пока идёт цикл, новый не стартует. Выключение
        останавливает генерацию и заливку, запущенную циклом.
      </p>
    </Card>
  )
}
