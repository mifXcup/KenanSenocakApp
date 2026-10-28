import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { apiRequest, formatMoney, makeIdempotencyKey, toKurus } from './lib/api'
import { Button, EmptyState, ErrorState, LoadingRows, PageHeader } from './components/ui'
import type { Employee, Project, Supplier } from './lib/types'
import { CustomerExtras } from './customerExtras'
import { AttendanceImport } from './attendanceImport'
import { CalendarManualActions } from './calendarManualActions'
import { CustomerAging } from './customerAging'
import { LeaveLedgerControls } from './leaveLedgerControls'

const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const qs = (values: Record<string, string>) => new URLSearchParams(Object.entries(values).filter(([, value]) => value)).toString()
type SourceRoute = { entity?: string; entity_id?: string; project_id?: string; employee_id?: string; customer_id?: string; supplier_id?: string }
function sourceLink(source?: SourceRoute) {
  if (!source) return '/takvim'
  if (source.customer_id || source.entity === 'customer') return `/musteriler?customer=${source.customer_id || source.entity_id || ''}`
  if (source.supplier_id || source.entity === 'purchase') return `/firmalar?supplier=${source.supplier_id || ''}`
  if (source.employee_id || source.entity === 'leave_request') return `/personel?employee=${source.employee_id || ''}`
  if (source.project_id) return `/projeler?project=${source.project_id}`
  return '/takvim'
}
type CalendarEvent = { event_id: string; title: string; description?: string | null; event_type: string; state: string; start_date: string; occurrence_date: string; amount_kurus: number | null; source_type: string; source_id: string; source_route: SourceRoute; repeat_rule?: string }
const eventLabels: Record<string, string> = { receivable_due: 'Tahsilat', supplier_payable: 'Tedarikçi ödemesi', payroll_due: 'Maaş', leave: 'İzin', leave_return: 'İşe dönüş', project_task: 'Görev', project_visit: 'Ziyaret', manual_event: 'Olay', reminder: 'Hatırlatma' }
function EventList({ events }: { events: CalendarEvent[] }) {
  if (!events.length) return <p>Bu aralıkta kayıt yok.</p>
  return <div className="p0-list">{events.map((event) => <article className="p0-row" key={event.event_id}><span className="badge">{eventLabels[event.event_type] || event.event_type}</span><div><strong>{event.title}</strong><small>{event.start_date} · {event.state}{event.description ? ` · ${event.description}` : ''}</small></div>{event.amount_kurus != null && <b>{formatMoney(event.amount_kurus)}</b>}<Link to={sourceLink(event.source_route)}>Kaynağa git</Link></article>)}</div>
}

type TodayGroup = { count: number; amount_kurus: number; receivable_kurus: number; payable_kurus: number; events: CalendarEvent[] }
type TodayResponse = { overdue: TodayGroup; today: TodayGroup; next_7_days: TodayGroup; totals: Record<string, number> }
export function TodayPage() {
  const summary = useQuery({ queryKey: ['today'], queryFn: () => apiRequest<TodayResponse>('/api/v1/today'), refetchInterval: 60000 })
  const backup = useQuery({ queryKey: ['backup-status'], queryFn: () => apiRequest<{ healthy: boolean; latest_backup?: { created_at: string } | null }>('/api/v1/backups/status') })
  const date = today()
  const attendance = useQuery({ queryKey: ['attendance-today', date], queryFn: () => apiRequest<{ totals: { enforced_missing_day: number; missing_required_day: number } }>(`/api/v1/attendance/check?date_from=${date}&date_to=${date}`) })
  return <div className="page"><PageHeader title="Bugün" description="Gecikmiş işler, bugünkü vadeler ve önümüzdeki yedi gün." />
    {summary.isLoading ? <LoadingRows /> : summary.error ? <ErrorState error={summary.error} onRetry={() => summary.refetch()} /> : summary.data && <>
      <div className="p0-metrics"><div><span>Gecikmiş</span><strong>{summary.data.overdue.count}</strong></div><div><span>Bugün</span><strong>{summary.data.today.count}</strong></div><div><span>Yaklaşan tahsilat</span><strong>{formatMoney(summary.data.next_7_days.receivable_kurus)}</strong></div><div><span>Yaklaşan ödeme</span><strong>{formatMoney(summary.data.next_7_days.payable_kurus)}</strong></div></div>
      {([['Gecikmiş', summary.data.overdue], ['Bugün', summary.data.today], ['Sonraki 7 gün', summary.data.next_7_days]] as const).map(([label, group]) => <section className="panel p0-section" key={label}><h2>{label} <small>{group.count}</small></h2><EventList events={group.events} /></section>)}
    </>}
    <section className="panel p0-section"><h2>Kontrol</h2><p>Son yedek: {backup.data?.latest_backup?.created_at ? new Date(backup.data.latest_backup.created_at).toLocaleString('tr-TR') : 'Henüz yedek yok'}</p>{backup.data && !backup.data.healthy && <p role="alert">Yedekleme sağlığı kontrol gerektiriyor.</p>}{attendance.data && attendance.data.totals.enforced_missing_day > 0 && <p role="alert"><Link to="/puantaj-izin">{attendance.data.totals.enforced_missing_day} zorunlu puantaj günü eksik. İncele</Link></p>}</section>
  </div>
}

