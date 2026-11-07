import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiRequest } from './lib/api'
import { Button } from './components/ui'

type Spreadsheet = { file_name: string; content_base64: string }
type Preview = { total_rows: number; valid_rows: number; invalid_rows: number; duplicate_rows: number; issues: Array<{ row: number; message: string }> }

const importKinds: Array<[string, string]> = [['suppliers', 'Firmalar'], ['materials', 'Malzemeler'], ['opening-debts', 'Açılış borçları']]
const exportKinds: Array<{ kind: string; label: string; pdf: boolean }> = [
  { kind: 'suppliers', label: 'Firmalar', pdf: false },
  { kind: 'materials', label: 'Malzemeler', pdf: false },
  { kind: 'purchases', label: 'Satın almalar', pdf: true },
  { kind: 'project-costs', label: 'Proje maliyetleri', pdf: true },
]

function describe(result: { status: string; message?: string } | undefined, ok: string) {
  if (result?.status === 'saved') return ok
  if (result?.status === 'cancelled') return 'Kaydetme iptal edildi.'
  return result?.message || 'Dosya kaydedilemedi.'
}

export function DataTools() {
  const client = useQueryClient()
  const [message, setMessage] = useState('')
  const [kind, setKind] = useState('suppliers')
  const [file, setFile] = useState<Spreadsheet | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)

  async function save(path: string, filename: string) {
    setMessage('')
    setMessage(describe(await window.ksDesktop?.api.downloadReport({ path, filename }), 'Dosya kaydedildi.'))
  }

  async function select() {
    const result = await window.ksDesktop?.api.readSpreadsheet()
    if (result?.status === 'selected' && result.file_name && result.content_base64) {
      setFile({ file_name: result.file_name, content_base64: result.content_base64 })
      setPreview(null)
      setMessage(`${result.file_name} seçildi.`)
    } else if (result?.status === 'error') setMessage(result.message || 'Dosya açılamadı.')
  }

  async function run(action: 'preview' | 'commit') {
    if (!file) return
    setBusy(true)
    setMessage('')
    try {
      if (action === 'preview') setPreview(await apiRequest<Preview>(`/api/v1/imports/${kind}/preview`, { method: 'POST', body: file }))
      else {
        const result = await apiRequest<{ created: number; skipped_duplicates: number; backup_id: string }>(`/api/v1/imports/${kind}/commit`, { method: 'POST', body: file })
        setMessage(`${result.created} kayıt eklendi, ${result.skipped_duplicates} mükerrer atlandı. Öncesinde otomatik yedek alındı: ${result.backup_id}`)
        setPreview(null)
        setFile(null)
        await client.invalidateQueries()
      }
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  return <section className="panel panel--wide" aria-label="Veri dışa ve içe aktarma">
    <div className="panel__header"><h2>Excel / PDF dışa aktarma</h2></div>
    <div className="p0-controls">
      {exportKinds.map((item) => <span key={item.kind} className="p0-controls">
        <Button onClick={() => save(`/api/v1/exports/${item.kind}`, item.label)}>{item.label} (Excel)</Button>
        {item.pdf && <Button onClick={() => save(`/api/v1/exports/${item.kind}/pdf`, item.label)}>{item.label} (PDF)</Button>}
      </span>)}
    </div>
    <div className="panel__header"><h2>Excel ile toplu içe aktarma</h2></div>
    <p>Önce şablonu kaydedin, doldurun, ön izlemede hataları görün. Aktarmadan önce otomatik yedek alınır.</p>
    <div className="p0-controls">
      <select aria-label="Aktarım türü" value={kind} onChange={(e) => { setKind(e.target.value); setPreview(null) }}>{importKinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <Button onClick={() => save(`/api/v1/imports/templates/${kind}`, `Şablon ${importKinds.find(([value]) => value === kind)?.[1] ?? ''}`)}>Şablonu kaydet</Button>
      <Button onClick={select}>XLSX seç</Button>
      <Button disabled={!file || busy} onClick={() => run('preview')}>Ön izleme</Button>
      <Button variant="primary" disabled={!preview || preview.invalid_rows > 0 || preview.valid_rows === 0 || busy} onClick={() => run('commit')}>Kayıtları aktar</Button>
    </div>
    {preview && <div><p>{preview.total_rows} satır · {preview.valid_rows} geçerli · {preview.invalid_rows} hatalı · {preview.duplicate_rows} mükerrer</p>{preview.issues.map((issue, index) => <p role="alert" key={index}>Satır {issue.row}: {issue.message}</p>)}</div>}
    {message && <p role="status">{message}</p>}
  </section>
}
