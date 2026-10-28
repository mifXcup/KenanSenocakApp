export function profitTone(value: number | null): 'positive' | 'negative' | 'neutral' {
  if (value == null || value === 0) return 'neutral'
  return value > 0 ? 'positive' : 'negative'
}

