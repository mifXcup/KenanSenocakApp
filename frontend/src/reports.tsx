import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiRequest, formatDate } from './lib/api'
import { monthLabel, rangeError, rangeFor, type DateRange, type RangePreset } from './lib/reportRange'
import type { DebtAgingReport, PurchaseReport } from './lib/types'
import { EmptyState, ErrorState, Field, LoadingRows, MoneyValue, PageHeader, SelectInput, StatusBanner, TextInput } from './components/ui'
import { queryKeys as q, useCoreData } from './hooks/useCoreData'

const todayIso = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())

const presets: { key: RangePreset; label: string }[] = [
  { key: 'month', label: 'Bu ay' },
  { key: 'last30', label: 'Son 30 gün' },
  { key: 'year', label: 'Bu yıl' },
  { key: 'all', label: 'Tüm zamanlar' },
]

const bucketTone: Record<string, string> = { not_due: 'ok', no_due_date: 'muted', d1_30: 'warn', d31_60: 'warn', d61_90: 'bad', d90_plus: 'bad' }

const shortLabel: Record<string, string> = { not_due: 'Gelmemiş', d1_30: '1–30 gün', d31_60: '31–60 gün', d61_90: '61–90 gün', d90_plus: '90+ gün', no_due_date: 'Vade yok' }

type Tab = 'purchases' | 'aging'

export function ReportsPage() {
  const [tab, setTab] = useState<Tab>('purchases')
  return (
    <div className="page">
      <PageHeader title="Raporlar" description="Ne aldığınızı, kimden aldığınızı ve firmalara olan borcunuzu tarih bazında izleyin." />
      <div className="tabs" role="tablist" aria-label="Rapor türü">
        <button role="tab" aria-selected={tab === 'purchases'} className="tabs__item" onClick={() => setTab('purchases')}>Satın alma özeti</button>
        <button role="tab" aria-selected={tab === 'aging'} className="tabs__item" onClick={() => setTab('aging')}>Borç yaşlandırma</button>
      </div>
      {tab === 'purchases' ? <PurchaseSummary /> : <DebtAging />}
    </div>
  )
}

