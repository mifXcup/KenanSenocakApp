import { ProjectExpenses } from './projectExpenses'
import { useEffect, useState, type ChangeEvent, type CSSProperties, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowSquareOut, CalendarBlank, Check, Circle, Clock, Drop, MapPin, NotePencil,
  Plus, Target,
} from '@phosphor-icons/react'
import { ApiError, apiList, apiRequest, formatCurrency, formatDate, formatMoney } from './lib/api'
import type { Project, ProjectContract, ProjectHub, ProjectTask } from './lib/types'
import { Button, EmptyState, ErrorState, Field, LoadingRows, PageHeader, SelectInput, SideSheet, TextInput } from './components/ui'
import { ProductPricingPanel } from './productPricing'
import { convertMinorAtRate, formatPriceInput, minorFromPriceInput, priceInputFromMinor } from './lib/moneyInput'

const stages: Array<[Project['stage'], string]> = [
  ['planning', 'Planlama'], ['design', 'Tasarım'], ['approval', 'Onay'], ['production', 'Üretim'],
  ['delivery', 'Sevkiyat'], ['installation', 'Montaj'], ['completed', 'Tamamlandı'],
]
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
type AddKind = 'note' | 'task' | 'color' | 'visit' | 'edit' | 'project' | 'historical' | null

const stageLabel = (stage: string) => stages.find(([value]) => value === stage)?.[1] ?? stage

