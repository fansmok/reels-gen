const { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } = require('fs')
const { join } = require('path')

// Chrome и ffmpeg Remotion кладёт рядом с package.json. Кириллица в пути проекта обрывает распаковку.
const browserHome = join(process.env.LOCALAPPDATA || process.env.TEMP || '.', 'reels-caption-browser')
mkdirSync(browserHome, { recursive: true })
writeFileSync(join(browserHome, 'package.json'), '{"private":true}\n')
process.chdir(browserHome)

const modules = process.env.REELS_NODE_MODULES
if (modules) module.paths.unshift(modules)

const { ensureBrowser, renderMedia, selectComposition } = require('@remotion/renderer')

function newestChrome() {
  const own = join(browserHome, 'node_modules', '.remotion', 'chrome-headless-shell', 'win64', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')
  if (existsSync(own)) return own
  const root = join(process.env.LOCALAPPDATA || '', 'ms-playwright')
  if (!existsSync(root)) return null
  const hits = []
  for (const name of readdirSync(root)) {
    const exe = join(root, name, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')
    if (existsSync(exe)) hits.push(exe)
  }
  return hits.sort().at(-1) || null
}

async function main() {
  const propsPath = process.argv[2]
  const outPath = process.argv[3]
  const bundle = process.argv[4]
  if (!propsPath || !outPath || !bundle) {
    throw new Error('Нужны пути: props, выходной webm, папка сборки')
  }
  const inputProps = JSON.parse(readFileSync(propsPath, 'utf8').replace(/^\uFEFF/, ''))
  const browserExecutable = newestChrome()
  console.log('Субтитры: готовлю анимацию')
  await ensureBrowser(browserExecutable ? { browserExecutable } : undefined)
  const composition = await selectComposition({
    serveUrl: bundle,
    id: 'ReelCaptions',
    inputProps,
    browserExecutable: browserExecutable || null
  })
  let last = -1
  await renderMedia({
    composition,
    serveUrl: bundle,
    codec: 'vp8',
    imageFormat: 'png',
    pixelFormat: 'yuva420p',
    outputLocation: outPath,
    inputProps,
    browserExecutable: browserExecutable || null,
    chromiumOptions: { gl: 'swiftshader' },
    onProgress: ({ progress }) => {
      const pct = Math.round(progress * 100)
      if (pct >= last + 15) {
        last = pct
        console.log(`Субтитры: отрисовка ${pct}%`)
      }
    }
  })
  console.log('Субтитры: анимация готова')
}

main().catch((error) => {
  const text = error && error.stack ? error.stack : String(error)
  console.error(text)
  process.exit(1)
})
