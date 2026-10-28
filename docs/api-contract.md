# API Sözleşmesi — `/api/v1`

## Taşıma ve yetkilendirme

- Backend yalnız `127.0.0.1` üzerinde çalışır.
- `/health` dışındaki isteklerde `X-KS-Sidecar-Token` zorunludur.
- Renderer token'ı veya backend URL'sini doğrudan yönetmez; Electron main dar IPC köprüsünden geçirir.
- JSON alanları para için `*_kurus`, miktar için en fazla üç ondalıklı decimal kullanır.
- Paketli sidecar `ks-core.exe --host 127.0.0.1 --port <port>` argümanlarını kabul eder; `KS_SIDECAR_TOKEN` en az 32 karakterli ve `KS_DATA_DIR` yazılabilir kullanıcı veri dizini olmalıdır. Eksik token ile sidecar başlamaz.

## Hata şekli

```json
{
  "error": {
    "code": "overpayment",
    "message": "Ödeme satın almanın kalan tutarını aşıyor.",
    "details": { "remaining_kurus": 1200000 }
  }
}
```

Önemli kodlar: `validation_error`, `unauthorized`, `not_found`, `duplicate_supplier`, `duplicate_material`, `supplier_mismatch`, `overpayment`, `purchase_has_payments`.

## Endpoint özeti

| Method | Yol | Amaç |
| --- | --- | --- |
| GET | `/health` | Sidecar hazır mı? |
| GET | `/dashboard/summary` | Proje, firma, alış, ödeme ve borç özeti |
| GET | `/backups/status` | Yedekleme sağlığı, son yedek ve retention durumu |
| GET | `/backups` | Otomatik, manuel ve pre-restore yedeklerini listele |
| POST | `/backups` | Manuel online SQLite yedeği oluştur |
| POST | `/backups/{backup_id}/verify` | SHA-256, boyut ve SQLite integrity doğrula |
| POST | `/backups/{backup_id}/restore` | Doğrulanmış yedeği güvenli geri yükle |
| POST/GET | `/suppliers` | Firma oluştur/listele |
| PATCH | `/suppliers/{id}` | Firma adı, telefon veya notunu düzenle |
| GET | `/suppliers/{id}/balance` | Firma alış, ödeme ve kalan toplamı |
| POST/GET | `/materials` | Malzeme oluştur/listele |
| PATCH | `/materials/{id}` | Malzeme adı, birimi, takip biçimi veya notunu düzenle |
| GET | `/materials/{id}/balance` | Tahmini miktar ve güven uyarısı |
| POST/GET | `/projects` | Proje oluştur/listele |
| PATCH | `/projects/{id}` | Proje bilgileri, bütçe ve durumunu düzenle |
| POST/GET | `/purchases` | Satın alma oluştur/listele |
| PATCH | `/purchases/{id}` | Açıklama, vade veya proje bağlantısını düzelt |
| POST | `/purchases/{id}/cancel` | Ödemesiz satın almayı iptal et |
| POST/GET | `/payments` | Ödeme oluştur/listele |
| POST | `/payments/{id}/reverse` | Ödemeyi tersle |
| POST | `/material-movements` | Kullanım, fire, iade veya düzeltme oluştur |
| POST/GET | `/employees` | Personel oluştur/listele |
| POST/GET | `/sites` | Şantiye oluştur/listele |
| POST/GET | `/work-logs` | Çalışma ve işçilik maliyeti oluştur/listele |
| POST | `/work-logs/{id}/cancel` | Çalışma kaydını iptal et |
| POST/GET | `/employee-payments` | Avans veya ücret ödemesi oluştur/listele |
| POST | `/employee-payments/{id}/reverse` | Personel ödemesini tersle |
| POST/GET | `/project-expenses` | Proje gideri oluştur/listele |
| POST | `/project-expenses/{id}/cancel` | Proje giderini iptal et |
| GET | `/projects/{id}/cost-summary` | Malzeme, işçilik ve diğer giderleri birleştir |
| GET | `/imports/templates/{kind}` | Excel içe aktarma şablonu üret |
| POST | `/imports/{kind}/preview` | Excel dosyasını kayıt yapmadan doğrula |
| POST | `/imports/{kind}/commit` | Yedek alıp doğrulanmış satırları atomik kaydet |
| GET | `/exports/{kind}` | XLSX rapor üret |
| GET | `/exports/{kind}/pdf` | PDF rapor üret |
| GET | `/analytics/ml/insights` | Yerel fiyat, yeniden alım ve proje riski tahminleri |

Liste endpoint'leri `limit` (1–500) ve `offset` destekler. Satın alma listesi ayrıca `supplier_id`, `project_id`; ödeme listesi `supplier_id` ile filtrelenir.

PATCH istekleri yalnız gönderilen alanları değiştirir. Boş body reddedilir. Firma ve malzeme adları benzersiz kalır; proje durumu `active`, `completed` veya `cancelled` değerlerinden biridir. Değişikliklerin önceki ve sonraki değerleri audit kaydına yazılır.

