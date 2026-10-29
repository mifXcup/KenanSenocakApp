# Kenan Şenocak Yönetim

Mobilya atölyesi için çevrimdışı çalışan Windows masaüstü yönetim uygulaması.

## İlk sürüm kapsamı

- Tedarikçi kartları ve iletişim bilgileri
- Malzeme kartları; adet, kg, metre, levha ve benzeri birimler
- Tam, yaklaşık veya yalnızca değer bazlı stok yaklaşımı
- Proje kartları ve proje bazlı satın alma/maliyet görünümü
- Basit satın alma kaydı: ne alındı, miktar, birim, fiyat ve tedarikçi
- Tedarikçi borçları, ödemeler ve geçmiş hareketler
- Yönetim paneli ve satın alma raporları
- Doğrulanabilir yerel yedekleme ve geri yükleme
- Personel, şantiye, çalışma ve avans/ücret kayıtları
- Nakliye, montaj, şantiye ve diğer proje giderleri
- Birleşik proje maliyeti, bütçe farkı ve tahmini kâr
- Kontrollü Excel şablonları, ön izleme ve toplu içe aktarma
- Excel ve PDF rapor dışa aktarma
- Yerel fiyat anomalisi, yeniden alım ve bütçe riski tahminleri
- Geçmiş ürün tekliflerini güncel malzeme/işçilik maliyetlerine taşıyan açıklanabilir fiyat önerileri

Bu sürüm bilinçli olarak KDV, iskonto ve ayrıntılı fatura/muhasebe işlemleri içermez.

## Kurulum

`TESLIM/Kenan Şenocak Yönetim Setup 0.5.0.exe` dosyasını çalıştırın.

Uygulama yerel SQLite veritabanı kullanır. Veriler ve yedekler Windows kullanıcı veri dizininde saklanır. Programı güncellemeden veya farklı bir bilgisayara taşımadan önce Ayarlar > Yedekleme bölümünden manuel yedek alın.

Kurulum paketi henüz ticari bir kod imzalama sertifikasıyla imzalanmadığı için Windows ilk çalıştırmada yayıncı uyarısı gösterebilir.

## Geliştirme

Gereksinimler: Node.js, npm ve Python 3.14.

```powershell
npm install
npm --prefix frontend install
npm run dev
```

Kontroller:

```powershell
npm test
npm run lint
npm --prefix frontend run build
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
backend\.venv\Scripts\python.exe -m ruff check backend
```

Windows kurulum paketi:

```powershell
npm run dist
```

## Yerel tahmin modelleri

Tahminler hiçbir veriyi dışarı göndermez. Fiyat modeli en az 5, yeniden alım modeli en az 4 kayıt ister. Proje bütçe modeli en az 4 maliyet hareketi olmadan sonuç üretmez. Yetersiz veri, tahmin yerine açıkça bildirilir.

Ürün fiyat öneri motoru Proje Takip > Ürünler ve fiyat önerisi alanındadır. İlk öneri için aynı ürün türü ve biriminde fiyatı bulunan en az bir geçmiş kayıt gerekir; az kayıtta sonuç düşük güvenli aralık olarak gösterilir. Akıllı Öngörüler > Fiyat Öğrenimi ekranı fiyatlı geçmiş, gerçekleşen maliyet ve maliyet payı kapsamını gösterir.

## Dağıtım notu

Ticari dağıtım öncesinde kurulum paketinin kod imzalama sertifikasıyla imzalanması gerekir.
