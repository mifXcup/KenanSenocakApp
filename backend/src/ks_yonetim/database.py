from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().resolved_database_url
    connect_args = {"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_schema(target: Engine | None = None) -> None:
    """Tabloları oluşturur; v0.1 ile açılmış veritabanlarına sonradan eklenen sütunları ekler."""
    bind = target or engine
    Base.metadata.create_all(bind=bind)
    with bind.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(purchases)")}
        if "due_date" not in columns:
            connection.exec_driver_sql("ALTER TABLE purchases ADD COLUMN due_date DATE")
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_purchases_due_date ON purchases (due_date)"
            )


def get_session() -> Generator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
