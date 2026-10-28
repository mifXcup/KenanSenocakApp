from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .backup import backup_manager
from .database import get_session
from .models import (
    Material,
    Project,
    ProjectExpense,
    Purchase,
    RecordStatus,
    Supplier,
    TrackingMode,
    WorkLog,
)
from .receipts import add_receipt
from .schemas import (
    ImportCommitResult,
    ImportIssue,
    ImportPreview,
    SpreadsheetFilePayload,
    SpreadsheetFileResponse,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_ROWS = 5000
KINDS = {"suppliers", "materials", "opening-debts"}

TEMPLATES = {
    "suppliers": ["Firma Adı*", "Telefon", "Not"],
    "materials": ["Malzeme Adı*", "Birim*", "Takip Türü*", "Not"],
    "opening-debts": ["Firma Adı*", "Tutar (TL)*", "Tarih*", "Vade Tarihi", "Açıklama"],
}


def normalize_header(value: Any) -> str:
    text = str(value or "").strip().casefold().replace("*", "")
    table = str.maketrans("çğıöşü", "cgiosu")
    return re.sub(r"[^a-z0-9]+", "_", text.translate(table)).strip("_")


def encode_workbook(workbook: Workbook, file_name: str) -> SpreadsheetFileResponse:
    stream = io.BytesIO()
    workbook.save(stream)
    return SpreadsheetFileResponse(
        file_name=file_name,
        mime_type=MIME_XLSX,
        content_base64=base64.b64encode(stream.getvalue()).decode("ascii"),
    )


def decode_workbook(payload: SpreadsheetFilePayload):
    if not payload.file_name.casefold().endswith(".xlsx"):
        raise ApiError("invalid_file_type", "Yalnız .xlsx dosyaları kabul edilir.", 422)
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise ApiError("invalid_file", "Excel dosyası çözülemedi.", 422) from exc
    if len(raw) > MAX_FILE_BYTES:
        raise ApiError("file_too_large", "Excel dosyası 8 MB sınırını aşıyor.", 413)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > 200:
                raise ApiError("unsafe_workbook", "Excel dosyası çok fazla parça içeriyor.", 422)
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ApiError("unsafe_workbook", "Excel dosyasının açılmış boyutu çok büyük.", 422)
        return load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ApiError("invalid_file", "Geçerli bir Excel çalışma kitabı değil.", 422) from exc


def parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("Tarih YYYY-AA-GG veya GG.AA.YYYY biçiminde olmalıdır.")


def parse_money_kurus(value: Any) -> int:
    if isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, (float, Decimal)):
        amount = Decimal(str(value))
    else:
        text = str(value or "").strip().replace("₺", "").replace(" ", "")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError("Geçerli bir TL tutarı girilmelidir.") from exc
    if amount < 0:
        raise ValueError("Tutar negatif olamaz.")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def rows_from_workbook(payload: SpreadsheetFilePayload) -> list[tuple[int, dict[str, Any]]]:
    workbook = decode_workbook(payload)
    sheet = workbook.active
    iterator = sheet.iter_rows(values_only=True)
    try:
        headers = [normalize_header(value) for value in next(iterator)]
    except StopIteration as exc:
        raise ApiError("empty_workbook", "Excel dosyası boş.", 422) from exc
    rows: list[tuple[int, dict[str, Any]]] = []
    for row_number, values in enumerate(iterator, start=2):
        if row_number > MAX_ROWS + 1:
            raise ApiError("too_many_rows", "En fazla 5.000 satır içe aktarılabilir.", 422)
        if all(value is None or str(value).strip() == "" for value in values):
            continue
        rows.append((row_number, dict(zip(headers, values, strict=False))))
    return rows


