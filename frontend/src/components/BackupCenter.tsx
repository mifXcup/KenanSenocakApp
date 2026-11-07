import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowClockwise, CheckCircle, Database, ShieldCheck, WarningCircle } from '@phosphor-icons/react'
import { backupApi, backupIntegrityLabel, backupReasonLabel, formatFileSize } from '../lib/backup'
import type { BackupRecord } from '../lib/types'
import { queryKeys } from '../hooks/useCoreData'
import { Button, EmptyState, ErrorState, LoadingRows, Modal, StatusBanner } from './ui'

const formatDateTime = (value: string | null) => value
  ? new Intl.DateTimeFormat('tr-TR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : 'Henüz yok'

export function BackupCenter() {
  const client = useQueryClient()
  const [selected, setSelected] = useState<BackupRecord | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [transferBusy, setTransferBusy] = useState(false)
  const status = useQuery({ queryKey: queryKeys.backupStatus, queryFn: backupApi.status })
  const backups = useQuery({ queryKey: queryKeys.backups, queryFn: backupApi.list })

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.backupStatus }),
      client.invalidateQueries({ queryKey: queryKeys.backups }),
    ])
  }

  const create = useMutation({
    mutationFn: backupApi.create,
    onSuccess: async (record) => { setNotice(`${formatDateTime(record.created_at)} tarihli yedek oluşturuldu.`); await refresh() },
  })
  const verify = useMutation({
    mutationFn: backupApi.verify,
    onSuccess: async (result) => { setNotice(`${formatDateTime(result.created_at)} tarihli yedeğin bütünlüğü doğrulandı.`); await refresh() },
  })
  const restore = useMutation({
    mutationFn: backupApi.restore,
    onSuccess: async (result) => {
      setSelected(null)
      setNotice(`Veriler ${formatDateTime(result.restored_backup.created_at)} tarihli yedekten geri yüklendi.`)
      if (result.restart_required) {
        if (!window.ksDesktop) throw new Error('Uygulama yeniden başlatma köprüsü bulunamadı.')
        await window.ksDesktop.app.relaunch()
      } else {
        await refresh()
      }
    },
  })

  const error = status.error ?? backups.error ?? create.error ?? verify.error ?? restore.error

  async function importBackup() {
    if (!window.ksDesktop) return
    setTransferBusy(true)
    try {
      const result = await window.ksDesktop.api.importBackup()
      if (result.status === 'imported') { setNotice('Yedek aktarıldı ve doğrulandı. Geri yüklemek için listeden seçin.'); await refresh() }
      else if (result.status === 'error') setNotice(result.message || 'Yedek aktarılamadı.')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'Yedek aktarılamadı.') }
    finally { setTransferBusy(false) }
  }

  async function exportBackup(backupId: string) {
    if (!window.ksDesktop) return
    setTransferBusy(true)
    try {
      const result = await window.ksDesktop.api.exportBackup(backupId)
      if (result.status === 'saved') setNotice('Yedek dosyası kaydedildi. Ayrı bir yerde saklayın.')
      else if (result.status === 'error') setNotice(result.message || 'Yedek kaydedilemedi.')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'Yedek kaydedilemedi.') }
    finally { setTransferBusy(false) }
  }

  return (
    <section className="backup-center" aria-labelledby="backup-title">
      <div className="backup-center__header">
        <div><h2 id="backup-title">Yedekleme merkezi</h2><p>Yerel verinin güvenli kopyalarını oluşturun, doğrulayın ve gerektiğinde geri yükleyin.</p></div>
        <div className="p0-controls"><Button loading={transferBusy} onClick={importBackup}>Dosyadan yedek yükle</Button><Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}><Database size={18} />Şimdi yedekle</Button></div>
      </div>

      {notice && <StatusBanner>{notice}</StatusBanner>}
      {error && <ErrorState error={error} onRetry={() => refresh()} />}

      {status.isLoading ? <LoadingRows count={2} /> : status.data && (
        <div className="backup-summary">
          <div><span>Son başarılı yedek</span><strong>{formatDateTime(status.data.latest_backup?.created_at ?? null)}</strong></div>
          <div><span>Otomatik yedek</span><strong>{status.data.healthy ? 'Sağlıklı' : 'Kontrol gerekli'}</strong></div>
          <div><span>Son otomatik yedek</span><strong>{formatDateTime(status.data.latest_automatic?.created_at ?? null)}</strong></div>
          <div><span>Toplam yedek</span><strong>{status.data.backup_count}</strong></div>
          <div className="backup-summary__path"><span>Otomatik saklama</span><strong>Son {status.data.automatic_retention} otomatik yedek korunur{status.data.in_progress ? ' · Yedekleme sürüyor' : ''}</strong>{status.data.last_error && <small>{status.data.last_error}</small>}</div>
        </div>
      )}

      <div className="backup-list-header"><h3>Yedek geçmişi</h3><span>Geri yüklemeden önce bütünlüğü doğrulayın.</span></div>
      {backups.isLoading ? <LoadingRows count={3} /> : !backups.data?.length ? (
        <EmptyState title="Henüz yedek yok" description="İlk güvenli kopyayı oluşturmak için Şimdi yedekle seçeneğini kullanın." />
      ) : (
        <div className="backup-list" role="list">
          {backups.data.map((backup) => (
            <article className="backup-row" key={backup.backup_id} role="listitem">
              <div className="backup-row__icon backup-row__icon--valid" aria-hidden="true">
                <ShieldCheck size={21} />
              </div>
              <div className="backup-row__identity"><strong>{formatDateTime(backup.created_at)}</strong><span>{backupReasonLabel(backup.kind)} · Sürüm {backup.app_version}</span></div>
              <div><span className="badge badge--exact">{backupIntegrityLabel(backup.integrity)}</span></div>
              <div className="backup-row__size">{formatFileSize(backup.size_bytes)}</div>
              <div className="backup-row__actions">
                <Button disabled={transferBusy} onClick={() => exportBackup(backup.backup_id)}>Dosyaya kaydet</Button>
                <Button loading={verify.isPending && verify.variables === backup.backup_id} onClick={() => verify.mutate(backup.backup_id)}><CheckCircle size={17} />Doğrula</Button>
                <Button variant="quiet" onClick={() => setSelected(backup)}><ArrowClockwise size={17} />Geri yükle</Button>
              </div>
            </article>
          ))}
        </div>
      )}

      <Modal
        title="Yedeği geri yükle"
        description="Mevcut veriler seçilen yedek tarihindeki duruma dönecek."
        open={Boolean(selected)}
        onClose={() => !restore.isPending && setSelected(null)}
        footer={<><Button disabled={restore.isPending} onClick={() => setSelected(null)}>Vazgeç</Button><Button variant="danger" loading={restore.isPending} onClick={() => selected && restore.mutate(selected.backup_id)}>Güvenlik yedeğini al ve geri yükle</Button></>}
      >
        {selected && <div className="restore-impact">
          <dl><div><dt>Yedek tarihi</dt><dd>{formatDateTime(selected.created_at)}</dd></div><div><dt>Dosya boyutu</dt><dd>{formatFileSize(selected.size_bytes)}</dd></div><div><dt>Bütünlük</dt><dd>{backupIntegrityLabel(selected.integrity)}</dd></div></dl>
          <div className="restore-warning"><WarningCircle size={22} /><p><strong>Bu işlem mevcut veriyi değiştirir.</strong><span>Geri yüklemeden hemen önce mevcut veritabanının ayrı bir güvenlik yedeği otomatik oluşturulur. İşlem tamamlandığında uygulama yeniden başlatılabilir.</span></p></div>
        </div>}
      </Modal>
    </section>
  )
}
