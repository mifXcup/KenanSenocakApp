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
  "app_version": "0.4.0",
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


## P0 / WP-B2 — İzin, puantaj ve maaş güvenliği

Resmî bordro/SGK değildir; işletme içi takip. WP-B1/B1.1 sözleşmesi değişmedi; aşağıdakiler eklemedir. Miktarlar
(saat, gün) 2 ondalıklı string olarak döner. İş tarihi `ks_yonetim.clock.business_today`'dir; istemci tarih
gerektiren çağrılarda (izin ters kaydı, `receipt_date` vb.) bugünün tarihini açıkça göndermelidir.

### Uç noktalar

| Method | Yol | Amaç |
| --- | --- | --- |
| GET/PUT | `/settings/attendance` | `attendance_enforcement_start_date`, `default_salary_day` (1–31), `allow_negative_leave_balance`; `null` ayarı kaldırır |
| POST/GET | `/holidays` | Resmî tatil (`holiday_date`, `name`, `is_half_day`); aktif tarih benzersiz. Filtre: `year`, `date_from`, `date_to`, `include_cancelled` |
| POST | `/holidays/{id}/cancel` | Tatili iptal et (tarih yeniden tanımlanabilir) |
| POST/GET | `/weekly-work-plans` | Haftalık çalışma planı. `employee_id` boşsa şirket planı; `workdays` ISO hafta günleri (1=Pzt … 7=Paz); yeni plan öncekinin `effective_to`'sunu kapatır. Filtre: `employee_id`, `company_only` |
| GET | `/employees/{id}/work-calendar` | Gün tipi (`workday`, `weekly_rest`, `public_holiday`, `outside_employment`), zorunluluk ve puantaj (`date_from`, `date_to`) |
| GET | `/attendance/check` | Puantaj eksiklik/uyumsuzluk kontrolü (`date_from`+`date_to` veya `payroll_period_id`; `employee_id`, `include_clean`) |
| GET | `/attendance/duplicate-reports` | Migration sırasında çözülen mükerrer puantaj raporu |
| GET | `/payroll-periods/{id}/salary-due-dates` | Personel bazında türetilmiş maaş vadesi (önizleme) |
| GET/POST | `/leave-types`, `/leave-types/{id}/archive` | İzin türleri (5 sistem türü + özel); sistem türü arşivlenemez |
| GET/POST | `/employees/{id}/leave-ledger` | İzin hak defteri ve bakiye (`leave_type_code`, `as_of`) / hak, hakediş, düzeltme kaydı |
| POST | `/leave-ledger/{entry_id}/reverse` | Ters kayıt (`entry_date?`, `note?`) |
| GET | `/employees/{id}/leave-entitlement?year=` | Kıdeme göre yıllık izin gün önerisi (bilgilendirme) |
| POST/GET | `/leave-requests` | İzin talebi oluştur / listele (`employee_id`, `state`, `date_from`, `date_to`) |
| GET | `/leave-requests/{id}` | Talep + üretilen `work_log_ids` |
| POST | `/leave-requests/{id}/approve`, `/reject`, `/cancel` | Yönetici kararı (gövde: `note?`) |

Mevcut uçlardaki değişiklikler: `POST/PATCH /employees` ve `Employee` yanıtı `email`, `address`, `skill` (ustalık),
`emergency_contact_name/phone/relation`, `payment_method` (`cash`, `bank_transfer`, `other`), `salary_day` (1–31) taşır.
`WorkLog` yanıtı `leave_request_id`, `leave_hours`, `source` (`manual` | `leave`) taşır. `POST /work-logs` yeni
`public_holiday` (ücretli, varsayılan normal süre) ve `weekly_rest` (saat girilmez, tutar 0) durumlarını kabul eder;
`annual_leave`, `sick_leave`, `excused_leave` yalnız izin talebiyle üretilir (elle gönderilirse `422`).
`POST /payroll-periods/{id}/finalize` artık zorunlu gün eksiğinde `409 attendance_incomplete` döner ve vade türetir.

### Enumlar

| Alan | Değerler |
| --- | --- |
| Puantaj `work_status` | `worked`, `half_day`, `overtime`, `paid_leave`, `unpaid_leave`, `absent` (mevcut) + `annual_leave`, `sick_leave`, `excused_leave`, `public_holiday`, `weekly_rest` |
| Ücretli / ücretsiz | Ücretli: `worked`, `half_day`, `overtime`, `paid_leave`, `annual_leave`, `public_holiday`. Ücretsiz: `unpaid_leave`, `absent`, `sick_leave` (raporlu; işveren ödemez), `excused_leave`. Nötr: `weekly_rest` (aylıkta kesinti yok, günlük/saatlikte ödeme yok) |
| İzin türü `code` | `annual` (hak düşer), `sick`, `other_paid` (`paid_leave`), `unpaid`, `excused`; özel türler `work_status` seçer |
| İzin talebi `day_part` | `full`, `half_am`, `half_pm`, `hourly` (`hours` zorunlu, ≤ günlük normal süre) |
| İzin talebi `request_state` | `pending`, `approved`, `rejected`, `cancelled` |
| Hak defteri `entry_type` | `grant`, `accrual`, `use` (sistem), `adjustment` (işaretli), `reversal` (sistem) |

