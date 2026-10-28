# Kenan Şenocak Yönetim — Yeni Sohbet Tamamlama Promptu

Bu repo üzerindeki kalan tüm P0 işlerini bitir. Ara onay isteme; güvenli ve geri dönüşlü kararları kendin al. Yalnızca geri dönüşsüz veri kaybı, yeni haricî yetki/hesap veya gerçek bir güvenlik engeli varsa dur.

## Ortam ve sabit durum

- Ana çalışma alanı: `C:\Users\Emir\Desktop\KŞ`
- Codex dalı: `codex/p0-desktop-client` @ `5fcf0f1`
- Claude backend worktree: `C:\Users\Emir\Desktop\KS-claude-p0`
- Claude backend dalı: `claude/p0-domain-core` @ `cc1bcef`
- `main`: `da7fc0c`
- Eski personel dalı/worktree'si referans içindir; değiştirme: `ks-staff-finance` / `C:\Users\Emir\Desktop\KS-staff`

Her iki aktif dal da temizdir. Claude backend'i tamamlandı:

- WP-B1 müşteri cari ve proje finansı
- WP-B1.1 müşteri avansı, tahsilat dağıtımı, teslim fişleri ve manuel maliyet tahmini
- WP-B2 izin, puantaj ve maaş güvenliği
- WP-B3 takvim, Bugün, hatırlatma ve bildirim teslim kaydı
- WP-B4 16 finans raporu, 6 ML modeli, tasarruf analizi ve backend final kapısı

Claude sonucu: ruff temiz, 203 backend testi geçiyor, tek Alembic head `f4d1b8c6e2a3`, temiz/v0.2.0/v0.3.0/B1/B1.1/B2/B3 migration senaryoları geçiyor.

Codex istemcisinde şimdiden tamamlananlar:

- Yeni Operasyon / Finans / Personel / Analiz / Sistem bilgi mimarisi
- Proje kârlılığının eski `/cost-summary` tabanlı ilk ekranı
- Maaş dönemi oluştur/hesapla/kesinleştir/kapat ilk ekranı
- Frontend lint, test ve build son çalıştırmada geçiyordu

## Zorunlu çalışma biçimi

1. Önce `README.md`, `docs/architecture.md`, `docs/api-contract.md`, `docs/data-model.md`, `docs/P0_COLLABORATION_MASTER.md` ve bu dosyayı tamamen oku.
2. Ekran/CUA/browser otomasyonu kullanma. Komut, test, statik inceleme ve gerekirse yerel HTTP smoke testleriyle doğrula.
3. Mevcut kullanıcı verisini koru. Yıkıcı Git veya veritabanı komutu kullanma.
4. Mevcut sade, beyaz, şeffaf ve masaüstü odaklı tasarım dilini koru; yeni bir paralel tasarım sistemi kurma.
5. Para değerlerini kuruş tam sayı olarak tut; tahmin ile kesin değeri açıkça ayır.
6. Finansal kayıtlarda silme sunma; iptal/ters kayıt kullan.
7. Backend kontratında sorun bulursan istemcide gizleme. En küçük geriye uyumlu backend düzeltmesini yap, test ekle ve ayrı commit et.
8. Her anlamlı iş paketini ayrı commit et. Kirli çalışma alanı bırakma.

## Aşama 1 — Backend dalını Codex dalına birleştir

`C:\Users\Emir\Desktop\KŞ` içinde:

```powershell
git status --short --branch
git merge --no-ff claude/p0-domain-core -m "merge: integrate P0 domain backend"
```

Çakışma olursa:

- Backend ve backend dokümanlarında Claude dalı esas.
- Frontend/desktop dosyalarında Codex dalı esas.
- `README.md` ve ortak belgelerde iki tarafın doğru bilgilerini sentezle.
- Migration dosyası silme veya yeniden adlandırma; tek head'i koru.

Birleştirme sonrası hemen backend ruff/test ve Alembic head kontrolü yap. Hata varsa istemciye geçmeden düzelt.

## Aşama 2 — İstemci API ve masaüstü köprüsü

### Tipler ve veri katmanı

- `frontend/src/lib/types.ts` tiplerini güncel `docs/api-contract.md` ile birebir eşleştir.
- Query key ve API servislerini modül bazında ayır; dev bir `useCoreData` bağımlılığı oluşturma.
- Tarih gerektiren ters kayıt, teslim fişi ve izin tersleme çağrılarında UI bugünün iş tarihini açıkça göndersin.
- `attendance_incomplete` hatasındaki `details.employees[]` listesini kullanıcıya göster.
- Loading, empty, error, retry ve locked state'leri her modülde uygula.