Satın alma PATCH işlemi finansal tutarları, firmayı, malzemeyi veya miktarı değiştirmez. Yalnız `description`, `due_date` ve `project_id` kabul edilir. Proje bağlantısı değiştiğinde satın almanın otomatik malzeme hareketi de aynı projeye taşınır.

Excel aktarımı `suppliers`, `materials` ve `opening-debts` türlerini destekler. Dosya üst sınırı 8 MB, satır üst sınırı 5.000'dir. Commit öncesinde `pre_import` yedeği alınır; herhangi bir hatalı satır varsa hiçbir kayıt yazılmaz. Dışa aktarma `suppliers`, `materials`, `purchases`, `project-costs`; PDF ise `purchases` ve `project-costs` türlerini destekler.

Yerel tahmin endpoint'i fiyat için en az 5, yeniden alım aralığı için en az 4 satın alma; proje riski için en az 4 maliyet olayı ister. Veri yeterli değilse boş sonuç ve `ready=false` döndürür.

## Yedekleme kontratı

`Backup` nesnesi:

```json
{
  "backup_id": "ks-20261025-201530-123456-manual.db",
  "kind": "manual",
  "created_at": "2026-10-25T17:15:30.123456+00:00",
  "size_bytes": 155648,
  "sha256": "64-karakterli-sha256",
  "app_version": "0.2.0",
  "integrity": "ok"
}
```

`GET /backups/status` yanıtı:

```json
{
  "healthy": true,
  "in_progress": false,
  "last_error": null,
  "backup_count": 4,
  "latest_backup": {},
  "latest_automatic": {},
  "automatic_retention": 30
}
```

`POST /backups/{backup_id}/restore` yanıtı seçilen yedeği, restore öncesi otomatik oluşturulan `pre_restore` yedeğini ve `restart_required: true` bilgisini döndürür. Request body yoktur. `backup_id` yalnız sistemin ürettiği sıkı dosya adı formatını kabul eder; mutlak yol, `..` ve dizin ayırıcıları reddedilir. Bozuk, hash'i değişmiş veya metadata'sı eksik yedek geri yüklenmez.

## Satın alma isteği

`total_kurus` doğrudan girilebilir veya `quantity × unit_price_kurus` üzerinden hesaplanabilir. İkisi birlikte girilirse en fazla 1 kuruş yuvarlama farkı kabul edilir.

```json
{
  "supplier_id": "uuid",
  "material_id": "uuid",
  "project_id": "uuid veya null",
  "purchase_date": "2026-10-25",
  "quantity": "20.000",
  "unit": "levha",
  "unit_price_kurus": 160000,
  "paid_kurus": 2000000,
  "description": "İsteğe bağlı not",
  "idempotency_key": "renderer-uretimli-benzersiz-anahtar"
}
```

Yanıt toplam, ödenen ve kalan tutarı birlikte döndürür.

## Malzeme hareketi isteği

`movement_type`: `use`, `waste`, `return`, `adjustment`. `purchase` yalnız satın alma endpoint'i tarafından otomatik üretilir.

`confidence`: `exact`, `estimated`, `value_only`.

```json
{
  "material_id": "uuid",
  "project_id": "uuid veya null",
  "movement_date": "2026-10-25",
  "movement_type": "use",
  "quantity": "3.500",
  "unit": "levha",
  "confidence": "estimated",
  "note": "Yaklaşık kullanım"
}
```

`value_only` için `amount_kurus` zorunlu, miktar opsiyoneldir. Kesin/yaklaşık kayıtta miktar ve birim zorunludur.

## Ödeme isteği

```json
{
  "supplier_id": "uuid",
  "purchase_id": "uuid veya null",
  "payment_date": "2026-10-26",
  "amount_kurus": 500000,
  "note": "İsteğe bağlı not",
  "idempotency_key": "renderer-uretimli-benzersiz-anahtar"
}
```

`purchase_id=null` firma geneline ödeme/avans anlamına gelir. Alışa bağlı ödeme ilgili alışın kalanını aşamaz.

## Frontend durum kontratı

- `401`: Sidecar oturumu bozuldu; renderer tekrar denemek yerine Electron main'e çekirdeği yeniden başlatma isteği verir.
- `409`: Kullanıcının düzeltebileceği iş kuralı çatışması; mesaj form yanında gösterilir.
- `422`: Alan bazlı doğrulama; `details` içindeki konumlar forma eşlenir.
- Ulaşılamıyor: “Yerel veri hizmeti başlatılamadı” kurtarma ekranı; kayıt yapılmış gibi davranılmaz.
- Mutation tekrarında aynı `idempotency_key` kullanılmalıdır.


## v0.3.0 — Personel, maaş, finans defteri ve yerel ML

Bu sistem resmî bordro/SGK/vergi hesabı yapmaz; işletme içi maaş ve borç takibidir. Tüm para değerleri
kuruş (integer), finansal kayıtlar fiziksel silinmez (ters kayıt veya iptal durumu), her değişiklik
audit log'a yazılır. Yeni liste uçlarının hepsi `limit`/`offset` ile sayfalanır.

