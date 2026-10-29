# Veri Modeli — İlk Çekirdek

## Ana tablolar

| Tablo | Amaç | Kritik kurallar |
| --- | --- | --- |
| `suppliers` | Tedarikçi firma kartı | Ad benzersiz; silinmez, arşivlenir |
| `materials` | Malzeme sözlüğü | Varsayılan birim ve takip güven modu zorunlu |
| `projects` | Müşteri işi/proje | Sözleşme ve bütçe kuruş cinsinden, tahsilatla karıştırılmaz |
| `purchases` | Basit satın alma | Firma, malzeme, tarih ve toplam zorunlu; idempotency key benzersiz |
| `payments` | Firmaya yapılan ödeme | Alışa bağlı veya firma geneline yapılabilir; terslenebilir |
| `material_movements` | Alınan/kullanılan/fire/iade | Kesin, yaklaşık veya yalnız maliyet güveni taşır |
| `audit_logs` | Değişmez işlem izi | Oluşturma, iptal ve tersleme olayları |
| `employees` | Personel kartı | Günlük ücret isteğe bağlı; silinmez, arşivlenir |
| `sites` | Şantiye kartı | İsteğe bağlı olarak tek projeye bağlanır |
| `work_logs` | Günlük çalışma ve işçilik | Saat ve maliyet taşır; iptal edilebilir |
| `employee_payments` | Avans ve ücret ödemesi | Finansal kayıt terslenir, silinmez |
| `project_expenses` | Nakliye, montaj, şantiye ve diğer gider | Proje zorunlu, şantiye isteğe bağlı |

## Yedek metadata modeli

Yedek dosyaları operasyonel güvenlik verisi olduğundan canlı SQLite içinde tutulmaz; veritabanıyla aynı anda kaybolmaması için `backups/` dizininde eşlenik JSON metadata ile saklanır. Alanlar: `backup_id`, `kind`, `created_at`, `size_bytes`, `sha256`, `app_version`, `integrity`. `backup-events.jsonl` oluşturma, doğrulama, retention ve restore olaylarının sıralı operasyon günlüğüdür.

## İlişkiler

```text
Supplier 1 ── N Purchase N ── 1 Material
    │              │
    │              ├── 0..1 Project
    │              └── N Payment
    └── N Payment (alışa dağıtılmamış avans/ödeme dahil)

Material 1 ── N MaterialMovement N ── 0..1 Project
                         └─────────── 0..1 Purchase

Employee 1 ── N WorkLog N ── 0..1 Project
                    └─────── 0..1 Site
Employee 1 ── N EmployeePayment
Project 1 ── N ProjectExpense N ── 0..1 Site
```

## Hesaplama kuralları

### Firma borcu

```text
aktif satın alma toplamı - aktif ödeme toplamı
```

Negatif sonuç firma avansı/alacak bakiyesi olarak yorumlanır. İptal edilmiş satın alma ve terslenmiş ödeme hesaba katılmaz.

### Satın alma kalanı

```text
satın alma toplamı - o satın almaya bağlı aktif ödemeler
```

Bağlı ödeme kalan tutarı aşamaz. Firma geneline girilen ödeme kullanıcı dağıtım yapana kadar satın alma bazlı kalanı azaltmaz; firma toplam borcunu azaltır.

### Tahmini malzeme miktarı

```text
satın alma + iade + pozitif düzeltme - kullanım - fire
```

`value_only` kayıtta miktar hesaplanmaz. Negatif miktar blok değil veri kalitesi uyarısıdır.

## İndeksler

- Firma + alış tarihi
- Proje + alış tarihi
- Firma + ödeme tarihi
- Satın alma + ödeme tarihi
- Malzeme + hareket tarihi
- Proje + hareket tarihi
- Durum alanları ve görünür liste adları
- Audit entity type + entity id

## Sonraki migration'lar

