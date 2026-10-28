import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, CheckCircle, Lock, Plus } from '@phosphor-icons/react'
import { apiRequest, formatDate, formatMoney } from './lib/api'
import type { PayrollEntry, PayrollPeriod, PayrollPeriodDetail, PayrollState } from './lib/types'
import { queryKeys } from './hooks/useCoreData'
import { Button, EmptyState, ErrorState, Field, LoadingRows, MoneyValue, PageHeader, SideSheet, StatusBanner, TextInput } from './components/ui'

const stateLabels: Record<PayrollState, string> = { draft: 'Taslak', calculated: 'Hesaplandı', finalized: 'Kesinleşti', closed: 'Kapatıldı' }

function stateTone(state: PayrollState) {
  return state === 'closed' ? 'ok' : state === 'finalized' ? 'exact' : state === 'calculated' ? 'estimated' : 'neutral'
}

function nextMonthRange() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  const iso = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
  return { start: iso(start), end: iso(end) }
}

function CreatePeriodSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient()
  const initial = useMemo(() => nextMonthRange(), [])
  const [start, setStart] = useState(initial.start)
  const [end, setEnd] = useState(initial.end)
  const [title, setTitle] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiRequest<PayrollPeriodDetail>('/api/v1/payroll-periods', { method: 'POST', body: { period_start: start, period_end: end, title: title || null } }),
    onSuccess: () => { client.invalidateQueries({ queryKey: queryKeys.payrollPeriods }); onClose() },
  })
  return <SideSheet title="Maaş dönemi oluştur" description="Çakışan tarih aralıkları kabul edilmez." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!start || !end} onClick={() => mutation.mutate()}>Dönemi oluştur</Button></>}>
    <div className="form-stack"><Field label="Dönem başlığı" hint="Boş bırakılırsa tarih aralığı kullanılır"><TextInput value={title} onChange={(event) => setTitle(event.target.value)} /></Field><div className="form-grid"><Field label="Başlangıç"><TextInput type="date" value={start} onChange={(event) => setStart(event.target.value)} /></Field><Field label="Bitiş"><TextInput type="date" value={end} onChange={(event) => setEnd(event.target.value)} /></Field></div>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div>
  </SideSheet>
}

function PeriodActions({ period }: { period: PayrollPeriodDetail }) {
  const client = useQueryClient()
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: queryKeys.payrollPeriods }), client.invalidateQueries({ queryKey: ['payroll-period', period.id] }), client.invalidateQueries({ queryKey: ['payroll-period', period.id, 'entries'] })])
  const calculate = useMutation({ mutationFn: () => apiRequest(`/api/v1/payroll-periods/${period.id}/calculate`, { method: 'POST', body: {} }), onSuccess: refresh })
  const finalize = useMutation({ mutationFn: () => apiRequest(`/api/v1/payroll-periods/${period.id}/finalize`, { method: 'POST', body: { payment_due_date: period.period_end } }), onSuccess: refresh })
  const close = useMutation({ mutationFn: () => apiRequest(`/api/v1/payroll-periods/${period.id}/close`, { method: 'POST', body: { allow_unpaid: period.totals.remaining_kurus > 0 } }), onSuccess: refresh })
  const error = calculate.error ?? finalize.error ?? close.error
  return <div className="payroll-actions">
    {(period.state === 'draft' || period.state === 'calculated') && <Button loading={calculate.isPending} onClick={() => calculate.mutate()}><Calculator size={17} />{period.state === 'calculated' ? 'Yeniden hesapla' : 'Hesapla'}</Button>}
    {period.state === 'calculated' && <Button variant="primary" loading={finalize.isPending} onClick={() => window.confirm('Bu dönem kesinleştirilecek ve maaş tahakkukları oluşturulacak. Devam edilsin mi?') && finalize.mutate()}><CheckCircle size={17} />Kesinleştir</Button>}
    {period.state === 'finalized' && <Button variant="primary" loading={close.isPending} onClick={() => window.confirm(period.totals.remaining_kurus > 0 ? 'Dönemde ödenmemiş maaş var. Kalan borçla birlikte kapatılsın mı?' : 'Dönem kapatılsın mı?') && close.mutate()}><Lock size={17} />Dönemi kapat</Button>}
    {error && <span className="form-error">{error.message}</span>}
  </div>
}

