import { useState } from 'react'
import { apiRequest } from './lib/api'
import { Button } from './components/ui'

type Manual = { source_id: string; title: string; occurrence_date: string; repeat_rule?: string }
export function CalendarManualActions({ event, onChanged }: { event: Manual; onChanged: () => void }) {
  const [title, setTitle] = useState(event.title)
  const [postponeDate, setPostponeDate] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  async function act(suffix: string, method: string, body: unknown) { setBusy(true); setMessage(''); try { await apiRequest(`/api/v1/calendar/manual-events/${event.source_id}${suffix}`, { method, body }); onChanged(); setMessage('Kaydedildi.') } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) } }
  return <div className="p0-controls"><label>Başlık<input value={title} onChange={(e) => setTitle(e.target.value)} /></label><Button disabled={busy || title.length < 2} onClick={() => act('', 'PATCH', { title })}>Düzenle</Button><Button disabled={busy} onClick={() => act('/complete', 'POST', { occurrence_date: event.occurrence_date })}>Tamamla</Button><label>Yeni tarih<input type="date" value={postponeDate} min={event.occurrence_date} onChange={(e) => setPostponeDate(e.target.value)} /></label><Button disabled={busy || !postponeDate} onClick={() => act('/postpone', 'POST', { occurrence_date: event.occurrence_date, new_date: postponeDate })}>Ertele</Button><Button disabled={busy} onClick={() => act('/cancel', 'POST', { occurrence_date: event.occurrence_date })}>Bu tekrarı iptal et</Button><Button disabled={busy} onClick={() => act('/cancel', 'POST', {})}>Seriyi iptal et</Button>{message && <span role="status">{message}</span>}</div>
}
