import { createWriteStream } from 'fs'
import { mkdir, unlink } from 'fs/promises'
import https from 'https'
import net from 'net'
import { dirname } from 'path'
import type { ProxyConfig } from '../shared/types'
import { isProxyConfigured } from '../shared/proxy'
import { getPersisted } from './store'

export class TelegramApiError extends Error {
  constructor(
    message: string,
    readonly code: number,
    readonly retryAfter = 0
  ) {
    super(message)
  }
}

interface CallOptions {
  signal: AbortSignal
  timeoutMs: number
}

/** POST к Bot API. Если в программе включён прокси — через него: напрямую api.telegram.org часто не открывается. */
export async function telegramCall(token: string, method: string, payload: object, options: CallOptions): Promise<unknown> {
  const body = JSON.stringify(payload)
  const path = `/bot${token}/${method}`
  const linked = linkTimeout(options.signal, options.timeoutMs)
  try {
    const proxy = getPersisted().proxy
    const text =
      proxy.enabled && isProxyConfigured(proxy)
        ? await postTunneled(path, body, proxy, linked.signal)
        : await postDirect(path, body, linked.signal)
    return parseApi(text, token)
  } catch (error) {
    if (options.signal.aborted) throw error
    if (error instanceof TelegramApiError) throw error
    throw new Error(humanNetError(error, token))
  } finally {
    linked.done()
  }
}

/** Скачать файл бота: https://api.telegram.org/file/bot<token>/<file_path>. Идёт тем же прокси, что и методы API. */
export async function downloadTelegramFile(token: string, filePath: string, dest: string, options: CallOptions): Promise<void> {
  const encoded = filePath
    .split('/')
    .map((part) => encodeURIComponent(part))
    .join('/')
  const path = `/file/bot${token}/${encoded}`
  const linked = linkTimeout(options.signal, options.timeoutMs)
  await mkdir(dirname(dest), { recursive: true })
  try {
    const proxy = getPersisted().proxy
    const socket = proxy.enabled && isProxyConfigured(proxy) ? (proxy.type === 'socks5' ? await socks5Tunnel(proxy, linked.signal) : await httpTunnel(proxy, linked.signal)) : undefined
    try {
      await getToFile(path, dest, linked.signal, socket)
    } catch (error) {
      socket?.destroy()
      throw error
    }
  } catch (error) {
    if (options.signal.aborted) throw error
    throw new Error(humanNetError(error, token))
  } finally {
    linked.done()
  }
}

function parseApi(text: string, token: string): unknown {
  let data: { ok?: boolean; description?: string; error_code?: number; parameters?: { retry_after?: number }; result?: unknown }
  try {
    data = JSON.parse(text) as typeof data
  } catch {
    throw new Error('Telegram ответил не JSON')
  }
  if (!data.ok) {
    const code = data.error_code || 0
    const retry = Math.max(0, Number(data.parameters?.retry_after) || 0)
    throw new TelegramApiError(stripToken(data.description || 'ошибка Telegram', token), code, retry)
  }
  return data.result
}

function humanNetError(error: unknown, token: string): string {
  if (error instanceof Error && error.name === 'AbortError') return 'Telegram не ответил вовремя'
  const code = (error as NodeJS.ErrnoException)?.code
  const raw = stripToken(error instanceof Error ? error.message : String(error), token)
  if (code === 'ETIMEDOUT' || code === 'ECONNRESET' || code === 'ECONNREFUSED' || code === 'ENOTFOUND' || raw === 'Telegram не ответил вовремя') {
    const proxy = getPersisted().proxy
    if (proxy.enabled && isProxyConfigured(proxy)) return `Нет связи с Telegram через прокси: ${raw}`
    return 'Нет связи с Telegram. Включите прокси в программе: с этой сети api.telegram.org часто не открывается.'
  }
  return raw
}

function stripToken(text: string, token: string): string {
  return token ? text.split(token).join('…') : text
}

function linkTimeout(outer: AbortSignal, timeoutMs: number): { signal: AbortSignal; done: () => void } {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  const abort = (): void => ctrl.abort()
  if (outer.aborted) ctrl.abort()
  else outer.addEventListener('abort', abort, { once: true })
  return {
    signal: ctrl.signal,
    done() {
      clearTimeout(timer)
      outer.removeEventListener('abort', abort)
    }
  }
}