function PeriodDetail({ periodId }: { periodId: string }) {
  const period = useQuery({ queryKey: ['payroll-period', periodId], queryFn: () => apiRequest<PayrollPeriodDetail>(`/api/v1/payroll-periods/${periodId}`) })
  const entries = useQuery({ queryKey: ['payroll-period', periodId, 'entries'], queryFn: () => apiRequest<PayrollEntry[]>(`/api/v1/payroll-periods/${periodId}/entries`) })
  if (period.isLoading) return <div className="payroll-detail"><LoadingRows /></div>
  if (period.error || !period.data) return <div className="payroll-detail"><ErrorState error={period.error} onRetry={() => period.refetch()} /></div>
  const data = period.data
  return <section className="payroll-detail">
    <header className="payroll-hero"><div><span>MAAŞ DÖNEMİ</span><h2>{data.title}</h2><p>{formatDate(data.period_start)} – {formatDate(data.period_end)}</p></div><span className={`badge badge--${stateTone(data.state)}`}>{stateLabels[data.state]}</span></header>
    <div className="payroll-metrics"><div><span>Personel</span><strong>{data.entry_count}</strong></div><div><span>Brüt hakediş</span><MoneyValue value={data.totals.gross_earning_kurus} /></div><div><span>Net ödenecek</span><MoneyValue value={data.totals.net_due_kurus} /></div><div><span>Kalan</span><MoneyValue value={data.totals.remaining_kurus} emphasis /></div></div>
    {data.state === 'draft' && <StatusBanner>Dönem henüz hesaplanmadı. Puantaj ve ücret kayıtlarını kontrol ettikten sonra hesaplayın.</StatusBanner>}
    <PeriodActions period={data} />
    {entries.isLoading ? <LoadingRows /> : entries.error ? <ErrorState error={entries.error} onRetry={() => entries.refetch()} /> : !entries.data?.length ? <EmptyState title="Hesap satırı yok" description="Dönemi hesapladığınızda personel bazlı tutarlar burada görünür." /> : <div className="table-wrap" role="region" aria-label="Maaş hesap satırları" tabIndex={0}><table><thead><tr><th>Personel</th><th>Çalışma</th><th className="number">Normal</th><th className="number">Mesai</th><th className="number">Kesinti / avans</th><th className="number">Net</th><th className="number">Kalan</th></tr></thead><tbody>{entries.data.map((entry) => <tr key={entry.id}><td><strong>{entry.employee_name ?? entry.employee_id}</strong><small>{entry.wage_type}</small></td><td>{entry.worked_days} gün · {entry.overtime_hours} saat mesai</td><td className="number">{formatMoney(entry.base_earning_kurus)}</td><td className="number">{formatMoney(entry.overtime_earning_kurus)}</td><td className="number">{formatMoney(entry.deduction_kurus + entry.advance_deduction_kurus)}</td><td className="number">{formatMoney(entry.net_due_kurus)}</td><td className="number"><strong>{formatMoney(entry.remaining_kurus)}</strong></td></tr>)}</tbody></table></div>}
  </section>
}

export function PayrollPeriodsPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const periods = useQuery({ queryKey: queryKeys.payrollPeriods, queryFn: () => apiRequest<PayrollPeriod[]>('/api/v1/payroll-periods') })
  if (periods.isLoading) return <div className="page"><PageHeader title="Maaş Dönemleri" description="Maaş hesabını kontrol edin, kesinleştirin ve kapatın." /><LoadingRows /></div>
  if (periods.error) return <div className="page"><PageHeader title="Maaş Dönemleri" description="Maaş hesabını kontrol edin, kesinleştirin ve kapatın." /><ErrorState error={periods.error} onRetry={() => periods.refetch()} /></div>
  const selected = periods.data?.find((item) => item.id === selectedId) ?? periods.data?.[0]
  return <div className="page"><PageHeader title="Maaş Dönemleri" description="İşletme içi hakediş ve ödeme hesabı; resmî SGK/vergi bordrosu değildir." action={<Button variant="primary" onClick={() => setCreateOpen(true)}><Plus size={17} />Yeni dönem</Button>} />
    {!periods.data?.length ? <EmptyState title="Henüz maaş dönemi yok" description="İlk dönemi oluşturarak puantajdan maaş hesabına geçin." action={<Button onClick={() => setCreateOpen(true)}>Dönem oluştur</Button>} /> : <div className="payroll-layout"><aside className="payroll-periods">{periods.data.map((item) => <button key={item.id} className={item.id === selected?.id ? 'payroll-period payroll-period--active' : 'payroll-period'} onClick={() => setSelectedId(item.id)}><span><strong>{item.title}</strong><small>{formatDate(item.period_start)} – {formatDate(item.period_end)}</small></span><i className={`badge badge--${stateTone(item.state)}`}>{stateLabels[item.state]}</i></button>)}</aside>{selected && <PeriodDetail periodId={selected.id} />}</div>}
    <CreatePeriodSheet open={createOpen} onClose={() => setCreateOpen(false)} />
  </div>
}

