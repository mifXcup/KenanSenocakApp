# Kenan Şenocak Yönetim — Masaüstü Akışları

## 1. Bilgi mimarisi

Uygulamanın ana işi kayıt yığmak değil, kullanıcının şu sorulara hızlı cevap vermesidir:

1. Hangi projede ne kadar maliyet oluştu?
2. Hangi firmaya ne kadar borç kaldı?
3. Ne aldık, ne kadar kullandık ve kayıt ne kadar güvenilir?
4. Yakında hangi ödeme veya operasyon dikkat istiyor?

Ana navigation modül temellidir; her modül aynı desenle çalışır:

`Liste / özet → detay → hareket geçmişi → ekle veya düzelt`

Liste ekranları kullanıcıya bağlam kaybettiren tam sayfa modal açmaz. Detay ve hızlı kayıt için sağ sheet; kapsamlı proje ekranı için route kullanılır.

## 2. Global uygulama davranışı

### Başlangıç

1. Uygulama yerel çekirdeği başlatır.
2. Son veritabanı bütünlük durumu ve son başarılı yedek kontrol edilir.
3. Sorun yoksa son açık modül yüklenir.
4. Yedek eskiyse dashboard üstünde kalıcı ama engellemeyen uyarı görünür.
5. Veri açılamıyorsa boş dashboard gösterilmez; kurtarma ekranı açılır.

### Global arama

`Ctrl+K` ile açılır. Firma, proje, malzeme ve satın alma içinde arar. Sonuçlar tür başlığıyla gruplanır. Kullanıcı ok tuşlarıyla gezer ve Enter ile açar. Arama yerel olduğundan ağ durumu gösterilmez.

### Hızlı ekle

Üst toolbar'daki “Yeni” eylemi açılır menü sunar:

- Satın alma
- Firma ödemesi
- Malzeme kullanımı
- Proje
- Şantiye ziyareti

Menüde kısayollar görünür. Kullanıcının son kullandığı eylem buton label'ına dönüşmez; ana eylem konumu sabit kalır.

## 3. Genel Bakış

### Amaç

Bugün karar gerektiren işletme durumunu göstermek; tüm raporları tek ekrana sıkıştırmamak.

### Yerleşim

Üst özet bandı iki bölümlüdür:

- Sol geniş bölüm: toplam açık firma borcu, yaklaşan ödeme, aktif proje maliyeti
- Sağ dar bölüm: son yedek zamanı ve veri sağlığı

Alt alan:

- “Dikkat gerekenler” kronolojik listesi
- Aktif projeler ve bütçe sapması
- Son satın almalar
- Satın alma harcaması trendi

Üç eşit KPI kartı sırası kullanılmaz. Metrikler çizgiler ve boşlukla gruplanır. Grafik yoksa boş grafik çerçevesi gösterilmez.

### Durumlar

- **Loading:** Özet bandı ve listeler ölçülü skeleton.
- **Empty:** “Henüz işletme kaydı yok” + “İlk satın almayı ekle”.
- **Kısmi hata:** Başarılı bölümler kalır, başarısız bölümde retry.
- **Veri yetersiz:** ML/tahmin alanında “Tahmin için yeterli geçmiş yok”; sahte eğri yok.
- **Uzun içerik:** Dikkat listesi en fazla 8 öğe; devamı ilgili rapora gider.

## 4. Satın alma ekleme

### Giriş noktaları

- `Ctrl+Shift+P`
- Genel Bakış “Yeni” menüsü
- Satın Almalar ekranı birincil eylemi
- Firma detayından “Bu firmadan alış ekle”

### Form sırası

Sağ sheet, 560 px:

1. Tarih — varsayılan bugün, açıkça değiştirilebilir
2. Firma — aranabilir combobox; yoksa inline hızlı firma ekle
3. Malzeme / alınan şey — serbest arama + mevcut malzeme eşleştirme
4. Miktar
5. Birim — adet, kg, metre, m², levha, kutu, litre, paket veya diğer
6. Fiyat yöntemi — “Toplam tutar” varsayılan; isteyen “Birim fiyat” seçer
7. Toplam tutar
8. Ödenen tutar — boşsa sıfır
9. Kalan borç — salt okunur, otomatik hesap
10. İlgili proje — isteğe bağlı
11. Takip türü — kesin / yaklaşık / yalnız tutar
12. Açıklama ve isteğe bağlı belge

