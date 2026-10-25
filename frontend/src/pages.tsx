import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ChartBar, Plus, Receipt, ShieldCheck } from '@phosphor-icons/react'
import { apiRequest, formatDate, formatMoney, makeIdempotencyKey, toKurus } from './lib/api'
import type { DesktopInfo, Material, Project, Purchase, Supplier, SupplierBalance, TrackingMode } from './lib/types'
import { Button, ConfidenceBadge, EmptyState, ErrorState, Field, LoadingRows, MoneyValue, PageHeader, SelectInput, SideSheet, StatusBanner, TextInput } from './components/ui'
import { queryKeys as q, useCoreData } from './hooks/useCoreData'
import { BackupCenter } from './components/BackupCenter'

const todayIso = new Intl.DateTimeFormat('en-CA', {
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

export function DashboardPage({ onNewPurchase }: { onNewPurchase: () => void }) {
  const data = useCoreData()
  const summary = useMemo(() => {
    const purchaseTotal = data.purchases.data?.reduce((sum, item) => sum + item.total_kurus, 0) ?? 0
    const paidTotal = data.payments.data?.filter((x) => x.status === 'active').reduce((sum, item) => sum + item.amount_kurus, 0) ?? 0
    return { purchaseTotal, paidTotal, debt: purchaseTotal - paidTotal }
  }, [data.purchases.data, data.payments.data])
  const loading = Object.values(data).some((item) => item.isLoading)
  const error = Object.values(data).find((item) => item.error)?.error

  return (
    <div className="page">
      <PageHeader title="Genel Bakış" description="Bugün karar gerektiren işletme durumunu tek yerde görün." action={<Button variant="primary" onClick={onNewPurchase}><Plus size={18} />Satın alma ekle</Button>} />
      {error && <ErrorState error={error} />}
      {loading ? <LoadingRows count={3} /> : data.purchases.data?.length === 0 && data.suppliers.data?.length === 0 ? (
        <EmptyState title="Henüz işletme kaydı yok" description="Firma, malzeme ve satın alma kayıtları eklendikçe borç ve maliyet özeti burada oluşur." action={<Button variant="primary" onClick={onNewPurchase}>İlk satın almayı ekle</Button>} />
      ) : (
        <>
          <section className="summary-band" aria-label="Finans özeti">
            <div className="summary-band__main"><span>Açık firma borcu</span><MoneyValue value={summary.debt} emphasis /><small>Kayıtlı satın alma ve ödemelere göre</small></div>
            <div className="summary-stat"><span>Toplam satın alma</span><MoneyValue value={summary.purchaseTotal} /></div>
            <div className="summary-stat"><span>Toplam ödeme</span><MoneyValue value={summary.paidTotal} /></div>
            <div className="summary-health"><ShieldCheck size={24} /><strong>Yerel veri</strong><span>Bu bilgisayarda korunuyor</span></div>
          </section>
          <div className="dashboard-grid">
            <section className="panel"><div className="panel__header"><h2>Son satın almalar</h2><a href="#/satin-almalar">Tümünü gör <ArrowRight size={16} /></a></div>
              {!data.purchases.data?.length ? <p className="muted">Henüz satın alma kaydı yok.</p> : <RecentPurchases purchases={data.purchases.data.slice(0, 6)} suppliers={data.suppliers.data ?? []} materials={data.materials.data ?? []} />}
            </section>
            <section className="panel panel--quiet"><div className="panel__header"><h2>Karar desteği</h2><ChartBar size={20} /></div><p className="muted">Tahmin için yeterli geçmiş yok. Sistem veri biriktikçe fiyat ve maliyet eğilimlerini burada açıklayacak.</p></section>
          </div>
        </>
      )}
    </div>
  )
}

function RecentPurchases({ purchases, suppliers, materials }: { purchases: Purchase[]; suppliers: Supplier[]; materials: Material[] }) {
  const supplier = Object.fromEntries(suppliers.map((x) => [x.id, x.name]))
  const material = Object.fromEntries(materials.map((x) => [x.id, x.name]))
  return <div className="activity-list">{purchases.map((item) => <div className="activity-row" key={item.id}><div><strong>{material[item.material_id] ?? 'Malzeme'}</strong><span>{supplier[item.supplier_id] ?? 'Firma'} · {formatDate(item.purchase_date)}</span></div><MoneyValue value={item.total_kurus} /></div>)}</div>
}

export function SuppliersPage() {
  const client = useQueryClient()
  const suppliers = useQuery({ queryKey: q.suppliers, queryFn: () => apiRequest<Supplier[]>('/api/v1/suppliers') })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiRequest<Supplier>('/api/v1/suppliers', { method: 'POST', body: { name, phone: phone || null, note: null } }),
    onSuccess: () => { client.invalidateQueries({ queryKey: q.suppliers }); setOpen(false); setName(''); setPhone('') },
  })
  return <div className="page"><PageHeader title="Firmalar" description="Alışlar, ödemeler ve kalan borcu firma bağlamında izleyin." action={<Button variant="primary" onClick={() => setOpen(true)}><Plus size={18} />Firma ekle</Button>} />
    <QueryState query={suppliers} empty={<EmptyState title="Henüz firma yok" description="İlk satın alma için çalıştığınız firmayı ekleyin." action={<Button onClick={() => setOpen(true)}>Firma ekle</Button>} />}>
      <DataTable label="Firmalar"><thead><tr><th>Firma</th><th>Telefon</th><th>Kayıt durumu</th><th>Oluşturma</th></tr></thead><tbody>{suppliers.data?.map((item) => <SupplierRow key={item.id} supplier={item} />)}</tbody></DataTable>
    </QueryState>
    <SideSheet title="Yeni firma" description="Yalnız iş için gerekli temel bilgileri girin." open={open} onClose={() => setOpen(false)} footer={<><Button onClick={() => setOpen(false)}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} onClick={() => mutation.mutate()}>Kaydet</Button></>}>
      <div className="form-stack"><Field label="Firma adı" error={mutation.error instanceof Error ? mutation.error.message : undefined}><TextInput value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field><Field label="Telefon" hint="İsteğe bağlı"><TextInput value={phone} onChange={(e) => setPhone(e.target.value)} /></Field></div>
    </SideSheet>
  </div>
}

