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
- Vade ve borç yaşlandırma alanları
- Ek/dosya metadata tablosu
- Proje tahsilatları ve finans hareket defteri
- Personel maliyet dönemi, zaman kaydı ve şantiye ziyareti
- ML veri snapshot ve prediction tabloları

