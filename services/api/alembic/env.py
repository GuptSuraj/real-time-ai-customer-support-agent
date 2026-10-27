from alembic import context
from support_api.config import settings
from support_api.db import Base, engine
from support_api import models  # noqa: F401

POSTGRES_ONLY_INDEXES = {"ix_knowledge_chunks_fts", "ix_knowledge_chunks_vector", "uq_knowledge_index_active"}


def include_object(obj, name, type_, reflected, compare_to):
    # SQLAlchemy ddl_if controls creation, but Alembic comparison needs the same dialect boundary.
    if type_ == "index" and name in POSTGRES_ONLY_INDEXES and engine.dialect.name != "postgresql":
        return False
    return True


if context.is_offline_mode():
    context.configure(
        url=settings().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