function SupplierRow({ supplier }: { supplier: Supplier }) {
  const balance = useQuery({ queryKey: ['supplier-balance', supplier.id], queryFn: () => apiRequest<SupplierBalance>(`/api/v1/suppliers/${supplier.id}/balance`) })
  return <tr><td><strong>{supplier.name}</strong><small>{supplier.note}</small></td><td>{supplier.phone || 'Girilmedi'}</td><td>{balance.isLoading ? 'Hesaplanıyor' : balance.error ? 'Hesaplanamadı' : <MoneyValue value={balance.data?.remaining_kurus} />}</td><td>{new Intl.DateTimeFormat('tr-TR').format(new Date(supplier.created_at))}</td></tr>
}

export function PurchasesPage({ onNewPurchase }: { onNewPurchase: () => void }) {
  const data = useCoreData()
  const supplier = Object.fromEntries((data.suppliers.data ?? []).map((x) => [x.id, x.name]))
  const material = Object.fromEntries((data.materials.data ?? []).map((x) => [x.id, x.name]))
  const project = Object.fromEntries((data.projects.data ?? []).map((x) => [x.id, x.name]))
  return <div className="page"><PageHeader title="Satın Almalar" description="Ne aldığınızı, kimden aldığınızı ve projeye etkisini izleyin." action={<Button variant="primary" onClick={onNewPurchase}><Plus size={18} />Satın alma ekle</Button>} />
    <QueryState query={data.purchases} empty={<EmptyState title="Satın alma kaydı yok" description="KDV ve fatura ayrıntıları olmadan, yalnız operasyon için gereken alış bilgisini kaydedin." action={<Button onClick={onNewPurchase}>İlk kaydı ekle</Button>} />}>
      <DataTable label="Satın almalar"><thead><tr><th>Tarih</th><th>Firma</th><th>Malzeme</th><th className="number">Miktar</th><th className="number">Toplam</th><th>Vade</th><th>Proje</th><th>Durum</th></tr></thead><tbody>{data.purchases.data?.map((item) => <tr key={item.id}><td>{formatDate(item.purchase_date)}</td><td>{supplier[item.supplier_id] ?? 'Bilinmiyor'}</td><td>{material[item.material_id] ?? 'Bilinmiyor'}</td><td className="number">{item.quantity ? `${item.quantity} ${item.unit ?? ''}` : 'Yalnız tutar'}</td><td className="number"><MoneyValue value={item.total_kurus} /></td><td>{item.due_date ? formatDate(item.due_date) : "—"}</td><td>{item.project_id ? project[item.project_id] ?? 'Bilinmiyor' : 'Genel'}</td><td><span className="badge badge--neutral">Aktif</span></td></tr>)}</tbody></DataTable>
    </QueryState>
  </div>
}