| Method | Yol | Amaç |
| --- | --- | --- |
| POST/GET | `/employees` | Personel oluştur (ücret türü, güncel ücret, IBAN, işe giriş/çıkış)/listele (`employment_state`, `include_archived`, `q`) |
| PATCH | `/employees/{id}` | Kart bilgileri; ücret değişikliği yalnız wage-rates ile |
| POST | `/employees/{id}/archive` | Personeli arşivle (silinmez) |
| GET/POST | `/employees/{id}/wage-rates` | Çakışmasız ücret geçmişi; yeni açık uçlu ücret öncekini kapatır |
| POST | `/employees/{id}/wage-rates/{rate_id}/cancel` | Yanlış ücret kaydını iptal et |
| POST/GET | `/work-logs` | Puantaj (`work_status`, `normal_hours`, `overtime_hours`, `manual_amount_kurus`); eski `hours`/`amount_kurus` alanları kabul edilir |
| PATCH | `/work-logs/{id}` | Puantaj düzelt; tutar yeniden hesaplanır |
| POST | `/work-logs/{id}/cancel` | Puantajı iptal et (maliyetten çıkar) |
| GET | `/work-logs/import-template` | Excel puantaj şablonu |
| POST | `/work-logs/bulk-preview` | Excel ön izleme (hatalı/mükerrer satır listesi) |
| POST | `/work-logs/bulk-commit` | `pre_import` yedeği alıp atomik aktarım; tek hata varsa hiçbir kayıt yazılmaz |
| GET/PUT | `/settings/payroll` | Fazla mesai oranı (%) ve standart gün saati |
| POST/GET | `/payroll-periods` | Maaş dönemi oluştur (çakışma yok)/listele |
| GET | `/payroll-periods/{id}` | Dönem ve toplamlar |
| POST | `/payroll-periods/{id}/calculate` | Draft/calculated dönemi deterministik hesapla |
| POST | `/payroll-periods/{id}/finalize` | `pre_finalize` yedeği alır, bayat hesabı reddeder, tahakkuk hareketlerini yazar |
| POST | `/payroll-periods/{id}/close` | Kapat (ödenmemiş kalan varsa `allow_unpaid` gerekir) |
| GET | `/payroll-periods/{id}/entries` | Personel bazlı hesap satırları |
| GET | `/payroll-periods/{id}/export.xlsx`, `/export.pdf` | Dosya çıktısı (ham dosya) |
| POST/GET | `/employee-finance/movements` | Finans defteri hareketi (`idempotency_key` zorunlu)/listele |
| POST | `/employee-finance/movements/{id}/reverse` | Ters kayıt (bir hareket yalnız bir kez) |
| GET | `/employees/{id}/financial-summary` | Şirket borcu / personel borcu ayrı toplamlar |
| GET | `/employees/{id}/statement` | Hesap ekstresi ve yürüyen bakiye |
| GET | `/employees/{id}/debt-aging` | `not_due`, `1_30`, `31_60`, `61_90`, `90_plus`, `no_due_date` |
| GET | `/projects/{id}/cost-summary` | Satın alma + işçilik tahakkuku + giderler, bütçe/kâr/marj |
| GET | `/projects/{id}/labor-breakdown` | Personel, ay, şantiye ve durum kırılımı |
| GET | `/sites/{id}/cost-summary` | Şantiye işçilik ve gider özeti |
| GET | `/analytics/ml/status` | Model hazırlığı, son çalıştırma, değerlendirme (`local_only: true`) |
| POST | `/analytics/ml/run` | Seçilen/tüm modelleri çalıştır, sonuçları kaydet, bekleyen tahminleri değerlendir |
| GET | `/analytics/ml/insights` | Canlı içgörüler (A–F modelleri) |
| GET | `/analytics/ml/runs`, `/analytics/ml/predictions` | Sonuç geçmişi |
| POST | `/analytics/ml/predictions/{id}/feedback` | `useful`/`not_useful`/`wrong` |
| POST | `/analytics/ml/evaluate` | Gerçekleşen değerle değerlendirme |
| GET | `/reports/staff` | Rapor listesi (12 rapor) |
| GET | `/reports/staff/{name}` | JSON rapor (`date_from`, `date_to`, `employee_id`, `project_id`, `site_id`, `payroll_period_id`) |
| GET | `/reports/staff/{name}/export.xlsx`, `/export.pdf` | Aynı üreticiden dosya çıktısı |

Raporlar: `employee-statement`, `payroll-period-summary`, `unpaid-payroll`, `employee-advances`,
`employee-debts`, `payment-history`, `project-labor`, `site-labor`, `monthly-staff-cost`,
`upcoming-payments`, `debt-aging`, `ml-prediction-vs-actual`.

