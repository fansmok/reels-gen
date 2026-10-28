import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function fileName(path?: string): string {
  if (!path) return ''
  return path.split(/[/\\]/).pop() ?? path
}

export function formatDelay(ms: number): string {
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} с`
  const minutes = Math.round(seconds / 60)
  return `${minutes} мин`
}

export function formatDate(iso?: string): string {
  if (!iso) return 'сразу'
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}
