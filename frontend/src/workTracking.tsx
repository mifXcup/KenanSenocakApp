import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ClipboardText, Drop, FileText, MapPinLine, NotePencil, Ruler, Swatches } from '@phosphor-icons/react'
import { apiRequest } from './lib/api'
import type { Project } from './lib/types'
import { EmptyState, ErrorState, LoadingRows, PageHeader, SelectInput, StatusBanner } from './components/ui'

const sections = [
  { icon: ClipboardText, title: 'Şantiye eksikleri', description: 'Eksik iş, malzeme veya kararları tek listede toplayın.' },
  { icon: Ruler, title: 'Şantiye ölçüleri', description: 'Mahal ve parça bazında ölçü notlarını saklayın.' },
  { icon: FileText, title: 'Dosya ve belgeler', description: 'Teklif, çizim, görsel ve saha belgelerini projede tutun.' },
  { icon: Swatches, title: 'Renk ve kodlar', description: 'Boya, kumaş, kaplama ve ürün kodlarını kayıt altına alın.' },
  { icon: NotePencil, title: 'Proje notları', description: 'Sahadan gelen kararları ve hatırlatmaları yazın.' },
  { icon: Drop, title: 'Durum takibi', description: 'İşin hangi aşamada olduğunu görünür hale getirin.' },
]

export function WorkTrackingPage() {
  const [projectId, setProjectId] = useState('')
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const project = useMemo(() => projects.data?.find((item) => item.id === projectId), [projectId, projects.data])

  return (
    <div className="page">
      <PageHeader title="İş Takibi" description="Proje başlayınca saha bilgisini, belgeleri ve karar notlarını tek çalışma alanında toplayın." />
      <StatusBanner><strong>İlk iskelet hazır.</strong>&nbsp; Kayıt alanlarının ayrıntılarını birlikte netleştirdiğimizde kaydetme ve dosya ekleme işlemlerini etkinleştireceğiz.</StatusBanner>
      {projects.isLoading ? <LoadingRows count={3} /> : projects.error ? <ErrorState error={projects.error} onRetry={() => projects.refetch()} /> : !projects.data?.length ? (
        <EmptyState title="Önce bir proje oluşturun" description="İş takibi her projeye ayrı bağlanacak. Proje eklendiğinde çalışma alanı burada açılır." />
      ) : (
        <>
          <section className="project-picker" aria-label="İş takibi projesi">
            <div><MapPinLine size={22} /><div><strong>Çalışılacak proje</strong><span>Bilgiler seçtiğiniz projenin altında tutulacak.</span></div></div>
            <SelectInput aria-label="Proje seçin" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Proje seçin</option>{projects.data.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.customer_name}</option>)}</SelectInput>
          </section>
          {!project ? <EmptyState title="Bir proje seçin" description="Şantiye eksikleri, ölçüler, belgeler ve notlar seçtiğiniz proje için gruplanacak." /> : (
            <section className="work-hub" aria-label={`${project.name} iş takip alanları`}>
              <header className="work-hub__header"><div><span className="eyebrow">AKTİF ÇALIŞMA ALANI</span><h2>{project.name}</h2><p>{project.customer_name}</p></div><span className="status-chip">{project.project_state || 'Durum belirtilmedi'}</span></header>
              <div className="work-hub__grid">{sections.map(({ icon: Icon, title, description }, index) => <article className="work-module" key={title}><div className="work-module__index">0{index + 1}</div><Icon size={22} /><div><h3>{title}</h3><p>{description}</p></div><span className="work-module__state">Detay bekliyor</span></article>)}</div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
