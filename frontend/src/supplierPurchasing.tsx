import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { apiList, apiRequest, formatMoney, makeIdempotencyKey, toKurus } from './lib/api'
import type { Material, Payment, Purchase, Supplier } from './lib/types'
import { Button, EmptyState, ErrorState, LoadingRows, PageHeader } from './components/ui'
import { SupplierPrices } from './supplierPrices'
import { ledgerRowLabel, statusLabel, lifecycleLabel } from './lib/labels'

const businessDate = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
type Receipt = { id: string; receipt_date: string; amount_kurus: number; quantity: string | null; note: string | null; status: string; warnings?: Array<{ message: string }> }
export function PurchasingPage({ onNewPurchase }: { onNewPurchase: () => void }) {
  const client = useQueryClient()
  const [params] = useSearchParams()
  const requestedPurchase = params.get('purchase')
  const [selectedId, setSelectedId] = useState(requestedPurchase || '')
  const [seen_requestedPurchase, setSeen_requestedPurchase] = useState(requestedPurchase)
  if (requestedPurchase !== seen_requestedPurchase) { setSeen_requestedPurchase(requestedPurchase); if (requestedPurchase) setSelectedId(requestedPurchase) }
  const [amount, setAmount] = useState('')
  const [quantity, setQuantity] = useState('')
  const [note, setNote] = useState('')
  const [date, setDate] = useState(businessDate())
  const [error, setError] = useState('')
  const purchases = useQuery({ queryKey: ['purchasing-purchases'], queryFn: () => apiList<Purchase>('/api/v1/purchases') })
  const suppliers = useQuery({ queryKey: ['purchasing-suppliers'], queryFn: () => apiList<Supplier>('/api/v1/suppliers') })
  const materials = useQuery({ queryKey: ['purchasing-materials'], queryFn: () => apiList<Material>('/api/v1/materials') })
  const selected = purchases.data?.find((item) => item.id === selectedId) || purchases.data?.[0]
  const receipts = useQuery({ queryKey: ['purchase-receipts', selected?.id], enabled: !!selected, queryFn: () => apiRequest<{ receipts?: Receipt[]; warnings?: Array<{ message: string }> } | Receipt[]>(`/api/v1/purchases/${selected!.id}/receipts?include_cancelled=true`) })
  const payments = useQuery({ queryKey: ['purchase-payments', selected?.id], enabled: !!selected, queryFn: () => apiList<Payment>(`/api/v1/payments?supplier_id=${selected!.supplier_id}`) })
  const receiptList = Array.isArray(receipts.data) ? receipts.data : receipts.data?.receipts || []
  async function post(path: string, body: unknown) { try { setError(''); await apiRequest(path, { method: 'POST', body }); await client.invalidateQueries(); setAmount(''); setQuantity(''); setNote('') } catch (e) { setError(e instanceof Error ? e.message : String(e)) } }
  return <div className="page"><PageHeader title="Satın Almalar" description="Sipariş, teslim fişi, taahhüt ve ödemeleri kaynağında izleyin." action={<Button variant="primary" onClick={onNewPurchase}>Satın alma ekle</Button>} />
    {purchases.isLoading ? <LoadingRows /> : purchases.error ? <ErrorState error={purchases.error} onRetry={() => purchases.refetch()} /> : !purchases.data?.length ? <EmptyState title="Satın alma yok" description="İlk siparişi ekleyin." /> : <div className="p0-two-col"><aside className="panel p0-section">{purchases.data.map((item) => <button className="p0-select-row" key={item.id} onClick={() => setSelectedId(item.id)}><strong>{materials.data?.find((material) => material.id === item.material_id)?.name || 'Malzeme'}</strong><small>{suppliers.data?.find((supplier) => supplier.id === item.supplier_id)?.name} · {lifecycleLabel(item.lifecycle_state || 'received')}</small></button>)}</aside>{selected && <div>
      <section className="panel p0-section"><h2>{materials.data?.find((item) => item.id === selected.material_id)?.name || 'Satın alma'}</h2><p>{suppliers.data?.find((item) => item.id === selected.supplier_id)?.name} · {selected.purchase_date} · {lifecycleLabel(selected.lifecycle_state)}</p><div className="p0-metrics"><div><span>Sipariş tutarı</span><strong>{formatMoney(selected.total_kurus)}</strong></div><div><span>Teslim alınan gerçek</span><strong>{formatMoney(selected.received_kurus)}</strong></div><div><span>Bekleyen taahhüt</span><strong>{formatMoney(Math.max(0, selected.total_kurus - (selected.received_kurus || 0)))}</strong></div></div><div className="p0-controls">{selected.lifecycle_state === 'planned' && <Button onClick={() => post(`/api/v1/purchases/${selected.id}/lifecycle`, { state: 'ordered' })}>Sipariş verildi</Button>}{['planned', 'ordered', 'partially_received'].includes(selected.lifecycle_state || '') && <Button onClick={() => post(`/api/v1/purchases/${selected.id}/lifecycle`, { state: 'received', receipt_date: businessDate(), idempotency_key: makeIdempotencyKey('receipt') })}>Tam teslim</Button>}{['planned', 'ordered'].includes(selected.lifecycle_state || '') && <Button onClick={() => post(`/api/v1/purchases/${selected.id}/lifecycle`, { state: 'cancelled' })}>Siparişi iptal et</Button>}</div></section>
      <section className="panel p0-section"><h2>Satın alma işlemleri</h2><div className="p0-controls"><Button onClick={() => { if (window.confirm('Bu satın alma iptal edilsin mi? Ödemesi varsa önce ödeme ters kaydı yapılmalıdır.')) post(`/api/v1/purchases/${selected.id}/cancel`, {}) }}>Satın almayı iptal et</Button></div></section>
      <section className="panel p0-section"><h2>Teslim fişleri</h2>{receipts.isLoading ? <LoadingRows /> : receipts.error ? <ErrorState error={receipts.error} onRetry={() => receipts.refetch()} /> : receiptList.map((item) => <div className="p0-row" key={item.id}><span>{item.receipt_date}</span><strong>{formatMoney(item.amount_kurus)}</strong><span>{item.quantity || '—'} {selected.unit}</span><span>{statusLabel(item.status)}</span>{item.warnings?.map((warning, i) => <span role="alert" key={i}>{warning.message}</span>)}{item.status === 'active' && <Button onClick={() => post(`/api/v1/purchase-receipts/${item.id}/cancel`, { reason: 'Kullanıcı iptali' })}>İptal et</Button>}</div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); post(`/api/v1/purchases/${selected.id}/receipts`, { receipt_date: date, amount_kurus: toKurus(amount), quantity: quantity || null, note: note || null, idempotency_key: makeIdempotencyKey('receipt') }) }}><input aria-label="Teslim tarihi" type="date" value={date} onChange={(e) => setDate(e.target.value)} /><input aria-label="Teslim tutarı TL" placeholder="Tutar TL" value={amount} onChange={(e) => setAmount(e.target.value)} /><input aria-label="Teslim miktarı" placeholder="Miktar" value={quantity} onChange={(e) => setQuantity(e.target.value)} /><input aria-label="Teslim notu" placeholder="Not" value={note} onChange={(e) => setNote(e.target.value)} /><Button variant="primary" disabled={!amount}>Fiş ekle</Button></form></section>
      <section className="panel p0-section"><h2>Ödemeler</h2>{payments.data?.filter((item) => item.purchase_id === selected.id).map((item) => <div className="p0-row" key={item.id}><span>{item.payment_date}</span><strong>{formatMoney(item.amount_kurus)}</strong><span>{statusLabel(item.status)}</span>{item.status === 'active' && <Button onClick={() => post(`/api/v1/payments/${item.id}/reverse`, {})}>Ters kayıt</Button>}</div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); post('/api/v1/payments', { supplier_id: selected.supplier_id, purchase_id: selected.id, payment_date: date, amount_kurus: toKurus(amount), note: note || null, idempotency_key: makeIdempotencyKey('payment') }) }}><input aria-label="Ödeme tarihi" type="date" value={date} onChange={(e) => setDate(e.target.value)} /><input aria-label="Ödeme tutarı TL" placeholder="Tutar TL" value={amount} onChange={(e) => setAmount(e.target.value)} /><Button variant="primary" disabled={!amount}>Ödeme kaydet</Button></form></section>
      {error && <p role="alert">{error}</p>}
    </div>}</div>}
  </div>
}

