export const stealthInitScript = `(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => undefined,
      configurable: true
    })
  } catch {}
  try {
    if (!window.chrome) window.chrome = {}
    if (!window.chrome.runtime) {
      window.chrome.runtime = { connect: () => ({}), sendMessage: () => {} }
    }
  } catch {}
})()`
