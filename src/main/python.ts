import { execFileSync, spawn, type ChildProcessWithoutNullStreams } from 'child_process'
import { app, screen } from 'electron'
import { existsSync } from 'fs'
import { join } from 'path'
import type { EngineCheck, EnginePaths } from '../shared/types'
import { getPersisted } from './store'

export type BridgeMessage =
  | { type: 'log'; message: string }
  | { type: 'ready'; [key: string]: unknown }
  | { type: 'result'; data: unknown }
  | { type: 'error'; message: string }
  | { type: 'closed'; [key: string]: unknown }
  | { type: 'progress'; value: number; [key: string]: unknown }
  | { type: string; [key: string]: unknown }

export interface BridgeHandlers {
  onMessage?: (msg: BridgeMessage) => void
  onLog?: (line: string) => void
}

export function enginePaths(): EnginePaths {
  return getPersisted().enginePaths
}

/** Ищем системный Python, если в настройках путь пустой или битый. */
export function resolvePythonExe(configured: string): string {
  const raw = configured.trim()
  if (raw && existsSync(raw)) return raw
  const local = process.env.LOCALAPPDATA || ''
  const candidates =
    process.platform === 'win32'
      ? [
          join(local, 'Programs', 'Python', 'Python314', 'python.exe'),
          join(local, 'Programs', 'Python', 'Python313', 'python.exe'),
          join(local, 'Programs', 'Python', 'Python312', 'python.exe'),
          join(local, 'Programs', 'Python', 'Python311', 'python.exe'),
          'C:\\Python312\\python.exe',
          'C:\\Python311\\python.exe'
        ]
      : ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3']
  for (const path of candidates) {
    if (path && existsSync(path)) return path
  }
  try {
    if (process.platform === 'win32') {
      const out = execFileSync('py', ['-3', '-c', 'import sys; print(sys.executable)'], {
        encoding: 'utf8',
        windowsHide: true
      })
        .trim()
        .split(/\r?\n/)
        .pop()
      if (out && existsSync(out)) return out
    }
  } catch {
    /* ignore */
  }
  try {
    const cmd = process.platform === 'win32' ? 'where' : 'which'
    const name = process.platform === 'win32' ? 'python' : 'python3'
    const out = execFileSync(cmd, [name], { encoding: 'utf8', windowsHide: true })
      .trim()
      .split(/\r?\n/)[0]
      ?.trim()
    if (out && existsSync(out)) return out
  } catch {
    /* ignore */
  }
  return raw || (process.platform === 'win32' ? 'python' : 'python3')
}

/** Папка со скриптами-мостами: в dev — `<repo>/python`, в сборке — `resources/python`. */
export function bridgeDir(): string {
  return app.isPackaged ? join(process.resourcesPath, 'python') : join(app.getAppPath(), 'python')
}

export function bridgeScript(name: string): string {
  return join(bridgeDir(), name)
}

/** Размер рабочей области только на Mac. На Windows мост считает экран через WinAPI. */
function macScreenEnv(): Record<string, string> {
  if (process.platform !== 'darwin') return {}
  try {
    const display = screen.getPrimaryDisplay()
    const width = Math.max(800, display.workAreaSize.width)
    const height = Math.max(640, display.workAreaSize.height)
    const scale = Math.round((display.scaleFactor || 1) * 100)
    return {
      REELS_SCREEN_CSS: `${width}x${height}`,
      REELS_SCREEN_SCALE: String(scale)
    }
  } catch {
    return {}
  }
}

export function bridgeEnv(): NodeJS.ProcessEnv {
  const paths = enginePaths()
  return {
    ...process.env,
    ...macScreenEnv(),
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
    REELS_TG_ROOT: paths.tgRoot,
    REELS_VK_BOT: paths.vkBot,
    REELS_YDA_ROOT: paths.ydaRoot,
    REELS_YT_COOKIES: paths.ytCookies,
    ...captionRenderEnv()
  }
}

/** Сборка Remotion и скрипт, которым Python рисует анимированные субтитры. */
function captionRenderEnv(): Record<string, string> {
  const root = app.isPackaged ? process.resourcesPath : app.getAppPath()
  const modules = app.isPackaged
    ? join(process.resourcesPath, 'app.asar.unpacked', 'node_modules')
    : join(app.getAppPath(), 'node_modules')
  return {
    REELS_CAPTION_SCRIPT: join(root, 'captions', 'render.cjs'),
    REELS_CAPTION_BUNDLE: join(root, 'captions-bundle'),
    REELS_ELECTRON_EXEC: process.execPath,
    REELS_NODE_MODULES: modules
  }
}

