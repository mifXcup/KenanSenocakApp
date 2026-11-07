/*
 * Kenan Şenocak Yönetim — ESP32 + RC522 kart okuyucu TASLAĞI.
 *
 * DURUM: Taslaktır; bu depoda derlenip donanımda denenmedi. Kendi kartınızla bench testi yapın.
 *
 * Bağlantılar (ESP32 DevKit, VSPI):
 *   RC522 SDA(SS)=GPIO5  SCK=GPIO18  MOSI=GPIO23  MISO=GPIO19  RST=GPIO22  3.3V  GND
 *   Buzzer=GPIO27   LED=GPIO2
 * Kütüphaneler (Arduino IDE / Library Manager): "MFRC522" (miguelbalboa), ESP32 çekirdeği (WiFi, HTTPClient, LittleFS).
 *
 * Çalışma: kart okununca olay (event_id, uid, ISO zaman) bir kuyruk dosyasına yazılır, internet varsa
 * Google Apps Script adresine gönderilir; gönderilemeyenler cihaz yeniden başlasa bile kuyrukta kalır.
 */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <SPI.h>
#include <MFRC522.h>
#include <time.h>

// ---- AYARLAR (kendinize göre değiştirin) ----
const char* WIFI_SSID = "ATOLYE_WIFI";
const char* WIFI_PASS = "wifi-sifresi";
const char* WEB_APP_URL = "https://script.google.com/macros/s/XXXXXXXX/exec";
const char* SECRET = "apps-script-ile-ayni-uzun-anahtar";
const char* DEVICE_ID = "kapi-1";
const char* DIRECTION = "";            // "in", "out" ya da boş (tek okuyucu: sıra uygulamada belirlenir)
const long TZ_OFFSET_SECONDS = 3 * 3600;  // Türkiye UTC+3 (yaz saati yok)
const unsigned long SAME_CARD_IGNORE_MS = 5000;  // aynı kartı art arda okumayı yerelde engelle
const size_t MAX_QUEUE_BYTES = 60000;

const int PIN_SS = 5, PIN_RST = 22, PIN_BUZZER = 27, PIN_LED = 2;
const char* QUEUE_FILE = "/queue.txt";

MFRC522 reader(PIN_SS, PIN_RST);
String lastUid;
unsigned long lastReadMs = 0;
unsigned long lastFlushMs = 0;

void beep(int times, int ms) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_BUZZER, HIGH); digitalWrite(PIN_LED, HIGH); delay(ms);
    digitalWrite(PIN_BUZZER, LOW); digitalWrite(PIN_LED, LOW); delay(ms);
  }
}

bool timeIsValid() { return time(nullptr) > 1700000000; }  // NTP ile senkron oldu mu

String isoNow() {
  time_t now = time(nullptr) + TZ_OFFSET_SECONDS;
  struct tm t;
  gmtime_r(&now, &t);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S+03:00", &t);
  return String(buf);
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 10000) delay(250);
  if (WiFi.status() == WL_CONNECTED && !timeIsValid()) configTime(0, 0, "pool.ntp.org", "time.google.com");
}

void enqueue(const String& line) {
  File f = LittleFS.open(QUEUE_FILE, FILE_APPEND);
  if (!f) return;
  if (f.size() < MAX_QUEUE_BYTES) f.println(line);  // dolarsa yeni olay atlanır (çok uzun kesinti)
  f.close();
}

// Tek olayı gönderir. Başarılıysa true (sunucu "duplicate" dese de başarı sayılır).
bool postEvent(const String& eventId, const String& uid, const String& at) {
  WiFiClientSecure client;
  client.setInsecure();  // TLS sertifikası doğrulanmaz; üretimde Google kök CA'sını setCACert ile verin
  HTTPClient http;
  if (!http.begin(client, WEB_APP_URL)) return false;
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);  // Apps Script 302 ile yönlendirir
  http.addHeader("Content-Type", "application/json");
  String body = String("{\"secret\":\"") + SECRET + "\",\"device_id\":\"" + DEVICE_ID + "\",\"event_id\":\"" + eventId +
                "\",\"card_uid\":\"" + uid + "\",\"event_at\":\"" + at + "\"" +
                (strlen(DIRECTION) ? String(",\"direction\":\"") + DIRECTION + "\"" : String("")) + "}";
  int code = http.POST(body);
  String answer = code > 0 ? http.getString() : "";
  http.end();
  return code == 200 && answer.indexOf("\"ok\":true") >= 0;
}

// Kuyruktaki satırları sırayla göndermeyi dener; gönderilemeyenleri dosyada tutar.
void flushQueue() {
  if (WiFi.status() != WL_CONNECTED || !LittleFS.exists(QUEUE_FILE)) return;
  File in = LittleFS.open(QUEUE_FILE, FILE_READ);
  if (!in) return;
  String remaining;
  bool failed = false;
  while (in.available()) {
    String line = in.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) continue;
    int a = line.indexOf('|'), b = line.indexOf('|', a + 1);
    if (a < 0 || b < 0) continue;
    if (failed || !postEvent(line.substring(0, a), line.substring(a + 1, b), line.substring(b + 1))) {
      failed = true;
      remaining += line + "\n";
    }
  }
  in.close();
  if (remaining.length() == 0) {
    LittleFS.remove(QUEUE_FILE);
  } else {
    File out = LittleFS.open(QUEUE_FILE, FILE_WRITE);
    if (out) { out.print(remaining); out.close(); }
  }
}

String uidToHex(const MFRC522::Uid& uid) {
  String s;
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += "0";
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

void setup() {
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  LittleFS.begin(true);
  SPI.begin();
  reader.PCD_Init();
  connectWifi();
  beep(1, 80);
}

void loop() {
  connectWifi();
  if (millis() - lastFlushMs > 15000) { lastFlushMs = millis(); flushQueue(); }

  if (!reader.PICC_IsNewCardPresent() || !reader.PICC_ReadCardSerial()) { delay(30); return; }
  String uid = uidToHex(reader.uid);
  reader.PICC_HaltA();

  if (uid == lastUid && millis() - lastReadMs < SAME_CARD_IGNORE_MS) return;
  lastUid = uid;
  lastReadMs = millis();

  if (!timeIsValid()) { beep(3, 150); return; }  // saat bilinmeden olay kaydetmeyiz (yanlış tarih yazmamak için)
  String at = isoNow();
  String eventId = String(DEVICE_ID) + "-" + String((unsigned long)time(nullptr)) + "-" + uid;
  enqueue(eventId + "|" + uid + "|" + at);
  flushQueue();
  beep(1, 120);
}