- Müşteriyi projeden bağımsız tabloya ayırma
- Ek/dosya metadata tablosu
- Proje tahsilatları ve finans hareket defteri
- Gerekirse tahmin sonucu geçmişi; mevcut ML hesapları salt okunur ve istek anında üretilir


## v0.3.0 tabloları

- `employees`: `employment_start_date`, `employment_end_date`, `employment_state` (active/inactive/left),
  `wage_type` (monthly/daily/hourly), `current_rate_kurus`, `iban`, `payment_note`; `daily_rate_kurus`
  eski istemciler için günlük ücretin aynasıdır.
- `employee_wage_rates`: çakışmasız ücret dönemleri; geçmiş hesap tarihte geçerli kaydı kullanır.
- `work_logs`: `work_status`, `normal_hours`, `overtime_hours`, `calculated_amount_kurus`,
  `manual_amount_kurus`; `amount_kurus` etkin maliyet, `hours` toplam saattir. Bir personel için aynı gün
  tek aktif kayıt vardır (uygulama düzeyinde zorlanır).
- `app_settings`: fazla mesai oranı ve standart gün saati.
- `payroll_periods`, `payroll_entries`: draft → calculated → finalized → closed; finalized/closed dönem
  hesapları değişmez, düzeltme `correction` hareketiyle yapılır.
- `employee_financial_movements`: değişmez defter. Şirket borcu, avans havuzu ve personel borç havuzu ayrı
  hesaplanır; `reversed_movement_id` benzersizdir; `idempotency_key` benzersizdir. v0.2.0
  `employee_payments` satırları aynı kimlikle taşınır, eski tablo korunur.
- `ml_runs`, `ml_predictions`: yerel model çalıştırma ve tahmin/gerçekleşme geçmişi.

### Alembic revizyonları

1. `1597ff061a94` initial local core
2. `a3c1d2e4f5b6` add purchase due date
3. `b4d2e3f5a6c7` add operations and project costs (v0.2.0)
4. `c5e3f4a6b7d8` employee model and wage rates
5. `d6f4a5b7c8e9` work log statuses and settings
6. `e7a5b6c8d9f0` payroll periods and entries
7. `f8b6c7d9e0a1` employee financial movements
8. `a9c7d8e0f1b2` ml runs and predictions

Açılışta `ks_yonetim.migrate.upgrade_database` çalışır: eski (`alembic_version` olmayan) veritabanını tablo/sütun
izinden tanıyıp damgalar, bekleyen revizyon varsa önce `pre_migration` yedeği alır, başarısızlıkta canlı
veritabanını bu yedekten geri yükler.


## P0 / WP-B1 tabloları

- `customers`: müşteri kartı (`name`, `normalized_name` benzersiz, telefon, adres, ilgili kişi, not). Normalize ad,
  boşlukları sadeleştirilmiş ve Türkçe `İ→i`, `I→ı` kuralıyla küçültülmüş addır. Silinmez, `archived` olur.
- `projects.customer_id`: müşteri kartına bağ (boş olabilir). `customer_name` orijinal metin olarak değişmeden kalır.
  Migration mevcut `customer_name` değerlerini normalize ederek kartlara bağlar (aynı normalize ad → tek kart, kart adı ilk
  görülen yazımdır; kart kimliği normalize addan deterministik üretilir).
- `receivable_schedules`: beklenen tahsilat planı (müşteri, isteğe bağlı proje, başlık, tutar, isteğe bağlı vade, durum
  `active`/`cancelled`). Defter hareketi değildir.
- `customer_financial_movements`: değişmez müşteri cari defteri (`movement_type`, `direction`, `amount_kurus` > 0,
  `receivable_schedule_id`, `change_order_id`, `idempotency_key` benzersiz, `reversed_movement_id` benzersiz → bir hareket
  yalnız bir kez terslenir, `source` `manual`/`system`). Projesiz açılış bakiyesi `project_id = NULL` ile yazılır.
