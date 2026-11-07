import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiList, apiRequest, toKurus } from './lib/api'
import type { Material, Project } from './lib/types'
import { Button, Field, SelectInput, TextInput } from './components/ui'

type Balance = { material_id: string; estimated_quantity: number | string | null; unit: string; warning: string | null }
type MovementType = 'use' | 'waste' | 'return' | 'adjustment'

export function MaterialTracking({ materials }: { materials: Material[] }) {
  const client = useQueryClient()
  const [chosenId, setChosenId] = useState('')
  const [movementType, setMovementType] = useState<MovementType>('use')
  const [movementDate, setMovementDate] = useState(() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()))
  const [quantity, setQuantity] = useState('')
  const [amount, setAmount] = useState('')
  const [projectId, setProjectId] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const materialId = materials.some((item) => item.id === chosenId) ? chosenId : materials[0]?.id ?? ''
  const material = materials.find((item) => item.id === materialId)
  const balance = useQuery({ queryKey: ['material-balance', materialId], enabled: !!materialId, queryFn: () => apiRequest<Balance>(`/api/v1/materials/${materialId}/balance`) })
  const projects = useQuery({ queryKey: ['material-projects'], queryFn: () => apiList<Project>('/api/v1/projects') })
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiRequest('/api/v1/material-movements', { method: 'POST', body }),
    onSuccess: async () => {
      setQuantity(''); setAmount(''); setNote(''); setError(''); setNotice('Malzeme hareketi kaydedildi.')
      await Promise.all([client.invalidateQueries({ queryKey: ['material-balance', materialId] }), client.invalidateQueries({ queryKey: ['report'] })])
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'Hareket kaydedilemedi.'),
  })

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!material) return
    const valueOnly = material.tracking_mode === 'value_only'
    const normalized = quantity.trim().replace(',', '.')
    if (!valueOnly && (!/^\d+(\.\d{1,3})?$/.test(normalized) || Number(normalized) <= 0)) {
      setError('Sıfırdan büyük, en fazla üç ondalıklı bir miktar girin.'); return
    }
    const amountKurus = amount.trim() ? toKurus(amount) : null
    if (valueOnly && (!amountKurus || amountKurus <= 0)) { setError('Tutar girin.'); return }
    if (amount.trim() && (!amountKurus || amountKurus <= 0)) { setError('Geçerli bir tutar girin.'); return }
    setError(''); setNotice('')
    save.mutate({ material_id: material.id, project_id: projectId || null, movement_date: movementDate, movement_type: movementType, quantity: valueOnly ? null : normalized, unit: valueOnly ? null : material.default_unit, amount_kurus: amountKurus, confidence: material.tracking_mode, note: note || null })
  }

  if (!material) return null
  return <section className="panel p0-section" aria-label="Malzeme takibi">
    <h2>Malzeme kullanımı ve bakiye</h2>
    <div className="p0-controls"><Field label="Malzeme"><SelectInput value={materialId} onChange={(event) => { setChosenId(event.target.value); setQuantity(''); setAmount(''); setError(''); setNotice('') }}>{materials.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field>
      <div><span>Tahmini bakiye</span><strong>{balance.isLoading ? 'Yükleniyor…' : balance.error ? 'Alınamadı' : balance.data?.estimated_quantity == null ? 'Yalnız tutar' : `${balance.data.estimated_quantity} ${balance.data.unit}`}</strong></div></div>
    {balance.data?.warning && <p role="alert">{balance.data.warning}</p>}
    <form className="p0-controls" onSubmit={submit}>
      <Field label="Hareket"><SelectInput value={movementType} onChange={(event) => setMovementType(event.target.value as MovementType)}><option value="use">Kullanım</option><option value="waste">Fire</option><option value="return">İade / giriş</option><option value="adjustment">Sayım artışı</option></SelectInput></Field>
      <Field label="Tarih"><TextInput type="date" value={movementDate} onChange={(event) => setMovementDate(event.target.value)} required /></Field>
      {material.tracking_mode !== 'value_only' && <Field label={`Miktar (${material.default_unit})`}><TextInput inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} required /></Field>}
      <Field label={material.tracking_mode === 'value_only' ? 'Tutar (₺)' : 'Tutar (₺, isteğe bağlı)'}><TextInput inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required={material.tracking_mode === 'value_only'} /></Field>
      <Field label="Proje"><SelectInput value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Projesiz</option>{projects.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectInput></Field>
      <Field label="Not"><TextInput value={note} onChange={(event) => setNote(event.target.value)} /></Field>
      <Button variant="primary" loading={save.isPending}>Hareketi kaydet</Button>
    </form>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>
}
