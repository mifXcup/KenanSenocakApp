import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, formatMoney, makeIdempotencyKey, toKurus } from './lib/api'
import { Button, ErrorState, LoadingRows } from './components/ui'

type Customer = { id: string; name: string; phone: string | null; address: string | null; contact_person: string | null; note: string | null }
type Collection = { id: string; amount_kurus: number; unallocated_kurus?: number; movement_type: string; movement_date: string; status: string }
type Schedule = { id: string; title: string; remaining_kurus: number }
type Allocation = { id: string; collection_id: string; receivable_schedule_id: string; amount_kurus: number; status: string }
export function CustomerExtras({ customer, collections, schedules }: { customer: Customer; collections: Collection[]; schedules: Schedule[] }) {
  const client = useQueryClient()
  const [name, setName] = useState(customer.name)
  const [phone, setPhone] = useState(customer.phone || '')
  const [address, setAddress] = useState(customer.address || '')
  const [collectionId, setCollectionId] = useState('')
  const [scheduleId, setScheduleId] = useState('')
  const [amount, setAmount] = useState('')
  const [message, setMessage] = useState('')
  const allocations = useQuery({ queryKey: ['customer-allocations', customer.id], queryFn: () => apiRequest<Allocation[]>(`/api/v1/customer-payment-allocations?customer_id=${customer.id}&include_cancelled=true`) })
  async function mutate(path: string, method: string, body: unknown) { try { setMessage(''); await apiRequest(path, { method, body }); await client.invalidateQueries(); setMessage('Kaydedildi.') } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) } }
  return <><section className="panel p0-section"><h2>Müşteri kartı</h2><div className="p0-controls"><label>Ad <input value={name} onChange={(e) => setName(e.target.value)} /></label><label>Telefon <input value={phone} onChange={(e) => setPhone(e.target.value)} /></label><label>Adres <input value={address} onChange={(e) => setAddress(e.target.value)} /></label><Button onClick={() => mutate(`/api/v1/customers/${customer.id}`, 'PATCH', { name, phone: phone || null, address: address || null })}>Güncelle</Button></div></section>
    <section className="panel p0-section"><h2>Tahsilat dağıtımı</h2>{allocations.isLoading ? <LoadingRows /> : allocations.error ? <ErrorState error={allocations.error} onRetry={() => allocations.refetch()} /> : allocations.data?.map((item) => <div className="p0-row" key={item.id}><strong>{schedules.find((schedule) => schedule.id === item.receivable_schedule_id)?.title || item.receivable_schedule_id}</strong><span>{formatMoney(item.amount_kurus)}</span><span>{item.status}</span>{item.status === 'active' && <Button onClick={() => mutate(`/api/v1/customer-payment-allocations/${item.id}/cancel`, 'POST', { reason: 'Kullanıcı düzeltmesi' })}>Dağıtımı iptal et</Button>}</div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); mutate('/api/v1/customer-payment-allocations', 'POST', { collection_id: collectionId, receivable_schedule_id: scheduleId, amount_kurus: toKurus(amount), allocation_date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()), idempotency_key: makeIdempotencyKey('allocation') }) }}><label>Tahsilat <select required value={collectionId} onChange={(e) => setCollectionId(e.target.value)}><option value="">Seçin</option>{collections.filter((item) => item.movement_type === 'collection' && item.status === 'active' && (item.unallocated_kurus || 0) > 0).map((item) => <option key={item.id} value={item.id}>{item.movement_date} · {formatMoney(item.unallocated_kurus)}</option>)}</select></label><label>Plan <select required value={scheduleId} onChange={(e) => setScheduleId(e.target.value)}><option value="">Seçin</option>{schedules.filter((item) => item.remaining_kurus > 0).map((item) => <option key={item.id} value={item.id}>{item.title} · {formatMoney(item.remaining_kurus)}</option>)}</select></label><label>Tutar TL <input required value={amount} onChange={(e) => setAmount(e.target.value)} /></label><Button variant="primary" disabled={!collectionId || !scheduleId || !amount}>Dağıt</Button></form></section>{message && <p role="status">{message}</p>}
  </>
}
