import { describe, expect, it } from 'vitest'
import { formatMoney, toKurus } from './api'

describe('Türkçe para yardımcıları', () => {
  it('yerel ondalık girdiyi kuruşa çevirir', () => {
    expect(toKurus('1.250,75')).toBe(125075)
  })

  it('nokta ve virgül girdilerini 100 kat hata üretmeden çevirir', () => {
    expect(toKurus('1234.50')).toBe(123450)
    expect(toKurus('1.5')).toBe(150)
    expect(toKurus('1.250')).toBe(125000)
    expect(toKurus('12,5')).toBe(1250)
    expect(toKurus('1234')).toBe(123400)
  })

  it('geçersiz girdiyi sıfır sayar', () => {
    for (const bad of ['abc', '-5', '1e3', '1,2,3', '1.2345', '']) expect(toKurus(bad)).toBe(0)
  })

  it('eksik mali değeri dürüstçe gösterir', () => {
    expect(formatMoney(null)).toBe('Veri yok')
  })
})
