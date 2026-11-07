from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from . import models  # noqa: F401
from .api import ApiError, api_error_handler, router, validation_error_handler
from .attendance import router as attendance_router
from .backup import BackupError, backup_manager
from .calendar_api import router as calendar_router
from .card_reader import router as card_reader_router
from .card_reader import run_scheduled_sync
from .customers import router as customers_router
from .database import ensure_schema
from .employees import router as employees_router
from .finance import router as finance_router
from .finance_reports import router as finance_reports_router
from .leave import router as leave_router
from .ml import router as ml_router
from .operations import router as operations_router
from .payroll import router as payroll_router
from .pdf_exports import router as pdf_router
from .pricing import router as pricing_router
from .project_costs import router as project_costs_router
from .project_finance import router as project_finance_router
from .receipts import router as receipts_router
from .savings import router as savings_router
from .spreadsheet_io import router as spreadsheet_router
from .staff_reports import router as staff_reports_router
from .supplier_ledger import router as supplier_ledger_router
from .worklogs import router as worklogs_router

DAILY_BACKUP_CHECK_SECONDS = 3600


def _run_daily_backup() -> None:
    try:
        backup_manager.ensure_daily_automatic()
    except BackupError:
        # Uygulama çalışır; sorun /backups/status üzerinden görünür kalır.
        pass


async def _daily_backup_loop() -> None:
    # Uygulama günlerce açık kalırsa günlük otomatik yedek de her gün alınır.
    while True:
        await asyncio.sleep(DAILY_BACKUP_CHECK_SECONDS)
        await asyncio.to_thread(_run_daily_backup)


CARD_READER_CHECK_SECONDS = 60


async def _card_reader_loop() -> None:
    # Kart okuyucu eşitlemesi ayarlardan açıksa ve süre dolduysa Google Sheet'ten yeni hareketleri alır.
    while True:
        await asyncio.sleep(CARD_READER_CHECK_SECONDS)
        await asyncio.to_thread(run_scheduled_sync)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    _run_daily_backup()
    tasks = [asyncio.create_task(_daily_backup_loop()), asyncio.create_task(_card_reader_loop())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()


app = FastAPI(
    title="Kenan Şenocak Yönetim Core",
    version="0.5.2",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(router)
app.include_router(employees_router)
app.include_router(operations_router)
app.include_router(worklogs_router)
app.include_router(payroll_router)
app.include_router(finance_router)
app.include_router(finance_reports_router)
app.include_router(customers_router)
app.include_router(attendance_router)
app.include_router(leave_router)
app.include_router(calendar_router)
app.include_router(project_costs_router)
app.include_router(project_finance_router)
app.include_router(pricing_router)
app.include_router(receipts_router)
app.include_router(supplier_ledger_router)
app.include_router(staff_reports_router)
app.include_router(spreadsheet_router)
app.include_router(ml_router)
app.include_router(savings_router)
app.include_router(pdf_router)
app.include_router(card_reader_router)
