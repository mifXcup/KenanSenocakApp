import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiRequest, formatMoney } from './lib/api'
import type { Employee, Material, Project, Site, Supplier } from './lib/types'
import { Button, EmptyState, ErrorState, LoadingRows, PageHeader } from './components/ui'

type CatalogItem = { name: string }
type Report = { title: string; columns: Array<{ key: string; label: string; kind: string }>; rows: Array<Record<string, unknown>>; totals: Record<string, unknown>; notes: string[]; warnings: Array<{ message: string }>; row_count: number }
function cell(value: unknown, kind: string) { if (value == null) return '—'; if (kind === 'money' && typeof value === 'number') return formatMoney(value); return String(value) }
export function ReportCenterPage() {
  const [family, setFamily] = useState<'finance' | 'staff'>('finance')
  const [name, setName] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [saveMessage, setSaveMessage] = useState('')
  const catalogs = useQuery({ queryKey: ['report-catalogs'], queryFn: async () => { const [finance, staff] = await Promise.all([apiRequest<CatalogItem[]>('/api/v1/reports/finance'), apiRequest<CatalogItem[]>('/api/v1/reports/staff')]); return { finance, staff } } })
  const projects = useQuery({ queryKey: ['report-projects'], queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const employees = useQuery({ queryKey: ['report-employees'], queryFn: () => apiRequest<Employee[]>('/api/v1/employees') })
  const suppliers = useQuery({ queryKey: ['report-suppliers'], queryFn: () => apiRequest<Supplier[]>('/api/v1/suppliers') })
  const customers = useQuery({ queryKey: ['report-customers'], queryFn: () => apiRequest<Array<{ id: string; name: string }>>('/api/v1/customers') })
  const periods = useQuery({ queryKey: ['report-periods'], queryFn: () => apiRequest<Array<{ id: string; title: string }>>('/api/v1/payroll-periods') })
  const materials = useQuery({ queryKey: ['report-materials'], queryFn: () => apiRequest<Material[]>('/api/v1/materials') })
  const sites = useQuery({ queryKey: ['report-sites'], queryFn: () => apiRequest<Site[]>('/api/v1/sites') })
  const selected = catalogs.data?.[family].some((item) => item.name === name) ? name : catalogs.data?.[family][0]?.name || ''
  const params = useMemo(() => new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString(), [filters])
  const report = useQuery({ queryKey: ['report', family, selected, params], enabled: !!selected, queryFn: () => apiRequest<Report>(`/api/v1/reports/${family}/${selected}${params ? `?${params}` : ''}`) })
  async function save(extension: 'xlsx' | 'pdf') { if (!window.ksDesktop || !selected) return; const result = await window.ksDesktop.api.downloadReport({ path: `/api/v1/reports/${family}/${selected}/export.${extension}${params ? `?${params}` : ''}`, filename: `Rapor ${selected}` }); setSaveMessage(result.status === 'saved' ? 'Dosya kaydedildi.' : result.status === 'cancelled' ? 'Kaydetme iptal edildi.' : result.message || 'Dosya kaydedilemedi.') }
  const filterOptions: Array<[string, string, Array<{ id: string; name: string }> | undefined]> = [['project_id', 'Proje', projects.data], ['customer_id', 'Müşteri', customers.data], ['supplier_id', 'Tedarikçi', suppliers.data], ['employee_id', 'Personel', employees.data], ['material_id', 'Malzeme', materials.data], ['site_id', 'Şantiye', sites.data], ['payroll_period_id', 'Maaş dönemi', periods.data?.map((item) => ({ id: item.id, name: item.title }))]]
  return <div className="page"><PageHeader title="Rapor Merkezi" description="Personel ve finans raporlarını aynı filtrelerle görüntüleyin ve kaydedin." />
    {catalogs.isLoading ? <LoadingRows /> : catalogs.error ? <ErrorState error={catalogs.error} onRetry={() => catalogs.refetch()} /> : <>
      <div className="tabs" role="tablist" aria-label="Rapor ailesi"><button role="tab" aria-selected={family === 'finance'} className="tabs__item" onClick={() => { setFamily('finance'); setName('') }}>Finans ({catalogs.data?.finance.length})</button><button role="tab" aria-selected={family === 'staff'} className="tabs__item" onClick={() => { setFamily('staff'); setName('') }}>Personel ({catalogs.data?.staff.length})</button></div>
      <section className="panel p0-section"><div className="p0-controls"><label>Rapor <select value={selected} onChange={(e) => setName(e.target.value)}>{catalogs.data?.[family].map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>{(['date_from', 'date_to'] as const).map((key) => <label key={key}>{key === 'date_from' ? 'Başlangıç' : 'Bitiş'} <input type="date" value={filters[key] || ''} onChange={(e) => setFilters({ ...filters, [key]: e.target.value })} /></label>)}{filterOptions.map(([key, label, options]) => <label key={key}>{label}<select value={filters[key] || ''} onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}><option value="">Tümü</option>{options?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>)}</div><div className="p0-controls"><Button onClick={() => save('xlsx')}>Excel kaydet</Button><Button onClick={() => save('pdf')}>PDF kaydet</Button>{saveMessage && <span role="status">{saveMessage}</span>}</div></section>
      {report.isLoading ? <LoadingRows /> : report.error ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : report.data && <section className="panel p0-section"><h2>{report.data.title}</h2><p>{report.data.row_count} satır</p>{report.data.rows.length ? <div className="table-wrap p0-report-table" role="region" aria-label={report.data.title} tabIndex={0}><table><thead><tr>{report.data.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{report.data.rows.map((row, i) => <tr key={i}>{report.data!.columns.map((column) => <td key={column.key}>{cell(row[column.key], column.kind)}</td>)}</tr>)}</tbody><tfoot><tr>{report.data.columns.map((column) => <td key={column.key}>{cell(report.data!.totals[column.key], column.kind)}</td>)}</tr></tfoot></table></div> : <EmptyState title="Bu filtrede kayıt yok" description="Filtreleri değiştirerek tekrar deneyin." />}{report.data.notes.map((note, i) => <p key={i}>{note}</p>)}{report.data.warnings.map((warning, i) => <p role="alert" key={i}>{warning.message}</p>)}</section>}
    </>}
  </div>
}
