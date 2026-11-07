# Kart okuyucu (ESP32 + Google Sheets) kurulumu

Bu klasör **isteğe bağlı** kart okuyucu özelliğinin cihaz ve Google tarafını içerir. Uygulama varsayılan olarak
tamamen çevrimdışıdır; özellik yalnız **Ayarlar > Kart okuyucu** bölümünden açılırsa Google'a bağlanır.

## Veri akışı

```
Kart → ESP32 (RC522) → Apps Script (doPost) → Google Sheet "Hareketler"
                                                  ↑ yeni satırları okur (doGet, gizli anahtarla)
                              Masaüstü uygulaması (Ayarlar'dan açıksa, her N dakikada)
                                   ↓
                         Ham kart hareketleri → Puantaj ve İzin > Kart hareketleri → siz onaylarsınız → puantaj kaydı
```

- Kart hareketi **kendiliğinden puantaj olmaz**. Önerilen saatleri görür, düzeltir ve onaylarsınız.
- Aynı kartın 60 sn içindeki tekrar okumaları (ayarlanabilir) tekrar sayılır; aynı olay iki kez içeri alınmaz.
- Tanınmayan kartlar listelenir; bir personele atadığınızda geçmiş okumaları da ona bağlanır.
- Gün içindeki **ilk okuma giriş, son okuma çıkış** sayılır. Tek okuma varsa süreyi siz girersiniz.
- Saat dilimi: Türkiye sabit UTC+3 (yaz saati yok).

## Gizlilik

Sheet'e kart numarası, cihaz adı ve zaman yazılır (personel adı yazılmaz). Gizli anahtar uygulamanın yerel
veritabanında saklanır ve **yedeklere dahildir**; yedek dosyalarını paylaşırken dikkat edin. Anahtarı
değiştirmek için Apps Script özelliğini ve uygulama ayarını birlikte güncelleyin.

## Kurulum adımları

1. **Google Sheet** oluşturun (boş). Uzantılar > Apps Script > `apps_script/Code.gs` içeriğini yapıştırın.
2. Proje Ayarları > Komut Dosyası Özellikleri: `SECRET` = en az 16 karakterlik rastgele anahtar.
3. Dağıt > Yeni dağıtım > **Web uygulaması**: Çalıştıran *Ben*, erişim *Herkes*. Çıkan `.../exec` adresini kopyalayın.
   Kodu her değiştirdiğinizde yeni sürüm dağıtın.
4. `esp32/card_reader.ino` içinde Wi-Fi, `WEB_APP_URL`, `SECRET`, `DEVICE_ID` değerlerini girin ve yükleyin.
5. Uygulama: **Ayarlar > Kart okuyucu**: adresi ve anahtarı girin, kaydedin, **Eşitlemeyi aç**.
6. **Puantaj ve İzin > Kart hareketleri**: kartları personele atayın.

## Donanım notları

- Uno/Nano Wi-Fi taşımaz; **ESP32** (veya ESP8266) kullanın. Okuyucu: RC522 (MIFARE 13,56 MHz) ya da PN532.
- Kart numarası (UID) kopyalanabilir; bu sistem **devam takibi** içindir, kapı güvenliği için kullanmayın.
- Cihaz internet yokken olayları belleğinde (LittleFS) biriktirir, bağlantı gelince gönderir. Saat NTP ile
  alınır; saat alınmadan okuma kaydedilmez (üç uyarı bip'i).
- `esp32/card_reader.ino` **derlenmemiş taslaktır**: önce tek kartla masada deneyin. TLS doğrulaması taslakta
  kapalıdır (`setInsecure`); kalıcı kurulumda Google kök sertifikasını ekleyin.
- Apps Script `doPost` yanıtı 302 ile yönlenir; taslak bunu `HTTPC_FORCE_FOLLOW_REDIRECTS` ile izler.

## Sorun giderme

| Belirti | Neden |
|---|---|
| Uygulamada "Apps Script geçerli JSON döndürmedi" | Adres yanlış ya da dağıtım "Herkes" erişimine açık değil |
| `unauthorized` | `SECRET` iki tarafta aynı değil |
| Hareket gelmiyor ama Sheet'te satır var | Eşitleme kapalı ya da imleç ilerlemiş; Ayarlar'da adresi yeniden kaydedin (imleç sıfırlanır) |
| Saat 3 saat kayık | Cihazda `TZ_OFFSET_SECONDS` ve `+03:00` birlikte kalmalı |
