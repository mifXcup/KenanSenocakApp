const { app, BrowserWindow, ipcMain, session } = require('electron')
const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const net = require('node:net')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const API_HOST = '127.0.0.1'
const SIDECAR_TOKEN = crypto.randomBytes(32).toString('hex')
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
let mainWindow
let projectBarWindow
let backendProcess
let apiPort

function apiOrigin() {
  if (!apiPort) throw new Error('Yerel veri hizmeti portu hazır değil.')
  return `http://${API_HOST}:${apiPort}`
}

function findAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, API_HOST, () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => port ? resolve(port) : reject(new Error('Uygun yerel port bulunamadı.')))
    })
  })
}

function isTrustedRendererUrl(frameUrl) {
  if (process.env.VITE_DEV_SERVER_URL) {
    try { return new URL(frameUrl).origin === new URL(process.env.VITE_DEV_SERVER_URL).origin } catch { return false }
  }
  const rendererRoot = pathToFileURL(path.join(__dirname, '..', 'frontend', 'dist')).href
  return frameUrl.startsWith(rendererRoot)
}

function isTrustedSender(event) {
  return isTrustedRendererUrl(event.senderFrame?.url || '')
}

function resolveBackendCommand(port) {
  if (!app.isPackaged) {
    const root = path.resolve(__dirname, '..')
    return {
      command: path.join(root, 'backend', '.venv', 'Scripts', 'python.exe'),
      args: ['-m', 'uvicorn', 'ks_yonetim.main:app', '--host', API_HOST, '--port', String(port)],
      cwd: path.join(root, 'backend'),
      env: { ...process.env, PYTHONPATH: path.join(root, 'backend', 'src') },
    }
  }

  const executable = path.join(process.resourcesPath, 'backend', 'ks-core.exe')
  return {
    command: executable,
    args: ['--host', API_HOST, '--port', String(port)],
    cwd: path.dirname(executable),
    env: { ...process.env },
  }
}

async function startBackend() {
  apiPort = await findAvailablePort()
  const config = resolveBackendCommand(apiPort)
  backendProcess = spawn(config.command, config.args, {
    cwd: config.cwd,
    env: {
      ...config.env,
      KS_SIDECAR_TOKEN: SIDECAR_TOKEN,
      KS_DATA_DIR: path.join(app.getPath('userData'), 'data'),
    },
    windowsHide: true,
    stdio: app.isPackaged ? 'ignore' : 'pipe',
  })

  if (!app.isPackaged) {
    backendProcess.stdout?.on('data', (data) => process.stdout.write(`[backend] ${data}`))
    backendProcess.stderr?.on('data', (data) => process.stderr.write(`[backend] ${data}`))
  }
  backendProcess.on('error', (error) => {
    console.error('Backend başlatılamadı:', error)
  })
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) backendProcess.kill()
  backendProcess = undefined
}

function validateApiRequest(request) {
  if (!request || typeof request.path !== 'string') throw new Error('Geçersiz API isteği.')
  const method = String(request.method || 'GET').toUpperCase()
  if (!ALLOWED_METHODS.has(method)) throw new Error('Bu istek yöntemi desteklenmiyor.')
  if (!request.path.startsWith('/api/v1/') || request.path.includes('..') || request.path.includes('://')) {
    throw new Error('İzin verilmeyen API yolu.')
  }
  return { method, path: request.path }
}

ipcMain.handle('api:request', async (event, request) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  const safe = validateApiRequest(request)
  try {
    const response = await fetch(`${apiOrigin()}${safe.path}`, {
      method: safe.method,
      headers: {
        'content-type': 'application/json',
        'x-ks-sidecar-token': SIDECAR_TOKEN,
      },
      body: request.body == null ? undefined : JSON.stringify(request.body),
    })
    const text = await response.text()
    const data = text ? JSON.parse(text) : null
    return { ok: response.ok, status: response.status, data }
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: { error: { code: 'backend_unavailable', message: 'Yerel veri hizmetine ulaşılamadı.', details: String(error) } },
    }
  }
})

