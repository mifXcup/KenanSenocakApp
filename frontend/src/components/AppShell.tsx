import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { Archive, MagnifyingGlass, Plus } from '@phosphor-icons/react'
import { Button } from './ui'
import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '../lib/api'
import type { Employee, Material, Project, Supplier } from '../lib/types'
import { navigationGroups, navigationLabel } from '../appNavigation'

export function AppShell({ children, onQuickPurchase }: { children: ReactNode; onQuickPurchase: () => void }) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchValue, setSearchValue] = useState('')
  const location = useLocation()
  const navigate = useNavigate()
  const suppliers = useQuery({ queryKey: ['search-suppliers'], queryFn: () => apiRequest<Supplier[]>('/api/v1/suppliers?limit=500') })
  const projects = useQuery({ queryKey: ['search-projects'], queryFn: () => apiRequest<Project[]>('/api/v1/projects?limit=500') })
  const materials = useQuery({ queryKey: ['search-materials'], queryFn: () => apiRequest<Material[]>('/api/v1/materials?limit=500') })
  const customers = useQuery({ queryKey: ['search-customers'], queryFn: () => apiRequest<Array<{ id: string; name: string; phone: string | null }>>('/api/v1/customers?limit=500') })
  const employees = useQuery({ queryKey: ['search-employees'], queryFn: () => apiRequest<Employee[]>('/api/v1/employees?limit=500') })
  const searchResults = useMemo(() => {
    const term = searchValue.trim().toLocaleLowerCase('tr-TR')
    if (term.length < 2) return []
    return [
      ...(customers.data ?? []).filter((item) => `${item.name} ${item.phone ?? ''}`.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Müşteri', title: item.name, detail: item.phone ?? 'Telefon yok', route: `/musteriler?customer=${item.id}` })),
      ...(suppliers.data ?? []).filter((item) => `${item.name} ${item.phone ?? ''}`.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Firma', title: item.name, detail: item.phone ?? 'Telefon yok', route: `/firmalar?supplier=${item.id}` })),
      ...(projects.data ?? []).filter((item) => `${item.name} ${item.customer_name}`.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Proje', title: item.name, detail: item.customer_name, route: `/projeler?project=${item.id}` })),
      ...(materials.data ?? []).filter((item) => item.name.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Malzeme', title: item.name, detail: item.default_unit, route: '/malzemeler' })),
      ...(employees.data ?? []).filter((item) => `${item.name} ${item.role ?? ''}`.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Personel', title: item.name, detail: item.role ?? 'Görev yok', route: `/personel?employee=${item.id}` })),
    ].slice(0, 12)
  }, [customers.data, employees.data, materials.data, projects.data, suppliers.data, searchValue])

  const closeSearch = () => { setSearchOpen(false); setSearchValue('') }
  const openResult = (route: string) => { navigate(route); closeSearch() }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setSearchOpen(true)
      }
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'p') {
        event.preventDefault(); onQuickPurchase()
      }
      if (event.ctrlKey && event.key.toLowerCase() === 'b') {
        event.preventDefault(); navigate('/ayarlar')
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [navigate, onQuickPurchase])

  const current = navigationLabel(location.pathname)

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand__mark">KŞ</span><span><strong>Kenan Şenocak</strong><small>Yönetim</small></span></div>
        <nav aria-label="Ana navigasyon">
          {navigationGroups.map((group) => <div className="nav-group" key={group.label}><span className="nav-group__label">{group.label}</span>{group.items.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`} title={label}>
                <Icon size={19} weight="regular" aria-hidden="true" /><span>{label}</span>
              </NavLink>
            ))}</div>)}
        </nav>
        <div className="sidebar__footer"><Archive size={18} /><span>Veriler bu bilgisayarda</span></div>
      </aside>
      <div className="workspace">
        <header className="toolbar">
          <span className="toolbar__context">{current}</span>
          <div className="toolbar__actions">
            <button className="search-trigger" onClick={() => setSearchOpen(true)}><MagnifyingGlass size={18} /><span>Ara</span><kbd>Ctrl K</kbd></button>
            <Button variant="primary" onClick={onQuickPurchase}><Plus size={18} />Yeni satın alma</Button>
          </div>
        </header>
        <main className="main-content">{children}</main>
      </div>
      {searchOpen && (
        <div className="command-layer" onMouseDown={(event) => event.target === event.currentTarget && closeSearch()}>
          <section className="command" role="dialog" aria-modal="true" aria-label="Global arama">
            <MagnifyingGlass size={20} /><input autoFocus value={searchValue} onChange={(event) => setSearchValue(event.target.value)} placeholder="Müşteri, proje, tedarikçi, malzeme veya personel ara" onKeyDown={(event) => event.key === 'Escape' && closeSearch()} />
            <kbd>Esc</kbd>
            <div className="search-results">
              {searchValue.trim().length < 2 ? <p>Aramak için en az iki karakter yazın.</p> : searchResults.length === 0 ? <p>Eşleşen kayıt bulunamadı.</p> : searchResults.map((result) => <button key={`${result.type}-${result.id}`} onClick={() => openResult(result.route)}><span className="search-results__type">{result.type}</span><strong>{result.title}</strong><small>{result.detail}</small></button>)}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