export function SupplierLedgerPage() {
  const client = useQueryClient()
  const [params] = useSearchParams()
  const requestedSupplier = params.get('supplier')
  const [selectedId, setSelectedId] = useState(requestedSupplier || '')
  const [seen_requestedSupplier, setSeen_requestedSupplier] = useState(requestedSupplier)
  if (requestedSupplier !== seen_requestedSupplier) { setSeen_requestedSupplier(requestedSupplier); if (requestedSupplier) setSelectedId(requestedSupplier) }
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(businessDate())
  const [error, setError] = useState('')
  const suppliers = useQuery({ queryKey: ['supplier-ledger-list'], queryFn: () => apiList<Supplier>('/api/v1/suppliers') })
  const selected = suppliers.data?.find((item) => item.id === selectedId) || suppliers.data?.[0]
  const statement = useQuery({ queryKey: ['supplier-statement', selected?.id], enabled: !!selected, queryFn: () => apiRequest<{ closing_balance_kurus: number; rows: Array<{ row_type: string; source_id: string; date: string; increase_kurus: number; decrease_kurus: number; balance_kurus: number; purchase_id: string | null }> }>(`/api/v1/suppliers/${selected!.id}/statement`) })
  const aging = useQuery({ queryKey: ['supplier-aging', selected?.id], enabled: !!selected, queryFn: () => apiRequest<{ total_open_kurus: number; overdue_kurus: number; credit_kurus: number; buckets: Array<{ key: string; label: string; amount_kurus: number }> }>(`/api/v1/suppliers/${selected!.id}/aging`) })
  const payments = useQuery({ queryKey: ['supplier-payments', selected?.id], enabled: !!selected, queryFn: () => apiList<Payment>(`/api/v1/payments?supplier_id=${selected!.id}`) })
  async function post(path: string, body: unknown) { try { setError(''); await apiRequest(path, { method: 'POST', body }); await client.invalidateQueries(); setAmount('') } catch (e) { setError(e instanceof Error ? e.message : String(e)) } }
  return <div className="page"><PageHeader title="Tedarikçi Cari" description="Teslim alınan gerçek borç, ödeme ve yaşlandırma." /><div className="p0-two-col"><aside className="panel p0-section"><h2>Firmalar</h2>{suppliers.isLoading ? <LoadingRows /> : suppliers.error ? <ErrorState error={suppliers.error} onRetry={() => suppliers.refetch()} /> : suppliers.data?.map((item) => <button className="p0-select-row" key={item.id} onClick={() => setSelectedId(item.id)}>{item.name}</button>)}<form onSubmit={(e) => { e.preventDefault(); post('/api/v1/suppliers', { name }) }}><h3>Yeni firma</h3><input aria-label="Firma adı" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /><Button variant="primary">Ekle</Button></form></aside><div>{selected ? <>
    <section className="panel p0-section"><h2>{selected.name}</h2><p>{selected.phone || 'Telefon girilmedi'}</p><div className="p0-metrics"><div><span>Güncel borç</span><strong>{formatMoney(statement.data?.closing_balance_kurus)}</strong></div><div><span>Vadesi geçmiş</span><strong>{formatMoney(aging.data?.overdue_kurus)}</strong></div><div><span>Avans</span><strong>{formatMoney(aging.data?.credit_kurus)}</strong></div></div></section>
    <section className="panel p0-section"><h2>Ekstre</h2>{statement.isLoading ? <LoadingRows /> : statement.error ? <ErrorState error={statement.error} onRetry={() => statement.refetch()} /> : statement.data?.rows.map((row) => <div className="p0-row" key={`${ledgerRowLabel(row.row_type)}-${row.source_id}`}><span>{row.date}</span><strong>{ledgerRowLabel(row.row_type)}</strong><span>Artış {formatMoney(row.increase_kurus)}</span><span>Azalış {formatMoney(row.decrease_kurus)}</span><b>{formatMoney(row.balance_kurus)}</b>{row.purchase_id && <a href={`#/satin-almalar?purchase=${row.purchase_id}`}>Satın alma</a>}</div>)}</section>
    <section className="panel p0-section"><h2>Borç yaşlandırması</h2>{aging.data?.buckets.map((bucket) => <div className="p0-row" key={bucket.key}><span>{bucket.label}</span><strong>{formatMoney(bucket.amount_kurus)}</strong></div>)}</section>
    <SupplierPrices supplierId={selected.id} />
    <section className="panel p0-section"><h2>Ödeme</h2>{payments.data?.map((item) => <div className="p0-row" key={item.id}><span>{item.payment_date}</span><strong>{formatMoney(item.amount_kurus)}</strong><span>{statusLabel(item.status)}</span>{item.status === 'active' && <Button onClick={() => post(`/api/v1/payments/${item.id}/reverse`, {})}>Ters kayıt</Button>}</div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); post('/api/v1/payments', { supplier_id: selected.id, purchase_id: null, payment_date: date, amount_kurus: toKurus(amount), idempotency_key: makeIdempotencyKey('supplier-payment') }) }}><input aria-label="Ödeme tarihi" type="date" value={date} onChange={(e) => setDate(e.target.value)} /><input aria-label="Tutar TL" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Tutar TL" /><Button variant="primary" disabled={!amount}>Ödeme kaydet</Button></form></section>
  </> : <EmptyState title="Firma seçin" description="Tedarikçi cari bilgileri burada görünür." />}{error && <p role="alert">{error}</p>}</div></div></div>
}
