// @vitest-environment jsdom
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Button, Field, Modal, SideSheet, TextInput } from './ui'

afterEach(cleanup)

function SheetHarness() {
  const [open, setOpen] = useState(false)
  return <><button onClick={() => setOpen(true)}>Formu aç</button><SideSheet title="Kayıt" open={open} onClose={() => setOpen(false)} footer={<Button>Kaydet</Button>}><TextInput aria-label="Ad" /></SideSheet></>
}

describe('erişilebilir modal davranışı', () => {
  it('Escape ile kapanır ve odağı açan kontrole döndürür', () => {
    render(<SheetHarness />)
    const trigger = screen.getByRole('button', { name: 'Formu aç' })
    trigger.focus()
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('Modal Escape olayını kapatma işlevine iletir', () => {
    const onClose = vi.fn()
    render(<Modal title="Onay" open onClose={onClose}><p>Etki</p></Modal>)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('alan hatasını kontrolle aria üzerinden ilişkilendirir', () => {
    render(<Field label="Tutar" error="Tutar geçersiz"><TextInput /></Field>)
    const input = screen.getByRole('textbox', { name: 'Tutar' })
    const error = screen.getByText('Tutar geçersiz')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(input.getAttribute('aria-describedby')).toBe(error.id)
  })
})
