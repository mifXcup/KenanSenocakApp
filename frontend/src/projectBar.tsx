import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowsInSimple, ArrowsOutSimple, ArrowSquareOut, Check, DotsSixVertical, NotePencil, X } from '@phosphor-icons/react'
import { apiList, apiRequest, formatDate } from './lib/api'
import { workStatusLabel } from './lib/labels'
import type { Employee, Project, ProjectHub } from './lib/types'

type Tab = 'project' | 'attendance'
type AddMode = 'task' | 'note'
type DayLog = { id: string; employee_id: string; work_status: string; status: string }

const istanbulToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error))

export function MiniProjectBar() {
  const client = useQueryClient()
  const [expanded, setExpanded] = useState(true)
  const [tab, setTab] = useState<Tab>('project')
  const [mode, setMode] = useState<AddMode>('task')
  const [text, setText] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [withProject, setWithProject] = useState(true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const today = istanbulToday()

  const projects = useQuery({ queryKey: ['projects'], queryFn: () => apiList<Project>('/api/v1/projects') })
  const [projectId, setProjectId] = useState(() => localStorage.getItem('ks-active-project') || '')
  const activeProjectId = projects.data?.some((project) => project.id === projectId) ? projectId : projects.data?.[0]?.id ?? ''

  // Ana pencerede proje değişince (aynı localStorage) bar da aynı projeye geçer.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => { if (event.key === 'ks-active-project' && event.newValue) setProjectId(event.newValue) }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') void window.ksDesktop?.app.hideProjectBar() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const hub = useQuery({ queryKey: ['project-hub', activeProjectId], queryFn: () => apiRequest<ProjectHub>(`/api/v1/projects/${activeProjectId}/hub`), enabled: Boolean(activeProjectId), refetchInterval: 30_000 })
  const employees = useQuery({ queryKey: ['bar-employees'], queryFn: () => apiList<Employee>('/api/v1/employees'), enabled: tab === 'attendance' })
  const logs = useQuery({ queryKey: ['bar-logs', today], queryFn: () => apiList<DayLog>(`/api/v1/work-logs?date_from=${today}&date_to=${today}`), enabled: tab === 'attendance', refetchInterval: 60_000 })

  const refreshHub = () => client.invalidateQueries({ queryKey: ['project-hub', activeProjectId] })
  const fail = (e: unknown) => { setMessage(''); setError(messageOf(e)) }
  const succeed = (done: string) => { setError(''); setMessage(done) }

  const add = useMutation({
    mutationFn: () => mode === 'note'
      ? apiRequest(`/api/v1/projects/${activeProjectId}/notes`, { method: 'POST', body: { content: text.trim(), pinned: false } })
      : apiRequest(`/api/v1/projects/${activeProjectId}/tasks`, { method: 'POST', body: { title: text.trim(), due_date: dueDate || null } }),
    onSuccess: () => { setText(''); setDueDate(''); succeed(mode === 'note' ? 'Not kaydedildi.' : 'Görev eklendi.'); void refreshHub() },
    onError: fail,
  })
  const complete = useMutation({
    mutationFn: (taskId: string) => apiRequest(`/api/v1/project-tasks/${taskId}`, { method: 'PATCH', body: { task_state: 'done' } }),
    onSuccess: () => { succeed('Görev tamamlandı.'); void refreshHub() },
    onError: fail,
  })
  const mark = useMutation({
    mutationFn: ({ employeeId, status }: { employeeId: string; status: 'worked' | 'absent' }) => apiRequest('/api/v1/work-logs', {
      method: 'POST',
      body: { employee_id: employeeId, work_date: today, work_status: status, project_id: status === 'worked' && withProject && activeProjectId ? activeProjectId : null },
    }),
    onSuccess: () => { succeed('Puantaj kaydedildi.'); void client.invalidateQueries({ queryKey: ['bar-logs', today] }) },
    onError: fail,
  })

  const toggle = () => { const next = !expanded; setExpanded(next); void window.ksDesktop?.app.setProjectBarExpanded(next) }
  const openTasks = useMemo(() => hub.data?.tasks.filter((task) => task.task_state !== 'done') ?? [], [hub.data?.tasks])
  const nextVisit = hub.data?.visits.find((visit) => visit.visit_state === 'planned')
  const project = hub.data?.project
  const loggedToday = useMemo(() => new Map((logs.data ?? []).filter((log) => log.status === 'active').map((log) => [log.employee_id, log])), [logs.data])
  const activeEmployees = (employees.data ?? []).filter((employee) => (employee.employment_state ?? 'active') === 'active')
  const canAdd = text.trim().length >= 2 && Boolean(activeProjectId) && !add.isPending

  return <main className={`project-bar ${expanded ? 'project-bar--expanded' : 'project-bar--compact'}`} style={{ '--project-accent': project?.accent_color || '#9A5A3A' } as CSSProperties}>
    <header className="project-bar__drag">
      <DotsSixVertical size={20} />
      <span><b>PROJE BARI</b></span>
      <button className="project-bar__control" onClick={toggle} aria-label={expanded ? 'Barı daralt' : 'Barı genişlet'}>{expanded ? <ArrowsInSimple size={17} /> : <ArrowsOutSimple size={17} />}</button>
      <button className="project-bar__control" onClick={() => void window.ksDesktop?.app.hideProjectBar()} aria-label="Barı gizle (Esc)" title="Gizle (Esc). Tepsi simgesinden tekrar açılır."><X size={17} /></button>
    </header>
    <section className="project-bar__project">
      <span className="project-bar__mark" />
      <select value={activeProjectId} onChange={(event) => { setProjectId(event.target.value); localStorage.setItem('ks-active-project', event.target.value) }} aria-label="Aktif proje">{projects.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
      <button onClick={() => void window.ksDesktop?.app.showMain(activeProjectId)} aria-label="Projeyi uygulamada aç" title="Projeyi uygulamada aç"><ArrowSquareOut size={18} /></button>
    </section>
    {expanded && <>
      <nav className="pb-tabs" aria-label="Bar bölümleri">
        <button className={tab === 'project' ? 'pb-tabs__on' : ''} aria-pressed={tab === 'project'} onClick={() => setTab('project')}>Proje</button>
        <button className={tab === 'attendance' ? 'pb-tabs__on' : ''} aria-pressed={tab === 'attendance'} onClick={() => setTab('attendance')}>Bugünkü puantaj</button>
      </nav>
      <div className="pb-body">
        {projects.isError ? <div className="project-bar__empty" role="alert">Projeler alınamadı: {messageOf(projects.error)}</div> : tab === 'project' ? (
          hub.isError ? <div className="project-bar__empty" role="alert">Proje bilgisi alınamadı: {messageOf(hub.error)}</div>
            : !project ? <div className="project-bar__empty">{projects.isLoading || hub.isLoading ? 'Yükleniyor…' : 'Henüz proje bulunmuyor.'}</div> : <>
              <section className="project-bar__status">
                <span><small>%{project.progress_percent} TAMAMLANDI</small><b>{project.next_step || 'Sıradaki adımı belirleyin'}</b></span>
                <div role="progressbar" aria-valuenow={project.progress_percent} aria-valuemin={0} aria-valuemax={100} aria-label="Proje ilerlemesi"><i style={{ width: `${project.progress_percent}%` }} /></div>
              </section>
              <section className="project-bar__facts"><div><small>AÇIK İŞ</small><b>{openTasks.length}</b></div><div><small>SONRAKİ ZİYARET</small><b>{nextVisit ? formatDate(nextVisit.visit_date) : '—'}</b></div></section>
              <ul className="pb-tasks" aria-label="Açık işler">
                {openTasks.length ? openTasks.map((task) => <li key={task.id}>
                  <button className="pb-check" disabled={complete.isPending} onClick={() => complete.mutate(task.id)} aria-label={`${task.title} işini tamamla`}><Check size={12} /></button>
                  <span><b>{task.title}</b><small>{task.task_state === 'waiting' ? `${task.waiting_on || 'Dışarıdan'} bekleniyor` : task.due_date ? formatDate(task.due_date) : 'Tarih yok'}</small></span>
                </li>) : <li className="pb-empty">Açık iş bulunmuyor.</li>}
              </ul>
            </>
        ) : (
          <section className="pb-att">
            <label className="pb-att__option"><input type="checkbox" checked={withProject} onChange={(event) => setWithProject(event.target.checked)} />“Geldi” kaydını seçili projeye yaz{project ? ` (${project.name})` : ''}</label>
            {employees.isError || logs.isError ? <div className="project-bar__empty" role="alert">Personel bilgisi alınamadı: {messageOf(employees.error ?? logs.error)}</div>
              : employees.isLoading || logs.isLoading ? <div className="project-bar__empty">Yükleniyor…</div>
                : !activeEmployees.length ? <div className="project-bar__empty">Aktif personel yok.</div>
                  : <ul>{activeEmployees.map((employee) => {
                    const log = loggedToday.get(employee.id)
                    return <li key={employee.id}>
                      <span><b>{employee.name}</b><small>{employee.role || 'Görev yok'}</small></span>
                      {log ? <em>{workStatusLabel(log.work_status)}</em> : <span className="pb-att__buttons">
                        <button disabled={mark.isPending} onClick={() => mark.mutate({ employeeId: employee.id, status: 'worked' })}>Geldi</button>
                        <button disabled={mark.isPending} onClick={() => mark.mutate({ employeeId: employee.id, status: 'absent' })}>Gelmedi</button>
                      </span>}
                    </li>
                  })}</ul>}
          </section>
        )}
      </div>
      {tab === 'project' && <form className="pb-add" onSubmit={(event) => { event.preventDefault(); if (canAdd) add.mutate() }}>
        <div className="pb-add__mode" role="group" aria-label="Ekleme türü">
          <button type="button" className={mode === 'task' ? 'pb-tabs__on' : ''} aria-pressed={mode === 'task'} onClick={() => setMode('task')}>Görev</button>
          <button type="button" className={mode === 'note' ? 'pb-tabs__on' : ''} aria-pressed={mode === 'note'} onClick={() => setMode('note')}>Not</button>
        </div>
        <div className="pb-add__row">
          <NotePencil size={17} />
          <input value={text} onChange={(event) => setText(event.target.value)} placeholder={mode === 'task' ? 'Yeni görev…' : 'Hızlı not yaz…'} aria-label={mode === 'task' ? 'Yeni görev' : 'Hızlı not'} />
          {mode === 'task' && <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} aria-label="Görev tarihi" />}
          <button disabled={!canAdd}>{mode === 'task' ? 'Ekle' : 'Kaydet'}</button>
        </div>
      </form>}
      {(message || error) && <p className={error ? 'pb-msg pb-msg--error' : 'pb-msg'} role={error ? 'alert' : 'status'}>{error || message}</p>}
    </>}
  </main>
}
