from __future__ import annotations

import base64
import io
from pathlib import Path

from fastapi import APIRouter, Depends
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import ApiError, require_sidecar_token
from .database import get_session
from .models import Material, Project, ProjectExpense, Purchase, RecordStatus, Supplier, WorkLog
from .schemas import SpreadsheetFileResponse

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])


def register_font() -> str:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ]
    for path in candidates:
        if path.exists():
            if "KSUnicode" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("KSUnicode", str(path)))
            return "KSUnicode"
    return "Helvetica"


def money(kurus: int | None) -> str:
    if kurus is None:
        return "—"
    return f"{kurus / 100:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def build_pdf(title: str, headers: list[str], rows: list[list[str]]) -> bytes:
    stream = io.BytesIO()
    font = register_font()
    document = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=title,
        author="Kenan Şenocak Yönetim",
    )
    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "KSHeading", parent=styles["Heading1"], fontName=font, fontSize=16, leading=20, alignment=TA_LEFT
    )
    body = ParagraphStyle("KSBody", parent=styles["BodyText"], fontName=font, fontSize=8, leading=10)
    table_data = [[Paragraph(str(value), body) for value in headers]]
    table_data.extend([[Paragraph(str(value), body) for value in row] for row in rows])
    table = Table(table_data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7A3F18")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8D1C8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F4EF")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    document.build([Paragraph(title, heading), Spacer(1, 6 * mm), table])
    return stream.getvalue()


@router.get("/exports/{kind}/pdf", response_model=SpreadsheetFileResponse)
def export_pdf(kind: str, session: Session = Depends(get_session)) -> SpreadsheetFileResponse:
    if kind == "purchases":
        title = "Satın Alma Raporu"
        headers = ["Tarih", "Vade", "Firma", "Malzeme", "Tutar", "Açıklama"]
        rows = []
        records = session.execute(
            select(Purchase, Supplier.name, Material.name)
            .join(Supplier, Supplier.id == Purchase.supplier_id)
            .join(Material, Material.id == Purchase.material_id)
            .where(Purchase.status == RecordStatus.ACTIVE)
            .order_by(Purchase.purchase_date)
        )
        for purchase, supplier_name, material_name in records:
            rows.append(
                [
                    purchase.purchase_date.isoformat(),
                    purchase.due_date.isoformat() if purchase.due_date else "—",
                    supplier_name,
                    material_name,
                    money(purchase.total_kurus),
                    purchase.description or "",
                ]
            )
    elif kind == "project-costs":
        title = "Proje Maliyet Raporu"
        headers = ["Proje", "Müşteri", "Satın Alma", "İşçilik", "Diğer", "Toplam", "Bütçe"]
        rows = []
        for project in session.scalars(select(Project).order_by(Project.name)):
            purchase = int(
                session.scalar(
                    select(func.sum(Purchase.total_kurus)).where(
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
            other = int(
                session.scalar(
                    select(func.sum(ProjectExpense.amount_kurus)).where(
                        ProjectExpense.project_id == project.id,
                        ProjectExpense.status == RecordStatus.ACTIVE,
                    )
                )
                or 0
            )
            rows.append(
                [
                    project.name,
                    project.customer_name,
                    money(purchase),
                    money(labor),
                    money(other),
                    money(purchase + labor + other),
                    money(project.budget_kurus),
                ]
            )
    else:
        raise ApiError("invalid_export_kind", "Bu rapor için PDF çıktısı desteklenmiyor.", 404)
    raw = build_pdf(title, headers, rows)
    return SpreadsheetFileResponse(
        file_name=f"kenan-senocak-{kind}.pdf",
        mime_type="application/pdf",
        content_base64=base64.b64encode(raw).decode("ascii"),
    )
