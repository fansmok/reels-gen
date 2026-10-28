import { net, protocol } from 'electron'
import { pathToFileURL } from 'url'

export const REEL_SCHEME = 'reel'

export function registerReelScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: REEL_SCHEME,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        stream: true,
        bypassCSP: true,
        corsEnabled: true
      }
    }
  ])
}

export function handleReelProtocol(): void {
  protocol.handle(REEL_SCHEME, (request) => {
    try {
      const url = new URL(request.url)
      const filePath = url.searchParams.get('p')
      if (!filePath) return new Response('Not found', { status: 404 })
      return net.fetch(pathToFileURL(filePath).href)
    } catch {
      return new Response('Not found', { status: 404 })
    }
  })
}

export function toReelUrl(filePath: string): string {
  return `${REEL_SCHEME}://local/?p=${encodeURIComponent(filePath)}`
}
