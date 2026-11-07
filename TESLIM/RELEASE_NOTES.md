# Kenan Şenocak Yönetim 0.5.9 — güvenilir GitHub paketi

- Windows kurulum paketi ve `latest.yml` güncelleme bildirimi bağımsız GitHub Release adımında birlikte yayımlanır.
- Uygulama Ayarlar ekranına güncelleme denetleme, indirme ve yeniden başlatarak yükleme akışı eklendi.
- Kaynak kodu ve sonraki geliştirmeler `mifXcup/KenanSenocakApp` deposuna gönderilir.

## 0.5.8 / 0.5.7 — proje ürün toplamları

- Proje ekleme ve düzenlemede detay alanı, ürün eklemede kapsam ve iş notları eklendi.
- Teklif tutarları yazılırken binlik ayırıcı ekleniyor; ürün zorluğu Kolay, Orta, Zor olarak seçiliyor.
- Ürün oluşturma formundan hedef marj ve gerçekleşen maliyet kaldırıldı. Ürün maliyeti proje tamamlanınca girilebiliyor.
- 0.5.2 üzerine aynı kurulum konumunda uygulanabilen Windows kurulum paketi.

- Ürün kartlarında teklif durumu seçenekleri kaldırıldı; yalnız onaylanan proje ürünleri üzerinden ilerleniyor.
- Teklif tutarı ve anlaşılan fiyat ayrı alanlar olarak düzenlenebiliyor (örnek: 10.000.000 TL / 9.500.000 TL).
- Ürün adı, açıklaması, miktarı, fiyatı, zorluğu ve notu düzenlenebiliyor; ürün silme işlemi arşivleme olarak eklendi.
- 0.5.3 üzerine aynı kurulum konumunda uygulanabilen Windows kurulum paketi.
- Ürün kartında teklif ve anlaşılan fiyat artık ayrı ayrı gösteriliyor.
- 0.5.4 üzerine aynı kurulum konumunda uygulanabilen Windows kurulum paketi.
- Ürünler bölümünde teklif toplamı ve anlaşılan ürünler toplamı gösteriliyor.
- 0.5.5 üzerine aynı kurulum konumunda uygulanabilen Windows kurulum paketi.
- Ürün toplamı proje anlaşma tutarından farklıysa fark uyarısı ve indirim / fark tutarı gösteriliyor.
- 0.5.6 üzerine aynı kurulum konumunda uygulanabilen Windows kurulum paketi.

## 0.5.2

- Siyah beyaz Swiss Industrial Print arayüzü: köşeli kontroller, yüksek kontrastlı gezinme, büyük başlıklar ve çizgili veri alanları.
- 0.5.1 üzerine aynı kurulum konumunda uygulanabilen Windows kurulum paketi.
- Mevcut çalışma kopyasındaki kart okuyucu, proje gideri, rapor, satın alma ve veri araçları geliştirmeleri bu test paketine dahil edildi.
- Veritabanı kullanıcı veri dizininde kalır; yeni şema gereken kurulumlarda yükseltme öncesi yedek oluşturulur.

## 0.5.1

- Malzemeler ekranında kullanım, fire, iade ve sayım artışı kaydı ile tahmini bakiye görünümü eklendi.
- Rapor Merkezi 500 satırlık sayfalar arasında geziniyor ve görüntülenen aralığı gösteriyor.
- Yedekler tek `.ksbackup` dosyası olarak dışarı kaydedilip başka kurulumda içeri alınabiliyor; içeri alınan dosyanın bütünlüğü doğrulanıyor.
- Veri hizmeti açılmazsa dış yedekten kurtarma ve yedek klasörünü açma seçenekleri sunuluyor; kurtarma öncesi mevcut veritabanı kopyalanıyor.
- Önceki geliştirme değişikliklerindeki rapor katmanı birleştirmesi, veri araçları ve kart okuyucu akışı bu pakete dahil edildi.

## 0.5.0

## Yeni: Ürün Fiyat Öneri Motoru

- Proje Takip ekranına ürün, miktar/birim, yüzey, aksesuar seviyesi, zorluk, teklif ve gerçekleşen maliyet kaydı eklendi.
- Geçmiş ürün teklifleri güncel malzeme ve manuel maliyet referanslarına taşınarak düşük/merkez/yüksek fiyat aralığı üretiliyor.
- Fiyat artışı bütün teklife uygulanmıyor; yalnız kullanıcı tarafından tanımlanan MDF, işçilik, boya ve benzeri maliyet payları güncelleniyor.
- Her öneri kullanılan benzer teklifleri, eski/güncel birim fiyatı, değişim yüzdesini, güven seviyesini ve eksik veri uyarılarını gösteriyor.
- Akıllı Öngörüler ekranına fiyatlı geçmiş, gerçekleşen maliyet ve maliyet payı kapsamını gösteren Fiyat Öğrenimi paneli eklendi.
- Satın alma geçmişinde bulunmayan işçilik veya piyasa değerleri tarihli manuel maliyet referansı olarak girilebiliyor.
- Kabul edilen fiyat ve proje sonunda gerçekleşen maliyet daha sonraki öneriler için öğrenme verisi oluyor.

## Düzeltme

- Personel finans ekstresi backend sözleşmesindeki `lines` alanından doğru görüntüleniyor.

0.4.0 kapsamındaki müşteri, proje finansı, tedarikçi, personel, takvim, bildirim, rapor, yedekleme ve diğer yerel ML özellikleri korunmuştur. Veriler yerel kullanıcı dizininde tutulur; kurulum paketi kaynak kod, Python veya Node kurulumu gerektirmez.
