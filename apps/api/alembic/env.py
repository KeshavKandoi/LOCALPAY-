from sqlalchemy import MetaData

from alembic import context
from app.core.settings import get_settings
from app.db.session import build_engine

metadata = MetaData()
settings = get_settings()

if context.is_offline_mode():
    context.configure(
        url=str(settings.database_url),
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
