# Kullanıma başlangıç

1. KŞ açıksa kapatın. `Kenan Şenocak Yönetim Setup 0.5.7.exe` dosyasını çalıştırın; 0.5.6 kuruluysa önceki kurulum konumunu seçin. Uygulamayı kaldırmanız gerekmez.
2. Uygulamayı açın. İlk açılışta yerel veritabanı otomatik hazırlanır; eski kurulum varsa yükseltme öncesi yedek alınır.
3. Ayarlar > Yedekleme bölümünden düzenli olarak manuel yedek alın; listedeki **Dosyaya kaydet** ile `.ksbackup` dosyasını ayrı bir konuma saklayın.
4. Önce müşteri, proje, tedarikçi, malzeme ve personel kartlarını oluşturun. Ardından satın alma, tahsilat, puantaj ve gider kayıtlarını girin.

## Fiyat motorunu kullanma

1. Proje Takip ekranında projeyi seçip **Proje ürünleri ve teklifler > Ürün ekle** yolunu açın.
2. Ürün türünü, kapsamını, miktarını, aksesuar seviyesini, zorluğunu ve verilen teklif tutarını kaydedin.
3. MDF gibi maliyet etkilerinde teklif içindeki payı, o günkü birim fiyatı ve ilgili malzemeyi seçin.
4. Yeni projede aynı ürün türü ve birimiyle fiyat alanını boş bırakarak yeni ürün oluşturun.
5. **Fiyat öner** düğmesiyle güncel düşük/merkez/yüksek aralığı ve kullanılan eski işleri görün.
6. Müşterinin kabul ettiği fiyatı kaydedin. Proje tamamlandığında ürün maliyetini ve proje giderlerini işleyip kâr sonucunu inceleyin.
7. Akıllı Öngörüler > Fiyat Öğrenimi bölümünden veri kapsamını ve manuel işçilik/piyasa referanslarını yönetin.

Öneri karar desteğidir; otomatik teklif göndermez veya finansal işlem oluşturmaz. Başka bilgisayara taşıma için `.ksbackup` dosyasını yeni bilgisayara kopyalayın, Ayarlar > Yedekleme > **Dosyadan yedek yükle** ile aktarın ve listedeki **Geri yükle** işlemini kullanın. Uygulama veri hizmeti hatası nedeniyle açılmazsa açılış penceresindeki **Dış yedekten geri yükle** seçeneğini kullanın.
