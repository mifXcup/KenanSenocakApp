import { describe, expect, it } from 'vitest'
import { rangeError, rangeFor } from './reportRange'

describe('reportRange', () => {
  it('hazır dönemleri bugüne göre hesaplar', () => {
    expect(rangeFor('month', '2026-10-25')).toEqual({ from: '2026-10-01', to: '2026-10-25' })
    expect(rangeFor('last30', '2026-10-25')).toEqual({ from: '2026-09-26', to: '2026-10-25' })
    expect(rangeFor('last30', '2026-03-05')).toEqual({ from: '2026-02-04', to: '2026-03-05' })
    expect(rangeFor('year', '2026-10-25')).toEqual({ from: '2026-01-01', to: '2026-10-25' })
    expect(rangeFor('all', '2026-10-25')).toEqual({ from: '', to: '' })
  })

  it('ters tarih aralığını reddeder', () => {
    expect(rangeError({ from: '2026-11-01', to: '2026-10-01' })).toBeTruthy()
    expect(rangeError({ from: '2026-10-01', to: '' })).toBeUndefined()
  })
})
