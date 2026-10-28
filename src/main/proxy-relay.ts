import { createConnection, createServer, type AddressInfo, type Server, type Socket } from 'net'
import { isIPv6 } from 'net'
import type { ProxyConfig } from '../shared/types'
import { isProxyConfigured, normalizeProxy } from '../shared/proxy'

function authHeader(username: string, password: string): Buffer | null {
  if (!username && !password) return null
  const token = Buffer.from(`${username}:${password}`).toString('base64')
  return Buffer.from(`Proxy-Authorization: Basic ${token}`)
}

function readHeaders(socket: Socket, initial: Buffer): Promise<{ head: Buffer; rest: Buffer }> {
  return new Promise((resolve, reject) => {
    let buf = initial
    const onData = (chunk: Buffer): void => {
      buf = Buffer.concat([buf, chunk])
      const idx = buf.indexOf('\r\n\r\n')
      if (idx === -1) return
      socket.off('data', onData)
      socket.off('error', onError)
      resolve({ head: buf.subarray(0, idx), rest: buf.subarray(idx + 4) })
    }
    const onError = (error: Error): void => {
      socket.off('data', onData)
      socket.off('error', onError)
      reject(error)
    }
    const idx = buf.indexOf('\r\n\r\n')
    if (idx !== -1) {
      resolve({ head: buf.subarray(0, idx), rest: buf.subarray(idx + 4) })
      return
    }
    socket.on('data', onData)
    socket.on('error', onError)
  })
}

function injectAuth(head: Buffer, auth: Buffer | null): Buffer {
  if (!auth || head.includes('Proxy-Authorization:')) return head
  return Buffer.concat([head, Buffer.from('\r\n'), auth])
}

function connectIPv4(host: string, port: number, timeoutMs: number): Promise<Socket> {
  return new Promise((resolve, reject) => {
    const socket = createConnection({ host, port, family: 4 })
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error(`прокси ${host}:${port} не отвечает`))
    }, timeoutMs)
    socket.once('connect', () => {
      clearTimeout(timer)
      socket.setNoDelay(true)
      resolve(socket)
    })
    socket.once('error', (error) => {
      clearTimeout(timer)
      reject(error)
    })
  })
}

function pipeSockets(a: Socket, b: Socket): void {
  const hangup = (): void => {
    a.destroy()
    b.destroy()
  }
  a.pipe(b)
  b.pipe(a)
  a.on('error', hangup)
  b.on('error', hangup)
  a.on('close', hangup)
  b.on('close', hangup)
}

export interface ProxyRelayHandle {
  localUrl: string
  localPort: number
  close: () => Promise<void>
}

export async function startProxyRelay(proxy: ProxyConfig): Promise<ProxyRelayHandle> {
  const normalized = normalizeProxy(proxy)
  if (!isProxyConfigured(normalized)) {
    throw new Error('Прокси не задан')
  }
  if (isIPv6(normalized.host)) {
    throw new Error('Нужен IPv4-прокси')
  }
  const upPort = Number(normalized.port)
  const auth = authHeader(normalized.username, normalized.password)

  const server: Server = createServer((client) => {
    client.once('data', (first) => {
      void (async () => {
        try {
          const { head, rest } = await readHeaders(client, first)
          const upstream = await connectIPv4(normalized.host, upPort, 20_000)
          const request = Buffer.concat([injectAuth(head, auth), Buffer.from('\r\n\r\n'), rest])
          if (head.toString('latin1').startsWith('CONNECT')) {
            upstream.write(request)
            const reply = await readHeaders(upstream, Buffer.alloc(0))
            const status = reply.head.toString('latin1').split('\r\n', 1)[0] ?? ''
            if (!status.includes('200')) {
              client.write(Buffer.concat([reply.head, Buffer.from('\r\n\r\n'), reply.rest]))
              client.end()
              upstream.destroy()
              return
            }
            client.write(Buffer.from('HTTP/1.1 200 Connection Established\r\n\r\n'))
            if (reply.rest.length) client.write(reply.rest)
            pipeSockets(client, upstream)
            return
          }
          upstream.write(request)
          pipeSockets(client, upstream)
        } catch {
          client.destroy()
        }
      })()
    })
    client.on('error', () => client.destroy())
  })

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => resolve())
  })
  const address = server.address() as AddressInfo
  return {
    localUrl: `http://127.0.0.1:${address.port}`,
    localPort: address.port,
    close: () =>
      new Promise((resolve) => {
        server.close(() => resolve())
        setTimeout(resolve, 400)
      })
  }
}
