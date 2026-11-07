/**
 * Kenan Şenocak Yönetim — kart okuyucu için Google Apps Script web uygulaması.
 *
 * Görevi:
 *  - doPost: ESP32 cihazından gelen kart okutmalarını "Hareketler" sayfasına satır olarak ekler.
 *  - doGet : masaüstü uygulamasının, belirli bir satırdan sonraki yeni satırları okumasını sağlar.
 *
 * Kurulum (ayrıntı için ../README.md):
 *  1) Yeni bir Google Sheet açın, Uzantılar > Apps Script ile bu dosyayı yapıştırın.
 *  2) Proje Ayarları > Komut Dosyası Özellikleri: SECRET = uzun rastgele bir anahtar.
 *  3) Dağıt > Yeni dağıtım > Web uygulaması: "Çalıştıran: Ben", "Erişim: Herkes".
 *     (Adresi bilen herkes istek gönderebilir; bu yüzden SECRET olmadan hiçbir işlem yapılmaz.)
 */

var SHEET_NAME = 'Hareketler';
var HEADERS = ['event_id', 'device_id', 'card_uid', 'event_at', 'direction', 'received_at'];
var MAX_DEDUPE_LOOKBACK = 300;
var MAX_LIMIT = 500;

function json_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(ContentService.MimeType.JSON);
}

function secret_() {
  return PropertiesService.getScriptProperties().getProperty('SECRET');
}

function authorized_(provided) {
  var expected = secret_();
  return !!expected && expected.length >= 16 && String(provided || '') === expected;
}

function sheet_() {
  var book = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = book.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(SHEET_NAME);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function normalizeUid_(value) {
  return String(value || '').replace(/[\s:\-]/g, '').toUpperCase();
}

/** ESP32 → Sheet. Gövde: {secret, device_id, card_uid, event_at, direction?, event_id?} */
function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var body = JSON.parse(e.postData.contents);
    if (!authorized_(body.secret)) {
      return json_({ ok: false, error: 'unauthorized' });
    }
    var uid = normalizeUid_(body.card_uid);
    if (!/^[0-9A-F]{4,20}$/.test(uid)) {
      return json_({ ok: false, error: 'invalid_card_uid' });
    }
    var at = String(body.event_at || '');
    if (isNaN(Date.parse(at))) {
      return json_({ ok: false, error: 'invalid_event_at' });
    }
    var device = String(body.device_id || 'cihaz-1').slice(0, 60);
    var eventId = String(body.event_id || (device + '-' + Date.parse(at) + '-' + uid)).slice(0, 100);
    var direction = body.direction === 'in' || body.direction === 'out' ? body.direction : '';

    var sheet = sheet_();
    var last = sheet.getLastRow();
    if (last > 1) {
      var from = Math.max(2, last - MAX_DEDUPE_LOOKBACK + 1);
      var ids = sheet.getRange(from, 1, last - from + 1, 1).getValues();
      for (var i = 0; i < ids.length; i++) {
        if (ids[i][0] === eventId) {
          return json_({ ok: true, duplicate: true, event_id: eventId });
        }
      }
    }
    sheet.appendRow([eventId, device, uid, at, direction, new Date().toISOString()]);
    return json_({ ok: true, event_id: eventId, row: sheet.getLastRow() });
  } catch (err) {
    return json_({ ok: false, error: String(err).slice(0, 120) });
  } finally {
    lock.releaseLock();
  }
}

/** Uygulama → Sheet. Parametreler: secret, after (son işlenen satır no, 0 = baştan), limit. */
function doGet(e) {
  var params = (e && e.parameter) || {};
  if (!authorized_(params.secret)) {
    return json_({ error: 'unauthorized' });
  }
  var sheet = sheet_();
  var after = Math.max(1, parseInt(params.after || '0', 10) || 0);
  var limit = Math.min(MAX_LIMIT, Math.max(1, parseInt(params.limit || '500', 10) || MAX_LIMIT));
  var last = sheet.getLastRow();
  if (last <= after) {
    return json_({ events: [], next_cursor: String(Math.max(after, 1)) });
  }
  var count = Math.min(limit, last - after);
  var rows = sheet.getRange(after + 1, 1, count, HEADERS.length).getValues();
  var events = [];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    if (!r[0]) {
      continue;
    }
    var at = r[3] instanceof Date ? r[3].toISOString() : String(r[3]);
    events.push({ event_id: String(r[0]), device_id: String(r[1] || ''), card_uid: String(r[2]), event_at: at, direction: r[4] ? String(r[4]) : null });
  }
  return json_({ events: events, next_cursor: String(after + count) });
}
