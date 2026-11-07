const { app, BrowserWindow, ipcMain, session, dialog, Notification, Tray, Menu, nativeImage, screen, shell } = require('electron')
const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs/promises')
const net = require('node:net')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
const { autoUpdater } = require('electron-updater')
const { exportBundle, importBundle, readLocalBackup } = require('./backup-transfer.cjs')
const updateConfig = require('./update-config.cjs')

const API_HOST = '127.0.0.1'
const SIDECAR_TOKEN = crypto.randomBytes(32).toString('hex')
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
let mainWindow
let backendExited = false
let tray
let isQuitting = false
let trayNoticeShown = false
let pendingRoute = null
let barState = { x: undefined, y: undefined, expanded: true, visible: true }
let stateSaveTimer
let projectBarWindow
let backendProcess
let apiPort
let notificationTimer
let updateState = { status: 'idle', version: null, message: null }
let updaterConfigured = false
const shownNotifications = new Set()
const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => showMainWindow())
}

function updateConfigurationError() {
  if (!app.isPackaged) return 'Güncelleme denetimi yalnızca kurulu uygulamada kullanılabilir.'
  if (updateConfig.provider !== 'github' || !/^[A-Za-z0-9_.-]+$/.test(updateConfig.owner) || !/^[A-Za-z0-9_.-]+$/.test(updateConfig.repo)) {
    return 'Güncelleme kaynağı henüz yapılandırılmadı.'
  }
  return null
}

function updateSnapshot() { return { ...updateState } }

function configureUpdater() {
  if (updaterConfigured) return true
  const error = updateConfigurationError()
  if (error) { updateState = { status: 'unavailable', version: null, message: error }; return false }
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = false
  autoUpdater.allowPrerelease = false
  autoUpdater.setFeedURL({ provider: 'github', owner: updateConfig.owner, repo: updateConfig.repo, private: false })
  autoUpdater.on('checking-for-update', () => { updateState = { status: 'checking', version: null, message: 'Güncelleme denetleniyor.' } })
  autoUpdater.on('update-available', (info) => { updateState = { status: 'available', version: info.version, message: 'Yeni sürüm indirilmeye hazır.' } })
  autoUpdater.on('update-not-available', () => { updateState = { status: 'current', version: app.getVersion(), message: 'Bu bilgisayarda en güncel sürüm kurulu.' } })
  autoUpdater.on('download-progress', (progress) => { updateState = { status: 'downloading', version: updateState.version, message: `İndiriliyor: %${Math.round(progress.percent)}` } })
  autoUpdater.on('update-downloaded', (info) => { updateState = { status: 'downloaded', version: info.version, message: 'Güncelleme hazır. Uygulamayı yeniden başlatarak yükleyin.' } })
  autoUpdater.on('error', (error) => { updateState = { status: 'error', version: null, message: `Güncelleme denetlenemedi: ${error.message}` } })
  updaterConfigured = true
  return true
}

async function checkForUpdates() {
  if (!configureUpdater()) return updateSnapshot()
  try { await autoUpdater.checkForUpdates() } catch (error) { updateState = { status: 'error', version: null, message: `Güncelleme denetlenemedi: ${error.message}` } }
  return updateSnapshot()
}

// ---- Proje barı konumu: ekran dışına taşmayı önleyen saf yardımcılar ----
const BAR_WIDTH = 360
const BAR_EXPANDED_HEIGHT = 560
const BAR_COMPACT_HEIGHT = 112
const BAR_MARGIN = 16
const BAR_HEADER_HEIGHT = 48

function barHeight(expanded) { return expanded ? BAR_EXPANDED_HEIGHT : BAR_COMPACT_HEIGHT }

function pickArea(x, y, areas) {
  const cx = x + BAR_WIDTH / 2
  const cy = y + BAR_HEADER_HEIGHT / 2
  return areas.find((a) => cx >= a.x && cx <= a.x + a.width && cy >= a.y && cy <= a.y + a.height) || null
}

function clampBar(x, y, height, area) {
  return {
    x: Math.min(Math.max(x, area.x), area.x + area.width - BAR_WIDTH),
    y: Math.min(Math.max(y, area.y), area.y + Math.max(0, area.height - height)),
  }
}

/** Kayıtlı konum bir ekranda duruyorsa onu (ekrana sığdırarak), yoksa birincil ekranın sağ altını döndürür. */
function placeBar(saved, areas, height) {
  if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    const area = pickArea(saved.x, saved.y, areas)
    if (area) return clampBar(saved.x, saved.y, height, area)
  }
  const area = areas[0]
  return clampBar(area.x + area.width - BAR_WIDTH - BAR_MARGIN, area.y + area.height - height - BAR_MARGIN, height, area)
}

