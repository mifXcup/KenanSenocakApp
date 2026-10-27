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
