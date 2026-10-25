# Kenan Şenocak Yönetim — Masaüstü Tasarım Sistemi

## 1. Tasarım kararı

**Birincil mod:** Sedan Design System Mode  
**İkincil modlar:** Desktop UX Mode, Accessibility and Performance Mode  
**Neden:** Ürün uzun süre açık kalan, para ve operasyon verisi gösteren bir Windows uygulamasıdır. Görsel gösteriden çok hızlı tarama, hatasız veri girişi, klavye kullanımı ve güven hissi önemlidir.

Tasarım yönü **“Sakin Atölye”** olarak adlandırılır: sıcak beyaz zemin, kontrollü saydam kabuk katmanları, koyu kömür metin ve tek ahşap-tonlu vurgu. Şeffaflık dekorasyon değil, pencere katmanlarını ayırmak için kullanılır. Tablolar, formlar ve mali özetler tam opak yüzeylerde kalır.

`design-taste-frontend-v1` ayarları kullanıcı talebine göre değiştirilmiştir:

- Design variance: **4/10** — düzenli ama steril olmayan asimetri
- Motion intensity: **2/10** — yalnız durum değişimi ve geri bildirim
- Visual density: **6/10** — masaüstü operasyonu için yoğun ama ferah

`color-expert` bu kurulumda yalnız katalog girdisidir; tam upstream araç seti yüklü değildir. Buna rağmen renk sistemi OKLCH tabanlı kurulmuş, roller ayrıştırılmış ve WCAG 2.2 AA hedefi tanımlanmıştır. Uygulama aşamasında gerçek render renkleri otomatik kontrast testiyle doğrulanmalıdır.

## 2. Tasarım ilkeleri

1. **Veri dekorasyondan üstündür.** Para, borç, miktar ve tarih bilgileri arka plan efektlerinden etkilenmez.
2. **Tek bakışta yön.** Her ekranda bir birincil eylem ve en fazla iki ikincil eylem görünür.
3. **Kayıt güveni görünürdür.** Kesin, yaklaşık ve yalnız tutar kayıtları renk yanında metin ve ikonla ayrılır.
4. **Muhasebe taklidi yapılmaz.** KDV, iskonto ve resmi fatura dili arayüze sokulmaz.
5. **Klavye birinci sınıf girdidir.** Tab sırası, kısayollar, Enter/Escape davranışı ve görünür odak zorunludur.
6. **Hata geri alınabilir olmalıdır.** Silme yerine iptal/arşiv; uygun hareketlerde “Geri al” kullanılır.
7. **Sahte kesinlik yoktur.** Stok ve makine öğrenmesi sonuçları güven seviyesiyle gösterilir.

## 3. Primitive tokenlar

### 3.1 Renk paleti

OKLCH ana kaynaktır; aşağıdaki hex değerleri eski WebView veya export yüzeyleri için yaklaşık fallback'tir.

| Token | OKLCH | Hex fallback | Kullanım |
| --- | --- | --- | --- |
| `white` | `oklch(1 0 0)` | `#ffffff` | Ana opak yüzey |
| `warm-25` | `oklch(0.985 0.006 78)` | `#fcfaf7` | Uygulama zemini |
| `warm-50` | `oklch(0.965 0.008 76)` | `#f7f3ee` | İkincil zemin |
| `warm-100` | `oklch(0.925 0.010 72)` | `#eae4dd` | İnce sınır |
| `warm-200` | `oklch(0.855 0.014 68)` | `#d8cfc5` | Güçlü sınır |
| `warm-500` | `oklch(0.53 0.020 60)` | `#766d65` | İkincil metin |
| `warm-700` | `oklch(0.34 0.018 55)` | `#453f3a` | Gövde metni |
| `warm-900` | `oklch(0.22 0.014 50)` | `#282421` | Başlık ve mali değer |
| `wood-50` | `oklch(0.955 0.025 55)` | `#faeee5` | Seçili satır / yumuşak vurgu |
| `wood-500` | `oklch(0.50 0.125 47)` | `#92502f` | Birincil eylem |
| `wood-600` | `oklch(0.43 0.115 45)` | `#773d24` | Basılı / hover eylem |
| `green-600` | `oklch(0.47 0.095 145)` | `#42704a` | Başarılı / ödendi |
| `amber-600` | `oklch(0.55 0.115 78)` | `#8d621c` | Yaklaşan / yaklaşık |
| `red-600` | `oklch(0.49 0.145 28)` | `#a33d35` | Hata / gecikmiş / yıkıcı |
| `blue-600` | `oklch(0.47 0.105 245)` | `#35658c` | Bilgi mesajı; marka vurgusu değildir |

