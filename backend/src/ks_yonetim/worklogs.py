from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Query
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_active, require_sidecar_token
from .backup import backup_manager
from .database import get_session
from .labor_cost import (
    SETTING_DEFAULTS,
    UNPAID_STATUSES,
    WORK_STATUSES,
    HoursError,
    LaborSettings,
    load_settings,
    normalize_hours,
    work_log_amount,
)
from .locks import assert_dates_unlocked
from .models import (
    AppSetting,
    Employee,
    Project,
    RecordStatus,
    Site,
    WorkLog,
)
from .operations import validate_site_project
from .schemas import (
    ImportIssue,
    LaborSettingsRead,
    LaborSettingsUpdate,
    SpreadsheetFilePayload,
    SpreadsheetFileResponse,
    WorkLogCreate,
    WorkLogImportPreview,
    WorkLogImportResult,
    WorkLogRead,
    WorkLogUpdate,
)
from .spreadsheet_io import (
    encode_workbook,
    normalize_header,
    parse_date,
    parse_money_kurus,
    rows_from_workbook,
    value,
)
from .wages import RateBook, load_rate_book

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

IMPORT_HEADERS = [
    "Personel*",
    "Tarih*",
    "Durum*",
    "Normal Saat",
    "Fazla Mesai Saat",
    "Proje",
    "Şantiye",
    "Manuel Tutar (TL)",
    "Not",
]
STATUS_ALIASES = {
    "calisti": "worked",
    "calisildi": "worked",
    "yarim_gun": "half_day",
    "fazla_mesai": "overtime",
    "mesai": "overtime",
    "ucretli_izin": "paid_leave",
    "ucretsiz_izin": "unpaid_leave",
    "devamsiz": "absent",
    "devamsizlik": "absent",
}
MAX_IMPORT_ISSUES = 200


def resolve_work_log_values(
    employee: Employee,
    work_date: date,
    status: str,
    normal_hours: Decimal | None,
    overtime_hours: Decimal | None,
    manual_amount: int | None,
    settings: LaborSettings,
    book: RateBook,
) -> dict:
    """Saat, hesaplanan/manuel ve etkin tutarı üretir; hatada ApiError fırlatır."""
    try:
        normal, overtime = normalize_hours(status, normal_hours, overtime_hours, settings)
    except HoursError as exc:
        raise ApiError("invalid_hours", str(exc), 422) from exc
    if status in UNPAID_STATUSES:
        if manual_amount:
            raise ApiError(
                "invalid_amount", "Ücretsiz izin ve devamsızlık maliyeti sıfır olmalıdır.", 422
            )
        calculated: int | None = 0
        manual_amount = None
    else:
        rate = book.at(employee.id, work_date)
        calculated = (
            work_log_amount(
                status, rate.rate_kurus, rate.wage_type, work_date, normal, overtime, settings
            )
            if rate
            else None
        )
    amount = manual_amount if manual_amount is not None else calculated
    if amount is None:
        raise ApiError(
            "missing_labor_rate",
            "Tutar girilmeli veya personelin o tarihte geçerli ücreti bulunmalıdır.",
            422,
        )
    return {
        "work_status": status,
        "normal_hours": normal,
        "overtime_hours": overtime,
        "hours": normal + overtime,
        "calculated_amount_kurus": calculated,
        "manual_amount_kurus": manual_amount,
        "amount_kurus": amount,
    }


def ensure_project_site(
    session: Session, project_id: str | None, site_id: str | None
) -> None:
    if project_id:
        require_active(session, Project, project_id, "Proje")
    if site_id:
        site = require_active(session, Site, site_id, "Şantiye")
        validate_site_project(site, project_id)


