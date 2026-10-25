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

Bu sürüm bilinçli olarak KDV, iskonto ve ayrıntılı fatura/muhasebe işlemleri içermez.

## Kurulum

`dist-desktop/Kenan Şenocak Yönetim Setup 0.2.0.exe` dosyasını çalıştırın.

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

## Sonraki aşamalar

- Yeterli gerçek veri biriktikten sonra tahmin ve anomali odaklı makine öğrenmesi
- Personel ve şantiye modülleri
- İmzalı ticari dağıtım paketi