function postDirect(path: string, body: string, signal: AbortSignal): Promise<string> {
  return postHttps(path, body, signal)
}

async function postTunneled(path: string, body: string, proxy: ProxyConfig, signal: AbortSignal): Promise<string> {
  const socket = proxy.type === 'socks5' ? await socks5Tunnel(proxy, signal) : await httpTunnel(proxy, signal)
  try {
    return await postHttps(path, body, signal, socket)
  } catch (error) {
    socket.destroy()
    throw error
  }
}

function getToFile(path: string, dest: string, signal: AbortSignal, socket?: net.Socket): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(dest)
    const fail = (error: Error): void => {
      file.destroy()
      socket?.destroy()
      void unlink(dest).catch(() => undefined)
      reject(error)
    }
    const options: https.RequestOptions & { socket?: net.Socket } = {
      host: 'api.telegram.org',
      servername: 'api.telegram.org',
      path,
      method: 'GET',
      headers: { host: 'api.telegram.org', connection: 'close' },
      signal
    }
    if (socket) {
      options.socket = socket
      options.agent = false
    }
    const req = https.request(options, (res) => {
      if ((res.statusCode || 0) !== 200) {
        res.resume()
        res.on('end', () => {
          socket?.destroy()
          file.destroy()
          void unlink(dest).catch(() => undefined)
          reject(new Error(`файл Telegram: HTTP ${res.statusCode || 0}`))
        })
        return
      }
      res.pipe(file)
      file.on('finish', () => {
        file.close(() => {
          socket?.destroy()
          resolve()
        })
      })
      res.on('error', fail)
      file.on('error', fail)
    })
    req.on('error', fail)
    req.end()
  })
}

function postHttps(path: string, body: string, signal: AbortSignal, socket?: net.Socket): Promise<string> {
  return new Promise((resolve, reject) => {
    const options: https.RequestOptions & { socket?: net.Socket } = {
      host: 'api.telegram.org',
      servername: 'api.telegram.org',
      path,
      method: 'POST',
      headers: {
        host: 'api.telegram.org',
        'content-type': 'application/json',
        'content-length': Buffer.byteLength(body),
        connection: 'close'
      },
      signal
    }
    if (socket) {
      options.socket = socket
      options.agent = false
    }
    const req = https.request(
      options,
      (res) => {
        const chunks: Buffer[] = []
        res.on('data', (chunk: Buffer) => chunks.push(chunk))
        res.on('end', () => {
          socket?.destroy()
          resolve(Buffer.concat(chunks).toString('utf8'))
        })
        res.on('error', (error) => {
          socket?.destroy()
          reject(error)
        })
      }
    )
    req.on('error', (error) => {
      socket?.destroy()
      reject(error)
    })
    req.end(body)
  })
}

function httpTunnel(proxy: ProxyConfig, signal: AbortSignal): Promise<net.Socket> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error('прервано'))
      return
    }
    const socket = net.connect({ host: proxy.host, port: Number(proxy.port), family: 4 })
    const fail = (error: Error): void => {
      socket.destroy()
      reject(error)
    }
    const onAbort = (): void => fail(new Error('прервано'))
    signal.addEventListener('abort', onAbort, { once: true })
    socket.setTimeout(20_000, () => fail(new Error('прокси не отвечает')))
    socket.once('error', fail)
    socket.once('connect', () => {
      socket.setNoDelay(true)
      const lines = ['CONNECT api.telegram.org:443 HTTP/1.1', 'Host: api.telegram.org:443']
      if (proxy.username || proxy.password) {
        lines.push(`Proxy-Authorization: Basic ${Buffer.from(`${proxy.username}:${proxy.password}`).toString('base64')}`)
      }
      socket.write(`${lines.join('\r\n')}\r\n\r\n`)
      void readHttpHead(socket)
        .then(({ status, rest }) => {
          socket.off('error', fail)
          signal.removeEventListener('abort', onAbort)
          socket.setTimeout(0)
          if (!status.includes(' 200')) {
            socket.destroy()
            reject(new Error(status.includes('407') ? 'прокси не принял логин или пароль' : `прокси ответил: ${status}`))
            return
          }
          socket.pause()
          if (rest.length) socket.unshift(rest)
          resolve(socket)
        })
        .catch(fail)
    })
  })
}

