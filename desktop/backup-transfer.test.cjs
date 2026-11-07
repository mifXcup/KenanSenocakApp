const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const crypto = require('node:crypto')
const { exportBundle, importBundle, readLocalBackup } = require('./backup-transfer.cjs')

const backupId = 'ks-20261029-120000-123456-manual.db'

test('backup bundle round trips and rejects a tampered database', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ks-backup-test-'))
  try {
    const source = path.join(root, 'source')
    const target = path.join(root, 'target')
    await fs.mkdir(path.join(source, 'backups'), { recursive: true })
    const bytes = Buffer.concat([Buffer.from('SQLite format 3\0'), Buffer.alloc(128, 42)])
    const metadata = { backup_id: backupId, kind: 'manual', created_at: '2026-10-29T12:00:00Z', size_bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex'), app_version: '0.5.0', integrity: 'ok' }
    await fs.writeFile(path.join(source, 'backups', backupId), bytes)
    await fs.writeFile(path.join(source, 'backups', backupId.replace(/\.db$/, '.json')), JSON.stringify(metadata))
    const bundlePath = path.join(root, 'transfer.ksbackup')
    await exportBundle(source, backupId, bundlePath)
    assert.deepEqual(await importBundle(target, bundlePath), { backupId, created: true })
    assert.deepEqual((await readLocalBackup(target, backupId)).bytes, bytes)
    assert.deepEqual(await importBundle(target, bundlePath), { backupId, created: false })
    const altered = JSON.parse(await fs.readFile(bundlePath, 'utf8'))
    altered.database_base64 = Buffer.concat([Buffer.from('SQLite format 3\0'), Buffer.alloc(128, 43)]).toString('base64')
    await fs.writeFile(bundlePath, JSON.stringify(altered))
    await assert.rejects(importBundle(path.join(root, 'altered'), bundlePath), /bütünlük/)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})