- `project_budget_lines`: kategori bazlı bütçe (`amount_kurus` güncel, `original_amount_kurus` ilk bütçe, `revision_no`).
- `project_budget_revisions`: her tutar değişiminin değişmez kaydı (`previous_amount_kurus`, `amount_kurus`, `reason`);
  (`budget_line_id`, `revision_no`) benzersiz. Satır oluşturulurken 1. revizyon yazılır.
- `project_change_orders`: kapsam/bedel değişikliği (`amount_kurus` ≠ 0, negatif olabilir; `change_state`).
- `purchases.lifecycle_state` (varsayılan `received`) ve `purchases.received_kurus`: `received_kurus`, aktif
  `purchase_receipts` toplamının önbelleğidir (WP-B1.1). Migration c1a7e9d2b3f4 mevcut satırlarda `received_kurus = total_kurus`,
  iptal edilmişlerde `cancelled` / `0` yazar.
- `project_expenses.category`: `subcontract` ve `rework` eklendi (sütun genişliği değişmez, ek migration gerekmez).

### Alembic revizyonu

9. `c1a7e9d2b3f4` customer ledger and project finance (`fb1db398215f` merge revizyonunu izler)
10. `d2b8f6a1c4e7` allocations, receipts, forecasts (head; WP-B1.1)

Not: `projects.customer_id` SQLite'ta sütun içi `REFERENCES customers (id)` olarak eklenir (tablo yeniden kurulmaz,
mevcut veri kopyalanmaz). SQLAlchemy'nin SQLite yansıtması sütun içi `ON DELETE` ifadesini okuyamadığından bu FK'de
`ondelete` belirtilmez (varsayılan NO ACTION; FK pragma açıkken referanslı müşteri silinemez).


## P0 / WP-B1.1 tabloları

- `customer_payment_allocations`: tahsilatın alacak planına dağıtımı (çoktan çoğa). `customer_id`, `collection_id`
  (`customer_financial_movements`), `receivable_schedule_id`, `amount_kurus` > 0, `allocation_date`, `idempotency_key`
  benzersiz, `status` (`active` / `cancelled`), `cancelled_at`, `cancel_reason`. Silinmez; tahsilat tersleme ve manuel iptal
  durumu değiştirir ve audit'e yazar. Plan ödenen tutarı = plana ait aktif dağıtımların toplamı.