KDV, iskonto, vergi matrahı ve fatura satır muhasebesi yoktur.

### Davranış

- Firma seçilince son alışlar küçük bir yardımcı satır olarak gösterilebilir; kullanıcıyı fiyat yönünde zorlamaz.
- `Ödenen > toplam` ise kaydetme engellenir ve açık hata gösterilir.
- Miktar bilinmiyorsa “Yalnız tutar” seçilerek miktar zorunluluğu kalkar.
- Yaklaşık miktar kaydında kullanıcıdan gerekçe istenmez; etiket yeterlidir.
- Kaydetme tek transaction'dır: alış ve varsa ilk ödeme birlikte oluşur veya hiçbiri oluşmaz.
- Başarı toast'ı “Satın alma kaydedildi” der ve “Kaydı aç” sunar.
- Aynı kaydetme tekrar tetiklenirse duplicate oluşmaması backend idempotency kontratına bağlıdır; UI butonu istek sürerken kilitler.

### Klavye

- Tab form sırasını izler.
- Combobox açıkken Enter seçim yapar; formu kaydetmez.
- `Ctrl+S` doğrular ve kaydeder.
- `Esc` değişiklik varsa “Taslak kaybolacak” uyarısı verir.

## 5. Satın Almalar listesi

### Varsayılan görünüm

Kolonlar:

- Tarih
- Firma
- Malzeme
- Miktar + birim
- Toplam
- Ödenen
- Kalan
- Proje
- Takip türü
- Durum / eylem

Filtreler toolbar içinde:

- Tarih aralığı
- Firma
- Proje
- Ödeme durumu
- Takip türü

Filtreler URL yerine masaüstü navigation state'inde saklanabilir; “Filtreleri temizle” açık görünür. Toplamlar aktif filtreye göre hesaplanır ve “Filtrelenmiş toplam” diye etiketlenir.

Satır tıklaması detay sheet'i açar. Satır içinde doğrudan “Ödeme ekle” yalnız kalan borç varsa görünür.

## 6. Firma detayı ve cari geçmiş

### Üst bölüm

- Firma adı ve iletişim bilgisi
- Toplam alış
- Toplam ödeme
- Kalan borç
- Son alış
- Son ödeme

Kalan borç en görünür mali değerdir. “Toplam alış” ile aynı görsel ağırlıkta gösterilmez.

### Sekmeler

1. **Hareketler:** Satın alma, ödeme, iade/düzeltme kronolojik akış
2. **Alınanlar:** Malzeme ve miktar özetleri
3. **Fiyat geçmişi:** Aynı malzemenin dönemsel alış fiyatı
4. **Bilgiler:** İletişim ve notlar

### Firma ödemesi ekleme

1. Firma bağlamı hazır gelir.
2. Tarih seçilir.
3. Tutar girilir.
4. İstenirse açık alışa bağlanır; zorunlu değildir.
5. Ödeme yöntemi ve kısa açıklama isteğe bağlıdır.
6. Kaydetmeden önce “Bu ödeme sonrası tahmini kalan” gösterilir.

Ödeme mevcut borçtan fazlaysa sistem bunu sessizce reddetmez. “Avans olarak kaydet” seçeneği ancak backend modeli destekliyorsa görünür; desteklemiyorsa açık hata gösterilir.

### Hareket çizelgesi

Tablo/timeline hibriti kullanılmaz; erişilebilir ve taranabilir tablo tercih edilir:

- Tarih
- İşlem türü
- Açıklama
- Borç
- Alacak/ödeme
- İşlem sonrası bakiye

Her satırda kaynak kayda gitme eylemi vardır. İptal edilen hareket üstü çizili değil; “İptal edildi” etiketi ve karşı hareket bağlantısıyla gösterilir.

