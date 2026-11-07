import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, CheckCircle, Lock, Plus } from '@phosphor-icons/react'
import { apiList, ApiError, apiRequest, formatDate, formatMoney } from './lib/api'
import type { PayrollEntry, PayrollPeriod, PayrollPeriodDetail, PayrollState } from './lib/types'
import { queryKeys } from './hooks/useCoreData'
import { Button, EmptyState, ErrorState, Field, LoadingRows, Modal, MoneyValue, PageHeader, SideSheet, StatusBanner, TextInput } from './components/ui'
import { PayrollPayment } from './payrollPayment'

const stateLabels: Record<PayrollState, string> = { draft: 'Taslak', calculated: 'Hesaplandı', finalized: 'Kesinleşti', closed: 'Kapatıldı' }

function stateTone(state: PayrollState) {
  return state === 'closed' ? 'ok' : state === 'finalized' ? 'exact' : state === 'calculated' ? 'estimated' : 'neutral'
}

function nextMonthRange() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth() - (now.getDate() <= 5 ? 1 : 0), 6)
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 5)
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
  const chooseMonth = (value: string) => { const [year, month] = value.split('-').map(Number); if (!year || !month) return; const previous = new Date(year, month - 2, 6); setStart(`${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, '0')}-06`); setEnd(`${value}-05`) }
  return <SideSheet title="Maaş dönemi oluştur" description="Kesim ayın 5'inde, ödeme vadesi ayın 10'undadır." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!start || !end} onClick={() => mutation.mutate()}>Dönemi oluştur</Button></>}>
    <div className="form-stack"><Field label="Kesim ayı"><TextInput type="month" value={end.slice(0, 7)} onChange={(event) => chooseMonth(event.target.value)} /></Field><p>Çalışma dönemi: {formatDate(start)} – {formatDate(end)} · ödeme vadesi: ayın 10'u.</p><Field label="Dönem başlığı" hint="Boş bırakılırsa tarih aralığı kullanılır"><TextInput value={title} onChange={(event) => setTitle(event.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div>
  </SideSheet>
}

function PeriodActions({ period }: { period: PayrollPeriodDetail }) {
  const client = useQueryClient()
  const [confirmAction, setConfirmAction] = useState<'finalize' | 'close' | null>(null)
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: queryKeys.payrollPeriods }), client.invalidateQueries({ queryKey: ['payroll-period', period.id] }), client.invalidateQueries({ queryKey: ['payroll-period', period.id, 'entries'] })])
  const calculate = useMutation({ mutationFn: () => apiRequest(`/api/v1/payroll-periods/${period.id}/calculate`, { method: 'POST', body: {} }), onSuccess: refresh })
  const finalize = useMutation({ mutationFn: () => apiRequest(`/api/v1/payroll-periods/${period.id}/finalize`, { method: 'POST', body: {} }), onSuccess: refresh })
  const close = useMutation({ mutationFn: () => apiRequest(`/api/v1/payroll-periods/${period.id}/close`, { method: 'POST', body: { allow_unpaid: period.totals.remaining_kurus > 0 } }), onSuccess: refresh })
  const error = calculate.error ?? finalize.error ?? close.error
  return <div className="payroll-actions">
    {(period.state === 'draft' || period.state === 'calculated') && <Button loading={calculate.isPending} onClick={() => calculate.mutate()}><Calculator size={17} />{period.state === 'calculated' ? 'Yeniden hesapla' : 'Hesapla'}</Button>}
    {period.state === 'calculated' && <Button variant="primary" loading={finalize.isPending} onClick={() => setConfirmAction('finalize')}><CheckCircle size={17} />Kesinleştir</Button>}
    {period.state === 'finalized' && <Button variant="primary" loading={close.isPending} onClick={() => setConfirmAction('close')}><Lock size={17} />Dönemi kapat</Button>}
    {error && <span className="form-error">{error.message}</span>}
    {error instanceof ApiError && error.code === 'attendance_incomplete' && <div role="alert"><strong>Eksik puantaj</strong>{((error.details as { employees?: Array<{ employee_id: string; employee_name: string; missing_dates: string[] }> } | null)?.employees || []).map((employee) => <p key={employee.employee_id}>{employee.employee_name}: {employee.missing_dates.join(', ')} · <a href={`#/puantaj-izin?employee=${employee.employee_id}&month=${period.period_start.slice(0, 7)}`}>Puantaja git</a></p>)}</div>}
    <Modal title={confirmAction === 'finalize' ? 'Maaş dönemini kesinleştir' : 'Maaş dönemini kapat'} description={confirmAction === 'close' && period.totals.remaining_kurus > 0 ? `Ödenmemiş kalan: ${formatMoney(period.totals.remaining_kurus)}` : 'Bu işlem finansal deftere yansır.'} open={confirmAction !== null} onClose={() => setConfirmAction(null)} footer={<><Button onClick={() => setConfirmAction(null)}>Vazgeç</Button><Button variant="primary" onClick={() => { if (confirmAction === 'finalize') finalize.mutate(); else close.mutate(); setConfirmAction(null) }}>Onayla</Button></>}>İşlemi onayladığınızda dönem durumu değişir.</Modal>
  </div>
}

