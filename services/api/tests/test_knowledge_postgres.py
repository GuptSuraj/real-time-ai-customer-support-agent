import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from support_api.db import Base
from support_api.knowledge import ingest as ingest_module
from support_api.knowledge import retrieval
from support_api.knowledge.embeddings import EmbeddingUnavailable
from support_api.knowledge.policy_guard import approve_review, validate_corpus
from support_api.models import KnowledgeChunk, KnowledgeDocument, KnowledgeIndex
from support_api.seed import seed


class FixtureEmbedder:
    """Deterministic vectors test SQL/fusion only, never claim multilingual model quality."""

    def __init__(self):
        self.calls = []

    def embed(self, texts, *, task):
        self.calls.append((task, list(texts)))
        vectors = []
        for content in texts:
            value = content.lower()
            index = 1 if any(w in value for w in ["refund", "रिफंड", "paise"]) else 0
            if "shipping" in value:
                index = 2
            if "bluetooth" in value:
                index = 3
            vector = [0.0] * 768
            vector[index] = 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture()
def knowledge_db(tmp_path, monkeypatch):
    url = os.getenv("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_URL is required for pgvector/full-text integration")
    admin = create_engine(url)
    schema = "rag_test_" + uuid.uuid4().hex
    with admin.begin() as db:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema},public"},
        execution_options={"schema_translate_map": {None: schema}},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
    root = tmp_path / "kb"
    (root / "policies").mkdir(parents=True)
    for name, title, body in [
        (
            "return",
            "Returns",
            "A whole-order return request is allowed within 30 calendar days of delivery. Identity verification is required.",
        ),
        (
            "refund",
            "Refund approval",
            "A refund requires a return marked received, customer confirmation and human approval. Payments are simulated.",
        ),
        (
            "shipping",
            "Shipping",
            "Standard shipping usually takes 3 to 5 business days. Dates are not guaranteed.",
        ),
        (
            "bluetooth",
            "Bluetooth headphones",
            "For Bluetooth pairing problems, check charge and remove stale pairing. Never open the device.",
        ),
    ]:
        (root / f"policies/{name}.txt").write_text(
            f"Title: {title}\nDocument ID: {name}\nLanguage: English\nVersion: v1\n\n{title}\n\nOverview\n\n{body}\n"
        )
    review = tmp_path / "review.json"
    approve_review(root, review_path=review)
    monkeypatch.setattr(
        ingest_module, "validate_corpus", lambda root: validate_corpus(root, review_path=review)
    )
    yield engine, root, review, schema
    engine.dispose()
    with admin.begin() as db:
        db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def test_real_vector_fts_and_rrf_return_source_metadata(knowledge_db):
    engine, root, _, schema = knowledge_db
    fake = FixtureEmbedder()
    result = ingest_module.ingest(engine, root, embedder=fake)
    assert result["documents"] == 4 and result["embedded_chunks"] == 4
    with Session(engine) as db:
        response = retrieval.retrieve(db, "refund human approval", embedder=fake)
        assert response["mode"] == "hybrid", response
        assert response["sources"][0]["document_id"] == "refund"
        source = response["sources"][0]
        assert source["semantic_rank"] == 1 and source["lexical_rank"] == 1
        assert source["source_path"] == "knowledge_base/policies/refund.txt"
        assert source["rrf_score"] == pytest.approx(2 / 61)
        dimensions = (
            db.execute(text(f'SELECT DISTINCT vector_dims(embedding) FROM "{schema}".knowledge_chunks'))
            .scalars()
            .all()
        )
        assert dimensions == [768]
        indexes = (
            db.execute(text("SELECT indexdef FROM pg_indexes WHERE schemaname=:schema"), {"schema": schema})
            .scalars()
            .all()
        )
        assert any("USING hnsw" in index for index in indexes)
        assert any("USING gin" in index for index in indexes)