### Kurallar

- **Zorunlu iş günü:** personelin işe giriş/çıkış aralığında, haftalık planda çalışma günü olan ve resmî tatil olmayan gün.
  Plan önceliği: personel planı > şirket planı > varsayılan (Pazartesi–Cumartesi). Plan yoksa Pazar haftalık izindir.
- **Devam zorunluluğu:** `attendance_enforcement_start_date` yoksa veya dönem bu tarihten önceyse eski davranış korunur
  (puantajsız gün engel değil; aylıkta çalışıldı sayılır). Tarih dönemin ortasındaysa yalnız bu tarihten itibaren olan
  günler denetlenir. Kesinleştirme, hesaplanmış dönemdeki personelden zorunlu günü puantajsız olan varsa
  `409 attendance_incomplete` (`details.employees[]`: `employee_id`, `employee_name`, `missing_count`, `missing_dates`) döner;
  dönem `calculated` durumunda kalır.
- **Tekil aktif puantaj:** veritabanında (`work_logs`, kısmi benzersiz indeks `status = 'ACTIVE'`) aynı personel+gün için
  tek aktif kayıt vardır; iptal edilen kayıtlar kısıtı tutmaz. Yarışta da `409 duplicate_work_log` döner.
- **Mükerrer migration:** eski veritabanındaki çoklu aktif kayıtlar **silinmez**. Aynı personel+gün için en eski kayıt
  (`created_at`, `id`) korunur, diğerleri `CANCELLED` yapılır, nota işaret düşülür, `audit_logs`'a (`actor = migration`)
  yazılır ve `work_log_duplicate_reports` tablosuna (`kept_*`, `cancelled_*` tutar/durum, `in_locked_period`) raporlanır.
  Kesinleşmiş döneme denk gelen mükerrerler de aynı kuralla çözülür; `in_locked_period = true` ile işaretlenir ve
  maliyet farkı rapordan izlenip düzeltme hareketiyle ele alınmalıdır.
- **İzin hak defteri (saat cinsinden):** 1 gün = `standard_day_hours`. Bakiye geçerlilik dönemine (`valid_from`/`valid_to`)
  göre FIFO hesaplanır: önce süresi dolacak hak tüketilir; süresi dolan kullanılmamış saat `expired_hours` olur.
  `available_hours` bakiye tarihinde geçerli kalan hak, `overdrawn_hours` karşılanamayan kullanımdır,
  `balance_hours = available − overdrawn`. Yalnız `deducts_entitlement` türleri (yıllık) hak tutar.
- **Yetersiz bakiye:** onay `409 insufficient_leave_balance` (`details`: `available_hours`, `required_hours`) ile reddedilir ve
  hiçbir kayıt bırakmaz. `allow_negative_leave_balance = true` ise onaylanır ve bakiye negatife düşer. Negatif düzeltme ve
  kullanılmış hakkın terslenmesi (`reversal_makes_negative`) aynı kurala bağlıdır.
- **İzin onayı:** haftalık plan ve resmî tatile denk gelen günler izin sayılmaz (hak düşmez, puantaj yazılmaz); tüm günler
  atlanıyorsa `422 leave_no_working_days`. Kalan her gün için puantaj üretilir: ücretli izinde `normal_hours` = günlük
  normal süre (izin saati + varsayılan çalışılan kalan saat), ücretsizde 0; yarım gün/saatlik **ücretsiz** izinde
  `normal_hours` = günlük süre − izin saati. `leave_hours` izin saatidir. Maliyet tarihte geçerli ücretle hesaplanır;
  ücret yoksa `422 missing_labor_rate`. Aylık çalışanda kısmi ücretsiz izin yalnız `leave_hours / günlük süre` oranında kesinti yapar.
- **Çakışma:** o günlerde aktif puantaj varsa `409 attendance_conflict` (`details.dates`); bekleyen/onaylı başka talep varsa
  `409 leave_overlap`; işe giriş/çıkış dışı tarih `422 leave_outside_employment`.
- **Dönem kilidi:** kesinleşmiş/kapanmış dönemle kesişen izin talebi oluşturma, onay ve onaylı talebin iptali
  `409 period_locked`; yarım kalan hiçbir kayıt bırakılmaz. Ay sınırını aşan talepte herhangi bir gün kilitliyse tamamı reddedilir.
