import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiRequest, formatMoney } from './lib/api'
import { ErrorState, LoadingRows } from './components/ui'

type Aging = { open_receivable_kurus: number; overdue_kurus: number; advance_kurus: number; unscheduled_kurus: number; buckets: Array<{ bucket: string; amount_kurus: number; count: number }>; items: Array<{ receivable_schedule_id: string | null; project_id: string | null; title: string; remaining_kurus: number; due_date: string | null; days_overdue: number | null }> }
export function CustomerAging({ customerId }: { customerId: string }) {
  const query = useQuery({ queryKey: ['customer-aging-view', customerId], queryFn: () => apiRequest<Aging>(`/api/v1/customers/${customerId}/aging`) })
  if (query.isLoading) return <LoadingRows />
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  if (!query.data) return null
  return <><div className="p0-metrics"><div><span>Açık alacak</span><strong>{formatMoney(query.data.open_receivable_kurus)}</strong></div><div><span>Gecikmiş</span><strong>{formatMoney(query.data.overdue_kurus)}</strong></div><div><span>Avans</span><strong>{formatMoney(query.data.advance_kurus)}</strong></div><div><span>Plansız</span><strong>{formatMoney(query.data.unscheduled_kurus)}</strong></div></div>{query.data.buckets.map((bucket) => <div className="p0-row" key={bucket.bucket}><strong>{bucket.bucket}</strong><span>{bucket.count} kayıt</span><b>{formatMoney(bucket.amount_kurus)}</b></div>)}<h3>Açık kalemler</h3>{query.data.items.map((item, index) => <div className="p0-row" key={`${item.receivable_schedule_id}-${index}`}><strong>{item.title}</strong><span>Vade: {item.due_date || 'Yok'}</span><span>{item.days_overdue ? `${item.days_overdue} gün gecikmiş` : ''}</span><b>{formatMoney(item.remaining_kurus)}</b>{item.project_id && <Link to={`/projeler?project=${item.project_id}`}>Proje</Link>}</div>)}</>
}
