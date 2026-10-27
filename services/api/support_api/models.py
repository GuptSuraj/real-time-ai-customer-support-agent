from pgvector.sqlalchemy import Vector
from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import TSVECTOR
import time
import uuid
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid.uuid4())


class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(100))


class Customer(Record, Base):
    __tablename__ = "customers"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    notes: Mapped[str] = mapped_column(Text, default="")


class LoginSession(Record, Base):
    __tablename__ = "login_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[float] = mapped_column(Float)


class Product(Record, Base):
    __tablename__ = "products"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    price_paise: Mapped[int] = mapped_column(Integer)
    returnable: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Record, Base):
    __tablename__ = "orders"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    delivered_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_paise: Mapped[int] = mapped_column(Integer)


class OrderItem(Record, Base):
    __tablename__ = "order_items"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class Return(Record, Base):
    __tablename__ = "returns"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="requested")
    reason: Mapped[str] = mapped_column(Text)


class Refund(Record, Base):
    __tablename__ = "refunds"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="pending_approval")
    amount_paise: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    processing_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Call(Record, Base):
    __tablename__ = "calls"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    room: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="connecting")
    language: Mapped[str] = mapped_column(String(8), default="en")
    summary: Mapped[str] = mapped_column(Text, default="")
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_epoch: Mapped[int] = mapped_column(Integer, default=0)


class Verification(Record, Base):
    __tablename__ = "verifications"
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_until: Mapped[float | None] = mapped_column(Float, nullable=True)


class PendingAction(Record, Base):
    __tablename__ = "pending_actions"
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[float] = mapped_column(Float)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Ticket(Record, Base):
    __tablename__ = "tickets"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("calls.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Escalation(Record, Base):
    __tablename__ = "escalations"
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    reason: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deadline: Mapped[float] = mapped_column(Float)
    representative_connected: Mapped[bool] = mapped_column(Boolean, default=False)


class Transcript(Record, Base):
    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("call_id", "event_id"),)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)


class Policy(Record, Base):
    __tablename__ = "policies"
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)


class Audit(Record, Base):
    __tablename__ = "audit_events"
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("calls.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(100))
    event: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Metric(Record, Base):
    __tablename__ = "metrics"
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)


class WebhookReceipt(Record, Base):
    __tablename__ = "webhook_receipts"


# SQLite retains portable metadata for existing unit tests; hybrid indexing requires PostgreSQL.

EMBEDDING_DIMENSIONS = 768


class KnowledgeIndex(Record, Base):
    __tablename__ = "knowledge_indexes"
    corpus_hash: Mapped[str] = mapped_column(String(64))
    business_fingerprint: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=EMBEDDING_DIMENSIONS)
    pipeline_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="active")


class KnowledgeDocument(Record, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("index_id", "source_path"),
        UniqueConstraint("index_id", "document_id"),
    )
    index_id: Mapped[str] = mapped_column(ForeignKey("knowledge_indexes.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(String(200))
    source_path: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(30))
    version: Mapped[str] = mapped_column(String(100))
    checksum: Mapped[str] = mapped_column(String(64))


class KnowledgeChunk(Record, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)
    index_id: Mapped[str] = mapped_column(ForeignKey("knowledge_indexes.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list] = mapped_column(Vector(EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite"))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR().with_variant(Text(), "sqlite"), nullable=True
    )


Index("ix_knowledge_chunks_fts", KnowledgeChunk.search_vector, postgresql_using="gin").ddl_if(
    dialect="postgresql"
)
Index(
    "ix_knowledge_chunks_vector",
    KnowledgeChunk.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
).ddl_if(dialect="postgresql")
Index(
    "uq_knowledge_index_active",
    KnowledgeIndex.status,
    unique=True,
    postgresql_where=KnowledgeIndex.status == "active",
).ddl_if(dialect="postgresql")