/** Daralt/genişlet sırasında alt kenar çalışma alanının dışına taşmasın. */
function resizeBar(bounds, expanded, areas) {
  const height = barHeight(expanded)
  const area = pickArea(bounds.x, bounds.y, areas) || areas[0]
  const next = clampBar(bounds.x, bounds.y, height, area)
  return { x: next.x, y: next.y, width: BAR_WIDTH, height }
}

function workAreas() {
  try { return screen.getAllDisplays().map((d) => d.workArea) } catch { return [{ x: 0, y: 0, width: 1440, height: 900 }] }
}

function windowStatePath() { return path.join(app.getPath('userData'), 'window-state.json') }

async function loadWindowState() {
  try {
    const parsed = JSON.parse(await fs.readFile(windowStatePath(), 'utf8'))
    const bar = parsed && typeof parsed.bar === 'object' && parsed.bar ? parsed.bar : {}
    barState = {
      x: Number.isFinite(bar.x) ? bar.x : undefined,
      y: Number.isFinite(bar.y) ? bar.y : undefined,
      expanded: bar.expanded !== false,
      visible: bar.visible !== false,
    }
  } catch { /* Kayıt yok ya da bozuk: varsayılanlarla devam. */ }
}

function scheduleStateSave() {
  clearTimeout(stateSaveTimer)
  stateSaveTimer = setTimeout(() => {
    fs.writeFile(windowStatePath(), JSON.stringify({ bar: barState }), 'utf8').catch(() => {})
  }, 400)
}

// ---- Ana pencere gösterme ve güvenilir yönlendirme ----
function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) createWindow()
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

/** Yeni açılan pencere henüz hazır değilken mesaj kaybolmasın: yönlendirme bekletilir, arayüz açılışta çeker. */
function navigateMain(route) {
  showMainWindow()
  pendingRoute = { route, at: Date.now() }
  if (!mainWindow.webContents.isLoading()) mainWindow.webContents.send('app:navigate', route)
}

const EXPORT_PATH = /^\/api\/v1\/(?:reports\/(?:staff|finance)\/[a-z0-9-]+\/export\.(?:xlsx|pdf)|payroll-periods\/[0-9a-f-]+\/export\.(?:xlsx|pdf)|exports\/[a-z0-9-]+(?:\/pdf)?|work-logs\/import-template|imports\/templates\/[a-z0-9-]+)(?:\?[a-zA-Z0-9_=&%.-]*)?$/

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

function dialogOwner() {
  return mainWindow && !mainWindow.isDestroyed() ? mainWindow : undefined
}

function dataDirectory() { return path.join(app.getPath('userData'), 'data') }

async function chooseBackupBundle() {
  const choice = await dialog.showOpenDialog(dialogOwner(), { properties: ['openFile'], filters: [{ name: 'Kenan Şenocak yedeği', extensions: ['ksbackup'] }] })
  if (choice.canceled || choice.filePaths.length !== 1) return null
  return choice.filePaths[0]
}

ipcMain.handle('backup:export', async (event, backupId) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  try {
    const choice = await dialog.showSaveDialog(dialogOwner(), { defaultPath: `${backupId}.ksbackup`, filters: [{ name: 'Kenan Şenocak yedeği', extensions: ['ksbackup'] }] })
    if (choice.canceled || !choice.filePath) return { status: 'cancelled' }
    if (path.extname(choice.filePath).toLowerCase() !== '.ksbackup') return { status: 'error', message: 'Yedek dosyası uzantısı geçersiz.' }
    await exportBundle(dataDirectory(), backupId, choice.filePath)
    return { status: 'saved' }
  } catch (error) { return { status: 'error', message: String(error) } }
})

ipcMain.handle('backup:import', async (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  try {
    const source = await chooseBackupBundle()
    if (!source) return { status: 'cancelled' }
    const { backupId, created } = await importBundle(dataDirectory(), source)
    const response = await fetch(`${apiOrigin()}/api/v1/backups/${encodeURIComponent(backupId)}/verify`, { method: 'POST', headers: { 'x-ks-sidecar-token': SIDECAR_TOKEN }, signal: AbortSignal.timeout(30000) })
    if (!response.ok) {
      if (created) {
        const backupPath = path.join(dataDirectory(), 'backups', backupId)
        await fs.rm(backupPath, { force: true })
        await fs.rm(backupPath.replace(/\.db$/, '.json'), { force: true })
      }
      return { status: 'error', message: 'Yedek SQLite bütünlüğü doğrulanamadığı için reddedildi.' }
    }
    return { status: 'imported', backupId }
  } catch (error) { return { status: 'error', message: String(error) } }
})

