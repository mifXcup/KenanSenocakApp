import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowSquareOut, CalendarBlank, Check, Circle, Clock, Drop, MapPin, NotePencil,
  Plus, Ruler, Target,
} from '@phosphor-icons/react'
import { apiRequest, formatDate, toKurus } from './lib/api'
import type { Project, ProjectHub, ProjectTask } from './lib/types'
import { Button, EmptyState, ErrorState, Field, LoadingRows, PageHeader, SelectInput, SideSheet, TextInput } from './components/ui'
import { ProductPricingPanel } from './productPricing'

const stages: Array<[Project['stage'], string]> = [
  ['planning', 'Planlama'], ['design', 'Tasarım'], ['approval', 'Onay'], ['production', 'Üretim'],
  ['delivery', 'Sevkiyat'], ['installation', 'Montaj'], ['completed', 'Tamamlandı'],
]
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
type AddKind = 'note' | 'task' | 'color' | 'measurement' | 'visit' | 'edit' | 'project' | null

const stageLabel = (stage: string) => stages.find(([value]) => value === stage)?.[1] ?? stage

export function ProjectCenterPage() {
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const requestedId = params.get('project')
  const [selectedId, setSelectedId] = useState(() => requestedId || localStorage.getItem('ks-active-project') || '')
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
  const refresh = () => { client.invalidateQueries({ queryKey: ['project-hub', activeSelectedId] }); client.invalidateQueries({ queryKey: ['projects'] }); setSheet(null) }

  if (projects.isLoading) return <div className="page"><LoadingRows count={5} /></div>
  if (projects.error) return <div className="page"><ErrorState error={projects.error} onRetry={() => projects.refetch()} /></div>
  if (!projects.data?.length) return <div className="page"><PageHeader title="Proje Takip" description="Bütün saha kararları ve notları tek yerde." /><EmptyState title="İlk projenizi oluşturun" description="Ölçüleri, renk kodlarını, ziyaretleri ve yapılacakları proje altında takip edin." action={<Button variant="primary" onClick={() => setSheet('project')}><Plus size={18} />Proje oluştur</Button>} />{sheet === 'project' && <ProjectSheet kind="project" projectId="" onClose={() => setSheet(null)} onSaved={refresh} />}</div>

  const data = hub.data
  const openTasks = data?.tasks.filter((task) => task.task_state !== 'done') ?? []
  const nextVisit = data?.visits.find((visit) => visit.visit_state === 'planned' && visit.visit_date >= today)

  return (
    <div className="page project-center">
      <PageHeader title="Proje Takip" description="Bugünkü durumu, saha bilgisini ve sıradaki kararı aynı yerde tutun." action={<div className="project-actions"><Button onClick={() => window.ksDesktop?.app.toggleProjectBar()}><ArrowSquareOut size={18} />Masaüstü barı</Button><Button variant="primary" onClick={() => setSheet('project')}><Plus size={18} />Yeni proje</Button></div>} />
      <div className="project-center__layout">
        <aside className="project-rail">
          <span className="project-rail__label">AKTİF PROJELER</span>
          {projects.data.map((project) => <button key={project.id} className={`project-card ${project.id === activeSelectedId ? 'project-card--active' : ''}`} onClick={() => selectProject(project.id)}>
            <span className="project-card__color" style={{ background: project.accent_color }} />
            <span><strong>{project.name}</strong><small>{project.customer_name}</small></span>
            <em>{project.progress_percent}%</em>
          </button>)}
        </aside>
        <section className="project-canvas">
          {hub.isLoading ? <LoadingRows count={6} /> : hub.error ? <ErrorState error={hub.error} onRetry={() => hub.refetch()} /> : data && <>
            <header className="project-hero" style={{ '--project-accent': data.project.accent_color } as CSSProperties}>
              <div className="project-hero__title"><span className="project-dot" /><div><span className="eyebrow-dark">{stageLabel(data.project.stage)}</span><h2>{data.project.name}</h2><p>{data.project.customer_name}{data.project.address ? ` · ${data.project.address}` : ''}</p></div></div>
              <Button onClick={() => setSheet('edit')}>Projeyi düzenle</Button>
              <div className="project-progress"><span><b>İlerleme</b><em>{data.project.progress_percent}%</em></span><div><i style={{ width: `${data.project.progress_percent}%` }} /></div></div>
              <div className="project-next"><Target size={20} /><span><small>SIRADAKİ ADIM</small><strong>{data.project.next_step || 'Sıradaki adım henüz yazılmadı'}</strong></span></div>
            </header>
            <div className="project-pulse">
              <div><Clock size={19} /><span><small>Açık iş</small><strong>{openTasks.length}</strong></span></div>
              <div><CalendarBlank size={19} /><span><small>Sonraki ziyaret</small><strong>{nextVisit ? formatDate(nextVisit.visit_date) : 'Planlanmadı'}</strong></span></div>
              <div><Ruler size={19} /><span><small>Kayıtlı ölçü</small><strong>{data.measurements.length}</strong></span></div>
              <div><Drop size={19} /><span><small>Renk / malzeme</small><strong>{data.colors.length}</strong></span></div>
            </div>
            <div className="project-grid">
              <HubSection title="Yapılacaklar ve beklenenler" count={data.tasks.length} action={() => setSheet('task')} icon={<Check size={18} />}>
                {data.tasks.length ? <div className="compact-list">{data.tasks.slice(0, 6).map((task) => <TaskRow key={task.id} task={task} onChanged={() => hub.refetch()} />)}</div> : <MiniEmpty text="Henüz yapılacak eklenmedi." />}
              </HubSection>
              <HubSection title="Hızlı notlar" count={data.notes.length} action={() => setSheet('note')} icon={<NotePencil size={18} />}>
                {data.notes.length ? <div className="note-stack">{data.notes.slice(0, 4).map((note) => <article key={note.id}><p>{note.content}</p><time>{new Date(note.created_at).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'short' })}</time></article>)}</div> : <MiniEmpty text="Projeye ilk notu ekleyin." />}
              </HubSection>
              <HubSection title="Ölçüler" count={data.measurements.length} action={() => setSheet('measurement')} icon={<Ruler size={18} />}>
                {data.measurements.length ? <div className="spec-list">{data.measurements.slice(0, 5).map((item) => <div key={item.id}><span><strong>{item.space_name}</strong><small>{item.label}</small></span><b>{item.value} {item.unit}</b></div>)}</div> : <MiniEmpty text="Mahal ve ölçü bilgisi yok." />}
              </HubSection>
              <HubSection title="Renk ve malzemeler" count={data.colors.length} action={() => setSheet('color')} icon={<Drop size={18} />}>
                {data.colors.length ? <div className="swatch-list">{data.colors.slice(0, 5).map((item) => <div key={item.id}><span className="swatch" style={{ background: item.color_code.startsWith('#') ? item.color_code : '#ded8d1' }} /><span><strong>{item.label}</strong><small>{item.material || 'Malzeme belirtilmedi'}</small></span><b>{item.color_code}</b></div>)}</div> : <MiniEmpty text="Renk veya malzeme kodu yok." />}
              </HubSection>
              <HubSection title="Şantiye ziyaretleri" count={data.visits.length} action={() => setSheet('visit')} icon={<MapPin size={18} />} wide>
                {data.visits.length ? <div className="visit-list">{data.visits.slice(0, 5).map((visit) => <div key={visit.id}><span className={`visit-date ${visit.visit_state === 'completed' ? 'visit-date--done' : ''}`}><b>{new Date(`${visit.visit_date}T12:00:00`).toLocaleDateString('tr-TR', { day: '2-digit' })}</b><small>{new Date(`${visit.visit_date}T12:00:00`).toLocaleDateString('tr-TR', { month: 'short' })}</small></span><span><strong>{visit.purpose}</strong><small>{visit.note || (visit.visit_state === 'planned' ? 'Planlandı' : 'Tamamlandı')}</small></span></div>)}</div> : <MiniEmpty text="Planlanmış ziyaret bulunmuyor." />}
              </HubSection>
            </div>
            <ProductPricingPanel projectId={activeSelectedId} />
          </>}
        </section>
      </div>
      {sheet && <ProjectSheet kind={sheet} projectId={activeSelectedId} project={data?.project} onClose={() => setSheet(null)} onSaved={refresh} />}
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

