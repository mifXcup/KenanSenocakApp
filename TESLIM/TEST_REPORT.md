# Test raporu — 0.5.7

- 0.5.3 ön yüz: TypeScript, lint, fiyat girişi testleri ve üretim derlemesi geçti.
- PyInstaller veri hizmeti ve NSIS Windows kurulum paketi başarıyla üretildi.
- Kurulum dosyasının ürün sürümü 0.5.3; `TESLIM` kopyasının SHA-256 özeti derleme çıktısıyla eşleşiyor.
- Kurulum ve etkileşimli arayüz denemesi kullanıcı tarafından yapılacak.
- Backend ürün fiyatlandırma testleri, frontend TypeScript ve lint kontrolleri geçti.
- NSIS kurulum paketi üretildi; ürün düzenleme ve arşivleme rotaları pakete dahil edildi.

## 0.5.2 geçmiş testleri

- Backend: 230 test geçti; Ruff temiz. Starlette TestClient için bir deprecation uyarısı var.
- Ön yüz: 21 test, lint ve TypeScript/Vite production build geçti.
- Masaüstü: 11 test geçti.
- Paketli backend geçici veri dizininde temel API akışıyla ve dolu 0.3.0 veritabanı yükseltmesiyle sınandı; ikisi de geçti.
- NSIS 0.5.2 kurulum dosyası üretildi. Paket içindeki uygulama sürümü 0.5.2; teslim kopyasının SHA-256 özeti derleme çıktısıyla aynı.
- Kurulu 0.5.1 üzerine gerçek Windows kurulum denemesi ve etkileşimli arayüz testi henüz yapılmadı.

## 0.5.1 geçmiş testleri

- Backend testleri ve Ruff kontrolü geçti.
- Frontend: 21 test, lint ve TypeScript/Vite production build geçti.
- Masaüstü: 11 test geçti; yedek paketi aktarımı ve bozuk içerik reddi sınandı.
- Paketli sidecar ile dolu 0.3.0 veritabanı güncel `b7d3f1a9c5e2` şemasına yükseltildi; kayıtlar ve SQLite bütünlüğü doğrulandı.
- NSIS 0.5.1 installer üretildi; app.asar içinde ana süreç, yedek aktarım modülü, preload ve arayüz dosyaları doğrulandı. TESLIM kopyasının SHA-256 özeti derleme çıktısıyla eşleşiyor.
- Farklı Windows cihazında gerçek kurulum ve etkileşimli arayüz kabul testi henüz yapılmadı.

## 0.5.0 geçmiş testleri

- Backend: 207 test geçti; Ruff temiz; tek Alembic head `a5e2c7d9f1b3`.
- Fiyat motoru: 150.000 TL geçmiş teklif, %30 MDF payı ve 1.300 → 1.600 TL değişimiyle 160.384,62 TL merkez öneri testi geçti.
- Migration: doğrudan güncel şema, temiz DB ve dolu 0.3.0 DB yükseltme testleri geçti.
- Frontend: 14 test geçti; lint ve TypeScript/Vite production build geçti.
- Masaüstü: 5 IPC/bildirim testi geçti; main ve preload sözdizimi kontrolü geçti.
- npm audit: kök ve frontend üretim bağımlılıklarında 0 güvenlik açığı.
- Paketli sidecar: yeni geçici veritabanında P0 API akışı, ürün fiyat önerisi, JSON/XLSX/PDF ve yedekleme/geri yükleme geçti.
- Paketli sidecar: dolu 0.3.0 veritabanı `a5e2c7d9f1b3` head'e yükseltildi; kayıtlar ve SQLite bütünlüğü doğrulandı.
- Electron Windows unpacked paketinde app.asar ve 0.5.0 sidecar mevcut; NSIS installer üretildi.

Kurulmuş uygulamanın farklı bir Windows cihazında etkileşimli UI testi bu makinede yapılmadı. Paket yapısı ve paketlenmiş sidecar burada doğrulandı.
