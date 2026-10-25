import { apiRequest } from './api'
import type { BackupRecord, BackupStatus, RestoreResult } from './types'

export const backupApi = {
  status: () => apiRequest<BackupStatus>('/api/v1/backups/status'),
  list: () => apiRequest<BackupRecord[]>('/api/v1/backups'),
  create: () => apiRequest<BackupRecord>('/api/v1/backups', { method: 'POST' }),
  verify: (backupId: string) => apiRequest<BackupRecord>(`/api/v1/backups/${encodeURIComponent(backupId)}/verify`, { method: 'POST' }),
  restore: (backupId: string) => apiRequest<RestoreResult>(`/api/v1/backups/${encodeURIComponent(backupId)}/restore`, { method: 'POST' }),
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} KB`
  return `${(bytes / (1024 * 1024)).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} MB`
}

export function backupReasonLabel(kind: BackupRecord['kind']): string {
  if (kind === 'manual') return 'Manuel'
  if (kind === 'pre_restore') return 'Geri yükleme öncesi'
  return 'Otomatik'
}

export function backupIntegrityLabel(integrity: BackupRecord['integrity']): string {
  if (integrity === 'ok') return 'Doğrulandı'
  return 'Bilinmiyor'
}
