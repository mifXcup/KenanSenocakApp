# Kenan Şenocak Yönetim 0.5.0

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