## 7. Proje maliyet ekranı

### Üst hiyerarşi

1. Proje adı, müşteri ve durum
2. Sözleşme bedeli
3. Tahsil edilen
4. Gerçekleşen maliyet
5. Kalan tahmini maliyet
6. Beklenen kâr ve marj

Nakit akışı ile kârlılık ayrı sekme veya ayrı açık başlık altında tutulur; aynı grafikte üst üste bindirilmez.

### Sekmeler

- Özet
- Maliyet hareketleri
- Tahsilatlar
- Malzemeler
- İşçilik
- Şantiye ve ziyaretler
- Belgeler

### Maliyet dökümü

Kategori bazında:

- Malzeme
- Atölye işçiliği
- Şantiye/montaj
- Nakliye/araç
- Dış hizmet
- Genel gider payı
- Fire/yeniden imalat
- Garanti/düzeltme

Her kategori satırı bütçe, gerçekleşen, kalan tahmin ve sapma gösterir. Sapma yalnız kırmızı/yeşille anlatılmaz; tutar, yüzde ve “bütçeyi aştı / bütçe içinde” metni kullanılır.

### Tahmin görünümü

Makine öğrenmesi yeterli veri olmadan skor göstermez. Yeterli olduğunda:

- Tahmin değeri
- Güven seviyesi
- Kullanılan tarih aralığı
- Başlıca etkileyen veriler
- “Tahmini maliyete uygula” yerine “Karşılaştır” eylemi

Kullanıcı onayı olmadan bütçe veya kayıt değiştirilmez.

## 8. Malzeme hareketi

### Liste

Kolonlar:

- Tarih
- Malzeme
- Hareket: alış / kullanım / fire / iade / düzeltme
- Miktar + birim
- Takip türü
- Proje
- Tahmini kalan

“Tahmini kalan” yanında son doğrulama tarihi görünür. Uzun süredir sayım yapılmadıysa metin “Güncelliği düşük” der; alarm rengi tek başına kullanılmaz.

### Kullanım ekleme

1. Malzeme
2. Proje
3. Tarih
4. Kayıt şekli: kesin miktar / yaklaşık miktar / yalnız maliyet
5. Miktar + birim veya tutar
6. Hareket türü: kullanım / fire / düzeltme
7. Açıklama

Kullanım tahmini stoku negatife düşürürse kayıt engellenmez; kullanıcıya “Kayıtlara göre miktar sıfırın altına inecek” uyarısı gösterilir. Kullanıcı “Yine de kaydet” ile devam edebilir. Bu tercih audit log'a yazılır.

### Sayım doğrulama

Malzeme detayında “Sayımı doğrula” eylemi:

1. Fiziksel miktar girilir.
2. Sistem beklenen ile farkı gösterir.
3. Kullanıcı gerekirse açıklama ekler.
4. Düzeltme hareketi oluşturulur; geçmiş hareketler değiştirilmez.

## 9. Ayarlar ve yedekleme

### Ayarlar grupları

- İşletme bilgileri
- Birimler ve varsayılanlar
- Veri ve yedekleme
- Görünüm ve tablo yoğunluğu
- Kısayollar
- Hakkında ve sürüm

### Yedekleme merkezi

Üstte:

- Son başarılı yedek
- Otomatik yedek durumu
- Yedek klasörü
- Bir sonraki planlı yedek

Eylemler:

- Şimdi yedekle
- Yedek klasörünü aç
- Yedekten geri yükle
- Yedek bütünlüğünü doğrula

“Yedekten geri yükle” geri döndürülemez etkiye yakın kritik akıştır:

1. Yedek dosyası native file dialog ile seçilir.
2. Sistem sürüm ve bütünlük kontrolü yapar.
3. Mevcut verinin işlem öncesi güvenlik yedeği alınır.
4. Kullanıcı hedef yedeğin tarihini ve etkisini görür.
5. Açık onay sonrası uygulama yeniden başlatılır.
6. Başarı/başarısızlık sonrası net sonuç ekranı gelir.

