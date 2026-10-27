from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ks_yonetim import models  # noqa: F401
from ks_yonetim.config import get_settings
from ks_yonetim.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().resolved_database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # ks_yonetim.migrate.upgrade_database bağlantıyı doğrudan verir; CLI ise ayarlardaki URL'yi kullanır.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    config.set_main_option("sqlalchemy.url", get_settings().resolved_database_url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as live:
        context.configure(connection=live, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
