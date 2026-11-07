"""Kart okuyucu (Arduino/ESP32) hareketleri.

Akış: ESP32 kart okutmayı Google Apps Script web uygulamasına yazar → Google Sheet satırı olur →
bu modül, kullanıcı ayarlardan AÇTIYSA Apps Script'ten yeni satırları okur ve ham `attendance_events`
kayıtlarına çevirir. Ham hareketler otomatik puantaj olmaz: kullanıcı "Kart hareketleri" ekranında
önerilen süreleri gözden geçirip onaylar; onayda mevcut `work-logs` kuralları (kilitli dönem, çift kayıt,
ücret hesabı) aynen uygulanır.

Uygulama çevrimdışı çalışır; bu özellik varsayılan KAPALIdır ve açıldığında yalnız ayarlanan Apps Script
adresine, gizli anahtarla, yeni satırları okumak için bağlanır. Personel verisi Google'a bu uygulamadan
gönderilmez; kart UID'si ve zaman damgası ise cihazdan Google Sheet'e yazılır (kullanıcının seçimi).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .database import SessionLocal, get_session
from .labor_cost import load_settings as load_labor_settings
from .models import (
    AppSetting,
    AttendanceEvent,
    Employee,
    EmployeeCard,
    RecordStatus,
    WorkLog,
    utcnow,
)
from .schemas import WorkLogCreate
from .worklogs import create_work_log

router = APIRouter(prefix="/api/v1/card-reader", dependencies=[Depends(require_sidecar_token)])

# Türkiye 2016'dan beri yaz saati uygulamasını bırakmıştır: sabit UTC+3.
TR_TZ = timezone(timedelta(hours=3))
ALLOWED_HOSTS = frozenset({"script.google.com", "script.googleusercontent.com"})
PAGE_SIZE = 500
MAX_PAGES_PER_SYNC = 10
MAX_RESPONSE_BYTES = 2_000_000
FETCH_TIMEOUT_SECONDS = 20
UID_PATTERN = re.compile(r"^[0-9A-F]{4,20}$")
QUARTER = Decimal("0.25")

DEFAULTS = {
    "enabled": "false",
    "web_app_url": "",
    "secret": "",
    "poll_minutes": "15",
    "duplicate_seconds": "60",
    "break_minutes": "0",
    "cursor": "0",
    "last_sync_at": "",
    "last_error": "",
}


class CardReaderError(Exception):
    pass


# ---------------------------------------------------------------- ayarlar


def _key(name: str) -> str:
    return f"card_reader.{name}"


def load_settings(session: Session) -> dict[str, str]:
    stored = {
        key: value
        for key, value in session.execute(select(AppSetting.key, AppSetting.value)).all()
        if key.startswith("card_reader.")
    }
    return {name: stored.get(_key(name), default) for name, default in DEFAULTS.items()}


def save_setting(session: Session, name: str, value: str) -> None:
    row = session.get(AppSetting, _key(name))
    if row is None:
        session.add(AppSetting(key=_key(name), value=value[:255]))
    else:
        row.value = value[:255]


def settings_view(values: dict[str, str]) -> dict:
    return {
        "enabled": values["enabled"] == "true",
        "web_app_url": values["web_app_url"],
        "has_secret": bool(values["secret"]),
        "poll_minutes": int(values["poll_minutes"]),
        "duplicate_seconds": int(values["duplicate_seconds"]),
        "break_minutes": int(values["break_minutes"]),
        "cursor": values["cursor"],
        "last_sync_at": values["last_sync_at"] or None,
        "last_error": values["last_error"] or None,
        "external_service": "Google Apps Script / Google Sheets",
        "notice": (
            "Açıldığında uygulama yalnız ayarlanan Apps Script adresinden yeni kart satırlarını okur. "
            "Kart numarası ve zaman bilgisi cihaz tarafından Google Sheet'e yazılır."
        ),
    }


class SettingsUpdate(BaseModel):
    enabled: bool | None = None
    web_app_url: str | None = Field(default=None, max_length=240)
    secret: str | None = Field(default=None, max_length=120)
    clear_secret: bool = False
    poll_minutes: int | None = Field(default=None, ge=5, le=1440)
    duplicate_seconds: int | None = Field(default=None, ge=10, le=600)
    break_minutes: int | None = Field(default=None, ge=0, le=240)
    reset_cursor: bool = False


def validate_web_app_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or not parsed.path.startswith("/macros/")
        or parsed.query
        or parsed.fragment
    ):
        raise ApiError(
            "invalid_web_app_url",
            "Adres, https://script.google.com/macros/s/.../exec biçiminde bir Apps Script web uygulaması olmalıdır.",
            422,
        )
    return parsed.geturl()


@router.get("/settings")
def read_settings(session: Session = Depends(get_session)) -> dict:
    return settings_view(load_settings(session))


@router.put("/settings")
def update_settings(payload: SettingsUpdate, session: Session = Depends(get_session)) -> dict:
    values = load_settings(session)
    changes = payload.model_dump(exclude_unset=True)
    before = settings_view(values)
    if "web_app_url" in changes:
        url = changes["web_app_url"] or ""
        new_url = validate_web_app_url(url) if url else ""
        if new_url != values["web_app_url"]:
            save_setting(session, "web_app_url", new_url)
            save_setting(session, "cursor", "0")
            values["web_app_url"] = new_url
    if payload.clear_secret:
        save_setting(session, "secret", "")
        values["secret"] = ""
    elif changes.get("secret"):
        save_setting(session, "secret", changes["secret"].strip())
        values["secret"] = changes["secret"].strip()
    for name in ("poll_minutes", "duplicate_seconds", "break_minutes"):
        if changes.get(name) is not None:
            save_setting(session, name, str(changes[name]))
            values[name] = str(changes[name])
    if payload.reset_cursor:
        save_setting(session, "cursor", "0")
        values["cursor"] = "0"
    if "enabled" in changes and changes["enabled"] is not None:
        if changes["enabled"] and (not values["web_app_url"] or not values["secret"]):
            raise ApiError(
                "card_reader_incomplete",
                "Açmadan önce Apps Script adresini ve gizli anahtarı girin.",
                422,
            )
        save_setting(session, "enabled", "true" if changes["enabled"] else "false")
        values["enabled"] = "true" if changes["enabled"] else "false"
    add_audit(
        session,
        "app_settings",
        "card_reader",
        "updated",
        {"before": before, "after": settings_view(values)},
    )
    session.commit()
    return settings_view(values)


# ---------------------------------------------------------------- yardımcılar


def normalize_uid(value: str) -> str:
    uid = re.sub(r"[\s:\-]", "", str(value or "")).upper()
    if not UID_PATTERN.fullmatch(uid):
        raise ValueError("Kart numarası 4-20 karakterlik onaltılık (0-9, A-F) değer olmalıdır.")
    return uid


def as_utc(value: datetime) -> datetime:
    """SQLite zaman damgalarını tz'siz (UTC) döndürür; hesaplar için UTC'ye sabitler."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_event_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TR_TZ)
    return parsed.astimezone(UTC)


