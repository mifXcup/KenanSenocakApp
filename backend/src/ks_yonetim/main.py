from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from . import models  # noqa: F401
from .api import ApiError, api_error_handler, router, validation_error_handler
from .backup import BackupError, backup_manager
from .database import ensure_schema
from .employees import router as employees_router
from .finance import router as finance_router
from .ml import router as ml_router
from .operations import router as operations_router
from .payroll import router as payroll_router
from .pdf_exports import router as pdf_router
from .project_costs import router as project_costs_router
from .spreadsheet_io import router as spreadsheet_router
from .staff_reports import router as staff_reports_router
from .worklogs import router as worklogs_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    try:
        backup_manager.ensure_daily_automatic()
    except BackupError:
        # Uygulama açılır; sorun /backups/status üzerinden görünür kalır.
        pass
    yield


app = FastAPI(
    title="Kenan Şenocak Yönetim Core",
    version="0.3.0",
    docs_url=None,
    redoc_url=None,
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
app.include_router(project_costs_router)
app.include_router(staff_reports_router)
app.include_router(spreadsheet_router)
app.include_router(ml_router)
app.include_router(pdf_router)