Eski `/employee-payments` uçları korunur ve artık deftere yazar (`advance` → avans, `wage` → maaş ödemesi;
fazla ödeme otomatik avans olur). Yeni hata kodları: `period_locked`, `payroll_stale`,
`payroll_period_overlap`, `wage_rate_overlap`, `duplicate_work_log`, `already_reversed`,
`system_movement`, `overpayment`, `idempotency_conflict`.

Hesap kuralları: günlük = ücret × normal saat / 8; saatlik = ücret × saat; aylık = takvim günü başına
aylık/gün sayısı (tam takvim ayı tam aylık ücret, ücretsiz izin/devamsızlık günü düşer, kaydı olmayan
gün çalışıldı sayılır); fazla mesai = saatlik karşılık × saat × oran (varsayılan %150, dönemde
değiştirilebilir). Yuvarlama bileşen başına `ROUND_HALF_UP`.


## P0 / WP-B1 — Müşteri cari ve proje finansı

Bu bölüm resmî muhasebe değildir: KDV, e-Fatura, vergi ve SGK yoktur. Tüm para alanları kuruş (integer),
finansal kayıtlar silinmez (ters kayıt/iptal), her değişiklik audit log'a yazılır. Liste uçları `limit`/`offset`
ile sayfalanır. `as_of` verilmezse sunucu tarihi kullanılır; tekrar edilebilir sonuç için her zaman gönderin.

| Method | Yol | Amaç |
| --- | --- | --- |
| POST/GET | `/customers` | Müşteri kartı oluştur / listele (`q`, `include_archived`) |
| GET/PATCH | `/customers/{id}` | Kart + `balance_kurus`, `project_count` / düzenle |
| POST | `/customers/{id}/archive`, `/unarchive` | Arşivle / geri al (silinmez) |
| GET | `/customers/{id}/statement` | Ekstre, yürüyen bakiye (`date_from`, `date_to`, `project_id`) |
| GET | `/customers/{id}/aging` | Alacak yaşlandırma (`as_of`) |
| POST/GET | `/receivable-schedules` | Alacak planı (`customer_id`, `project_id`, `state`, `as_of`) |
| PATCH | `/receivable-schedules/{id}` | Başlık, tutar, vade, not (tutar tahsilatın altına inemez) |
| POST | `/receivable-schedules/{id}/cancel` | Planı iptal et (bağlı hareket varsa reddedilir) |
| POST/GET | `/customer-financial-movements` | Defter hareketi (`idempotency_key` zorunlu) / listele |
| POST | `/customer-financial-movements/{id}/reverse` | Ters kayıt (gövde isteğe bağlı: `movement_date`, `note`) |
| POST/GET | `/projects/{id}/budget-lines` | Bütçe satırı oluştur / listele (`include_cancelled`) |
| PATCH | `/projects/{id}/budget-lines/{line_id}` | Düzenle; tutar değişimi `reason` ile revizyon üretir |
| POST | `/projects/{id}/budget-lines/{line_id}/cancel` | Satırı iptal et |
| GET | `/projects/{id}/budget-lines/{line_id}/revisions` | Revizyon geçmişi |
| POST/GET | `/projects/{id}/change-orders` | Ek iş / kapsam değişikliği (`state` filtresi) |
| PATCH | `/projects/{id}/change-orders/{order_id}` | Yalnız taslak düzenlenir |
| POST | `/projects/{id}/change-orders/{order_id}/approve`, `/reject`, `/cancel` | Durum geçişi (gövde: `note`) |
| POST | `/purchases/{id}/lifecycle` | Satın alma yaşam döngüsü geçişi (teslim geçişleri fiş yazar) |
| GET | `/projects/{id}/profitability` | Taahhüt, gerçekleşen, kalan tahmin, tahmini bitiş maliyeti ve kâr |
| GET | `/projects/{id}/cost-drilldown` | Her toplamın kaynak kayıt kimlikleri (`category`, `limit`) |
| GET | `/suppliers/{id}/statement` | Tedarikçi ekstresi, yürüyen bakiye (`date_from`, `date_to`) |
| GET | `/suppliers/{id}/aging` | Tedarikçi borç yaşlandırması (`as_of`) |

Mevcut uçlardaki değişiklikler (geriye uyumlu): `POST /projects` ve `PATCH /projects/{id}` isteğe bağlı
`customer_id` kabul eder; verilmezse `customer_name` normalize edilip müşteri kartı bulunur/oluşturulur. `Project`
yanıtı `customer_id` taşır, `customer_name` orijinal metin olarak kalır. `POST /purchases` isteğe bağlı
`lifecycle_state` (`planned`, `ordered`, `received`; varsayılan `received`) alır; `Purchase` yanıtları
`lifecycle_state` ve `received_kurus` taşır. `POST /payments/{id}/reverse` zaten terslenmiş ödemede `404` yerine
`409 already_reversed` döner. `GET /projects/{id}/cost-summary` ve `/sites/{id}/cost-summary` yanıtlarına
`subcontract_kurus`, `rework_kurus` eklendi; `ProjectExpense.category` artık `subcontract` ve `rework` değerlerini de kabul eder.