export function ProjectsPage() {
  const client = useQueryClient(); const projects = useQuery({ queryKey: q.projects, queryFn: () => apiRequest<Project[]>('/api/v1/projects') })
  const [open, setOpen] = useState(false); const [name, setName] = useState(''); const [customer, setCustomer] = useState(''); const [contract, setContract] = useState(''); const [budget, setBudget] = useState('')
  const mutation = useMutation({ mutationFn: () => apiRequest<Project>('/api/v1/projects', { method: 'POST', body: { name, customer_name: customer, contract_amount_kurus: contract ? toKurus(contract) : null, budget_kurus: budget ? toKurus(budget) : null, note: null } }), onSuccess: () => { client.invalidateQueries({ queryKey: q.projects }); setOpen(false) } })
  return <div className="page"><PageHeader title="Projeler" description="Sözleşme, bütçe ve gerçekleşen maliyeti aynı bağlamda yönetin." action={<Button variant="primary" onClick={() => setOpen(true)}><Plus size={18} />Proje ekle</Button>} />
    <QueryState query={projects} empty={<EmptyState title="Henüz proje yok" description="İlk müşteri projesini ekleyerek maliyetleri bağlamaya başlayın." action={<Button onClick={() => setOpen(true)}>Proje ekle</Button>} />}>
      <div className="project-list">{projects.data?.map((item) => <article className="project-row" key={item.id}><div><strong>{item.name}</strong><span>{item.customer_name}</span></div><div><small>Sözleşme</small><MoneyValue value={item.contract_amount_kurus} /></div><div><small>Bütçe</small><MoneyValue value={item.budget_kurus} /></div><span className="badge badge--neutral">{item.project_state}</span></article>)}</div>
    </QueryState>
    <SideSheet title="Yeni proje" open={open} onClose={() => setOpen(false)} footer={<><Button onClick={() => setOpen(false)}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Proje adı"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field><Field label="Müşteri"><TextInput value={customer} onChange={(e) => setCustomer(e.target.value)} /></Field><Field label="Sözleşme bedeli"><TextInput inputMode="decimal" value={contract} onChange={(e) => setContract(e.target.value)} /></Field><Field label="Bütçe"><TextInput inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
  </div>
}

export function MaterialsPage() {
  const client = useQueryClient(); const materials = useQuery({ queryKey: q.materials, queryFn: () => apiRequest<Material[]>('/api/v1/materials') })
  const [open, setOpen] = useState(false); const [name, setName] = useState(''); const [unit, setUnit] = useState('adet'); const [mode, setMode] = useState<TrackingMode>('estimated')
  const mutation = useMutation({ mutationFn: () => apiRequest<Material>('/api/v1/materials', { method: 'POST', body: { name, default_unit: unit, tracking_mode: mode, note: null } }), onSuccess: () => { client.invalidateQueries({ queryKey: q.materials }); setOpen(false) } })
  return <div className="page"><PageHeader title="Malzemeler" description="Kesin stok iddiası olmadan, kayıt güvenini görünür tutun." action={<Button variant="primary" onClick={() => setOpen(true)}><Plus size={18} />Malzeme ekle</Button>} />
    <StatusBanner>Malzeme miktarları kayıt şekline göre kesin veya tahmini olabilir. Sistem eksi miktarda kaydı engellemez; uyarı üretir.</StatusBanner>
    <QueryState query={materials} empty={<EmptyState title="Henüz malzeme yok" description="Takibini yapmak istediğiniz ilk malzemeyi ekleyin." action={<Button onClick={() => setOpen(true)}>Malzeme ekle</Button>} />}>
      <DataTable label="Malzemeler"><thead><tr><th>Malzeme</th><th>Birim</th><th>Takip şekli</th><th>Durum</th></tr></thead><tbody>{materials.data?.map((item) => <tr key={item.id}><td><strong>{item.name}</strong></td><td>{item.default_unit}</td><td><ConfidenceBadge mode={item.tracking_mode} /></td><td>Aktif</td></tr>)}</tbody></DataTable>
    </QueryState>
    <SideSheet title="Yeni malzeme" open={open} onClose={() => setOpen(false)} footer={<><Button onClick={() => setOpen(false)}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} onClick={() => mutation.mutate()}>Kaydet</Button></>}><div className="form-stack"><Field label="Malzeme adı"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field><Field label="Varsayılan birim"><SelectInput value={unit} onChange={(e) => setUnit(e.target.value)}><option>adet</option><option>kg</option><option>metre</option><option>m²</option><option>levha</option><option>kutu</option><option>litre</option><option>paket</option></SelectInput></Field><Field label="Takip şekli"><SelectInput value={mode} onChange={(e) => setMode(e.target.value as TrackingMode)}><option value="exact">Kesin</option><option value="estimated">Yaklaşık</option><option value="value_only">Yalnız tutar</option></SelectInput></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</div></SideSheet>
  </div>
}