Sadece “Emin misiniz?” modalı yeterli değildir.

## 10. Tüm ekranlar için state matrisi

| State | Arayüz davranışı |
| --- | --- |
| Loading | Layout ölçüsünü koruyan skeleton; eylemler gerekmedikçe kaybolmaz |
| Empty | Neden + bir sonraki doğru eylem; sahte demo veri yok |
| Error | Nelerin kaydolmadığı + retry/kopyalanabilir hata kodu |
| Success | Kısa toast; bağlamı değiştirmeden doğrulama |
| Permission | Hangi yerel klasör/işlem izninin neden gerektiği |
| Offline | Uygulama yerel çalıştığı için “internet yok” hata değildir; yalnız harici işlev varsa belirtilir |
| Backend unavailable | Kaydetme kapalı, mevcut güvenli cache varsa salt okunur görünüm, yeniden başlat seçeneği |
| Long content | Sticky header, kendi içinde scroll, kesilmeyen Türkçe metin, kontrollü truncation + tooltip |
| Unsaved | Route/pencere kapanışında kayıp uyarısı |
| Duplicate | İkinci kayıt oluşturmak yerine önceki işlem sonucu gösterilir |

## 11. Resizable window davranışı

### 1440 px ve üstü

- Açık sidebar
- Ana içerik + sağ bağlamsal detay aynı anda
- Tabloda önerilen kolonların tümü

### 1120–1439 px

- Açık veya kullanıcı tercihine göre dar sidebar
- Sağ panel overlay sheet olur
- İkincil tablo kolonları kullanıcı ayarına göre gizlenebilir

### 960–1119 px

- İkon sidebar
- Filter toolbar ikinci satıra sarar
- Detay tam genişlik sheet
- Kritik mali kolonlar sabit kalır; diğerleri yatay scroll

### 960 px altı

İlk sürümün destek sınırıdır. Uygulama çalışabilir fakat yoğun tablolar için “Pencereyi genişletin” yardımcı banner'ı gösterilir. Veri girişi yine tek kolon form ile tamamlanabilir. Kontroller üst üste binmez.

## 12. Yağmur için uygulama brief'i

### Component sınırları

- `AppShell`: native pencere içi navigation ve toolbar
- `PageHeader`: başlık, açıklama, ana eylem, kapsam filtresi
- `DataTable`: kolon, sıralama, filtre, selection, empty/loading/error state
- `MoneyValue`: TRY biçimleme, tabular nums, negatif/pozitif semantik
- `ConfidenceBadge`: kesin/yaklaşık/yalnız tutar
- `FormField`: label, helper, error, readonly/disabled
- `SideSheet`: form ve detay varyantı
- `StatusBanner`: sistemsel kalıcı uyarı
- `BackupStatus`: son yedek ve sağlık bilgisi

### State sınırları

- Remote/network cache kütüphanesi yalnız local backend isteklerinde de loading/error/invalidation disiplini sağlamak için kullanılabilir.
- Form draft state component içinde; sunucu verisi global store'a kopyalanmaz.
- Para ve miktar hesaplarının otoritesi backend'dir; frontend yalnız anlık önizleme yapar.
- Global state yalnız pencere tercihi, aktif kapsam ve kullanıcı görünüm tercihleri için kullanılır.

### Kabul kontrolü

- Dashboard, satın alma, firma ve proje ana akışları yalnız klavyeyle tamamlanır.
- 960×640, 1120×700, 1360×860 ve 1440×900 test edilir.
- Windows %125 ve %150 ölçeklemede taşma kontrol edilir.
- Loading, empty, error, success ve backend unavailable durumlarının ekran görüntüsü alınır.
- Tablo para sütunları sağa hizalı ve tabular rakamlıdır.
- Şeffaf yüzey üzerinde tablo veya uzun form bulunmaz.
- Harici font/CDN/ağ isteği yoktur.
- Sahte veri prod build'e girmez; örnekler yalnız açıkça işaretli test fixture'larında bulunur.
