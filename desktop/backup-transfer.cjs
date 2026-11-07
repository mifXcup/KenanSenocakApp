const fs = require('node:fs/promises')
const path = require('node:path')
const crypto = require('node:crypto')

const BACKUP_ID = /^ks-\d{8}-\d{6}-\d{6}-(automatic|manual|pre_restore|pre_import|pre_migration|pre_finalize)\.db$/
const MAX_BACKUP_BYTES = 256 * 1024 * 1024

function validateMetadata(metadata) {
  if (!metadata || typeof metadata !== 'object' || !BACKUP_ID.test(metadata.backup_id) || typeof metadata.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(metadata.sha256) || !Number.isSafeInteger(metadata.size_bytes) || metadata.size_bytes < 100 || metadata.size_bytes > MAX_BACKUP_BYTES) throw new Error('Yedek bilgileri geçersiz veya dosya 256 MB sınırını aşıyor.')
  return metadata
}

function verifyBytes(metadata, bytes) {
  validateMetadata(metadata)
  if (bytes.length !== metadata.size_bytes || bytes.subarray(0, 16).toString() !== 'SQLite format 3\0' || crypto.createHash('sha256').update(bytes).digest('hex') !== metadata.sha256) throw new Error('Yedek dosyası bütünlük doğrulamasından geçemedi.')
}

async function readLocalBackup(dataDirectory, backupId) {
  if (!BACKUP_ID.test(backupId)) throw new Error('Geçersiz yedek kimliği.')
  const backupPath = path.join(dataDirectory, 'backups', backupId)
  const metadata = validateMetadata(JSON.parse(await fs.readFile(backupPath.replace(/\.db$/, '.json'), 'utf8')))
  if (metadata.backup_id !== backupId) throw new Error('Yedek kimliği uyuşmuyor.')
  const bytes = await fs.readFile(backupPath)
  verifyBytes(metadata, bytes)
  return { metadata, bytes, backupPath }
}

async function exportBundle(dataDirectory, backupId, destination) {
  const { metadata, bytes } = await readLocalBackup(dataDirectory, backupId)
  const bundle = { format: 'ksbackup-v1', metadata, database_base64: bytes.toString('base64') }
  await fs.writeFile(destination, JSON.stringify(bundle), { flag: 'w' })
}

async function importBundle(dataDirectory, source) {
  const stat = await fs.stat(source)
  if (stat.size > MAX_BACKUP_BYTES * 1.4) throw new Error('Yedek paketi 256 MB sınırını aşıyor.')
  const bundle = JSON.parse(await fs.readFile(source, 'utf8'))
  if (bundle.format !== 'ksbackup-v1' || typeof bundle.database_base64 !== 'string') throw new Error('Desteklenmeyen yedek paketi.')
  const metadata = validateMetadata(bundle.metadata)
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(bundle.database_base64)) throw new Error('Yedek içeriği geçersiz.')
  const bytes = Buffer.from(bundle.database_base64, 'base64')
  verifyBytes(metadata, bytes)
  const backupDir = path.join(dataDirectory, 'backups')
  await fs.mkdir(backupDir, { recursive: true })
  const backupPath = path.join(backupDir, metadata.backup_id)
  const metadataPath = backupPath.replace(/\.db$/, '.json')
  try {
    const existing = await readLocalBackup(dataDirectory, metadata.backup_id)
    if (existing.metadata.sha256 === metadata.sha256) return { backupId: existing.metadata.backup_id, created: false }
    throw new Error('Aynı kimlikte farklı içerikli bir yedek zaten var.')
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
  }
  let createdDatabase = false
  try {
    await fs.writeFile(backupPath, bytes, { flag: 'wx' })
    createdDatabase = true
    await fs.writeFile(metadataPath, JSON.stringify(metadata), { flag: 'wx' })
  } catch (error) {
    if (createdDatabase) await fs.rm(backupPath, { force: true }).catch(() => {})
    throw error
  }
  return { backupId: metadata.backup_id, created: true }
}

module.exports = { exportBundle, importBundle, readLocalBackup }
