import type { ProxyConfig } from './types'

export function emptyProxy(): ProxyConfig {
  return {
    enabled: false,
    type: 'http',
    host: '',
    port: '',
    username: '',
    password: ''
  }
}

export function formatProxyLine(proxy: ProxyConfig): string {
  const host = proxy.host.trim()
  const port = proxy.port.trim()
  if (!host) return ''
  const auth =
    proxy.username || proxy.password
      ? `:${proxy.username}:${proxy.password}`
      : ''
  const body = port ? `${host}:${port}${auth}` : host
  return proxy.type === 'socks5' ? `socks5://${body}` : body
}

export function parseProxyLine(raw: string): ProxyConfig {
  const empty = emptyProxy()
  let value = raw.trim()
  if (!value) return empty

  let type: ProxyConfig['type'] = 'http'
  if (/^socks5:\/\//i.test(value)) {
    type = 'socks5'
    value = value.replace(/^socks5:\/\//i, '')
  } else if (/^https?:\/\//i.test(value)) {
    type = 'http'
    value = value.replace(/^https?:\/\//i, '')
  }

  const at = value.lastIndexOf('@')
  if (at !== -1) {
    const userinfo = value.slice(0, at)
    const hostport = value.slice(at + 1)
    const colon = userinfo.indexOf(':')
    const username = colon === -1 ? userinfo : userinfo.slice(0, colon)
    const password = colon === -1 ? '' : userinfo.slice(colon + 1)
    const [host, port = ''] = splitHostPort(hostport)
    return finish(type, host, port, username, password)
  }

  const parts = value.split(':')
  if (parts.length >= 4) {
    const [host, port, username, ...rest] = parts
    return finish(type, host, port, username, rest.join(':'))
  }
  if (parts.length === 3) {
    const [host, port, username] = parts
    return finish(type, host, port, username, '')
  }
  if (parts.length === 2) {
    return finish(type, parts[0], parts[1], '', '')
  }
  return empty
}

export function normalizeProxy(proxy: ProxyConfig): ProxyConfig {
  const line = formatProxyLine(proxy)
  return parseProxyLine(line)
}

export function isProxyConfigured(proxy: ProxyConfig): boolean {
  const normalized = normalizeProxy(proxy)
  return Boolean(normalized.host && normalized.port)
}

function splitHostPort(value: string): [string, string] {
  const idx = value.lastIndexOf(':')
  if (idx === -1) return [value, '']
  return [value.slice(0, idx), value.slice(idx + 1)]
}

function finish(
  type: ProxyConfig['type'],
  host: string,
  port: string,
  username: string,
  password: string
): ProxyConfig {
  const cleanHost = host.trim()
  const cleanPort = port.trim()
  return {
    enabled: Boolean(cleanHost && cleanPort),
    type,
    host: cleanHost,
    port: cleanPort,
    username: username.trim(),
    password
  }
}