/** Быстрая проверка путей без запуска Python. Для склейки нужны Python + reels_gen. */
export function quickEngineCheck(): EngineCheck {
  const paths = enginePaths()
  const problems: string[] = []
  const python = resolvePythonExe(paths.pythonExe)
  if (!existsSync(python) && python.includes('\\')) problems.push(`Не найден Python: ${python}`)
  if (!existsSync(paths.tgRoot)) problems.push(`Не найдена папка движка: ${paths.tgRoot}`)
  if (!existsSync(join(paths.tgRoot, 'reels_gen'))) problems.push(`Нет reels_gen в ${paths.tgRoot}`)
  if (!existsSync(bridgeScript('yt_bridge.py'))) problems.push(`Нет скрипта моста: ${bridgeScript('yt_bridge.py')}`)
  return { ok: problems.length === 0, problems }
}

function parseLine(line: string): BridgeMessage | null {
  const text = line.trim()
  if (!text.startsWith('{') || !text.endsWith('}')) return null
  try {
    const parsed = JSON.parse(text) as BridgeMessage
    return parsed && typeof parsed === 'object' && typeof parsed.type === 'string' ? parsed : null
  } catch {
    return null
  }
}

export function spawnBridge(script: string, args: string[], handlers: BridgeHandlers = {}): ChildProcessWithoutNullStreams {
  const quick = quickEngineCheck()
  if (!quick.ok) throw new Error(quick.problems[0])
  const paths = enginePaths()
  const python = resolvePythonExe(paths.pythonExe)
  const child = spawn(python, ['-u', bridgeScript(script), ...args], {
    cwd: bridgeDir(),
    env: bridgeEnv(),
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe']
  })
  let buffer = ''
  const handle = (chunk: Buffer | string): void => {
    buffer += chunk.toString()
    let idx = buffer.indexOf('\n')
    while (idx >= 0) {
      const line = buffer.slice(0, idx).replace(/\r$/, '')
      buffer = buffer.slice(idx + 1)
      if (line.trim()) {
        const msg = parseLine(line)
        if (msg) {
          if (msg.type === 'log') handlers.onLog?.(String((msg as { message: string }).message))
          handlers.onMessage?.(msg)
        } else {
          handlers.onLog?.(line)
        }
      }
      idx = buffer.indexOf('\n')
    }
  }
  child.stdout.on('data', handle)
  child.stderr.on('data', (chunk: Buffer) => {
    for (const line of chunk.toString().split(/\r?\n/)) {
      if (line.trim()) handlers.onLog?.(line)
    }
  })
  return child
}

/** Запускает мост, ждёт `result` и завершения процесса. */
export function runBridge<T>(
  script: string,
  args: string[],
  options: { timeoutMs?: number; onLog?: (line: string) => void } = {}
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false
    let resultData: T | undefined
    let hasResult = false
    let errorMessage = ''
    const lastLogs: string[] = []
    let child: ChildProcessWithoutNullStreams
    try {
      child = spawnBridge(script, args, {
        onLog: (line) => {
          lastLogs.push(line)
          if (lastLogs.length > 20) lastLogs.shift()
          options.onLog?.(line)
        },
        onMessage: (msg) => {
          if (msg.type === 'result') {
            resultData = (msg as { data: T }).data
            hasResult = true
          } else if (msg.type === 'error') {
            errorMessage = String((msg as { message: string }).message)
          }
        }
      })
    } catch (error) {
      reject(error)
      return
    }
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      child.kill()
      reject(new Error(`Python не ответил за ${Math.round((options.timeoutMs ?? 120_000) / 1000)} с`))
    }, options.timeoutMs ?? 120_000)
    child.on('error', (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(error)
    })
    child.on('close', (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (hasResult) resolve(resultData as T)
      else reject(new Error(errorMessage || lastLogs.slice(-3).join(' | ') || `Python завершился с кодом ${code}`))
    })
  })
}

/** Полная проверка движка через Python (ffmpeg, Chrome, профили). */
export async function checkEngine(): Promise<EngineCheck> {
  const quick = quickEngineCheck()
  if (!quick.ok) return quick
  try {
    const data = await runBridge<EngineCheck & { problems: string[] }>('yt_bridge.py', ['check'], { timeoutMs: 60_000 })
    return { ...data, ok: data.problems.length === 0 }
  } catch (error) {
    return { ok: false, problems: [error instanceof Error ? error.message : String(error)] }
  }
}
