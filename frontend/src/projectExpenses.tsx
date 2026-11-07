import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiList, apiRequest, formatMoney, toKurus } from './lib/api'
import { Button, ErrorState, LoadingRows } from './components/ui'

type Expense = { id: string; project_id: string; site_id: string | null; expense_date: string; category: string; amount_kurus: number; description: string | null; status: string }

const categoryLabels: Record<string, string> = {
  shipping: 'Nakliye',
  installation: 'Montaj',
  site: 'Şantiye',
  subcontract: 'Taşeron',
  rework: 'Yeniden iş',
  other: 'Diğer',
}

const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())

export function ProjectExpenses({ projectId }: { projectId: string }) {
  const client = useQueryClient()
  const [date, setDate] = useState(today())
  const [category, setCategory] = useState('shipping')
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const expenses = useQuery({ queryKey: ['project-expenses', projectId], queryFn: () => apiList<Expense>(`/api/v1/project-expenses?project_id=${projectId}`) })
  const refresh = () => { client.invalidateQueries({ queryKey: ['project-expenses', projectId] }); client.invalidateQueries({ queryKey: ['profitability'] }); client.invalidateQueries({ queryKey: ['projects'] }) }
  const create = useMutation({
    mutationFn: () => apiRequest('/api/v1/project-expenses', { method: 'POST', body: { project_id: projectId, expense_date: date, category, amount_kurus: toKurus(amount), description: description.trim() || null } }),
    onSuccess: () => { setAmount(''); setDescription(''); setError(''); refresh() },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  })
  const cancel = useMutation({
    mutationFn: (id: string) => apiRequest(`/api/v1/project-expenses/${id}/cancel`, { method: 'POST', body: {} }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  })
  const active = (expenses.data ?? []).filter((item) => item.status === 'active')
  const total = active.reduce((sum, item) => sum + item.amount_kurus, 0)
  const valid = toKurus(amount) > 0

  return <section className="panel p0-section" aria-label="Proje giderleri">
    <h2>Nakliye, montaj ve diğer giderler <small>{formatMoney(total)}</small></h2>
    {expenses.isLoading ? <LoadingRows count={2} /> : expenses.error ? <ErrorState error={expenses.error} onRetry={() => expenses.refetch()} /> : !active.length ? <p>Bu projeye işlenmiş gider yok.</p> : active.map((item) => <div className="p0-row" key={item.id}>
      <span>{item.expense_date}</span><strong>{categoryLabels[item.category] ?? item.category}</strong><span>{item.description ?? ''}</span><b>{formatMoney(item.amount_kurus)}</b>
      <Button disabled={cancel.isPending} onClick={() => cancel.mutate(item.id)}>İptal et</Button>
    </div>)}
    <form className="p0-controls" onSubmit={(e) => { e.preventDefault(); if (valid) create.mutate() }}>
      <input type="date" aria-label="Gider tarihi" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
      <select aria-label="Gider türü" value={category} onChange={(e) => setCategory(e.target.value)}>{Object.entries(categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <input aria-label="Gider tutarı TL" placeholder="Tutar TL" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <input aria-label="Gider açıklaması" placeholder="Açıklama (isteğe bağlı)" value={description} onChange={(e) => setDescription(e.target.value)} />
      <Button variant="primary" loading={create.isPending} disabled={!valid}>Gider ekle</Button>
    </form>
    {error && <p role="alert">{error}</p>}
  </section>
}
