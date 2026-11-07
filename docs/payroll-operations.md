# Maaş hesap ve ödeme akışı

## İşletme kuralı

- Dönem, önceki ayın 6'sında başlar ve kesim ayının 5'inde biter. Maaş vadesi aynı ayın 10'udur.
- Aylık ücret günlük hesaplanır: aylık ücret / 30. Saatlik karşılık: günlük tutar / 9. Örneğin 30.000 TL aylık ücret için günlük 1.000 TL, saatlik yaklaşık 111,11 TL'dir. Tam bir dönemi çalışan aylık ücretlinin toplamı, dönem 28 veya 31 gün sürse de aylık sözleşme tutarına eşitlenir; fark ayrı bir dönem uzunluğu düzeltmesi olarak gösterilir. Kısmi dönemde fiili takvim günleri esas alınır.
- Haber verilerek veya verilmeden gelinmeyen günün günlük karşılığı tahakkuktan düşer. Habersiz gelinmeyen günün ilave yarım günlük tutarı yalnız **hukuki değerlendirme** alanında görünür; net ücretten otomatik düşmez.
- Normal fazla mesai saatlik tutarın 1,5 katıdır. Pazar ve kayıtlı resmî tatilde fiilen çalışılan normal saatler için toplam 2 kat ücret hesaplanır. Bu günlerdeki fazla mesai 2 kattır.
- Günlük tutarlar ve kesintiler `payroll_entries.calculation_detail.daily_breakdown` içinde saklanır. Kuruş yuvarlaması toplam bileşen düzeyindedir; günlük satırların yuvarlanmış toplamı birkaç kuruş farklı olabilir.
- Eski kesinleşmiş dönemler değiştirilmez. Eski tarihli dönemlerin görünümü mevcut kayıtlarını kullanır.

## Elden ödeme teslim belgesi

Kesinleşmiş dönem için elden ödeme kaydı oluşturulduğunda belge, ödeme hareket numarası, ad soyad, T.C. kimlik numarası, tarih, ödenen tutar ve ödeme öncesi/sonrası kalan ücreti gösterir. T.C. kimlik numarası uygulama veritabanına kaydedilmez; çıktı alınırken geçici olarak kullanılır. İmzalı iki nüshadan biri çalışana verilir. Belge yalnız belirtilen tutarın teslimi içindir; genel ibra beyanı içermez.

## Hukuki konu özeti

Çalışma ve Sosyal Güvenlik Bakanlığı'nın İş Kanunu m.38 açıklamasına göre ücret kesme cezası sözleşmede gösterilen sebeplere, yazılı bildirime, aylık iki gündelik sınırına ve ceza tutarının Bakanlık hesabına yatırılmasına tabidir. Bu yüzden ilave 0,5 günlük ceza otomatik maaş kesintisine dahil edilmedi. [Bakanlık: ücret kesme cezası](https://www.csgb.gov.tr/poco-pages/ucret-kesme-cezasi/).

2025 yönetmelik değişikliğiyle Türkiye genelinde en az üç işçi çalıştıran işverenlerde ücret ödemesi için banka zorunluluğu bulunmaktadır. Elden ödeme belgesi bu zorunluluğun yerine geçmez. İşyerinin somut durumu ve belge metni kullanılmadan önce iş hukuku danışmanıyla değerlendirilmelidir. [Bakanlık teftiş bülteni](https://www.csgb.gov.tr/Media/lmyogdpp/tefti%C5%9F-b%C3%BClten-temmuz-2025.pdf).

KVKK, T.C. kimlik numarasının işlenmesinde veri minimizasyonu ve ölçülülük gereğini vurgular. Bu nedenle numara uygulama veritabanında tutulmaz. [KVKK rehberi](https://www.kvkk.gov.tr/Icerik/7798/Turkiye-Cumhuriyeti-Kimlik-Numaralarinin-Islenmesi-Hakkinda-Rehber).
