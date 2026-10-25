import { describe, expect, it } from 'vitest'
import { formatMoney, fromKurus, toKurus } from './api'

describe('Türkçe para yardımcıları', () => {
  it('yerel ondalık girdiyi kuruşa çevirir', () => {
    expect(toKurus('1.250,75')).toBe(125075)
  })

  it('kuruşu düzenlenebilir Türkçe metne çevirir', () => {
    expect(fromKurus(125075)).toBe('1250,75')
  })

  it('eksik mali değeri dürüstçe gösterir', () => {
    expect(formatMoney(null)).toBe('Veri yok')
  })
})