export function PersonnelPage() { return <div className="page"><PageHeader title="Personel ve Şantiye" description="İşçilik ve saha hareketleri için planlanan çalışma alanı." /><EmptyState title="Bu modül henüz etkin değil" description="Personel maliyeti ve şantiye ziyaretleri backend sözleşmesi tamamlandığında burada açılacak. Çalışmayan kontrol gösterilmiyor." /></div> }

export function SettingsPage() {
  const info = useQuery<DesktopInfo>({ queryKey: ['desktop-info'], queryFn: async () => { if (!window.ksDesktop) throw new Error('Masaüstü köprüsü bulunamadı.'); return window.ksDesktop.app.getInfo() } })
  const health = useQuery({ queryKey: ['health'], queryFn: () => apiRequest<{ status: string; service: string }>('/api/v1/health') })
  return <div className="page"><PageHeader title="Ayarlar" description="Yerel uygulama, veri dizini ve sürüm bilgilerini görüntüleyin." />
    <div className="settings-grid"><section className="panel"><div className="panel__header"><h2>Uygulama</h2></div>{info.isLoading ? <LoadingRows count={2} /> : info.error ? <ErrorState error={info.error} /> : <dl className="definition-list"><div><dt>Sürüm</dt><dd>{info.data?.version}</dd></div><div><dt>Çalışma biçimi</dt><dd>{info.data?.packaged ? 'Kurulu masaüstü uygulaması' : 'Geliştirme ortamı'}</dd></div><div><dt>Veri dizini</dt><dd className="path-value">{info.data?.dataDirectory}</dd></div></dl>}</section>
      <section className="panel"><div className="panel__header"><h2>Yerel çekirdek</h2></div>{health.isLoading ? <LoadingRows count={2} /> : health.error ? <ErrorState error={health.error} onRetry={() => health.refetch()} /> : <div className="health-ok"><ShieldCheck size={28} /><div><strong>Çalışıyor</strong><span>Veri hizmeti bu bilgisayarda erişilebilir.</span></div></div>}</section>
      <section className="panel panel--wide"><BackupCenter /></section></div>
  </div>
}

