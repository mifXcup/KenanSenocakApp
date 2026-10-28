import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiRequest, formatMoney } from './lib/api'
import { Button } from './components/ui'

type Spreadsheet = { file_name: string; content_base64: string }
type Preview = { total_rows: number; valid_rows: number; invalid_rows: number; duplicate_rows: number; total_labor_kurus: number; issues: Array<{ row: number; message: string }>; duplicates: Array<{ row: number; message: string }>; sample: Array<Record<string, unknown>> }
export function AttendanceImport() {
  const client = useQueryClient()
  const [file, setFile] = useState<Spreadsheet | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  async function template() { const result = await window.ksDesktop?.api.downloadReport({ path: '/api/v1/work-logs/import-template', filename: 'Puantaj şablonu' }); setMessage(result?.status === 'saved' ? 'Şablon kaydedildi.' : result?.status === 'cancelled' ? 'Kaydetme iptal edildi.' : result?.message || 'Şablon kaydedilemedi.') }
  async function select() { const result = await window.ksDesktop?.api.readSpreadsheet(); if (result?.status === 'selected' && result.file_name && result.content_base64) { setFile({ file_name: result.file_name, content_base64: result.content_base64 }); setPreview(null); setMessage(`${result.file_name} seçildi.`) } else if (result?.status === 'error') setMessage(result.message || 'Dosya açılamadı.') }
  async function run(path: string) { if (!file) return; setBusy(true); setMessage(''); try { if (path.endsWith('preview')) setPreview(await apiRequest<Preview>(path, { method: 'POST', body: file })); else { const result = await apiRequest<{ created: number; backup_id: string }>(path, { method: 'POST', body: file }); setMessage(`${result.created} kayıt eklendi. Yedek: ${result.backup_id}`); setPreview(null); setFile(null); await client.invalidateQueries() } } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) } }
  return <section className="panel p0-section"><h2>Excel toplu puantaj</h2><p>Ön izleme hatalı veya mükerrer satırları gösterir. Commit öncesi otomatik yedek alınır.</p><div className="p0-controls"><Button onClick={template}>Şablonu kaydet</Button><Button onClick={select}>XLSX seç</Button><Button disabled={!file || busy} onClick={() => run('/api/v1/work-logs/bulk-preview')}>Ön izleme</Button><Button variant="primary" disabled={!preview || preview.invalid_rows > 0 || busy} onClick={() => run('/api/v1/work-logs/bulk-commit')}>Kayıtları aktar</Button></div>{preview && <div><p>{preview.total_rows} satır · {preview.valid_rows} geçerli · {preview.invalid_rows} hatalı · {preview.duplicate_rows} mükerrer · {formatMoney(preview.total_labor_kurus)} işçilik</p>{[...preview.issues, ...preview.duplicates].map((issue, index) => <p role="alert" key={index}>Satır {issue.row}: {issue.message}</p>)}<div className="table-wrap" role="region" tabIndex={0} aria-label="Puantaj ön izleme"><table><thead><tr>{Object.keys(preview.sample[0] || {}).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{preview.sample.map((row, index) => <tr key={index}>{Object.values(row).map((value, i) => <td key={i}>{String(value ?? '')}</td>)}</tr>)}</tbody></table></div></div>}{message && <p role="status">{message}</p>}</section>
}