def business_day(value: datetime) -> date:
    return as_utc(value).astimezone(TR_TZ).date()


def tr_iso(value: datetime) -> str:
    return as_utc(value).astimezone(TR_TZ).isoformat(timespec="seconds")


def round_quarter(hours: Decimal) -> Decimal:
    return (hours / QUARTER).quantize(Decimal(1)) * QUARTER


# ---------------------------------------------------------------- hareket alma


class EventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    device_id: str | None = Field(default=None, max_length=60)
    card_uid: str = Field(min_length=1, max_length=40)
    event_at: str = Field(min_length=10, max_length=40)
    direction: Literal["in", "out"] | None = None


class ImportRequest(BaseModel):
    events: list[EventIn] = Field(max_length=2000)


def active_card_map(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(EmployeeCard.card_uid, EmployeeCard.employee_id)
        .join(Employee, Employee.id == EmployeeCard.employee_id)
        .where(EmployeeCard.status == RecordStatus.ACTIVE, Employee.status == RecordStatus.ACTIVE)
    ).all()
    return {uid: employee_id for uid, employee_id in rows}


def ingest_events(
    session: Session, events: Iterable[EventIn | dict], *, source: str
) -> dict:
    values = load_settings(session)
    window = timedelta(seconds=int(values["duplicate_seconds"]))
    cards = active_card_map(session)
    prepared: list[tuple[datetime, EventIn, str]] = []
    invalid: list[dict] = []
    received = 0
    for index, raw in enumerate(events):
        received += 1
        try:
            item = raw if isinstance(raw, EventIn) else EventIn.model_validate(raw)
            prepared.append((parse_event_time(item.event_at), item, normalize_uid(item.card_uid)))
        except (ValueError, TypeError) as exc:
            invalid.append({"index": index, "message": str(exc)[:200]})
    keys = [item.event_id for _, item, _ in prepared]
    existing = set(
        session.scalars(select(AttendanceEvent.event_key).where(AttendanceEvent.event_key.in_(keys)))
    ) if keys else set()
    prepared.sort(key=lambda row: row[0])
    last_seen: dict[str, datetime] = {}
    created = duplicates = skipped = unknown = 0
    seen_in_batch: set[str] = set()
    for at, item, uid in prepared:
        if item.event_id in existing or item.event_id in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(item.event_id)
        if uid not in last_seen:
            latest = session.scalar(
                select(AttendanceEvent.event_at)
                .where(AttendanceEvent.card_uid == uid, AttendanceEvent.state != "duplicate")
                .order_by(AttendanceEvent.event_at.desc())
                .limit(1)
            )
            if latest is not None:
                last_seen[uid] = as_utc(latest)
        previous = last_seen.get(uid)
        is_duplicate = previous is not None and timedelta(0) <= at - previous < window
        employee_id = cards.get(uid)
        session.add(
            AttendanceEvent(
                event_key=item.event_id,
                device_id=item.device_id,
                card_uid=uid,
                event_at=at,
                direction=item.direction,
                source=source,
                employee_id=employee_id,
                state="duplicate" if is_duplicate else "pending",
            )
        )
        if is_duplicate:
            duplicates += 1
        else:
            last_seen[uid] = at
            created += 1
            if employee_id is None:
                unknown += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("event_conflict", "Hareketler eş zamanlı işlendi; yeniden deneyin.", 409) from exc
    return {
        "received": received,
        "created": created,
        "duplicates": duplicates,
        "skipped_existing": skipped,
        "unknown_card": unknown,
        "invalid": invalid[:50],
    }