export function PurchaseSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient(); const data = useCoreData()
  const [supplierId, setSupplierId] = useState(''); const [materialId, setMaterialId] = useState(''); const [projectId, setProjectId] = useState(''); const [date, setDate] = useState(todayIso); const [quantity, setQuantity] = useState(''); const [unit, setUnit] = useState('adet'); const [total, setTotal] = useState(''); const [paid, setPaid] = useState(''); const [dueDate, setDueDate] = useState(''); const [description, setDescription] = useState('')
  const totalKurus = toKurus(total); const paidKurus = toKurus(paid); const error = paidKurus > totalKurus ? 'Ödenen tutar toplam tutarı aşamaz.' : undefined; const dueError = dueDate && dueDate < date ? 'Vade tarihi satın alma tarihinden önce olamaz.' : undefined
  const mutation = useMutation({ mutationFn: () => apiRequest<Purchase>('/api/v1/purchases', { method: 'POST', body: { supplier_id: supplierId, material_id: materialId, project_id: projectId || null, purchase_date: date, due_date: dueDate || null, quantity: quantity ? Number(quantity.replace(',', '.')) : null, unit: quantity ? unit : null, unit_price_kurus: null, total_kurus: totalKurus, paid_kurus: paidKurus, description: description || null, idempotency_key: makeIdempotencyKey('purchase') } }), onSuccess: () => { client.invalidateQueries({ queryKey: q.purchases }); client.invalidateQueries({ queryKey: q.payments }); client.invalidateQueries({ queryKey: q.reports }); setDueDate(''); onClose() } })
  function submit(event: FormEvent) { event.preventDefault(); if (!error && !dueError) mutation.mutate() }
  return <SideSheet title="Yeni satın alma" description="KDV ve fatura ayrıntısı olmadan temel alış kaydı." open={open} onClose={onClose} footer={<><Button onClick={onClose}>Vazgeç</Button><Button variant="primary" loading={mutation.isPending} disabled={!supplierId || !materialId || !total || Boolean(error) || Boolean(dueError)} onClick={() => !error && !dueError && mutation.mutate()}><Receipt size={18} />Satın almayı kaydet</Button></>}>
    <form className="form-stack" onSubmit={submit}><Field label="Tarih"><TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field><Field label="Firma"><SelectInput value={supplierId} onChange={(e) => setSupplierId(e.target.value)}><option value="">Firma seçin</option>{data.suppliers.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field><Field label="Malzeme / alınan şey"><SelectInput value={materialId} onChange={(e) => { setMaterialId(e.target.value); const material = data.materials.data?.find((x) => x.id === e.target.value); if (material) setUnit(material.default_unit) }}><option value="">Malzeme seçin</option>{data.materials.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field><div className="form-grid"><Field label="Miktar" hint="Bilinmiyorsa boş bırakın"><TextInput inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></Field><Field label="Birim"><SelectInput value={unit} onChange={(e) => setUnit(e.target.value)} disabled={!quantity}><option>adet</option><option>kg</option><option>metre</option><option>m²</option><option>levha</option><option>kutu</option><option>litre</option><option>paket</option></SelectInput></Field></div><Field label="Toplam tutar"><TextInput inputMode="decimal" placeholder="0,00" value={total} onChange={(e) => setTotal(e.target.value)} /></Field><Field label="Ödenen tutar" error={error}><TextInput inputMode="decimal" placeholder="0,00" value={paid} onChange={(e) => setPaid(e.target.value)} /></Field><div className="calculation"><span>Kalan borç</span><strong>{formatMoney(Math.max(0, totalKurus - paidKurus))}</strong></div><Field label="Vade tarihi" hint="Kalan borç ne zaman ödenecek? İsteğe bağlı" error={dueError}><TextInput type="date" value={dueDate} min={date} onChange={(e) => setDueDate(e.target.value)} /></Field><Field label="İlgili proje" hint="İsteğe bağlı"><SelectInput value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Genel satın alma</option>{data.projects.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</SelectInput></Field><Field label="Açıklama" hint="İsteğe bağlı"><textarea className="input textarea" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>{mutation.error && <span className="form-error">{mutation.error.message}</span>}</form>
  </SideSheet>
}
