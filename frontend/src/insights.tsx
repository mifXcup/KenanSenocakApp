import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowClockwise, CalendarDots, ChartLineUp, FunnelSimple, Sparkle, WarningCircle } from '@phosphor-icons/react'
import { apiRequest, formatDate, formatMoney } from './lib/api'
import type { MLInsights } from './lib/types'
import { Button, EmptyState, ErrorState, LoadingRows, PageHeader, StatusBanner } from './components/ui'
import './insights.css'
import { InsightsExtra } from './insightsExtra'

const todayIso = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date())

const riskLabel: Record<string, string> = { low: 'Düşük', medium: 'Orta', high: 'Yüksek' }
const confidenceLabel: Record<string, string> = { low: 'Düşük güven', medium: 'Orta güven', high: 'Yüksek güven' }

export function InsightsPage() {
  const [attentionOnly, setAttentionOnly] = useState(false)
  const asOf = todayIso()
  const insights = useQuery({
    queryKey: ['ml-insights', asOf],
    queryFn: () => apiRequest<MLInsights>(`/api/v1/analytics/ml/insights?as_of=${asOf}`),
  })
  const view = useMemo(() => {
    const source = insights.data
    if (!source) return null
    return {
      price: [...source.price_anomalies].filter((item) => !attentionOnly || (item.is_anomaly && !item.dismissed)).sort((a, b) => Number(b.is_anomaly) - Number(a.is_anomaly) || Math.abs(b.deviation_percent) - Math.abs(a.deviation_percent)),
      reorder: [...source.reorder_forecasts].filter((item) => !attentionOnly || (item.days_until_expected <= 14 && !item.dismissed)).sort((a, b) => a.days_until_expected - b.days_until_expected),
      risk: [...source.project_risks].filter((item) => !attentionOnly || (item.risk_level !== 'low' && !item.dismissed)).sort((a, b) => b.projected_usage_percent - a.projected_usage_percent),
    }
  }, [attentionOnly, insights.data])

  return (
    <div className="page">
      <PageHeader title="Akıllı Öngörüler" description="Yerel geçmişinizden fiyat, yeniden alım ve proje maliyeti sinyalleri üretir." action={<Button onClick={() => insights.refetch()} disabled={insights.isFetching}><ArrowClockwise size={18} className={insights.isFetching ? 'spin' : ''} />Yenile</Button>} />
      {insights.isLoading ? <LoadingRows count={4} /> : insights.error ? <ErrorState error={insights.error} onRetry={() => insights.refetch()} /> : insights.data && (
        <>
          <StatusBanner><strong>Veriler cihazınızda analiz edilir.</strong>&nbsp; Bu ekran karar desteğidir; kesin fiyat veya maliyet taahhüdü değildir.</StatusBanner>
          <section className="insight-readiness" aria-label="Analiz hazırlık durumu">
            <div className="insight-readiness__lead"><Sparkle size={22} /><div><strong>{insights.data.status.ready ? 'Analizler hazır' : 'Sistem öğreniyor'}</strong><span>{insights.data.status.message}</span></div></div>
            <div><span>Satın alma</span><strong>{insights.data.status.purchase_count}</strong></div>
            <div><span>Fiyat serisi</span><strong>{insights.data.status.material_series_ready}</strong></div>
            <div><span>Proje serisi</span><strong>{insights.data.status.project_series_ready}</strong></div>
          </section>
          <div className="insight-toolbar"><span><CalendarDots size={16} />{formatDate(insights.data.as_of)} itibarıyla</span><button type="button" className={attentionOnly ? 'insight-filter insight-filter--active' : 'insight-filter'} aria-pressed={attentionOnly} onClick={() => setAttentionOnly((value) => !value)}><FunnelSimple size={16} />Yalnız dikkat gerekenler</button></div>

          {!insights.data.status.ready && !insights.data.price_anomalies.length && !insights.data.reorder_forecasts.length && !insights.data.project_risks.length ? (
            <EmptyState title="Tahmin için biraz daha geçmiş gerekiyor" description={`Fiyat analizi için malzeme başına en az ${insights.data.status.minimum_price_samples}, yeniden alım tahmini için en az ${insights.data.status.minimum_reorder_samples} kayıt gerekir. Kayıt girdikçe bu alan kendiliğinden dolacak.`} />
          ) : (
            <div className="insights-grid">
              <section className="panel insight-section">
                <div className="panel__header"><h2>Fiyat sinyalleri</h2><ChartLineUp size={20} /></div>
                {!view?.price.length ? <p className="muted">{attentionOnly ? 'Dikkat gerektiren fiyat sinyali yok.' : 'Yeterli fiyat serisi oluşmadı.'}</p> : <div className="signal-list">{view.price.map((item) => <article className="signal-row" key={`${item.material_id}-${item.unit}`}><div className={`signal-icon ${item.is_anomaly ? 'signal-icon--warn' : ''}`}>{item.is_anomaly ? <WarningCircle size={18} /> : <ChartLineUp size={18} />}</div><div><strong>{item.material_name}</strong><span>{formatDate(item.latest_date)} · {item.sample_count} kayıt · {item.unit}</span><small>Beklenen sonraki fiyat: {formatMoney(item.next_expected_unit_price_kurus)}</small>{item.dismissed && <small>Geri bildiriminiz nedeniyle gizlendi; yeni kayıt gelince yeniden değerlendirilir.</small>}</div><div className="signal-row__value"><strong>{formatMoney(item.latest_unit_price_kurus)}</strong><span className={item.deviation_percent > 0 ? 'text-warn' : ''}>Beklenenden %{Math.abs(item.deviation_percent).toLocaleString('tr-TR')} {item.deviation_percent >= 0 ? 'yüksek' : 'düşük'}</span></div></article>)}</div>}
              </section>

              <section className="panel insight-section">
                <div className="panel__header"><h2>Yeniden alım</h2><CalendarDots size={20} /></div>
                {!view?.reorder.length ? <p className="muted">{attentionOnly ? 'Önümüzdeki 14 günde beklenen alım yok.' : 'Tekrarlayan satın alma aralığı henüz oluşmadı.'}</p> : <div className="signal-list">{view.reorder.map((item) => <article className="signal-row" key={item.material_id}><div className="signal-icon"><CalendarDots size={18} /></div><div><strong>{item.material_name}</strong><span>Ortalama {item.median_interval_days} günde bir · {item.sample_count} alış · {confidenceLabel[item.confidence] ?? item.confidence}</span>{item.dismissed && <small>Geri bildiriminiz nedeniyle gizlendi.</small>}{item.stale && <small className="text-warn">Son alıştan {item.days_since_last} gün geçti; düzenli alım kesilmiş olabilir.</small>}</div><div className="signal-row__value"><strong>{formatDate(item.next_expected_date)}</strong><span>{item.days_until_expected < 0 ? `${Math.abs(item.days_until_expected)} gün geçti` : item.days_until_expected === 0 ? 'Bugün bekleniyor' : `${item.days_until_expected} gün kaldı`}</span></div></article>)}</div>}
              </section>

              <section className="panel panel--wide insight-section">
                <div className="panel__header"><h2>Proje bütçe riski</h2><span className="count-label">30 günlük öngörü</span></div>
                {!view?.risk.length ? <p className="muted">{attentionOnly ? 'Orta veya yüksek riskli proje yok.' : 'Bütçe ve maliyet geçmişi olan proje bulunamadı.'}</p> : <div className="risk-table" role="table" aria-label="Proje riskleri">{view.risk.map((item) => <article className="risk-row" role="row" key={item.project_id}><div><strong>{item.project_name}</strong><span>{item.sample_count} maliyet kaydı{item.sample_count < 8 ? ' · az veri' : ''}{item.dismissed ? ' · geri bildiriminiz nedeniyle gizlendi' : ''}</span></div><div><span>Mevcut maliyet</span><strong>{formatMoney(item.current_cost_kurus)}</strong></div><div><span>30 gün öngörüsü</span><strong>{formatMoney(item.projected_30d_cost_kurus)}</strong></div><div><span>Bütçe kullanımı (şimdi → 30 gün)</span><strong>%{item.budget_usage_percent.toLocaleString('tr-TR')} → %{item.projected_usage_percent.toLocaleString('tr-TR')}</strong>{item.confidence_score != null && <small>Güven %{Math.round(item.confidence_score * 100)}</small>}</div><span className={`risk-badge risk-badge--${item.risk_level}`}>{riskLabel[item.risk_level] ?? item.risk_level}</span></article>)}</div>}
              </section>
            </div>
          )}
        </>
      )}
      <InsightsExtra />
    </div>
  )
}
