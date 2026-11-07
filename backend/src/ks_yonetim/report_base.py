"""Rapor ailelerinin (finans, personel) ortak uçları: liste, JSON, Excel ve PDF çıktısı."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .api import ApiError
from .database import get_session
from .exports import ReportTable, pdf_response, xlsx_response

MAX_EXPORT_ROWS = 20000

Builder = Callable[[Session, object], ReportTable]


def build_report(builders: Mapping[str, Builder], session: Session, name: str, filters: object) -> ReportTable:
    builder = builders.get(name)
    if builder is None:
        raise ApiError("not_found", "Rapor bulunamadı.", 404, {"available": sorted(builders)})
    return builder(session, filters)


def register_report_routes(router: APIRouter, builders: Mapping[str, Builder], get_filters: Callable) -> None:
    """`router` altına GET "", "/{name}", "/{name}/export.xlsx" ve "/{name}/export.pdf" uçlarını ekler."""

    def export_table(session: Session, name: str, filters: object) -> ReportTable:
        table = build_report(builders, session, name, filters)
        if len(table.rows) > MAX_EXPORT_ROWS:
            raise ApiError("too_many_rows", f"Dosya çıktısı en fazla {MAX_EXPORT_ROWS} satır içerir.", 422)
        return table

    @router.get("")
    def list_reports():
        return [{"name": name} for name in sorted(builders)]

    @router.get("/{name}")
    def json_report(
        name: str,
        filters=Depends(get_filters),
        limit: int = Query(500, ge=1, le=2000),
        offset: int = Query(0, ge=0),
        session: Session = Depends(get_session),
    ):
        table = build_report(builders, session, name, filters)
        body = table.to_json()
        body["limit"], body["offset"] = limit, offset
        body["rows"] = table.rows[offset : offset + limit]  # toplamlar tüm satırlardan hesaplanır
        return body

    @router.get("/{name}/export.xlsx")
    def xlsx_report(name: str, filters=Depends(get_filters), session: Session = Depends(get_session)):
        return xlsx_response(export_table(session, name, filters), f"rapor-{name}.xlsx")

    @router.get("/{name}/export.pdf")
    def pdf_report(name: str, filters=Depends(get_filters), session: Session = Depends(get_session)):
        return pdf_response(export_table(session, name, filters), f"rapor-{name}.pdf")