### Güvenli dosya indirme

Mevcut Electron `api:request` yalnızca JSON varsayıyor. XLSX/PDF için renderer'a genel dosya sistemi veya genel URL yetkisi verme.

- Main process'te dar kapsamlı `api:download` IPC oluştur.
- Yalnızca `GET`, `/api/v1/` ve belgelenmiş export yollarını kabul et.
- Sidecar token yalnızca main process'te kalsın.
- `dialog.showSaveDialog` kullan; kullanıcı iptalini normal sonuç olarak ele al.
- Dosyayı main process yazsın; renderer'a path veya Node/fs yetkisi verme.
- Content-Type, uzantı ve başarısız JSON hata yanıtlarını doğrula.
- Preload yalnızca dar `downloadReport(request)` işlevi açsın.

### Windows bildirimleri

- Backend `/notifications/due` kayıtlarını uygulama açılışında ve en fazla 15 dakikada bir kontrol et.
- Electron main process `Notification` kullansın.
- Bildirim gösterildikten sonra `/notifications/delivered` ile deduplikasyon kaydı yaz.
- Bildirime tıklanınca ana pencereyi aç/odakla ve güvenli `source_route` rotasına git.
- Backend kapalıyken crash veya sınırsız retry yapma.
- Renderer'a genel notification veya network yetkisi açma.

## Aşama 3 — Tüm P0 ekranlarını tamamla

Geçici `FoundationPage` ekranlarını canlı modüllerle değiştir. Bitmiş üründe “backend hazırlanıyor” metni veya pending noktası kalmasın.

### Bugün

- `/today` ile gecikmiş, bugün ve sonraki 7 gün.
- Tahsilat, tedarikçi ödemesi, maaş, izin, görev ve ziyaretleri ayrı türlerde göster.
- Tutar özetleri, kritik uyarılar ve kaynak kayda deep-link.
- Son yedekleme durumu ve eksik puantaj uyarısı.

### Takvim

- Ay, hafta ve gündem görünümü.
- Tarih aralığı, tür, proje, personel ve durum filtresi.
- Gecikmiş/bugün/yaklaşan ayrımı.
- Manuel olay oluşturma/düzenleme; tekrar, tamamlama, erteleme ve iptal.
- Kaynak kayda deep-link; kaynak olaylar istemciden düzenlenmeye çalışılmasın.

### Proje kârlılığı

Eski `/cost-summary` ekranını yeni sözleşmeye taşı:

- `/projects/{id}/profitability`
- Bütçe satırları ve revizyon geçmişi
- Kategori bazlı ilk/revize bütçe
- Gerçekleşen, taahhüt, otomatik/manuel kalan tahmin
- Tahmini bitirme maliyeti, kâr ve marj
- Müşteri tahsilatları, kalan alacak ve bağlantısız avans uyarısı
- Onaylı/bekleyen ek işler
- Cost drilldown; her toplamdan kaynak kayda geçiş
- Manuel maliyet tahmini girişi ve gerekçeli revizyon
- Tahmin/kesin değer görsel ayrımı

### Müşteri cari

- Müşteri liste/arama/oluşturma/düzenleme/arşiv.
- Bağlı projeler.
- Tahsilat planı; kapora, ara ödeme, kısmi tahsilat.
- Tahsilat dağıtımını planlara bağlama/iptal.
- Ekstre, brüt alacak, avans/kredi, net bakiye ve yaşlandırma.
- Yanlış finansal hareketi silme yerine ters kayıt.
- Projeye bağlı ve bağlantısız avansı ayrı göster.

### Tedarikçi cari ve satın alma

- Firma kartında ekstre, borç yaşlandırma ve kısmi ödeme.
- Satın alma yaşam döngüsü: planned, ordered, partially_received, received, cancelled.
- Teslim fişi ekleme/iptal; tarih, miktar, tutar ve not.
- Sipariş tutarı, teslim alınan gerçek tutar ve bekleyen taahhüdü ayrı göster.
- `quantity_over_received` engel değil, açıklanabilir uyarı olsun.
- Ödeme ve ters kayıt.
- Malzeme son fiyatı ve tedarikçi karşılaştırması.

### Personel 360

- Profil: iletişim, adres, ustalık, acil kişi, IBAN, ödeme yöntemi, maaş günü, işe giriş/çıkış.
- Ücret geçmişi.
- Aylık puantaj, izin, maaş, avans/borç, ekstre ve proje işçiliği sekmeleri.
- Arşiv/aktiflik davranışı.

