export type PriceCurrency = 'TRY' | 'USD' | 'EUR' | 'GBP'

/** TL fields that may be empty while a quote is being prepared. */
export function formatTlInput(raw: string): string {
  const numeric = raw.replace(/[^\d,.]/g, '')
  const comma = numeric.indexOf(',')
  const whole = (comma < 0 ? numeric : numeric.slice(0, comma)).replace(/\D/g, '').replace(/^0+(?=\d)/, '')
  const fraction = comma < 0 ? '' : numeric.slice(comma + 1).replace(/\D/g, '').slice(0, 2)
  if (!whole && !fraction) return ''
  return `${(whole || '0').replace(/\B(?=(\d{3})+(?!\d))/g, '.')}${comma < 0 ? '' : `,${fraction}`}`
}

const symbols: Record<PriceCurrency, string> = { TRY: '₺', USD: '$', EUR: '€', GBP: '£' }

export function formatPriceInput(raw: string, currency: PriceCurrency): string {
  const numeric = raw.replace(/[^\d,.]/g, '')
  const comma = numeric.indexOf(',')
  const wholeDigits = (comma < 0 ? numeric : numeric.slice(0, comma)).replace(/\D/g, '').replace(/^0+(?=\d)/, '')
  const fraction = comma < 0 ? '' : numeric.slice(comma + 1).replace(/\D/g, '').slice(0, 2)
  if (!wholeDigits && !fraction) return ''
  const whole = (wholeDigits || '0').replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${whole},${fraction.padEnd(2, '0')}${symbols[currency]}`
}

export function priceInputFromMinor(minor: number | null | undefined, currency: PriceCurrency): string {
  if (minor == null) return ''
  const whole = Math.floor(minor / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${whole},${String(minor % 100).padStart(2, '0')}${symbols[currency]}`
}

export function minorFromPriceInput(value: string): number {
  if (!value) return 0
  const numeric = value.replace(/[^\d,.]/g, '')
  const [whole, fraction = ''] = numeric.split(',', 2)
  const minor = Number(whole.replace(/\D/g, '')) * 100 + Number(fraction.replace(/\D/g, '').slice(0, 2).padEnd(2, '0'))
  return Number.isSafeInteger(minor) ? minor : 0
}

export function convertMinorAtRate(minor: number, rate: string): number {
  const match = /^(\d+)(?:[.,](\d{1,6}))?$/.exec(rate.trim())
  if (!match || !Number.isSafeInteger(minor) || minor < 0) return 0
  const scaled = BigInt(match[1]) * 1_000_000n + BigInt((match[2] ?? '').padEnd(6, '0'))
  const converted = (BigInt(minor) * scaled + 500_000n) / 1_000_000n
  return converted <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(converted) : 0
}
