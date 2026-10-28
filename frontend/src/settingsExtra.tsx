import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest } from './lib/api'
import { Button, ErrorState, LoadingRows } from './components/ui'

type AttendanceSettings = { attendance_enforcement_start_date: string | null; default_salary_day: number | null; allow_negative_leave_balance: boolean }
type PayrollSettings = { overtime_multiplier_percent: number; standard_day_hours: number }
type Holiday = { id: string; holiday_date: string; name: string; is_half_day: boolean }
type Plan = { id: string; effective_from: string; effective_to: string | null; workday_numbers: number[] }
type Preference = { event_type: string; enabled: boolean; offsets_days: number[] }
const day = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
export function OperationalSettings() {
  const client = useQueryClient()
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [holidayDate, setHolidayDate] = useState(day())
  const [holidayName, setHolidayName] = useState('')
  const [planDate, setPlanDate] = useState(day())
  const [planDays, setPlanDays] = useState([1, 2, 3, 4, 5, 6])
  const [attendanceDraft, setAttendanceDraft] = useState<AttendanceSettings | null>(null)
  const [payrollDraft, setPayrollDraft] = useState<PayrollSettings | null>(null)
  const attendance = useQuery({ queryKey: ['settings-attendance'], queryFn: () => apiRequest<AttendanceSettings>('/api/v1/settings/attendance') })
  const payroll = useQuery({ queryKey: ['settings-payroll'], queryFn: () => apiRequest<PayrollSettings>('/api/v1/settings/payroll') })
  const holidays = useQuery({ queryKey: ['settings-holidays'], queryFn: () => apiRequest<Holiday[]>('/api/v1/holidays') })
  const plans = useQuery({ queryKey: ['settings-plans'], queryFn: () => apiRequest<Plan[]>('/api/v1/weekly-work-plans?company_only=true') })
  const reminders = useQuery({ queryKey: ['settings-reminders'], queryFn: () => apiRequest<{ preferences: Preference[] }>('/api/v1/calendar/reminder-preferences') })
  const [reminderDraft, setReminderDraft] = useState<Preference[] | null>(null)
  const att = attendanceDraft || attendance.data
  const pay = payrollDraft || payroll.data
  const prefs = reminderDraft || reminders.data?.preferences
  async function save(path: string, method: string, body: unknown) { try { setError(''); setSaved(''); await apiRequest(path, { method, body }); await client.invalidateQueries(); setSaved('Kaydedildi.') } catch (e) { setError(e instanceof Error ? e.message : String(e)) } }
  return <><section className="panel p0-section"><h2>Puantaj ve maaş ayarları</h2>{attendance.isLoading || payroll.isLoading ? <LoadingRows /> : attendance.error || payroll.error ? <ErrorState error={attendance.error || payroll.error} onRetry={() => { attendance.refetch(); payroll.refetch() }} /> : att && pay && <><div className="p0-controls"><label>Puantaj zorunluluğu başlangıcı <input type="date" value={att.attendance_enforcement_start_date || ''} onChange={(e) => setAttendanceDraft({ ...att, attendance_enforcement_start_date: e.target.value || null })} /></label><label>Şirket maaş günü <input type="number" min="1" max="31" value={att.default_salary_day || ''} onChange={(e) => setAttendanceDraft({ ...att, default_salary_day: e.target.value ? Number(e.target.value) : null })} /></label><label>Negatif izin bakiyesi <input type="checkbox" checked={att.allow_negative_leave_balance} onChange={(e) => setAttendanceDraft({ ...att, allow_negative_leave_balance: e.target.checked })} /></label><Button variant="primary" onClick={() => save('/api/v1/settings/attendance', 'PUT', att)}>Kaydet</Button></div><div className="p0-controls"><label>Fazla mesai oranı % <input type="number" min="100" max="500" value={pay.overtime_multiplier_percent} onChange={(e) => setPayrollDraft({ ...pay, overtime_multiplier_percent: Number(e.target.value) })} /></label><label>Standart gün saati <input type="number" min="1" max="24" value={pay.standard_day_hours} onChange={(e) => setPayrollDraft({ ...pay, standard_day_hours: Number(e.target.value) })} /></label><Button variant="primary" onClick={() => save('/api/v1/settings/payroll', 'PUT', pay)}>Kaydet</Button></div></>}</section>
    <section className="panel p0-section"><h2>Haftalık çalışma planı</h2>{plans.data?.map((plan) => <p key={plan.id}>{plan.effective_from}–{plan.effective_to || 'devam ediyor'}: {plan.workday_numbers.join(', ')}</p>)}<div className="p0-controls"><label>Başlangıç <input type="date" value={planDate} onChange={(e) => setPlanDate(e.target.value)} /></label>{['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'].map((label, i) => <label key={label}><input type="checkbox" checked={planDays.includes(i + 1)} onChange={(e) => setPlanDays(e.target.checked ? [...planDays, i + 1].sort() : planDays.filter((day) => day !== i + 1))} />{label}</label>)}<Button onClick={() => save('/api/v1/weekly-work-plans', 'POST', { effective_from: planDate, workdays: planDays })}>Planı ekle</Button></div></section>
    <section className="panel p0-section"><h2>Resmî tatiller</h2>{holidays.data?.map((holiday) => <div className="p0-row" key={holiday.id}><span>{holiday.holiday_date}</span><strong>{holiday.name}</strong><span>{holiday.is_half_day ? 'Yarım gün' : 'Tam gün'}</span><Button onClick={() => save(`/api/v1/holidays/${holiday.id}/cancel`, 'POST', {})}>İptal et</Button></div>)}<form className="p0-controls" onSubmit={(e) => { e.preventDefault(); save('/api/v1/holidays', 'POST', { holiday_date: holidayDate, name: holidayName }) }}><input aria-label="Tatil tarihi" type="date" value={holidayDate} onChange={(e) => setHolidayDate(e.target.value)} /><input aria-label="Tatil adı" value={holidayName} onChange={(e) => setHolidayName(e.target.value)} /><Button disabled={holidayName.length < 2}>Tatil ekle</Button></form></section>
    <section className="panel p0-section"><h2>Hatırlatma tercihleri</h2>{prefs?.map((pref, index) => <div className="p0-row" key={pref.event_type}><strong>{pref.event_type}</strong><label>Etkin <input type="checkbox" checked={pref.enabled} onChange={(e) => setReminderDraft(prefs.map((item, i) => i === index ? { ...item, enabled: e.target.checked } : item))} /></label><label>Önceki günler <input aria-label={`${pref.event_type} bildirim günleri`} value={pref.offsets_days.join(',')} onChange={(e) => setReminderDraft(prefs.map((item, i) => i === index ? { ...item, offsets_days: e.target.value.split(',').map(Number).filter(Number.isFinite) } : item))} /></label></div>)}<Button onClick={() => save('/api/v1/calendar/reminder-preferences', 'PUT', { items: prefs })} disabled={!prefs?.length}>Tercihleri kaydet</Button></section>{error && <p role="alert">{error}</p>}{saved && <p role="status">{saved}</p>}
  </>
}