ipcMain.handle('app:get-info', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  return ({
  version: app.getVersion(),
  platform: process.platform,
  packaged: app.isPackaged,
  dataDirectory: app.getPath('userData'),
  })
})

ipcMain.handle('app:relaunch', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  setImmediate(() => {
    stopBackend()
    app.relaunch()
    app.exit(0)
  })
  return { accepted: true }
})

async function waitForBackend() {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    try {
      const response = await fetch(`${apiOrigin()}/api/v1/health`)
      if (response.ok) return true
    } catch { /* Sidecar henüz dinlemiyor. */ }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  return false
}

function installSecurityHeaders() {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const dev = Boolean(process.env.VITE_DEV_SERVER_URL)
    const policy = dev
      ? "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:5173 http://127.0.0.1:5173"
      : "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    callback({ responseHeaders: { ...details.responseHeaders, 'Content-Security-Policy': [policy] } })
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1024,
    minHeight: 700,
    backgroundColor: '#f6f5f2',
    title: 'Kenan Şenocak Yönetim',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  mainWindow.removeMenu()
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (!isTrustedRendererUrl(targetUrl)) event.preventDefault()
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }
}

function rendererTarget(hash = '') {
  if (process.env.VITE_DEV_SERVER_URL) return `${process.env.VITE_DEV_SERVER_URL}${hash}`
  return { file: path.join(__dirname, '..', 'frontend', 'dist', 'index.html'), hash: hash.replace(/^#/, '') }
}

function loadRenderer(window, hash = '') {
  const target = rendererTarget(hash)
  if (typeof target === 'string') window.loadURL(target)
  else window.loadFile(target.file, { hash: target.hash })
}

function createProjectBar() {
  if (projectBarWindow && !projectBarWindow.isDestroyed()) {
    projectBarWindow.show()
    projectBarWindow.focus()
    return projectBarWindow
  }
  projectBarWindow = new BrowserWindow({
    width: 360,
    height: 560,
    minWidth: 340,
    minHeight: 104,
    maxWidth: 440,
    frame: false,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    backgroundColor: '#F7F3ED',
    show: false,
    title: 'Proje Barı',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  projectBarWindow.removeMenu()
  projectBarWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  projectBarWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (!isTrustedRendererUrl(targetUrl)) event.preventDefault()
  })
  projectBarWindow.once('ready-to-show', () => projectBarWindow.showInactive())
  projectBarWindow.on('closed', () => { projectBarWindow = undefined })
  loadRenderer(projectBarWindow, '#/mini-bar')
  return projectBarWindow
}

ipcMain.handle('app:toggle-project-bar', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (projectBarWindow && !projectBarWindow.isDestroyed() && projectBarWindow.isVisible()) projectBarWindow.hide()
  else createProjectBar()
  return { visible: Boolean(projectBarWindow?.isVisible()) }
})

ipcMain.handle('app:set-project-bar-expanded', (event, expanded) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (!projectBarWindow || projectBarWindow.isDestroyed()) return { accepted: false }
  projectBarWindow.setSize(360, expanded ? 560 : 112, true)
  return { accepted: true }
})

ipcMain.handle('app:show-main', (event, projectId) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (!mainWindow || mainWindow.isDestroyed()) createWindow()
  mainWindow.show()
  mainWindow.focus()
  const safeId = typeof projectId === 'string' && /^[a-zA-Z0-9-]+$/.test(projectId) ? projectId : ''
  mainWindow.webContents.send('app:navigate', safeId ? `/projeler?project=${safeId}` : '/projeler')
  return { accepted: true }
})

app.whenReady().then(async () => {
  installSecurityHeaders()
  await startBackend()
  await waitForBackend()
  createWindow()
  createProjectBar()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', stopBackend)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