def ensure_no_duplicate(
    session: Session, employee_id: str, work_date: date, exclude_id: str | None = None
) -> None:
    query = select(WorkLog.id).where(
        WorkLog.employee_id == employee_id,
        WorkLog.work_date == work_date,
        WorkLog.status == RecordStatus.ACTIVE,
    )
    if exclude_id:
        query = query.where(WorkLog.id != exclude_id)
    if session.scalar(query.limit(1)):
        raise ApiError(
            "duplicate_work_log",
            "Bu personel için aynı güne ait çalışma kaydı zaten var.",
            409,
        )


@router.post("/work-logs", response_model=WorkLogRead, status_code=201)
def create_work_log(payload: WorkLogCreate, session: Session = Depends(get_session)) -> WorkLog:
    employee = require_active(session, Employee, payload.employee_id, "Personel")
    ensure_project_site(session, payload.project_id, payload.site_id)
    ensure_no_duplicate(session, employee.id, payload.work_date)
    assert_dates_unlocked(session, [payload.work_date], "Çalışma kaydı")
    values = resolve_work_log_values(
        employee,
        payload.work_date,
        payload.work_status,
        payload.normal_hours,
        payload.overtime_hours,
        payload.manual_amount_kurus,
        load_settings(session),
        load_rate_book(session, [employee.id]),
    )
    work_log = WorkLog(
        employee_id=employee.id,
        project_id=payload.project_id,
        site_id=payload.site_id,
        work_date=payload.work_date,
        note=payload.note,
        **values,
    )
    session.add(work_log)
    session.flush()
    add_audit(
        session,
        "work_log",
        work_log.id,
        "created",
        {"amount_kurus": work_log.amount_kurus, "work_status": work_log.work_status},
    )
    session.commit()
    session.refresh(work_log)
    return work_log


