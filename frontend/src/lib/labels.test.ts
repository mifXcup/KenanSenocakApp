import { describe, expect, it } from 'vitest'
import { eventStateLabel, lifecycleLabel, movementTypeLabel, statusLabel } from './labels'

describe('Türkçe etiketler', () => {
  it('bilinen kodları Türkçeye çevirir', () => {
    expect(statusLabel('active')).toBe('Aktif')
    expect(lifecycleLabel('received')).toBe('Teslim alındı')
    expect(movementTypeLabel('collection')).toBe('Tahsilat')
    expect(eventStateLabel('overdue')).toBe('Gecikmiş')
  })

  it('bilinmeyen kodu olduğu gibi, boş değeri boş döndürür', () => {
    expect(statusLabel('yeni_durum')).toBe('yeni_durum')
    expect(statusLabel(null)).toBe('')
  })
})
