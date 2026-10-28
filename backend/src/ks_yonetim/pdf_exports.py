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
from .models import Project, ProjectExpense, Purchase, RecordStatus, WorkLog
from .schemas import SpreadsheetFileResponse

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])


def _bundled_font() -> Path:
    import reportlab

    return Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"


def font_candidates() -> list[Path]:
    """Sistem yazı tipleri; sonuncusu reportlab'in paketlediği Vera'dır (Türkçe harfleri kapsar)."""
    return [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        _bundled_font(),
    ]


def register_font() -> str:
    """Türkçe karakterleri (ğ, ü, ş, ı, ö, ç, İ) taşıyan ilk yazı tipini kaydeder."""
    for path in font_candidates():
        if path.exists():
            name = "KSUnicode" if path != _bundled_font() else "KSUnicodeVera"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
            return name
    return "Helvetica"


def money(kurus: int | None) -> str:
    if kurus is None:
        return "—"
    return f"{kurus / 100:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def build_pdf(
    title: str, headers: list[str], rows: list[list[str]], notes: list[str] | None = None
) -> bytes:
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
    story = [Paragraph(title, heading), Spacer(1, 6 * mm), table]
    if notes:
        story.append(Spacer(1, 4 * mm))
        story.extend(Paragraph(f"• {line}", body) for line in notes)
    document.build(story)
    return stream.getvalue()


@router.get("/exports/{kind}/pdf", response_model=SpreadsheetFileResponse)
def export_pdf(kind: str, session: Session = Depends(get_session)) -> SpreadsheetFileResponse:
    if kind == "purchases":
        from .exports import table_pdf
        from .finance_reports import purchase_lifecycle_table

        raw = table_pdf(purchase_lifecycle_table(session))
        return SpreadsheetFileResponse(
            file_name=f"kenan-senocak-{kind}.pdf",
            mime_type="application/pdf",
            content_base64=base64.b64encode(raw).decode("ascii"),
        )
    elif kind == "project-costs":
        title = "Proje Maliyet Raporu"
        headers = ["Proje", "Müşteri", "Satın Alma", "İşçilik", "Diğer", "Toplam", "Bütçe"]
        rows = []
        for project in session.scalars(select(Project).order_by(Project.name)):
            purchase = int(
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