export function CalendarPage() {
  const [view, setView] = useState<'month' | 'week' | 'agenda'>('month')
  const [anchor, setAnchor] = useState(today())
  const [type, setType] = useState('')
  const [state, setState] = useState('')
  const [projectId, setProjectId] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [supplierId, setSupplierId] = useState('')
  const [title, setTitle] = useState('')
  const [eventDate, setEventDate] = useState(today())
  const [repeat, setRepeat] = useState('none')
  const [error, setError] = useState('')
  const client = useQueryClient()
  const range = useMemo(() => { const date = new Date(`${anchor}T12:00:00`); const start = new Date(date); const end = new Date(date); if (view === 'month') { start.setDate(1); end.setMonth(end.getMonth() + 1, 0) } else if (view === 'week') { start.setDate(start.getDate() - ((start.getDay() + 6) % 7)); end.setTime(start.getTime()); end.setDate(end.getDate() + 6) } else end.setDate(end.getDate() + 30); return { start: start.toLocaleDateString('sv-SE'), end: end.toLocaleDateString('sv-SE') } }, [anchor, view])
  const events = useQuery({ queryKey: ['calendar', range, type, state, projectId, employeeId, customerId, supplierId], queryFn: () => apiRequest<CalendarEvent[] | { events: CalendarEvent[] }>(`/api/v1/calendar/events?${qs({ date_from: range.start, date_to: range.end, event_type: type, state, project_id: projectId, employee_id: employeeId, customer_id: customerId, supplier_id: supplierId })}`) })
  const projects = useQuery({ queryKey: ['project-options'], queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const employees = useQuery({ queryKey: ['employee-options'], queryFn: () => apiRequest<Employee[]>('/api/v1/employees') })
  const customers = useQuery({ queryKey: ['calendar-customer-options'], queryFn: () => apiRequest<Customer[]>('/api/v1/customers') })
  const suppliers = useQuery({ queryKey: ['calendar-supplier-options'], queryFn: () => apiRequest<Supplier[]>('/api/v1/suppliers') })
  const create = useMutation({ mutationFn: () => apiRequest('/api/v1/calendar/manual-events', { method: 'POST', body: { title, start_date: eventDate, repeat_rule: repeat, event_type: 'manual_event' } }), onSuccess: () => { setTitle(''); setError(''); client.invalidateQueries({ queryKey: ['calendar'] }) }, onError: (e) => setError(e.message) })
  const list = Array.isArray(events.data) ? events.data : events.data?.events || []
  const dates = view === 'agenda' ? [...new Set(list.map((event) => event.start_date))].sort() : Array.from({ length: Math.round((new Date(`${range.end}T12:00:00`).getTime() - new Date(`${range.start}T12:00:00`).getTime()) / 86400000) + 1 }, (_, index) => { const current = new Date(`${range.start}T12:00:00`); current.setDate(current.getDate() + index); return current.toLocaleDateString('sv-SE') })
  return <div className="page"><PageHeader title="Takvim" description="Kaynak kayıtlara bağlı görevler, vadeler, ziyaretler ve izinler." />
    <div className="panel p0-section"><div className="p0-controls"><label>Görünüm <select value={view} onChange={(e) => setView(e.target.value as typeof view)}><option value="month">Ay</option><option value="week">Hafta</option><option value="agenda">Gündem</option></select></label><label>Tarih <input type="date" value={anchor} onChange={(e) => setAnchor(e.target.value)} /></label><label>Tür <select value={type} onChange={(e) => setType(e.target.value)}><option value="">Tümü</option>{Object.entries(eventLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label>Durum <select value={state} onChange={(e) => setState(e.target.value)}><option value="">Tümü</option><option value="overdue">Gecikmiş</option><option value="today">Bugün</option><option value="upcoming">Yaklaşan</option><option value="completed">Tamamlandı</option></select></label><label>Proje <select value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Tümü</option>{projects.data?.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label>Personel <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}><option value="">Tümü</option>{employees.data?.map((employee) => <option key={employee.id} value={employee.id}>{employee.name}</option>)}</select></label></div></div>
    <div className="panel p0-section"><div className="p0-controls"><label>Müşteri <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}><option value="">Tümü</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label><label>Tedarikçi <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}><option value="">Tümü</option>{suppliers.data?.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label></div></div>
    {events.isLoading ? <LoadingRows /> : events.error ? <ErrorState error={events.error} onRetry={() => events.refetch()} /> : !list.length ? <EmptyState title="Takvim boş" description="Bu tarih aralığında olay bulunamadı." /> : <div className={view === 'month' ? 'p0-calendar-grid' : 'p0-calendar-agenda'}>{dates.map((date) => <section className="panel p0-section" key={date}><h2>{date}</h2><EventList events={list.filter((event) => event.start_date === date)} />{list.filter((event) => event.start_date === date && event.source_type === 'manual_event').map((event) => <CalendarManualActions key={`${event.event_id}-action`} event={event} onChanged={() => events.refetch()} />)}</section>)}</div>}
    <section className="panel p0-section"><h2>Olay ekle</h2><form className="p0-controls" onSubmit={(e) => { e.preventDefault(); create.mutate() }}><label>Başlık <input required minLength={2} value={title} onChange={(e) => setTitle(e.target.value)} /></label><label>Tarih <input required type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} /></label><label>Tekrar <select value={repeat} onChange={(e) => setRepeat(e.target.value)}><option value="none">Yok</option><option value="daily">Günlük</option><option value="weekly">Haftalık</option><option value="monthly">Aylık</option></select></label><Button variant="primary" loading={create.isPending}>Ekle</Button></form>{error && <p role="alert">{error}</p>}</section>
  </div>
}

type Customer = { id: string; name: string; phone: string | null; address: string | null; contact_person: string | null; note: string | null; status: string; receivable_kurus?: number; credit_kurus?: number; net_balance_kurus?: number; project_count?: number }
type Schedule = { id: string; title: string; due_date: string; amount_kurus: number; remaining_kurus: number; state: string; project_id: string | null }
type Movement = { id: string; movement_date: string; movement_type: string; amount_kurus: number; project_id: string | null; unallocated_kurus?: number; status: string }
export function CustomersPage() {
  const [searchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState(searchParams.get('customer') || '')
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(today())
  const [scheduleTitle, setScheduleTitle] = useState('Kapora')
  const [collectionProjectId, setCollectionProjectId] = useState('')
  const [error, setError] = useState('')
  const client = useQueryClient()
  const customers = useQuery({ queryKey: ['customers', search], queryFn: () => apiRequest<Customer[]>(`/api/v1/customers?${qs({ q: search, limit: '500' })}`) })
  const selected = customers.data?.find((item) => item.id === selectedId) || customers.data?.[0]
  const detail = useQuery({ queryKey: ['customer', selected?.id], enabled: !!selected, queryFn: () => apiRequest<Customer>(`/api/v1/customers/${selected!.id}`) })
  const statement = useQuery({ queryKey: ['customer-statement', selected?.id], enabled: !!selected, queryFn: () => apiRequest<{ rows: Array<{ movement_id: string; movement_date: string; movement_type: string; balance_kurus: number; increase_kurus: number; decrease_kurus: number }> }>(`/api/v1/customers/${selected!.id}/statement`) })
  const schedules = useQuery({ queryKey: ['customer-schedules', selected?.id], enabled: !!selected, queryFn: () => apiRequest<Schedule[]>(`/api/v1/receivable-schedules?customer_id=${selected!.id}`) })
  const movements = useQuery({ queryKey: ['customer-movements', selected?.id], enabled: !!selected, queryFn: () => apiRequest<Movement[]>(`/api/v1/customer-financial-movements?customer_id=${selected!.id}`) })
  const projects = useQuery({ queryKey: ['customer-projects'], queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  async function submit(path: string, body: unknown) { try { setError(''); await apiRequest(path, { method: 'POST', body }); await client.invalidateQueries(); setAmount('') } catch (e) { setError(e instanceof Error ? e.message : String(e)) } }
  return <div className="page"><PageHeader title="Müşteri Cari" description="Alacak, tahsilat planı, avans ve ekstre." />
    <div className="p0-two-col"><aside className="panel p0-section"><input aria-label="Müşteri ara" placeholder="Müşteri ara" value={search} onChange={(e) => setSearch(e.target.value)} />{customers.isLoading ? <LoadingRows /> : customers.error ? <ErrorState error={customers.error} onRetry={() => customers.refetch()} /> : customers.data?.map((item) => <button className="p0-select-row" key={item.id} onClick={() => setSelectedId(item.id)}>{item.name}</button>)}<form onSubmit={(e) => { e.preventDefault(); submit('/api/v1/customers', { name }) }}><h3>Yeni müşteri</h3><input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /><Button variant="primary">Oluştur</Button></form></aside>
    <div>{!selected ? <EmptyState title="Müşteri seçin" description="Cari detayları görüntülemek için müşteri oluşturun veya seçin." /> : <>
      <section className="panel p0-section"><h2>{selected.name}</h2>{detail.isLoading ? <LoadingRows /> : detail.error ? <ErrorState error={detail.error} onRetry={() => detail.refetch()} /> : <div className="p0-metrics"><div><span>Brüt alacak</span><strong>{formatMoney(detail.data?.receivable_kurus)}</strong></div><div><span>Avans / kredi</span><strong>{formatMoney(detail.data?.credit_kurus)}</strong></div><div><span>Net bakiye</span><strong>{formatMoney(detail.data?.net_balance_kurus)}</strong></div></div>}<div className="p0-controls"><span>{selected.phone}</span><span>{selected.address}</span><Button onClick={() => submit(`/api/v1/customers/${selected.id}/${selected.status === 'archived' ? 'unarchive' : 'archive'}`, {})}>{selected.status === 'archived' ? 'Aktifleştir' : 'Arşivle'}</Button></div></section>
      <section className="panel p0-section"><h2>Bağlı projeler</h2>{projects.data?.filter((project) => project.customer_name === selected.name).map((project) => <p key={project.id}><Link to={`/projeler?project=${project.id}`}>{project.name}</Link></p>)}</section>
      <section className="panel p0-section"><h2>Tahsilat planı</h2>{schedules.isLoading ? <LoadingRows /> : schedules.error ? <ErrorState error={schedules.error} onRetry={() => schedules.refetch()} /> : schedules.data?.map((item) => <div className="p0-row" key={item.id}><strong>{item.title}</strong><span>{item.due_date}</span><span>{formatMoney(item.amount_kurus)}</span><span>Kalan {formatMoney(item.remaining_kurus)}</span></div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); submit('/api/v1/receivable-schedules', { customer_id: selected.id, project_id: collectionProjectId || null, title: scheduleTitle, due_date: date, amount_kurus: toKurus(amount) }) }}><select aria-label="Plan projesi" value={collectionProjectId} onChange={(e) => setCollectionProjectId(e.target.value)}><option value="">Müşteri geneli</option>{projects.data?.filter((project) => project.customer_name === selected.name).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><input aria-label="Plan başlığı" value={scheduleTitle} onChange={(e) => setScheduleTitle(e.target.value)} /><input aria-label="Vade" type="date" value={date} onChange={(e) => setDate(e.target.value)} /><input aria-label="Tutar TL" placeholder="Tutar TL" value={amount} onChange={(e) => setAmount(e.target.value)} /><Button variant="primary">Plan ekle</Button></form></section>
      <section className="panel p0-section"><h2>Tahsilatlar ve avanslar</h2>{movements.data?.map((item) => <div className="p0-row" key={item.id}><span>{item.movement_date}</span><strong>{item.movement_type}</strong><span>{formatMoney(item.amount_kurus)}</span><span>{item.project_id ? 'Projeye bağlı' : 'Bağlantısız'}</span>{item.movement_type !== 'reversal' && item.status === 'active' && <Button onClick={() => submit(`/api/v1/customer-financial-movements/${item.id}/reverse`, { movement_date: today() })}>Ters kayıt</Button>}</div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); submit('/api/v1/customer-financial-movements', { customer_id: selected.id, movement_date: date, movement_type: 'collection', project_id: collectionProjectId || null, amount_kurus: toKurus(amount), idempotency_key: makeIdempotencyKey('collection') }) }}><select aria-label="Tahsilat projesi" value={collectionProjectId} onChange={(e) => setCollectionProjectId(e.target.value)}><option value="">Bağlantısız avans</option>{projects.data?.filter((project) => project.customer_name === selected.name).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><input aria-label="Tahsilat tarihi" type="date" value={date} onChange={(e) => setDate(e.target.value)} /><input aria-label="Tahsilat TL" placeholder="Tutar TL" value={amount} onChange={(e) => setAmount(e.target.value)} /><Button variant="primary">Tahsilat kaydet</Button></form></section>
      <section className="panel p0-section"><h2>Ekstre</h2>{statement.isLoading ? <LoadingRows /> : statement.error ? <ErrorState error={statement.error} onRetry={() => statement.refetch()} /> : !statement.data?.rows.length ? <p>Ekstre hareketi yok.</p> : statement.data.rows.map((row) => <div className="p0-row" key={row.movement_id}><span>{row.movement_date}</span><span>{row.movement_type}</span><span>Artış {formatMoney(row.increase_kurus)}</span><span>Azalış {formatMoney(row.decrease_kurus)}</span><strong>{formatMoney(row.balance_kurus)}</strong></div>)}</section><section className="panel p0-section"><h2>Yaşlandırma</h2><CustomerAging customerId={selected.id} /></section>
      <CustomerExtras key={selected.id} customer={selected} collections={movements.data || []} schedules={schedules.data || []} />
    </>}</div></div>{error && <p role="alert">{error}</p>}
  </div>
}

export function AttendancePage() {
  const [month, setMonth] = useState(today().slice(0, 7))
  const [employeeId, setEmployeeId] = useState('')
  const [workDate, setWorkDate] = useState(today())
  const [workStatus, setWorkStatus] = useState('worked')
  const [hours, setHours] = useState('8')
  const [overtime, setOvertime] = useState('0')
  const [leaveType, setLeaveType] = useState('annual')
  const [error, setError] = useState('')
  const client = useQueryClient()
  const start = `${month}-01`; const end = new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).toLocaleDateString('sv-SE')
  const employees = useQuery({ queryKey: ['attendance-employees'], queryFn: () => apiRequest<Employee[]>('/api/v1/employees') })
  const logs = useQuery({ queryKey: ['attendance-logs', month], queryFn: () => apiRequest<Array<{ id: string; employee_id: string; work_date: string; work_status: string; normal_hours: string; overtime_hours: string; status: string }>>(`/api/v1/work-logs?date_from=${start}&date_to=${end}&limit=500`) })
  const check = useQuery({ queryKey: ['attendance-check', month], queryFn: () => apiRequest<{ totals: Record<string, number>; employees: Array<{ employee_id: string; employee_name: string; issues: Array<{ date: string; code: string }> }> }>(`/api/v1/attendance/check?date_from=${start}&date_to=${end}`) })
  const leave = useQuery({ queryKey: ['leave-requests'], queryFn: () => apiRequest<Array<{ id: string; employee_id: string; leave_type_code: string; start_date: string; end_date: string; request_state: string }>>('/api/v1/leave-requests') })
  async function submit(path: string, body: unknown) { try { setError(''); await apiRequest(path, { method: 'POST', body }); await client.invalidateQueries() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } }
  const days = Array.from({ length: Number(end.slice(8)) }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`)
  return <div className="page"><PageHeader title="Puantaj ve İzin" description="Aylık çalışma çizelgesi, izin ve eksik kayıt denetimi." /><div className="p0-controls"><label>Ay <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></label></div>
    {employees.isLoading || logs.isLoading ? <LoadingRows /> : employees.error || logs.error ? <ErrorState error={employees.error || logs.error} onRetry={() => { employees.refetch(); logs.refetch() }} /> : <div className="table-wrap" role="region" aria-label="Aylık puantaj" tabIndex={0}><table><thead><tr><th>Personel</th>{days.map((day) => <th key={day}>{day.slice(8)}</th>)}</tr></thead><tbody>{employees.data?.map((employee) => <tr key={employee.id}><th>{employee.name}</th>{days.map((day) => { const log = logs.data?.find((item) => item.employee_id === employee.id && item.work_date === day && item.status === 'active'); return <td key={day} title={log ? `${log.work_status}: ${log.normal_hours} saat + ${log.overtime_hours} mesai` : 'Kayıt yok'}>{log ? log.work_status.slice(0, 2) : '—'}</td> })}</tr>)}</tbody></table></div>}
    <section className="panel p0-section"><h2>Puantaj girişi</h2><form className="p0-controls" onSubmit={(e) => { e.preventDefault(); submit('/api/v1/work-logs', { employee_id: employeeId, work_date: workDate, work_status: workStatus, normal_hours: hours, overtime_hours: overtime }) }}><select aria-label="Personel" required value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}><option value="">Personel seç</option>{employees.data?.map((employee) => <option value={employee.id} key={employee.id}>{employee.name}</option>)}</select><input type="date" aria-label="Tarih" value={workDate} onChange={(e) => setWorkDate(e.target.value)} /><select aria-label="Durum" value={workStatus} onChange={(e) => setWorkStatus(e.target.value)}>{['worked', 'absent', 'annual_leave', 'sick_leave', 'excused_leave', 'public_holiday', 'weekly_rest'].map((item) => <option value={item} key={item}>{item}</option>)}</select><input aria-label="Normal saat" type="number" min="0" max="24" value={hours} onChange={(e) => setHours(e.target.value)} /><input aria-label="Fazla mesai" type="number" min="0" max="24" value={overtime} onChange={(e) => setOvertime(e.target.value)} /><Button variant="primary">Kaydet</Button></form></section>
    <section className="panel p0-section"><h2>Eksik ve çakışan kayıtlar</h2>{check.isLoading ? <LoadingRows /> : check.error ? <ErrorState error={check.error} onRetry={() => check.refetch()} /> : check.data?.employees.map((item) => <div key={item.employee_id}><strong>{item.employee_name}</strong>{item.issues.map((issue, i) => <span className="badge" key={i}>{issue.date}: {issue.code}</span>)}</div>)}</section>
    <AttendanceImport />
    <section className="panel p0-section"><h2>İzin</h2>{employeeId && <LeaveLedgerControls employeeId={employeeId} />}{leave.data?.map((item) => <div className="p0-row" key={item.id}><span>{employees.data?.find((employee) => employee.id === item.employee_id)?.name}</span><span>{item.leave_type_code}</span><span>{item.start_date}–{item.end_date}</span><strong>{item.request_state}</strong>{item.request_state === 'pending' && <><Button onClick={() => submit(`/api/v1/leave-requests/${item.id}/approve`, {})}>Onayla</Button><Button onClick={() => submit(`/api/v1/leave-requests/${item.id}/reject`, {})}>Reddet</Button></>}{item.request_state === 'approved' && <Button onClick={() => submit(`/api/v1/leave-requests/${item.id}/cancel`, {})}>İptal et</Button>}</div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); submit('/api/v1/leave-requests', { employee_id: employeeId, leave_type_code: leaveType, start_date: workDate, end_date: workDate, idempotency_key: makeIdempotencyKey('leave') }) }}><select aria-label="İzin türü" value={leaveType} onChange={(e) => setLeaveType(e.target.value)}>{['annual', 'sick', 'excused', 'unpaid', 'other_paid'].map((item) => <option key={item} value={item}>{item}</option>)}</select><Button variant="primary" disabled={!employeeId}>İzin talebi oluştur</Button></form></section>{error && <p role="alert">{error}</p>}
  </div>
}
