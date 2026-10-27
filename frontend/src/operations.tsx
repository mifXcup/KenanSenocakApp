import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck, Coins, HardHat, Plus, UserPlus, UsersThree } from '@phosphor-icons/react'
import { apiRequest, formatDate, formatMoney, toKurus } from './lib/api'
import type { Employee, EmployeePayment, Project, Site, WorkLog } from './lib/types'
import { Button, EmptyState, ErrorState, Field, LoadingRows, PageHeader, SelectInput, SideSheet, TextInput } from './components/ui'

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

type SheetKind = 'employee' | 'site' | 'work' | 'payment' | null

export function PersonnelPage() {
  const client = useQueryClient()
  const [sheet, setSheet] = useState<SheetKind>(null)
  const employees = useQuery({ queryKey: operationKeys.employees, queryFn: () => apiRequest<Employee[]>('/api/v1/employees') })
  const sites = useQuery({ queryKey: operationKeys.sites, queryFn: () => apiRequest<Site[]>('/api/v1/sites') })
  const workLogs = useQuery({ queryKey: operationKeys.workLogs, queryFn: () => apiRequest<WorkLog[]>('/api/v1/work-logs') })
  const payments = useQuery({ queryKey: operationKeys.employeePayments, queryFn: () => apiRequest<EmployeePayment[]>('/api/v1/employee-payments') })
  const projects = useQuery({ queryKey: operationKeys.projects, queryFn: () => apiRequest<Project[]>('/api/v1/projects') })

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

          <div className="operations-grid">
            <section className="panel">
              <div className="panel__header"><h2>Personel</h2><span className="count-label">{employees.data?.length ?? 0} kayıt</span></div>
              {!employees.data?.length ? <EmptyState title="Henüz personel yok" description="Çalışma ve ödeme kaydı girebilmek için önce personel kartı oluşturun." action={<Button onClick={() => setSheet('employee')}>Personel ekle</Button>} /> : (
                <div className="record-list">{employees.data.map((employee) => {
                  const labor = (workLogs.data ?? []).filter((item) => item.employee_id === employee.id && item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0)
                  const paid = (payments.data ?? []).filter((item) => item.employee_id === employee.id && item.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0)
                  return <article className="record-row" key={employee.id}><div className="record-avatar" aria-hidden="true">{employee.name.slice(0, 1).toLocaleUpperCase('tr-TR')}</div><div><strong>{employee.name}</strong><span>{employee.role || 'Görev belirtilmedi'}{employee.current_rate_kurus != null ? ` · ${wageTypeLabel[employee.wage_type ?? 'daily']} ${formatMoney(employee.current_rate_kurus)}` : ''}</span></div><div className="record-row__money"><strong>{formatMoney(labor - paid)}</strong><span>işçilik eksi ödeme</span></div></article>
                })}</div>
              )}
            </section>

            <section className="panel">
              <div className="panel__header"><h2>Son hareketler</h2><span className="count-label">Çalışma ve ödeme</span></div>
              {!workLogs.data?.length && !payments.data?.length ? <p className="muted">Henüz personel hareketi yok.</p> : (
                <div className="timeline-list">
                  {[...(workLogs.data ?? []).map((item) => ({ id: item.id, date: item.work_date, title: employeeById[item.employee_id] ?? 'Personel', detail: `${item.hours} saat${item.site_id ? ` · ${siteById[item.site_id] ?? 'Şantiye'}` : ''}`, amount: item.amount_kurus, type: 'Çalışma' })), ...(payments.data ?? []).filter((item) => item.status === 'active').map((item) => ({ id: item.id, date: item.payment_date, title: employeeById[item.employee_id] ?? 'Personel', detail: item.payment_type === 'advance' ? 'Avans ödemesi' : 'Maaş ödemesi', amount: item.amount_kurus, type: 'Ödeme' }))]
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
    </div>
  )
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
  const [employeeId, setEmployeeId] = useState(''); const [siteId, setSiteId] = useState(''); const [projectId, setProjectId] = useState(''); const [date, setDate] = useState(todayIso); const [hours, setHours] = useState('8'); const [amount, setAmount] = useState(''); const [note, setNote] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<WorkLog>('/api/v1/work-logs', { method: 'POST', body: { employee_id: employeeId, site_id: siteId || null, project_id: projectId || null, work_date: date, hours: Number(hours.replace(',', '.')), amount_kurus: amount ? toKurus(amount) : null, note: note || null } }), onSuccess: () => { onSaved(); onClose(); setAmount(''); setNote('') } })
  return <SideSheet title="Çalışma kaydı" description="Süreyi ve işçilik maliyetini projeye veya şantiyeye bağlayın." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!employeeId || !date || Number(hours.replace(',', '.')) <= 0} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Personel"><SelectInput value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} autoFocus><option value="">Personel seçin</option>{employees.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><div className="form-grid"><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Saat"><TextInput inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} /></Field></div><Field label="Proje" hint="İsteğe bağlı"><SelectInput value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Genel çalışma</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><Field label="Şantiye" hint="İsteğe bağlı"><SelectInput value={siteId} onChange={(e) => setSiteId(e.target.value)}><option value="">Şantiye seçilmedi</option>{sites.filter((item) => !projectId || !item.project_id || item.project_id === projectId).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><Field label="İşçilik tutarı" hint="Boşsa günlük ücrete ve saate göre hesaplanır"><TextInput inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Otomatik hesapla" /></Field><Field label="Not" hint="İsteğe bağlı"><textarea className="input textarea" value={note} onChange={(e) => setNote(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}

function PaymentSheet({ open, onClose, onSaved, employees }: { open: boolean; onClose: () => void; onSaved: () => void; employees: Employee[] }) {
  const [employeeId, setEmployeeId] = useState(''); const [date, setDate] = useState(todayIso); const [amount, setAmount] = useState(''); const [type, setType] = useState<'advance' | 'wage'>('wage'); const [note, setNote] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<EmployeePayment>('/api/v1/employee-payments', { method: 'POST', body: { employee_id: employeeId, payment_date: date, amount_kurus: toKurus(amount), payment_type: type, note: note || null } }), onSuccess: () => { onSaved(); onClose(); setAmount(''); setNote('') } })
  return <SideSheet title="Personel ödemesi" description="Maaş ve avans ödemelerini personel geçmişine kaydedin." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!employeeId || !amount || toKurus(amount) <= 0} onClick={() => mutation.mutate()}>Ödemeyi kaydet</Button></>}><div className="form-stack"><Field label="Personel"><SelectInput value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} autoFocus><option value="">Personel seçin</option>{employees.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field><div className="form-grid"><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Ödeme türü"><SelectInput value={type} onChange={(e) => setType(e.target.value as 'advance' | 'wage')}><option value="wage">Maaş</option><option value="advance">Avans</option></SelectInput></Field></div><Field label="Tutar"><TextInput inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0,00" /></Field><Field label="Not" hint="İsteğe bağlı"><textarea className="input textarea" value={note} onChange={(e) => setNote(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
}
