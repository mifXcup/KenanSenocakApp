import type { ApiErrorShape } from './types'

export class ApiError extends Error {
  status: number
  code: string
  details: unknown

  constructor(message: string, status = 0, code = 'unknown_error', details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

type RequestOptions = { method?: string; body?: unknown }

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (!window.ksDesktop) {
    throw new ApiError('Bu ekran yalnız Kenan Şenocak Yönetim masaüstü uygulamasında çalışır.', 0, 'desktop_bridge_missing')
  }

  const response = await window.ksDesktop.api.request<T | ApiErrorShape>({
    path,
    method: options.method ?? 'GET',
    body: options.body,
  })

  if (!response.ok) {
    const payload = response.data as ApiErrorShape
    throw new ApiError(
      payload?.error?.message ?? 'İşlem tamamlanamadı.',
      response.status,
      payload?.error?.code ?? 'request_failed',
      payload?.error?.details,
    )
  }

  return response.data as T
}

export function makeIdempotencyKey(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`
}

export function toKurus(input: string): number {
  const normalized = input.trim().replace(/\s/g, '').replace(/\./g, '').replace(',', '.')
  const value = Number(normalized)
  if (!Number.isFinite(value)) return 0
  return Math.round(value * 100)
}

export function fromKurus(value: number | null | undefined): string {
  if (value == null) return ''
  return (value / 100).toFixed(2).replace('.', ',')
}

export const formatMoney = (value: number | null | undefined) =>
  value == null
    ? 'Veri yok'
    : new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(value / 100)

export const formatDate = (value: string) =>
  new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`))
