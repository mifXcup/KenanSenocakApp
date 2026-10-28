import { describe, expect, it } from 'vitest'
import { navigationGroups, navigationItems, navigationLabel } from './appNavigation'

describe('masaüstü bilgi mimarisi', () => {
  it('rotaları tekil tutar', () => {
    const routes = navigationItems.map((item) => item.to)
    expect(new Set(routes).size).toBe(routes.length)
  })

  it('P0 modüllerini doğru gruplarda sunar', () => {
    expect(navigationGroups.map((group) => group.label)).toEqual(['Operasyon', 'Finans', 'Personel', 'Analiz', 'Sistem'])
    expect(navigationItems.map((item) => item.to)).toContain('/takvim')
    expect(navigationItems.map((item) => item.to)).toContain('/proje-karliligi')
    expect(navigationItems.map((item) => item.to)).toContain('/puantaj-izin')
    expect(navigationItems.map((item) => item.to)).not.toContain('/is-takibi')
  })

  it('araç çubuğu bağlamını rotadan bulur', () => {
    expect(navigationLabel('/musteriler')).toBe('Müşteri Cari')
    expect(navigationLabel('/bilinmeyen')).toBe('Kenan Şenocak Yönetim')
  })
})
