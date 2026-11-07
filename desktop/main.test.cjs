const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

function harness() {
  const handlers = new Map()
  const writes = []
  const notices = []
  const navigations = []
  let fetchImpl = async () => { throw new Error('fetch not configured') }
  let saveChoice = { canceled: false, filePath: 'C:/Temp/report.pdf' }
  const electron = {
    app: { isPackaged: false, requestSingleInstanceLock: () => true, quit() {}, whenReady: () => new Promise(() => {}), on: () => {}, getPath: () => 'C:/Temp', getVersion: () => '0.4.0' },
    BrowserWindow: class {},
    ipcMain: { handle: (name, callback) => handlers.set(name, callback), on: (name, callback) => handlers.set(name, callback) },
    session: {},
    Tray: class {},
    Menu: { buildFromTemplate: () => ({}) },
    nativeImage: { createFromPath: () => ({ isEmpty: () => true }) },
    screen: { getAllDisplays: () => [] },
    dialog: { showErrorBox() {}, showSaveDialog: async () => saveChoice, showOpenDialog: async () => ({ canceled: true }) },
    Notification: class {
      static isSupported() { return true }
      constructor(options) { this.options = options; notices.push(this) }
      on(name, callback) { if (name === 'click') this.click = callback }
      show() { this.shown = true }
    },
  }
  const context = vm.createContext({
    require: (name) => name === 'electron' ? electron : name === 'electron-updater' ? { autoUpdater: { on() {}, setFeedURL() {}, checkForUpdates: async () => null, downloadUpdate: async () => null, quitAndInstall() {} } } : name === 'node:fs/promises' ? { writeFile: async (...args) => writes.push(args), stat: async () => ({ size: 10 }), readFile: async () => Buffer.from('PKfile') } : require(name),
    process: { env: { VITE_DEV_SERVER_URL: 'http://127.0.0.1:5173' }, platform: 'win32', stdout: { write() {} }, stderr: { write() {} } },
    __dirname: path.join(__dirname),
    Buffer, URL, AbortSignal, setImmediate, setTimeout, setInterval, clearInterval,
    fetch: (...args) => fetchImpl(...args), console,
  })
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8'), context)
  vm.runInContext('apiPort=8765; mainWindow={ isDestroyed:()=>false, show(){}, focus(){}, webContents:{send:(_name,route)=>globalThis._navigate(route), isLoading:()=>false}, isMinimized:()=>false, restore(){} }', context)
  context._navigate = (route) => navigations.push(route)
  const event = { senderFrame: { url: 'http://127.0.0.1:5173/' } }
  return { handlers, writes, notices, navigations, event, context, setFetch: (impl) => { fetchImpl = impl }, setChoice: (choice) => { saveChoice = choice } }
}

function response(contentType, bytes, status = 200) {
  return { ok: status >= 200 && status < 300, status, headers: { get: () => contentType }, arrayBuffer: async () => Uint8Array.from(bytes).buffer, json: async () => ({ error: { message: 'Rapor hatası' } }) }
}

test('download IPC rejects untrusted sender, method and path', async () => {
  const h = harness(); const download = h.handlers.get('api:download')
  await assert.rejects(download({ senderFrame: { url: 'https://evil.example' } }, { path: '/api/v1/reports/finance/project-profitability/export.pdf' }))
  await assert.rejects(download(h.event, { path: 'http://evil.example/x' }))
  await assert.rejects(download(h.event, { method: 'POST', path: '/api/v1/reports/finance/project-profitability/export.pdf' }))
  await assert.rejects(download(h.event, { path: '/api/v1/reports/finance/../../customers/export.pdf' }))
})

test('download validates content and handles save, cancellation and backend errors', async () => {
  const h = harness(); const download = h.handlers.get('api:download')
  const request = { path: '/api/v1/reports/finance/project-profitability/export.pdf', filename: 'Kârlılık' }
  h.setFetch(async () => response('application/pdf', Buffer.from('%PDF-1.4')))
  assert.equal((await download(h.event, request)).status, 'saved')
  assert.equal(h.writes.length, 1)
  h.setChoice({ canceled: true })
  assert.equal((await download(h.event, request)).status, 'cancelled')
  h.setFetch(async () => response('application/json', Buffer.from('{}')))
  assert.equal((await download(h.event, request)).status, 'error')
  h.setFetch(async () => response('application/json', Buffer.from('{}'), 422))
  assert.match((await download(h.event, request)).message, /Rapor hatası/)
})