function PeriodDetail({ periodId }: { periodId: string }) {
  const [saveMessage, setSaveMessage] = useState('')
  const period = useQuery({ queryKey: ['payroll-period', periodId], queryFn: () => apiRequest<PayrollPeriodDetail>(`/api/v1/payroll-periods/${periodId}`) })
  const entries = useQuery({ queryKey: ['payroll-period', periodId, 'entries'], queryFn: () => apiList<PayrollEntry>(`/api/v1/payroll-periods/${periodId}/entries`) })
  if (period.isLoading) return <div className="payroll-detail"><LoadingRows /></div>
  if (period.error || !period.data) return <div className="payroll-detail"><ErrorState error={period.error} onRetry={() => period.refetch()} /></div>
  const data = period.data
  return <section className="payroll-detail">
    <header className="payroll-hero"><div><span>MAAŞ DÖNEMİ</span><h2>{data.title}</h2><p>{formatDate(data.period_start)} – {formatDate(data.period_end)}</p></div><span className={`badge badge--${stateTone(data.state)}`}>{stateLabels[data.state]}</span></header>
    <div className="payroll-metrics"><div><span>Personel</span><strong>{data.entry_count}</strong></div><div><span>Brüt hakediş</span><MoneyValue value={data.totals.gross_earning_kurus} /></div><div><span>Net ödenecek</span><MoneyValue value={data.totals.net_due_kurus} /></div><div><span>Kalan</span><MoneyValue value={data.totals.remaining_kurus} emphasis /></div></div>
    {data.state === 'draft' && <StatusBanner>Dönem henüz hesaplanmadı. Puantaj ve ücret kayıtlarını kontrol ettikten sonra hesaplayın.</StatusBanner>}
    <PeriodActions period={data} />
    <PayrollPayment periodId={periodId} periodTitle={data.title} entries={entries.data ?? []} locked={data.state === 'finalized'} />
    <div className="p0-controls"><Button onClick={async () => { const result = await window.ksDesktop?.api.downloadReport({ path: `/api/v1/payroll-periods/${periodId}/export.xlsx`, filename: `Maas ${data.title}` }); setSaveMessage(result?.status === 'saved' ? 'Excel kaydedildi.' : result?.status === 'cancelled' ? 'Kaydetme iptal edildi.' : result?.message || 'Dosya kaydedilemedi.') }}>Excel kaydet</Button><Button onClick={async () => { const result = await window.ksDesktop?.api.downloadReport({ path: `/api/v1/payroll-periods/${periodId}/export.pdf`, filename: `Maas ${data.title}` }); setSaveMessage(result?.status === 'saved' ? 'PDF kaydedildi.' : result?.status === 'cancelled' ? 'Kaydetme iptal edildi.' : result?.message || 'Dosya kaydedilemedi.') }}>PDF kaydet</Button>{saveMessage && <span role="status">{saveMessage}</span>}</div>
    {entries.isLoading ? <LoadingRows /> : entries.error ? <ErrorState error={entries.error} onRetry={() => entries.refetch()} /> : !entries.data?.length ? <EmptyState title="Hesap satırı yok" description="Dönemi hesapladığınızda personel bazlı tutarlar burada görünür." /> : <div className="table-wrap" role="region" aria-label="Maaş hesap satırları" tabIndex={0}><table><thead><tr><th>Personel</th><th>Çalışma</th><th className="number">Normal</th><th className="number">Mesai</th><th className="number">Prim</th><th className="number">Ek kazanç</th><th className="number">Kesinti / avans</th><th className="number">Net</th><th className="number">Ödenen</th><th className="number">Kalan</th></tr></thead><tbody>{entries.data.map((entry) => <tr key={entry.id}><td><strong>{entry.employee_name ?? entry.employee_id}</strong><small>{entry.wage_type}</small></td><td>{entry.worked_days} gün · {entry.overtime_hours} saat mesai</td><td className="number">{formatMoney(entry.base_earning_kurus)}</td><td className="number">{formatMoney(entry.overtime_earning_kurus)}</td><td className="number">{formatMoney(entry.bonus_kurus)}</td><td className="number">{formatMoney(entry.additional_earning_kurus)}</td><td className="number">{formatMoney(entry.deduction_kurus + entry.advance_deduction_kurus)}</td><td className="number">{formatMoney(entry.net_due_kurus)}</td><td className="number">{formatMoney(entry.paid_kurus)}</td><td className="number"><strong>{formatMoney(entry.remaining_kurus)}</strong></td></tr>)}</tbody></table></div>}
    {entries.data?.map((entry) => <details key={entry.id} className="panel p0-section"><summary>{entry.employee_name || entry.employee_id} - günlük maaş dökümü</summary><p>Dönem uzunluğu düzeltmesi: {formatMoney(Number(entry.calculation_detail?.period_length_adjustment_kurus || 0))}. Habersiz devamsızlık ek değerlendirme: {formatMoney(Number(entry.calculation_detail?.unnotified_absence_extra_for_review_kurus || 0))}. Bu tutar net maaştan otomatik düşülmez.</p><div className="table-wrap"><table><thead><tr><th>Tarih</th><th>Durum</th><th>Günlük</th><th>Saatlik</th><th>Taban</th><th>Devamsızlık</th><th>Mesai</th><th>Pazar / tatil ek</th></tr></thead><tbody>{((entry.calculation_detail?.daily_breakdown || []) as Array<{ date: string; status: string; daily_rate_kurus: number; hourly_rate_kurus: number; base_kurus: number; absence_kurus: number; overtime_kurus: number; sunday_holiday_extra_kurus: number }>).map((day) => <tr key={day.date}><td>{formatDate(day.date)}</td><td>{day.status}</td><td>{formatMoney(day.daily_rate_kurus)}</td><td>{formatMoney(day.hourly_rate_kurus)}</td><td>{formatMoney(day.base_kurus)}</td><td>{formatMoney(day.absence_kurus)}</td><td>{formatMoney(day.overtime_kurus)}</td><td>{formatMoney(day.sunday_holiday_extra_kurus)}</td></tr>)}</tbody></table></div></details>)}
  </section>
}