### Enumlar

| Alan | Değerler |
| --- | --- |
| Müşteri hareketi `movement_type` | `accrual` (tahakkuk), `opening_balance`, `collection` (tahsilat), `refund` (iade), `correction`, `reversal` (yalnız sistem) |
| `direction` | `receivable_increase` (tahakkuk, açılış, iade, artıran düzeltme), `receivable_decrease` (tahsilat, azaltan düzeltme). `correction` için zorunlu, diğerlerinde türden türetilir |
| Alacak planı `payment_state` (türetilir) | `open`, `partial`, `paid`, `overdue`, `cancelled` |
| Bütçe `category` | `material`, `labor`, `shipping`, `installation`, `subcontractor`, `site`, `waste_rework`, `other` |
| Ek iş `change_state` | `draft`, `approved`, `rejected`, `cancelled` |
| Satın alma `lifecycle_state` | `planned`, `ordered`, `partially_received`, `received`, `cancelled` |
| Gider `category` | `shipping`, `installation`, `site`, `other`, `subcontract` (→ bütçe `subcontractor`), `rework` (→ `waste_rework`) |

### Durum geçişleri

- Ek iş: `draft → approved | rejected | cancelled`; `approved → cancelled` (müşteriye tahakkuk edilmişse önce tahakkuk
  terslenmelidir). `rejected` ve `cancelled` terminaldir. Yalnız `approved` olanlar revize sözleşme bedeline girer.
- Satın alma: `planned → ordered | partially_received | received | cancelled`; `ordered → partially_received | received |
  cancelled`; `partially_received → partially_received (daha büyük tutar) | received | cancelled`; `received → cancelled`.
  `cancelled` terminaldir. Geri dönüş (`received → ordered` gibi) yoktur. Ödemesi olan satın alma iptal edilemez.
- Müşteri hareketi: değişmez; yalnız `reverse` ile terslenir. Bir hareket bir kez terslenir, ters kayıt hiç terslenmez.

### Hesap kuralları

- Müşteri bakiyesi = artıran hareketler − azaltan hareketler (ters satırlar zıt yönde yazıldığı için toplam doğrudur).
- Tahsilat açık alacaktan fazla olabilir; fazlası müşteri avansı/kredisi olur (WP-B1.1). İade net tahsilatı aşamaz →
  `overrefund`. `overcollection` ve `reversal_makes_credit` kodları kaldırıldı.
- Ters kayıt tarihi WP-B1.1 ile sunucu iş tarihidir (aşağıya bakın); istemci her zaman bugünün tarihini göndermelidir.
- Tahsilatın planlara dağıtımı `customer_payment_allocations` ile yapılır; dağıtılmayan tahsilat yaşlandırmada en eski
  vadeden düşülür. Plana bağlanmamış bakiye `unscheduled_kurus` ve `no_due_date` kovasında gösterilir; planlar
  bakiyeyi aşarsa `plan_excess_kurus` bilgi verir.
- Yaşlandırma kovaları: `not_due`, `1_30`, `31_60`, `61_90`, `90_plus`, `no_due_date`.
- Satın alma borcu ve proje maliyeti teslim fişlerinin (`purchase_receipts`) tarih ve tutarıyla hesaplanır
  (`received_kurus` aktif fişlerin toplamıdır; planlı/siparişte 0). Eski kayıtlar tek başlangıç fişine dönüştürüldü. Teslim edilmemiş siparişe yapılan ön ödeme tedarikçi avansı (`credit_kurus`) olarak görünür.
- Taahhüt = planlı/siparişli satın almanın tamamı + kısmi tesliminin teslim edilmemiş kısmı.
- Kalan tahmin (kategori): manuel tahmin varsa o (`forecast_source = manual`, bütçeyi aşabilir), yoksa otomatik
  `max(kategori bütçesi − gerçekleşen − taahhüt, 0)` (`forecast_source = auto`; bütçe yoksa 0). Satır bazlı bütçe
  yoksa proje geneli `budget_kurus` esas alınır (`budget_source = project_budget`), manuel tahminler bu bütçeden
  harcanmış sayılır ve kalan genel artık tek kalemde tahmin edilir.
- Tahmini bitiş maliyeti = gerçekleşen + taahhüt + kalan tahmin. Tahmini kâr = revize sözleşme − tahmini bitiş maliyeti;
  marj = kâr / revize sözleşme × 100 (2 ondalık). Sözleşme yoksa kâr ve marj `null` döner.
- Revize sözleşme = `contract_amount_kurus` + onaylı ek işler toplamı (sözleşme ve ek iş yoksa `null`).
- `cost-drilldown` ve `profitability` aynı kaynak listesinden üretilir: her kategorinin `actual_sources` /
  `commitment_sources` toplamı ilgili toplama eşittir. Kaynak türleri: `purchase_receipt` (gerçekleşen), `purchase` (taahhüt), `work_log`, `project_expense`.
