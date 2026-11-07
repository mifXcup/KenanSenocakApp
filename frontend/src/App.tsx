import { Component, lazy, Suspense, useCallback, useEffect, useState, type ErrorInfo, type ReactNode } from 'react'
import { HashRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { MaterialsPage, PurchaseSheet, SettingsPage } from './pages'
import { MiniProjectBar } from './projectBar'
const ReportCenterPage = lazy(() => import('./reportCenter').then((m) => ({ default: m.ReportCenterPage })))
const PersonnelPage = lazy(() => import('./operations').then((m) => ({ default: m.PersonnelPage })))
const InsightsPage = lazy(() => import('./insights').then((m) => ({ default: m.InsightsPage })))
const ProjectCenterPage = lazy(() => import('./projectCenter').then((m) => ({ default: m.ProjectCenterPage })))
const AttendancePage = lazy(() => import('./p0Pages').then((m) => ({ default: m.AttendancePage })))
const CalendarPage = lazy(() => import('./p0Pages').then((m) => ({ default: m.CalendarPage })))
const CustomersPage = lazy(() => import('./p0Pages').then((m) => ({ default: m.CustomersPage })))
const TodayPage = lazy(() => import('./p0Pages').then((m) => ({ default: m.TodayPage })))
const ProfitabilityPage = lazy(() => import('./profitability').then((m) => ({ default: m.ProfitabilityPage })))
const PayrollPeriodsPage = lazy(() => import('./payrollPeriods').then((m) => ({ default: m.PayrollPeriodsPage })))
const PurchasingPage = lazy(() => import('./supplierPurchasing').then((m) => ({ default: m.PurchasingPage })))
const SupplierLedgerPage = lazy(() => import('./supplierPurchasing').then((m) => ({ default: m.SupplierLedgerPage })))

class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Sayfa yükleme hatası:', error, info)
  }

  render() {
    if (this.state.failed) {
      return <div className="page"><section className="status-panel status-panel--error" role="alert"><div><strong>Bu ekran açılamadı</strong><p>Beklenmeyen bir veri veya yükleme hatası oluştu. Ana sayfaya dönüp tekrar deneyin.</p></div><button className="button button--secondary" onClick={() => { window.location.hash = '#/' }}>Ana sayfaya dön</button></section></div>
    }
    return this.props.children
  }
}

function AppContent() {
  const [purchaseOpen, setPurchaseOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const openPurchase = useCallback(() => setPurchaseOpen(true), [])
  const closePurchase = useCallback(() => setPurchaseOpen(false), [])

  useEffect(() => window.ksDesktop?.app.onNavigate((route) => navigate(route)), [navigate])
  // Pencere yeni açılırken gelen yönlendirme (bildirim, mini bar) sayfa hazır olunca bir kez alınır.
  useEffect(() => {
    void window.ksDesktop?.app.takePendingRoute?.().then((route) => { if (route) navigate(route) })
  }, [navigate])

  if (location.pathname === '/mini-bar') return <MiniProjectBar />

  return (
    <AppShell onQuickPurchase={openPurchase}>
      <RouteErrorBoundary key={location.pathname}><Suspense fallback={<div className="page" role="status">Yükleniyor…</div>}><Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/is-takibi" element={<Navigate to="/projeler" replace />} />
        <Route path="/takvim" element={<CalendarPage />} />
        <Route path="/projeler" element={<ProjectCenterPage />} />
        <Route path="/proje-karliligi" element={<ProfitabilityPage />} />
        <Route path="/musteriler" element={<CustomersPage />} />
        <Route path="/satin-almalar" element={<PurchasingPage onNewPurchase={openPurchase} />} />
        <Route path="/firmalar" element={<SupplierLedgerPage />} />
        <Route path="/malzemeler" element={<MaterialsPage />} />
        <Route path="/personel" element={<PersonnelPage />} />
        <Route path="/puantaj-izin" element={<AttendancePage />} />
        <Route path="/maas-donemleri" element={<PayrollPeriodsPage />} />
        <Route path="/raporlar" element={<ReportCenterPage />} />
        <Route path="/akilli-ongoruler" element={<InsightsPage />} />
        <Route path="/ayarlar" element={<SettingsPage />} />
      </Routes></Suspense></RouteErrorBoundary>
      <PurchaseSheet open={purchaseOpen} onClose={closePurchase} />
    </AppShell>
  )
}

export default function App() {
  return <HashRouter><AppContent /></HashRouter>
}
