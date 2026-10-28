import { describe, expect, it } from 'vitest'
import { profitTone } from './profitabilityUtils'

describe('proje kârlılık sunumu', () => {
  it('pozitif, negatif ve bilinmeyen tutarları ayırır', () => {
    expect(profitTone(1)).toBe('positive')
    expect(profitTone(-1)).toBe('negative')
    expect(profitTone(0)).toBe('neutral')
    expect(profitTone(null)).toBe('neutral')
  })
})
