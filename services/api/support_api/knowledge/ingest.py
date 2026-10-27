import time
from pathlib import Path
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from opentelemetry import trace
from ..config import settings
from ..models import EMBEDDING_DIMENSIONS, KnowledgeChunk, KnowledgeDocument, KnowledgeIndex, uid
from .documents import chunk_document
from .embeddings import GoogleEmbedder, normalize_vector
from .policy_guard import business_fingerprint, validate_corpus

PIPELINE_VERSION = "sections220-overlap32-embedding2-search-v1"


def ingest(engine, root=None, *, embedder=None):
    cfg = settings()
    root = Path(root or cfg.knowledge_base_dir)
    # Validate all sources before opening an embedding connection or making any DB changes.
    documents, corpus_hash = validate_corpus(root)
    if engine.dialect.name != "postgresql":
        raise ValueError(
            "Hybrid indexing requires PostgreSQL with pgvector; SQLite remains available for portal tests"
        )
    with trace.get_tracer("support.knowledge").start_as_current_span("rag.ingest") as span:
        started = time.monotonic()
        with Session(engine) as db:
            active = db.scalar(select(KnowledgeIndex).where(KnowledgeIndex.status == "active"))
            compatible = (
                active
                and active.embedding_model == cfg.embedding_model
                and active.pipeline_version == PIPELINE_VERSION
                and active.embedding_dimensions == EMBEDDING_DIMENSIONS
            )
            if compatible and active.corpus_hash == corpus_hash:
                return {
                    "status": "unchanged",
                    "index_id": active.id,
                    "documents": len(documents),
                    "embedded_chunks": 0,
                }
            old_vectors = (
                {
                    c.content_hash: list(c.embedding)
                    for c in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.index_id == active.id))
                }
                if compatible
                else {}
            )
        chunks = [chunk for doc in documents for chunk in chunk_document(doc)]
        needed = {}
        for chunk in chunks:
            if chunk.content_hash not in old_vectors:
                needed[chunk.content_hash] = f"{chunk.document.title}\n{chunk.section}\n{chunk.text}"
        embedder = embedder or GoogleEmbedder(cfg, indexing=True)
        keys = list(needed)
        vectors = dict(old_vectors)
        for offset in range(0, len(keys), 32):
            batch = keys[offset : offset + 32]
            embedded = embedder.embed([needed[k] for k in batch], task="RETRIEVAL_DOCUMENT")
            if len(embedded) != len(batch):
                raise ValueError("Embedding provider returned an incomplete batch")
            vectors.update({key: normalize_vector(value) for key, value in zip(batch, embedded, strict=True)})
        # Re-check after provider I/O; never publish embeddings for changed files or rules.
        _, latest_hash = validate_corpus(root)
        if latest_hash != corpus_hash:
            raise ValueError("Knowledge corpus changed during indexing; retry")
        with Session(engine) as db, db.begin():
            db.execute(text("SELECT pg_advisory_xact_lock(76432911)"))
            winner = db.scalar(select(KnowledgeIndex).where(KnowledgeIndex.status == "active"))
            if (
                winner
                and winner.corpus_hash == corpus_hash
                and winner.embedding_model == cfg.embedding_model
                and winner.pipeline_version == PIPELINE_VERSION
                and winner.embedding_dimensions == EMBEDDING_DIMENSIONS
            ):
                return {
                    "status": "unchanged",
                    "index_id": winner.id,
                    "documents": len(documents),
                    "embedded_chunks": 0,
                }
            index = KnowledgeIndex(
                id=uid(),
                corpus_hash=corpus_hash,
                business_fingerprint=business_fingerprint(),
                embedding_model=cfg.embedding_model,
                embedding_dimensions=EMBEDDING_DIMENSIONS,
                pipeline_version=PIPELINE_VERSION,
                status="staging",
            )
            db.add(index)
            db.flush()
            records = {}
            for doc in documents:
                record = KnowledgeDocument(
                    index_id=index.id,
                    document_id=doc.document_id,
                    source_path=doc.path,
                    title=doc.title,
                    category=doc.category,
                    version=doc.version,
                    checksum=doc.checksum,
                )
                db.add(record)
                db.flush()
                records[doc.path] = record
            for chunk in chunks:
                weighted_title = func.setweight(
                    func.to_tsvector(
                        text("'english'::regconfig"), chunk.document.title + " " + chunk.section
                    ),
                    text("'A'"),
                )
                weighted_body = func.setweight(
                    func.to_tsvector(text("'english'::regconfig"), chunk.text),
                    text("'B'"),
                )
                search_vector = weighted_title.op("||")(weighted_body)
                db.add(
                    KnowledgeChunk(
                        index_id=index.id,
                        document_id=records[chunk.document.path].id,
                        ordinal=chunk.ordinal,
                        section=chunk.section,
                        text=chunk.text,
                        content_hash=chunk.content_hash,
                        embedding=vectors[chunk.content_hash],
                        search_vector=search_vector,
                    )
                )
            db.flush()
            db.execute(
                update(KnowledgeIndex).where(KnowledgeIndex.status == "active").values(status="retired")
            )
            index.status = "active"
            index_id = index.id
        elapsed = time.monotonic() - started
        span.set_attributes(
            {
                "rag.documents": len(documents),
                "rag.chunks": len(chunks),
                "rag.embedded_chunks": len(keys),
                "rag.duration_seconds": elapsed,
            }
        )
        return {
            "status": "indexed",
            "index_id": index_id,
            "documents": len(documents),
            "chunks": len(chunks),
            "embedded_chunks": len(keys),
            "reused_chunks": len(chunks) - len(keys),
            "duration_seconds": elapsed,
        }
