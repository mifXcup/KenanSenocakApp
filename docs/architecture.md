# Kenan Şenocak Yönetim — Yerel Masaüstü Mimarisi

## Karar

Uygulama Windows'a kurulan tek kullanıcı odaklı bir masaüstü programıdır. React arayüz Electron penceresinde çalışır; Python/FastAPI çekirdeği paketlenmiş bir sidecar süreç olarak yalnızca `127.0.0.1` üzerinde dinler. SQLite dosyası kurulum klasörüne değil kullanıcının yazılabilir uygulama veri dizinine kaydedilir.

Bu yaklaşımın nedeni; çevrimdışı çalışma, verinin işletmede kalması, Python tabanlı analiz/makine öğrenmesi yolunun korunması ve kullanıcıya tarayıcı göstermeden masaüstü deneyimi sunmaktır.

## Süreç sınırları

```text
React renderer
  │ dar ve tipli IPC
  ▼
Electron preload (contextIsolation=true, nodeIntegration=false)
  │ izinli method/path listesi
  ▼
Electron main
  │ X-KS-Sidecar-Token + 127.0.0.1
  ▼
FastAPI sidecar
  │ SQLAlchemy transaction
  ▼
SQLite (WAL)
```

- Renderer doğrudan dosya sistemi, shell, process veya genel amaçlı ağ yetkisi almaz.
- Electron main her açılışta rastgele güçlü bir sidecar token üretip yalnızca child-process environment üzerinden backend'e verir.
- Backend `127.0.0.1` dışına bind edilmez. Token yoksa korunan endpoint'ler `401` döndürür.
- IPC tarafı genel `fetch(url)` sunmaz; yalnızca izin verilen `/api/v1/...` yollarını ve HTTP methodlarını geçirir.
- Uygulama kapanırken sidecar süreci kontrollü biçimde sonlandırılır; sahipsiz süreç temizleme yolu ayrıca bulunur.

## Veri dizinleri

Varsayılan kök:

```text
%LOCALAPPDATA%\Kenan Senocak Yonetim\
├── data\kenan-senocak.db
├── backups\
├── attachments\
├── exports\
├── logs\
└── models\
```

Geliştirmede `KS_DATA_DIR`; test ve otomasyonda `KS_DATABASE_URL` ile konum değiştirilebilir. Installer altındaki `Program Files` salt-okunur kabul edilir.

## Veri bütünlüğü

- Para `integer kuruş` olarak saklanır; binary floating point kullanılmaz.
- Miktar `Numeric(18,3)` olarak saklanır.
- Satın alma, otomatik malzeme girişi ve ilk ödeme tek transaction içinde yazılır.
- Tekrarlanan satın alma/ödeme istekleri `idempotency_key` ile aynı kayda döner.
- Fiziksel silme yoktur. Satın alma iptali ve ödeme tersleme audit kaydı üretir.
- Ödemesi bulunan satın alma, ödemeler terslenmeden iptal edilemez.
- SQLite foreign key, WAL, `busy_timeout=15000` ve `synchronous=NORMAL` ile açılır.

## Stok gerçeği

Bu ürün kusursuz depo sistemi iddiasında değildir. Malzeme üç moddan biriyle izlenir:

- `exact`: Sayılabilir ve doğrulanmış miktar.
- `estimated`: Yaklaşık kullanım ve tahmini kalan.
- `value_only`: Miktar değil yalnızca maliyet.

Tahmini miktar sıfırın altına düşerse kayıt engellenmez; kullanıcıya eksik kullanım/sayım uyarısı verilir. Raporlarda güven modu miktarın yanında taşınmalıdır.

## Paketleme kontratı

Geliştirme komutu:

```powershell
backend\.venv\Scripts\python.exe -m uvicorn ks_yonetim.main:app --host 127.0.0.1 --port <dinamik-port>
```

Dağıtımda backend PyInstaller `onedir` paketiyle `backend/dist/ks-core/ks-core.exe` sidecar'ına dönüştürülür. `scripts/build-backend.ps1` bu çıktıyı üretir. Electron Builder `backend/dist/ks-core` içeriğini `resources/backend` altına kopyalar; böylece paketli uygulamadaki beklenen çalıştırılabilir yol `resources/backend/ks-core.exe` olur. Sidecar'ın kaynak kod dizinine veya global Python kurulumuna bağımlılığı yoktur.

