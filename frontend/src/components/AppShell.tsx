import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Archive,
  Buildings,
  ChartLineUp,
  GearSix,
  House,
  MagnifyingGlass,
  Package,
  Plus,
  Receipt,
  Toolbox,
  UsersThree,
} from '@phosphor-icons/react'
import { Button } from './ui'
import { useCoreData } from '../hooks/useCoreData'

const navigation = [
  { to: '/', label: 'Genel Bakış', icon: House },
  { to: '/projeler', label: 'Projeler', icon: Buildings },
  { to: '/satin-almalar', label: 'Satın Almalar', icon: Receipt },
  { to: '/firmalar', label: 'Firmalar', icon: UsersThree },
  { to: '/malzemeler', label: 'Malzemeler', icon: Package },
  { to: '/personel', label: 'Personel ve Şantiye', icon: Toolbox },
  { to: '/raporlar', label: 'Raporlar', icon: ChartLineUp },
  { to: '/ayarlar', label: 'Ayarlar', icon: GearSix },
]

export function AppShell({ children, onQuickPurchase }: { children: ReactNode; onQuickPurchase: () => void }) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchValue, setSearchValue] = useState('')
  const location = useLocation()
  const navigate = useNavigate()
  const data = useCoreData()
  const searchResults = useMemo(() => {
    const term = searchValue.trim().toLocaleLowerCase('tr-TR')
    if (term.length < 2) return []
    return [
      ...(data.suppliers.data ?? []).filter((item) => `${item.name} ${item.phone ?? ''}`.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Firma', title: item.name, detail: item.phone ?? 'Telefon yok', route: '/firmalar' })),
      ...(data.projects.data ?? []).filter((item) => `${item.name} ${item.customer_name}`.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Proje', title: item.name, detail: item.customer_name, route: '/projeler' })),
      ...(data.materials.data ?? []).filter((item) => item.name.toLocaleLowerCase('tr-TR').includes(term)).map((item) => ({ id: item.id, type: 'Malzeme', title: item.name, detail: item.default_unit, route: '/malzemeler' })),
    ].slice(0, 12)
  }, [data.materials.data, data.projects.data, data.suppliers.data, searchValue])

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

  const current = navigation.find((item) => item.to === location.pathname)?.label ?? 'Kenan Şenocak Yönetim'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand__mark">KŞ</span><span><strong>Kenan Şenocak</strong><small>Yönetim</small></span></div>
        <nav aria-label="Ana navigasyon">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'nav-item--active' : ''}`} title={label}>
              <Icon size={20} weight="regular" aria-hidden="true" /><span>{label}</span>
            </NavLink>
          ))}
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
            <MagnifyingGlass size={20} /><input autoFocus value={searchValue} onChange={(event) => setSearchValue(event.target.value)} placeholder="Firma, proje veya malzeme ara" onKeyDown={(event) => event.key === 'Escape' && closeSearch()} />
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