def value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def validate_rows(
    kind: str, payload: SpreadsheetFilePayload, session: Session
) -> tuple[list[dict[str, Any]], list[ImportIssue], int]:
    if kind not in KINDS:
        raise ApiError("invalid_import_kind", "Desteklenmeyen içe aktarma türü.", 404)
    raw_rows = rows_from_workbook(payload)
    issues: list[ImportIssue] = []
    valid: list[dict[str, Any]] = []
    duplicate_count = 0
    existing_suppliers = {
        name.casefold(): supplier_id
        for supplier_id, name in session.execute(select(Supplier.id, Supplier.name)).all()
    }
    existing_materials = {
        name.casefold() for name in session.scalars(select(Material.name)).all()
    }
    seen: set[str] = set()

    for row_number, row in raw_rows:
        try:
            if kind == "suppliers":
                name = str(value(row, "firma_adi", "firma") or "").strip()
                if len(name) < 2:
                    raise ValueError("Firma adı zorunludur.")
                key = name.casefold()
                if key in existing_suppliers or key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                valid.append(
                    {
                        "row": row_number,
                        "name": name,
                        "phone": str(value(row, "telefon") or "").strip() or None,
                        "note": str(value(row, "not") or "").strip() or None,
                    }
                )
            elif kind == "materials":
                name = str(value(row, "malzeme_adi", "malzeme") or "").strip()
                unit = str(value(row, "birim") or "").strip()
                tracking = str(value(row, "takip_turu", "takip") or "").strip().casefold()
                tracking_alias = {
                    "kesin": "exact",
                    "yaklasik": "estimated",
                    "yaklaşık": "estimated",
                    "sadece_deger": "value_only",
                    "yalniz_deger": "value_only",
                }
                tracking = tracking_alias.get(tracking, tracking)
                if len(name) < 2 or not unit:
                    raise ValueError("Malzeme adı ve birim zorunludur.")
                if tracking not in {item.value for item in TrackingMode}:
                    raise ValueError("Takip türü exact, estimated veya value_only olmalıdır.")
                key = name.casefold()
                if key in existing_materials or key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                valid.append(
                    {
                        "row": row_number,
                        "name": name,
                        "default_unit": unit,
                        "tracking_mode": tracking,
                        "note": str(value(row, "not") or "").strip() or None,
                    }
                )
            else:
                supplier_name = str(value(row, "firma_adi", "firma") or "").strip()
                supplier_id = existing_suppliers.get(supplier_name.casefold())
                if not supplier_id:
                    raise ValueError("Firma sistemde bulunamadı.")
                purchase_date = parse_date(value(row, "tarih"))
                due_raw = value(row, "vade_tarihi", "vade")
                due_date = parse_date(due_raw) if due_raw not in (None, "") else None
                if due_date and due_date < purchase_date:
                    raise ValueError("Vade tarihi borç tarihinden önce olamaz.")
                amount_kurus = parse_money_kurus(value(row, "tutar_tl", "tutar"))
                if amount_kurus <= 0:
                    raise ValueError("Tutar sıfırdan büyük olmalıdır.")
                row_key = hashlib.sha256(
                    f"{supplier_id}|{purchase_date}|{due_date}|{amount_kurus}".encode()
                ).hexdigest()[:40]
                duplicate = session.scalar(
                    select(Purchase.id).where(Purchase.idempotency_key == f"opening:{row_key}")
                )
                if duplicate or row_key in seen:
                    duplicate_count += 1
                    continue
                seen.add(row_key)
                valid.append(
                    {
                        "row": row_number,
                        "supplier_id": supplier_id,
                        "purchase_date": purchase_date,
                        "due_date": due_date,
                        "total_kurus": amount_kurus,
                        "description": str(value(row, "aciklama") or "").strip()
                        or "Açılış borcu",
                        "idempotency_key": f"opening:{row_key}",
                    }
                )
        except ValueError as exc:
            issues.append(ImportIssue(row=row_number, message=str(exc)))
    return valid, issues, duplicate_count


@router.get("/imports/templates/{kind}", response_model=SpreadsheetFileResponse)
def import_template(kind: str) -> SpreadsheetFileResponse:
    if kind not in KINDS:
        raise ApiError("invalid_import_kind", "Desteklenmeyen şablon türü.", 404)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Aktarım"
    sheet.append(TEMPLATES[kind])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7A3F18")
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 24
    sheet.freeze_panes = "A2"
    return encode_workbook(workbook, f"kenan-senocak-{kind}-sablon.xlsx")


@router.post("/imports/{kind}/preview", response_model=ImportPreview)
def preview_import(
    kind: str, payload: SpreadsheetFilePayload, session: Session = Depends(get_session)
) -> ImportPreview:
    valid, issues, duplicates = validate_rows(kind, payload, session)
    return ImportPreview(
        kind=kind,
        total_rows=len(valid) + len(issues) + duplicates,
        valid_rows=len(valid),
        invalid_rows=len(issues),
        duplicate_rows=duplicates,
        issues=issues[:100],
        sample=[{k: v for k, v in row.items() if k != "idempotency_key"} for row in valid[:20]],
    )


def opening_material(session: Session) -> Material:
    material = session.scalar(
        select(Material).where(func.lower(Material.name) == "açılış bakiyesi".casefold())
    )
    if material:
        return material
    material = Material(
        name="Açılış Bakiyesi",
        default_unit="tutar",
        tracking_mode=TrackingMode.VALUE_ONLY,
        note="Excel açılış borcu aktarımı için sistem malzemesi",
    )
    session.add(material)
    session.flush()
    return material