- Malzeme hareketi teslim fişi yazılırken oluşur (miktar varsa veya malzeme `value_only` ise); planlı/siparişte hareket
  yoktur. Excel/PDF dışa aktarımlarında satın alma listeleri tüm aktif satırları gösterir (WP-B4'te uyarlanacaktır).

### Hata kodları (yeni)

| Kod | HTTP | Anlam |
| --- | --- | --- |
| `duplicate_customer` | 409 | Normalize ad zaten kayıtlı |
| `customer_archived` | 409 | Arşivli müşteriye yeni kayıt/düzenleme |
| `already_archived`, `not_archived` | 409 | Arşiv durumu zaten istenen halde |
| `project_customer_mismatch` | 409 | Proje başka müşteriye ait |
| `schedule_customer_mismatch`, `schedule_project_mismatch` | 409 | Plan başka müşteri/projeye ait |
| `schedule_cancelled` | 409 | İptal edilmiş plana işlem |
| `schedule_has_allocations` | 409 | Aktif tahsilat dağıtımı olan plan iptal edilemez |
| `amount_below_collected` | 409 | Plan tutarı tahsilatın altına indirilemez |
| `overrefund` | 409 | Fazla iade (`details.refundable_kurus`) |
| `idempotency_conflict` | 409 | Aynı anahtar farklı bir hareketle kullanılmış |
| `already_reversed` | 409 | Hareket/ödeme zaten terslenmiş |
| `cannot_reverse_reversal` | 409 | Ters kayıt tekrar terslenemez |
| `invalid_reversal_date` | 422 | Ters kayıt tarihi orijinalden önce |
| `change_order_not_approved` | 409 | Onaysız ek iş tahakkuk edilemez |
| `change_order_project_mismatch` | 409 | Tahakkuk ek işin projesine yazılmalıdır |
| `change_order_locked` | 409 | Taslak olmayan ek iş düzenlenemez |
| `change_order_has_accruals` | 409 | Tahakkuklu onaylı ek iş iptal edilemez |
| `invalid_transition` | 409 | İzin verilmeyen durum geçişi (`details.from`, `details.to`) |
| `budget_line_cancelled` | 409 | İptal edilmiş bütçe satırı düzenlenemez |
| `invalid_received_amount` | 422 | Kısmi teslim tutarı geçersiz |
| `invalid_range` | 422 | `date_from > date_to` |

### Örnek yanıtlar

`POST /customer-financial-movements` (`201`; aynı `idempotency_key` ve aynı gövdeyle tekrar aynı kaydı döner):

```json
{
  "id": "uuid", "customer_id": "uuid", "project_id": "uuid", "receivable_schedule_id": null,
  "change_order_id": null, "movement_date": "2026-01-20", "movement_type": "collection",
  "direction": "receivable_decrease", "amount_kurus": 300000, "note": null,
  "idempotency_key": "col-0001-aaaa", "reversed_movement_id": null, "source": "manual",
  "status": "active", "is_voided": false
}
```

`GET /customers/{id}/statement`:

```json
{
  "customer_id": "uuid", "customer_name": "Kenan Yapı", "opening_balance_kurus": 0,
  "total_increase_kurus": 1000000, "total_decrease_kurus": 300000, "closing_balance_kurus": 700000,
  "rows": [
    {"movement_id": "uuid", "movement_date": "2026-01-10", "movement_type": "accrual",
     "direction": "receivable_increase", "increase_kurus": 1000000, "decrease_kurus": 0,
     "balance_kurus": 1000000, "project_id": "uuid", "receivable_schedule_id": null,
     "change_order_id": null, "reversed_movement_id": null, "is_voided": false, "note": null}
  ]
}
```

`GET /projects/{id}/profitability` (özet):

```json
{
  "project_id": "uuid", "contract_amount_kurus": 3000000, "approved_change_orders_kurus": 200000,
  "pending_change_orders_kurus": 0, "revised_contract_kurus": 3200000, "budget_source": "budget_lines",
  "original_budget_kurus": 850000, "revised_budget_kurus": 850000, "actual_cost_kurus": 530000,
  "commitment_kurus": 150000, "remaining_estimate_kurus": 250000,
  "forecast_cost_at_completion_kurus": 930000, "budget_variance_kurus": -80000,
  "current_profit_kurus": 2670000, "estimated_profit_kurus": 2270000, "estimated_margin_percent": 70.94,
  "categories": [
    {"category": "material", "budget_kurus": 500000, "original_budget_kurus": 500000,
     "actual_kurus": 400000, "commitment_kurus": 150000, "remaining_estimate_kurus": 0,
     "forecast_kurus": 550000, "variance_kurus": -50000, "budget_line_ids": ["uuid"]}
  ]
}
```

`GET /projects/{id}/cost-drilldown` (özet):

```json
{
  "project_id": "uuid", "actual_total_kurus": 530000, "commitment_total_kurus": 150000,
  "categories": [
    {"category": "material", "actual_kurus": 400000, "commitment_kurus": 150000,
     "actual_source_count": 1, "commitment_source_count": 1, "truncated": false,
     "actual_sources": [{"source_type": "purchase_receipt", "source_id": "uuid", "purchase_id": "uuid",
                         "date": "2026-02-01", "amount_kurus": 400000, "label": "MDF",
                         "lifecycle_state": "received"}],
     "commitment_sources": [{"source_type": "purchase", "source_id": "uuid", "purchase_id": "uuid",
                             "date": "2026-02-01", "amount_kurus": 150000, "label": "MDF",
                             "lifecycle_state": "planned"}],
     "remaining_estimate_kurus": 0, "forecast_source": "auto", "forecast_kurus": 550000}
  ]
}
```


## P0 / WP-B1.1 — Avans, ters kayıt tarihi, teslim fişleri, manuel tahmin

WP-B1 (19b18b8) sözleşmesinden farklar. Bu bölüm çelişen B1 ifadelerinin yerine geçer.

### 1. Müşteri avansı ve tahsilat dağıtımı

Tahsilat açık alacaktan fazla olabilir ve tahakkuk veya plan oluşmadan (kapora) girilebilir. Defter tek bir net
bakiye tutar: `net_balance_kurus = artıran − azaltan hareketler`; `receivable_kurus = max(net, 0)`,
`credit_kurus = max(−net, 0)`. Kullanılmamış tutar kredi olarak görünür; sonradan gelen tahakkuk krediyi otomatik
mahsup eder. `GET /customers/{id}` yanıtı: `receivable_kurus`, `credit_kurus`, `net_balance_kurus` (`balance_kurus` ile
aynı), `unallocated_collection_kurus` (planlara dağıtılmamış tahsilat toplamı), `project_count`. Ekstre yanıtı
`closing_receivable_kurus`, `closing_credit_kurus` taşır (satır `balance_kurus` negatifse kredi). Yaşlandırma yanıtı
`receivable_kurus`, `net_balance_kurus`, `advance_kurus` (avans; gecikmiş alacağa dahil değildir),
`unallocated_collection_kurus` döner; `overdue_kurus` yalnız alacaktır.

| Method | Yol | Amaç |
| --- | --- | --- |
| POST | `/customer-payment-allocations` | Tahsilatı plana dağıt (`collection_id`, `receivable_schedule_id`, `amount_kurus`, `allocation_date?`, `idempotency_key`) |
| GET | `/customer-payment-allocations` | Listele (`customer_id`, `collection_id`, `receivable_schedule_id`, `include_cancelled`) |
| POST | `/customer-payment-allocations/{id}/cancel` | Dağıtımı iptal et (gövde: `reason?`); fiziksel silme yok |

- Bir tahsilat birden fazla plana, bir plan birden fazla tahsilata dağıtılabilir. Plan durumu (`payment_state`: `open`,
  `partial`, `paid`, `overdue`, `cancelled`) aktif dağıtım toplamından türetilir.
- `POST /customer-financial-movements` ile `receivable_schedule_id` gönderilen tahsilat, planın kalanı kadar otomatik
  dağıtılır; fazlası dağıtılmamış (avans) kalır. Tahsilat yanıtı `allocated_kurus`, `unallocated_kurus` taşır.
  `receivable_schedule_id` yalnız `collection` hareketinde geçerlidir (iade/diğerlerinde `422`).
- Tahsilat terslenince aktif dağıtımları aynı transaction'da iptal edilir (her biri audit'e yazılır,
  `cancel_reason = "Tahsilat ters kaydı"`). Terslenmiş tahsilat yeniden dağıtılamaz (`collection_reversed`).