function readHttpHead(socket: net.Socket): Promise<{ status: string; rest: Buffer }> {
  return new Promise((resolve, reject) => {
    let buf = Buffer.alloc(0)
    const onData = (chunk: Buffer): void => {
      buf = Buffer.concat([buf, chunk])
      const idx = buf.indexOf('\r\n\r\n')
      if (idx === -1) return
      cleanup()
      const head = buf.subarray(0, idx).toString('latin1')
      resolve({ status: head.split('\r\n', 1)[0] ?? '', rest: buf.subarray(idx + 4) })
    }
    const onError = (error: Error): void => {
      cleanup()
      reject(error)
    }
    const cleanup = (): void => {
      socket.off('data', onData)
      socket.off('error', onError)
    }
    socket.on('data', onData)
    socket.on('error', onError)
  })
}

function socks5Tunnel(proxy: ProxyConfig, signal: AbortSignal): Promise<net.Socket> {
  return new Promise((resolve, reject) => {
    const socket = net.connect({ host: proxy.host, port: Number(proxy.port) })
    const fail = (error: Error): void => {
      socket.destroy()
      reject(error)
    }
    if (signal.aborted) {
      fail(new Error('прервано'))
      return
    }
    const onAbort = (): void => fail(new Error('прервано'))
    signal.addEventListener('abort', onAbort, { once: true })
    socket.setTimeout(20_000, () => fail(new Error('прокси не отвечает')))
    socket.once('error', fail)
    socket.once('connect', () => {
      void handshake()
        .then(() => {
          socket.off('error', fail)
          signal.removeEventListener('abort', onAbort)
          socket.setTimeout(0)
          resolve(socket)
        })
        .catch(fail)
    })

    async function handshake(): Promise<void> {
      const user = Buffer.from(proxy.username || '', 'utf8')
      const pass = Buffer.from(proxy.password || '', 'utf8')
      const useAuth = user.length > 0 || pass.length > 0
      const reader = createReader(socket, signal)
      socket.write(Buffer.from([0x05, 0x01, useAuth ? 0x02 : 0x00]))
      const greet = await reader.read(2)
      if (greet[0] !== 0x05 || greet[1] === 0xff) throw new Error('прокси SOCKS5 отклонил подключение')
      if (greet[1] === 0x02) {
        socket.write(Buffer.concat([Buffer.from([0x01, user.length]), user, Buffer.from([pass.length]), pass]))
        const auth = await reader.read(2)
        if (auth[1] !== 0x00) throw new Error('прокси не принял логин или пароль')
      }
      const host = Buffer.from('api.telegram.org')
      socket.write(Buffer.concat([Buffer.from([0x05, 0x01, 0x00, 0x03, host.length]), host, Buffer.from([0x01, 0xbb])]))
      const head = await reader.read(4)
      if (head[1] !== 0x00) throw new Error('прокси не открыл соединение с Telegram')
      const atyp = head[3]
      if (atyp === 0x01) await reader.read(6)
      else if (atyp === 0x04) await reader.read(18)
      else if (atyp === 0x03) {
        const len = (await reader.read(1))[0]
        await reader.read(len + 2)
      }
      const extra = reader.rest()
      reader.stop()
      socket.pause()
      if (extra.length) socket.unshift(extra)
    }
  })
}

function createReader(socket: net.Socket, signal: AbortSignal): {
  read: (n: number) => Promise<Buffer>
  rest: () => Buffer
  stop: () => void
} {
  let buf = Buffer.alloc(0)
  let waiter: ((error?: Error) => void) | null = null
  const onData = (chunk: Buffer): void => {
    buf = Buffer.concat([buf, chunk])
    waiter?.()
  }
  const onError = (error: Error): void => waiter?.(error)
  const onAbort = (): void => waiter?.(new Error('прервано'))
  socket.on('data', onData)
  socket.on('error', onError)
  signal.addEventListener('abort', onAbort, { once: true })
  return {
    async read(n: number): Promise<Buffer> {
      while (buf.length < n) {
        await new Promise<void>((resolve, reject) => {
          waiter = (error) => (error ? reject(error) : resolve())
        })
      }
      const out = buf.subarray(0, n)
      buf = buf.subarray(n)
      return out
    },
    rest: () => buf,
    stop() {
      socket.pause()
      socket.off('data', onData)
      socket.off('error', onError)
      signal.removeEventListener('abort', onAbort)
      waiter = null
    }
  }
}
