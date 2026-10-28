import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PersonnelExtras } from './personnelExtras'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck, ClockCounterClockwise, Coins, HardHat, Plus, UserPlus, UsersThree } from '@phosphor-icons/react'
import { apiRequest, formatDate, formatMoney, toKurus } from './lib/api'
import type { Employee, EmployeePayment, Project, Site, WorkLog } from './lib/types'
import { Button, EmptyState, ErrorState, Field, LoadingRows, PageHeader, SelectInput, SideSheet, TextInput } from './components/ui'
import './operations.css'

const todayIso = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date())

const operationKeys = {
  employees: ['employees'] as const,
  sites: ['sites'] as const,
  workLogs: ['work-logs'] as const,
  employeePayments: ['employee-payments'] as const,
  projects: ['projects'] as const,
}

const wageTypeLabel = { monthly: 'Aylık', daily: 'Günlük', hourly: 'Saatlik' } as const
const workStatusLabel = { worked: 'Çalıştı', half_day: 'Yarım gün', overtime: 'Fazla mesai', paid_leave: 'Ücretli izin', unpaid_leave: 'Ücretsiz izin', absent: 'Devamsız' } as const

type WageType = keyof typeof wageTypeLabel
type WorkStatus = keyof typeof workStatusLabel
type DetailedWorkLog = WorkLog & {
  work_status?: WorkStatus
  normal_hours?: string
  overtime_hours?: string
  calculated_amount_kurus?: number | null
  manual_amount_kurus?: number | null
}
type WageRate = {
  id: string
  employee_id: string
  effective_from: string
  effective_to: string | null
  wage_type: WageType
  rate_kurus: number
  reason: string | null
  status: string
}

type SheetKind = 'employee' | 'site' | 'work' | 'payment' | 'wage' | null

