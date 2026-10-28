"""Rapor tablolarını JSON/XLSX/PDF'e aynı veriden dönüştürür (ekran ve dosya toplamları aynıdır)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .pdf_exports import build_pdf, money

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"  # text | money | number | date


@dataclass
class ReportTable:
    name: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    # Açıklama satırları (yöntem/kapsam notları) ve yapılandırılmış uyarılar; JSON, XLSX ve PDF'te aynıdır.
    notes: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def footnotes(self) -> list[str]:
        return [*self.notes, *(w["message"] for w in self.warnings if w.get("message"))]

    def to_json(self) -> dict:
        return {
            "notes": self.notes,
            "warnings": self.warnings,
            "name": self.name,
            "title": self.title,
            "filters": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.filters.items()},
            "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in self.columns],
            "rows": self.rows,
            "totals": self.totals,
            "row_count": len(self.rows),
        }


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def table_xlsx(table: ReportTable) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = re.sub(r"[\[\]:*?/\\]", "-", table.title)[:31]
    sheet.append([c.label for c in table.columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7A3F18")

    def cell_value(column: Column, value: Any) -> Any:
        if value is None:
            return None
        if column.kind == "money":
            return value / 100
        return _plain(value)

    for row in table.rows:
        sheet.append([cell_value(c, row.get(c.key)) for c in table.columns])
    if table.totals:
        sheet.append(
            [
                "TOPLAM" if index == 0 else cell_value(c, table.totals.get(c.key))
                for index, c in enumerate(table.columns)
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
    footnotes = table.footnotes()
    if footnotes:
        sheet.append([])
        for line in footnotes:
            sheet.append([line])
            sheet.cell(sheet.max_row, 1).font = Font(italic=True)
    for index, column in enumerate(table.columns, start=1):
        if column.kind == "money":
            for cells in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                cells[0].number_format = '#,##0.00 "TL"'
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = max(14, len(column.label) + 4)
    sheet.freeze_panes = "A2"
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _pdf_cell(column: Column, value: Any) -> str:
    if value is None:
        return "—"
    if column.kind == "money":
        return money(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def table_pdf(table: ReportTable) -> bytes:
    rows = [[_pdf_cell(c, row.get(c.key)) for c in table.columns] for row in table.rows]
    if table.totals:
        rows.append(
            [
                "TOPLAM" if index == 0 else _pdf_cell(c, table.totals.get(c.key)) if c.key in table.totals else ""
                for index, c in enumerate(table.columns)
            ]
        )
    return build_pdf(table.title, [c.label for c in table.columns], rows, notes=table.footnotes())


def file_response(content: bytes, media_type: str, file_name: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def xlsx_response(table: ReportTable, file_name: str) -> Response:
    return file_response(table_xlsx(table), MIME_XLSX, file_name)


def pdf_response(table: ReportTable, file_name: str) -> Response:
    return file_response(table_pdf(table), "application/pdf", file_name)