@router.post("/events/import")
def import_events(payload: ImportRequest, session: Session = Depends(get_session)) -> dict:
    return ingest_events(session, payload.events, source="manual")


# ---------------------------------------------------------------- Google Sheets eşitleme


def fetch_sheet_events(url: str, secret: str, cursor: str, limit: int = PAGE_SIZE) -> dict:
    """Apps Script web uygulamasından yeni satırları okur. Testlerde değiştirilir."""
    query = urllib.parse.urlencode({"secret": secret, "after": cursor, "limit": limit})
    request = urllib.request.Request(
        f"{url}?{query}", headers={"Accept": "application/json", "User-Agent": "KS-Yonetim"}
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CardReaderError(f"Google Sheet'e ulaşılamadı: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise CardReaderError("Apps Script yanıtı beklenenden büyük.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CardReaderError("Apps Script geçerli JSON döndürmedi (adres veya yetki hatalı olabilir).") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise CardReaderError(f"Apps Script hata döndürdü: {str(payload.get('error'))[:120]}")
    if not isinstance(payload.get("events"), list):
        raise CardReaderError("Apps Script yanıtında 'events' listesi yok.")
    return payload


def sync_once(session: Session) -> dict:
    values = load_settings(session)
    if values["enabled"] != "true":
        raise ApiError("card_reader_disabled", "Kart okuyucu eşitlemesi kapalı.", 409)
    totals = {"received": 0, "created": 0, "duplicates": 0, "skipped_existing": 0, "unknown_card": 0, "invalid": []}
    cursor = values["cursor"]
    try:
        for _ in range(MAX_PAGES_PER_SYNC):
            payload = fetch_sheet_events(values["web_app_url"], values["secret"], cursor, PAGE_SIZE)
            batch = payload["events"]
            result = ingest_events(session, batch, source="sheet")
            for name in ("received", "created", "duplicates", "skipped_existing", "unknown_card"):
                totals[name] += result[name]
            totals["invalid"].extend(result["invalid"])
            cursor = str(payload.get("next_cursor", cursor))
            save_setting(session, "cursor", cursor)
            session.commit()
            if len(batch) < PAGE_SIZE:
                break
    except CardReaderError as exc:
        save_setting(session, "last_error", str(exc))
        session.commit()
        raise ApiError("card_reader_sync_failed", str(exc), 502) from exc
    save_setting(session, "last_sync_at", utcnow().isoformat(timespec="seconds"))
    save_setting(session, "last_error", "")
    session.commit()
    totals["invalid"] = totals["invalid"][:50]
    return totals


@router.post("/sync")
def sync_now(session: Session = Depends(get_session)) -> dict:
    return sync_once(session)


def run_scheduled_sync() -> None:
    """Arka plan döngüsü: ayar açıksa ve süre dolduysa eşitler; hatalar `last_error`a yazılır."""
    with SessionLocal() as session:
        values = load_settings(session)
        if values["enabled"] != "true":
            return
        if values["last_sync_at"]:
            last = datetime.fromisoformat(values["last_sync_at"]).replace(tzinfo=UTC)
            if utcnow() - last < timedelta(minutes=int(values["poll_minutes"])):
                return
        try:
            sync_once(session)
        except ApiError:
            pass


# ---------------------------------------------------------------- kartlar


class CardAssign(BaseModel):
    employee_id: str
    card_uid: str = Field(min_length=1, max_length=40)
    reassign: bool = False


def card_view(card: EmployeeCard, employee_name: str | None) -> dict:
    return {
        "id": card.id,
        "employee_id": card.employee_id,
        "employee_name": employee_name,
        "card_uid": card.card_uid,
        "status": card.status.value,
    }


@router.get("/cards")
def list_cards(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(EmployeeCard, Employee.name)
        .join(Employee, Employee.id == EmployeeCard.employee_id)
        .where(EmployeeCard.status == RecordStatus.ACTIVE)
        .order_by(Employee.name, EmployeeCard.card_uid)
    ).all()
    return [card_view(card, name) for card, name in rows]


@router.put("/cards")
def assign_card(payload: CardAssign, session: Session = Depends(get_session)) -> dict:
    try:
        uid = normalize_uid(payload.card_uid)
    except ValueError as exc:
        raise ApiError("invalid_card_uid", str(exc), 422) from exc
    employee = session.get(Employee, payload.employee_id)
    if employee is None or employee.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Personel bulunamadı.", 404)
    card = session.scalar(select(EmployeeCard).where(EmployeeCard.card_uid == uid))
    if card is None:
        card = EmployeeCard(employee_id=employee.id, card_uid=uid)
        session.add(card)
        session.flush()
        add_audit(session, "employee_card", card.id, "created", {"employee_id": employee.id})
    elif card.status == RecordStatus.ACTIVE and card.employee_id != employee.id:
        if not payload.reassign:
            raise ApiError(
                "card_in_use", "Bu kart başka bir personele atanmış.", 409, {"employee_id": card.employee_id}
            )
        add_audit(session, "employee_card", card.id, "reassigned", {"from": card.employee_id, "to": employee.id})
        card.employee_id = employee.id
    elif card.status != RecordStatus.ACTIVE:
        card.employee_id = employee.id
        card.status = RecordStatus.ACTIVE
        add_audit(session, "employee_card", card.id, "restored", {"employee_id": employee.id})
    # Bu karta ait, personeli bilinmeyen bekleyen hareketler artık eşleşir.
    for event in session.scalars(
        select(AttendanceEvent).where(
            AttendanceEvent.card_uid == uid, AttendanceEvent.employee_id.is_(None)
        )
    ):
        event.employee_id = employee.id
    session.commit()
    return card_view(card, employee.name)


@router.post("/cards/{card_id}/archive")
def archive_card(card_id: str, session: Session = Depends(get_session)) -> dict:
    card = session.get(EmployeeCard, card_id)
    if card is None:
        raise ApiError("not_found", "Kart bulunamadı.", 404)
    card.status = RecordStatus.ARCHIVED
    add_audit(session, "employee_card", card.id, "archived")
    session.commit()
    employee = session.get(Employee, card.employee_id)
    return card_view(card, employee.name if employee else None)


# ---------------------------------------------------------------- hareket listesi


def event_view(event: AttendanceEvent, names: dict[str, str]) -> dict:
    return {
        "id": event.id,
        "event_key": event.event_key,
        "device_id": event.device_id,
        "card_uid": event.card_uid,
        "event_at": tr_iso(event.event_at),
        "work_date": business_day(event.event_at).isoformat(),
        "direction": event.direction,
        "state": event.state,
        "employee_id": event.employee_id,
        "employee_name": names.get(event.employee_id or ""),
        "work_log_id": event.work_log_id,
    }


def employee_names(session: Session, ids: Iterable[str | None]) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(session.execute(select(Employee.id, Employee.name).where(Employee.id.in_(wanted))).all())


@router.get("/events")
def list_events(
    session: Session = Depends(get_session),
    state: str | None = Query(default=None, pattern="^(pending|processed|ignored|duplicate)$"),
    unknown_only: bool = False,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    query = select(AttendanceEvent)
    if state:
        query = query.where(AttendanceEvent.state == state)
    if unknown_only:
        query = query.where(AttendanceEvent.employee_id.is_(None))
    events = list(
        session.scalars(
            query.order_by(AttendanceEvent.event_at.desc(), AttendanceEvent.id).limit(limit).offset(offset)
        )
    )
    names = employee_names(session, (e.employee_id for e in events))
    return [event_view(event, names) for event in events]


@router.post("/events/{event_id}/ignore")
def ignore_event(event_id: str, session: Session = Depends(get_session)) -> dict:
    event = session.get(AttendanceEvent, event_id)
    if event is None:
        raise ApiError("not_found", "Hareket bulunamadı.", 404)
    if event.state == "processed":
        raise ApiError("event_processed", "Puantaja işlenmiş hareket yok sayılamaz.", 409)
    event.state = "ignored"
    add_audit(session, "attendance_event", event.id, "ignored")
    session.commit()
    return event_view(event, employee_names(session, [event.employee_id]))


# ---------------------------------------------------------------- gün önerisi ve onay


def propose_hours(first: datetime, last: datetime, normal_cap: Decimal, break_minutes: int) -> tuple[Decimal, Decimal]:
    minutes = Decimal(str((as_utc(last) - as_utc(first)).total_seconds())) / 60
    worked = max(Decimal(0), minutes - break_minutes) / 60
    worked = min(round_quarter(worked), Decimal(24))
    normal = min(worked, normal_cap)
    overtime = min(worked - normal, Decimal(24))
    return normal, overtime


@router.get("/review")
def review(
    session: Session = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    values = load_settings(session)
    cap = Decimal(load_labor_settings(session).standard_day_hours)
    break_minutes = int(values["break_minutes"])
    events = list(
        session.scalars(
            select(AttendanceEvent)
            .where(AttendanceEvent.state == "pending", AttendanceEvent.employee_id.is_not(None))
            .order_by(AttendanceEvent.event_at)
        )
    )
    groups: dict[tuple[str, date], list[AttendanceEvent]] = {}
    for event in events:
        day = business_day(event.event_at)
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        groups.setdefault((event.employee_id or "", day), []).append(event)
    names = employee_names(session, (key[0] for key in groups))
    existing = {
        (employee_id, work_date)
        for employee_id, work_date in session.execute(
            select(WorkLog.employee_id, WorkLog.work_date).where(WorkLog.status == RecordStatus.ACTIVE)
        ).all()
    } if groups else set()
    days = []
    for (employee_id, day), group in sorted(groups.items(), key=lambda item: (item[0][1], names.get(item[0][0], ""))):
        first, last = group[0].event_at, group[-1].event_at
        needs_manual = len(group) < 2
        normal = overtime = None
        if not needs_manual:
            normal, overtime = propose_hours(first, last, cap, break_minutes)
        days.append(
            {
                "employee_id": employee_id,
                "employee_name": names.get(employee_id),
                "work_date": day.isoformat(),
                "event_ids": [event.id for event in group],
                "event_count": len(group),
                "first_at": tr_iso(first),
                "last_at": tr_iso(last),
                "needs_manual": needs_manual,
                "proposed_normal_hours": float(normal) if normal is not None else None,
                "proposed_overtime_hours": float(overtime) if overtime is not None else None,
                "existing_work_log": (employee_id, day) in existing,
            }
        )
    unknown = session.scalar(
        select(func.count(AttendanceEvent.id)).where(AttendanceEvent.state == "pending", AttendanceEvent.employee_id.is_(None))
    )
    return {"days": days, "unknown_pending": int(unknown or 0)}


class ApproveItem(BaseModel):
    employee_id: str
    work_date: date
    normal_hours: Decimal = Field(ge=0, le=24, decimal_places=2)
    overtime_hours: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    project_id: str | None = None
    site_id: str | None = None


class ApproveRequest(BaseModel):
    items: list[ApproveItem] = Field(min_length=1, max_length=200)


@router.post("/review/approve")
def approve(payload: ApproveRequest, session: Session = Depends(get_session)) -> dict:
    results = []
    for item in payload.items:
        try:
            log = create_work_log(
                WorkLogCreate(
                    employee_id=item.employee_id,
                    work_date=item.work_date,
                    work_status="overtime" if item.overtime_hours > 0 else "worked",
                    normal_hours=item.normal_hours,
                    overtime_hours=item.overtime_hours,
                    project_id=item.project_id,
                    site_id=item.site_id,
                    note="Kart okuyucu hareketlerinden onaylandı",
                ),
                session,
            )
        except ApiError as exc:
            session.rollback()
            results.append(
                {"employee_id": item.employee_id, "work_date": item.work_date.isoformat(), "ok": False, "code": exc.code, "message": exc.message}
            )
            continue
        for event in session.scalars(
            select(AttendanceEvent).where(
                AttendanceEvent.employee_id == item.employee_id, AttendanceEvent.state == "pending"
            )
        ):
            if business_day(event.event_at) == item.work_date:
                event.state = "processed"
                event.work_log_id = log.id
        add_audit(session, "work_log", log.id, "card_reader_approved", {"work_date": item.work_date.isoformat()})
        session.commit()
        results.append({"employee_id": item.employee_id, "work_date": item.work_date.isoformat(), "ok": True, "work_log_id": log.id})
    return {"results": results, "approved": sum(1 for r in results if r["ok"])}
