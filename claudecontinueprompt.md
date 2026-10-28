# Claude Sonuç Promptu — WP-B3 + WP-B4

WP-B2 onaylandı. `661b70e` sabit ve kabul edilmiş entegrasyon tabanıdır.

Bu noktadan sonra ara onay isteme. WP-B3 ve WP-B4'ü sırayla tamamla, her birini ayrı commit et, bütün backend kalite kapılarını çalıştır ve yalnızca ikisi de tamamen bittiğinde sonuç raporu ver.

Yalnızca şu durumlarda dur:

- Geri dönüşsüz veri kaybı riski
- Mevcut kullanıcı verisini yıkıcı migration gereksinimi
- Sidecar güvenlik modelini zayıflatacak zorunluluk
- Kullanıcı hesabı, haricî servis veya yeni yetki olmadan teknik olarak tamamlanamayan iş

Bunların dışındaki isim, enum, varsayılan, hata kodu ve uygulama ayrıntılarında en güvenli/geriye uyumlu kararı kendin ver, test et ve son raporda belirt. B3 sonunda onay bekleme; doğrudan B4'e geç.

## Değişmez sınırlar

- Dal/worktree: `claude/p0-domain-core` / `C:\Users\Emir\Desktop\KS-claude-p0`
- Yalnızca `backend/**`, Alembic dosyaları ve backend sözleşme belgelerini değiştir.
- `frontend/**`, `desktop/**`, kök paketleme dosyaları ve installer ayarlarına dokunma.
- `main` ile birleştirme yapma.
- B1/B1.1/B2 API'lerini kırma. Yeni alanlar geriye uyumlu ve additive olsun.
- Para tam sayı kuruş; finansal kayıtlar silinmez; reversal/iptal + audit kullanılır.
- KDV, e-Fatura, SGK, vergi ve resmî bordro ekleme.
- Stok kesinliği iddiası kurma.
- Tüm tarih varsayımları `clock.business_today()` üzerinden test edilebilir olsun.
- Ortak `.venv` kullanılabilir; her komutta `PYTHONPATH` worktree `backend/src` dizinine işaret etsin.
- Sürüm numarasını değiştirme; birleşik release sürümünü Codex belirleyecek.

## Kabul edilmiş B2 kararları

- Aynı personel+gün için tek aktif puantaj.
- Mükerrer migration'ı en eski kaydı korur, diğerlerini silmeden iptal edip raporlar.
- Raporlu ve mazeret izni varsayılan olarak ücretsizdir; ücretli özel izin için `paid_leave` türü kullanılabilir.
- Haftalık plan varsayılanı Pazartesi–Cumartesi.
- Elle puantajla çakışan izin otomatik üzerine yazmaz; `attendance_conflict` verir.
- Onaylı izin puantajı izin talebi üzerinden iptal edilir.
- Kıdeme göre izin hakkı otomatik yazılmaz, yalnızca öneri olur.

## WP-B3 — Birleşik takvim, Bugün ve hatırlatmalar

Takvim için kaynak kayıtları kopyalayan gevşek tablolar oluşturma. Kaynaklardan deterministik olay projeksiyonu üret; yalnızca manuel olaylar, hatırlatma tercihleri ve bildirim teslim kayıtları saklansın.

### Kaynak olaylar

- Proje görevi vadesi
- Proje/şantiye ziyareti
- Müşteri alacak planı vadesi
- Tedarikçi açık borç vadesi
- Personel maaş vadesi ve kalan maaş borcu
- Onaylı personel izni ve işe dönüş tarihi
- Manuel olay/hatırlatma

Kaynak olay kimliği sabit ve tekrar üretilebilir olsun: `source_type + source_id + occurrence_date`.

### Olay yanıtı

En az şu bilgileri dön:

- `event_id`
- `source_type`, `source_id`
- `event_type`
- `title`, `description`
- `start_date`, `end_date`, `all_day`
- `state`: overdue, today, upcoming, completed, cancelled
- `amount_kurus` nullable
- `project_id`, `employee_id`, `customer_id`, `supplier_id` nullable
- `source_route` veya istemcinin deep-link üretebileceği eşdeğer yapı
- `notification_defaults`

