import { useQuery } from '@tanstack/react-query'
import { apiRequest, formatMoney } from './lib/api'
import { ErrorState, LoadingRows } from './components/ui'

type PriceRow = { material_name?: string; supplier_name?: string; receipt_date?: string; unit_price_kurus?: number; quantity?: number; unit?: string }
type Comparison = { material_name: string; suppliers: Array<{ supplier_id: string; supplier_name: string; trend_adjusted_unit_price_kurus: number; record_count: number }>; comparable: boolean; caveats: string[] }
export function SupplierPrices({ supplierId }: { supplierId: string }) {
  const history = useQuery({ queryKey: ['supplier-price-history', supplierId], queryFn: () => apiRequest<{ rows: PriceRow[] }> (`/api/v1/reports/finance/material-price-history?supplier_id=${supplierId}`) })
  const insights = useQuery({ queryKey: ['supplier-comparisons'], queryFn: () => apiRequest<{ supplier_comparisons: Comparison[] }>('/api/v1/analytics/ml/insights') })
  return <section className="panel p0-section"><h2>Malzeme son fiyatı ve karşılaştırma</h2>{history.isLoading ? <LoadingRows /> : history.error ? <ErrorState error={history.error} onRetry={() => history.refetch()} /> : !history.data?.rows.length ? <p>Karşılaştırılabilir teslim kaydı yok.</p> : history.data.rows.slice().sort((a, b) => String(b.receipt_date).localeCompare(String(a.receipt_date))).slice(0, 30).map((row, i) => <div className="p0-row" key={i}><strong>{row.material_name}</strong><span>{row.receipt_date}</span><span>{row.quantity} {row.unit}</span><b>{formatMoney(row.unit_price_kurus)}</b></div>)}<h3>Tedarikçi karşılaştırması</h3>{insights.data?.supplier_comparisons.filter((item) => item.suppliers.some((supplier) => supplier.supplier_id === supplierId)).map((item) => <div key={item.material_name}><strong>{item.material_name}</strong>{item.suppliers.map((supplier) => <div className="p0-row" key={supplier.supplier_id}><span>{supplier.supplier_name}</span><span>{supplier.record_count} teslim</span><b>{formatMoney(supplier.trend_adjusted_unit_price_kurus)}</b></div>)}{!item.comparable && <p>Fiyatlar doğrudan karşılaştırılamıyor: {item.caveats.join(', ')}</p>}</div>)}</section>
}