- Planın aktif dağıtımı varsa plan iptal edilemez (`schedule_has_allocations`); plan tutarı dağıtımın altına inemez
  (`amount_below_collected`).
- Dağıtım tarihi verilmezse sunucu iş tarihi (tahsilat tarihinden önceyse tahsilat tarihi) kullanılır.
- Yeni hata kodları: `allocation_exceeds_collection` (`details.unallocated_kurus`), `allocation_exceeds_schedule`
  (`details.remaining_kurus`), `allocation_cancelled`, `collection_reversed`, `invalid_allocation_date` (422),
  `schedule_has_allocations`. Kaldırılan kodlar: `overcollection`, `reversal_makes_credit`, `schedule_has_movements`.

### 2. Ters kayıt tarihi

`POST /customer-financial-movements/{id}/reverse` gövdesi: `movement_date?`, `note?`, `idempotency_key?`.
`movement_date` verilmezse sunucunun iş tarihi kullanılır (orijinal hareket gelecek tarihliyse orijinalin tarihi).
Verilen tarih orijinalden önce olamaz (`invalid_reversal_date`, 422). **İstemci her zaman bugünün tarihini açıkça
gönderir.** Böylece geçmiş tarihli ekstreler sonradan yapılan düzeltmeyle geriye dönük değişmez. İş tarihi tek bir
noktadan (`ks_yonetim.clock.business_today`) okunur; testler bunu sabitler.