Kurallar:

- Marka/eylem vurgusu yalnız `wood-*` ailesidir.
- Başarı, uyarı, hata ve bilgi renkleri yalnız semantik geri bildirim için kullanılır.
- Durum hiçbir zaman yalnız renkle anlatılmaz; ikon ve açık metin zorunludur.
- Saf siyah, neon, mor/mavi gradyan ve dış glow kullanılmaz.

### 3.2 Aralık sistemi

4 px tabanlı ölçek:

| Token | Değer |
| --- | --- |
| `space-1` | 4 px |
| `space-2` | 8 px |
| `space-3` | 12 px |
| `space-4` | 16 px |
| `space-5` | 20 px |
| `space-6` | 24 px |
| `space-8` | 32 px |
| `space-10` | 40 px |
| `space-12` | 48 px |

Sayfa iç boşluğu 24 px; dar pencerede 16 px. Form alanları arasında 16 px; aynı grubun label–input arası 8 px. Büyük bölüm arası 32 px'i geçmez.

### 3.3 Radius

| Token | Değer | Kullanım |
| --- | --- | --- |
| `radius-sm` | 6 px | Badge, küçük kontrol |
| `radius-md` | 8 px | Input, button |
| `radius-lg` | 12 px | Panel, popover |
| `radius-xl` | 16 px | Sheet, modal |

Yuvarlaklık 16 px üzerinde kullanılmaz. Hap/pill yalnız durum rozeti veya kısa filtre için uygundur.

### 3.4 Elevation ve saydamlık

| Token | Değer | Kullanım |
| --- | --- | --- |
| `elevation-0` | gölge yok | Tablo, ana içerik |
| `elevation-1` | `0 1px 2px rgba(61,48,37,.06)` | Toolbar, panel |
| `elevation-2` | `0 12px 32px rgba(61,48,37,.10)` | Popover, dropdown |
| `elevation-3` | `0 24px 56px rgba(61,48,37,.16)` | Modal |

Saydam kabuk yüzeyi: `rgba(255,255,255,.82)` + 1 px `rgba(255,255,255,.72)` iç sınır + en fazla 12 px backdrop blur. Yalnız sidebar, üst toolbar ve modal kabuğunda kullanılabilir. Liste, tablo, form ve tooltip'te blur yoktur.

### 3.5 Motion

| Token | Değer |
| --- | --- |
| `duration-fast` | 100 ms |
| `duration-base` | 160 ms |
| `duration-slow` | 220 ms |
| `ease-standard` | `cubic-bezier(.2, 0, 0, 1)` |
| `ease-exit` | `cubic-bezier(.4, 0, 1, 1)` |

- Sürekli/infinite animasyon yoktur.
- Hover, focus ve toast girişleri opacity + en fazla 4 px transform kullanır.
- Buton basılı durumunda `translateY(1px)` veya `scale(.99)` uygulanabilir.
- `prefers-reduced-motion` altında transform kaldırılır; yalnız anlık renk/opacity değişimi kalır.
- Blur, width, height, top veya left animasyonu yapılmaz.

## 4. Semantic tokenlar

| Rol | Light değer |
| --- | --- |
| `surface.background` | `warm-25` |
| `surface.primary` | `white` |
| `surface.secondary` | `warm-50` |
| `surface.elevated` | `white` |
| `surface.glass` | `rgba(255,255,255,.82)` |
| `text.primary` | `warm-900` |
| `text.secondary` | `warm-500` |
| `text.inverse` | `white` |
| `icon.primary` | `warm-700` |
| `icon.muted` | `warm-500` |
| `border.subtle` | `warm-100` |
| `border.strong` | `warm-200` |
| `action.primary` | `wood-500` |
| `action.primary-hover` | `wood-600` |
| `action.primary-pressed` | `wood-600` |
| `action.secondary` | `white` + `border.strong` |
| `selection.background` | `wood-50` |
| `feedback.success` | `green-600` |
| `feedback.warning` | `amber-600` |
| `feedback.error` | `red-600` |
| `feedback.info` | `blue-600` |
| `focus.ring` | `wood-500` dışta 2 px + beyaz ayırıcı 1 px |
| `disabled.surface` | `warm-50` |
| `disabled.content` | `warm-500` %65 opacity |