def test_semantic_leg_can_retrieve_without_english_keyword_overlap(knowledge_db):
    engine, root, _, _ = knowledge_db
    fake = FixtureEmbedder()
    ingest_module.ingest(engine, root, embedder=fake)
    with Session(engine) as db:
        # Stub maps the Hindi question to the refund vector; real multilingual quality is evaluated separately.
        response = retrieval.retrieve(db, "रिफंड", embedder=fake)
        assert response["sources"][0]["document_id"] == "refund"
        assert fake.calls[-1] == ("RETRIEVAL_QUERY", ["रिफंड"])


def test_reindex_is_idempotent_reuses_vectors_and_hides_deleted_sources(knowledge_db):
    engine, root, review, _ = knowledge_db
    fake = FixtureEmbedder()
    first = ingest_module.ingest(engine, root, embedder=fake)
    calls = len(fake.calls)
    assert ingest_module.ingest(engine, root, embedder=fake)["status"] == "unchanged"
    assert len(fake.calls) == calls
    (root / "policies/refund.txt").unlink()
    approve_review(root, review_path=review)
    second = ingest_module.ingest(engine, root, embedder=fake)
    assert second["embedded_chunks"] == 0 and second["documents"] == 3
    assert second["index_id"] != first["index_id"]
    with Session(engine) as db:
        response = retrieval.retrieve(db, "refund", embedder=fake)
        assert all(s["document_id"] != "refund" for s in response["sources"])
        assert (
            db.scalar(
                select(func.count()).select_from(KnowledgeIndex).where(KnowledgeIndex.status == "active")
            )
            == 1
        )
        assert (
            db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 7
        )  # Historical generations retained.


def test_failed_embedding_or_unreviewed_edit_preserves_active_generation(knowledge_db):
    engine, root, review, _ = knowledge_db
    first = ingest_module.ingest(engine, root, embedder=FixtureEmbedder())
    path = root / "policies/refund.txt"
    path.write_text(path.read_text() + "\nStaff can investigate a delayed request.\n")
    with pytest.raises(ValueError, match="changed since policy review"):
        ingest_module.ingest(engine, root, embedder=FixtureEmbedder())
    approve_review(root, review_path=review)

    class Broken:
        def embed(self, *args, **kwargs):
            raise EmbeddingUnavailable("test outage")

    with pytest.raises(EmbeddingUnavailable):
        ingest_module.ingest(engine, root, embedder=Broken())
    with Session(engine) as db:
        assert (
            db.scalar(select(KnowledgeIndex).where(KnowledgeIndex.status == "active")).id == first["index_id"]
        )
        response = retrieval.retrieve(db, "refund", embedder=Broken())
        assert response["mode"] == "lexical_only" and response["status"] == "degraded"
        assert response["sources"][0]["document_id"] == "refund"


def test_database_timeout_recovers_in_savepoint_and_uses_fts(knowledge_db, monkeypatch):
    engine, root, _, _ = knowledge_db
    ingest_module.ingest(engine, root, embedder=FixtureEmbedder())
    original = retrieval._query
    count = 0

    def timeout_first(db, statement):
        nonlocal count
        count += 1
        return original(db, text("SELECT pg_sleep(2)")) if count == 1 else original(db, statement)

    monkeypatch.setattr(retrieval, "_query", timeout_first)
    started = time.monotonic()
    with Session(engine) as db:
        result = retrieval.retrieve(db, "refund", embedder=FixtureEmbedder())
        assert result["mode"] == "lexical_only", result
        assert result["sources"][0]["document_id"] == "refund"
        assert db.scalar(select(func.count()).select_from(KnowledgeChunk)) == 4
    assert time.monotonic() - started < 2


def test_model_mismatch_does_not_embed_or_compare_incompatible_vectors(knowledge_db):
    engine, root, _, _ = knowledge_db
    ingest_module.ingest(engine, root, embedder=FixtureEmbedder())
    with Session(engine) as db:
        active = db.scalar(select(KnowledgeIndex).where(KnowledgeIndex.status == "active"))
        active.embedding_model = "gemini-embedding-001"
        db.commit()
    fake = FixtureEmbedder()
    with Session(engine) as db:
        result = retrieval.retrieve(db, "refund", embedder=fake)
        assert result["mode"] == "lexical_only" and not fake.calls