export function ProjectCenterPage() {
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => apiList<Project>('/api/v1/projects') })
  const requestedId = params.get('project')
  const [selectedId, setSelectedId] = useState(() => requestedId || localStorage.getItem('ks-active-project') || '')
  // Mini bardan gelen ?project= değeri sayfa zaten açıkken de seçimi değiştirir.
  const [seenRequestedId, setSeenRequestedId] = useState(requestedId)
  if (requestedId !== seenRequestedId) { setSeenRequestedId(requestedId); if (requestedId) setSelectedId(requestedId) }
  const [sheet, setSheet] = useState<AddKind>(null)
  const activeSelectedId = projects.data?.some((project) => project.id === selectedId)
    ? selectedId
    : requestedId && projects.data?.some((project) => project.id === requestedId)
      ? requestedId
      : projects.data?.[0]?.id ?? ''

  useEffect(() => {
    if (activeSelectedId) localStorage.setItem('ks-active-project', activeSelectedId)
  }, [activeSelectedId])

  const selectProject = (id: string) => {
    setSelectedId(id)
    localStorage.setItem('ks-active-project', id)
    setParams(id ? { project: id } : {})
  }
  const hub = useQuery({ queryKey: ['project-hub', activeSelectedId], queryFn: () => apiRequest<ProjectHub>(`/api/v1/projects/${activeSelectedId}/hub`), enabled: Boolean(activeSelectedId) })
  const contract = useQuery({ queryKey: ['project-contract', activeSelectedId], queryFn: async () => {
    try { return await apiRequest<ProjectContract>(`/api/v1/projects/${activeSelectedId}/contract`) }
    catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error }
  }, enabled: Boolean(activeSelectedId) })
  const [contractMessage, setContractMessage] = useState('')
  const saveContract = async () => {
    if (!contract.data) return
    const result = await window.ksDesktop?.api.saveProjectContract(activeSelectedId, contract.data.file_name)
    setContractMessage(result?.status === 'saved' ? 'Sözleşme dosyası kaydedildi.' : result?.status === 'cancelled' ? '' : result?.message || 'Sözleşme kaydedilemedi.')
  }
  const refresh = (createdId?: string) => { client.invalidateQueries({ queryKey: ['project-hub'] }); client.invalidateQueries({ queryKey: ['project-contract'] }); client.invalidateQueries({ queryKey: ['projects'] }); if (createdId) selectProject(createdId); setSheet(null) }

  if (projects.isLoading) return <div className="page"><LoadingRows count={5} /></div>
  if (projects.error) return <div className="page"><ErrorState error={projects.error} onRetry={() => projects.refetch()} /></div>
  if (!projects.data?.length) return <div className="page"><PageHeader title="Proje Takip" description="Bütün saha kararları ve notları tek yerde." /><EmptyState title="İlk projenizi oluşturun" description="Devam eden veya tamamlanmış bir projeyi ekleyin; geçmiş ürün fiyatlarını proje altında kaydedin." action={<div className="project-actions"><Button variant="primary" onClick={() => setSheet('project')}><Plus size={18} />Yeni proje</Button><Button onClick={() => setSheet('historical')}>Geçmiş proje ekle</Button></div>} />{(sheet === 'project' || sheet === 'historical') && <ProjectSheet kind={sheet} projectId="" onClose={() => setSheet(null)} onSaved={refresh} />}</div>

  const data = hub.data
  const openTasks = data?.tasks.filter((task) => task.task_state !== 'done') ?? []
  const nextVisit = data?.visits.find((visit) => visit.visit_state === 'planned' && visit.visit_date >= today)

  return (
    <div className="page project-center">
      <PageHeader title="Proje Takip" description="Bugünkü durumu, saha bilgisini ve sıradaki kararı aynı yerde tutun." action={<div className="project-actions"><Button onClick={() => window.ksDesktop?.app.toggleProjectBar()}><ArrowSquareOut size={18} />Masaüstü barı</Button><Button onClick={() => setSheet('historical')}>Geçmiş proje ekle</Button><Button variant="primary" onClick={() => setSheet('project')}><Plus size={18} />Yeni proje</Button></div>} />
      <div className="project-center__layout">
        <aside className="project-rail">
          <span className="project-rail__label">PROJELER</span>
          {projects.data.map((project) => <button key={project.id} className={`project-card ${project.id === activeSelectedId ? 'project-card--active' : ''}`} onClick={() => selectProject(project.id)}>
            <span className="project-card__color" style={{ background: project.accent_color }} />
            <span><strong>{project.name}</strong><small>{project.customer_name}{project.project_state === 'completed' ? ' · Tamamlandı' : ''}</small></span>
            <em>{project.progress_percent}%</em>
          </button>)}
        </aside>
        <section className="project-canvas">
          {hub.isLoading ? <LoadingRows count={6} /> : hub.error ? <ErrorState error={hub.error} onRetry={() => hub.refetch()} /> : data && <>
            <header className="project-hero" style={{ '--project-accent': data.project.accent_color } as CSSProperties}>
              <div className="project-hero__title"><span className="project-dot" /><div><span className="eyebrow-dark">{stageLabel(data.project.stage)}</span><h2>{data.project.name}</h2><p>{data.project.customer_name}{data.project.address ? ` · ${data.project.address}` : ''}</p>{data.project.note && <p>{data.project.note}</p>}</div></div>
              <Button onClick={() => setSheet('edit')}>Projeyi düzenle</Button>
              <div className="project-progress"><span><b>İlerleme</b><em>{data.project.progress_percent}%</em></span><div><i style={{ width: `${data.project.progress_percent}%` }} /></div></div>
              <div className="project-next"><Target size={20} /><span><small>SIRADAKİ ADIM</small><strong>{data.project.next_step || 'Sıradaki adım henüz yazılmadı'}</strong></span></div>
              <div className="project-contract-summary"><span><small>ANLAŞILAN PROJE FİYATI</small><strong>{formatCurrency(data.project.contract_currency === 'TRY' ? data.project.contract_amount_kurus : data.project.contract_foreign_amount_minor, data.project.contract_currency)}</strong>{data.project.contract_currency !== 'TRY' && <small>TL karşılığı: {formatMoney(data.project.contract_amount_kurus)}</small>}</span><span><small>SÖZLEŞME</small><strong>{contract.data?.file_name || 'Henüz yüklenmedi'}</strong></span>{contract.data && <Button onClick={saveContract}>Dosyayı kaydet</Button>}{contractMessage && <span role="status">{contractMessage}</span>}</div>
            </header>
            <div className="project-pulse">
              <div><Clock size={19} /><span><small>Açık iş</small><strong>{openTasks.length}</strong></span></div>
              <div><CalendarBlank size={19} /><span><small>Sonraki ziyaret</small><strong>{nextVisit ? formatDate(nextVisit.visit_date) : 'Planlanmadı'}</strong></span></div>
              <div><Drop size={19} /><span><small>Renk / malzeme</small><strong>{data.colors.length}</strong></span></div>
            </div>
            <div className="project-grid">
              <HubSection title="Yapılacaklar ve beklenenler" count={data.tasks.length} action={() => setSheet('task')} icon={<Check size={18} />}>
                {data.tasks.length ? <div className="compact-list">{data.tasks.slice(0, 6).map((task) => <TaskRow key={task.id} task={task} onChanged={() => hub.refetch()} />)}</div> : <MiniEmpty text="Henüz yapılacak eklenmedi." />}
              </HubSection>
              <HubSection title="Hızlı notlar" count={data.notes.length} action={() => setSheet('note')} icon={<NotePencil size={18} />}>
                {data.notes.length ? <div className="note-stack">{data.notes.slice(0, 4).map((note) => <article key={note.id}><p>{note.content}</p><time>{new Date(note.created_at).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'short' })}</time></article>)}</div> : <MiniEmpty text="Projeye ilk notu ekleyin." />}
              </HubSection>
              <HubSection title="Renk ve malzemeler" count={data.colors.length} action={() => setSheet('color')} icon={<Drop size={18} />}>
                {data.colors.length ? <div className="swatch-list">{data.colors.slice(0, 5).map((item) => <div key={item.id}><span className="swatch" style={{ background: item.color_code.startsWith('#') ? item.color_code : '#ded8d1' }} /><span><strong>{item.label}</strong><small>{item.material || 'Malzeme belirtilmedi'}</small></span><b>{item.color_code}</b></div>)}</div> : <MiniEmpty text="Renk veya malzeme kodu yok." />}
              </HubSection>
              <HubSection title="Şantiye ziyaretleri" count={data.visits.length} action={() => setSheet('visit')} icon={<MapPin size={18} />} wide>
                {data.visits.length ? <div className="visit-list">{data.visits.slice(0, 5).map((visit) => <div key={visit.id}><span className={`visit-date ${visit.visit_state === 'completed' ? 'visit-date--done' : ''}`}><b>{new Date(`${visit.visit_date}T12:00:00`).toLocaleDateString('tr-TR', { day: '2-digit' })}</b><small>{new Date(`${visit.visit_date}T12:00:00`).toLocaleDateString('tr-TR', { month: 'short' })}</small></span><span><strong>{visit.purpose}</strong><small>{visit.note || (visit.visit_state === 'planned' ? 'Planlandı' : 'Tamamlandı')}</small></span></div>)}</div> : <MiniEmpty text="Planlanmış ziyaret bulunmuyor." />}
              </HubSection>
            </div>
            <ProductPricingPanel projectId={activeSelectedId} projectCompleted={data.project.stage === 'completed' || data.project.project_state === 'completed'} contractAmountKurus={data.project.contract_amount_kurus} />
          </>}
          {data && <ProjectExpenses projectId={data.project.id} />}
        </section>
      </div>
      {sheet && <ProjectSheet kind={sheet} projectId={activeSelectedId} project={data?.project} contract={contract.data} onClose={() => setSheet(null)} onSaved={refresh} />}
    </div>
  )
}

