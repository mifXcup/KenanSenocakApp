# P0 Ortak Geliştirme Planı — Claude + Codex

## Hedef

Kenan Şenocak Yönetim'i kurulumdan önce proje kârlılığı, müşteri alacakları, tedarikçi borçları, personel-puantaj-izin-maaş ve birleşik takvim alanlarında gerçek kullanıma hazır hale getirmek.

Uygulama tam muhasebe programı değildir. KDV, e-Fatura, SGK, vergi ve resmî bordro kapsam dışıdır. Finansal yanlışlar silme yerine ters kayıtla düzeltilir. Stok kesinliği zorunlu değildir.

## Dal ve worktree düzeni

- Ana referans: Bu koordinasyon dosyalarını içeren güncel `main`
- Claude dalı: `claude/p0-domain-core`
- Claude worktree: `C:\Users\Emir\Desktop\KS-claude-p0`
- Codex dalı: `codex/p0-desktop-client`
- Codex çalışma alanı: `C:\Users\Emir\Desktop\KŞ`

Claude worktree oluşturmadan önce `main` üzerinde bu dosyanın bulunduğunu doğrular. Claude kendi worktree'si dışında değişiklik yapmaz. Codex Claude tamamlanana kadar `backend/**` dosyalarına dokunmaz. Claude tamamlanınca dalı Codex dalına birleştirilir; istemci entegrasyonu ve tüm paket testi bundan sonra tamamlanır.

## Dosya sahipliği

### Claude

- `backend/**`
- Backend Alembic revizyonları
- `docs/api-contract.md`
- `docs/data-model.md`
- Backend davranışıyla ilgili `docs/architecture.md` bölümleri

### Codex

- `frontend/**`
- `desktop/**`
- Kök `package.json` ve istemci paketleme ayarları
- `docs/ui-flows.md`
- Windows bildirimleri ve istemci derin bağları

### Birleştirme sırasında Codex

- `README.md`
- Sürüm numarası
- Birleşik migration doğrulaması
- Installer ve paketli sidecar smoke testi

## API sözleşmesi

Claude endpoint, enum, durum geçişi ve hata kodlarını `docs/api-contract.md` içinde kesinleştirir. Codex istemci tiplerini bu sözleşmeden üretir. Alan adları entegrasyon sonrası haber verilmeden değiştirilmez.

Yeni endpoint aileleri:

- `/customers`, `/customers/{id}/statement`, `/customers/{id}/aging`
- `/receivable-schedules`, `/customer-financial-movements`
- `/projects/{id}/budget-lines`, `/projects/{id}/change-orders`
- `/projects/{id}/profitability`, `/projects/{id}/cost-drilldown`
- `/leave-types`, `/leave-requests`, `/employees/{id}/leave-ledger`
- `/calendar/events`, `/reminders`, `/today`

## Teslim sırası

1. Claude WP-B1: müşteri cari ve proje finansı.
2. Claude WP-B2: izin, puantaj ve maaş güvenliği.
3. Claude WP-B3: takvim, Bugün ve hatırlatma API'leri.
4. Claude WP-B4: rapor, ML uyarlaması, migration, doküman ve backend kalite kapısı.
5. Codex WP-F1–F5: istemci yüzeyleri; backend sözleşmesi kesinleşen modüller sırayla entegre edilir.
6. Claude dalı Codex dalına birleştirilir.
7. Birleşik regresyon, eski veritabanı migration'ı, paketli uygulama ve installer testleri yapılır.
8. Tüm kapılar geçerse `main` birleştirmesi ve yeni kurulum paketi hazırlanır.

## Birleştirme kapısı

Claude teslimi için:

- Ruff temiz.
- Backend testleri tamamen geçer.
- Temiz veritabanı ve 0.3.0 örnek veritabanı `alembic upgrade head` geçer.
- Finansal ters kayıt, idempotency, dönem kilidi ve audit testleri vardır.
- Dal temizdir ve her iş paketi ayrı commit'tir.

Codex nihai teslimi için:

- Frontend lint, test ve build geçer.
- Backend regresyonu tekrar geçer.
- Takvim bildirimi mükerrer üretmez.
- Tüm finansal sayılardan kaynak kayda detay açılır.
- Paketli `ks-core.exe`, yeni ve 0.3.0 veritabanıyla smoke test geçer.
- NSIS installer üretilir ve temiz Windows kullanıcı akışı doğrulanır.

## Çakışma kuralları

- Claude frontend veya Electron dosyası değiştirmez.
- Codex entegrasyon öncesi backend davranışını değiştirmez.
- Ortak bir hata backend kontratından kaynaklanıyorsa düzeltme Claude dalına yapılır; istemci yorumuyla gizlenmez.
- Migration dosyaları yeniden adlandırılmaz veya silinmez; gerekirse merge revision kullanılır.
- Mevcut kullanıcı verisi korunur; yıkıcı migration kabul edilmez.
- Her iş paketi sonunda commit kimliği, test sonucu, açık risk ve sonraki pakete etkisi raporlanır.

