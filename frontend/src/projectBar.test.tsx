// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MiniProjectBar } from './projectBar'

type Call = { path: string; method: string; body?: unknown }

const project = { id: 'p1', name: 'Villa Mutfak', accent_color: '#9A5A3A', progress_percent: 40, next_step: 'Ölçü al', customer_name: 'Ayşe' }
const hub = {
  project, notes: [], colors: [],
  visits: [],
  tasks: [
    { id: 't1', project_id: 'p1', title: 'Kapak siparişi', due_date: '2026-03-12', task_state: 'todo', waiting_on: null, note: null, created_at: '' },
    { id: 't2', project_id: 'p1', title: 'Eski iş', due_date: null, task_state: 'done', waiting_on: null, note: null, created_at: '' },
  ],
}
let calls: Call[]
let hideBar: ReturnType<typeof vi.fn>

function install(overrides: Record<string, unknown> = {}) {
  calls = []
  hideBar = vi.fn().mockResolvedValue({ visible: false })
  const answers: Record<string, unknown> = {
    '/api/v1/projects': [project],
    '/api/v1/projects/p1/hub': hub,
    '/api/v1/employees': [{ id: 'e1', name: 'Ahmet Usta', role: 'Marangoz', employment_state: 'active' }, { id: 'e2', name: 'Mehmet', role: null, employment_state: 'active' }],
    '/api/v1/work-logs': [{ id: 'l1', employee_id: 'e2', work_status: 'worked', status: 'active' }],
    ...overrides,
  }
  window.ksDesktop = {
    api: {
      request: vi.fn(async (request: { path: string; method?: string; body?: unknown }) => {
        const method = request.method ?? 'GET'
        const path = request.path.split('?')[0]
        calls.push({ path, method, body: request.body })
        if (method !== 'GET') return { ok: true, status: 201, data: {} }
        return { ok: true, status: 200, data: answers[path] ?? [] }
      }),
      downloadReport: vi.fn(),
      readSpreadsheet: vi.fn(),
    },
    app: {
      getInfo: vi.fn(), relaunch: vi.fn(), toggleProjectBar: vi.fn(), hideProjectBar: hideBar,
      setProjectBarExpanded: vi.fn().mockResolvedValue({ accepted: true }), showMain: vi.fn(),
      takePendingRoute: vi.fn(), notifyDataChanged: vi.fn(), onDataChanged: vi.fn(() => () => {}), onNavigate: vi.fn(() => () => {}),
    },
  } as unknown as Window['ksDesktop']
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MiniProjectBar /></QueryClientProvider>)
}

beforeEach(() => { localStorage.clear() })
afterEach(() => { cleanup(); delete window.ksDesktop })

describe('mini proje barı', () => {
  it('yalnız açık görevleri gösterir ve görevi tamamlar', async () => {
    install(); mount()
    expect(await screen.findByText('Kapak siparişi')).toBeTruthy()
    expect(screen.queryByText('Eski iş')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Kapak siparişi işini tamamla' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.path === '/api/v1/project-tasks/t1')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ task_state: 'done' })
  })

  it('yeni görev ve hızlı not ekler', async () => {
    install(); mount()
    await screen.findByText('Kapak siparişi')
    fireEvent.change(screen.getByLabelText('Yeni görev'), { target: { value: 'Menteşe al' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ekle' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v1/projects/p1/tasks')).toBe(true))
    expect(calls.find((c) => c.path.endsWith('/tasks') && c.method === 'POST')?.body).toEqual({ title: 'Menteşe al', due_date: null })

    fireEvent.click(screen.getByRole('button', { name: 'Not' }))
    fireEvent.change(screen.getByLabelText('Hızlı not'), { target: { value: 'Müşteri rengi beğendi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Kaydet' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v1/projects/p1/notes' && c.method === 'POST')).toBe(true))
  })

  it('puantaj sekmesinde kaydı olmayan personeli işaretler, olanı tekrar işaretletmez', async () => {
    install(); mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Bugünkü puantaj' }))
    expect(await screen.findByText('Ahmet Usta')).toBeTruthy()
    expect(screen.getByText('Çalıştı')).toBeTruthy()          // Mehmet'in kaydı zaten var
    expect(screen.getAllByRole('button', { name: 'Geldi' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Geldi' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v1/work-logs' && c.method === 'POST')).toBe(true))
    const body = calls.find((c) => c.path === '/api/v1/work-logs' && c.method === 'POST')?.body as Record<string, unknown>
    expect(body).toMatchObject({ employee_id: 'e1', work_status: 'worked', project_id: 'p1' })
  })

  it('Gelmedi kaydı projeye bağlanmaz', async () => {
    install(); mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Bugünkü puantaj' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Gelmedi' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v1/work-logs' && c.method === 'POST')).toBe(true))
    const posted = calls.find((c) => c.method === 'POST')
    expect((posted?.body as Record<string, unknown> | undefined)?.project_id).toBeNull()
  })

  it('gizle düğmesi ve Esc barı gizler', async () => {
    install(); mount()
    await screen.findByText('Kapak siparişi')
    fireEvent.click(screen.getByRole('button', { name: 'Barı gizle (Esc)' }))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(hideBar).toHaveBeenCalledTimes(2)
  })

  it('backend hatasını boş durum gibi göstermez', async () => {
    install()
    ;(window.ksDesktop!.api.request as ReturnType<typeof vi.fn>).mockImplementation(async () => ({ ok: false, status: 0, data: { error: { code: 'backend_unavailable', message: 'Yerel veri hizmetine ulaşılamadı.' } } }))
    mount()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText('Henüz proje bulunmuyor.')).toBeNull()
  })
})