function HubSection({ title, count, action, icon, children, wide = false }: { title: string; count: number; action: () => void; icon: ReactNode; children: ReactNode; wide?: boolean }) {
  return <section className={`hub-section ${wide ? 'hub-section--wide' : ''}`}><header><span>{icon}<strong>{title}</strong><em>{count}</em></span><button onClick={action} aria-label={`${title} ekle`}><Plus size={17} /></button></header>{children}</section>
}

function MiniEmpty({ text }: { text: string }) { return <div className="mini-empty"><Circle size={13} />{text}</div> }

function TaskRow({ task, onChanged }: { task: ProjectTask; onChanged: () => void }) {
  const mutation = useMutation({ mutationFn: () => apiRequest(`/api/v1/project-tasks/${task.id}`, { method: 'PATCH', body: { task_state: task.task_state === 'done' ? 'todo' : 'done' } }), onSuccess: onChanged })
  return <button className={`task-row ${task.task_state === 'done' ? 'task-row--done' : ''}`} onClick={() => mutation.mutate()}><span className="task-check">{task.task_state === 'done' && <Check size={13} />}</span><span><strong>{task.title}</strong><small>{task.task_state === 'waiting' ? `${task.waiting_on || 'Dışarıdan'} dönüş bekleniyor` : task.due_date ? formatDate(task.due_date) : 'Tarih yok'}</small></span></button>
}

