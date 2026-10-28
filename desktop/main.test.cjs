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
    app: { isPackaged: false, whenReady: () => new Promise(() => {}), on: () => {}, getPath: () => 'C:/Temp', getVersion: () => '0.4.0' },
    BrowserWindow: class {},
    ipcMain: { handle: (name, callback) => handlers.set(name, callback) },
    session: {},
    dialog: { showSaveDialog: async () => saveChoice, showOpenDialog: async () => ({ canceled: true }) },
    Notification: class {
      static isSupported() { return true }
      constructor(options) { this.options = options; notices.push(this) }
      on(name, callback) { if (name === 'click') this.click = callback }
      show() { this.shown = true }
    },
  }
  const context = vm.createContext({
    require: (name) => name === 'electron' ? electron : name === 'node:fs/promises' ? { writeFile: async (...args) => writes.push(args), stat: async () => ({ size: 10 }), readFile: async () => Buffer.from('PKfile') } : require(name),
    process: { env: { VITE_DEV_SERVER_URL: 'http://127.0.0.1:5173' }, platform: 'win32', stdout: { write() {} }, stderr: { write() {} } },
    __dirname: path.join(__dirname),
    Buffer, URL, AbortSignal, setImmediate, setTimeout, setInterval, clearInterval,
    fetch: (...args) => fetchImpl(...args), console,
  })
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8'), context)
  vm.runInContext('apiPort=8765; mainWindow={ isDestroyed:()=>false, show(){}, focus(){}, webContents:{send:(_name,route)=>globalThis._navigate(route)} }', context)
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