export function PayrollPeriodsPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedId, setSelectedId] = useState('')
  const periods = useQuery({ queryKey: queryKeys.payrollPeriods, queryFn: () => apiList<PayrollPeriod>('/api/v1/payroll-periods') })
  if (periods.isLoading) return <div className="page"><PageHeader title="Maaş Dönemleri" description="Maaş hesabını kontrol edin, kesinleştirin ve kapatın." /><LoadingRows /></div>
  if (periods.error) return <div className="page"><PageHeader title="Maaş Dönemleri" description="Maaş hesabını kontrol edin, kesinleştirin ve kapatın." /><ErrorState error={periods.error} onRetry={() => periods.refetch()} /></div>
  const selected = periods.data?.find((item) => item.id === selectedId) ?? periods.data?.[0]
  return <div className="page"><PageHeader title="Maaş Dönemleri" description="İşletme içi hakediş ve ödeme hesabı; resmî SGK/vergi bordrosu değildir." action={<Button variant="primary" onClick={() => setCreateOpen(true)}><Plus size={17} />Yeni dönem</Button>} />
    {!periods.data?.length ? <EmptyState title="Henüz maaş dönemi yok" description="İlk dönemi oluşturarak puantajdan maaş hesabına geçin." action={<Button onClick={() => setCreateOpen(true)}>Dönem oluştur</Button>} /> : <div className="payroll-layout"><aside className="payroll-periods">{periods.data.map((item) => <button key={item.id} className={item.id === selected?.id ? 'payroll-period payroll-period--active' : 'payroll-period'} onClick={() => setSelectedId(item.id)}><span><strong>{item.title}</strong><small>{formatDate(item.period_start)} – {formatDate(item.period_end)}</small></span><i className={`badge badge--${stateTone(item.state)}`}>{stateLabels[item.state]}</i></button>)}</aside>{selected && <PeriodDetail periodId={selected.id} />}</div>}
    <CreatePeriodSheet open={createOpen} onClose={() => setCreateOpen(false)} />
  </div>
}