async function readContractFile(file: File): Promise<{ file_name: string; content_base64: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Sözleşme dosyası okunamadı.'))
    reader.readAsDataURL(file)
  })
  return { file_name: file.name, content_base64: dataUrl.split(',', 2)[1] ?? '' }
}

function ProjectSheet({ kind, projectId, project, contract, onClose, onSaved }: { kind: Exclude<AddKind, null>; projectId: string; project?: Project; contract?: ProjectContract | null; onClose: () => void; onSaved: (createdId?: string) => void }) {
  const [a, setA] = useState(project?.name ?? '')
  const [b, setB] = useState(project?.customer_name ?? '')
  const [c, setC] = useState(kind === 'edit' ? project?.address ?? '' : '')
  const [d, setD] = useState(kind === 'edit' ? project?.next_step ?? '' : '')
  const [projectNote, setProjectNote] = useState(kind === 'edit' ? project?.note ?? '' : '')
  const [projectPrice, setProjectPrice] = useState(() => {
    const minor = project?.contract_currency && project.contract_currency !== 'TRY' ? project.contract_foreign_amount_minor : project?.contract_amount_kurus
    return priceInputFromMinor(minor, project?.contract_currency ?? 'TRY')
  })
  const [currency, setCurrency] = useState<Project['contract_currency']>(project?.contract_currency ?? 'TRY')
  const [fxRate, setFxRate] = useState(project?.contract_fx_rate == null ? '' : String(project.contract_fx_rate))
  const [date, setDate] = useState(today)
  const [stage, setStage] = useState<Project['stage']>(project?.stage ?? 'planning')
  const [progress, setProgress] = useState(String(project?.progress_percent ?? 0))
  const [color, setColor] = useState(project?.accent_color ?? '#9A5A3A')
  const [waiting, setWaiting] = useState(false)
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const priceValue = kind === 'project' ? c : projectPrice
  const priceMinor = minorFromPriceInput(priceValue)
  const priceError = priceValue.trim() && priceMinor <= 0 ? 'Geçerli bir proje fiyatı girin.' : ''
  const numericFxRate = /^\d+(?:[.,]\d{1,6})?$/.test(fxRate.trim()) ? Number(fxRate.replace(',', '.')) : 0
  const fxRateError = currency !== 'TRY' && priceValue.trim() && numericFxRate <= 0 ? 'Dövizli fiyat için 1 birimin TL kurunu girin.' : ''
  const priceFields = currency === 'TRY'
    ? { contract_currency: currency, contract_amount_kurus: priceValue ? priceMinor : null, contract_foreign_amount_minor: null, contract_fx_rate: null }
    : { contract_currency: currency, contract_amount_kurus: null, contract_foreign_amount_minor: priceValue ? priceMinor : null, contract_fx_rate: priceValue ? fxRate.trim().replace(',', '.') || null : null }
  const changePrice = (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget
    const raw = input.value
    const cursor = input.selectionStart ?? raw.length
    const comma = raw.indexOf(',')
    const wholeSide = comma < 0 || cursor <= comma
    const digitsBeforeCursor = (wholeSide ? raw.slice(0, cursor) : raw.slice(comma + 1, cursor)).replace(/\D/g, '').length
    const formatted = formatPriceInput(raw, currency)
    if (kind === 'project') setC(formatted)
    else setProjectPrice(formatted)
    requestAnimationFrame(() => {
      if (!input.isConnected) return
      let next = 0
      if (wholeSide) {
        const whole = formatted.split(',')[0]
        let digits = 0
        while (next < whole.length && digits < digitsBeforeCursor) { if (/\d/.test(whole[next])) digits++; next++ }
      } else {
        next = formatted.indexOf(',') + 1 + Math.min(digitsBeforeCursor, 2)
      }
      input.setSelectionRange(next, next)
    })
  }
  const changeCurrency = (next: Project['contract_currency']) => {
    setCurrency(next)
    if (next !== currency) setFxRate('')
    if (kind === 'project') setC(formatPriceInput(priceValue, next))
    else setProjectPrice(formatPriceInput(priceValue, next))
  }
  const selectContractFile = (file: File | null) => {
    if (!file) { setContractFile(null); setFileError(''); return }
    if (file.name.length > 180 || !/\.(pdf|docx)$/i.test(file.name)) { setContractFile(null); setFileError('En fazla 180 karakterlik PDF veya DOCX dosyası seçin.'); return }
    if (file.size === 0 || file.size > 8 * 1024 * 1024) { setContractFile(null); setFileError('Dosya boş olamaz ve en fazla 8 MB olabilir.'); return }
    setContractFile(file)
    setFileError('')
  }

  const config = (() => {
    if (kind === 'project' || kind === 'historical') return { title: kind === 'historical' ? 'Geçmiş proje ekle' : 'Yeni proje', path: '/api/v1/projects', method: 'POST', body: { name: a, customer_name: b, note: projectNote || null, ...priceFields, accent_color: color, project_state: kind === 'historical' ? 'completed' : 'active', stage: kind === 'historical' ? 'completed' : 'planning', progress_percent: kind === 'historical' ? 100 : 0 } }
    if (kind === 'edit') return { title: 'Projeyi düzenle', path: `/api/v1/projects/${projectId}`, method: 'PATCH', body: { name: a, customer_name: b, note: projectNote || null, ...priceFields, address: c || null, next_step: d || null, stage, progress_percent: Number(progress), accent_color: color } }
    if (kind === 'note') return { title: 'Hızlı not ekle', path: `/api/v1/projects/${projectId}/notes`, method: 'POST', body: { content: a, pinned: false } }
    if (kind === 'task') return { title: 'Yapılacak ekle', path: `/api/v1/projects/${projectId}/tasks`, method: 'POST', body: { title: a, due_date: date || null, task_state: waiting ? 'waiting' : 'todo', waiting_on: waiting ? b || null : null, note: c || null } }
    if (kind === 'color') return { title: 'Renk / malzeme ekle', path: `/api/v1/projects/${projectId}/colors`, method: 'POST', body: { label: a, color_code: b, material: c || null, note: d || null } }
    return { title: 'Şantiye ziyareti planla', path: `/api/v1/projects/${projectId}/visits`, method: 'POST', body: { visit_date: date, purpose: a, note: b || null, visit_state: 'planned' } }
  })()
  const mutation = useMutation({ mutationFn: async () => {
    const file = contractFile ? await readContractFile(contractFile) : null
    if (kind === 'project' || kind === 'historical') return apiRequest<Project>(config.path, { method: config.method, body: { ...config.body, contract_file: file } })
    const result = await apiRequest(config.path, { method: config.method, body: config.body })
    if (kind === 'edit' && file) await apiRequest(`/api/v1/projects/${projectId}/contract`, { method: 'PUT', body: file })
    return result
  }, onSuccess: (result) => onSaved(kind === 'project' || kind === 'historical' ? (result as Project).id : undefined) })

  return <SideSheet title={config.title} description={kind === 'historical' ? 'Tamamlanmış projeyi ekleyin. Ardından Ürünler ve fiyat önerisi bölümünde geçmiş teklif tarihini, gerçekleşen maliyeti ve o günkü malzeme birim fiyatlarını kaydedin.' : undefined} open onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!a.trim() || Boolean(priceError || fxRateError || fileError)} onClick={() => mutation.mutate()}>Kaydet</Button></>}>
    <div className="form-stack">
      {(kind === 'project' || kind === 'historical' || kind === 'edit') && <>
        <Field label="Proje adı"><TextInput value={a} onChange={(e) => setA(e.target.value)} autoFocus /></Field>
        <Field label="Müşteri"><TextInput value={b} onChange={(e) => setB(e.target.value)} /></Field>
        <Field label="Proje detayları" hint="Kapsamı, önemli talepleri ve teklif varsayımlarını yazın."><textarea className="input textarea textarea--large" maxLength={2000} value={projectNote} onChange={(e) => setProjectNote(e.target.value)} placeholder="Örn. Mutfak ve vestiyer imalatı; özel aksesuar ve montaj dahil" /></Field>
        <div className="form-grid">
          <Field label="Anlaşılan proje fiyatı" hint="Müşteriyle anlaşılan toplam tutar." error={priceError || undefined}>
            <TextInput inputMode="decimal" value={priceValue} onChange={changePrice} onKeyDown={(event) => {
              if (!priceValue || event.currentTarget.selectionStart !== event.currentTarget.selectionEnd) return
              const input = event.currentTarget
              const comma = priceValue.indexOf(',')
              const cursor = input.selectionStart ?? 0
              if (event.key === ',' || event.key === '.') { event.preventDefault(); input.setSelectionRange(comma + 1, comma + 1) }
              else if (event.key === 'Backspace' && cursor === comma + 1) { event.preventDefault(); input.setSelectionRange(comma, comma) }
              else if (event.key === 'Delete' && cursor === comma) { event.preventDefault(); input.setSelectionRange(comma + 1, comma + 1) }
              else if (/^\d$/.test(event.key) && cursor >= comma + 3) input.setSelectionRange(comma, comma)
            }} placeholder="Örn. 300.000,00₺" />
          </Field>
          <Field label="Para birimi"><SelectInput value={currency} onChange={(e) => changeCurrency(e.target.value as Project['contract_currency'])}><option value="TRY">TL</option><option value="USD">USD ($)</option><option value="EUR">EUR (€)</option><option value="GBP">GBP (£)</option></SelectInput></Field>
        </div>
        {currency !== 'TRY' && <><Field label={`1 ${currency} kaç TL?`} hint="Sözleşme tarihindeki kuru girin; kârlılık TL karşılığıyla hesaplanır." error={fxRateError || undefined}><TextInput inputMode="decimal" value={fxRate} onChange={(e) => setFxRate(e.target.value)} placeholder="Örn. 42,25" /></Field>{priceValue && numericFxRate > 0 && <div className="calculation"><span>TL karşılığı</span><strong>{formatMoney(convertMinorAtRate(priceMinor, fxRate))}</strong></div>}</>}
        <Field label="Sözleşme dosyası" hint={contractFile ? `${contractFile.name} seçildi` : contract ? `Mevcut dosya: ${contract.file_name}` : 'PDF veya DOCX · en fazla 8 MB'} error={fileError || undefined}>
          <TextInput type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(e) => selectContractFile(e.target.files?.[0] ?? null)} />
        </Field>
        {kind === 'edit' && <>
          <Field label="Adres"><textarea className="input textarea" value={c} onChange={(e) => setC(e.target.value)} /></Field>
          <Field label="Sıradaki adım"><TextInput value={d} onChange={(e) => setD(e.target.value)} /></Field>
          <div className="form-grid"><Field label="Aşama"><SelectInput value={stage} onChange={(e) => setStage(e.target.value as Project['stage'])}>{stages.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</SelectInput></Field><Field label="İlerleme %"><TextInput type="number" min="0" max="100" value={progress} onChange={(e) => setProgress(e.target.value)} /></Field></div>
        </>}
        <Field label="Proje rengi"><TextInput type="color" value={color} onChange={(e) => setColor(e.target.value)} /></Field>
      </>}
      {kind === 'note' && <Field label="Not"><textarea className="input textarea textarea--large" value={a} onChange={(e) => setA(e.target.value)} autoFocus /></Field>}
      {kind === 'task' && <><Field label="Yapılacak"><TextInput value={a} onChange={(e) => setA(e.target.value)} autoFocus /></Field><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><label className="check-field"><input type="checkbox" checked={waiting} onChange={(e) => setWaiting(e.target.checked)} />Birinden dönüş bekliyorum</label>{waiting && <Field label="Kimden / nereden?"><TextInput value={b} onChange={(e) => setB(e.target.value)} /></Field>}<Field label="Not"><textarea className="input textarea" value={c} onChange={(e) => setC(e.target.value)} /></Field></>}
      {kind === 'color' && <><Field label="Kullanım yeri"><TextInput value={a} onChange={(e) => setA(e.target.value)} placeholder="Mutfak kapakları" autoFocus /></Field><Field label="Renk kodu"><TextInput value={b} onChange={(e) => setB(e.target.value)} placeholder="RAL 1019 veya #B7A99A" /></Field><Field label="Malzeme"><TextInput value={c} onChange={(e) => setC(e.target.value)} placeholder="Mat lake" /></Field><Field label="Not"><textarea className="input textarea" value={d} onChange={(e) => setD(e.target.value)} /></Field></>}
      {kind === 'visit' && <><Field label="Ziyaret amacı"><TextInput value={a} onChange={(e) => setA(e.target.value)} placeholder="Son ölçü kontrolü" autoFocus /></Field><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Hazırlık notu"><textarea className="input textarea" value={b} onChange={(e) => setB(e.target.value)} /></Field></>}
      {mutation.error && <span className="form-error">{mutation.error.message}</span>}
    </div>
  </SideSheet>
}
