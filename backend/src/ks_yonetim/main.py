from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from . import models  # noqa: F401
from .api import ApiError, api_error_handler, router, validation_error_handler
from .backup import BackupError, backup_manager
from .database import ensure_schema
from .operations import router as operations_router
from .spreadsheet_io import router as spreadsheet_router


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
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(router)
app.include_router(operations_router)
app.include_router(spreadsheet_router)
