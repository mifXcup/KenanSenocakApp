import { Link } from 'react-router-dom'
import { formatMoney } from './lib/api'
import type { Project } from './lib/types'

type Collection = {
  id: string
  amount_kurus: number
  movement_date: string
  movement_type: string
  payment_method?: string | null
  project_id: string | null
  status: string
}

const paymentMethodLabel: Record<string, string> = {
  cash: 'Elden',
  bank_transfer: 'Banka',
  other: 'Diğer',
}

export function CustomerAccountOverview({ projects, movements }: { projects: Project[]; movements: Collection[] }) {
  const collections = movements.filter((movement) => movement.movement_type === 'collection' && movement.status === 'active')
  const collectedFor = (projectId: string) => collections.filter((movement) => movement.project_id === projectId).reduce((total, movement) => total + movement.amount_kurus, 0)

  return <>
    <section className="panel p0-section">
      <h2>Projeler ve anlaşma tutarları</h2>
      {!projects.length ? <p>Bu müşteriye bağlı proje yok.</p> : projects.map((project) => {
        const contract = project.contract_amount_kurus || 0
        const collected = collectedFor(project.id)
        return <article className="p0-row" key={project.id}>
          <div><strong>{project.name}</strong><small>Anlaşma {formatMoney(contract)}</small></div>
          <span>Alınan {formatMoney(collected)}</span>
          <b>Kalan {formatMoney(Math.max(0, contract - collected))}</b>
          <Link to={`/projeler?project=${project.id}`}>Projeyi aç</Link>
        </article>
      })}
    </section>
    <section className="panel p0-section">
      <h2>Alınan ödemeler</h2>
      {!collections.length ? <p>Henüz tahsilat kaydı yok.</p> : collections.map((movement) => <div className="p0-row" key={movement.id}>
        <span>{movement.movement_date}</span>
        <strong>{formatMoney(movement.amount_kurus)}</strong>
        <span>{paymentMethodLabel[movement.payment_method || ''] || 'Yöntem belirtilmedi'}</span>
        <span>{projects.find((project) => project.id === movement.project_id)?.name || 'Müşteri avansı'}</span>
      </div>)}
    </section>
  </>
}