### Endpointler

- `GET /calendar/events`: `date_from`, `date_to`, `event_type`, `project_id`, `employee_id`, `state`
- `GET /today`: overdue, today ve next_7_days grupları; toplam adet/tutarlar
- `POST/GET/PATCH /calendar/manual-events`
- Manuel olay iptal/tamamla/ertele endpointleri
- `GET/PUT /calendar/reminder-preferences`
- `GET /notifications/due`
- Bildirimi teslim edildi olarak işaretleyen dar kapsamlı endpoint

### Manuel olay ve tekrar

- Tek seferlik, günlük, haftalık ve aylık tekrar
- Opsiyonel tekrar bitiş tarihi
- Erteleme, tamamlanma ve iptal
- Tekrarlar sorgu tarih aralığında deterministik üretilsin; sonsuz satır önceden yazılmasın

### Bildirim kuralları

- Finansal olaylar: vade günü ve bir gün önce
- Diğer olaylar: bir gün önce
- Gecikmiş olaylar `/today` içinde kalır fakat her gün yeni Windows bildirimi oluşturmaz
- Backend bildirim göstermez; Electron'un alacağı `due` kayıtlarını ve teslim deduplikasyonunu sağlar
- Benzersiz teslim anahtarı olay+occurrence+offset+channel kombinasyonuna dayansın
- Aynı bildirim iki kez teslim edilmesin

### B3 testleri

- Her kaynak türü için olay üretimi
- Tarih aralığı ve filtreler
- Vade geçişleri: upcoming → today → overdue
- Ödenen/tamamlanan/iptal edilen kaynağın takvim davranışı
- Tekrar eden manuel olay ay sonu dahil
- Erteleme ve tamamlama
- Bildirim deduplikasyonu
- Maaş, izin ve müşteri/tedarikçi vadelerinde tutar doğruluğu
- Kaynak kaydı değiştiğinde kopya olay kalmaması
- Temiz DB ve tüm eski head'lerden migration

B3 sonunda ruff + tüm testler + migration kapısını çalıştır, ayrı commit at ve doğrudan B4'e devam et.

## WP-B4 — Raporlar, ML, tasarruf analizi ve backend final kapısı

### Raporlar

JSON, XLSX ve PDF aynı veri üreticisini kullansın. En az:

- Proje kâr/zarar ve tahmini marj
- İlk/revize bütçe, gerçekleşen, taahhüt, kalan tahmin ve bitirme maliyeti
- Kategori bazlı bütçe sapması
- Projeler arası kârlılık karşılaştırması
- Müşteri alacak yaşlandırması
- Tedarikçi borç yaşlandırması
- Müşteri ve tedarikçi ekstreleri
- 13 haftalık planlı nakit girişi, çıkışı ve net değişim
- Personel maaş, avans, borç ve kalan ödeme
- Puantaj, fazla mesai, izin ve eksik devam
- Proje/şantiye işçilik maliyeti
- Malzeme alım fiyat geçmişi
- Fire ve yeniden işleme maliyeti
- Yaklaşan ödeme/tahsilat takvimi

13 haftalık rapor banka bakiyesi iddiasında bulunmasın. Yalnızca planlı giriş, planlı çıkış ve net değişim göstersin.

### Zorunlu B4 devir maddeleri

1. Excel/PDF satın alma listeleri yaşam döngüsü ve teslim fişlerine göre uyarlansın. Planlı/sipariş/teslim ayrı gösterilsin; planlı satın alma gerçek maliyet gibi toplanmasın.
2. Kısmi teslim miktarı satın alma miktarını aşarsa işlemi engelleme; API yanıtı/raporda açıklanabilir `quantity_over_received` uyarısı üret.
3. Projeye bağlı ve bağlantısız müşteri avansları raporlarda ayrı gösterilsin. Proje kârlılığı yalnızca projeye bağlı veya o projenin planlarına dağıtılmış tahsilatı kullansın; bağlantısız avans için uyarı dönsün.

