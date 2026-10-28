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
- `purchases.lifecycle_state` (varsayılan `received`) ve `purchases.received_kurus`: borç ve maliyet `received_kurus`
  üzerinden hesaplanır. Migration mevcut satırlarda `received_kurus = total_kurus`, iptal edilmişlerde `cancelled` / `0` yazar.
- `project_expenses.category`: `subcontract` ve `rework` eklendi (sütun genişliği değişmez, ek migration gerekmez).

### Alembic revizyonu

9. `c1a7e9d2b3f4` customer ledger and project finance (head; `fb1db398215f` merge revizyonunu izler)

Not: `projects.customer_id` SQLite'ta sütun içi `REFERENCES customers (id)` olarak eklenir (tablo yeniden kurulmaz,
mevcut veri kopyalanmaz). SQLAlchemy'nin SQLite yansıtması sütun içi `ON DELETE` ifadesini okuyamadığından bu FK'de
`ondelete` belirtilmez (varsayılan NO ACTION; FK pragma açıkken referanslı müşteri silinemez).