function PurchaseSummary() {
  const core = useCoreData()
  const [preset, setPreset] = useState<RangePreset>('month')
  const [range, setRange] = useState<DateRange>(() => rangeFor('month', todayIso))
  const [supplierId, setSupplierId] = useState('')
  const [projectId, setProjectId] = useState('')
  const invalid = rangeError(range)

  const params = useMemo(() => {
    const search = new URLSearchParams()
    if (range.from) search.set('date_from', range.from)
    if (range.to) search.set('date_to', range.to)
    if (supplierId) search.set('supplier_id', supplierId)
    if (projectId) search.set('project_id', projectId)
    return search.toString()
  }, [range, supplierId, projectId])

  const report = useQuery({
    queryKey: [...q.reports, 'purchases', params],
    queryFn: () => apiRequest<PurchaseReport>(`/api/v1/reports/purchases${params ? `?${params}` : ''}`),
    enabled: !invalid,
  })

  function choosePreset(next: RangePreset) {
    setPreset(next)
    setRange(rangeFor(next, todayIso))
  }

  return (
    <>
      <section className="filter-bar" aria-label="Rapor filtreleri">
        <div className="segmented" role="group" aria-label="Hazır dönem">
          {presets.map((item) => <button key={item.key} aria-pressed={preset === item.key} onClick={() => choosePreset(item.key)}>{item.label}</button>)}
        </div>
        <Field label="Başlangıç" error={invalid}><TextInput type="date" value={range.from} max={range.to || undefined} onChange={(e) => { setPreset('all'); setRange({ ...range, from: e.target.value }) }} /></Field>
        <Field label="Bitiş"><TextInput type="date" value={range.to} min={range.from || undefined} onChange={(e) => { setPreset('all'); setRange({ ...range, to: e.target.value }) }} /></Field>
        <Field label="Firma"><SelectInput value={supplierId} onChange={(e) => setSupplierId(e.target.value)}><option value="">Tüm firmalar</option>{core.suppliers.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field>
        <Field label="Proje"><SelectInput value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Tüm projeler</option>{core.projects.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field>
      </section>

      {report.isLoading ? <LoadingRows /> : report.error ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : report.data && (
        report.data.purchase_count === 0 && report.data.payment_total_kurus === 0 ? (
          <EmptyState title="Bu filtrede kayıt yok" description="Tarih aralığını veya firma/proje seçimini değiştirerek tekrar deneyin." />
        ) : (
          <>
            <section className="summary-band" aria-label="Dönem özeti">
              <div className="summary-band__main"><span>Dönem satın alması</span><MoneyValue value={report.data.purchase_total_kurus} emphasis /><small>{report.data.purchase_count} kayıt</small></div>
              <div className="summary-stat"><span>Dönemde yapılan ödeme</span><MoneyValue value={report.data.payment_total_kurus} /></div>
            </section>

            <section className="panel"><div className="panel__header"><h2>Firmaya göre</h2><span className="caption">Güncel borç dönem filtresinden bağımsızdır</span></div>
              <div className="table-wrap"><table aria-label="Firmaya göre satın alma"><thead><tr><th>Firma</th><th className="number">Alış sayısı</th><th className="number">Dönem alışı</th><th className="number">Dönem ödemesi</th><th className="number">Güncel borç</th></tr></thead>
                <tbody>{report.data.by_supplier.map((row) => <tr key={row.supplier_id}><td><strong>{row.supplier_name}</strong></td><td className="number">{row.purchase_count}</td><td className="number"><MoneyValue value={row.purchase_total_kurus} /></td><td className="number"><MoneyValue value={row.payment_total_kurus} /></td><td className="number"><MoneyValue value={row.current_debt_kurus} /></td></tr>)}</tbody></table></div>
            </section>

            <section className="panel"><div className="panel__header"><h2>Malzemeye göre</h2><span className="caption">Miktarlar birim bazında ayrı toplanır</span></div>
              <div className="table-wrap"><table aria-label="Malzemeye göre satın alma"><thead><tr><th>Malzeme</th><th className="number">Alış sayısı</th><th className="number">Miktar</th><th className="number">Tutar</th></tr></thead>
                <tbody>{report.data.by_material.map((row) => <tr key={`${row.material_id}-${row.unit}`}><td><strong>{row.material_name}</strong></td><td className="number">{row.purchase_count}</td><td className="number">{row.quantity ? `${Number(row.quantity).toLocaleString('tr-TR')} ${row.unit ?? ''}` : 'Yalnız tutar'}</td><td className="number"><MoneyValue value={row.total_kurus} /></td></tr>)}</tbody></table></div>
            </section>

            <section className="panel"><div className="panel__header"><h2>Aylık dağılım</h2></div>
              <div className="ranking">{report.data.by_month.map((row) => <div className="ranking__row ranking__row--wide" key={row.month}><span className="ranking__count">{row.purchase_count} alış</span><strong>{monthLabel(row.month)}</strong><MoneyValue value={row.total_kurus} /></div>)}</div>
            </section>
          </>
        )
      )}
    </>
  )
}

function DebtAging() {
  const [asOf, setAsOf] = useState(todayIso)
  const report = useQuery({
    queryKey: [...q.reports, 'debt-aging', asOf],
    queryFn: () => apiRequest<DebtAgingReport>(`/api/v1/reports/debt-aging?as_of=${asOf}`),
    enabled: Boolean(asOf),
  })

  return (
    <>
      <section className="filter-bar" aria-label="Yaşlandırma tarihi">
        <Field label="Hesaplama tarihi" hint="Vadeler bu tarihe göre değerlendirilir"><TextInput type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
      </section>
      {report.isLoading ? <LoadingRows /> : report.error ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : report.data && (
        report.data.total_open_kurus === 0 && report.data.credit_kurus === 0 ? (
          <EmptyState title="Açık borç yok" description="Bu tarihte ödenmemiş firma borcu bulunmuyor." />
        ) : (
          <>
            <section className="summary-band" aria-label="Borç özeti">
              <div className="summary-band__main"><span>Toplam açık borç</span><MoneyValue value={report.data.total_open_kurus} emphasis /><small>{formatDate(report.data.as_of)} itibarıyla</small></div>
              <div className="summary-stat"><span>Vadesi geçmiş</span><MoneyValue value={report.data.overdue_kurus} /></div>
              <div className="summary-stat"><span>Firmalarda avans</span><MoneyValue value={report.data.credit_kurus} /></div>
            </section>
            {report.data.buckets.some((b) => b.key === 'no_due_date' && b.count > 0) && <StatusBanner>Vade tarihi girilmemiş alışlar ayrı gösterilir; gecikme hesabına katılmaz.</StatusBanner>}

            <section className="panel"><div className="panel__header"><h2>Yaşlandırma</h2></div>
              <div className="aging-grid">{report.data.buckets.map((b) => <div className={`aging-cell aging-cell--${bucketTone[b.key]}`} key={b.key}><span>{b.label}</span><MoneyValue value={b.amount_kurus} emphasis /><small>{b.count} alış</small></div>)}</div>
            </section>

            <section className="panel"><div className="panel__header"><h2>Firmaya göre açık borç</h2></div>
              <div className="table-wrap"><table aria-label="Firmaya göre borç yaşlandırma"><thead><tr><th>Firma</th>{report.data.buckets.map((b) => <th className="number" key={b.key} title={b.label}>{shortLabel[b.key]}</th>)}<th className="number">Toplam</th></tr></thead>
                <tbody>{report.data.suppliers.map((s) => <tr key={s.supplier_id}><td><strong>{s.supplier_name}</strong>{s.credit_kurus > 0 && <small>Avans: <MoneyValue value={s.credit_kurus} /></small>}</td>{report.data!.buckets.map((b) => <td className="number" key={b.key}>{s.buckets[b.key] ? <MoneyValue value={s.buckets[b.key]} /> : '—'}</td>)}<td className="number"><MoneyValue value={s.total_open_kurus} /></td></tr>)}</tbody></table></div>
            </section>

            <section className="panel"><div className="panel__header"><h2>Açık alışlar</h2><span className="caption">Vadesi en yakın olan üstte</span></div>
              <div className="table-wrap"><table aria-label="Açık alışlar"><thead><tr><th>Firma</th><th>Malzeme</th><th>Alış tarihi</th><th>Vade</th><th className="number">Gecikme</th><th className="number">Kalan</th></tr></thead>
                <tbody>{report.data.items.map((i) => <tr key={i.purchase_id}><td><strong>{i.supplier_name}</strong></td><td>{i.material_name}</td><td>{formatDate(i.purchase_date)}</td><td>{i.due_date ? formatDate(i.due_date) : 'Girilmedi'}</td><td className="number">{i.days_overdue ? `${i.days_overdue} gün` : '—'}</td><td className="number"><MoneyValue value={i.remaining_kurus} /></td></tr>)}</tbody></table></div>
            </section>
          </>
        )
      )}
    </>
  )
}