function ProjectSheet({ kind, projectId, project, onClose, onSaved }: { kind: Exclude<AddKind, null>; projectId: string; project?: Project; onClose: () => void; onSaved: () => void }) {
  const [a, setA] = useState(project?.name ?? '')
  const [b, setB] = useState(project?.customer_name ?? '')
  const [c, setC] = useState(kind === 'edit' ? project?.address ?? '' : '')
  const [d, setD] = useState(kind === 'edit' ? project?.next_step ?? '' : '')
  const [date, setDate] = useState(today)
  const [stage, setStage] = useState<Project['stage']>(project?.stage ?? 'planning')
  const [progress, setProgress] = useState(String(project?.progress_percent ?? 0))
  const [color, setColor] = useState(project?.accent_color ?? '#9A5A3A')
  const [waiting, setWaiting] = useState(false)

  const config = useMemo(() => {
    if (kind === 'project') return { title: 'Yeni proje', path: '/api/v1/projects', method: 'POST', body: { name: a, customer_name: b, contract_amount_kurus: c ? toKurus(c) : null, budget_kurus: d ? toKurus(d) : null, accent_color: color, stage: 'planning', progress_percent: 0 } }
    if (kind === 'edit') return { title: 'Projeyi düzenle', path: `/api/v1/projects/${projectId}`, method: 'PATCH', body: { name: a, customer_name: b, address: c || null, next_step: d || null, stage, progress_percent: Number(progress), accent_color: color } }
    if (kind === 'note') return { title: 'Hızlı not ekle', path: `/api/v1/projects/${projectId}/notes`, method: 'POST', body: { content: a, pinned: false } }
    if (kind === 'task') return { title: 'Yapılacak ekle', path: `/api/v1/projects/${projectId}/tasks`, method: 'POST', body: { title: a, due_date: date || null, task_state: waiting ? 'waiting' : 'todo', waiting_on: waiting ? b || null : null, note: c || null } }
    if (kind === 'color') return { title: 'Renk / malzeme ekle', path: `/api/v1/projects/${projectId}/colors`, method: 'POST', body: { label: a, color_code: b, material: c || null, note: d || null } }
    if (kind === 'measurement') return { title: 'Ölçü ekle', path: `/api/v1/projects/${projectId}/measurements`, method: 'POST', body: { space_name: a, label: b, value: c, unit: d || 'cm', measured_on: date } }
    return { title: 'Şantiye ziyareti planla', path: `/api/v1/projects/${projectId}/visits`, method: 'POST', body: { visit_date: date, purpose: a, note: b || null, visit_state: 'planned' } }
  }, [a, b, c, d, color, date, kind, progress, projectId, stage, waiting])
  const mutation = useMutation({ mutationFn: () => apiRequest(config.path, { method: config.method, body: config.body }), onSuccess: onSaved })

  return <SideSheet title={config.title} open onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!a.trim()} onClick={() => mutation.mutate()}>Kaydet</Button></>}>
    <div className="form-stack">
      {(kind === 'project' || kind === 'edit') && <><Field label="Proje adı"><TextInput value={a} onChange={(e) => setA(e.target.value)} autoFocus /></Field><Field label="Müşteri"><TextInput value={b} onChange={(e) => setB(e.target.value)} /></Field>{kind === 'project' ? <div className="form-grid"><Field label="Sözleşme"><TextInput inputMode="decimal" value={c} onChange={(e) => setC(e.target.value)} /></Field><Field label="Bütçe"><TextInput inputMode="decimal" value={d} onChange={(e) => setD(e.target.value)} /></Field></div> : <><Field label="Adres"><textarea className="input textarea" value={c} onChange={(e) => setC(e.target.value)} /></Field><Field label="Sıradaki adım"><TextInput value={d} onChange={(e) => setD(e.target.value)} /></Field><div className="form-grid"><Field label="Aşama"><SelectInput value={stage} onChange={(e) => setStage(e.target.value as Project['stage'])}>{stages.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</SelectInput></Field><Field label="İlerleme %"><TextInput type="number" min="0" max="100" value={progress} onChange={(e) => setProgress(e.target.value)} /></Field></div></>}<Field label="Proje rengi"><TextInput type="color" value={color} onChange={(e) => setColor(e.target.value)} /></Field></>}
      {kind === 'note' && <Field label="Not"><textarea className="input textarea textarea--large" value={a} onChange={(e) => setA(e.target.value)} autoFocus /></Field>}
      {kind === 'task' && <><Field label="Yapılacak"><TextInput value={a} onChange={(e) => setA(e.target.value)} autoFocus /></Field><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><label className="check-field"><input type="checkbox" checked={waiting} onChange={(e) => setWaiting(e.target.checked)} />Birinden dönüş bekliyorum</label>{waiting && <Field label="Kimden / nereden?"><TextInput value={b} onChange={(e) => setB(e.target.value)} /></Field>}<Field label="Not"><textarea className="input textarea" value={c} onChange={(e) => setC(e.target.value)} /></Field></>}
      {kind === 'color' && <><Field label="Kullanım yeri"><TextInput value={a} onChange={(e) => setA(e.target.value)} placeholder="Mutfak kapakları" autoFocus /></Field><Field label="Renk kodu"><TextInput value={b} onChange={(e) => setB(e.target.value)} placeholder="RAL 1019 veya #B7A99A" /></Field><Field label="Malzeme"><TextInput value={c} onChange={(e) => setC(e.target.value)} placeholder="Mat lake" /></Field><Field label="Not"><textarea className="input textarea" value={d} onChange={(e) => setD(e.target.value)} /></Field></>}
      {kind === 'measurement' && <><Field label="Mahal"><TextInput value={a} onChange={(e) => setA(e.target.value)} placeholder="Salon" autoFocus /></Field><Field label="Ölçü"><TextInput value={b} onChange={(e) => setB(e.target.value)} placeholder="TV ünitesi duvarı" /></Field><div className="form-grid"><Field label="Değer"><TextInput value={c} onChange={(e) => setC(e.target.value)} /></Field><Field label="Birim"><SelectInput value={d || 'cm'} onChange={(e) => setD(e.target.value)}><option>cm</option><option>mm</option><option>m</option><option>m²</option></SelectInput></Field></div><Field label="Ölçüm tarihi"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field></>}
      {kind === 'visit' && <><Field label="Ziyaret amacı"><TextInput value={a} onChange={(e) => setA(e.target.value)} placeholder="Son ölçü kontrolü" autoFocus /></Field><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Hazırlık notu"><textarea className="input textarea" value={b} onChange={(e) => setB(e.target.value)} /></Field></>}
      {mutation.error && <span className="form-error">{mutation.error.message}</span>}
    </div>
  </SideSheet>
}
