export type RangePreset = 'month' | 'last30' | 'year' | 'all'

export interface DateRange {
  from: string
  to: string
}

function shiftDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function rangeFor(preset: RangePreset, today: string): DateRange {
  switch (preset) {
    case 'month':
      return { from: `${today.slice(0, 7)}-01`, to: today }
    case 'last30':
      return { from: shiftDays(today, -29), to: today }
    case 'year':
      return { from: `${today.slice(0, 4)}-01-01`, to: today }
    case 'all':
      return { from: '', to: '' }
  }
}

export function rangeError(range: DateRange): string | undefined {
  if (range.from && range.to && range.from > range.to) return 'Başlangıç tarihi bitiş tarihinden sonra olamaz.'
  return undefined
}

export function monthLabel(month: string): string {
  const [year, mm] = month.split('-')
  return new Intl.DateTimeFormat('tr-TR', { month: 'long', year: 'numeric' }).format(new Date(Number(year), Number(mm) - 1, 1))
}
