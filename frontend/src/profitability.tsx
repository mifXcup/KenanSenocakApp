import { useMemo, useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ChartLineUp, WarningCircle } from '@phosphor-icons/react'
import { apiRequest, formatMoney } from './lib/api'
import type { Project } from './lib/types'
import { queryKeys, useCoreData } from './hooks/useCoreData'
import { EmptyState, ErrorState, LoadingRows, PageHeader, StatusBanner } from './components/ui'
import { profitTone } from './profitabilityUtils'
import { ProfitabilityExtras } from './profitabilityExtras'

interface Profitability { contract_amount_kurus: number | null; revised_contract_kurus: number | null; original_budget_kurus: number | null; revised_budget_kurus: number | null; actual_cost_kurus: number; commitment_kurus: number; remaining_estimate_kurus: number; forecast_cost_at_completion_kurus: number; estimated_profit_kurus: number | null; estimated_margin_percent: number | null; budget_variance_kurus: number | null; categories: Array<{ category: string; actual_kurus: number; commitment_kurus: number; remaining_estimate_kurus: number; forecast_kurus: number; forecast_source?: string }>; collections?: { net_collected_kurus: number; open_receivable_kurus: number; unlinked_customer_advance_kurus: number }; warnings?: Array<{ message: string }> }

function ProjectSelector({ projects, selectedId, onSelect }: { projects: Project[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <aside className="profit-projects" aria-label="Projeler">
      <span className="profit-projects__label">PROJELER</span>
      {projects.map((project) => (
        <button key={project.id} className={`profit-project ${project.id === selectedId ? 'profit-project--active' : ''}`} onClick={() => onSelect(project.id)}>
          <i style={{ background: project.accent_color }} />
          <span><strong>{project.name}</strong><small>{project.customer_name}</small></span>
          <ArrowRight size={14} aria-hidden="true" />
        </button>
      ))}
    </aside>
  )
}

function SummaryMetric({ label, value, detail, tone = 'neutral' }: { label: string; value: string; detail: string; tone?: 'positive' | 'negative' | 'neutral' }) {
  return <div className={`profit-metric profit-metric--${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function ProjectProfitDetail({ project }: { project: Project }) {
  const summary = useQuery({
    queryKey: queryKeys.profitability(project.id),
    queryFn: () => apiRequest<Profitability>(`/api/v1/projects/${project.id}/profitability`),
  })
  const breakdown = useMemo(() => {
    if (!summary.data) return []
    return summary.data.categories.map((item) => ({ key: item.category, label: item.category, value: item.actual_kurus }))
  }, [summary.data])

  if (summary.isLoading) return <div className="profit-detail"><LoadingRows count={7} /></div>
  if (summary.error) return <div className="profit-detail"><ErrorState error={summary.error} onRetry={() => summary.refetch()} /></div>
  if (!summary.data) return null

  const data = summary.data
  const maximum = Math.max(...breakdown.map((item) => item.value), 1)
  return (
    <section className="profit-detail">
      <header className="profit-hero" style={{ '--project-accent': project.accent_color } as CSSProperties}>
        <div><span>PROJE FİNANS ÖZETİ</span><h2>{project.name}</h2><p>{project.customer_name}</p></div>
        <div className="profit-hero__state"><ChartLineUp size={18} /><span>{project.project_state || 'Durum belirtilmedi'}</span></div>
      </header>
      <div className="profit-metrics">
        <SummaryMetric label="Sözleşme" value={formatMoney(data.contract_amount_kurus)} detail="Mevcut proje bedeli" />
        <SummaryMetric label="Gerçekleşen maliyet" value={formatMoney(data.actual_cost_kurus)} detail="Teslim + işçilik + gider" />
        <SummaryMetric label="Taahhüt" value={formatMoney(data.commitment_kurus)} detail="Bekleyen sipariş" />
        <SummaryMetric label="Kalan tahmin" value={formatMoney(data.remaining_estimate_kurus)} detail="Otomatik / manuel" />
        <SummaryMetric label="Tahmini bitiş maliyeti" value={formatMoney(data.forecast_cost_at_completion_kurus)} detail="Gerçekleşen + taahhüt + kalan" />
        <SummaryMetric label="Tahmini kâr" value={formatMoney(data.estimated_profit_kurus)} detail={data.estimated_margin_percent == null ? 'Marj hesaplanamadı' : `%${data.estimated_margin_percent.toLocaleString('tr-TR')} marj`} tone={profitTone(data.estimated_profit_kurus)} />
        <SummaryMetric label="Bütçe farkı" value={formatMoney(data.budget_variance_kurus)} detail="Pozitif tutar kalan bütçedir" tone={profitTone(data.budget_variance_kurus)} />
      </div>
      <StatusBanner>Revize sözleşme {formatMoney(data.revised_contract_kurus)} · Net tahsilat {formatMoney(data.collections?.net_collected_kurus)} · Açık alacak {formatMoney(data.collections?.open_receivable_kurus)}</StatusBanner>
      {data.warnings?.map((warning, index) => <p role="alert" key={index}>{warning.message}</p>)}
      <div className="profit-grid">
        <section className="panel profit-breakdown">
          <header><div><h3>Maliyet dağılımı</h3><p>Bugüne kadar projeye bağlanan giderler</p></div><strong>{formatMoney(data.actual_cost_kurus)}</strong></header>
          <div>{breakdown.map((item) => (
            <div className="cost-line" key={item.key}>
              <span><strong>{item.label}</strong><small>{formatMoney(item.value)}</small></span>
              <div><i style={{ width: `${Math.max(item.value > 0 ? 3 : 0, (item.value / maximum) * 100)}%` }} /></div>
            </div>
          ))}</div>
        </section>
        <section className="panel profit-health">
          <header><h3>Kontrol noktaları</h3></header>
          <div className="profit-check"><span className={data.contract_amount_kurus == null ? 'check-dot check-dot--warn' : 'check-dot'} /><span><strong>Sözleşme bedeli</strong><small>{data.contract_amount_kurus == null ? 'Girilmeden kâr hesaplanamaz' : 'Kayıtlı'}</small></span></div>
          <div className="profit-check"><span className={data.revised_budget_kurus == null ? 'check-dot check-dot--warn' : 'check-dot'} /><span><strong>Revize bütçe</strong><small>{data.revised_budget_kurus == null ? 'Sapma takibi için girilmeli' : formatMoney(data.revised_budget_kurus)}</small></span></div>
          <div className="profit-check"><span className={data.budget_variance_kurus != null && data.budget_variance_kurus < 0 ? 'check-dot check-dot--bad' : 'check-dot'} /><span><strong>Bütçe durumu</strong><small>{data.budget_variance_kurus == null ? 'Hesaplanamadı' : data.budget_variance_kurus < 0 ? `${formatMoney(Math.abs(data.budget_variance_kurus))} aşım` : `${formatMoney(data.budget_variance_kurus)} alan var`}</small></span></div>
          {data.estimated_profit_kurus != null && data.estimated_profit_kurus < 0 && <div className="profit-alert"><WarningCircle size={18} /><span><strong>Zarar riski</strong><small>Tahmini bitiş maliyeti sözleşme bedelini aşıyor.</small></span></div>}
        </section>
      </div>
      <ProfitabilityExtras projectId={project.id} />
    </section>
  )
}

export function ProfitabilityPage() {
  const { projects } = useCoreData()
  const [selectedId, setSelectedId] = useState('')

  if (projects.isLoading) return <div className="page"><PageHeader title="Proje Kârlılığı" description="Proje finansal sağlığını tek ekranda izleyin." /><LoadingRows /></div>
  if (projects.error) return <div className="page"><PageHeader title="Proje Kârlılığı" description="Proje finansal sağlığını tek ekranda izleyin." /><ErrorState error={projects.error} onRetry={() => projects.refetch()} /></div>
  if (!projects.data?.length) return <div className="page"><PageHeader title="Proje Kârlılığı" description="Proje finansal sağlığını tek ekranda izleyin." /><EmptyState title="Henüz proje yok" description="Kârlılık hesabı için önce bir proje oluşturun." /></div>
  const selected = projects.data.find((project) => project.id === selectedId) ?? projects.data[0]
  return (
    <div className="page">
      <PageHeader title="Proje Kârlılığı" description="Sözleşme, bütçe ve gerçekleşen maliyeti aynı bağlamda inceleyin." />
      <div className="profit-layout"><ProjectSelector projects={projects.data} selectedId={selected.id} onSelect={setSelectedId} /><ProjectProfitDetail project={selected} /></div>
    </div>
  )
}

