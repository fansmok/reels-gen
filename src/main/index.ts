import { app, shell, BrowserWindow, nativeTheme } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import { handleReelProtocol, registerReelScheme } from './protocol'
import { closeAllBrowsers } from './browser'
import { initRuntime, registerIpc } from './ipc'
import { closeAllYoutubeProfiles } from './yt-plain'
import { cancelGenerator } from './generator'
import { shutdownAutomation } from './automation'
import { shutdownTelegram, startTelegram } from './telegram'

registerReelScheme()
nativeTheme.themeSource = 'light'

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1100,
    minHeight: 740,
    show: false,
    autoHideMenuBar: true,
    title: 'Рилс Загрузка',
    backgroundColor: '#f5f6fa',
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(async () => {
  electronApp.setAppUserModelId('com.reelsloader.app')
  handleReelProtocol()
  registerIpc()

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  await initRuntime()
  if (process.env.REELS_RUTUBE === '1') {
    const { liveRutube } = await import('./rutube-live')
    await liveRutube()
    app.quit()
    return
  }
  if (process.env.REELS_DUMP === '1') {
    const { dumpPlatforms } = await import('./dump-ui')
    await dumpPlatforms()
    app.quit()
    return
  }
  if (process.env.REELS_SCOUT === '1') {
    const { runScout } = await import('./scout')
    await runScout()
    app.quit()
    return
  }
  createWindow()
  if (process.env.REELS_STRESS !== '1') startTelegram()
  if (process.env.REELS_STRESS === '1') {
    const { runStressTest } = await import('./stress')
    await runStressTest()
    app.quit()
  }

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

let quitting = false

async function shutdownBrowsers(): Promise<void> {
  await shutdownTelegram().catch(() => undefined)
  shutdownAutomation()
  cancelGenerator()
  await Promise.all([closeAllBrowsers(), closeAllYoutubeProfiles()])
}

app.on('window-all-closed', () => {
  void shutdownBrowsers()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', (event) => {
  if (quitting) return
  quitting = true
  event.preventDefault()
  void shutdownBrowsers().finally(() => app.quit())
})
