// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CashReceipt } from './cashReceipt'

describe('elden ödeme teslim belgesi', () => {
  it('ödeme kaydı ve kalan borcu aynı belgede gösterir', () => {
    render(<CashReceipt receipt={{
      movementId: 'pay-123', employeeName: 'Emir Şenocak', identityNumber: '12345678901',
      periodTitle: 'Kasım 2026', paymentDate: '2026-11-10', amountKurus: 500_000,
      beforeKurus: 3_000_000, afterKurus: 2_500_000,
    }} />)
    const document = screen.getByRole('article', { name: 'Elden ücret ödeme teslim belgesi' })
    expect(document.textContent).toContain('pay-123')
    expect(document.textContent).toContain('Emir Şenocak')
    expect(document.textContent).toContain('12345678901')
    expect(document.textContent).toContain('25.000')
    expect(document.textContent).toContain('5.000')
    expect(document.textContent).toContain('ibra beyanı içermez')
  })
})
