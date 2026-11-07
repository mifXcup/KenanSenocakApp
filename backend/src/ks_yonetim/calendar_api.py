"""Birleşik takvim, Bugün ekranı, manuel olaylar ve bildirim teslim kayıtları.

Takvim olayları kaynak kayıtlardan (görev, ziyaret, alacak planı, tedarikçi borcu, maaş vadesi, onaylı izin)
her istekte deterministik olarak üretilir; kaynak tabloların kopyası saklanmaz. Yalnız elle girilen olaylar,
tekrarlarının tamamlama/erteleme/iptal durumları, hatırlatma tercihleri ve teslim edilen bildirimler saklanır.
Olay kimliği: `source_type:source_id:occurrence_date`. Backend bildirim göstermez; istemcinin (Electron)
alacağı `due` kayıtlarını ve teslim tekilleştirmesini sağlar.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, add_audit, require_sidecar_token
from .attendance import PlanBook, day_classification, holiday_dates
from .customers import compute_receivables
from .database import get_session
from .finance import compute_positions
from .models import (
    CalendarEventOccurrence,
    CalendarManualEvent,
    CalendarReminderPreference,
    Customer,
    Employee,
    LeaveRequest,
    NotificationDelivery,
    Project,
    ProjectTask,
    ProjectVisit,
    Purchase,
    ReceivableSchedule,
    RecordStatus,
    Supplier,
)
from .reports import debt_aging
from .schemas import OrmModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

EVENT_TYPES = (
    "project_task",
    "project_visit",
    "receivable_due",
    "supplier_payable",
    "payroll_due",
    "leave",
    "leave_return",
    "manual_event",
    "reminder",
)
FINANCIAL_TYPES = frozenset({"receivable_due", "supplier_payable", "payroll_due"})
OPEN_STATES = frozenset({"overdue", "today", "upcoming"})
MAX_RANGE_DAYS = 400
OVERDUE_HORIZON_DAYS = 730  # /today gecikmiş kaynak olaylar için geriye bakış
MANUAL_OVERDUE_LOOKBACK_DAYS = 7  # tekrarlı manuel olayların geçmiş tekrarları /today'de yığılmaz
RETURN_LOOKAHEAD_DAYS = 14
MAX_OFFSET_DAYS = 30
CHANNELS = ("windows",)


def default_offsets(event_type: str) -> list[int]:
    """Finansal olaylar: vade günü ve bir gün önce; diğerleri: bir gün önce."""
    return [0, 1] if event_type in FINANCIAL_TYPES else [1]


def load_preferences(session: Session) -> dict[str, dict]:
    stored = {p.event_type: p for p in session.scalars(select(CalendarReminderPreference))}
    result = {}
    for event_type in EVENT_TYPES:
        row = stored.get(event_type)
        result[event_type] = {
            "event_type": event_type,
            "enabled": row.enabled if row else True,
            "offsets_days": sorted({int(x) for x in row.offsets_days.split(",") if x != ""})
            if row
            else default_offsets(event_type),
            "is_default": row is None,
            "is_financial": event_type in FINANCIAL_TYPES,
        }
    return result


def state_for(day: date, today: date, *, completed: bool = False, cancelled: bool = False) -> str:
    if cancelled:
        return "cancelled"
    if completed:
        return "completed"
    if day < today:
        return "overdue"
    return "today" if day == today else "upcoming"


# --- Olay üretimi -------------------------------------------------------------------------------


def build_event(
    source_type: str,
    source_id: str,
    occurrence_date: date,
    *,
    event_type: str,
    title: str,
    start_date: date,
    state: str,
    description: str | None = None,
    end_date: date | None = None,
    all_day: bool = True,
    amount_kurus: int | None = None,
    project_id: str | None = None,
    employee_id: str | None = None,
    customer_id: str | None = None,
    supplier_id: str | None = None,
    entity: str | None = None,
    extra: dict | None = None,
) -> dict:
    return {
        "event_id": f"{source_type}:{source_id}:{occurrence_date.isoformat()}",
        "source_type": source_type,
        "source_id": source_id,
        "occurrence_date": occurrence_date,
        "event_type": event_type,
        "title": title,
        "description": description,
        "start_date": start_date,
        "end_date": end_date or start_date,
        "all_day": all_day,
        "state": state,
        "amount_kurus": amount_kurus,
        "project_id": project_id,
        "employee_id": employee_id,
        "customer_id": customer_id,
        "supplier_id": supplier_id,
        # İstemci deep-link için: entity/entity_id ve ilgili ilişkili kimlikler.
        "source_route": {
            "entity": entity or source_type,
            "entity_id": source_id,
            "project_id": project_id,
            "employee_id": employee_id,
            "customer_id": customer_id,
            "supplier_id": supplier_id,
        },
        **(extra or {}),
    }


def _names(session: Session, model, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    return dict(session.execute(select(model.id, model.name).where(model.id.in_(ids))).all())


def project_task_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    rows = session.execute(
        select(ProjectTask, Project.name)
        .join(Project, Project.id == ProjectTask.project_id)
        .where(
            ProjectTask.status == RecordStatus.ACTIVE,
            Project.status == RecordStatus.ACTIVE,
            ProjectTask.due_date.is_not(None),
            ProjectTask.due_date >= start,
            ProjectTask.due_date <= end,
        )
    ).all()
    return [
        build_event(
            "project_task", task.id, task.due_date, event_type="project_task",
            title=task.title, description=f"{project_name} – iş vadesi",
            start_date=task.due_date,
            state=state_for(task.due_date, today, completed=task.task_state == "done"),
            project_id=task.project_id,
            extra={"task_state": task.task_state},
        )
        for task, project_name in rows
    ]


def project_visit_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    rows = session.execute(
        select(ProjectVisit, Project.name)
        .join(Project, Project.id == ProjectVisit.project_id)
        .where(
            ProjectVisit.status == RecordStatus.ACTIVE,
            Project.status == RecordStatus.ACTIVE,
            ProjectVisit.visit_date >= start,
            ProjectVisit.visit_date <= end,
        )
    ).all()
    return [
        build_event(
            "project_visit", visit.id, visit.visit_date, event_type="project_visit",
            title=f"Ziyaret: {visit.purpose}", description=project_name,
            start_date=visit.visit_date,
            state=state_for(
                visit.visit_date, today,
                completed=visit.visit_state == "completed",
                cancelled=visit.visit_state == "cancelled",
            ),
            project_id=visit.project_id,
            extra={"visit_state": visit.visit_state},
        )
        for visit, project_name in rows
    ]


def receivable_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    schedules = list(
        session.scalars(
            select(ReceivableSchedule).where(
                ReceivableSchedule.status == RecordStatus.ACTIVE,
                ReceivableSchedule.due_date.is_not(None),
                ReceivableSchedule.due_date >= start,
                ReceivableSchedule.due_date <= end,
            )
        )
    )
    customers = _names(session, Customer, {s.customer_id for s in schedules})
    remaining: dict[str, int] = {}
    for customer_id in {s.customer_id for s in schedules}:
        for item in compute_receivables(session, customer_id, today)["items"]:
            if item.kind == "schedule" and item.receivable_schedule_id:
                remaining[item.receivable_schedule_id] = item.remaining_kurus
    events = []
    for schedule in schedules:
        open_amount = remaining.get(schedule.id, 0)
        paid = open_amount <= 0
        events.append(
            build_event(
                "receivable_schedule", schedule.id, schedule.due_date, event_type="receivable_due",
                title=f"Tahsilat vadesi: {customers.get(schedule.customer_id, '')} – {schedule.title}",
                description=schedule.note, start_date=schedule.due_date,
                state=state_for(schedule.due_date, today, completed=paid),
                amount_kurus=schedule.amount_kurus if paid else open_amount,
                project_id=schedule.project_id, customer_id=schedule.customer_id,
                entity="receivable_schedule",
                extra={"planned_amount_kurus": schedule.amount_kurus},
            )
        )
    return events


def supplier_payable_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    purchases = session.execute(
        select(Purchase, Supplier.name)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .where(
            Purchase.status == RecordStatus.ACTIVE,
            Purchase.due_date.is_not(None),
            Purchase.due_date >= start,
            Purchase.due_date <= end,
        )
    ).all()
    if not purchases:
        return []
    open_items = {item.purchase_id: item for item in debt_aging(session, today).items}
    events = []
    for purchase, supplier_name in purchases:
        item = open_items.get(purchase.id)
        if item is None and purchase.received_kurus <= 0:
            continue  # planlı/siparişli: henüz borç değil
        events.append(
            build_event(
                "supplier_purchase", purchase.id, purchase.due_date, event_type="supplier_payable",
                title=f"Ödeme vadesi: {supplier_name}", description=purchase.description,
                start_date=purchase.due_date,
                state=state_for(purchase.due_date, today, completed=item is None),
                amount_kurus=item.remaining_kurus if item else purchase.received_kurus,
                project_id=purchase.project_id, supplier_id=purchase.supplier_id,
                entity="purchase",
                extra={"material_name": item.material_name if item else None},
            )
        )
    return events


def payroll_due_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    rows = []
    for position in compute_positions(session, None, today).values():
        for item in position.co_items:
            due = item.movement.due_date
            if due is not None and start <= due <= end:
                rows.append(item)
    names = _names(session, Employee, {i.movement.employee_id for i in rows})
    events = []
    for item in rows:
        movement = item.movement
        paid = item.remaining <= 0
        label = "Maaş vadesi" if item.kind == "accrual" else "Personel ödeme vadesi"
        events.append(
            build_event(
                "employee_movement", movement.id, movement.due_date, event_type="payroll_due",
                title=f"{label}: {names.get(movement.employee_id, '')}", description=movement.note,
                start_date=movement.due_date, state=state_for(movement.due_date, today, completed=paid),
                amount_kurus=movement.amount_kurus if paid else item.remaining,
                employee_id=movement.employee_id, project_id=movement.project_id,
                entity="employee_financial_movement",
                extra={"payroll_period_id": movement.payroll_period_id, "movement_kind": item.kind},
            )
        )
    return events


def leave_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    requests = list(
        session.scalars(
            select(LeaveRequest).where(
                LeaveRequest.status == RecordStatus.ACTIVE,
                LeaveRequest.request_state == "approved",
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start - timedelta(days=RETURN_LOOKAHEAD_DAYS),
            )
        )
    )
    if not requests:
        return []
    employees = {
        e.id: e
        for e in session.scalars(select(Employee).where(Employee.id.in_({r.employee_id for r in requests})))
    }
    plans = PlanBook(session)
    holidays = holiday_dates(session, start - timedelta(days=RETURN_LOOKAHEAD_DAYS), end + timedelta(days=RETURN_LOOKAHEAD_DAYS * 2))
    events = []
    for request in requests:
        employee = employees[request.employee_id]
        if request.start_date <= end and request.end_date >= start:
            if request.end_date < today:
                state = "completed"
            elif request.start_date <= today:
                state = "today"
            else:
                state = "upcoming"
            events.append(
                build_event(
                    "leave_request", request.id, request.start_date, event_type="leave",
                    title=f"İzin: {employee.name}", description=request.reason,
                    start_date=request.start_date, end_date=request.end_date, state=state,
                    employee_id=employee.id, entity="leave_request",
                    extra={"day_part": request.day_part},
                )
            )
        cursor = request.end_date + timedelta(days=1)
        limit = request.end_date + timedelta(days=RETURN_LOOKAHEAD_DAYS)
        while cursor <= limit and day_classification(employee, cursor, plans, holidays) != "workday":
            cursor += timedelta(days=1)
        if cursor <= limit and start <= cursor <= end:
            events.append(
                build_event(
                    "leave_return", request.id, cursor, event_type="leave_return",
                    title=f"İşe dönüş: {employee.name}", start_date=cursor,
                    state=state_for(cursor, today, completed=cursor < today),
                    employee_id=employee.id, entity="leave_request",
                )
            )
    return events


# --- Manuel olaylar ve tekrar -------------------------------------------------------------------


def _add_months(anchor: date, months: int) -> date:
    index = anchor.year * 12 + anchor.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(anchor.day, calendar.monthrange(year, month + 1)[1]))


def occurrence_dates(event: CalendarManualEvent, start: date, end: date) -> list[date]:
    """[start, end] aralığındaki tekrar tarihleri (deterministik; satır yazılmaz). Ay sonu: gün ayın son gününe iner."""
    first = event.start_date
    hi = min(end, event.repeat_until) if event.repeat_until else end
    if hi < start or hi < first:
        return []
    rule = event.repeat_rule
    if rule == "none":
        return [first] if start <= first <= hi else []
    dates: list[date] = []
    if rule == "daily":
        cursor = max(first, start)
        while cursor <= hi:
            dates.append(cursor)
            cursor += timedelta(days=1)
    elif rule == "weekly":
        skip = max(0, (start - first).days // 7)
        cursor = first + timedelta(days=7 * skip)
        while cursor <= hi:
            if cursor >= start:
                dates.append(cursor)
            cursor += timedelta(days=7)
    elif rule == "monthly":
        k = max(0, (start.year - first.year) * 12 + start.month - first.month - 1)
        while True:
            cursor = _add_months(first, k)
            if cursor > hi:
                break
            if cursor >= start:
                dates.append(cursor)
            k += 1
    return dates


def manual_events(
    session: Session,
    start: date,
    end: date,
    today: date,
    recurring_start: date | None = None,
) -> list[dict]:
    series = list(
        session.scalars(
            select(CalendarManualEvent).where(CalendarManualEvent.status == RecordStatus.ACTIVE)
        )
    )
    if not series:
        return []
    overrides: dict[str, dict[date, CalendarEventOccurrence]] = {}
    for row in session.scalars(
        select(CalendarEventOccurrence).where(
            CalendarEventOccurrence.manual_event_id.in_([s.id for s in series])
        )
    ):
        overrides.setdefault(row.manual_event_id, {})[row.occurrence_date] = row
    events = []
    for item in series:
        span = (item.end_date - item.start_date).days if item.end_date else 0
        mine = overrides.get(item.id, {})

        def emit(original: date, shown: date, state: str, item=item, span=span) -> None:
            events.append(
                build_event(
                    "manual_event", item.id, original, event_type=item.event_type,
                    title=item.title, description=item.description, start_date=shown,
                    end_date=shown + timedelta(days=span), all_day=item.all_day, state=state,
                    amount_kurus=item.amount_kurus, project_id=item.project_id,
                    employee_id=item.employee_id, customer_id=item.customer_id,
                    supplier_id=item.supplier_id, entity="calendar_manual_event",
                    extra={
                        "repeat_rule": item.repeat_rule, "start_time": item.start_time,
                        "original_date": original,
                    },
                )
            )

        floor = start if item.repeat_rule == "none" or recurring_start is None else max(start, recurring_start)
        for day in occurrence_dates(item, floor - timedelta(days=span), end):
            if day in mine:
                continue
            emit(day, day, state_for(day, today))
        for original, row in mine.items():
            shown = row.postponed_to or original
            if shown > end or shown + timedelta(days=span) < start:
                continue
            emit(
                original, shown,
                state_for(
                    shown, today,
                    completed=row.occurrence_state == "completed",
                    cancelled=row.occurrence_state == "cancelled",
                ),
            )
    return events


# --- Birleştirme --------------------------------------------------------------------------------

SOURCES = {
    "project_task": project_task_events,
    "project_visit": project_visit_events,
    "receivable_due": receivable_events,
    "supplier_payable": supplier_payable_events,
    "payroll_due": payroll_due_events,
}


def collect_events(
    session: Session,
    start: date,
    end: date,
    today: date,
    *,
    event_types: set[str] | None = None,
    recurring_manual_start: date | None = None,
) -> list[dict]:
    wanted = event_types or set(EVENT_TYPES)
    events: list[dict] = []
    for name, producer in SOURCES.items():
        if name in wanted:
            events.extend(producer(session, start, end, today))
    if wanted & {"leave", "leave_return"}:
        events.extend(e for e in leave_events(session, start, end, today) if e["event_type"] in wanted)
    if wanted & {"manual_event", "reminder"}:
        events.extend(
            e
            for e in manual_events(session, start, end, today, recurring_manual_start)
            if e["event_type"] in wanted
        )
    preferences = load_preferences(session)
    for event in events:
        pref = preferences[event["event_type"]]
        event["notification_defaults"] = {
            "enabled": pref["enabled"],
            "offsets_days": pref["offsets_days"],
            "is_financial": pref["is_financial"],
        }
    events.sort(key=lambda e: (e["start_date"], e["event_type"], e["event_id"]))
    return events


def _check_range(start: date, end: date) -> None:
    if end < start:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    if (end - start).days > MAX_RANGE_DAYS:
        raise ApiError(
            "range_too_large", f"Aralık en fazla {MAX_RANGE_DAYS + 1} gün olabilir.", 422
        )


@router.get("/calendar/events")
def list_calendar_events(
    date_from: date,
    date_to: date,
    event_type: Literal[
        "project_task", "project_visit", "receivable_due", "supplier_payable", "payroll_due",
        "leave", "leave_return", "manual_event", "reminder",
    ] | None = None,
    project_id: str | None = None,
    employee_id: str | None = None,
    customer_id: str | None = None,
    supplier_id: str | None = None,
    state: Literal["overdue", "today", "upcoming", "completed", "cancelled"] | None = None,
    session: Session = Depends(get_session),
):
    _check_range(date_from, date_to)
    today = clock.business_today()
    events = collect_events(
        session, date_from, date_to, today, event_types={event_type} if event_type else None
    )
    for key, value in (
        ("project_id", project_id), ("employee_id", employee_id),
        ("customer_id", customer_id), ("supplier_id", supplier_id), ("state", state),
    ):
        if value:
            events = [e for e in events if e[key] == value]
    return {"date_from": date_from, "date_to": date_to, "as_of": today, "count": len(events), "events": events}


def _group(events: list[dict]) -> dict:
    return {
        "count": len(events),
        "amount_kurus": sum(e["amount_kurus"] or 0 for e in events),
        "receivable_kurus": sum(
            e["amount_kurus"] or 0 for e in events if e["event_type"] == "receivable_due"
        ),
        "payable_kurus": sum(
            e["amount_kurus"] or 0
            for e in events
            if e["event_type"] in ("supplier_payable", "payroll_due")
        ),
        "events": events,
    }


@router.get("/today")
def today_view(session: Session = Depends(get_session)):
    today = clock.business_today()
    events = collect_events(
        session,
        today - timedelta(days=OVERDUE_HORIZON_DAYS),
        today + timedelta(days=7),
        today,
        recurring_manual_start=today - timedelta(days=MANUAL_OVERDUE_LOOKBACK_DAYS),
    )
    open_events = [e for e in events if e["state"] in OPEN_STATES]
    overdue = [e for e in open_events if e["state"] == "overdue"]
    current = [e for e in open_events if e["state"] == "today"]
    upcoming = [e for e in open_events if e["state"] == "upcoming" and e["start_date"] <= today + timedelta(days=7)]
    return {
        "as_of": today,
        "overdue": _group(overdue),
        "today": _group(current),
        "next_7_days": _group(upcoming),
        "totals": {
            "count": len(overdue) + len(current) + len(upcoming),
            "amount_kurus": sum(e["amount_kurus"] or 0 for e in overdue + current + upcoming),
        },
        "overdue_horizon_days": OVERDUE_HORIZON_DAYS,
    }


# --- Manuel olay uçları -------------------------------------------------------------------------

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ManualEventCreate(BaseModel):
    event_type: Literal["manual_event", "reminder"] = "manual_event"
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    start_date: date
    end_date: date | None = None
    all_day: bool = True
    start_time: str | None = Field(default=None, pattern=TIME_PATTERN.pattern)
    repeat_rule: Literal["none", "daily", "weekly", "monthly"] = "none"
    repeat_until: date | None = None
    amount_kurus: int | None = Field(default=None, ge=0)
    project_id: str | None = None
    employee_id: str | None = None
    customer_id: str | None = None
    supplier_id: str | None = None

    @model_validator(mode="after")
    def validate_event(self) -> ManualEventCreate:
        check_event_fields(self)
        return self


class ManualEventUpdate(BaseModel):
    event_type: Literal["manual_event", "reminder"] | None = None
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    start_date: date | None = None
    end_date: date | None = None
    all_day: bool | None = None
    start_time: str | None = Field(default=None, pattern=TIME_PATTERN.pattern)
    repeat_rule: Literal["none", "daily", "weekly", "monthly"] | None = None
    repeat_until: date | None = None
    amount_kurus: int | None = Field(default=None, ge=0)
    project_id: str | None = None
    employee_id: str | None = None
    customer_id: str | None = None
    supplier_id: str | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> ManualEventUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        for name in ("event_type", "title", "start_date", "all_day", "repeat_rule"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} boş bırakılamaz.")
        return self


def check_event_fields(item) -> None:
    if item.end_date and item.start_date and item.end_date < item.start_date:
        raise ValueError("Bitiş tarihi başlangıçtan önce olamaz.")
    if item.repeat_until and item.repeat_rule == "none":
        raise ValueError("Tekrar bitişi için tekrar kuralı seçilmelidir.")
    if item.repeat_until and item.start_date and item.repeat_until < item.start_date:
        raise ValueError("Tekrar bitişi başlangıçtan önce olamaz.")
    if item.start_time and item.all_day:
        raise ValueError("Saat girildiğinde all_day false olmalıdır.")


class ManualEventRead(OrmModel):
    id: str
    event_type: str
    title: str
    description: str | None
    start_date: date
    end_date: date | None
    all_day: bool
    start_time: str | None
    repeat_rule: str
    repeat_until: date | None
    amount_kurus: int | None
    project_id: str | None
    employee_id: str | None
    customer_id: str | None
    supplier_id: str | None
    status: RecordStatus


class OccurrenceAction(BaseModel):
    occurrence_date: date | None = None
    note: str | None = Field(default=None, max_length=255)


class PostponeAction(OccurrenceAction):
    new_date: date


def _validate_links(session: Session, data: dict) -> None:
    for key, model, label in (
        ("project_id", Project, "Proje"), ("employee_id", Employee, "Personel"),
        ("customer_id", Customer, "Müşteri"), ("supplier_id", Supplier, "Firma"),
    ):
        if data.get(key) and session.get(model, data[key]) is None:
            raise ApiError("not_found", f"{label} bulunamadı.", 404)


def _get_event(session: Session, event_id: str) -> CalendarManualEvent:
    event = session.get(CalendarManualEvent, event_id)
    if event is None:
        raise ApiError("not_found", "Manuel olay bulunamadı.", 404)
    return event


@router.post("/calendar/manual-events", response_model=ManualEventRead, status_code=201)
def create_manual_event(payload: ManualEventCreate, session: Session = Depends(get_session)):
    data = payload.model_dump()
    _validate_links(session, data)
    event = CalendarManualEvent(**data)
    session.add(event)
    session.flush()
    add_audit(session, "calendar_manual_event", event.id, "created", {"title": event.title})
    session.commit()
    session.refresh(event)
    return event


@router.get("/calendar/manual-events", response_model=list[ManualEventRead])
def list_manual_events(
    include_cancelled: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    query = select(CalendarManualEvent)
    if not include_cancelled:
        query = query.where(CalendarManualEvent.status == RecordStatus.ACTIVE)
    return session.scalars(
        query.order_by(CalendarManualEvent.start_date, CalendarManualEvent.id).limit(limit).offset(offset)
    ).all()


@router.get("/calendar/manual-events/{event_id}", response_model=ManualEventRead)
def read_manual_event(event_id: str, session: Session = Depends(get_session)):
    return _get_event(session, event_id)


@router.patch("/calendar/manual-events/{event_id}", response_model=ManualEventRead)
def update_manual_event(
    event_id: str, payload: ManualEventUpdate, session: Session = Depends(get_session)
):
    event = _get_event(session, event_id)
    if event.status != RecordStatus.ACTIVE:
        raise ApiError("event_cancelled", "İptal edilmiş olay düzenlenemez.", 409)
    changes = payload.model_dump(exclude_unset=True)
    merged = {
        key: changes.get(key, getattr(event, key))
        for key in ("start_date", "end_date", "repeat_rule", "repeat_until", "start_time", "all_day")
    }
    try:
        check_event_fields(type("Merged", (), merged))
    except ValueError as exc:
        raise ApiError("validation_error", str(exc), 422) from exc
    if {"start_date", "repeat_rule"} & changes.keys() and session.scalar(
        select(CalendarEventOccurrence.id).where(CalendarEventOccurrence.manual_event_id == event.id).limit(1)
    ):
        raise ApiError(
            "event_has_history",
            "Tamamlanan/ertelenen tekrarı olan olayın başlangıcı veya tekrar kuralı değiştirilemez.",
            409,
        )
    _validate_links(session, changes)
    before = {key: getattr(event, key) for key in changes}
    for key, value in changes.items():
        setattr(event, key, value)
    add_audit(session, "calendar_manual_event", event.id, "updated", {"before": before, "after": changes})
    session.commit()
    session.refresh(event)
    return event


def _target_occurrence(event: CalendarManualEvent, requested: date | None) -> date:
    if requested is None:
        if event.repeat_rule != "none":
            raise ApiError(
                "occurrence_date_required", "Tekrarlı olayda occurrence_date zorunludur.", 422
            )
        return event.start_date
    if requested not in occurrence_dates(event, requested, requested):
        raise ApiError(
            "not_an_occurrence", "Bu tarih olayın bir tekrar tarihi değil.", 422,
            {"occurrence_date": requested},
        )
    return requested


def _occurrence_row(session: Session, event: CalendarManualEvent, day: date) -> CalendarEventOccurrence | None:
    row = session.scalar(
        select(CalendarEventOccurrence).where(
            CalendarEventOccurrence.manual_event_id == event.id,
            CalendarEventOccurrence.occurrence_date == day,
        )
    )
    if row is not None and row.occurrence_state in ("completed", "cancelled"):
        raise ApiError(
            "occurrence_closed", "Bu tekrar zaten tamamlanmış veya iptal edilmiş.", 409,
            {"occurrence_state": row.occurrence_state},
        )
    return row


def _set_occurrence(
    session: Session, event: CalendarManualEvent, day: date, state: str, postponed_to: date | None,
    note: str | None,
) -> CalendarEventOccurrence:
    row = _occurrence_row(session, event, day)
    if row is None:
        row = CalendarEventOccurrence(manual_event_id=event.id, occurrence_date=day)
        session.add(row)
    row.occurrence_state = state
    if postponed_to is not None or state == "postponed":
        row.postponed_to = postponed_to
    row.note = note
    row.changed_at = datetime.now(UTC)
    add_audit(
        session, "calendar_manual_event", event.id, state,
        {"occurrence_date": day, "postponed_to": row.postponed_to, "note": note},
    )
    return row


def _active_event(session: Session, event_id: str) -> CalendarManualEvent:
    event = _get_event(session, event_id)
    if event.status != RecordStatus.ACTIVE:
        raise ApiError("event_cancelled", "İptal edilmiş olay üzerinde işlem yapılamaz.", 409)
    return event


@router.post("/calendar/manual-events/{event_id}/complete")
def complete_manual_event(
    event_id: str, payload: OccurrenceAction | None = None, session: Session = Depends(get_session)
):
    payload = payload or OccurrenceAction()
    event = _active_event(session, event_id)
    day = _target_occurrence(event, payload.occurrence_date)
    _set_occurrence(session, event, day, "completed", None, payload.note)
    session.commit()
    return {"event_id": f"manual_event:{event.id}:{day.isoformat()}", "state": "completed"}


@router.post("/calendar/manual-events/{event_id}/postpone")
def postpone_manual_event(
    event_id: str, payload: PostponeAction, session: Session = Depends(get_session)
):
    event = _active_event(session, event_id)
    day = _target_occurrence(event, payload.occurrence_date)
    row = _occurrence_row(session, event, day)
    shown = row.postponed_to if row and row.postponed_to else day
    if payload.new_date <= shown:
        raise ApiError(
            "invalid_postpone_date", "Yeni tarih mevcut tarihten sonra olmalıdır.", 422,
            {"current_date": shown},
        )
    _set_occurrence(session, event, day, "postponed", payload.new_date, payload.note)
    session.commit()
    return {
        "event_id": f"manual_event:{event.id}:{day.isoformat()}",
        "state": state_for(payload.new_date, clock.business_today()),
        "start_date": payload.new_date,
    }


@router.post("/calendar/manual-events/{event_id}/cancel")
def cancel_manual_event(
    event_id: str, payload: OccurrenceAction | None = None, session: Session = Depends(get_session)
):
    """`occurrence_date` verilirse yalnız o tekrar, verilmezse tüm olay serisi iptal edilir."""
    payload = payload or OccurrenceAction()
    event = _active_event(session, event_id)
    if payload.occurrence_date is None:
        event.status = RecordStatus.CANCELLED
        add_audit(session, "calendar_manual_event", event.id, "cancelled", {"note": payload.note})
        session.commit()
        return {"event_id": event.id, "state": "cancelled", "scope": "series"}
    day = _target_occurrence(event, payload.occurrence_date)
    _set_occurrence(session, event, day, "cancelled", None, payload.note)
    session.commit()
    return {"event_id": f"manual_event:{event.id}:{day.isoformat()}", "state": "cancelled", "scope": "occurrence"}


# --- Hatırlatma tercihleri ve bildirimler ----------------------------------------------------------


class PreferenceItem(BaseModel):
    event_type: Literal[
        "project_task", "project_visit", "receivable_due", "supplier_payable", "payroll_due",
        "leave", "leave_return", "manual_event", "reminder",
    ]
    enabled: bool = True
    offsets_days: list[int] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_offsets(self) -> PreferenceItem:
        if any(o < 0 or o > MAX_OFFSET_DAYS for o in self.offsets_days) or len(
            set(self.offsets_days)
        ) != len(self.offsets_days):
            raise ValueError(f"offsets_days 0–{MAX_OFFSET_DAYS} arasında benzersiz günler olmalıdır.")
        return self


class PreferenceUpdate(BaseModel):
    items: list[PreferenceItem] = Field(min_length=1, max_length=len(EVENT_TYPES))

    @model_validator(mode="after")
    def unique_types(self) -> PreferenceUpdate:
        names = [i.event_type for i in self.items]
        if len(names) != len(set(names)):
            raise ValueError("Aynı olay türü bir istekte bir kez gönderilebilir.")
        return self


@router.get("/calendar/reminder-preferences")
def get_reminder_preferences(session: Session = Depends(get_session)):
    return {"channels": list(CHANNELS), "preferences": list(load_preferences(session).values())}


@router.put("/calendar/reminder-preferences")
def put_reminder_preferences(payload: PreferenceUpdate, session: Session = Depends(get_session)):
    existing = {p.event_type: p for p in session.scalars(select(CalendarReminderPreference))}
    for item in payload.items:
        offsets = ",".join(str(o) for o in sorted(item.offsets_days))
        row = existing.get(item.event_type)
        if row is None:
            session.add(
                CalendarReminderPreference(
                    event_type=item.event_type, enabled=item.enabled, offsets_days=offsets
                )
            )
        else:
            row.enabled, row.offsets_days = item.enabled, offsets
    add_audit(
        session, "calendar_reminder_preferences", "calendar", "updated",
        {"items": [i.model_dump() for i in payload.items]},
    )
    session.commit()
    return {"channels": list(CHANNELS), "preferences": list(load_preferences(session).values())}


def delivery_key(event: dict, offset: int, channel: str) -> str:
    return f"{event['event_id']}|{event['start_date'].isoformat()}|{offset}|{channel}"


@router.get("/notifications/due")
def notifications_due(
    channel: Literal["windows"] = "windows", session: Session = Depends(get_session)
):
    """Bugün gösterilmesi gereken, henüz teslim edilmemiş bildirimler.

    Kural: olay açık (today/upcoming) ve `başlangıç − offset <= bugün <= başlangıç`. Gecikmiş olaylar
    yeni bildirim üretmez; kaçırılan offset olay gününe kadar bir kez yakalanır.
    """
    today = clock.business_today()
    preferences = load_preferences(session)
    events = collect_events(session, today, today + timedelta(days=MAX_OFFSET_DAYS), today)
    delivered = set(session.scalars(select(NotificationDelivery.delivery_key)))
    due = []
    for event in events:
        pref = preferences[event["event_type"]]
        if event["state"] not in ("today", "upcoming") or not pref["enabled"]:
            continue
        for offset in pref["offsets_days"]:
            fire = event["start_date"] - timedelta(days=offset)
            key = delivery_key(event, offset, channel)
            if fire <= today <= event["start_date"] and key not in delivered:
                due.append(
                    {
                        "delivery_key": key,
                        "channel": channel,
                        "offset_days": offset,
                        "fire_date": fire,
                        "title": event["title"],
                        "body": event["description"],
                        "event": event,
                    }
                )
    due.sort(key=lambda d: (d["event"]["start_date"], d["offset_days"], d["delivery_key"]))
    return {"as_of": today, "channel": channel, "count": len(due), "notifications": due}


class DeliveryMark(BaseModel):
    delivery_key: str = Field(min_length=10, max_length=300)


@router.post("/notifications/delivered")
def mark_delivered(payload: DeliveryMark, session: Session = Depends(get_session)):
    parts = payload.delivery_key.rsplit("|", 3)
    if len(parts) != 4:
        raise ApiError("invalid_delivery_key", "Teslim anahtarı geçersiz.", 422)
    event_id, start_text, offset_text, channel = parts
    try:
        start = date.fromisoformat(start_text)
        offset = int(offset_text)
    except ValueError as exc:
        raise ApiError("invalid_delivery_key", "Teslim anahtarı geçersiz.", 422) from exc
    if channel not in CHANNELS:
        raise ApiError("invalid_delivery_key", "Bilinmeyen bildirim kanalı.", 422)
    existing = session.scalar(
        select(NotificationDelivery).where(NotificationDelivery.delivery_key == payload.delivery_key)
    )
    if existing is not None:
        return {"delivery_key": existing.delivery_key, "delivered": True, "already_delivered": True}
    today = clock.business_today()
    event = next(
        (e for e in collect_events(session, start, start, today) if e["event_id"] == event_id and e["start_date"] == start),
        None,
    )
    if event is None:
        raise ApiError("event_not_found", "Bildirimin olayı bulunamadı.", 404)
    if offset not in load_preferences(session)[event["event_type"]]["offsets_days"]:
        raise ApiError("invalid_offset", "Bu olay türü için tanımlı olmayan bildirim zamanı.", 422)
    row = NotificationDelivery(
        delivery_key=payload.delivery_key,
        event_id=event_id,
        source_type=event["source_type"],
        source_id=event["source_id"],
        occurrence_date=start,
        offset_days=offset,
        channel=channel,
        delivered_on=today,
    )
    session.add(row)
    try:
        session.flush()
        add_audit(session, "notification", row.id, "delivered", {"key": payload.delivery_key})
        session.commit()
    except IntegrityError:
        session.rollback()
        return {"delivery_key": payload.delivery_key, "delivered": True, "already_delivered": True}
    return {"delivery_key": payload.delivery_key, "delivered": True, "already_delivered": False}
