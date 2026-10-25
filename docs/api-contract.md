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
| POST | `/purchases/{id}/cancel` | Ödemesiz satın almayı iptal et |
| POST/GET | `/payments` | Ödeme oluştur/listele |
| POST | `/payments/{id}/reverse` | Ödemeyi tersle |
| POST | `/material-movements` | Kullanım, fire, iade veya düzeltme oluştur |

Liste endpoint'leri `limit` (1–500) ve `offset` destekler. Satın alma listesi ayrıca `supplier_id`, `project_id`; ödeme listesi `supplier_id` ile filtrelenir.

PATCH istekleri yalnız gönderilen alanları değiştirir. Boş body reddedilir. Firma ve malzeme adları benzersiz kalır; proje durumu `active`, `completed` veya `cancelled` değerlerinden biridir. Değişikliklerin önceki ve sonraki değerleri audit kaydına yazılır.

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

