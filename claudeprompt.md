# Claude'ye Verilecek Ana Prompt

Aşağıdaki metni Claude'ye tek parça olarak verin.

---

Sen Kenan Şenocak Yönetim projesinde yalnızca backend, veri modeli, migration, API, raporlama ve backend testlerinden sorumlusun. Codex aynı anda frontend ve Electron tarafında çalışacak. Dosya sahipliği sınırlarına kesinlikle uy.

## Başlangıç

Repo: `C:\Users\Emir\Desktop\KŞ`

Ana referans: `docs/P0_COLLABORATION_MASTER.md` dosyasını içeren güncel `main`.

Kendi ayrı worktree ve dalını oluştur:

```powershell
cd "C:\Users\Emir\Desktop\KŞ"
git worktree add -b claude/p0-domain-core "C:\Users\Emir\Desktop\KS-claude-p0" main
cd "C:\Users\Emir\Desktop\KS-claude-p0"
```

Eğer dal veya worktree zaten varsa yeniden oluşturma; mevcut olanı doğrula ve kullan. Worktree içinde `docs/P0_COLLABORATION_MASTER.md` yoksa yanlış tabandan başlamışsın; kod yazmadan dur ve raporla. Önce `README.md`, `docs/architecture.md`, `docs/api-contract.md`, `docs/data-model.md`, `docs/P0_COLLABORATION_MASTER.md`, modeller, servisler, migration zinciri ve test yardımcılarını oku.

## Kesin sınırlar

- Yalnızca `backend/**`, backend Alembic dosyaları, `docs/api-contract.md`, `docs/data-model.md` ve gerekli backend mimari notlarını değiştir.
- `frontend/**`, `desktop/**`, kök `package.json`, `docs/ui-flows.md` ve installer ayarlarına dokunma.
- KDV, iskonto, e-Fatura, e-Arşiv, SGK, vergi ve resmî bordro ekleme.
- Kusursuz stok bakiyesi veya depo zorunluluğu kurma.
- Finansal kayıtları fiziksel silme; ters kayıt ve audit kullan.
- SQLite, yerel tek kullanıcı ve mevcut sidecar güvenlik modelini koru.
- Para tutarlarını kuruş cinsinden tam sayı tut.
- Tarih ve hesaplamalar deterministik olsun; testlerde sistem saatine gizli bağımlılık olmasın.
- Mevcut 0.3.0 veritabanı kayıpsız migrate olmalı.

## WP-B1 — Müşteri cari ve proje finansı

Uygula:

1. Müşteri kartı: ad/unvan, telefon, adres, ilgili kişi, not, aktif/arşiv.
2. Mevcut `Project.customer_name` verisini migration sırasında normalize ederek müşteri kartına bağla. Aynı normalize ad için tek kart üret; orijinal metni veri kaybı olmadan koru.
3. Müşteri alacak planı: proje, başlık, tutar, vade, durum ve not.
4. Müşteri finans hareketleri: tahakkuk/açılış, tahsilat, iade, düzeltme ve reversal. Kısmi tahsilat ve idempotency destekle.
5. Müşteri ekstresi, yürüyen bakiye, kalan alacak ve yaşlandırma.
6. Proje bütçe satırları: malzeme, işçilik, nakliye, montaj, taşeron, şantiye, fire/yeniden işleme, diğer.
7. İlk ve revize bütçeyi koru; revizyonlar audit edilebilir olsun.
8. Proje kapsam/bedel değişikliği: taslak, onaylı, reddedildi, iptal. Yalnızca onaylı değişiklik revize sözleşme bedeline girsin.
9. Satın alma yaşam döngüsü: planlandı, sipariş verildi, kısmen teslim, teslim edildi, iptal. Eski satın almalar `received` kabul edilsin.
10. Taahhüt, gerçekleşen, kalan tahmin, tahmini bitş maliyeti, tahmini kâr ve marjı hesaplayan proje kârlılık servisi.
11. Her toplamın kaynak kayıt kimliklerini veren cost-drilldown.
12. Tedarikçi ekstresi, borç yaşlandırması, kısmi ödeme ve reversal davranışını mevcut yapı üzerinde tamamla.

Endpoint aileleri en az şunları kapsasın:

- `/customers`, `/customers/{id}`, `/customers/{id}/statement`, `/customers/{id}/aging`
- `/receivable-schedules`, `/customer-financial-movements`
- `/projects/{id}/budget-lines`, `/projects/{id}/change-orders`
- `/projects/{id}/profitability`, `/projects/{id}/cost-drilldown`

Kenar durumları: fazla tahsilat, vadesiz hareket, iptal edilmiş plan, aynı idempotency anahtarı, ters kaydın tekrar terslenmesi, arşivli müşteri, projesiz açılış bakiyesi, onaysız ek iş.

WP-B1 sonunda testleri çalıştır ve ayrı commit at.

## WP-B2 — İzin, puantaj ve maaş güvenliği

Uygula:

1. Personel profilini iletişim, görev/ustalık, acil durum kişisi, ödeme yöntemi, varsayılan maaş günü ve kişi bazlı maaş günü istisnasıyla genişlet.
2. İzin türleri: yıllık, raporlu, diğer ücretli, ücretsiz ve mazeret. Yapı genişletilebilir olsun.
3. İzin hak defteri: grant/accrual/use/adjustment/reversal, geçerlilik dönemi ve bakiye.
4. İzin talebi: pending/approved/rejected/cancelled; tam gün, yarım gün veya saatlik.
5. Onaylanan izin ilgili günlere puantaj kaydı üretsin; iptal/reversal davranışı audit edilsin.
6. Resmî tatil ve haftalık çalışma planı.
7. `attendance_enforcement_start_date`: bu tarihten önce eski aylık çalışan davranışı; bu tarihten sonra eksik zorunlu iş günü maaş finalize işlemini engellesin.
8. Aynı personel+gün için veritabanı seviyesinde tek aktif puantaj kısıtı. Migration öncesinde eski mükerrerleri deterministik biçimde raporla ve güvenli stratejiyle ele al; sessiz veri silme yapma.
9. Yeni puantaj durumları: annual_leave, sick_leave, excused_leave, public_holiday, weekly_rest. Mevcut durumları bozma.
10. Kesinleşmiş/kapanmış maaş dönemini etkileyen puantaj veya izin değişikliğini engelle.
11. Maaş vade tarihi şirket varsayılanı ve personel istisnasından deterministik türetilsin.

Endpoint aileleri:

- `/leave-types`
- `/leave-requests`
- `/employees/{id}/leave-ledger`
- `/holidays`
- Puantaj eksiklik/uyumsuzluk kontrol endpoint'i

Kenar durumları: yetersiz izin bakiyesi, negatif bakiyeye izin ayarı, tatille çakışma, yarım gün, ay sınırı, işe giriş/çıkış dışı tarih, kapanmış dönem, onaylanan iznin ikinci kez onaylanması.

WP-B2 sonunda testleri çalıştır ve ayrı commit at.

## WP-B3 — Birleşik takvim, Bugün ve hatırlatmalar

Takvim kaynak verilerini kopyalayan gevşek bir tablo kurma. Proje görevi, ziyaret, müşteri tahsilat vadesi, tedarikçi ödeme vadesi, maaş vadesi ve izin kayıtlarından birleşik salt-okunur olay projeksiyonu üret. Yalnızca manuel olay ve hatırlatmalar ayrı tabloda saklansın.

Uygula:

1. `/calendar/events`: tarih aralığı, tür, proje, personel, durum filtreleri.
2. `/today`: gecikmiş, bugün ve sonraki 7 gün eylemleri; kaynak kayda deep-link bilgisi.
3. Manuel olay/hatırlatma: tek seferlik ve tekrar eden, erteleme, tamamlama, iptal.
4. Kaynak olay için sabit `source_type + source_id + occurrence_date` kimliği.
5. Bildirim teslim kaydı: aynı olay/eşik için mükerrer Windows bildirimi engellensin.
6. Finansal olaylar için vade günü ve bir gün önce; diğer olaylar için bir gün önce varsayılan bildirim eşiği.
7. Gecikmiş olaylar Bugün sonucunda kalır fakat her gün yeni masaüstü bildirimi oluşturmaz.

WP-B3 sonunda testleri çalıştır ve ayrı commit at.

## WP-B4 — Raporlar, ML, migration ve teslim

1. Proje kârlılık, bütçe sapması, müşteri alacak yaşlandırma, tedarikçi borç yaşlandırma, cari ekstre, yaklaşan nakit akışı, izin/mesai/devam ve malzeme fiyat geçmişi raporlarını JSON/XLSX/PDF üret.
2. 13 haftalık nakit raporu banka bakiyesi iddiasında bulunmasın; planlı giriş, planlı çıkış ve net değişim göstersin.
3. Mevcut altı ML modelini yeni veri yapılarıyla uyumlu hale getir. Yetersiz veride `ready=false`; tahminle beraber veri sayısı, model sürümü ve güven bilgisi dön.
4. Proje bütçe riski modeli tahmini bitş maliyetini kullansın. Yeniden alım modeli stok kesinliği iddiasında bulunmasın.
5. Tasarruf fırsatı verisi üret: bütçe sapması, fiyat anomalisi, ucuz tedarikçi, fazla mesai yoğunluğu, fire/yeniden işleme, projeye bağlanmamış gider ve tahsil edilmemiş onaylı ek iş. Her bulgu kaynak kimliklerini içersin.
6. API ve veri modeli belgelerini eksiksiz güncelle; enumları, durum geçişlerini, hata kodlarını ve örnek yanıtları yaz.
7. Temiz veritabanı ve 0.3.0 örnek veritabanı migration testlerini yap.
8. Backup/restore, audit, reversal, idempotency, dönem kilidi ve bozuk girdi testlerini tamamla.

Teslim kapısı:

```powershell
cd backend
python -m ruff check .
python -m pytest
```

Ayrıca Alembic head sayısını, temiz DB upgrade'ini ve 0.3.0 DB upgrade'ini doğrula. Test veya migration hatasını gizleme. Frontend testleri çalıştırma veya frontend dosyası düzeltme.

WP-B4 için ayrı commit at. Dal temiz olmalı.

## Her iş paketi sonunda rapor formatı

```text
PAKET:
DURUM:
COMMIT:
DEĞİŞEN API/VERİ MODELİ:
TEST SONUCU:
MIGRATION SONUCU:
AÇIK RİSKLER:
CODEX ENTEGRASYON NOTU:
```

Son raporda dört commit'i, toplam test sayısını, Alembic head kimliğini, bilinen riskleri ve Codex'in entegrasyon için kullanacağı endpoint listesini ver. `main` ile birleştirme yapma; Codex entegrasyonundan önce bekle.

---