function isTrustedRendererUrl(frameUrl) {
  if (process.env.VITE_DEV_SERVER_URL) {
    try { return new URL(frameUrl).origin === new URL(process.env.VITE_DEV_SERVER_URL).origin } catch { return false }
  }
  const rendererRoot = pathToFileURL(path.join(__dirname, '..', 'frontend', 'dist')).href
  return frameUrl.startsWith(`${rendererRoot}/`)
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
    backendExited = true
    console.error('Backend başlatılamadı:', error)
  })
  backendProcess.on('exit', () => { backendExited = true })
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

function safeRoute(source) {
  if (!source || typeof source !== 'object') return '/'
  const id = (value) => typeof value === 'string' && /^[a-zA-Z0-9-]+$/.test(value) ? value : ''
  const entity = source.entity
  if (entity === 'receivable_schedule' || entity === 'customer') return `/musteriler${id(source.customer_id || source.entity_id) ? `?customer=${id(source.customer_id || source.entity_id)}` : ''}`
  if (entity === 'purchase' || entity === 'supplier') return `/firmalar${id(source.supplier_id) ? `?supplier=${id(source.supplier_id)}` : ''}`
  if (entity === 'employee_financial_movement' || entity === 'employee' || entity === 'leave_request') return `/personel${id(source.employee_id) ? `?employee=${id(source.employee_id)}` : ''}`
  if (entity === 'project_task' || entity === 'project_visit' || entity === 'project') return `/projeler${id(source.project_id) ? `?project=${id(source.project_id)}` : ''}`
  return '/takvim'
}

async function pollNotifications() {
  if (!apiPort || !Notification.isSupported()) return
  try {
    const response = await fetch(`${apiOrigin()}/api/v1/notifications/due`, { headers: { 'x-ks-sidecar-token': SIDECAR_TOKEN }, signal: AbortSignal.timeout(8000) })
    if (!response.ok) return
    const payload = await response.json()
    for (const item of payload.notifications || []) {
      if (typeof item.delivery_key !== 'string' || shownNotifications.has(item.delivery_key)) continue
      shownNotifications.add(item.delivery_key)
      const notice = new Notification({ title: String(item.title || 'Hatırlatma'), body: String(item.body || '') })
      notice.on('click', () => navigateMain(safeRoute(item.event?.source_route)))
      notice.show()
      const delivered = await fetch(`${apiOrigin()}/api/v1/notifications/delivered`, {
        method: 'POST', headers: { 'content-type': 'application/json', 'x-ks-sidecar-token': SIDECAR_TOKEN },
        body: JSON.stringify({ delivery_key: item.delivery_key }), signal: AbortSignal.timeout(8000),
      })
      if (!delivered.ok) shownNotifications.delete(item.delivery_key)
    }
  } catch { /* Sidecar unavailable: next bounded poll will retry. */ }
}

