import { app } from 'electron'
import {
  appendFileSync,
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readSync,
  statSync
} from 'fs'
import { join } from 'path'

const RING_MAX = 200
const ring: string[] = []

export type WindowLogAction = 'opened' | 'closed' | 'ignored'

function logsDir(): string {
  const dir = join(app.getPath('userData'), 'logs')
  mkdirSync(dir, { recursive: true })
  return dir
}

export function uploadLogPath(): string {
  return join(logsDir(), 'upload.log')
}

function oneLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, 2000)
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

function writeLine(line: string): void {
  const full = oneLine(line)
  ring.push(full)
  if (ring.length > RING_MAX) ring.splice(0, ring.length - RING_MAX)
  console.log(`[upload] ${full}`)
  try {
    appendFileSync(uploadLogPath(), `${full}\n`, 'utf-8')
  } catch (error) {
    console.log(`[upload] не удалось записать лог: ${errorText(error)}`)
  }
}

function formatLine(platform: string, step: string, detail?: string): string {
  const iso = new Date().toISOString()
  const extra = detail ? ` | ${oneLine(detail)}` : ''
  return `${iso} [${platform}] ${step}${extra}`
}

/** Шаг загрузки: время ISO, площадка, шаг, необязательная деталь. */
export function uploadLog(platform: string, step: string, detail?: string): void {
  writeLine(formatLine(platform, step, detail))
}

export function uploadLogError(platform: string, step: string, error: unknown): void {
  writeLine(formatLine(platform, `ERROR ${step}`, errorText(error)))
}

export function uploadLogWindow(platform: string, url: string, action: WindowLogAction): void {
  writeLine(formatLine(platform, `window ${action}`, url || '(пусто)'))
}

export function peekUploadLog(maxLines = 80): string[] {
  if (ring.length >= maxLines) return ring.slice(-maxLines)
  const fromFile = readLogFileLines(Math.max(maxLines, RING_MAX))
  if (!fromFile.length) return ring.slice(-maxLines)
  const merged = fromFile.length >= ring.length ? fromFile : [...fromFile, ...ring]
  const unique = [...new Set(merged)]
  return unique.slice(-maxLines)
}

export function readUploadLog(maxLines = 80): string {
  return peekUploadLog(maxLines).join('\n')
}

/** Короткая выжимка последних строк площадки — для progress в UI. */
export function recentUploadLogHint(platform?: string, maxLines = 3): string {
  const lines = peekUploadLog(40)
  const filtered = platform ? lines.filter((line) => line.includes(`[${platform}]`)) : lines
  const picked = (filtered.length ? filtered : lines).slice(-maxLines)
  if (!picked.length) return ''
  return picked
    .map((line) => line.replace(/^\S+\s+\[[^\]]+\]\s*/, ''))
    .join(' · ')
    .slice(0, 280)
}

function readLogFileLines(maxLines: number): string[] {
  const file = uploadLogPath()
  if (!existsSync(file)) return []
  try {
    const stat = statSync(file)
    const maxBytes = 96_000
    const fd = openSync(file, 'r')
    try {
      const start = Math.max(0, stat.size - maxBytes)
      const length = stat.size - start
      const buf = Buffer.alloc(length)
      readSync(fd, buf, 0, length, start)
      const text = buf.toString('utf-8')
      const lines = text.split(/\r?\n/).filter(Boolean)
      return lines.slice(-maxLines)
    } finally {
      closeSync(fd)
    }
  } catch {
    return []
  }
}
