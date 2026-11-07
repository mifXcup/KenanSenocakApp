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

/**
 * Türkçe tutar girdisini kuruşa çevirir. Geçersiz girdi 0 döner (arayüz 0'ı reddeder).
 * "1.250,75", "1250,75", "1250.75" ve "1.250" desteklenir; noktanın binlik mi ondalık mı
 * olduğu sonundaki hane sayısına göre belirlenir (tam 3 hane = binlik).
 */
export function toKurus(input: string): number {
  const text = input.trim().replace(/\s/g, '')
  let normalized: string
  if (/^\d+$/.test(text)) normalized = text
  else if (/^\d{1,3}(\.\d{3})*,\d{1,2}$/.test(text) || /^\d+,\d{1,2}$/.test(text)) normalized = text.replace(/\./g, '').replace(',', '.')
  else if (/^\d{1,3}(\.\d{3})+$/.test(text)) normalized = text.replace(/\./g, '')
  else if (/^\d+\.\d{1,2}$/.test(text)) normalized = text
  else return 0
  const value = Number(normalized)
  return Number.isFinite(value) ? Math.round(value * 100) : 0
}

const PAGE_SIZE = 500

/** Sayfalı liste uçlarının tamamını getirir (backend sayfa başına en çok 500 kayıt verir). */
export async function apiList<T>(path: string): Promise<T[]> {
  const separator = path.includes('?') ? '&' : '?'
  const result: T[] = []
  for (let offset = 0; offset < 100_000; offset += PAGE_SIZE) {
    const page = await apiRequest<T[]>(`${path}${separator}limit=${PAGE_SIZE}&offset=${offset}`)
    result.push(...page)
    if (page.length < PAGE_SIZE) break
  }
  return result
}

export const formatMoney = (value: number | null | undefined) =>
  value == null
    ? 'Veri yok'
    : new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(value / 100)

export const formatCurrency = (valueMinor: number | null | undefined, currency: 'TRY' | 'USD' | 'EUR' | 'GBP') =>
  valueMinor == null
    ? 'Veri yok'
    : new Intl.NumberFormat('tr-TR', { style: 'currency', currency }).format(valueMinor / 100)

export const formatDate = (value: string) =>
  new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`))
