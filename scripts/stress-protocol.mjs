const ENDPOINT = 'http://127.0.0.1:7923/ingest/e5140252-92da-48a7-9b69-27d5cd88873d'

function log(hypothesisId, location, message, data) {
  return fetch(ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'dbdf20' },
    body: JSON.stringify({
      sessionId: 'dbdf20',
      runId: 'stress-node',
      hypothesisId,
      location,
      message,
      data,
      timestamp: Date.now()
    })
  }).catch(() => undefined)
}

function toReelUrl(filePath) {
  return `reel://local/?p=${encodeURIComponent(filePath)}`
}

const paths = [
  'C:\\Users\\faans\\Desktop\\РИЛС-ЗАГРУЗКА\\video.mp4',
  'C:/Users/faans/Desktop/РИЛС-ЗАГРУЗКА/clip with spaces.mp4',
  'C:\\temp\\a#hash.mp4',
  'C:\\temp\\q?query.mp4'
]

async function main() {
  for (const filePath of paths) {
    const href = toReelUrl(filePath)
    try {
      const parsed = new URL(href).searchParams.get('p')
      await log('B', 'scripts/stress-protocol.mjs', 'roundtrip', { filePath, href, parsed, ok: parsed === filePath })
    } catch (error) {
      await log('B', 'scripts/stress-protocol.mjs', 'parse-error', { filePath, href, message: String(error) })
    }
  }
}

main()