test('Excel export and template use validated content', async () => {
  const h = harness(); const download = h.handlers.get('api:download')
  h.setChoice({ canceled: false, filePath: 'C:/Temp/report.xlsx' })
  h.setFetch(async () => response('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', Buffer.from('PKzip')))
  assert.equal((await download(h.event, { path: '/api/v1/reports/staff/unpaid-payroll/export.xlsx' })).status, 'saved')
  h.setFetch(async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => ({ mime_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', content_base64: Buffer.from('PKtemplate').toString('base64') }) }))
  assert.equal((await download(h.event, { path: '/api/v1/work-logs/import-template' })).status, 'saved')
  h.setChoice({ canceled: false, filePath: 'C:/Temp/report.txt' })
  assert.equal((await download(h.event, { path: '/api/v1/work-logs/import-template' })).status, 'error')
})

test('notifications deduplicate and deep link only to safe route', async () => {
  const h = harness()
  const due = { notifications: [{ delivery_key: 'event|date|1|windows', title: 'Tahsilat', body: '', event: { source_route: { entity: 'customer', customer_id: 'safe-id' } } }] }
  let delivered = 0
  h.setFetch(async (url) => url.endsWith('/notifications/due') ? { ok: true, json: async () => due } : (delivered++, { ok: true }))
  await vm.runInContext('pollNotifications()', h.context)
  await vm.runInContext('pollNotifications()', h.context)
  assert.equal(h.notices.length, 1)
  assert.equal(delivered, 1)
  h.notices[0].click()
  assert.equal(h.navigations[0], '/musteriler?customer=safe-id')
  assert.equal(vm.runInContext("safeRoute({entity:'customer',customer_id:'../../bad'})", h.context), '/musteriler')
})

test('spreadsheet picker rejects untrusted sender and treats cancel as normal', async () => {
  const h = harness(); const read = h.handlers.get('api:read-spreadsheet')
  await assert.rejects(read({ senderFrame: { url: 'file:///untrusted/index.html' } }))
  assert.equal((await read(h.event)).status, 'cancelled')
})

test('generic JSON export payloads save as PDF and Excel', async () => {
  const h = harness(); const download = h.handlers.get('api:download')
  const json = (mime, text) => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => ({ mime_type: mime, content_base64: Buffer.from(text).toString('base64') }) })
  h.setChoice({ canceled: false, filePath: 'C:/Temp/out.pdf' })
  h.setFetch(async () => json('application/pdf', '%PDF-1.4 x'))
  assert.equal((await download(h.event, { path: '/api/v1/exports/purchases/pdf' })).status, 'saved')
  h.setChoice({ canceled: false, filePath: 'C:/Temp/out.xlsx' })
  h.setFetch(async () => json('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'PKzip'))
  assert.equal((await download(h.event, { path: '/api/v1/exports/materials' })).status, 'saved')
  h.setFetch(async () => json('application/pdf', 'PKnot-pdf'))
  assert.equal((await download(h.event, { path: '/api/v1/exports/purchases/pdf' })).status, 'error')
})

test('API proxy reports non-JSON backend answers without throwing', async () => {
  const h = harness(); const request = h.handlers.get('api:request')
  h.setFetch(async () => ({ ok: false, status: 500, text: async () => 'Internal Server Error' }))
  const result = await request(h.event, { path: '/api/v1/suppliers' })
  assert.equal(result.ok, false)
  assert.equal(result.data.error.code, 'invalid_response')
})

test('update IPC rejects an untrusted renderer and is unavailable in development', async () => {
  const h = harness()
  const state = h.handlers.get('app:get-update-state')
  const check = h.handlers.get('app:check-for-updates')
  await assert.rejects(check({ senderFrame: { url: 'https://evil.example' } }))
  assert.equal((await state(h.event)).status, 'unavailable')
  assert.match((await state(h.event)).message, /kurulu uygulamada/)
})

test('mini bar placement stays inside a display and falls back to bottom-right', () => {
  const h = harness()
  const run = (code) => JSON.parse(vm.runInContext(`JSON.stringify(${code})`, h.context))
  const screens = '[{x:0,y:0,width:1920,height:1040},{x:1920,y:0,width:1280,height:984}]'
  assert.deepEqual(run(`placeBar(undefined, ${screens}, 560)`), { x: 1920 - 360 - 16, y: 1040 - 560 - 16 })
  assert.deepEqual(run(`placeBar({x:2000,y:100}, ${screens}, 560)`), { x: 2000, y: 100 })
  // Kaydedilmiş ekran artık yoksa (monitör çıkarıldı) birincil ekranın köşesine döner.
  assert.deepEqual(run(`placeBar({x:5000,y:100}, [{x:0,y:0,width:1920,height:1040}], 560)`), { x: 1920 - 360 - 16, y: 1040 - 560 - 16 })
  // Alta yakın bar genişleyince çalışma alanından taşmaz.
  assert.deepEqual(run(`resizeBar({x:100,y:900,width:360,height:112}, true, ${screens})`), { x: 100, y: 1040 - 560, width: 360, height: 560 })
  assert.deepEqual(run(`resizeBar({x:100,y:900,width:360,height:560}, false, ${screens})`), { x: 100, y: 900, width: 360, height: 112 })
})

test('show-main keeps the route for a window that is still loading', async () => {
  const h = harness()
  const showMain = h.handlers.get('app:show-main')
  const take = h.handlers.get('app:take-pending-route')
  vm.runInContext('mainWindow.webContents.isLoading = () => true', h.context)
  await showMain(h.event, 'abc-123')
  assert.equal(h.navigations.length, 0)          // sayfa yüklenirken itme yok
  assert.equal(await take(h.event), '/projeler?project=abc-123')
  assert.equal(await take(h.event), null)         // bir kez teslim edilir
  vm.runInContext('mainWindow.webContents.isLoading = () => false', h.context)
  await showMain(h.event, '../evil')
  assert.deepEqual(h.navigations, ['/projeler'])  // geçersiz kimlik yok sayılır
})

test('data-changed is forwarded to the other window only', () => {
  const h = harness()
  const sent = []
  vm.runInContext(`mainWindow.webContents.id = 1; projectBarWindow = { isDestroyed: () => false, webContents: { id: 2, send: (name) => globalThis._barGot(name) } }`, h.context)
  h.context._barGot = (name) => sent.push(name)
  h.handlers.get('app:data-changed')({ ...h.event, sender: { id: 1 } })
  assert.deepEqual(sent, ['app:data-changed'])
  h.handlers.get('app:data-changed')({ senderFrame: { url: 'https://evil.example' }, sender: { id: 1 } })
  assert.equal(sent.length, 1)
  h.handlers.get('app:data-changed')({ ...h.event, sender: { id: 2 } })
  assert.equal(sent.length, 1)
})
