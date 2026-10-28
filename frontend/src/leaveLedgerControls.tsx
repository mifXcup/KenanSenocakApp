import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, makeIdempotencyKey } from './lib/api'
import { Button, ErrorState, LoadingRows } from './components/ui'

const day = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
export function LeaveLedgerControls({ employeeId }: { employeeId: string }) {
  const client = useQueryClient()
  const [days, setDays] = useState('')
  const [date, setDate] = useState(day())
  const [message, setMessage] = useState('')
  const ledger = useQuery({ queryKey: ['leave-ledger-controls', employeeId], queryFn: () => apiRequest<{ balance: { balance_days: string }; entries: Array<{ id: string; entry_date: string; entry_type: string; quantity_hours: string; is_voided: boolean }> }>(`/api/v1/employees/${employeeId}/leave-ledger?leave_type_code=annual`) })
  async function post(path: string, body: unknown) { try { setMessage(''); await apiRequest(path, { method: 'POST', body }); await client.invalidateQueries(); setMessage('Kaydedildi.') } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) } }
  return <div><h3>Yıllık izin hak defteri</h3>{ledger.isLoading ? <LoadingRows /> : ledger.error ? <ErrorState error={ledger.error} onRetry={() => ledger.refetch()} /> : <><p>Bakiye: {ledger.data?.balance.balance_days} gün</p>{ledger.data?.entries.map((item) => <div className="p0-row" key={item.id}><span>{item.entry_date}</span><strong>{item.entry_type}</strong><span>{item.quantity_hours} saat</span>{!item.is_voided && ['grant', 'accrual', 'adjustment'].includes(item.entry_type) && <Button onClick={() => post(`/api/v1/leave-ledger/${item.id}/reverse`, { entry_date: day() })}>Ters kayıt</Button>}</div>)}</>}
    <form className="p0-controls" onSubmit={(e) => { e.preventDefault(); post(`/api/v1/employees/${employeeId}/leave-ledger`, { leave_type_code: 'annual', entry_type: 'grant', quantity_days: days, entry_date: date, idempotency_key: makeIdempotencyKey('leave-grant') }) }}><label>Hak tarihi<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label><label>Gün<input required value={days} onChange={(e) => setDays(e.target.value)} /></label><Button variant="primary" disabled={!days}>Hak ekle</Button></form>{message && <p role="status">{message}</p>}
  </div>
}
