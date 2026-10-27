"""Versioned knowledge corpus, pgvector embeddings and PostgreSQL full-text indexes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR
from pgvector.sqlalchemy import Vector

revision = "0002"
down_revision = "0001"


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.create_table(
        "knowledge_indexes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("corpus_hash", sa.String(64), nullable=False),
        sa.Column("business_fingerprint", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("pipeline_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column(
            "index_id",
            sa.String(64),
            sa.ForeignKey("knowledge_indexes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(200), nullable=False),
        sa.Column("source_path", sa.String(500), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.UniqueConstraint("index_id", "source_path"),
        sa.UniqueConstraint("index_id", "document_id"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column(
            "index_id",
            sa.String(64),
            sa.ForeignKey("knowledge_indexes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(768) if postgres else sa.JSON(), nullable=False),
        sa.Column("search_vector", TSVECTOR() if postgres else sa.Text(), nullable=True),
        sa.UniqueConstraint("document_id", "ordinal"),
    )
    for table, columns in [
        ("knowledge_documents", ["index_id"]),
        ("knowledge_chunks", ["index_id", "document_id"]),
    ]:
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    if postgres:
        op.create_index(
            "ix_knowledge_chunks_fts", "knowledge_chunks", ["search_vector"], postgresql_using="gin"
        )
        op.create_index(
            "ix_knowledge_chunks_vector",
            "knowledge_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
        op.create_index(
            "uq_knowledge_index_active",
            "knowledge_indexes",
            ["status"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        )


def downgrade():
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_indexes")
    # The vector extension may be shared; never drop it here.
