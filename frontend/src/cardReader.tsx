import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiList, apiRequest } from './lib/api'
import { Button, ErrorState, LoadingRows } from './components/ui'
import type { Employee } from './lib/types'

type Settings = {
  enabled: boolean; web_app_url: string; has_secret: boolean; poll_minutes: number; duplicate_seconds: number; break_minutes: number
  cursor: string; last_sync_at: string | null; last_error: string | null; external_service: string; notice: string
}
type SyncResult = { received: number; created: number; duplicates: number; skipped_existing: number; unknown_card: number; invalid: Array<{ message: string }> }
type Card = { id: string; employee_id: string; employee_name: string | null; card_uid: string }
type ReviewDay = {
  employee_id: string; employee_name: string | null; work_date: string; event_ids: string[]; event_count: number; first_at: string; last_at: string
  needs_manual: boolean; proposed_normal_hours: number | null; proposed_overtime_hours: number | null; existing_work_log: boolean
}
type Review = { days: ReviewDay[]; unknown_pending: number }
type CardEvent = { id: string; card_uid: string; event_at: string; device_id: string | null; state: string }

const message = (error: unknown) => (error instanceof Error ? error.message : String(error))
const clock = (iso: string) => iso.slice(11, 16)

export function CardReaderSettings() {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['card-reader-settings'], queryFn: () => apiRequest<Settings>('/api/v1/card-reader/settings') })
  const [url, setUrl] = useState<string | null>(null)
  const [secret, setSecret] = useState('')
  const [poll, setPoll] = useState<string | null>(null)
  const [dup, setDup] = useState<string | null>(null)
  const [brk, setBrk] = useState<string | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const refresh = () => { client.invalidateQueries({ queryKey: ['card-reader-settings'] }); client.invalidateQueries({ queryKey: ['card-review'] }) }
  const save = useMutation({
    mutationFn: (extra: Record<string, unknown>) => apiRequest<Settings>('/api/v1/card-reader/settings', { method: 'PUT', body: {
      ...(url !== null ? { web_app_url: url } : {}), ...(secret ? { secret } : {}),
      ...(poll !== null ? { poll_minutes: Number(poll) } : {}), ...(dup !== null ? { duplicate_seconds: Number(dup) } : {}), ...(brk !== null ? { break_minutes: Number(brk) } : {}), ...extra } }),
    onSuccess: () => { setSecret(''); setUrl(null); setPoll(null); setDup(null); setBrk(null); setError(''); setStatus('Ayarlar kaydedildi.'); refresh() },
    onError: (e) => { setStatus(''); setError(message(e)) },
  })
  const sync = useMutation({
    mutationFn: () => apiRequest<SyncResult>('/api/v1/card-reader/sync', { method: 'POST', body: {} }),
    onSuccess: (r) => { setError(''); setStatus(`${r.created} yeni hareket alındı, ${r.duplicates} tekrar okuma, ${r.unknown_card} tanınmayan kart.`); refresh() },
    onError: (e) => { setStatus(''); setError(message(e)); refresh() },
  })
  const s = settings.data
  return <section className="panel panel--wide" aria-label="Kart okuyucu ayarları">
    <div className="panel__header"><h2>Kart okuyucu (Google Sheets)</h2></div>
    {settings.isLoading ? <LoadingRows count={2} /> : settings.error ? <ErrorState error={settings.error} onRetry={() => settings.refetch()} /> : s && <>
      <p>{s.notice}</p>
      <p><strong>{s.enabled ? 'Açık' : 'Kapalı'}</strong>{s.last_sync_at ? ` · Son eşitleme: ${new Date(s.last_sync_at).toLocaleString('tr-TR')}` : ''}{s.last_error ? ` · Son hata: ${s.last_error}` : ''}</p>
      <div className="p0-controls">
        <label>Apps Script adresi <input style={{ minWidth: 320 }} placeholder="https://script.google.com/macros/s/.../exec" value={url ?? s.web_app_url} onChange={(e) => setUrl(e.target.value)} /></label>
        <label>Gizli anahtar <input type="password" autoComplete="off" placeholder={s.has_secret ? 'Kayıtlı (değiştirmek için yazın)' : 'Apps Script ile aynı anahtar'} value={secret} onChange={(e) => setSecret(e.target.value)} /></label>
      </div>
      <div className="p0-controls">
        <label>Kontrol sıklığı (dk) <input type="number" min={5} max={1440} value={poll ?? s.poll_minutes} onChange={(e) => setPoll(e.target.value)} /></label>
        <label>Tekrar okuma penceresi (sn) <input type="number" min={10} max={600} value={dup ?? s.duplicate_seconds} onChange={(e) => setDup(e.target.value)} /></label>
        <label>Öğle molası (dk) <input type="number" min={0} max={240} value={brk ?? s.break_minutes} onChange={(e) => setBrk(e.target.value)} /></label>
        <Button loading={save.isPending} onClick={() => save.mutate({})}>Kaydet</Button>
      </div>
      <div className="p0-controls">
        {s.enabled
          ? <Button onClick={() => save.mutate({ enabled: false })}>Eşitlemeyi kapat</Button>
          : <Button variant="primary" onClick={() => { if (window.confirm('Etkinleştirince uygulama Google Apps Script adresine bağlanıp yeni kart satırlarını okuyacak. Devam edilsin mi?')) save.mutate({ enabled: true }) }}>Eşitlemeyi aç</Button>}
        <Button loading={sync.isPending} disabled={!s.enabled} onClick={() => sync.mutate()}>Şimdi eşitle</Button>
      </div>
    </>}
    {status && <p role="status">{status}</p>}
    {error && <p role="alert">{error}</p>}
  </section>
}

