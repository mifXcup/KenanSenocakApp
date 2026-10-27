import { useCallback, useState } from 'react'
import { HashRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { DashboardPage, MaterialsPage, ProjectsPage, PurchaseSheet, PurchasesPage, SettingsPage, SuppliersPage } from './pages'
import { ReportsPage } from './reports'
import { PersonnelPage } from './operations'
import { InsightsPage } from './insights'
import { WorkTrackingPage } from './workTracking'

function AppContent() {
  const [purchaseOpen, setPurchaseOpen] = useState(false)
  const openPurchase = useCallback(() => setPurchaseOpen(true), [])
  const closePurchase = useCallback(() => setPurchaseOpen(false), [])

  return (
    <AppShell onQuickPurchase={openPurchase}>
      <Routes>
        <Route path="/" element={<DashboardPage onNewPurchase={openPurchase} />} />
        <Route path="/is-takibi" element={<WorkTrackingPage />} />
        <Route path="/projeler" element={<ProjectsPage />} />
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