ipcMain.handle('api:download', async (event, request) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (!request || request.method && request.method !== 'GET' || typeof request.path !== 'string' || !EXPORT_PATH.test(request.path)) throw new Error('İzin verilmeyen dışa aktarma yolu.')
  const extension = request.path.split('?')[0].endsWith('.pdf') || request.path.split('?')[0].endsWith('/pdf') ? 'pdf' : 'xlsx'
  const filename = typeof request.filename === 'string' && /^[\p{L}\p{N} _.-]{1,100}$/u.test(request.filename) ? request.filename.replace(/\.(xlsx|pdf)$/i, '') : 'Rapor'
  try {
    const response = await fetch(`${apiOrigin()}${request.path}`, { headers: { 'x-ks-sidecar-token': SIDECAR_TOKEN }, signal: AbortSignal.timeout(30000) })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      return { status: 'error', message: payload?.error?.message || `Rapor alınamadı (${response.status}).` }
    }
    const contentType = response.headers.get('content-type')?.split(';')[0]?.trim()
    const pathOnly = request.path.split('?')[0]
    const isBase64Payload = /\/import-template$|\/imports\/templates\/|\/exports\/[a-z0-9-]+(?:\/pdf)?$/.test(pathOnly)
    if (isBase64Payload) {
      const expectedMime = extension === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      if (contentType !== 'application/json') return { status: 'error', message: 'Dosya yanıtı geçersiz.' }
      const payload = await response.json()
      if (payload.mime_type !== expectedMime || typeof payload.content_base64 !== 'string' || payload.content_base64.length > 12_000_000) return { status: 'error', message: 'Dosya içeriği geçersiz.' }
      const bytes = Buffer.from(payload.content_base64, 'base64')
      const magic = extension === 'pdf' ? '%PDF-' : 'PK'
      if (bytes.subarray(0, magic.length).toString() !== magic) return { status: 'error', message: extension === 'pdf' ? 'PDF içeriği geçersiz.' : 'Excel içeriği geçersiz.' }
      const choice = await dialog.showSaveDialog(dialogOwner(), { defaultPath: `${filename}.${extension}`, filters: [{ name: extension.toUpperCase(), extensions: [extension] }] })
      if (choice.canceled || !choice.filePath) return { status: 'cancelled' }
      if (path.extname(choice.filePath).toLowerCase() !== `.${extension}`) return { status: 'error', message: 'Dosya uzantısı geçersiz.' }
      await fs.writeFile(choice.filePath, bytes)
      return { status: 'saved' }
    }
    const expected = extension === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if (contentType !== expected) return { status: 'error', message: 'Rapor dosya türü beklenen biçimde değil.' }
    const bytes = Buffer.from(await response.arrayBuffer())
    if (extension === 'pdf' && bytes.subarray(0, 5).toString() !== '%PDF-') return { status: 'error', message: 'PDF içeriği geçersiz.' }
    if (extension === 'xlsx' && bytes.subarray(0, 2).toString() !== 'PK') return { status: 'error', message: 'Excel içeriği geçersiz.' }
    const choice = await dialog.showSaveDialog(dialogOwner(), { defaultPath: `${filename}.${extension}`, filters: [{ name: extension.toUpperCase(), extensions: [extension] }] })
    if (choice.canceled || !choice.filePath) return { status: 'cancelled' }
    if (path.extname(choice.filePath).toLowerCase() !== `.${extension}`) return { status: 'error', message: 'Dosya uzantısı geçersiz.' }
    await fs.writeFile(choice.filePath, bytes, { flag: 'w' })
    return { status: 'saved' }
  } catch (error) { return { status: 'error', message: `Dosya kaydedilemedi: ${String(error)}` } }
})

ipcMain.handle('api:read-spreadsheet', async (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  const choice = await dialog.showOpenDialog(dialogOwner(), { properties: ['openFile'], filters: [{ name: 'XLSX', extensions: ['xlsx'] }] })
  if (choice.canceled || choice.filePaths.length !== 1) return { status: 'cancelled' }
  const filePath = choice.filePaths[0]
  if (path.extname(filePath).toLowerCase() !== '.xlsx') return { status: 'error', message: 'Yalnız XLSX dosyası seçilebilir.' }
  const stat = await fs.stat(filePath)
  if (stat.size > 8 * 1024 * 1024) return { status: 'error', message: 'Dosya 8 MB sınırını aşıyor.' }
  const bytes = await fs.readFile(filePath)
  if (bytes.subarray(0, 2).toString() !== 'PK') return { status: 'error', message: 'Geçersiz Excel dosyası.' }
  return { status: 'selected', file_name: path.basename(filePath), content_base64: bytes.toString('base64') }
})

