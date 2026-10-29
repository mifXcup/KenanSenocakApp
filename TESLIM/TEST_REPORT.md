# Test raporu — 0.5.0

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
