import { useCallback, useEffect, useState } from 'react'
import { HashRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { DashboardPage, MaterialsPage, PurchaseSheet, PurchasesPage, SettingsPage, SuppliersPage } from './pages'
import { ReportsPage } from './reports'
import { PersonnelPage } from './operations'
import { InsightsPage } from './insights'
import { WorkTrackingPage } from './workTracking'
import { ProjectCenterPage } from './projectCenter'
import { MiniProjectBar } from './projectBar'

function AppContent() {
  const [purchaseOpen, setPurchaseOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const openPurchase = useCallback(() => setPurchaseOpen(true), [])
  const closePurchase = useCallback(() => setPurchaseOpen(false), [])

  useEffect(() => window.ksDesktop?.app.onNavigate((route) => navigate(route)), [navigate])

  if (location.pathname === '/mini-bar') return <MiniProjectBar />

  return (
    <AppShell onQuickPurchase={openPurchase}>
      <Routes>
        <Route path="/" element={<DashboardPage onNewPurchase={openPurchase} />} />
        <Route path="/is-takibi" element={<WorkTrackingPage />} />
        <Route path="/projeler" element={<ProjectCenterPage />} />
        <Route path="/satin-almalar" element={<PurchasesPage onNewPurchase={openPurchase} />} />
        <Route path="/firmalar" element={<SuppliersPage />} />
        <Route path="/malzemeler" element={<MaterialsPage />} />
        <Route path="/personel" element={<PersonnelPage />} />
        <Route path="/raporlar" element={<ReportsPage />} />
        <Route path="/akilli-ongoruler" element={<InsightsPage />} />
        <Route path="/ayarlar" element={<SettingsPage />} />
      </Routes>
      <PurchaseSheet open={purchaseOpen} onClose={closePurchase} />
    </AppShell>
  )
}

export default function App() {
  return <HashRouter><AppContent /></HashRouter>
}
