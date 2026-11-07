import { describe, expect, it } from 'vitest'
import { convertMinorAtRate, formatPriceInput, formatTlInput, minorFromPriceInput, priceInputFromMinor } from './moneyInput'

describe('canlı proje fiyatı girişi', () => {
  it('tam sayı yazılırken Türkçe para biçimine dönüştürür', () => {
    expect(formatPriceInput('300000', 'TRY')).toBe('300.000,00₺')
    expect(formatPriceInput('300.000,00₺', 'USD')).toBe('300.000,00$')
    expect(formatTlInput('403000')).toBe('403.000')
    expect(formatTlInput('403000,50')).toBe('403.000,50')
  })

  it('ondalık kuruşu ve kayıtlı tutarı korur', () => {
    expect(formatPriceInput('300000,75', 'EUR')).toBe('300.000,75€')
    expect(minorFromPriceInput('300.000,75€')).toBe(30000075)
    expect(priceInputFromMinor(30000075, 'GBP')).toBe('300.000,75£')
  })

  it('döviz kurunu kuruş hassasiyetinde TL karşılığına çevirir', () => {
    expect(convertMinorAtRate(10050, '42,25')).toBe(424613)
  })
})
