import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Receipt, ShieldCheck } from '@phosphor-icons/react'
import { apiList, apiRequest, formatMoney, makeIdempotencyKey, toKurus } from './lib/api'
import type { DesktopInfo, Material, Purchase, TrackingMode, UpdateState } from './lib/types'
import { Button, ConfidenceBadge, EmptyState, ErrorState, Field, LoadingRows, PageHeader, SelectInput, SideSheet, StatusBanner, TextInput } from './components/ui'
import { queryKeys as q, useCoreData } from './hooks/useCoreData'
import { BackupCenter } from './components/BackupCenter'
import { OperationalSettings } from './settingsExtra'
import { DataTools } from './dataTools'
import { CardReaderSettings } from './cardReader'
import { MaterialTracking } from './materialTracking'

const todayIso = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/Istanbul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date())

function DataTable({ children, label }: { children: React.ReactNode; label: string }) {
  return <div className="table-wrap"><table aria-label={label}>{children}</table></div>
}

function QueryState({ query, empty, children }: { query: { isLoading: boolean; error: unknown; refetch: () => unknown; data?: unknown[] }; empty: React.ReactNode; children: React.ReactNode }) {
  if (query.isLoading) return <LoadingRows />
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  if (!query.data?.length) return <>{empty}</>
  return <>{children}</>
}