export function PersonnelPage() {
  const [searchParams] = useSearchParams()
  const client = useQueryClient()
  const [sheet, setSheet] = useState<SheetKind>(null)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(searchParams.get('employee') || '')
  const employees = useQuery({ queryKey: operationKeys.employees, queryFn: () => apiRequest<Employee[]>('/api/v1/employees') })
  const sites = useQuery({ queryKey: operationKeys.sites, queryFn: () => apiRequest<Site[]>('/api/v1/sites') })
  const workLogs = useQuery({ queryKey: operationKeys.workLogs, queryFn: () => apiRequest<DetailedWorkLog[]>('/api/v1/work-logs') })
  const payments = useQuery({ queryKey: operationKeys.employeePayments, queryFn: () => apiRequest<EmployeePayment[]>('/api/v1/employee-payments') })
  const projects = useQuery({ queryKey: operationKeys.projects, queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const selectedEmployee = employees.data?.find((item) => item.id === selectedEmployeeId) ?? null
  const wageRates = useQuery({
    queryKey: ['employee-wage-rates', selectedEmployeeId],
    queryFn: () => apiRequest<WageRate[]>(`/api/v1/employees/${selectedEmployeeId}/wage-rates`),
    enabled: Boolean(selectedEmployeeId),
  })

  const employeeById = useMemo(() => Object.fromEntries((employees.data ?? []).map((item) => [item.id, item.name])), [employees.data])
  const siteById = useMemo(() => Object.fromEntries((sites.data ?? []).map((item) => [item.id, item.name])), [sites.data])
  const totals = useMemo(() => ({
    labor: (workLogs.data ?? []).filter((item) => item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0),
    paid: (payments.data ?? []).filter((item) => item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0),
  }), [payments.data, workLogs.data])
  const loading = [employees, sites, workLogs, payments, projects].some((query) => query.isLoading)
  const firstError = [employees, sites, workLogs, payments, projects].find((query) => query.error)?.error
  const refresh = () => {
    client.invalidateQueries({ queryKey: operationKeys.employees })
    client.invalidateQueries({ queryKey: operationKeys.sites })
    client.invalidateQueries({ queryKey: operationKeys.workLogs })
    client.invalidateQueries({ queryKey: operationKeys.employeePayments })
    if (selectedEmployeeId) client.invalidateQueries({ queryKey: ['employee-wage-rates', selectedEmployeeId] })
  }

  return (
    <div className="page">
      <PageHeader title="Personel ve Şantiye" description="Çalışma günlerini, işçilik tutarlarını ve personele yapılan ödemeleri birlikte izleyin." action={<Button variant="primary" onClick={() => setSheet('work')} disabled={!employees.data?.length}><Plus size={18} />Çalışma ekle</Button>} />
      {firstError && <ErrorState error={firstError} />}
      {loading ? <LoadingRows count={4} /> : (
        <>
          <section className="operation-summary" aria-label="Personel özeti">
            <div><UsersThree size={20} /><span>Aktif personel</span><strong>{employees.data?.length ?? 0}</strong></div>
            <div><HardHat size={20} /><span>Şantiye</span><strong>{sites.data?.length ?? 0}</strong></div>
            <div><CalendarCheck size={20} /><span>İşçilik toplamı</span><strong>{formatMoney(totals.labor)}</strong></div>
            <div><Coins size={20} /><span>Yapılan ödeme</span><strong>{formatMoney(totals.paid)}</strong></div>
          </section>

          <div className="operation-actions" aria-label="Hızlı işlemler">
            <Button onClick={() => setSheet('employee')}><UserPlus size={18} />Personel ekle</Button>
            <Button onClick={() => setSheet('site')}><HardHat size={18} />Şantiye ekle</Button>
            <Button onClick={() => setSheet('payment')} disabled={!employees.data?.length}><Coins size={18} />Ödeme ekle</Button>
          </div>

          {selectedEmployee && (
            <EmployeeDetail
              employee={selectedEmployee}
              rates={wageRates.data ?? []}
              ratesLoading={wageRates.isLoading}
              labor={(workLogs.data ?? []).filter((item) => item.employee_id === selectedEmployee.id && item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0)}
              paid={(payments.data ?? []).filter((item) => item.employee_id === selectedEmployee.id && item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0)}
              onClose={() => setSelectedEmployeeId('')}
              onNewWage={() => setSheet('wage')}
            />
          )}

          <div className="operations-grid">
            <section className="panel">
              <div className="panel__header"><h2>Personel</h2><span className="count-label">{employees.data?.length ?? 0} kayıt</span></div>
              {!employees.data?.length ? <EmptyState title="Henüz personel yok" description="Çalışma ve ödeme kaydı girebilmek için önce personel kartı oluşturun." action={<Button onClick={() => setSheet('employee')}>Personel ekle</Button>} /> : (
                <div className="record-list">{employees.data.map((employee) => {
                  const labor = (workLogs.data ?? []).filter((item) => item.employee_id === employee.id && item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0)
                  const paid = (payments.data ?? []).filter((item) => item.employee_id === employee.id && item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0)
                  return <button type="button" className={`record-row record-row--button ${selectedEmployeeId === employee.id ? 'record-row--selected' : ''}`} key={employee.id} onClick={() => setSelectedEmployeeId(employee.id)} aria-pressed={selectedEmployeeId === employee.id}><div className="record-avatar" aria-hidden="true">{employee.name.slice(0, 1).toLocaleUpperCase('tr-TR')}</div><div><strong>{employee.name}</strong><span>{employee.role || 'Görev belirtilmedi'}{employee.current_rate_kurus != null ? ` · ${wageTypeLabel[employee.wage_type ?? 'daily']} ${formatMoney(employee.current_rate_kurus)}` : ''}</span></div><div className="record-row__money"><strong>{formatMoney(labor - paid)}</strong><span>kayıt farkı</span></div></button>
                })}</div>
              )}
            </section>

            <section className="panel">
              <div className="panel__header"><h2>Son hareketler</h2><span className="count-label">Çalışma ve ödeme</span></div>
              {!workLogs.data?.length && !payments.data?.length ? <p className="muted">Henüz personel hareketi yok.</p> : (
                <div className="timeline-list">
                  {[...(workLogs.data ?? []).map((item) => ({ id: item.id, date: item.work_date, title: employeeById[item.employee_id] ?? 'Personel', detail: `${workStatusLabel[item.work_status ?? 'worked']} · ${item.hours} saat${item.site_id ? ` · ${siteById[item.site_id] ?? 'Şantiye'}` : ''}`, amount: item.amount_kurus, type: 'Çalışma' })), ...(payments.data ?? []).filter((item) => item.status === 'active').map((item) => ({ id: item.id, date: item.payment_date, title: employeeById[item.employee_id] ?? 'Personel', detail: item.payment_type === 'advance' ? 'Avans ödemesi' : 'Maaş ödemesi', amount: item.amount_kurus, type: 'Ödeme' }))]
                    .sort((a, b) => b.date.localeCompare(a.date)).slice(0, 8).map((item) => <article className="timeline-row" key={`${item.type}-${item.id}`}><span className={`movement-mark movement-mark--${item.type === 'Ödeme' ? 'payment' : 'work'}`} aria-hidden="true" /><div><strong>{item.title}</strong><span>{item.type} · {item.detail} · {formatDate(item.date)}</span></div><strong className="money">{formatMoney(item.amount)}</strong></article>)}
                </div>
              )}
            </section>
          </div>
        </>
      )}

      <EmployeeSheet open={sheet === 'employee'} onClose={() => setSheet(null)} onSaved={refresh} />
      <SiteSheet open={sheet === 'site'} onClose={() => setSheet(null)} onSaved={refresh} projects={projects.data ?? []} />
      <WorkSheet open={sheet === 'work'} onClose={() => setSheet(null)} onSaved={refresh} employees={employees.data ?? []} sites={sites.data ?? []} projects={projects.data ?? []} />
      <PaymentSheet open={sheet === 'payment'} onClose={() => setSheet(null)} onSaved={refresh} employees={employees.data ?? []} />
      <WageSheet open={sheet === 'wage'} onClose={() => setSheet(null)} onSaved={refresh} employee={selectedEmployee} />
    </div>
  )
}

function EmployeeDetail({ employee, rates, ratesLoading, labor, paid, onClose, onNewWage }: { employee: Employee; rates: WageRate[]; ratesLoading: boolean; labor: number; paid: number; onClose: () => void; onNewWage: () => void }) {
  return <section className="employee-detail" aria-label={`${employee.name} personel özeti`}>
    <header className="employee-detail__header"><div><span className="eyebrow-dark">PERSONEL KARTI</span><h2>{employee.name}</h2><p>{employee.role || 'Görev belirtilmedi'}{employee.employment_start_date ? ` · ${formatDate(employee.employment_start_date)} tarihinde başladı` : ''}</p></div><div className="employee-detail__actions"><Button onClick={onNewWage}><ClockCounterClockwise size={17} />Ücreti güncelle</Button><Button variant="quiet" onClick={onClose}>Kapat</Button></div></header>
    <div className="employee-detail__facts">
      <div><span>Güncel ücret</span><strong>{formatMoney(employee.current_rate_kurus)}</strong><small>{wageTypeLabel[employee.wage_type ?? 'daily']}</small></div>
      <div><span>Hesaplanan işçilik</span><strong>{formatMoney(labor)}</strong><small>Çalışma kayıtlarına göre</small></div>
      <div><span>Yapılan ödeme</span><strong>{formatMoney(paid)}</strong><small>Maaş ve avans toplamı</small></div>
      <div><span>Kayıt farkı</span><strong>{formatMoney(labor - paid)}</strong><small>Kesinleşmiş maaş borcu değildir</small></div>
    </div>
    <PersonnelExtras key={employee.id} employee={employee} />
    <div className="employee-detail__lower"><div><h3>Ödeme bilgisi</h3><dl><div><dt>Telefon</dt><dd>{employee.phone || 'Girilmedi'}</dd></div><div><dt>IBAN</dt><dd className="mono-value">{employee.iban || 'Girilmedi'}</dd></div></dl></div><div><h3>Ücret geçmişi</h3>{ratesLoading ? <LoadingRows count={2} /> : !rates.length ? <p className="muted">Henüz ücret geçmişi yok.</p> : <div className="wage-history">{rates.slice(0, 4).map((rate) => <div key={rate.id}><span><strong>{wageTypeLabel[rate.wage_type]} · {formatMoney(rate.rate_kurus)}</strong><small>{formatDate(rate.effective_from)}{rate.effective_to ? ` - ${formatDate(rate.effective_to)}` : ' tarihinden itibaren'}</small></span>{rate.reason && <em>{rate.reason}</em>}</div>)}</div>}</div></div>
  </section>
}

function EmployeeSheet({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(''); const [role, setRole] = useState(''); const [phone, setPhone] = useState(''); const [rate, setRate] = useState(''); const [wageType, setWageType] = useState<'monthly' | 'daily' | 'hourly'>('monthly'); const [startDate, setStartDate] = useState(todayIso); const [iban, setIban] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<Employee>('/api/v1/employees', { method: 'POST', body: { name, role: role || null, phone: phone || null, wage_type: wageType, current_rate_kurus: rate ? toKurus(rate) : null, rate_effective_from: rate ? startDate : null, employment_start_date: startDate || null, employment_state: 'active', iban: iban || null, note: null } }), onSuccess: () => { onSaved(); onClose(); setName(''); setRole(''); setPhone(''); setRate(''); setIban('') } })
  return <SideSheet title="Yeni personel" description="Personel kartı, çalışma biçimi ve ücret başlangıcı." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={name.trim().length < 2} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Ad soyad"><TextInput value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field><div className="form-grid"><Field label="Görev" hint="İsteğe bağlı"><TextInput value={role} onChange={(e) => setRole(e.target.value)} placeholder="Usta, montaj, boya" /></Field><Field label="Telefon" hint="İsteğe bağlı"><TextInput value={phone} onChange={(e) => setPhone(e.target.value)} /></Field></div><div className="form-grid"><Field label="Ücret biçimi"><SelectInput value={wageType} onChange={(e) => setWageType(e.target.value as 'monthly' | 'daily' | 'hourly')}><option value="monthly">Aylık</option><option value="daily">Günlük</option><option value="hourly">Saatlik</option></SelectInput></Field><Field label={`${wageTypeLabel[wageType]} ücret`} hint="İşçilik hesabında kullanılır"><TextInput inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0,00" /></Field></div><Field label="İşe başlangıç tarihi"><TextInput type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></Field><Field label="IBAN" hint="İsteğe bağlı, boşluklar otomatik temizlenir"><TextInput value={iban} onChange={(e) => setIban(e.target.value.toLocaleUpperCase('tr-TR'))} placeholder="TR00 0000 0000 0000 0000 0000 00" /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}

function SiteSheet({ open, onClose, onSaved, projects }: { open: boolean; onClose: () => void; onSaved: () => void; projects: Project[] }) {
  const [name, setName] = useState(''); const [projectId, setProjectId] = useState(''); const [address, setAddress] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<Site>('/api/v1/sites', { method: 'POST', body: { name, project_id: projectId || null, address: address || null, note: null } }), onSuccess: () => { onSaved(); onClose(); setName(''); setProjectId(''); setAddress('') } })
  return <SideSheet title="Yeni şantiye" description="Sahayı isterseniz bir projeye bağlayın." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={name.trim().length < 2} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Şantiye adı"><TextInput value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field><Field label="İlgili proje" hint="İsteğe bağlı"><SelectInput value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Projeye bağlı değil</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><Field label="Adres" hint="İsteğe bağlı"><textarea className="input textarea" value={address} onChange={(e) => setAddress(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}