def test_business_rule_drift_blocks_stale_policy_answers(knowledge_db, monkeypatch):
    engine, root, _, _ = knowledge_db
    ingest_module.ingest(engine, root, embedder=FixtureEmbedder())
    monkeypatch.setattr(retrieval, "business_fingerprint", lambda: "different-rules")
    with Session(engine) as db:
        result = retrieval.retrieve(db, "return window", embedder=FixtureEmbedder())
        assert result["mode"] == "unavailable" and result["no_match"] is True
        assert not result["sources"] and not result["policies"]


def test_concurrent_index_publication_keeps_one_active_generation(knowledge_db):
    engine, root, _, _ = knowledge_db
    barrier = Barrier(2)

    class Concurrent(FixtureEmbedder):
        def embed(self, texts, *, task):
            barrier.wait(timeout=10)
            return super().embed(texts, task=task)

    def execute(_):
        return ingest_module.ingest(engine, root, embedder=Concurrent())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert {r["status"] for r in results} == {"indexed", "unchanged"}
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(KnowledgeIndex).where(KnowledgeIndex.status == "active")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(KnowledgeChunk)) == 4


def test_retrieval_spans_include_latency_but_no_raw_question(knowledge_db):
    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    engine, root, _, _ = knowledge_db
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    ingest_module.ingest(engine, root, embedder=FixtureEmbedder())
    with Session(engine) as db:
        retrieval.retrieve(db, "refund private-marker-123", embedder=FixtureEmbedder())
    spans = exporter.get_finished_spans()
    names = {s.name for s in spans}
    assert {
        "rag.retrieve",
        "rag.embed_query",
        "rag.vector_search",
        "rag.full_text_search",
        "rag.rrf",
    } <= names
    span = next(s for s in spans if s.name == "rag.retrieve")
    assert span.attributes["rag.duration_ms"] > 0
    assert span.attributes["rag.embedding_model"] == "gemini-embedding-2"
    assert all("private-marker" not in str(s.attributes) for s in spans)


def test_existing_authenticated_api_serves_hybrid_results_and_persists_latency(knowledge_db, monkeypatch):
    from fastapi.testclient import TestClient
    from support_api import main
    from support_api.db import get_db
    from support_api.models import Call, Metric
    from support_api.security import agent_token

    engine, root, _, _ = knowledge_db
    fake = FixtureEmbedder()
    ingest_module.ingest(engine, root, embedder=fake)
    monkeypatch.setattr(retrieval, "GoogleEmbedder", lambda cfg: fake)
    with Session(engine) as db:
        call = Call(customer_id="cust-aarav", room="rag-api-test", status="active")
        db.add(call)
        db.commit()
        token, call_id = agent_token(call), call.id

    def override():
        with Session(engine) as db:
            yield db

    from opentelemetry import trace
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    main.app.dependency_overrides[get_db] = override
    try:
        client = TestClient(main.app)
        result = client.get(
            "/internal/knowledge",
            params={"q": "refund private-question-marker"},
            headers={"Authorization": "Bearer " + token},
        )
        assert result.status_code == 200, result.text
        assert result.json()["mode"] == "hybrid"
        assert result.json()["sources"][0]["document_id"] == "refund"
        assert all("private-question-marker" not in str(s.attributes) for s in exporter.get_finished_spans())
        with Session(engine) as db:
            assert db.scalar(
                select(Metric).where(Metric.call_id == call_id, Metric.name == "retrieval_latency_seconds")
            )
    finally:
        main.app.dependency_overrides.clear()


def test_irrelevant_lexical_homonym_is_not_accepted_when_semantics_reject_it(knowledge_db):
    engine, root, _, _ = knowledge_db
    ingest_module.ingest(engine, root, embedder=FixtureEmbedder())

    class Unrelated:
        def embed(self, texts, *, task):
            return [[0.0] * 767 + [1.0] for _ in texts]

    with Session(engine) as db:
        response = retrieval.retrieve(db, "refund unrelated astronomy", embedder=Unrelated())
        assert response["mode"] == "hybrid" and response["no_match"] is True
        assert not response["sources"]
