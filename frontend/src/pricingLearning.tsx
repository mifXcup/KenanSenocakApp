import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, CheckCircle, WarningCircle } from '@phosphor-icons/react'
import { apiList, apiRequest, formatDate, formatMoney, toKurus } from './lib/api'
import type { Material, PricingLearningStatus } from './lib/types'
import { Button, ErrorState, LoadingRows } from './components/ui'

const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())

export function PricingLearningPanel() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['pricing-status'], queryFn: () => apiRequest<PricingLearningStatus>('/api/v1/pricing/status') })
  const materials = useQuery({ queryKey: ['materials'], queryFn: () => apiList<Material>('/api/v1/materials') })
  const [label, setLabel] = useState('')
  const [materialId, setMaterialId] = useState('')
  const [date, setDate] = useState(today)
  const [price, setPrice] = useState('')
  const [message, setMessage] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest('/api/v1/pricing/indices', { method: 'POST', body: { factor_key: materialId ? `material-${materialId}` : slug(label), label, material_id: materialId || null, recorded_on: date, unit_price_kurus: toKurus(price), note: 'Öğrenme Merkezi manuel referansı' } }), onSuccess: async () => { setMessage('Güncel maliyet referansı kaydedildi.'); setPrice(''); await queryClient.invalidateQueries({ queryKey: ['pricing-status'] }) }, onError: (error) => setMessage(error instanceof Error ? error.message : String(error)) })
  if (status.isLoading) return <section className="panel p0-section"><h2>Fiyat Öğrenimi</h2><LoadingRows count={3} /></section>
  if (status.error) return <section className="panel p0-section"><h2>Fiyat Öğrenimi</h2><ErrorState error={status.error} onRetry={() => status.refetch()} /></section>
  const data = status.data
  return <section className="panel p0-section pricing-learning"><div className="pricing-heading"><div><h2>Fiyat Öğrenimi</h2><p>Geçmiş ürün, gerçek maliyet ve güncel maliyet referanslarının öğrenme durumunu gösterir.</p></div><span className={`learning-ready ${data?.ready ? 'learning-ready--ok' : ''}`}>{data?.ready ? <CheckCircle size={18} /> : <WarningCircle size={18} />}{data?.ready ? 'İlk öneriye hazır' : 'Veri bekleniyor'}</span></div>
    <div className="p0-metrics"><div><span>Ürün kaydı</span><strong>{data?.product_count ?? 0}</strong></div><div><span>Fiyatlı geçmiş</span><strong>{data?.priced_product_count ?? 0}</strong></div><div><span>Gerçek maliyet</span><strong>{data?.actual_cost_count ?? 0}</strong></div><div><span>Maliyet payı bulunan</span><strong>{data?.factor_coverage_count ?? 0}</strong></div></div><p className="learning-message"><Brain size={18} />{data?.message}</p>
    {!!data?.product_types.length && <div><h3>Ürün türü kapsamı</h3>{data.product_types.map((item) => <div className="p0-row" key={item.product_type}><strong>{item.product_type}</strong><span>{item.priced_count} fiyatlı geçmiş kayıt</span></div>)}</div>}
    <h3>Güncel maliyet referansı gir</h3><p className="muted">Satın alma kaydı olmayan işçilik, boya veya piyasa endekslerini buradan tarihli olarak girebilirsiniz.</p><form className="p0-controls" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>Maliyet adı<input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Atölye işçiliği" /></label><label>Bağlı malzeme<select value={materialId} onChange={(event) => { setMaterialId(event.target.value); const material = materials.data?.find((item) => item.id === event.target.value); if (material) setLabel(material.name) }}><option value="">Manuel endeks</option>{materials.data?.map((material) => <option key={material.id} value={material.id}>{material.name}</option>)}</select></label><label>Tarih<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>Birim değer TL<input value={price} onChange={(event) => setPrice(event.target.value)} inputMode="decimal" /></label><Button variant="primary" type="submit" loading={mutation.isPending} disabled={label.trim().length < 2 || toKurus(price) <= 0}>Referansı kaydet</Button></form>
    {!!data?.latest_manual_indices.length && <div><h3>Son manuel referanslar</h3>{data.latest_manual_indices.slice(0, 10).map((item) => <div className="p0-row" key={item.id}><strong>{item.label}</strong><span>{formatDate(item.recorded_on)}</span><b>{formatMoney(item.unit_price_kurus)}</b><span className="badge badge--neutral">{item.source}</span></div>)}</div>}{message && <p role="status">{message}</p>}
  </section>
}

function slug(value: string) { return value.toLocaleLowerCase('tr-TR').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ı/g, 'i').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'manual-cost' }