### Puantaj ve izin

- Aylık ızgara; personel satırı, gün sütunu.
- Toplu durum girişi; normal/fazla mesai ve proje/şantiye.
- Yeni durumlar: annual_leave, sick_leave, excused_leave, public_holiday, weekly_rest.
- `/attendance/check` ile eksik/çakışan kayıtlar.
- İzin hakkı, bakiye, talep/onay/red/iptal ve ledger reversal.
- Resmî tatil ve haftalık çalışma planı ayarları.
- Mevcut Excel toplu puantaj ön izleme/commit akışını arayüze çıkar.

### Maaş dönemleri

Mevcut ilk ekranı tamamla:

- Taslak → hesaplandı → kesinleşti → kapatıldı.
- Eksik puantaj listesini detaylı göster ve ilgili aya/personellere geçiş ver.
- Personel bazlı hesap detayı: normal, mesai, prim, ek kazanç, kesinti, avans mahsubu, net, ödenen, kalan.
- Maaş vade tarihleri.
- Personel finans defteri üzerinden tam/kısmi ödeme.
- Kapatılmış dönem kilidi ve reversal davranışı.
- XLSX/PDF kaydetme.
- `window.confirm` kullanan kritik akışları erişilebilir uygulama modalıyla değiştir.

### Raporlar

- `/reports/staff` ve `/reports/finance` kataloglarını tek rapor merkezinde birleştir.
- Backend'in tüm personel raporları ve 16 finans raporu listelensin.
- Tarih, personel, proje, şantiye, maaş dönemi ve raporun desteklediği filtreler.
- JSON tablo görünümü; `notes` ve `warnings`.
- XLSX/PDF güvenli kaydetme.
- Uzun tabloda sticky header ve yatay/dikey kaydırma.

### Akıllı öngörüler ve tasarruf

- Altı model için readiness, veri sayısı, güven, son run ve model sürümü.
- Model çalıştırma, run history, prediction, feedback ve evaluate.
- Yetersiz veride tahmin gösterme; gereken veriyi anlat.
- `/analytics/savings` sekiz fırsat türü.
- Neden, tahmini parasal etki, güven ve kaynak deep-link.
- ML hiçbir otomatik finansal işlem yapmaz.

### Ayarlar

- Attendance enforcement başlangıcı.
- Şirket maaş günü.
- Negatif izin bakiye tercihi.
- Fazla mesai oranı ve standart gün saati.
- Haftalık çalışma planı ve resmî tatiller.
- Hatırlatma tercihleri.
- Mevcut yedekleme/geri yükleme ve veri dizini.

## Aşama 4 — Bilgi mimarisi ve istemci temizliği

- Eski `/is-takibi` rotası `/projeler` yönlendirmesi olarak kalabilir; kullanılmayan `workTracking.tsx` ve gerçekten ölü CSS/kod kaldırılsın.
- Global arama müşteri, proje, tedarikçi, malzeme ve personeli kapsasın.
- Route bazlı lazy loading/code splitting yap; 500 KB bundle uyarısını gider veya anlamlı biçimde azalt.
- Masaüstü minimum 1024×700 ve 1440×920 düzenlerinde layout taşması olmasın. Ekran otomasyonu kullanmadan CSS/layout ve build testleriyle kontrol et.
- Klavye/focus, modal focus return, loading/error/empty/locked ve dosya kaydetme iptali test edilsin.
- Kullanıcıya geliştirme notu, “hazırlanıyor” rozeti veya sahte veri gösterme.

## Aşama 5 — Birleşik test ve release

### Backend

- Ruff temiz.
- 203+ test; yeni entegrasyon düzeltmeleri için ek testler.
- Tek Alembic head.
- Temiz DB, v0.2.0, gerçek v0.3.0 ve tüm ara head'lerden upgrade.
- Backup/restore.

### Frontend/Desktop

- `npm audit`
- Frontend lint
- Frontend unit/integration testleri
- TypeScript production build
- `node --check desktop/main.cjs`
- `node --check desktop/preload.cjs`
- IPC path/method/content-type ve güvenilmeyen sender testleri veya eşdeğer doğrulama
- Bildirim deduplikasyonu ve deep-link testi
- XLSX/PDF save-dialog iptal/başarı/hata testi

### Uçtan uca smoke

Geçici veri dizininde gerçek sidecar başlat ve en az şu senaryoyu API/istemci kontratı seviyesinde doğrula:

