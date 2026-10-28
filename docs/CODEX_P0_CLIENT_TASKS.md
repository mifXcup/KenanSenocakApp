# Codex P0 İstemci Görev Listesi

## Rol

Codex masaüstü deneyim, React istemci, Electron entegrasyonu, Windows bildirimleri, istemci testleri, birleşik regresyon ve kurulum paketinden sorumludur. Claude backend dalı tamamlanana kadar backend uygulama dosyaları değiştirilmez.

## WP-F0 — Hazırlık ve dal

- `codex/p0-desktop-client` dalını bu koordinasyon dosyalarını içeren güncel `main` tabanından oluştur.
- Mevcut UI, route, query, IPC allowlist ve Electron bildirim kabiliyetini denetle.
- API sözleşmesi kesinleşene kadar fixture/mock veriyle ilerle; geçici backend endpoint'i uydurma.
- Mevcut sade, beyaz ve şeffaf odaklı tasarım dilini koru.

## WP-F1 — Bilgi mimarisi ve ortak istemci altyapısı

Navigasyonu şu gruplara ayır:

- Operasyon: Bugün, Takvim, Projeler
- Finans: Proje Kârlılığı, Müşteri Cari, Tedarikçi Cari, Satın Almalar
- Personel: Personel, Puantaj ve İzin, Maaş Dönemleri
- Analiz: Raporlar, Akıllı Öngörüler
- Sistem: Veri ve Ayarlar

Yapılacaklar:

- `İş Takibi` taslağını Proje Merkezi ve Takvimle birleştir.
- API tipleri, query key'leri, para/tarih/durum formatlayıcıları ve dosya indirme yardımcılarını merkezileştir.
- Finansal işlemlerde onay, hata, boş, loading ve reversal akışları için ortak bileşenler oluştur.
- Uzun tablolarda filtre, sticky başlık, sayfalama ve klavye/focus davranışı ekle.

## WP-F2 — Proje ve cari ekranları

- Proje kârlılık merkezi: sözleşme, revize bedel, tahsilat, bütçe, taahhüt, gerçekleşen, kalan tahmin, bitş maliyeti, kâr ve marj.
- Kategori bazlı bütçe ve sapma tablosu.
- Maliyet toplamından kaynak kayda drill-down.
- Müşteri listesi, kartı, proje bağlantıları, tahsilat planı, hareket ekleme, ekstre ve yaşlandırma.
- Tedarikçi kartı, satın alma/ödeme ekstresi, kısmi ödeme, borç yaşlandırma ve fiyat geçmişi.
- Yanlış finansal kayıt için silme yerine ters kayıt arayüzü.

## WP-F3 — Personel, puantaj, izin ve maaş

- Personel 360 sayfası: profil, ücret geçmişi, puantaj, izin, bordro, avans/borç, ekstre ve proje işçiliği sekmeleri.
- Aylık puantaj ızgarası: toplu durum, normal saat, fazla mesai, proje/şantiye ve eksik kayıt uyarısı.
- Yıllık izin hakkı, bakiye, talep/onay/iptal ve zaman çizelgesi.
- Maaş dönemi: oluştur, hesapla, kontrol et, kesinleştir, öde, kapat.
- Personel bazlı hesap açıklaması, kısmi ödeme, kalan borç ve XLSX/PDF.
- Kilitli dönem ve eksik puantaj durumlarını açık ve engelleyici göster.

## WP-F4 — Takvim, Bugün ve Windows bildirimleri

- Ay, hafta ve gündem görünümü.
- Tür, proje, personel ve durum filtreleri.
- Gecikmiş, bugün ve 7 gün ayrımı.
- Kaynak kayda deep-link.
- Manuel olay, tekrar, erteleme ve tamamlama.
- Electron main/preload IPC allowlist'i üzerinden Windows bildirimi.
- Backend notification delivery anahtarıyla mükerrer bildirimi engelle.
- Uygulama başlangıcı ve gün içi kontrollü yenileme; arka planda sınırsız polling yapma.

## WP-F5 — Raporlar, ML ve tasarruf alanı

- Backend'deki tüm personel/finans ve yeni P0 raporlarını filtrelenebilir arayüze taşı.
- Ham XLSX/PDF yanıtlarını Electron masaüstünde güvenli kaydetme akışıyla indir.
- Altı ML modelinin hazırlık, son çalıştırma, güven, veri miktarı, geçmiş ve değerlendirme durumunu göster.
- Yetersiz veride tahmin yerine veri gereksinimini anlat.
- Tasarruf önerilerinde neden, parasal etki, güven ve kaynak kayıt bağlantısı göster.
- Tahmin ile kesin finansal değeri görsel ve metinsel olarak ayır.

## WP-F6 — Entegrasyon ve release gate

Claude tesliminden sonra:

1. `claude/p0-domain-core` dalını Codex dalına birleştir.
2. API tiplerini kesin sözleşmeyle eşleştir.
3. Frontend unit/integration testlerini tamamla.
4. Backend testlerini ve Alembic migration senaryolarını tekrar çalştır.
5. Yeni DB ve 0.3.0 DB ile paketli sidecar smoke testi yap.
6. `npm audit`, lint, frontend test, `build:ui`, backend build ve NSIS installer üretimini doğrula.
7. Gerçekçi uçtan uca senaryo çalıştır: müşteri → proje → bütçe → satın alma → puantaj → maaş → tahsilat/ödeme → kârlılık → takvim.
8. Release notu, bilinen riskler ve geri dönüş/yedek adımlarını yaz.

## Codex kabul kriterleri

- Her finansal toplam kaynak kayda açılır.
- Tahmin ve kesin değer karışmaz.
- Finans hareketlerinde silme sunulmaz.
- Eksik puantaj maaş kesinleştirmesini engeller.
- Onaylanan izin puantaj ve takvimde aynı sonucu verir.
- Takvim aynı olayı mükerrer göstermez veya bildirmez.
- Klavye, focus, loading, error, empty ve export durumları test edilir.
- Installer yalnızca tüm release gate geçince kullanıcıya teslim edilir.