function WorkSheet({ open, onClose, onSaved, employees, sites, projects }: { open: boolean; onClose: () => void; onSaved: () => void; employees: Employee[]; sites: Site[]; projects: Project[] }) {
  const [employeeId, setEmployeeId] = useState(''); const [siteId, setSiteId] = useState(''); const [projectId, setProjectId] = useState(''); const [date, setDate] = useState(todayIso); const [workStatus, setWorkStatus] = useState<WorkStatus>('worked'); const [normalHours, setNormalHours] = useState(''); const [overtimeHours, setOvertimeHours] = useState(''); const [amount, setAmount] = useState(''); const [note, setNote] = useState('')
  const hasNoHours = workStatus === 'unpaid_leave' || workStatus === 'absent'
  const mutation = useMutation({ mutationFn: () => apiRequest<DetailedWorkLog>('/api/v1/work-logs', { method: 'POST', body: { employee_id: employeeId, site_id: siteId || null, project_id: projectId || null, work_date: date, work_status: workStatus, normal_hours: hasNoHours || !normalHours ? null : Number(normalHours.replace(',', '.')), overtime_hours: hasNoHours || !overtimeHours ? 0 : Number(overtimeHours.replace(',', '.')), manual_amount_kurus: amount ? toKurus(amount) : null, note: note || null } }), onSuccess: () => { onSaved(); onClose(); setAmount(''); setNote(''); setNormalHours(''); setOvertimeHours(''); setWorkStatus('worked') } })
  return <SideSheet title="Çalışma kaydı" description="Çalışma, izin ve fazla mesai durumunu günlük olarak kaydedin." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!employeeId || !date} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Personel"><SelectInput value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} autoFocus><option value="">Personel seçin</option>{employees.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><div className="form-grid"><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Gün durumu"><SelectInput value={workStatus} onChange={(e) => setWorkStatus(e.target.value as WorkStatus)}>{Object.entries(workStatusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</SelectInput></Field></div><div className="form-grid"><Field label="Normal saat" hint={hasNoHours ? 'Bu durumda saat girilmez' : 'Boşsa standart gün süresi kullanılır'}><TextInput inputMode="decimal" value={normalHours} onChange={(e) => setNormalHours(e.target.value)} placeholder="Otomatik" disabled={hasNoHours} /></Field><Field label="Fazla mesai saati" hint="Fazla mesai durumunda girin"><TextInput inputMode="decimal" value={overtimeHours} onChange={(e) => setOvertimeHours(e.target.value)} placeholder="0" disabled={hasNoHours} /></Field></div><Field label="Proje" hint="İsteğe bağlı"><SelectInput value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Genel çalışma</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><Field label="Şantiye" hint="İsteğe bağlı"><SelectInput value={siteId} onChange={(e) => setSiteId(e.target.value)}><option value="">Şantiye seçilmedi</option>{sites.filter((item) => !projectId || !item.project_id || item.project_id === projectId).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><Field label="Manuel işçilik tutarı" hint="Boşsa ücret geçmişi ve saatlere göre hesaplanır"><TextInput inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Otomatik hesapla" disabled={hasNoHours} /></Field><Field label="Not" hint="İsteğe bağlı"><textarea className="input textarea" value={note} onChange={(e) => setNote(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}

function PaymentSheet({ open, onClose, onSaved, employees }: { open: boolean; onClose: () => void; onSaved: () => void; employees: Employee[] }) {
  const [employeeId, setEmployeeId] = useState(''); const [date, setDate] = useState(todayIso); const [amount, setAmount] = useState(''); const [type, setType] = useState<'advance' | 'wage'>('wage'); const [note, setNote] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<EmployeePayment>('/api/v1/employee-payments', { method: 'POST', body: { employee_id: employeeId, payment_date: date, amount_kurus: toKurus(amount), payment_type: type, note: note || null } }), onSuccess: () => { onSaved(); onClose(); setAmount(''); setNote('') } })
  return <SideSheet title="Personel ödemesi" description="Maaş ve avans ödemelerini personel geçmişine kaydedin." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!employeeId || !amount || toKurus(amount) <= 0} onClick={() => mutation.mutate()}>Ödemeyi kaydet</Button></>}><div className="form-stack"><Field label="Personel"><SelectInput value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} autoFocus><option value="">Personel seçin</option>{employees.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><div className="form-grid"><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Ödeme türü"><SelectInput value={type} onChange={(e) => setType(e.target.value as 'advance' | 'wage')}><option value="wage">Maaş</option><option value="advance">Avans</option></SelectInput></Field></div><Field label="Tutar"><TextInput inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0,00" /></Field><Field label="Not" hint="İsteğe bağlı"><textarea className="input textarea" value={note} onChange={(e) => setNote(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}

function WageSheet({ open, onClose, onSaved, employee }: { open: boolean; onClose: () => void; onSaved: () => void; employee: Employee | null }) {
  const [wageType, setWageType] = useState<WageType>((employee?.wage_type as WageType | undefined) ?? 'monthly'); const [rate, setRate] = useState(''); const [effectiveFrom, setEffectiveFrom] = useState(todayIso); const [reason, setReason] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<WageRate>(`/api/v1/employees/${employee?.id}/wage-rates`, { method: 'POST', body: { effective_from: effectiveFrom, effective_to: null, wage_type: wageType, rate_kurus: toKurus(rate), reason: reason || null } }), onSuccess: () => { onSaved(); onClose(); setRate(''); setReason('') } })
  return <SideSheet title="Ücret güncelle" description={employee ? `${employee.name} için yeni ücret dönemi açılır. Önceki açık dönem otomatik kapanır.` : 'Önce personel seçin.'} open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!employee || !rate || toKurus(rate) < 0 || !effectiveFrom} onClick={() => mutation.mutate()}>Yeni dönemi kaydet</Button></>}><div className="form-stack"><Field label="Ücret biçimi"><SelectInput value={wageType} onChange={(e) => setWageType(e.target.value as WageType)} autoFocus><option value="monthly">Aylık</option><option value="daily">Günlük</option><option value="hourly">Saatlik</option></SelectInput></Field><Field label={`${wageTypeLabel[wageType]} ücret`}><TextInput inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0,00" /></Field><Field label="Geçerlilik başlangıcı" hint="Bu tarihten sonraki işçilik hesaplarında kullanılır"><TextInput type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} /></Field><Field label="Değişiklik nedeni" hint="İsteğe bağlı"><TextInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Yıllık zam, görev değişikliği" /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}