İlk sürüm light-only olabilir. Dark mode eklenirse aynı semantic isimler korunmalı; primitive değerler değiştirilmelidir. Dark mode için yalnız renkleri ters çevirmek kabul edilmez; tablolar ve durum renkleri yeniden kontrast testinden geçmelidir.

## 5. Tipografi

Uygulama çevrimdışı çalışacağı için fontlar paket içine alınır. Uzak font isteği yapılmaz.

**Aile:** `Geist Sans`, fallback `Segoe UI`, `Arial`, sans-serif  
**Sayısal alan:** `Geist Mono`, fallback `Cascadia Mono`, monospace; `font-variant-numeric: tabular-nums`

| Seviye | Boyut / Satır | Ağırlık | Kullanım |
| --- | --- | --- | --- |
| `display` | 28 / 36 px | 650 | Dashboard ana rakamı; seyrek |
| `title` | 24 / 32 px | 650 | Sayfa başlığı |
| `heading` | 18 / 26 px | 600 | Bölüm başlığı |
| `body` | 15 / 22 px | 450 | Standart içerik |
| `body-small` | 13 / 19 px | 450 | Tablo ve ikincil içerik |
| `label` | 13 / 18 px | 600 | Form label ve tablo başlığı |
| `caption` | 12 / 17 px | 500 | Meta, yardımcı metin |

- Büyük başlıklar tümü büyük harf yazılmaz.
- Türkçe metinlerde 65–75 karakter üzerindeki açıklamalar iki satırla sınırlandırılmaz; gerektiğinde sarar.
- Para sağa hizalanır ve tabular rakam kullanır.
- `₺` simgesi tutarla aynı satırda kalır; dar sütunda kesilmek yerine sütun yatay kaydırılır.
- Windows metin ölçeği %125 ve %150 ile test edilir.

## 6. Masaüstü kabuğu ve yerleşim

### 6.1 Pencere

- Native Windows çerçevesi korunur; özel başlık çubuğu ilk sürümde yapılmaz.
- Önerilen başlangıç: 1360 × 860 px.
- Desteklenen minimum: 960 × 640 px.
- 1120 px altında sidebar ikon+tooltip biçimine daralır.
- 960 px altında detay panelleri tam ekran sheet'e dönüşür; ana akış kaybolmaz.
- Son pencere boyutu ve konumu güvenli biçimde hatırlanır; ekran dışında kalan koordinat geri yüklenmez.

### 6.2 Uygulama iskeleti

- Sol navigation: açık 232 px, dar 64 px.
- Üst toolbar: 56 px; sayfa başlığı, kapsam filtresi, global arama ve hızlı ekle.
- İçerik: minimum 16 px, normal 24 px padding.
- Ana içerik maksimum genişlikle sınırlandırılmaz; veri tabloları pencereyi kullanır.
- Detail panel: 420–560 px, kritik formda en fazla 640 px.
- Alt durum çubuğu: yalnız yedekleme, çevrimdışı çekirdek veya işlem durumu gerektiğinde 28 px.

Navigation sırası:

1. Genel Bakış
2. Projeler
3. Satın Almalar
4. Firmalar
5. Malzemeler
6. Personel ve Şantiye
7. Raporlar
8. Ayarlar

Alt bölümde yalnız “Yedek durumu” ve “Yardım” bulunur. Modül sayısı arttığında ikincil sayfalar ilgili modül içinde sekme olur; sidebar sınırsız büyütülmez.

## 7. Component tokenları ve davranışları

### 7.1 Button

Varyantlar: `primary`, `secondary`, `quiet`, `destructive`.

- Standart yükseklik 40 px; kritik ana eylem 44 px.
- Horizontal padding 14–16 px; ikon–label arası 8 px.
- Tek ikonlu buton en az 40 × 40 px; görünür tooltip ve `aria-label` zorunlu.
- Loading durumunda genişlik değişmez; label kalır, başına küçük progress göstergesi gelir.
- Disabled yalnız soluklaştırılmaz; cursor ve `aria-disabled`/native disabled uygulanır.
- Focus: 2 px vurgu halkası + 1 px beyaz ayırıcı.
- Destructive eylem varsayılan olarak kırmızı dolu değildir; onay ekranındaki nihai eylemde kırmızı olur.

