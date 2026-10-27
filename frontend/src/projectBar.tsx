import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowsInSimple, ArrowsOutSimple, ArrowSquareOut, Check, DotsSixVertical, NotePencil, Plus } from '@phosphor-icons/react'
import { apiRequest, formatDate } from './lib/api'
import type { Project, ProjectHub } from './lib/types'

export function MiniProjectBar() {
  const client = useQueryClient()
  const [expanded, setExpanded] = useState(true)
  const [note, setNote] = useState('')
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const [projectId, setProjectId] = useState(() => localStorage.getItem('ks-active-project') || '')
  const activeProjectId = projects.data?.some((project) => project.id === projectId) ? projectId : projects.data?.[0]?.id ?? ''

  useEffect(() => { if (activeProjectId) localStorage.setItem('ks-active-project', activeProjectId) }, [activeProjectId])

  const hub = useQuery({ queryKey: ['project-hub', activeProjectId], queryFn: () => apiRequest<ProjectHub>(`/api/v1/projects/${activeProjectId}/hub`), enabled: Boolean(activeProjectId), refetchInterval: 30_000 })
  const addNote = useMutation({ mutationFn: () => apiRequest(`/api/v1/projects/${activeProjectId}/notes`, { method: 'POST', body: { content: note, pinned: false } }), onSuccess: () => { setNote(''); client.invalidateQueries({ queryKey: ['project-hub', activeProjectId] }) } })
  const toggle = () => { const next = !expanded; setExpanded(next); window.ksDesktop?.app.setProjectBarExpanded(next) }
  const openTasks = useMemo(() => hub.data?.tasks.filter((task) => task.task_state !== 'done').slice(0, 3) ?? [], [hub.data?.tasks])
  const nextVisit = hub.data?.visits.find((visit) => visit.visit_state === 'planned')
  const project = hub.data?.project

  return <main className={`project-bar ${expanded ? 'project-bar--expanded' : 'project-bar--compact'}`} style={{ '--project-accent': project?.accent_color || '#9A5A3A' } as CSSProperties}>
    <header className="project-bar__drag">
      <DotsSixVertical size={20} />
      <span><b>PROJE BARI</b><small>Sürükleyerek taşı</small></span>
      <button className="project-bar__control" onClick={toggle} aria-label={expanded ? 'Barı daralt' : 'Barı genişlet'}>{expanded ? <ArrowsInSimple size={17} /> : <ArrowsOutSimple size={17} />}</button>
    </header>
    <section className="project-bar__project">
      <span className="project-bar__mark" />
      <select value={activeProjectId} onChange={(event) => setProjectId(event.target.value)} aria-label="Aktif proje">{projects.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
      <button onClick={() => window.ksDesktop?.app.showMain(activeProjectId)} aria-label="Projeyi uygulamada aç"><ArrowSquareOut size={18} /></button>
    </section>
    {expanded && <>
      {!project ? <div className="project-bar__empty">{projects.isLoading ? 'Projeler yükleniyor…' : 'Henüz proje bulunmuyor.'}</div> : <>
        <section className="project-bar__status">
          <span><small>{project.progress_percent}% TAMAMLANDI</small><b>{project.next_step || 'Sıradaki adımı belirleyin'}</b></span>
          <div><i style={{ width: `${project.progress_percent}%` }} /></div>
        </section>
        <section className="project-bar__facts"><div><small>AÇIK İŞ</small><b>{openTasks.length}</b></div><div><small>SONRAKİ ZİYARET</small><b>{nextVisit ? formatDate(nextVisit.visit_date) : '—'}</b></div></section>
        <section className="project-bar__tasks">
          <header><span>Bugün / sıradaki</span><button onClick={() => window.ksDesktop?.app.showMain(activeProjectId)}><Plus size={15} />Ekle</button></header>
          {openTasks.length ? openTasks.map((task) => <div key={task.id}><span className="project-bar__check">{task.task_state === 'done' && <Check size={12} />}</span><span><b>{task.title}</b><small>{task.task_state === 'waiting' ? `${task.waiting_on || 'Dışarıdan'} bekleniyor` : task.due_date ? formatDate(task.due_date) : 'Tarih yok'}</small></span></div>) : <p>Açık iş bulunmuyor.</p>}
        </section>
        <form className="project-bar__note" onSubmit={(event) => { event.preventDefault(); if (note.trim()) addNote.mutate() }}>
          <NotePencil size={17} /><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Hızlı not yaz…" /><button disabled={!note.trim() || addNote.isPending}>Kaydet</button>
        </form>
      </>}
    </>}
  </main>
}