### 3. Satın alma teslim fişleri

| Method | Yol | Amaç |
| --- | --- | --- |
| POST | `/purchases/{id}/receipts` | Teslim kaydı (`receipt_date`, `amount_kurus`, `quantity?`, `note?`, `idempotency_key`) |
| GET | `/purchases/{id}/receipts` | Fişler (`include_cancelled`) |
| POST | `/purchase-receipts/{id}/cancel` | Fişi iptal et (gövde: `reason?`); fiziksel silme yok |

- Borç, maliyet ve taahhüt hesapları fişlerin tarih ve tutarına dayanır: tedarikçi bakiyesi/ekstresi, borç yaşlandırması
  (`as_of` tarihine kadarki fişler), alış raporu (`date_from`/`date_to` fiş tarihine göre; satın alma sayısı ayrı satın alma
  başınadır), `GET /projects/{id}/cost-summary` tarih aralığı, profitability ve drilldown.
- `received_kurus` aktif fişlerin toplamıdır ve aynı transaction'da senkronlanır; `lifecycle_state` buradan türetilir
  (`0 → ordered/planned korunur`, `< total → partially_received`, `= total → received`). Son fiş iptal edilirse durum
  `ordered` olur. Toplam satın alma tutarını aşan fiş reddedilir (`receipt_exceeds_total`, `details.remaining_kurus`).
- `POST /purchases/{id}/lifecycle` teslim geçişlerinde fiş yazar: `partially_received` (`received_kurus` = kümülatif
  tutar), `received` (kalan tutar; miktar varsa kalan miktar). İsteğe bağlı `receipt_date`, `idempotency_key`; tarih
  verilmezse iş tarihi. İstemci tarihi açıkça göndermelidir.
- `POST /purchases` `received` durumunda satın alma tarihinde tek fiş yazar. Satın alma iptali aktif fişleri iptal eder.
  Açılış borcu aktarımı da fiş yazar.
- Malzeme hareketi teslim anında oluşur: fişte miktar varsa veya malzeme `value_only` ise. `exact`/`estimated` malzemede
  miktarsız fiş hareket yazmaz. Hareket fişe (`purchase_receipt_id`) bağlıdır; fiş iptalinde birlikte iptal edilir.
  Stok kesinliği zorunlu değildir; `tracking_mode` kuralları değişmedi.
- Drilldown `actual_sources` artık `purchase_receipt` kaynaklarıdır (`source_id` = fiş, `purchase_id` = satın alma);
  `commitment_sources` satın alma düzeyinde kalır (`source_type = purchase`).
- Tedarikçi ekstresinde `row_type = purchase` yerine `purchase_receipt` kullanılır.
- Yeni hata kodları: `receipt_exceeds_total`, `receipt_cancelled`.

### 4. Manuel kalan maliyet tahmini

| Method | Yol | Amaç |
| --- | --- | --- |
| GET | `/projects/{id}/cost-forecasts` | Kategori başına etkin tahmin (`forecast_source`, otomatik değer, revizyon) |
| PUT | `/projects/{id}/cost-forecasts` | Gövde `{"items": [{category, remaining_estimate_kurus \| null, as_of_date, reason}]}`; atomik |
| GET | `/projects/{id}/cost-forecasts/history` | Tüm revizyonlar (`category` filtresi) |

- `reason` zorunludur (3–255 karakter); her PUT yeni revizyon yazar, eski revizyon `is_current = false` olur (silinmez).
  `remaining_estimate_kurus: null` manuel tahmini kaldırır ve otomatik hesaba döner (kaldırılacak yoksa
  `no_manual_forecast`, 409). Aynı kategori bir istekte bir kez gönderilir; hata varsa hiçbir kategori yazılmaz.
- Manuel tahmin bütçeden büyük veya otomatik değerden küçük olabilir. `GET /projects/{id}/profitability` kategori satırları:
  `forecast_source` (`auto` \| `manual`), `auto_remaining_estimate_kurus`, `remaining_estimate_kurus` (etkin),
  `forecast_revision_no`, `forecast_as_of_date`, `forecast_reason`; üst düzey `manual_forecast_count`.
  Tahmini bitiş maliyeti etkin kalan tahmini esas alır. `cost-drilldown` kategori satırları aynı
  `remaining_estimate_kurus`, `forecast_source`, `forecast_kurus` değerlerini taşır.
- Örnek (`GET /projects/{id}/cost-forecasts`):

```json
{
  "project_id": "uuid",
  "forecasts": [
    {"category": "material", "forecast_source": "manual", "remaining_estimate_kurus": 700000,
     "auto_remaining_estimate_kurus": 400000, "revision_no": 2, "as_of_date": "2026-03-15",
     "reason": "Tedarikçi indirimi"},
    {"category": "labor", "forecast_source": "auto", "remaining_estimate_kurus": 300000,
     "auto_remaining_estimate_kurus": 300000, "revision_no": null, "as_of_date": null, "reason": null}
  ]
}
```