### Makine öğrenmesi

Mevcut altı modeli koru ve yeni verilerle uyumla:

- price_anomaly
- reorder
- project_budget_risk
- supplier_price_comparison
- payroll_load
- employee_debt_risk

Kurallar:

- Yetersiz veride `ready=false`, boş tahmin ve açık gereksinim mesajı
- Model sürümü, kullanılan örnek sayısı, güven ve son çalıştırma
- Project budget risk, yeni `forecast_cost_at_completion_kurus` değerini esas alsın
- Reorder modeli stok kesinliği iddiasında bulunmasın
- Hiçbir model otomatik sipariş, ödeme veya maaş değişikliği yapmasın
- Run, history, predictions, feedback ve evaluate geriye uyumlu kalsın

### Tasarruf fırsatları

Backend açıklanabilir fırsat kayıtları dönsün:

- Bütçe sapması
- Fiyat anomalisi
- Daha uygun tedarikçi
- Fazla mesai yoğunluğu
- Fire/yeniden işleme artışı
- Projeye bağlanmamış gider
- Tahsil edilmemiş onaylı ek iş
- Bağlantısız müşteri avansı

Her fırsatta:

- Tür ve önem
- Açık Türkçe neden
- Tahmini parasal etki nullable
- Güven/veri yeterliliği
- Kaynak türleri ve kimlikleri
- İstemci deep-link bilgisi

### B4 test ve belge kapısı

- Tüm yeni raporlar JSON/XLSX/PDF aynı toplamları versin
- Türkçe karakter ve PDF font fallback testleri
- Teslim fişi tarih aralığı ve miktar aşım uyarısı
- Projeye bağlı/bağlantısız avans ayrımı
- ML yetersiz veri, yeterli veri, run history, evaluation ve feedback
- Tasarruf fırsatı toplam/kaynak tutarlılığı
- Backup/restore, audit, reversal, idempotency ve kilit regresyonu
- Temiz DB, v0.2.0, gerçek v0.3.0 ve B1/B1.1/B2/B3 head'lerinden migration
- Tek Alembic head ve metadata farkı olmaması
- `docs/api-contract.md`, `docs/data-model.md`, gerekli backend mimari notları tam güncellensin

B4 ayrı commit olsun.

## Son backend release gate

WP-B4 commit'inden sonra:

```powershell
$env:PYTHONPATH="C:\Users\Emir\Desktop\KS-claude-p0\backend\src"
& "C:\Users\Emir\Desktop\KŞ\backend\.venv\Scripts\python.exe" -m ruff check backend
& "C:\Users\Emir\Desktop\KŞ\backend\.venv\Scripts\python.exe" -m pytest backend
```

Ayrıca:

- Alembic tek head
- Temiz veritabanı upgrade
- v0.2.0 ve gerçek v0.3.0 veritabanı upgrade
- B1, B1.1, B2 ve B3 ara şemalarından upgrade
- Backup/restore doğrulaması
- Dalın temiz olması
- Frontend/desktop değişikliği olmaması

## Yalnızca en sonda verilecek rapor

```text
GENEL DURUM:

WP-B3 COMMIT:
WP-B3 API/VERİ MODELİ:
WP-B3 TEST/MIGRATION:

WP-B4 COMMIT:
WP-B4 RAPOR/ML/TASARRUF:
WP-B4 TEST/MIGRATION:

TOPLAM BACKEND TESTİ:
RUFF:
ALEMBIC HEAD:
TEMİZ DB:
ESKİ DB YÜKSELTMELERİ:
BACKUP/RESTORE:
DAL DURUMU:

CODEX ENTEGRASYON SÖZLEŞMESİ:
KIRICI DEĞİŞİKLİKLER:
BİLİNEN RİSKLER:
ERTELENEN P1/P2 İŞLER:
```

Ara onay isteme. B3 bitince B4'e geç. B4 ve final backend kapısı tamamen bitince tek sonuç raporu ver ve `main` birleştirmesi yapmadan bekle.

