import { useCallback, useEffect, useState } from 'react'
import { HashRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { DashboardPage, MaterialsPage, PurchaseSheet, PurchasesPage, SettingsPage, SuppliersPage } from './pages'
import { ReportsPage } from './reports'
import { PersonnelPage } from './operations'
import { InsightsPage } from './insights'
import { ProjectCenterPage } from './projectCenter'
import { MiniProjectBar } from './projectBar'
import { AttendanceFoundationPage, CalendarFoundationPage, CustomersFoundationPage, PayrollFoundationPage, ProfitabilityFoundationPage } from './foundationPages'

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
        <Route path="/is-takibi" element={<Navigate to="/projeler" replace />} />
        <Route path="/takvim" element={<CalendarFoundationPage />} />
        <Route path="/projeler" element={<ProjectCenterPage />} />
        <Route path="/proje-karliligi" element={<ProfitabilityFoundationPage />} />
        <Route path="/musteriler" element={<CustomersFoundationPage />} />
        <Route path="/satin-almalar" element={<PurchasesPage onNewPurchase={openPurchase} />} />
        <Route path="/firmalar" element={<SuppliersPage />} />
        <Route path="/malzemeler" element={<MaterialsPage />} />
        <Route path="/personel" element={<PersonnelPage />} />
        <Route path="/puantaj-izin" element={<AttendanceFoundationPage />} />
        <Route path="/maas-donemleri" element={<PayrollFoundationPage />} />
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