### 7.2 TextField ve sayı girdisi

- Yükseklik 40 px; çok satırlı alan minimum 88 px.
- Label her zaman input üstündedir; placeholder label yerine geçmez.
- Para ve miktar alanlarında birim suffix olarak görünür, değerin parçası olmaz.
- Durumlar: empty, filled, focused, error, disabled, readonly.
- Error metni input altında, ikon + açık cümleyle gösterilir.
- Sayısal alan yazarken yerel biçimi kabul eder; kayıtta normalize eder.
- `Enter`: güvenli ve doğrulanmış formu kaydeder. Çok satırlı input'ta Enter yeni satırdır.
- `Escape`: değişiklik varsa kayıp uyarısı gösterir; değişiklik yoksa paneli kapatır.

### 7.3 Select / combobox

- Firma, proje ve malzeme seçiminde arama yapılabilir combobox kullanılır.
- “Yeni firma ekle” gibi bağlamsal eylem listenin sonunda açık metinle yer alır.
- Son kullanılan seçenekler ilk 5 sırada gösterilebilir; algoritmik yeniden sıralama kullanıcı ararken listeyi oynatmaz.
- Klavye: oklar, Enter, Escape ve ilk harfle arama.

### 7.4 Table

- Başlık 40 px, normal satır 44 px; yoğun görünüm tercihi 36 px.
- Yüzey tam opak beyazdır; backdrop blur yoktur.
- Dikey çizgi kullanılmaz; satırlar ince yatay sınır ve boşlukla ayrılır.
- Header sticky; ilk kimlik sütunu isteğe bağlı sticky.
- Metin sola, tarih sola, para ve miktar sağa hizalanır.
- Sıralama yönü ikon + erişilebilir metinle belirtilir.
- Satır hover'ı yalnız fare geri bildirimidir; klavye focus ile aynı eylemlere erişilir.
- Satır eylemleri üç nokta menüsünde olabilir; en sık eylem satır sonunda açık ikon olarak kalabilir.
- Kolon görünürlüğü ve yoğunluk kullanıcı tercihi olarak saklanır.
- 100+ satırda sayfalama veya sanallaştırma düşünülür; tüm DOM'a basılmaz.
- Boş tabloda yalnız “Kayıt yok” denmez; neden ve uygun birincil eylem gösterilir.

### 7.5 Card / metric group

- Kart yalnız bağımsız bilgi grubu veya seçilebilir nesne için kullanılır.
- Radius 12 px, border `subtle`, gölge çoğu durumda yoktur.
- Dashboard metrikleri üç eşit kart sırası yerine 2+1 asimetrik grid veya çizgilerle bölünmüş tek özet bandında düzenlenir.
- State: static, hover/pressed, selected, disabled, loading.
- Para metrikleri trend yanında kaynak dönemini de gösterir; veri yoksa tire değil “Veri yok” yazar.

### 7.6 Sheet ve modal

- Ekleme/düzenleme: sağ sheet.
- Geri döndürülemez onay: merkez modal.
- Sheet başlığı ve alt eylem alanı sticky; içerik kendi içinde scroll olur.
- Modal açıldığında focus ilk anlamlı kontrole taşınır; kapatınca tetikleyiciye döner.
- Arka plan scrim `rgba(40,36,33,.28)`; yoğun blur yoktur.

### 7.7 Badge ve kayıt güveni

| Durum | Etiket | Görsel |
| --- | --- | --- |
| Kesin | `Kesin` | check ikon + nötr/yeşil |
| Yaklaşık | `Yaklaşık` | tilde/uyarı ikon + amber |
| Yalnız tutar | `Yalnız tutar` | para ikon + nötr |
| Gecikmiş | `Gecikmiş` | saat/uyarı ikon + kırmızı |
| Ödendi | `Ödendi` | check ikon + yeşil |

Rozet metni saklanmaz; yalnız nokta veya renk kullanılmaz.

### 7.8 Toast / banner

- Başarılı kayıt: sağ alt toast, 5 saniye; işlem uygunsa “Geri al”.
- Hata: alanla ilişkiliyse inline; sistemsel ise kalıcı banner + “Ayrıntıyı kopyala”.
- Yedek alınamadı veya veri dosyası riski toast ile geçiştirilemez; üstte kalıcı banner kullanılır.
- Aynı mesaj üst üste yığılmaz; sayaçla birleştirilir.