ipcMain.handle('api:save-project-contract', async (event, request) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (!request || typeof request.projectId !== 'string' || !/^[0-9a-f-]{36}$/i.test(request.projectId)) throw new Error('Geçersiz proje kimliği.')
  const filename = request.filename
  if (typeof filename !== 'string' || filename.length > 180 || !/^[^\\/\x00-\x1f]+\.(pdf|docx)$/i.test(filename)) throw new Error('Geçersiz sözleşme dosya adı.')
  const extension = path.extname(filename).toLowerCase()
  const expectedMime = extension === '.pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  try {
    const response = await fetch(`${apiOrigin()}/api/v1/projects/${request.projectId}/contract/file`, {
      headers: { 'x-ks-sidecar-token': SIDECAR_TOKEN }, signal: AbortSignal.timeout(30000),
    })
    if (!response.ok) return { status: 'error', message: `Sözleşme alınamadı (${response.status}).` }
    if (response.headers.get('content-type')?.split(';')[0]?.trim() !== expectedMime) return { status: 'error', message: 'Sözleşme dosya türü uyuşmuyor.' }
    const bytes = Buffer.from(await response.arrayBuffer())
    if (!bytes.length || bytes.length > 8 * 1024 * 1024 || (extension === '.pdf' ? bytes.subarray(0, 5).toString() !== '%PDF-' : bytes.subarray(0, 2).toString() !== 'PK')) return { status: 'error', message: 'Sözleşme içeriği geçersiz.' }
    const choice = await dialog.showSaveDialog(dialogOwner(), { defaultPath: filename, filters: [{ name: extension.slice(1).toUpperCase(), extensions: [extension.slice(1)] }] })
    if (choice.canceled || !choice.filePath) return { status: 'cancelled' }
    if (path.extname(choice.filePath).toLowerCase() !== extension) return { status: 'error', message: 'Dosya uzantısı geçersiz.' }
    await fs.writeFile(choice.filePath, bytes, { flag: 'w' })
    return { status: 'saved' }
  } catch (error) { return { status: 'error', message: `Sözleşme kaydedilemedi: ${String(error)}` } }
})

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
    let data = null
    if (text) {
      try { data = JSON.parse(text) } catch {
        return { ok: false, status: response.status, data: { error: { code: 'invalid_response', message: 'Yerel veri hizmetinden beklenmeyen yanıt alındı.', details: text.slice(0, 200) } } }
      }
    }
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

ipcMain.handle('app:get-update-state', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (updateState.status === 'idle') configureUpdater()
  return updateSnapshot()
})

ipcMain.handle('app:check-for-updates', async (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  return checkForUpdates()
})

ipcMain.handle('app:download-update', async (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (updateState.status !== 'available') return updateSnapshot()
  try { await autoUpdater.downloadUpdate() } catch (error) { updateState = { status: 'error', version: null, message: `Güncelleme indirilemedi: ${error.message}` } }
  return updateSnapshot()
})

ipcMain.handle('app:install-update', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (updateState.status !== 'downloaded') return { accepted: false }
  setImmediate(() => {
    stopBackend()
    autoUpdater.quitAndInstall(false, true)
  })
  return { accepted: true }
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
  // İlk açılışta veritabanı yükseltmesi ve yedek birkaç saniye sürebilir; 60 sn'ye kadar bekle.
  for (let attempt = 0; attempt < 240 && !backendExited; attempt += 1) {
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
  // Kapat düğmesi uygulamayı bitirmez, tepsiye indirir (arkada çalışıp mini barı sürdürmek için).
  mainWindow.on('close', (event) => {
    if (isQuitting || !tray) return
    event.preventDefault()
    mainWindow.hide()
    if (!trayNoticeShown && Notification.isSupported()) {
      trayNoticeShown = true
      new Notification({ title: 'Uygulama arka planda çalışıyor', body: 'Tepsi simgesinden açabilir veya Çıkış seçebilirsiniz.' }).show()
    }
  })
  mainWindow.on('closed', () => { if (!tray) app.quit() })

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
  const areas = workAreas()
  const height = barHeight(barState.expanded)
  const position = placeBar(barState, areas, height)
  projectBarWindow = new BrowserWindow({
    ...position,
    width: BAR_WIDTH,
    height,
    frame: false,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
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
  projectBarWindow.setAlwaysOnTop(true, 'floating')
  projectBarWindow.removeMenu()
  projectBarWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  projectBarWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (!isTrustedRendererUrl(targetUrl)) event.preventDefault()
  })
  projectBarWindow.once('ready-to-show', () => projectBarWindow.showInactive())
  projectBarWindow.on('moved', () => {
    if (!projectBarWindow || projectBarWindow.isDestroyed()) return
    const { x, y } = projectBarWindow.getBounds()
    barState = { ...barState, x, y }
    scheduleStateSave()
  })
  projectBarWindow.on('closed', () => { projectBarWindow = undefined })
  barState = { ...barState, visible: true }
  scheduleStateSave()
  loadRenderer(projectBarWindow, '#/mini-bar')
  return projectBarWindow
}

function hideProjectBar() {
  if (projectBarWindow && !projectBarWindow.isDestroyed()) projectBarWindow.hide()
  barState = { ...barState, visible: false }
  scheduleStateSave()
}

function toggleProjectBar() {
  if (projectBarWindow && !projectBarWindow.isDestroyed() && projectBarWindow.isVisible()) hideProjectBar()
  else createProjectBar()
  return { visible: barState.visible }
}

function createTray() {
  try {
    let image = nativeImage.createFromPath(path.join(__dirname, '..', 'build', 'icon.ico'))
    if (image.isEmpty()) image = nativeImage.createFromPath(process.execPath)
    tray = new Tray(image)
    tray.setToolTip('Kenan Şenocak Yönetim')
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Uygulamayı aç', click: () => showMainWindow() },
      { label: 'Mini barı göster / gizle', click: () => toggleProjectBar() },
      { type: 'separator' },
      { label: 'Çıkış', click: () => { isQuitting = true; app.quit() } },
    ]))
    tray.on('click', () => showMainWindow())
  } catch (error) {
    tray = undefined
    console.error('Tepsi simgesi oluşturulamadı:', error)
  }
}

