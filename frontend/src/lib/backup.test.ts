import { describe, expect, it } from 'vitest'
import { backupIntegrityLabel, backupReasonLabel, formatFileSize } from './backup'

describe('yedekleme görünüm yardımcıları', () => {
  it('dosya boyutunu okunabilir gösterir', () => {
    expect(formatFileSize(1_572_864)).toBe('1,5 MB')
  })

  it('yedek nedeni ve bütünlüğünü açık metinle gösterir', () => {
    expect(backupReasonLabel('pre_restore')).toBe('Geri yükleme öncesi')
    expect(backupIntegrityLabel('ok')).toBe('Doğrulandı')
  })
})