### 7.9 Skeleton, empty ve error

- Skeleton gerçek layout ölçülerini taklit eder; yuvarlak spinner ana loading deseni değildir.
- İlk yükleme 300 ms'den kısa ise skeleton göstermemek için küçük gecikme uygulanabilir.
- Empty state bir başlık, bir açıklama ve en fazla bir ana eylem içerir.
- Error state “Bir şeyler ters gitti” gibi belirsiz kalmaz; kaydedilmemiş veri durumu ve güvenli tekrar yolu söylenir.

## 8. İkonografi

- Yalnız `@phosphor-icons/react` kullanılmalı; paket kurulmadan import edilmemeli.
- Standart ağırlık `regular`, stroke hissi tutarlı; aktif navigation için `fill` yerine `duotone` kullanılabilir.
- Emojiler arayüz metni, ikon veya boş durum çizimi olarak kullanılmaz.
- İkon tek başına kritik anlam taşımaz; tooltip/label ile desteklenir.

## 9. Klavye kısayolları

| Kısayol | Eylem |
| --- | --- |
| `Ctrl+K` | Global arama / komut alanı |
| `Ctrl+N` | Mevcut modülde yeni kayıt |
| `Ctrl+S` | Açık formu doğrula ve kaydet |
| `Ctrl+Shift+P` | Hızlı satın alma |
| `Ctrl+Shift+O` | Firma ödemesi ekle |
| `Ctrl+B` | Yedekleme merkezini aç |
| `Esc` | Açık popover/sheet'i güvenli kapat |
| `F1` | Bulunulan ekranın yardımını aç |

Kısayollar menü ve tooltip'te görünür olmalıdır. Text input içindeki sistem kısayolları ezilmez.

## 10. Erişilebilirlik kabul kriterleri

- WCAG 2.2 AA kontrast hedeflenir; kritik metinler ve kontroller otomatik test edilir.
- Tüm ana akış yalnız klavyeyle tamamlanabilir.
- Focus sırası görsel sırayı izler ve focus hiçbir zaman görünmez olmaz.
- Hata metni alanla `aria-describedby` üzerinden ilişkilendirilir.
- Tablolarda doğru header ilişkisi, sıralama durumu ve açıklayıcı başlık vardır.
- Minimum ana hedef 40 px; dokunmatik ekran ihtimalinde 44 px tercih edilir.
- `%125` ve `%150` Windows metin ölçeğinde metin kesilmez.
- `prefers-reduced-motion` desteklenir.
- Para ve borç durumu yalnız renk ile anlatılmaz.

## 11. Frontend uygulama notu

- Tüm tokenlar CSS custom properties olarak tanımlanmalı; component içinde rastgele hex/radius kullanılmamalı.
- Tailwind sürümü `package.json` üzerinden doğrulanmalı; sürüme uygun entegrasyon seçilmeli.
- Electron renderer geniş filesystem/shell yetkisi almamalı; dosya seçimi ve yedek konumu narrow IPC üzerinden yürümeli.
- Native pencere frame'i ilk sürümde korunmalı.
- Dashboard'ta Framer Motion, GSAP veya perpetual animasyon gerekmiyor. CSS transition yeterlidir.
- Remote font, görsel veya CDN bağımlılığı kullanılmamalı.

## 12. Tasarım riskleri

1. Şeffaflığı artırmak tablo okunabilirliğini hızla düşürür; opacity kullanıcı ayarı yapılmamalı.
2. Çok sayıda KPI kartı dashboard'ı duvar panosuna çevirir; karar gerektirmeyen metrikler raporlara taşınmalı.
3. Yaklaşık stok bilgisini kesin rakam gibi göstermek güven kaybettirir; etiket zorunludur.
4. Satın alma formuna sonradan muhasebe alanları eklemek akışı bozar; kapsam kararı korunmalıdır.
5. Özel titlebar erken aşamada pencere, erişilebilirlik ve DPI sorunları üretir; ertelenmelidir.
6. `color-expert` tam paketi olmadığı için palette geniş gamut ve renk körlüğü simülasyonu implementasyon testinde ayrıca yapılmalıdır.