@router.post("/imports/{kind}/commit", response_model=ImportCommitResult)
def commit_import(
    kind: str, payload: SpreadsheetFilePayload, session: Session = Depends(get_session)
) -> ImportCommitResult:
    valid, issues, duplicates = validate_rows(kind, payload, session)
    if issues:
        raise ApiError(
            "import_validation_failed",
            "Hatalı satırlar düzeltilmeden aktarım yapılamaz.",
            422,
            [issue.model_dump() for issue in issues[:100]],
        )
    backup = backup_manager.create("pre_import")
    if kind == "suppliers":
        for row in valid:
            data = {k: v for k, v in row.items() if k != "row"}
            session.add(Supplier(**data))
    elif kind == "materials":
        for row in valid:
            data = {k: v for k, v in row.items() if k != "row"}
            session.add(Material(**data))
    else:
        material = opening_material(session)
        for row in valid:
            data = {k: v for k, v in row.items() if k != "row"}
            purchase = Purchase(material_id=material.id, **data)
            session.add(purchase)
            session.flush()
            add_receipt(
                session,
                purchase,
                receipt_date=purchase.purchase_date,
                amount_kurus=purchase.total_kurus,
                idempotency_key=f"{purchase.idempotency_key}:receipt",
            )
    session.flush()
    add_audit(
        session,
        "import",
        hashlib.sha256(f"{kind}:{backup.backup_id}".encode()).hexdigest()[:36],
        "committed",
        {"kind": kind, "created": len(valid), "duplicates": duplicates},
    )
    session.commit()
    return ImportCommitResult(
        kind=kind,
        created=len(valid),
        skipped_duplicates=duplicates,
        backup_id=backup.backup_id,
    )


def style_export(sheet) -> None:
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7A3F18")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(
            36, max(12, max(len(str(cell.value or "")) for cell in column) + 2)
        )


@router.get("/exports/{kind}", response_model=SpreadsheetFileResponse)
def export_xlsx(kind: str, session: Session = Depends(get_session)) -> SpreadsheetFileResponse:
    workbook = Workbook()
    sheet = workbook.active
    if kind == "suppliers":
        sheet.title = "Firmalar"
        sheet.append(["Firma", "Telefon", "Not", "Durum"])
        for item in session.scalars(select(Supplier).order_by(Supplier.name)):
            sheet.append([item.name, item.phone, item.note, item.status.value])
    elif kind == "materials":
        sheet.title = "Malzemeler"
        sheet.append(["Malzeme", "Birim", "Takip Türü", "Not", "Durum"])
        for item in session.scalars(select(Material).order_by(Material.name)):
            sheet.append(
                [item.name, item.default_unit, item.tracking_mode.value, item.note, item.status.value]
            )
    elif kind == "purchases":
        sheet.title = "Satın Almalar"
        sheet.append(["Tarih", "Vade", "Firma", "Malzeme", "Tutar (TL)", "Açıklama"])
        rows = session.execute(
            select(Purchase, Supplier.name, Material.name)
            .join(Supplier, Supplier.id == Purchase.supplier_id)
            .join(Material, Material.id == Purchase.material_id)
            .where(Purchase.status == RecordStatus.ACTIVE)
            .order_by(Purchase.purchase_date)
        )
        for purchase, supplier_name, material_name in rows:
            sheet.append(
                [
                    purchase.purchase_date,
                    purchase.due_date,
                    supplier_name,
                    material_name,
                    purchase.total_kurus / 100,
                    purchase.description,
                ]
            )
    elif kind == "project-costs":
        sheet.title = "Proje Maliyetleri"
        sheet.append(["Proje", "Müşteri", "Satın Alma (TL)", "İşçilik (TL)", "Diğer Gider (TL)", "Toplam (TL)", "Bütçe (TL)"])
        for project in session.scalars(select(Project).order_by(Project.name)):
            purchases = int(
                session.scalar(
                    select(func.sum(Purchase.received_kurus)).where(
                        Purchase.project_id == project.id, Purchase.status == RecordStatus.ACTIVE
                    )
                )
                or 0
            )
            labor = int(
                session.scalar(
                    select(func.sum(WorkLog.amount_kurus)).where(
                        WorkLog.project_id == project.id, WorkLog.status == RecordStatus.ACTIVE
                    )
                )
                or 0
            )
            expense = int(
                session.scalar(
                    select(func.sum(ProjectExpense.amount_kurus)).where(
                        ProjectExpense.project_id == project.id,
                        ProjectExpense.status == RecordStatus.ACTIVE,
                    )
                )
                or 0
            )
            sheet.append(
                [
                    project.name,
                    project.customer_name,
                    purchases / 100,
                    labor / 100,
                    expense / 100,
                    (purchases + labor + expense) / 100,
                    project.budget_kurus / 100 if project.budget_kurus is not None else None,
                ]
            )
    else:
        raise ApiError("invalid_export_kind", "Desteklenmeyen dışa aktarma türü.", 404)
    style_export(sheet)
    return encode_workbook(workbook, f"kenan-senocak-{kind}.xlsx")