- `purchase_receipts`: satın alma teslim olayı. `purchase_id`, `receipt_date`, `quantity` (boş olabilir), `amount_kurus`,
  `note`, `idempotency_key` benzersiz, `status` (`active` / `cancelled`), `cancelled_at`, `cancel_reason`. Silinmez.
  `purchases.received_kurus` aktif fişlerin toplamıdır (aynı transaction'da senkronlanır) ve `lifecycle_state` bundan
  türetilir. Migration, teslim alınmış her mevcut satın almayı satın alma tarihinde tek başlangıç fişine çevirir
  (`idempotency_key = legacy-receipt:{purchase_id}`) ve mevcut satın alma hareketini bu fişe bağlar.
- `material_movements.purchase_receipt_id`: teslim anında oluşan satın alma hareketinin fişi (boş olabilir).
- `project_cost_forecasts`: kategori bazlı manuel kalan maliyet tahmini revizyonları (ekleme-yalnız). `project_id`,
  `category`, `revision_no` (proje+kategori+revizyon benzersiz), `remaining_estimate_kurus` (NULL = otomatiğe dönüş),
  `as_of_date`, `reason` zorunlu, `status` (`active` güncel, `archived` eski revizyon).
- Mevcut `receivable_schedule_id` taşıyan tahsilatlar migration'da dağıtım kaydına çevrilir (`legacy-allocation:{id}`);
  terslenmiş olanlar `cancelled` durumunda gelir. `customer_financial_movements.receivable_schedule_id` kolonu korunur
  (bağlantı kolaylığı); plan ödemesinin kaynağı dağıtım tablosudur.

### Alembic revizyonu

10. `d2b8f6a1c4e7` allocations, receipts, forecasts (head). `material_movements.purchase_receipt_id` sütun içi
`REFERENCES purchase_receipts (id)` olarak eklenir (tablo yeniden kurulmaz); B1'deki `ON DELETE` notu burada da geçerlidir.


## P0 / WP-B2 tabloları

- `employees` (yeni sütunlar): `email`, `address`, `skill`, `emergency_contact_name`, `emergency_contact_phone`,
  `emergency_contact_relation`, `payment_method`, `salary_day` (boşsa şirket varsayılanı).
- `work_logs` (yeni sütunlar): `leave_request_id` (izin talebine bağ), `leave_hours`, `source` (`manual`/`leave`).
  **Kısmi benzersiz indeks** `uq_work_log_employee_day_active (employee_id, work_date) WHERE status = 'ACTIVE'`:
  personel+gün için tek aktif puantaj veritabanı düzeyinde garanti edilir.
- `leave_types`: izin türü (`code` benzersiz, `work_status`, `deducts_entitlement`, `is_system`). Migration 5 sistem türünü
  yazar (`annual`, `sick`, `other_paid`, `unpaid`, `excused`); kimlikleri deterministiktir.
- `leave_requests`: talep (`employee_id`, `leave_type_id`, `start_date`, `end_date`, `day_part`, `hours_per_day`, `total_hours`,
  `request_state`, `decision_note`, `decided_at`, `idempotency_key` benzersiz).
- `leave_ledger_entries`: hak defteri; `quantity_hours` işaretli, `entry_date`, `valid_from`/`valid_to`, `leave_request_id`,
  `reversed_entry_id` benzersiz (bir kayıt bir kez terslenir), `source` (`manual`/`system`), `idempotency_key` benzersiz.
  Silinmez; `use` ve `reversal` kayıtları sistemdir.
- `public_holidays`: `holiday_date`, `name`, `is_half_day`; aktif tarih için kısmi benzersiz indeks
  `uq_public_holiday_date_active`.
- `weekly_work_plans`: `employee_id` (boş = şirket planı), `effective_from`, `effective_to`, `workdays` (7 karakter, Pzt..Paz,
  `1` = çalışma günü).
- `work_log_duplicate_reports`: migration'ın çözdüğü mükerrer puantaj raporu (kalıcı denetim izi). Hiçbir puantaj
  silinmez; kaybeden kayıt `CANCELLED` olur.
- `app_settings` yeni anahtarlar: `attendance_enforcement_start_date`, `default_salary_day`, `allow_negative_leave_balance`.

### Alembic revizyonu

11. `e3c9a7b5d1f2` leave attendance and unique work log (head). `work_logs.leave_request_id` sütun içi
`REFERENCES leave_requests (id)` olarak eklenir (B1'deki `ON DELETE` notu geçerlidir). Mükerrer çözümü benzersiz indeks
oluşturulmadan önce aynı transaction'da yapılır; yükseltme öncesi otomatik `pre_migration` yedeği alınır.


## P0 / WP-B3 tabloları

Takvim için kaynak kayıtlarını kopyalayan tablo **yoktur**; olaylar `project_tasks`, `project_visits`,
`receivable_schedules` (+ dağıtımlar), `purchases`/`payments`, `employee_financial_movements` ve `leave_requests`
kayıtlarından projeksiyonla üretilir.

- `calendar_manual_events`: elle girilen olay/hatırlatma (`event_type` manual_event/reminder, `start_date`, `end_date`,
  `all_day`, `start_time`, `repeat_rule`, `repeat_until`, `amount_kurus`, isteğe bağlı proje/personel/müşteri/firma bağı,
  `status`). Tekrarlar satır olarak yazılmaz.
- `calendar_event_occurrences`: tek bir tekrarın durumu (`manual_event_id` + `occurrence_date` benzersiz;
  `occurrence_state` completed/postponed/cancelled; `postponed_to`).
- `calendar_reminder_preferences`: olay türü başına tercih (`event_type` benzersiz, `enabled`, `offsets_days`); kayıt yoksa
  varsayılan kullanılır.
- `notification_deliveries`: teslim edilen bildirimler (`delivery_key` benzersiz = olay|başlangıç|offset|kanal).

### Alembic revizyonu

12. `f4d1b8c6e2a3` calendar manual events and notifications (head)


## P0 / WP-B4

WP-B4 yeni tablo veya Alembic revizyonu eklemez; head `f4d1b8c6e2a3` olarak kalır. Raporlar, ML ve tasarruf analizi mevcut
tablolardan salt okunur hesaplanır; sonuçlar yalnız istendiğinde `ml_runs`/`ml_predictions` içine yazılır.

### Türetilmiş hesaplar

- **Proje kovası (müşteri avansı):** `customer_buckets(customer_id, as_of)` müşterinin etkin hareketlerini `project_id` kovalarına
  ayırır (`None` = bağlantısız). Tahsilatın plana dağıtılan kısmı o planın projesine, kalanı kendi `project_id` kovasına yazılır.
  Kova `net = artış − azalış`; `net < 0` ise `advance_kurus`. `project_advance_kurus` = projeye bağlı kovaların avansları toplamı,
  `unlinked_advance_kurus` = `None` kovasının avansı. Müşteri `credit_kurus` (B1.1) tek net bakiye olarak aynen kalır.
- **Gerçekleşen / taahhüt:** teslim fişleri (`purchase_receipts`), işçilik tahakkuku ve giderler gerçekleşen; planlı/siparişli
  satın almanın tamamı ve kısmi tesliminin kalanı taahhüttür. Fire malzeme hareketi (`WASTE`) satın alma maliyetinin içindedir ve
  raporlarda yeniden işleme giderine eklenmez.
- **13 haftalık nakit:** `calendar_api` projeksiyonunun açık `receivable_due`, `supplier_payable`, `payroll_due` olaylarından türetilir.
- **ML kaynak olayları:** proje maliyet olayları teslim fişi tarih ve tutarlarıdır; bütçe tabanı `compute_profitability` revize bütçesidir.

### Alembic revizyonları

## 0.5 / Ürün fiyat öneri motoru

- `project_products`: proje içindeki fiyatlandırılabilir ürün satırı; ürün türü, miktar/birim, yüzey, aksesuar seviyesi,
  göreli zorluk, teklif tarihi, verilen/kabul edilen fiyat, gerçekleşen maliyet, hedef marj ve teklif durumu.
- `product_cost_factors`: ürünün teklif tarihindeki maliyet etkileri. `share_percent` toplamı API'de %100 ile sınırlıdır;
  `reference_unit_price_kurus` ve `reference_date` geçmiş fiyatı sabitler. Malzemeye bağlanan etki güncel fiyatı son aktif
  satın almadan, malzemesiz etki `pricing_index_entries` kaydından alır.
- `pricing_index_entries`: satın alma dışında kalan işçilik/boya/piyasa referanslarının tarihli, denetlenebilir manuel serisi.
- `pricing_suggestions`: düşük/merkez/yüksek öneri, güven, karşılaştırılabilir kayıt sayısı, model sürümü ve bütün
  normalizasyon adımlarını içeren açıklama anlık görüntüsü. Öneri finansal hareket veya teklif onayı oluşturmaz.

Fiyat normalizasyonunda yalnız tanımlı maliyet payları güncellenir; kalan pay 1,0 katsayısında tutulur. Gerçekleşen maliyet
varsa hedef marj maliyet üzerine uygulanır, yoksa geçmiş satış fiyatı düşük güvenli karşılaştırma tabanı olur.

### Alembic revizyonu

13. `a5e2c7d9f1b3` product pricing engine (head). Yükseltme yolu testleri tüm ara revizyonlardan yeni head'e geçişi doğrular.
