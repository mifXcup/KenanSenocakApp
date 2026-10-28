# Test raporu — 0.4.0

- Backend: 203 test geçti; Ruff temiz; tek Alembic head `f4d1b8c6e2a3`.
- Frontend: 14 test geçti; lint ve TypeScript/Vite production build geçti.
- Masaüstü: 5 IPC/bildirim testi geçti; main ve preload sözdizimi kontrolü geçti.
- npm audit: kök ve frontend bağımlılıklarında 0 güvenlik açığı.
- Paketli sidecar: yeni geçici veritabanında P0 API akışı, JSON/XLSX/PDF, yedekleme/geri yükleme geçti.
- Paketli sidecar: dolu 0.3.0 veritabanı yükseltildi; kayıtlar ve SQLite bütünlüğü doğrulandı.
- PyInstaller Vera.ttf içeriyor; Türkçe karakter glifleri doğrulandı.
- Electron Windows unpacked paketinde app.asar ve sidecar mevcut; NSIS installer üretildi.

Kurulmuş uygulamanın farklı bir Windows cihazında etkileşimli UI testi bu makinede yapılmadı. Paket yapısı ve paketlenmiş sidecar burada doğrulandı.