Electron main sidecar'ı şu kontratla başlatır:

```text
ks-core.exe --host 127.0.0.1 --port 8765
KS_SIDECAR_TOKEN=<her açılışta üretilen en az 32 karakterli token>
KS_DATA_DIR=<Electron userData>/data
```

Sidecar loopback dışındaki hostları, geçersiz portu ve 32 karakterden kısa/eksik token'ı reddeder. `desktop/main.cjs` içindeki `windowsHide: true` paketli uygulamada konsol penceresini gizler. Electron kapanışında child process sonlandırılır; SQLite WAL ve transaction sınırları ani süreç kapanmasında veri bütünlüğünü korur. Installer testinde süreç sonlandırıldıktan sonra aynı veritabanıyla yeniden başlatma kontrolü yapılır.

## Migration ve güncelleme

- Şema değişiklikleri Alembic revision ile sürümlenir.
- Program güncellemesi öncesi otomatik veritabanı yedeği alınır.
- Migration başarısız olursa yeni sürüm açılmaz; eski uygulama ve yedek korunur.
- SQLite dosyası uygulama sürümü düşürülerek doğrudan açılmaz; downgrade yalnız doğrulanmış restore ile yapılır.

## Yedekleme ve geri yükleme

- Yedekler çalışan veritabanından Python `sqlite3.Connection.backup()` online backup API ile alınır; canlı `.db` dosyası ham biçimde kopyalanmaz.
- Hedef `%LOCALAPPDATA%/Kenan Senocak Yonetim/data/backups` dizinidir.
- Snapshot önce aynı dizindeki gizli `.tmp` dosyasına yazılır, `PRAGMA integrity_check` çalıştırılır, SHA-256 ve byte boyutu metadata'sı üretilir, ardından `os.replace` ile atomik olarak son adına geçirilir.
- Uygulama açılışında o yerel gün için otomatik yedek yoksa bir tane oluşturulur. Yalnız otomatik yedeklerde son 30 kayıt tutulur; manuel, `pre_restore` ve `pre_import` yedekleri retention tarafından silinmez.
- Restore öncesinde seçilen dosyanın adı/path sınırı, metadata, SHA-256, boyut ve SQLite bütünlüğü doğrulanır. Ardından mevcut canlı verinin `pre_restore` yedeği alınır.
- Restore yarıda kalırsa canlı veri `pre_restore` yedeğinden geri alınır. Başarılı yanıtta istemciye `restart_required: true` döner.
- Oluşturma, doğrulama, hata, retention ve restore olayları `backup-events.jsonl` dosyasına yazılır; mümkün olduğunda ilişkisel audit log'a da eklenir.
- Test matrisi yedek oluşturma/doğrulama, bozuk yedeğin reddi, path traversal reddi ve restore roundtrip senaryolarını kapsar.

## Makine öğrenmesi sınırı

Model kodu işlem kayıtlarını değiştiremez ve hiçbir veriyi dış servise göndermez. Tahminler API isteği sırasında salt okunur yerel kayıtlardan yeniden hesaplanır. Fiyat anomalisi doğrusal trend artıkları, yeniden alım tarihi medyan sipariş aralığı, proje riski kümülatif maliyet regresyonu kullanır. Fiyat için 5, yeniden alım için 4 satın alma; proje riski için 4 maliyet olayı oluşmadan sonuç üretilmez.

## Operasyon ve dosya aktarımı

- Personel, şantiye, çalışma, personel ödemesi ve proje gideri ayrı tablolarda tutulur.
- Proje maliyet özeti satın alma, işçilik ve diğer giderleri sorgu anında birleştirir.
- Excel dosyaları salt okunur açılır; uzantı, base64, sıkıştırılmış/açılmış boyut, parça sayısı, başlık ve satır sınırları doğrulanır.
- İçe aktarma commit'i öncesinde SQLite online `pre_import` yedeği alınır. Hatalı tek satır varsa hiçbir kayıt yazılmaz.
- XLSX ve PDF çıktıları backend tarafından bellekte üretilir; geçici rapor dosyası kullanıcı veri dizinine bırakılmaz.