export function MaterialsPage() {
  const client = useQueryClient(); const materials = useQuery({ queryKey: q.materials, queryFn: () => apiList<Material>('/api/v1/materials') })
  const [open, setOpen] = useState(false); const [name, setName] = useState(''); const [unit, setUnit] = useState('adet'); const [mode, setMode] = useState<TrackingMode>('estimated')
  const mutation = useMutation({ mutationFn: () => apiRequest<Material>('/api/v1/materials', { method: 'POST', body: { name, default_unit: unit, tracking_mode: mode, note: null } }), onSuccess: () => { client.invalidateQueries({ queryKey: q.materials }); setOpen(false) } })
  return <div className="page"><PageHeader title="Malzemeler" description="Kesin stok iddiası olmadan, kayıt güvenini görünür tutun." action={<Button variant="primary" onClick={() => setOpen(true)}><Plus size={18} />Malzeme ekle</Button>} />
    <StatusBanner>Malzeme miktarları kayıt şekline göre kesin veya tahmini olabilir. Sistem eksi miktarda kaydı engellemez; uyarı üretir.</StatusBanner>
    <QueryState query={materials} empty={<EmptyState title="Henüz malzeme yok" description="Takibini yapmak istediğiniz ilk malzemeyi ekleyin." action={<Button onClick={() => setOpen(true)}>Malzeme ekle</Button>} />}>
      <DataTable label="Malzemeler"><thead><tr><th>Malzeme</th><th>Birim</th><th>Takip şekli</th><th>Durum</th></tr></thead><tbody>{materials.data?.map((item) => <tr key={item.id}><td><strong>{item.name}</strong></td><td>{item.default_unit}</td><td><ConfidenceBadge mode={item.tracking_mode} /></td><td>Aktif</td></tr>)}</tbody></DataTable>
    </QueryState>
    {materials.data?.length ? <MaterialTracking materials={materials.data} /> : null}
    <SideSheet title="Yeni malzeme" open={open} onClose={() => setOpen(false)} footer={<><Button onClick={() => setOpen(false)}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Malzeme adı"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field><Field label="Varsayılan birim"><SelectInput value={unit} onChange={(e) => setUnit(e.target.value)}><option>adet</option><option>kg</option><option>metre</option><option>m²</option><option>levha</option><option>kutu</option><option>litre</option><option>paket</option></SelectInput></Field><Field label="Takip şekli"><SelectInput value={mode} onChange={(e) => setMode(e.target.value as TrackingMode)}><option value="exact">Kesin</option><option value="estimated">Yaklaşık</option><option value="value_only">Yalnız tutar</option></SelectInput></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
  </div>
}

export function SettingsPage() {
  const info = useQuery<DesktopInfo>({ queryKey: ['desktop-info'], queryFn: async () => { if (!window.ksDesktop) throw new Error('Masaüstü köprüsü bulunamadı.'); return window.ksDesktop.app.getInfo() } })
  const [update, setUpdate] = useState<UpdateState | null>(null)
  const [updateBusy, setUpdateBusy] = useState(false)
  useEffect(() => { window.ksDesktop?.app.getUpdateState().then(setUpdate).catch(() => {}) }, [])
  const health = useQuery({ queryKey: ['health'], queryFn: () => apiRequest<{ status: string; service: string }>('/api/v1/health') })
  async function runUpdate(action: 'checkForUpdates' | 'downloadUpdate') {
    if (!window.ksDesktop) return
    setUpdateBusy(true)
    try {
      const result = await window.ksDesktop.app[action]()
      setUpdate(result)
      if (action === 'downloadUpdate') {
        const timer = window.setInterval(() => window.ksDesktop?.app.getUpdateState().then((state) => {
          setUpdate(state)
          if (state.status !== 'downloading') window.clearInterval(timer)
        }), 500)
      }
    } finally { setUpdateBusy(false) }
  }
  async function installUpdate() { if (await window.ksDesktop?.app.installUpdate()) return }
  return <div className="page"><PageHeader title="Ayarlar" description="Yerel uygulama, veri dizini ve sürüm bilgilerini görüntüleyin." />
    <div className="settings-grid"><section className="panel"><div className="panel__header"><h2>Uygulama</h2></div>{info.isLoading ? <LoadingRows count={2} /> : info.error ? <ErrorState error={info.error} /> : <dl className="definition-list"><div><dt>Sürüm</dt><dd>{info.data?.version}</dd></div><div><dt>Çalışma biçimi</dt><dd>{info.data?.packaged ? 'Kurulu masaüstü uygulaması' : 'Geliştirme ortamı'}</dd></div><div><dt>Veri dizini</dt><dd className="path-value">{info.data?.dataDirectory}</dd></div></dl>}</section>
      <section className="panel"><div className="panel__header"><h2>Yerel çekirdek</h2></div>{health.isLoading ? <LoadingRows count={2} /> : health.error ? <ErrorState error={health.error} onRetry={() => health.refetch()} /> : <div className="health-ok"><ShieldCheck size={28} /><div><strong>Çalışıyor</strong><span>Veri hizmeti bu bilgisayarda erişilebilir.</span></div></div>}</section>
      <section className="panel"><div className="panel__header"><h2>Uygulama güncellemesi</h2></div><p>{update?.message || 'Yeni sürümleri GitHub üzerinden denetleyebilirsiniz.'}</p>{update?.version && update.status !== 'current' && <p><strong>Sürüm {update.version}</strong></p>}<div className="p0-controls"><Button onClick={() => runUpdate('checkForUpdates')} loading={updateBusy || update?.status === 'checking' || update?.status === 'downloading'} disabled={update?.status === 'unavailable'}>Güncelleme denetle</Button>{update?.status === 'available' && <Button variant="primary" onClick={() => runUpdate('downloadUpdate')} loading={updateBusy}>İndir</Button>}{update?.status === 'downloaded' && <Button variant="primary" onClick={installUpdate}>Yükle ve yeniden başlat</Button>}</div></section>
      <section className="panel panel--wide"><BackupCenter /></section><DataTools /><CardReaderSettings /></div><OperationalSettings />
  </div>
}

export function PurchaseSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient(); const data = useCoreData()
  const [supplierId, setSupplierId] = useState(''); const [materialId, setMaterialId] = useState(''); const [projectId, setProjectId] = useState(''); const [date, setDate] = useState(todayIso); const [quantity, setQuantity] = useState(''); const [unit, setUnit] = useState('adet'); const [total, setTotal] = useState(''); const [paid, setPaid] = useState(''); const [dueDate, setDueDate] = useState(''); const [description, setDescription] = useState(''); const [lifecycle, setLifecycle] = useState<'planned' | 'ordered' | 'received'>('planned')
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) { setWasOpen(open); if (open) setDate(todayIso()) }
  const totalKurus = toKurus(total); const paidKurus = toKurus(paid); const error = paidKurus > totalKurus ? 'Ödenen tutar toplam tutarı aşamaz.' : undefined; const dueError = dueDate && dueDate < date ? 'Vade tarihi satın alma tarihinden önce olamaz.' : undefined
  const mutation = useMutation({ mutationFn: () => apiRequest<Purchase>('/api/v1/purchases', { method: 'POST', body: { supplier_id: supplierId, material_id: materialId, project_id: projectId || null, purchase_date: date, due_date: dueDate || null, quantity: quantity ? Number(quantity.replace(',', '.')) : null, unit: quantity ? unit : null, unit_price_kurus: null, total_kurus: totalKurus, paid_kurus: paidKurus, description: description || null, lifecycle_state: lifecycle, idempotency_key: makeIdempotencyKey('purchase') } }), onSuccess: () => { client.invalidateQueries({ queryKey: q.purchases }); client.invalidateQueries({ queryKey: q.payments }); client.invalidateQueries({ queryKey: ['report'] }); setDueDate(''); onClose() } })
  function submit(event: FormEvent) { event.preventDefault(); if (!error && !dueError) mutation.mutate() }
  return <SideSheet title="Yeni satın alma" description="KDV ve fatura ayrıntısı olmadan temel alış kaydı." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!supplierId || !materialId || !total || Boolean(error) || Boolean(dueError)} onClick={() => !error && !dueError && mutation.mutate()}><Receipt size={18} />Satın almayı kaydet</Button></>}>
    <form className="form-stack" onSubmit={submit}><Field label="Satın alma durumu"><SelectInput value={lifecycle} onChange={(e) => setLifecycle(e.target.value as typeof lifecycle)}><option value="planned">Planlandı</option><option value="ordered">Sipariş verildi</option><option value="received">Teslim alındı</option></SelectInput></Field><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Firma"><SelectInput value={supplierId} onChange={(e) => setSupplierId(e.target.value)}><option value="">Firma seçin</option>{data.suppliers.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field><Field label="Malzeme / alınan şey"><SelectInput value={materialId} onChange={(e) => { setMaterialId(e.target.value); const material = data.materials.data?.find((x) => x.id === e.target.value); if (material) setUnit(material.default_unit) }}><option value="">Malzeme seçin</option>{data.materials.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field><div className="form-grid"><Field label="Miktar" hint="Bilinmiyorsa boş bırakın"><TextInput inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></Field><Field label="Birim"><SelectInput value={unit} onChange={(e) => setUnit(e.target.value)} disabled={!quantity}><option>adet</option><option>kg</option><option>metre</option><option>m²</option><option>levha</option><option>kutu</option><option>litre</option><option>paket</option></SelectInput></Field></div><Field label="Toplam tutar"><TextInput inputMode="decimal" placeholder="0,00" value={total} onChange={(e) => setTotal(e.target.value)} /></Field><Field label="Ödenen tutar" error={error}><TextInput inputMode="decimal" placeholder="0,00" value={paid} onChange={(e) => setPaid(e.target.value)} /></Field><div className="calculation"><span>Kalan borç</span><strong>{formatMoney(Math.max(0, totalKurus - paidKurus))}</strong></div><Field label="Vade tarihi" hint="Kalan borç ne zaman ödenecek? İsteğe bağlı" error={dueError}><TextInput type="date" value={dueDate} min={date} onChange={(e) => setDueDate(e.target.value)} /></Field><Field label="İlgili proje" hint="İsteğe bağlı"><SelectInput value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Genel satın alma</option>{data.projects.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field><Field label="Açıklama" hint="İsteğe bağlı"><textarea className="input textarea" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</form>
  </SideSheet>
}