1. Müşteri ve proje oluştur.
2. Bütçe, ek iş ve manuel kalan tahmin gir.
3. Planlı satın alma, sipariş, kısmi/tam teslim ve tedarikçi ödemesi.
4. Personel, ücret, puantaj, izin ve maaş dönemi.
5. Müşteri kaporası, tahsilat planı ve dağıtım.
6. Proje kârlılığı ve drilldown.
7. Takvim, `/today` ve bildirim teslimi.
8. JSON/XLSX/PDF rapor.
9. ML readiness/run ve tasarruf fırsatları.
10. Yedek al, sonrasında kayıt ekle, geri yükle ve kaydın geri alındığını doğrula.

### Paketli uygulama

- Backend PyInstaller build.
- Paketli `ks-core.exe` yeni DB ve gerçek 0.3.0 DB ile smoke.
- Vera PDF yazı tipinin pakete girdiğini ve Türkçe PDF ürettiğini doğrula.
- Frontend build.
- Electron unpacked build.
- NSIS installer.
- Uygulamayı kurmadan mümkün olan paket yapısı, sidecar başlama ve API smoke kontrollerini yap.

## Aşama 6 — Sürüm ve teslim paketi

Tüm kapılar geçtikten sonra sürümü `0.4.0` yap:

- Kök package
- Frontend package gerekiyorsa
- Backend pyproject
- Uygulamanın raporladığı sürüm alanları
- Dokümanlar ve backup metadata uyumu

`C:\Users\Emir\Desktop\KŞ\TESLIM` klasöründe şunları hazırla:

- `Kenan Şenocak Yönetim Setup 0.4.0.exe`
- `SHA256.txt`
- `RELEASE_NOTES.md`
- `TEST_REPORT.md`
- `KULLANIM_BASLANGIC.md`
- Gerekliyse `KNOWN_RISKS.md`

Teslim klasöründe kaynak kod, geçici DB, token, gizli bilgi, `.venv`, node_modules veya debug log bulundurma.

## Aşama 7 — Final Git durumu

- Tüm uygulama ve release değişikliklerini anlamlı commit'lere ayır.
- Birleşik dal temiz ve tüm kapılar geçmişse `codex/p0-desktop-client` dalını `main` ile `--no-ff` birleştir.
- `main` temiz olsun.
- Claude worktree veya eski worktree'leri silme; kullanıcı ayrıca istemedi.
- Google Drive'a kendiliğinden yükleme yapma. Yalnızca yerel `TESLIM` klasörünü hazırla.

## Final kabul kriterleri

- Bir projede sözleşme, tahsilat, bütçe, gerçekleşen, taahhüt, kalan tahmin, bitirme maliyeti, kâr ve en büyük sapmalar tek ekranda.
- Bir müşteride plan, tahsilat, avans, dağıtım, kalan alacak ve yaşlandırma.
- Bir tedarikçide sipariş, teslim, ödeme, kalan borç ve ekstre.
- Bir personelde profil, puantaj, izin, ücret, maaş, avans/borç ve proje işçiliği.
- Takvim görev, ziyaret, tahsilat, ödeme, maaş ve izni kaynağına bağlı gösteriyor.
- Eksik puantaj maaş kesinleştirmeyi engelliyor ve UI eksikleri listeliyor.
- Finansal sayılar kaynak kayıtlara kadar açılıyor.
- Tahminler kesin değer gibi gösterilmiyor.
- Tüm raporlar ve exportlar çalışıyor.
- ML yetersiz veride susuyor; yeterli veride kaynaklı ve güvenli sonuç veriyor.
- Installer başka Windows bilgisayarda kaynak kod/Python/Node gerektirmeden çalşabilecek durumda.

## Yalnızca en sonda raporla

Ara durum sorusu veya onay isteme. Kalan güvenli iş varken durma. Final yanıtında:

```text
GENEL DURUM:
MAIN COMMIT:
SÜRÜM:

TAMAMLANAN MODÜLLER:
BACKEND TESTLERİ:
FRONTEND TESTLERİ:
MIGRATION:
PAKETLİ SIDECAR:
INSTALLER:
TESLİM KLASÖRÜ:
SHA256:

BİLİNEN RİSKLER:
P1/P2'YE BIRAKILANLAR:
```

Installer veya bir test başarısızsa tamamlanmış gibi raporlama; nedeni düzeltip tekrar çalıştır. Gerçek bir dış engel yoksa bütün bu işleri bitirmeden final verme.