- **Onaylı izin iptali:** puantajlar `CANCELLED` olur (silinmez, audit'lenir), her `use` kaydı için aynı tarihli `reversal`
  yazılır. İzin talebinden üretilen puantaj elle değiştirilemez/iptal edilemez (`409 leave_managed`).
- **Maaş vadesi:** finalize'da tahakkuk vadesi önceliği: istekteki `payment_due_date` > personel `salary_day` > şirket
  `default_salary_day` > dönem bitişi (eski davranış). Türetme: dönem bitişinden sonraki ilk maaş günü; ay sonunu aşan gün ay
  sonuna iner (örn. 31 → 30 Kasım, 28/29 Şubat). Saf fonksiyondur, sistem saatine bağlı değildir.
- Yıllık izin kıdem önerisi: <1 yıl 0, 1–<5 yıl 14, 5–<15 yıl 20, ≥15 yıl 26 gün (yıl sonu itibarıyla tamamlanan yıl). Öneri hakkı
  otomatik yazmaz.

### Hata kodları (yeni)

| Kod | HTTP | Anlam |
| --- | --- | --- |
| `attendance_incomplete` | 409 | Enforcement sonrası zorunlu gün puantajı eksik; kesinleştirilemez |
| `duplicate_work_log` | 409 | Aynı personel+gün aktif puantaj (artık veritabanı kısıtıdır) |
| `leave_managed` | 409 | İzin talebinden üretilen puantaj doğrudan değiştirilemez |
| `duplicate_holiday`, `holiday_cancelled` | 409 | Tatil tekrarı / zaten iptal |
| `plan_order` | 409 | Yeni plan başlangıcı mevcut plandan sonra olmalı |
| `range_required`, `range_too_large`, `invalid_range` | 422 | Kontrol aralığı hatalı |
| `duplicate_leave_type`, `system_leave_type`, `leave_type_archived` | 409 | İzin türü kuralları |
| `leave_type_without_entitlement` | 422 | Hak tutmayan türe hak kaydı |
| `insufficient_leave_balance` | 409 | İzin bakiyesi yetersiz |
| `reversal_makes_negative` | 409 | Tersleme bakiyeyi negatife düşürür |
| `system_entry` | 409 | `use`/sistem kaydı yalnız izin iptaliyle geri alınır |
| `leave_overlap` | 409 | Aynı personelde çakışan bekleyen/onaylı talep |
| `leave_no_working_days` | 422 | Tarihlerin tamamı tatil/haftalık izin |
| `leave_outside_employment` | 422 | İzin, işe giriş/çıkış aralığı dışında |
| `attendance_conflict` | 409 | İzin günlerinde mevcut puantaj (`details.dates`) |
| `invalid_hours` | 422 | Saatlik izin günlük süreyi aşıyor |
| `invalid_transition` | 409 | İzin talebi durum geçişi geçersiz (`details.from`, `details.to`) |
| `period_locked` | 409 | Kesinleşmiş/kapanmış dönemi etkiliyor (izin dahil) |

### Örnek yanıtlar

`GET /attendance/check`:

```json
{
  "date_from": "2026-10-01", "date_to": "2026-10-12", "enforcement_start_date": "2026-10-05",
  "employees_checked": 1,
  "totals": {"missing_required_day": 6, "enforced_missing_day": 4, "inconsistency": 2},
  "employees": [{
    "employee_id": "uuid", "employee_name": "Kontrol Usta", "required_day_count": 7, "logged_day_count": 3,
    "issues": [
      {"code": "missing_required_day", "date": "2026-10-05", "enforced": true},
      {"code": "worked_on_weekly_rest", "date": "2026-10-04", "work_log_id": "uuid", "enforced": false}
    ]
  }]
}
```

`GET /employees/{id}/leave-ledger` (özet):

```json
{
  "employee_id": "uuid",
  "leave_type": {"code": "annual", "work_status": "annual_leave", "deducts_entitlement": true},
  "balance": {"as_of": "2026-12-31", "granted_hours": "80.00", "used_hours": "40.00", "adjusted_hours": "0.00",
              "expired_hours": "0.00", "available_hours": "40.00", "overdrawn_hours": "0.00",
              "balance_hours": "40.00", "granted_days": "10.00", "used_days": "5.00",
              "available_days": "5.00", "balance_days": "5.00", "standard_day_hours": 8},
  "entries": [{"id": "uuid", "entry_type": "grant", "quantity_hours": "80.00", "entry_date": "2026-01-01",
               "valid_from": null, "valid_to": "2026-12-31", "source": "manual", "is_voided": false}]
}
```

`attendance_incomplete` hatası:

```json
{"error": {"code": "attendance_incomplete", "message": "Zorunlu çalışma günlerinde puantajı eksik personel var; kesinleştirmeden önce tamamlayın.",
 "details": {"enforcement_start_date": "2026-10-01",
  "employees": [{"employee_id": "uuid", "employee_name": "Aylık A", "missing_count": 1, "missing_dates": ["2026-10-07"]}]}}}
```

### WP-B4'e devredilenler (değiştirilmeden korunur)

1. Excel/PDF satın alma dışa aktarımlarının yaşam döngüsüne (planlı/siparişli/kısmi teslim) uyarlanması.
2. Kısmi teslim miktarının satın alma miktarını aşması engel değil, açıklanabilir uyarı olacak (şu an yalnız tutar toplamı sınırlı).
3. Müşteri avanslarının raporda projeye bağlı ve bağlantısız olarak ayrılması (şu an müşteri başına tek net bakiye).


## P0 / WP-B3 — Birleşik takvim, Bugün ve hatırlatmalar

Takvim olayları kaynak kayıtlardan her istekte deterministik üretilir (kaynak tabloların kopyası saklanmaz; kaynak
değişince eski olay kalmaz). Saklananlar: elle girilen olaylar, tekrarlarının durumu, hatırlatma tercihleri ve teslim
edilen bildirimler. İş tarihi `clock.business_today`'dir. Backend bildirim göstermez; Electron `due` kayıtlarını alır ve
teslim bildirir.

| Method | Yol | Amaç |
| --- | --- | --- |
| GET | `/calendar/events` | `date_from`, `date_to` (zorunlu, en fazla 401 gün); `event_type`, `project_id`, `employee_id`, `customer_id`, `supplier_id`, `state` |
| GET | `/today` | `overdue`, `today`, `next_7_days` grupları; her grupta `count`, `amount_kurus`, `receivable_kurus`, `payable_kurus`, `events`; `totals` |
| POST/GET | `/calendar/manual-events` | Manuel olay/hatırlatma oluştur / listele (`include_cancelled`) |
| GET/PATCH | `/calendar/manual-events/{id}` | Oku / düzenle |
| POST | `/calendar/manual-events/{id}/complete` | Tekrarı tamamla (`occurrence_date`; tekrarlıda zorunlu) |
| POST | `/calendar/manual-events/{id}/postpone` | Tekrarı ertele (`occurrence_date`, `new_date`) |
| POST | `/calendar/manual-events/{id}/cancel` | `occurrence_date` ile tek tekrarı, tarihsiz tüm seriyi iptal et |
| GET/PUT | `/calendar/reminder-preferences` | Olay türü başına `enabled` ve `offsets_days`; PUT gövdesi `{"items": [...]}` |
| GET | `/notifications/due` | Bugün gösterilmesi gereken, henüz teslim edilmemiş bildirimler (`channel = windows`) |
| POST | `/notifications/delivered` | `{"delivery_key"}`: bildirimi teslim edildi işaretle (tekrar çağrı `already_delivered: true`) |

### Olay yapısı

`event_id`, `source_type`, `source_id`, `occurrence_date`, `event_type`, `title`, `description`, `start_date`, `end_date`,
`all_day`, `state`, `amount_kurus` (boş olabilir), `project_id`, `employee_id`, `customer_id`, `supplier_id`,
`source_route`, `notification_defaults`. `event_id = source_type:source_id:occurrence_date` ve tekrar üretilebilirdir.
`source_route`: `{entity, entity_id, project_id, employee_id, customer_id, supplier_id}`; istemci `entity` değerinden
deep-link üretir. `notification_defaults`: `{enabled, offsets_days, is_financial}`.

| Kaynak | `source_type` | `event_type` | `entity` | Tutar / not |
| --- | --- | --- | --- | --- |
| Proje görevi vadesi | `project_task` | `project_task` | `project_task` | `task_state` ekstra alan; `done` → completed |
| Ziyaret | `project_visit` | `project_visit` | `project_visit` | `visit_state` completed/cancelled yansır |
| Müşteri alacak planı vadesi | `receivable_schedule` | `receivable_due` | `receivable_schedule` | açık kalan (yaşlandırmayla aynı hesap); ödenince completed ve plan tutarı |
| Tedarikçi borç vadesi | `supplier_purchase` | `supplier_payable` | `purchase` | açık kalan; planlı/siparişli satın alma ve vadesizler görünmez; ödenince completed |
| Maaş / personel ödeme vadesi | `employee_movement` | `payroll_due` | `employee_financial_movement` | kalan maaş borcu; ödenince completed |
| Onaylı izin | `leave_request` | `leave` | `leave_request` | `start_date`–`end_date`; bekleyen/reddedilen/iptal edilen yok |
| İşe dönüş | `leave_return` | `leave_return` | `leave_request` | iznin sonrasındaki ilk zorunlu iş günü (haftalık izin ve tatil atlanır) |
| Manuel | `manual_event` | `manual_event` \| `reminder` | `calendar_manual_event` | `original_date` (ertelenen tekrar), `repeat_rule`, `start_time` |

Durum: `completed`/`cancelled` kaynak durumundan; aksi halde `overdue` (tarih < bugün), `today`, `upcoming`.
İptal edilmiş alacak planı, arşivlenmiş proje ve iptal edilmiş manuel seri takvimde görünmez.

### Manuel olay ve tekrar

`repeat_rule`: `none`, `daily`, `weekly`, `monthly`; isteğe bağlı `repeat_until`. Tekrarlar sorgu aralığında üretilir, önceden
satır yazılmaz. Aylık tekrar başlangıç gününe çıpalıdır; ay sonunu aşan gün ayın son gününe iner (31 Ocak → 28/29 Şubat →
31 Mart). Çok günlü olay `end_date − start_date` süresini her tekrara taşır. Tekrarın durumu `calendar_event_occurrences`
satırıdır: `completed`, `postponed` (`postponed_to`), `cancelled`. Ertelenen tekrar yalnız yeni tarihte görünür ve
`original_date` ile kimliğini korur; tamamlanan/iptal edilen tekrar yeniden işlenemez (`occurrence_closed`). Tamamlanma/erteleme
yapılmış olayın `start_date`/`repeat_rule` değeri değiştirilemez (`event_has_history`).

### Bildirim kuralları

- Varsayılan zamanlar: finansal olaylar (`receivable_due`, `supplier_payable`, `payroll_due`) vade günü ve bir gün önce
  (`[0, 1]`); diğerleri bir gün önce (`[1]`). `PUT /calendar/reminder-preferences` ile türe göre değiştirilir (0–30 gün).
- Bir bildirim `olay açık (today/upcoming)` ve `başlangıç − offset ≤ bugün ≤ başlangıç` iken `due`'dur. Kaçırılan offset olay
  gününe kadar bir kez yakalanır. **Gecikmiş olaylar yeni bildirim üretmez**; `/today` içinde `overdue` olarak kalır.
- `delivery_key = event_id|start_date|offset_days|channel`; benzersizdir. Teslim edilen anahtar bir daha `due` olmaz;
  `POST /notifications/delivered` tekrar çağrılsa `already_delivered: true` döner. Anahtar olayın bugünkü projeksiyonuna ve
  tanımlı offset'e karşı doğrulanır (`event_not_found` 404, `invalid_offset` 422, `invalid_delivery_key` 422).
- `/today` gecikmiş kaynak olaylar için 730 gün geriye bakar; tekrarlı manuel olayların geçmiş tekrarları yalnız son 7 gün
  içinde gösterilir (tek seferlik gecikmiş manuel olaylar sınırsızdır).

### Hata kodları (yeni)

| Kod | HTTP | Anlam |
| --- | --- | --- |
| `range_too_large`, `invalid_range` | 422 | Takvim aralığı hatalı |
| `occurrence_date_required` | 422 | Tekrarlı olayda `occurrence_date` zorunlu |
| `not_an_occurrence` | 422 | Tarih olayın bir tekrarı değil |
| `occurrence_closed` | 409 | Tekrar tamamlanmış/iptal edilmiş |
| `invalid_postpone_date` | 422 | Yeni tarih mevcut tarihten sonra olmalı |
| `event_cancelled` | 409 | İptal edilmiş olay üzerinde işlem |
| `event_has_history` | 409 | Geçmişi olan olayın tekrar kuralı/başlangıcı değişmez |
| `invalid_delivery_key`, `invalid_offset` | 422 | Bildirim teslim anahtarı/zamanı geçersiz |
| `event_not_found` | 404 | Teslim anahtarının olayı yok |

### Örnek yanıt

`GET /notifications/due`:

```json
{
  "as_of": "2026-03-11", "channel": "windows", "count": 1,
  "notifications": [{
    "delivery_key": "receivable_schedule:uuid:2026-03-12|2026-03-12|1|windows", "channel": "windows",
    "offset_days": 1, "fire_date": "2026-03-11", "title": "Tahsilat vadesi: Müşteri – Peşinat", "body": null,
    "event": {"event_id": "receivable_schedule:uuid:2026-03-12", "event_type": "receivable_due", "state": "upcoming",
              "start_date": "2026-03-12", "amount_kurus": 100000, "customer_id": "uuid",
              "source_route": {"entity": "receivable_schedule", "entity_id": "uuid", "customer_id": "uuid"},
              "notification_defaults": {"enabled": true, "offsets_days": [0, 1], "is_financial": true}}
  }]
}
```


## P0 / WP-B4 — Raporlar, ML, tasarruf analizi ve final kapısı

Bu bölüm B1–B3 sözleşmesini kırmaz; alanlar eklemedir. Bilinen kırıcı davranış değişiklikleri sonda listelenir.
İş tarihi her yerde `clock.business_today`'dir (tarih verilmeyen `as_of` dahil). Para alanları kuruş (integer).

### Rapor ailesi — `/reports/finance`

JSON, XLSX ve PDF aynı `ReportTable` üreticisinden çıkar: satır sayısı ve toplamlar üç biçimde aynıdır. Yanıt:
`name`, `title`, `filters`, `columns[{key,label,kind}]`, `rows`, `totals`, `row_count`, **`notes`** (yöntem/kapsam
açıklamaları) ve **`warnings`** (yapılandırılmış uyarılar; `code`, `message`, ilgili kimlikler). XLSX ve PDF `notes` ile
`warnings[].message` değerlerini tablonun altına yazar. Mevcut `/reports/staff/*` aileleri `notes`/`warnings` alanlarını boş
liste olarak taşır (additive).

| Method | Yol | Amaç |
| --- | --- | --- |
| GET | `/reports/finance` | Rapor listesi |
| GET | `/reports/finance/{name}` | JSON (`limit` 1–2000, `offset`; toplamlar tüm satırlardan) |
| GET | `/reports/finance/{name}/export.xlsx` | XLSX (ham dosya) |
| GET | `/reports/finance/{name}/export.pdf` | PDF (ham dosya) |

Ortak filtreler: `date_from`, `date_to` (`date_to` aynı zamanda `as_of`'tur), `project_id`, `customer_id`, `supplier_id`,
`employee_id`, `material_id`, `site_id`, `horizon_days` (1–365). Dosya çıktısı en fazla 20.000 satırdır (`too_many_rows`).

| Rapor `name` | İçerik |
| --- | --- |
| `project-profitability` | Sözleşme, onaylı ek iş, revize sözleşme, gerçekleşen, taahhüt, kalan tahmin, tahmini bitiş maliyeti, tahmini kâr/marj, projeye bağlı net tahsilat ve açık alacak; bağlantısız avans uyarısı |
| `budget-variance` | Proje × kategori: ilk bütçe, revize bütçe, gerçekleşen, taahhüt, kalan tahmin, tahmini bitiş, sapma (₺ ve %), tahmin kaynağı (`auto`/`manual`) |
| `project-comparison` | Projeler arası kârlılık sıralaması (`rank`, tahmini marj, maliyet payı %) |
| `customer-aging` | Müşteri alacak yaşlandırması; avans (projeye bağlı / bağlantısız) gecikmiş alacaktan ayrı sütunlarda |
| `customer-advances` | Müşteri avansları: `Projeye bağlı` ve `Bağlantısız` satırlar; `project_advance_kurus` / `unlinked_advance_kurus` toplamları |
| `supplier-aging` | Tedarikçi borç yaşlandırması (teslim fişlerine göre) ve tedarikçi avansı |
| `customer-statement` | `customer_id` zorunlu (`customer_required`, 422); yürüyen bakiye, hükümsüz satırlar işaretli |
| `supplier-statement` | `supplier_id` zorunlu (`supplier_required`, 422); teslim, ödeme, ödeme ters kaydı |
| `cash-forecast-13w` | 13 haftalık **planlı giriş, planlı çıkış ve net değişim** (+ kümülatif net değişim). Banka/kasa bakiyesi içermez |
| `upcoming-schedule` | Gecikmiş ve `horizon_days` içindeki açık tahsilat/ödeme/maaş vadeleri |
| `staff-balances` | Personel kalan maaş ödemesi, şirket borcu, açık avans, personel borcu, net pozisyon |
| `attendance-overtime-leave` | Çalışılan gün, normal/fazla mesai saat ve oran, yıllık/raporlu/mazeret izin saati, devamsızlık, eksik zorunlu gün (varsayılan son 30 gün) |
| `labor-cost` | Proje × şantiye işçilik tahakkuku (saat ve tutar) |
| `material-price-history` | Teslim bazlı birim fiyat geçmişi ve önceki alıma göre değişim % |
| `waste-rework-cost` | Fire (malzeme hareketi) ve yeniden işleme gideri; birbirine eklenmez |
| `purchase-lifecycle` | Satın alma listesi: planlı / sipariş / kısmen / teslim ayrı; yalnız teslim alınan tutar gerçektir |

13 haftalık rapor kuralları: 13 haftalık pencere `as_of` gününde başlar (hafta 1 = `as_of … as_of+6`). Vadesi geçmiş ve
ödenmemiş tutarlar `week_no = 0` "Vadesi geçmiş (devreden)" satırındadır. Planlı giriş = vadeli alacak planlarının açık kalanı;
planlı çıkış = vadeli tedarikçi borcu kalanı + maaş/personel ödemesi kalanı. Vadesi girilmemiş açık alacak rapora dahil
değildir ve notlarda tutarı belirtilir. Sütun, anahtar ve notlarda bakiye iddiası yoktur.

### Devir maddeleri

1. **Satın alma dışa aktarımları yaşam döngüsüne uyarlandı.** `GET /exports/purchases` (XLSX) ve `GET /exports/purchases/pdf`
   artık `purchase-lifecycle` tablosundan üretilir: `Durum`, `Sipariş tutarı`, `Teslim alınan (gerçek)`, `Bekleyen taahhüt`,
   `Uyarı`. TOPLAM satırı yalnız teslim alınan ve bekleyen taahhüdü toplar; sipariş tutarı toplanmaz. Planlı/siparişli kayıt
   gerçek maliyet gibi toplanmaz.
2. **`quantity_over_received` uyarısı.** Toplam teslim miktarı satın alma miktarını aşarsa işlem engellenmez; `POST
   /purchases/{id}/receipts`, `GET /purchases/{id}/receipts`, `POST /purchase-receipts/{id}/cancel` ve
   `POST /purchases/{id}/lifecycle` yanıtlarında `warnings[]` döner: `code`, `message`, `purchase_quantity`,
   `received_quantity`, `excess_quantity`. Aynı uyarı `purchase-lifecycle` raporunda satır `warning` sütununda ve rapor
   `warnings` listesindedir.
3. **Müşteri avansı proje ayrımı.** Müşteri hareketleri proje kovalarına ayrılır: tahakkuk/açılış/iade/artıran düzeltme kendi
   `project_id` kovasına; tahsilat plana dağıtılan kısmında o planın projesine, kalanında kendi `project_id` kovasına yazılır.
   Kova bakiyesi negatifse o kova avansıdır: `project_advance_kurus` (projeye bağlı kovalar toplamı) ve
   `unlinked_advance_kurus` (`project_id` boş kova). Müşteri düzeyindeki `credit_kurus` (B1.1) tek net bakiyedir ve değişmedi;
   bu nedenle bir müşteride hem alacak hem bağlantısız avans bulunabilir.

`GET /projects/{id}/profitability` yanıtına eklenenler: `collections` (`collected_kurus`, `refunded_kurus`,
`net_collected_kurus`, `billed_kurus`, `open_receivable_kurus`, `project_advance_kurus`,
`unlinked_customer_advance_kurus`, `basis`) ve `warnings[]` (`unlinked_customer_advance`: `customer_id`, `amount_kurus`,
`message`). Tahsilat yalnız projeye bağlı veya o projenin planlarına dağıtılmış tutarı sayar; bağlantısız avans sayılmaz ve
uyarı döner. Kâr hesabı sözleşme ve maliyete dayanır, tahsilattan etkilenmez.

### Yerel ML (altı model korundu, additive)

Modeller: `price_anomaly`, `reorder`, `project_budget_risk`, `supplier_price_comparison`, `payroll_load`,
`employee_debt_risk`. Run, history (`/runs`), `/predictions`, `/predictions/{id}/feedback`, `/evaluate` aynıdır.

- `GET /analytics/ml/insights` yanıtına `models[]` eklendi: `model_name`, `model_version`, `ready`, `prediction_count`,
  `sample_count`, `confidence` (ortalama güven), `requirement`, `message`; `read_only: true`, `automatic_actions: []`.
  Yetersiz veride `ready = false`, tahmin listeleri boş, `message = "Yetersiz veri: <gereksinim> gerekir; tahmin üretilmedi."`.
- `GET /analytics/ml/status` model satırlarına `message`, `sample_count` (son çalıştırma), `confidence` (son çalıştırma
  ortalaması), mevcut `model_version`, `last_run_at` eklendi; üst düzey `read_only` ve `automatic_actions`.
- `POST /analytics/ml/run`: tahmin üretilmeyen modelde `metrics = {status: "insufficient_data", ready: false, message}`.
- **`project_budget_risk`** tahmini bitiş maliyetini (`forecast_cost_at_completion_kurus`, kârlılıkla aynı hesap) esas alır.
  Bütçe tabanı revize bütçedir (bütçe satırları varsa onların toplamı, yoksa proje bütçesi). `risk_level`: `high` →
  tahmini bitiş maliyeti bütçeyi aşıyor veya 30 günlük trend bütçeyi aşıyor; `medium` → trend veya (gerçekleşen + taahhüt)
  bütçenin %80'inde; aksi halde `low`. Yeni alanlar: `forecast_cost_at_completion_kurus`, `forecast_overrun_kurus`,
  `forecast_usage_percent`, `commitment_kurus`, `forecast_source` (`manual` | `auto`), `budget_basis`
  (`budget_lines` | `project_budget`). Maliyet olayları artık teslim fişlerinin tarih ve tutarlarıdır.
- **`reorder`** stok kesinliği iddiasında bulunmaz: yanıtta `basis = "purchase_interval"`, `stock_claim = false` ve
  `disclaimer` döner; tahmin yalnız geçmiş satın alma aralığından türetilir.
- Hiçbir model otomatik sipariş, ödeme veya maaş hareketi oluşturmaz (`read_only`, `automatic_actions` boş).
- Yalnız teslim edilmiş (`received`/`partially_received`) satın almalar fiyat ve yeniden alım modellerine girer.

### Tasarruf / risk fırsatları — `GET /analytics/savings`

Parametreler: `as_of`, `project_id`, `min_severity` (`low` | `medium` | `high`). Salt okunur; sonuç sıralaması önem sonra
tahmini etkiye göredir. Yanıt: `as_of`, `read_only`, `automatic_actions`, `count`, `total_estimated_impact_kurus`, `by_type`,
`by_severity`, `opportunities[]`.

Fırsat alanları: `opportunity_id` (`type:key`, deterministik), `type`, `severity`, `title`, `reason` (açık Türkçe neden),
`estimated_impact_kurus` (boş olabilir), `related_amount_kurus`, `confidence` (`high`|`medium`|`low`), `data_sufficiency`
(`sample_count`, `minimum_samples`, `sufficient`), `sources[]` (`source_type`, `source_id`, `amount_kurus`), `deep_link`
(`entity`, `entity_id`, `project_id`), `project_id` ve türe özgü alanlar.

| `type` | Tetik | `estimated_impact_kurus` |
| --- | --- | --- |
| `budget_overrun` | Kategori tahmini bitiş maliyeti bütçeyi aşıyor | Aşım tutarı; kaynaklar bütçe satırları + gerçekleşen/taahhüt kalemleri (`role`) |
| `price_anomaly` | Son birim fiyat beklenenin belirgin üstünde (anomali skoru ≥ 3) | (son fiyat − beklenen) × son alım miktarı |
| `cheaper_supplier` | Karşılaştırılabilir malzemede net daha ucuz tedarikçi | Son 180 gün diğer tedarikçilerden teslim alınan tutar × tasarruf % |
| `overtime_concentration` | Son 90 günde fazla mesai ≥ 20 saat ve ≥ %20 oran | Fazla mesai primi payı |
| `rework_increase` | Fire + yeniden işleme son 90 gün, önceki 90 günün ≥ 1,5 katı | Artış tutarı |
| `unlinked_expense` | Projeye bağlanmamış teslim alınmış satın alma / manuel işçilik | Boş; tutar `related_amount_kurus` |
| `uncollected_change_order` | Onaylı ek işin müşteriye tahakkuk ettirilmeyen kısmı | Tahakkuk edilmeyen tutar (önem: onaydan geçen gün) |
| `unlinked_customer_advance` | Bağlantısız müşteri avansı | Boş; tutar `related_amount_kurus` |

Önem eşikleri: bütçe aşımı aşım/bütçe ≥ %20 yüksek, ≥ %5 orta; fiyat anomalisi skor ≥ 5 yüksek; tedarikçi farkı ≥ %15 yüksek,
≥ %7 orta; fazla mesai oranı ≥ %35 yüksek; fire/yeniden işleme maliyet payı ≥ %10 yüksek, ≥ %3 orta; projesiz gider payı ≥ %25
yüksek, ≥ %10 orta; ek iş yaşı > 30 gün yüksek, > 14 gün orta; avans payı ≥ %50 yüksek, ≥ %20 orta.

### Diğer değişiklikler

- PDF yazı tipi: Windows/Linux/macOS sistem yazı tipleri yoksa reportlab'in paketlediği Vera kullanılır (Türkçe harfleri kapsar);
  `Helvetica` yalnız hiçbir yazı tipi bulunamazsa son çaredir. Para birimi `TL` olarak yazılır.
- `ks_yonetim.clock.business_today` tek tarih kaynağıdır; personel ücreti sunumu, rapor ve ML `as_of` varsayılanları buna bağlandı.

### Kırıcı olabilecek değişiklikler (Codex notu)

1. `GET /exports/purchases` (XLSX) ve `/exports/purchases/pdf` sütunları değişti (Durum, Teslim alınan, Bekleyen taahhüt, Uyarı eklendi;
   `Tutar` sütunu `Sipariş tutarı` oldu ve toplanmaz). Dosyayı sütun konumuyla okuyan istemci uyarlanmalıdır.
2. `ProjectRisk` risk seviyesi artık tahmini bitiş maliyetinden etkilenir; aynı veriyle seviye daha yüksek çıkabilir. Bütçesi yalnız
   bütçe satırlarıyla tanımlı projeler de riske dahil edilir.
3. Teslim fişi/lifecycle yanıtlarında `warnings` alanı eklendi (boş liste olabilir); `ReportTable` JSON'una `notes`/`warnings` eklendi.