ipcMain.handle('app:toggle-project-bar', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  return toggleProjectBar()
})

ipcMain.handle('app:hide-project-bar', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  hideProjectBar()
  return { visible: false }
})

ipcMain.handle('app:set-project-bar-expanded', (event, expanded) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  if (!projectBarWindow || projectBarWindow.isDestroyed()) return { accepted: false }
  const isExpanded = Boolean(expanded)
  projectBarWindow.setBounds(resizeBar(projectBarWindow.getBounds(), isExpanded, workAreas()))
  const { x, y } = projectBarWindow.getBounds()
  barState = { ...barState, x, y, expanded: isExpanded }
  scheduleStateSave()
  return { accepted: true }
})

ipcMain.handle('app:show-main', (event, projectId) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  const safeId = typeof projectId === 'string' && /^[a-zA-Z0-9-]+$/.test(projectId) ? projectId : ''
  navigateMain(safeId ? `/projeler?project=${safeId}` : '/projeler')
  return { accepted: true }
})

ipcMain.handle('app:take-pending-route', (event) => {
  if (!isTrustedSender(event)) throw new Error('Güvenilmeyen renderer isteği reddedildi.')
  const pending = pendingRoute
  pendingRoute = null
  return pending && Date.now() - pending.at < 10_000 ? pending.route : null
})

// Bir pencerede veri değişince diğer pencere önbelleğini yeniler (ana pencere ↔ mini bar).
ipcMain.on('app:data-changed', (event) => {
  if (!isTrustedSender(event)) return
  for (const win of [mainWindow, projectBarWindow]) {
    if (win && !win.isDestroyed() && win.webContents.id !== event.sender.id) win.webContents.send('app:data-changed')
  }
})

app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return
  installSecurityHeaders()
  await startBackend()
  if (!(await waitForBackend())) {
    stopBackend()
    const backupDir = path.join(dataDirectory(), 'backups')
    await fs.mkdir(backupDir, { recursive: true })
    while (true) {
      const choice = await dialog.showMessageBox({ type: 'error', title: 'Yerel veri hizmeti açılamadı', message: 'Uygulama başlatılamadı. Dışarı kaydettiğiniz bir yedekten geri yükleyebilir veya yedek klasörünü açabilirsiniz.', detail: 'Geri yüklemeden önce mevcut veritabanının bir kopyası korunur.', buttons: ['Dış yedekten geri yükle', 'Yedek klasörünü aç', 'Kapat'], defaultId: 2, cancelId: 2, noLink: true })
      if (choice.response === 1) { await shell.openPath(backupDir); continue }
      if (choice.response !== 0) break
      try {
        const source = await chooseBackupBundle()
        if (!source) continue
        const { backupId } = await importBundle(dataDirectory(), source)
        const { backupPath } = await readLocalBackup(dataDirectory(), backupId)
        const livePath = path.join(dataDirectory(), 'kenan-senocak.db')
        const safetyPath = path.join(dataDirectory(), `kenan-senocak-before-recovery-${Date.now()}.db`)
        await fs.copyFile(livePath, safetyPath).catch((error) => { if (error.code !== 'ENOENT') throw error })
        const tempPath = `${livePath}.recovering`
        await fs.copyFile(backupPath, tempPath)
        await fs.rename(tempPath, livePath)
        app.relaunch()
        app.quit()
        return
      } catch (error) {
        dialog.showErrorBox('Geri yükleme başarısız', String(error))
      }
    }
    app.quit()
    return
  }
  await loadWindowState()
  createTray()
  createWindow()
  if (barState.visible) createProjectBar()
  await pollNotifications()
  notificationTimer = setInterval(pollNotifications, 15 * 60 * 1000)
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => { isQuitting = true; if (notificationTimer) clearInterval(notificationTimer); stopBackend() })
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