export function CardReview() {
  const client = useQueryClient()
  const employees = useQuery({ queryKey: ['card-employees'], queryFn: () => apiList<Employee>('/api/v1/employees') })
  const cards = useQuery({ queryKey: ['card-reader-cards'], queryFn: () => apiRequest<Card[]>('/api/v1/card-reader/cards') })
  const review = useQuery({ queryKey: ['card-review'], queryFn: () => apiRequest<Review>('/api/v1/card-reader/review'), refetchInterval: 120000 })
  const unknown = useQuery({ queryKey: ['card-unknown'], queryFn: () => apiRequest<CardEvent[]>('/api/v1/card-reader/events?unknown_only=true&state=pending') })
  const [employeeId, setEmployeeId] = useState('')
  const [uid, setUid] = useState('')
  const [edits, setEdits] = useState<Record<string, { normal: string; overtime: string }>>({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const refresh = () => { for (const key of ['card-reader-cards', 'card-review', 'card-unknown', 'attendance-logs', 'attendance-check']) client.invalidateQueries({ queryKey: [key] }) }
  const assign = useMutation({
    mutationFn: (body: { employee_id: string; card_uid: string; reassign?: boolean }) => apiRequest('/api/v1/card-reader/cards', { method: 'PUT', body }),
    onSuccess: () => { setUid(''); setError(''); setNotice('Kart atandı.'); refresh() },
    onError: (e, variables) => {
      if (e instanceof ApiError && e.code === 'card_in_use' && !variables.reassign && window.confirm('Bu kart başka bir personele atanmış. Yeni personele taşınsın mı?')) { assign.mutate({ ...variables, reassign: true }); return }
      setNotice(''); setError(message(e))
    },
  })
  const archive = useMutation({ mutationFn: (id: string) => apiRequest(`/api/v1/card-reader/cards/${id}/archive`, { method: 'POST', body: {} }), onSuccess: refresh, onError: (e) => setError(message(e)) })
  const ignore = useMutation({ mutationFn: (ids: string[]) => Promise.all(ids.map((id) => apiRequest(`/api/v1/card-reader/events/${id}/ignore`, { method: 'POST', body: {} }))), onSuccess: refresh, onError: (e) => setError(message(e)) })
  const approve = useMutation({
    mutationFn: (day: ReviewDay) => {
      const edit = edits[day.employee_id + day.work_date]
      const normal = edit?.normal ?? String(day.proposed_normal_hours ?? '')
      const overtime = edit?.overtime ?? String(day.proposed_overtime_hours ?? 0)
      return apiRequest<{ results: Array<{ ok: boolean; message?: string }> }>('/api/v1/card-reader/review/approve', { method: 'POST', body: { items: [{ employee_id: day.employee_id, work_date: day.work_date, normal_hours: normal.replace(',', '.'), overtime_hours: (overtime || '0').replace(',', '.') }] } })
    },
    onSuccess: (r) => { const failed = r.results.find((x) => !x.ok); setError(failed?.message ?? ''); setNotice(failed ? '' : 'Puantaj kaydı oluşturuldu.'); refresh() },
    onError: (e) => { setNotice(''); setError(message(e)) },
  })
  const employeeName = (id: string) => employees.data?.find((e) => e.id === id)?.name ?? ''
  const days = review.data?.days ?? []

  return <section className="panel p0-section" aria-label="Kart hareketleri">
    <h2>Kart hareketleri <small>{days.length} gün onay bekliyor</small></h2>
    <p>Kart okuyucudan gelen giriş-çıkışlar otomatik puantaj olmaz. Önerilen süreyi kontrol edip onaylayın; mevcut puantaj kuralları (kilitli dönem, çift kayıt) aynen geçerlidir.</p>
    {review.isLoading ? <LoadingRows count={2} /> : review.error ? <ErrorState error={review.error} onRetry={() => review.refetch()} /> : !days.length ? <p>Onay bekleyen kart hareketi yok.</p> : days.map((day) => {
      const key = day.employee_id + day.work_date
      const edit = edits[key]
      const normal = edit?.normal ?? (day.proposed_normal_hours != null ? String(day.proposed_normal_hours) : '')
      const overtime = edit?.overtime ?? String(day.proposed_overtime_hours ?? 0)
      return <div className="p0-row" key={key}>
        <strong>{day.employee_name ?? employeeName(day.employee_id)}</strong><span>{day.work_date}</span>
        <span>{clock(day.first_at)} → {day.event_count > 1 ? clock(day.last_at) : 'çıkış yok'}</span>
        <label>Normal saat <input aria-label="Normal saat" style={{ width: 70 }} inputMode="decimal" value={normal} onChange={(e) => setEdits({ ...edits, [key]: { normal: e.target.value, overtime } })} /></label>
        <label>Fazla mesai <input aria-label="Fazla mesai saati" style={{ width: 70 }} inputMode="decimal" value={overtime} onChange={(e) => setEdits({ ...edits, [key]: { normal, overtime: e.target.value } })} /></label>
        {day.needs_manual && <span role="note">Tek okuma: süreyi siz girin</span>}
        {day.existing_work_log && <span role="alert">Bu gün için puantaj kaydı var</span>}
        <Button variant="primary" disabled={day.existing_work_log || !normal || Number(normal.replace(',', '.')) <= 0 || approve.isPending} onClick={() => approve.mutate(day)}>Onayla</Button>
        <Button onClick={() => { if (window.confirm('Bu günün kart hareketleri yok sayılsın mı?')) ignore.mutate(day.event_ids) }}>Yok say</Button>
      </div>
    })}
    <h3>Tanınmayan kartlar</h3>
    {!unknown.data?.length ? <p>Tanınmayan kart yok.</p> : unknown.data.map((item) => <div className="p0-row" key={item.id}>
      <code>{item.card_uid}</code><span>{item.event_at.replace('T', ' ').slice(0, 16)}</span>
      <select aria-label="Personel seç" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}><option value="">Personel seç</option>{employees.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
      <Button disabled={!employeeId} onClick={() => assign.mutate({ employee_id: employeeId, card_uid: item.card_uid })}>Bu kartı ata</Button>
      <Button onClick={() => ignore.mutate([item.id])}>Yok say</Button>
    </div>)}
    <h3>Kartlar</h3>
    {cards.data?.map((card) => <div className="p0-row" key={card.id}><strong>{card.employee_name}</strong><code>{card.card_uid}</code><Button onClick={() => { if (window.confirm('Kart personelden ayrılsın mı?')) archive.mutate(card.id) }}>Kaldır</Button></div>)}
    <form className="p0-controls" onSubmit={(e) => { e.preventDefault(); assign.mutate({ employee_id: employeeId, card_uid: uid }) }}>
      <select aria-label="Kart sahibi" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}><option value="">Personel seç</option>{employees.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
      <input aria-label="Kart numarası" placeholder="Kart numarası (örn. 04A1B2C3)" value={uid} onChange={(e) => setUid(e.target.value)} />
      <Button variant="primary" loading={assign.isPending} disabled={!employeeId || !uid.trim()}>Kart ata</Button>
    </form>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
  </section>
}