@router.get("/work-logs", response_model=list[WorkLogRead])
def list_work_logs(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    project_id: str | None = None,
    site_id: str | None = None,
    work_status: str | None = Query(default=None, pattern="^[a-z_]{1,16}$"),
    date_from: date | None = None,
    date_to: date | None = None,
    include_cancelled: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(WorkLog)
    if not include_cancelled:
        query = query.where(WorkLog.status == RecordStatus.ACTIVE)
    if employee_id:
        query = query.where(WorkLog.employee_id == employee_id)
    if project_id:
        query = query.where(WorkLog.project_id == project_id)
    if site_id:
        query = query.where(WorkLog.site_id == site_id)
    if work_status:
        query = query.where(WorkLog.work_status == work_status)
    if date_from:
        query = query.where(WorkLog.work_date >= date_from)
    if date_to:
        query = query.where(WorkLog.work_date <= date_to)
    return session.scalars(
        query.order_by(WorkLog.work_date.desc(), WorkLog.created_at.desc(), WorkLog.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.patch("/work-logs/{work_log_id}", response_model=WorkLogRead)
def update_work_log(
    work_log_id: str, payload: WorkLogUpdate, session: Session = Depends(get_session)
) -> WorkLog:
    work_log = require_active(session, WorkLog, work_log_id, "Çalışma kaydı")
    changes = payload.model_dump(exclude_unset=True)
    work_date = changes.get("work_date", work_log.work_date)
    status = changes.get("work_status", work_log.work_status)
    project_id = changes.get("project_id", work_log.project_id)
    site_id = changes.get("site_id", work_log.site_id)
    manual = (
        changes.get("manual_amount_kurus", work_log.manual_amount_kurus)
    )
    if status != work_log.work_status:
        # Durum değişince önceki saat varsayılanlarını taşımak yerine yeniden türetilir.
        normal_in = changes.get("normal_hours")
        overtime_in = changes.get("overtime_hours")
    else:
        normal_in = changes.get("normal_hours", work_log.normal_hours)
        overtime_in = changes.get("overtime_hours", work_log.overtime_hours)
    employee = session.get(Employee, work_log.employee_id)
    assert employee is not None
    ensure_project_site(session, project_id, site_id)
    if work_date != work_log.work_date:
        ensure_no_duplicate(session, employee.id, work_date, exclude_id=work_log.id)
    assert_dates_unlocked(session, [work_log.work_date, work_date], "Çalışma kaydı")
    values = resolve_work_log_values(
        employee,
        work_date,
        status,
        normal_in,
        overtime_in,
        manual,
        load_settings(session),
        load_rate_book(session, [employee.id]),
    )
    before = {
        "work_date": work_log.work_date,
        "work_status": work_log.work_status,
        "amount_kurus": work_log.amount_kurus,
        "project_id": work_log.project_id,
        "site_id": work_log.site_id,
    }
    work_log.work_date = work_date
    work_log.project_id = project_id
    work_log.site_id = site_id
    if "note" in changes:
        work_log.note = changes["note"]
    for key, item in values.items():
        setattr(work_log, key, item)
    add_audit(
        session,
        "work_log",
        work_log.id,
        "updated",
        {
            "before": before,
            "after": {
                "work_date": work_date,
                "work_status": status,
                "amount_kurus": work_log.amount_kurus,
                "project_id": project_id,
                "site_id": site_id,
            },
        },
    )
    session.commit()
    session.refresh(work_log)
    return work_log


@router.post("/work-logs/{work_log_id}/cancel", response_model=WorkLogRead)
def cancel_work_log(work_log_id: str, session: Session = Depends(get_session)) -> WorkLog:
    work_log = require_active(session, WorkLog, work_log_id, "Çalışma kaydı")
    assert_dates_unlocked(session, [work_log.work_date], "Çalışma kaydı")
    work_log.status = RecordStatus.CANCELLED
    add_audit(session, "work_log", work_log.id, "cancelled", {"amount_kurus": work_log.amount_kurus})
    session.commit()
    session.refresh(work_log)
    return work_log


# --- Ayarlar -----------------------------------------------------------------------------------


@router.get("/settings/payroll", response_model=LaborSettingsRead)
def get_payroll_settings(session: Session = Depends(get_session)) -> LaborSettingsRead:
    return LaborSettingsRead(**load_settings(session).as_dict())


@router.put("/settings/payroll", response_model=LaborSettingsRead)
def update_payroll_settings(
    payload: LaborSettingsUpdate, session: Session = Depends(get_session)
) -> LaborSettingsRead:
    changes = payload.model_dump(exclude_unset=True)
    before = load_settings(session).as_dict()
    for key, item in changes.items():
        if key not in SETTING_DEFAULTS:
            continue
        setting = session.get(AppSetting, key)
        if setting is None:
            session.add(AppSetting(key=key, value=str(item)))
        else:
            setting.value = str(item)
    add_audit(
        session, "app_settings", "payroll", "updated", {"before": before, "after": changes}
    )
    session.commit()
    return LaborSettingsRead(**load_settings(session).as_dict())


# --- Toplu puantaj (Excel) -----------------------------------------------------------------------


@dataclass
class ParsedImport:
    total_rows: int = 0
    valid: list[dict] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)
    duplicates: list[ImportIssue] = field(default_factory=list)


def parse_decimal(raw) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip().replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Saat değeri sayı olmalıdır.") from exc


def parse_work_log_import(session: Session, payload: SpreadsheetFilePayload) -> ParsedImport:
    raw_rows = rows_from_workbook(payload)
    parsed = ParsedImport(total_rows=len(raw_rows))
    if not raw_rows:
        return parsed

    employees: dict[str, list[Employee]] = defaultdict(list)
    for employee in session.scalars(select(Employee).where(Employee.status != RecordStatus.CANCELLED)):
        employees[employee.name.casefold()].append(employee)
    projects: dict[str, list[Project]] = defaultdict(list)
    for project in session.scalars(select(Project).where(Project.status == RecordStatus.ACTIVE)):
        projects[project.name.casefold()].append(project)
    sites: dict[str, list[Site]] = defaultdict(list)
    for site in session.scalars(select(Site).where(Site.status == RecordStatus.ACTIVE)):
        sites[site.name.casefold()].append(site)

    settings = load_settings(session)
    candidate_ids = {e.id for items in employees.values() for e in items}
    book = load_rate_book(session, candidate_ids)
    existing = {
        (employee_id, work_date)
        for employee_id, work_date in session.execute(
            select(WorkLog.employee_id, WorkLog.work_date).where(
                WorkLog.status == RecordStatus.ACTIVE
            )
        )
    }
    seen: set[tuple[str, date]] = set()
    locked_cache: dict[date, bool] = {}

    for row_number, row in raw_rows:
        try:
            name = str(value(row, "personel", "personel_adi") or "").strip()
            matches = employees.get(name.casefold(), [])
            if not matches:
                raise ValueError("Personel sistemde bulunamadı.")
            if len(matches) > 1:
                raise ValueError("Aynı isimde birden fazla personel var; adı benzersiz yapın.")
            employee = matches[0]
            if employee.status != RecordStatus.ACTIVE:
                raise ValueError("Personel arşivlenmiş.")
            work_date = parse_date(value(row, "tarih"))
            status_text = normalize_header(value(row, "durum"))
            status = STATUS_ALIASES.get(status_text, status_text)
            if status not in WORK_STATUSES:
                raise ValueError(
                    "Durum worked, half_day, overtime, paid_leave, unpaid_leave veya absent "
                    "olmalıdır."
                )
            normal = parse_decimal(value(row, "normal_saat"))
            overtime = parse_decimal(value(row, "fazla_mesai_saat", "fazla_mesai"))
            manual_raw = value(row, "manuel_tutar_tl", "manuel_tutar")
            manual = (
                parse_money_kurus(manual_raw) if manual_raw not in (None, "") else None
            )

            project_name = str(value(row, "proje") or "").strip()
            project: Project | None = None
            if project_name:
                found = projects.get(project_name.casefold(), [])
                if not found:
                    raise ValueError("Proje sistemde bulunamadı.")
                if len(found) > 1:
                    raise ValueError("Aynı isimde birden fazla proje var.")
                project = found[0]
            site_name = str(value(row, "santiye") or "").strip()
            site: Site | None = None
            if site_name:
                found_sites = sites.get(site_name.casefold(), [])
                if project is not None and len(found_sites) > 1:
                    narrowed = [s for s in found_sites if s.project_id in (None, project.id)]
                    found_sites = narrowed or found_sites
                if not found_sites:
                    raise ValueError("Şantiye sistemde bulunamadı.")
                if len(found_sites) > 1:
                    raise ValueError("Aynı isimde birden fazla şantiye var.")
                site = found_sites[0]
                if site.project_id and site.project_id != (project.id if project else None):
                    raise ValueError("Şantiye seçilen projeye bağlı değil.")

            key = (employee.id, work_date)
            if key in existing or key in seen:
                parsed.duplicates.append(
                    ImportIssue(
                        row=row_number,
                        message="Bu personel için aynı güne ait kayıt zaten var; atlanır.",
                    )
                )
                continue
            if work_date not in locked_cache:
                try:
                    assert_dates_unlocked(session, [work_date], "Çalışma kaydı")
                    locked_cache[work_date] = False
                except ApiError:
                    locked_cache[work_date] = True
            if locked_cache[work_date]:
                raise ValueError("Tarih kesinleşmiş bir maaş dönemine ait.")
            try:
                values = resolve_work_log_values(
                    employee, work_date, status, normal, overtime, manual, settings, book
                )
            except ApiError as exc:
                raise ValueError(exc.message) from exc
            seen.add(key)
            parsed.valid.append(
                {
                    "row": row_number,
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    "project_id": project.id if project else None,
                    "site_id": site.id if site else None,
                    "work_date": work_date,
                    "note": str(value(row, "not") or "").strip() or None,
                    **values,
                }
            )
        except ValueError as exc:
            parsed.issues.append(ImportIssue(row=row_number, message=str(exc)))
    return parsed


@router.get("/work-logs/import-template", response_model=SpreadsheetFileResponse)
def work_log_import_template() -> SpreadsheetFileResponse:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Puantaj"
    sheet.append(IMPORT_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7A3F18")
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 22
    sheet.freeze_panes = "A2"
    help_sheet = workbook.create_sheet("Açıklama")
    help_sheet.append(["Durum değeri", "Anlamı"])
    for status, meaning in (
        ("worked", "Çalıştı (Normal Saat boşsa günlük normal süre)"),
        ("half_day", "Yarım gün"),
        ("overtime", "Fazla mesaili gün (Fazla Mesai Saat zorunlu)"),
        ("paid_leave", "Ücretli izin"),
        ("unpaid_leave", "Ücretsiz izin (saat girilmez)"),
        ("absent", "Devamsızlık (saat girilmez)"),
    ):
        help_sheet.append([status, meaning])
    help_sheet.column_dimensions["A"].width = 18
    help_sheet.column_dimensions["B"].width = 56
    return encode_workbook(workbook, "kenan-senocak-puantaj-sablon.xlsx")


@router.post("/work-logs/bulk-preview", response_model=WorkLogImportPreview)
def bulk_preview(
    payload: SpreadsheetFilePayload, session: Session = Depends(get_session)
) -> WorkLogImportPreview:
    parsed = parse_work_log_import(session, payload)
    return WorkLogImportPreview(
        total_rows=parsed.total_rows,
        valid_rows=len(parsed.valid),
        invalid_rows=len(parsed.issues),
        duplicate_rows=len(parsed.duplicates),
        total_labor_kurus=sum(item["amount_kurus"] for item in parsed.valid),
        issues=parsed.issues[:MAX_IMPORT_ISSUES],
        duplicates=parsed.duplicates[:MAX_IMPORT_ISSUES],
        sample=[
            {
                key: item[key]
                for key in (
                    "row",
                    "employee_name",
                    "work_date",
                    "work_status",
                    "normal_hours",
                    "overtime_hours",
                    "amount_kurus",
                )
            }
            for item in parsed.valid[:20]
        ],
    )


@router.post("/work-logs/bulk-commit", response_model=WorkLogImportResult)
def bulk_commit(
    payload: SpreadsheetFilePayload, session: Session = Depends(get_session)
) -> WorkLogImportResult:
    parsed = parse_work_log_import(session, payload)
    if parsed.issues:
        raise ApiError(
            "import_validation_failed",
            "Hatalı satırlar düzeltilmeden puantaj aktarımı yapılamaz.",
            422,
            [issue.model_dump() for issue in parsed.issues[:MAX_IMPORT_ISSUES]],
        )
    if not parsed.valid:
        raise ApiError("nothing_to_import", "Aktarılacak yeni satır bulunmuyor.", 422)
    backup = backup_manager.create("pre_import")
    logs = []
    for item in parsed.valid:
        data = {k: v for k, v in item.items() if k not in {"row", "employee_name"}}
        logs.append(WorkLog(**data))
    session.add_all(logs)
    session.flush()
    for log in logs:
        add_audit(
            session,
            "work_log",
            log.id,
            "created",
            {"amount_kurus": log.amount_kurus, "source": "bulk_import"},
        )
    add_audit(
        session,
        "import",
        backup.backup_id[:36],
        "work_logs_committed",
        {
            "created": len(logs),
            "duplicates": len(parsed.duplicates),
            "total_labor_kurus": sum(log.amount_kurus for log in logs),
            "backup_id": backup.backup_id,
        },
    )
    session.commit()
    return WorkLogImportResult(
        created=len(logs),
        skipped_duplicates=len(parsed.duplicates),
        total_labor_kurus=sum(log.amount_kurus for log in logs),
        backup_id=backup.backup_id,
    )
