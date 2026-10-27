import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from sqlalchemy import select
from support_api.knowledge.documents import Document, chunk_document, load_documents, sha
from support_api.knowledge.embeddings import EmbeddingUnavailable, GoogleEmbedder, normalize_vector
from support_api.knowledge.policy_guard import approve_review, validate_corpus
from support_api.knowledge.retrieval import lexical_query, reciprocal_rank_fusion
from support_api.models import Metric
from support_api.config import Settings

ROOT = Path(__file__).resolve().parents[3] / "knowledge_base"


def test_actual_corpus_matches_reviewed_backend_rules():
    docs, checksum = validate_corpus(ROOT)
    assert len(docs) == 33
    assert {d.category for d in docs} == {"policies", "faqs", "product_guides"}
    assert len(checksum) == 64
    assert "30-calendar-day" in next(d.body for d in docs if d.document_id == "en-policy-007")
    assert "3 to 5" in next(d.body for d in docs if d.document_id == "en-policy-003")


def write_document(
    root, text="The return window is 30-calendar-day for a return request.", *, document_id="policy-test"
):
    target = root / "policies/test.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"Title: Test policy\nDocument ID: {document_id}\nLanguage: English\nVersion: test-v1\n\nTest policy\n\nReturn window\n\n{text}\n"
    )
    return target


def test_changes_and_backend_drift_block_reviewed_corpus(tmp_path, monkeypatch):
    from support_api.knowledge import policy_guard

    root = tmp_path / "kb"
    doc = write_document(root)
    review = tmp_path / "review.json"
    approve_review(root, review_path=review)
    validate_corpus(root, review_path=review)
    doc.write_text(doc.read_text() + "\nNew unchecked statement.\n")
    with pytest.raises(ValueError, match="changed since policy review"):
        validate_corpus(root, review_path=review)
    approve_review(root, review_path=review)
    monkeypatch.setattr(policy_guard, "business_fingerprint", lambda: "changed-backend")
    with pytest.raises(ValueError, match="Backend business rules changed"):
        validate_corpus(root, review_path=review)


@pytest.mark.parametrize(
    "body",
    [
        "The return window is 14-calendar-day for a return request.",
        "The return window is 60-calendar-day for a return request.",
        "Standard delivery takes 3 to 7 business days.",
    ],
)
def test_conflicting_policy_cannot_be_approved(tmp_path, body):
    write_document(tmp_path / "kb", body)
    with pytest.raises(ValueError, match="conflicts|obsolete"):
        approve_review(tmp_path / "kb", review_path=tmp_path / "review.json")


def test_malformed_and_duplicate_documents_fail_validation(tmp_path):
    doc = write_document(tmp_path)
    doc.with_name("duplicate.txt").write_text(doc.read_text())
    with pytest.raises(ValueError, match="Duplicate Document ID"):
        load_documents(tmp_path)
    doc.with_name("duplicate.txt").unlink()
    doc.write_text("No metadata here")
    with pytest.raises(ValueError, match="metadata"):
        load_documents(tmp_path)


def test_symlinks_are_never_ingested(tmp_path):
    real = write_document(tmp_path / "outside")
    root = tmp_path / "kb"
    (root / "policies").mkdir(parents=True)
    (root / "policies/linked.txt").symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        load_documents(root)


def test_section_chunking_has_overlap_and_provenance():
    words = " ".join(f"token{i}" for i in range(500)) + "."
    doc = Document(
        "policies/long.txt",
        "long",
        "Long policy",
        "v1",
        "policies",
        "Long policy\n\nEligibility details\n\n" + words,
        sha(words),
    )
    chunks = chunk_document(doc)
    assert len(chunks) == 3
    assert all(c.section == "Eligibility details" and c.document.path == "policies/long.txt" for c in chunks)
    assert chunks[0].text.split()[-32:] == chunks[1].text.split()[:32]
    assert len({c.content_hash for c in chunks}) == 3
    assert all(len(c.text.split()) <= 220 for c in chunks)


def test_short_sentence_is_indexable():
    doc = Document(
        "policies/a.txt", "a", "Title", "v1", "policies", "Title\n\nReturns require verification.", "hash"
    )
    assert chunk_document(doc)[0].text == "Returns require verification."


def test_rrf_uses_ranks_not_incomparable_scores_and_deduplicates():
    scores, ranks = reciprocal_rank_fusion(["a", "b", "a"], ["b", "c"])
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)
    assert ranks["b"] == {"semantic": 2, "lexical": 1}
    assert scores["b"] > scores["a"]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("मेरे पैसे वापस कब आएंगे?", "refund"),
        ("mera refund abhi nahi aaya", "refund"),
        ("हेडफ़ोन ब्लूटूथ कनेक्ट नहीं हो रहा", "bluetooth"),
        ("return window कितने दिन है", "return"),
    ],
)
def test_multilingual_lexical_anchors(question, expected):
    assert expected in lexical_query(question)


def test_sql_like_text_is_lexical_data_not_an_operator():
    result = lexical_query("refund'); DROP TABLE users; --")
    assert "'" not in result and ";" not in result


@pytest.mark.parametrize("values", [[0.0] * 768, [1.0] * 767, [float("nan")] * 768, [float("inf")] * 768])
def test_bad_embedding_is_rejected(values):
    with pytest.raises(EmbeddingUnavailable):
        normalize_vector(values)


def test_embeddings_are_unit_normalized_and_missing_key_fails_without_network():
    normalized = normalize_vector([2.0] * 768)
    assert sum(v * v for v in normalized) == pytest.approx(1.0)
    embedder = GoogleEmbedder(Settings(google_api_key=""))
    with pytest.raises(EmbeddingUnavailable, match="GOOGLE_API_KEY"):
        embedder.embed(["question"], task="RETRIEVAL_QUERY")


def test_knowledge_endpoint_keeps_auth_and_returns_explicit_legacy_fallback(call):
    client, factory, c, headers = call
    assert client.get("/internal/knowledge", params={"q": "return policy"}).status_code == 401
    result = client.get("/internal/knowledge", params={"q": "return policy"}, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["mode"] == "legacy" and data["status"] == "degraded"
    browse = client.get("/internal/knowledge", headers=headers)
    assert browse.status_code == 200 and browse.json()["mode"] == "legacy"
    assert len(browse.json()["policies"]) == 4
    assert data["business_rules"]["return_window_days"] == 30
    assert len(data["products"]) == 3
    with factory() as db:
        metrics = list(db.scalars(select(Metric).where(Metric.call_id == c["id"])))
        assert any(m.name == "retrieval_latency_seconds" for m in metrics)
    assert client.get("/internal/knowledge", params={"q": "x" * 501}, headers=headers).status_code == 422
    assert client.get("/internal/knowledge", params={"q": ""}, headers=headers).status_code == 422
    assert client.get("/internal/knowledge", params={"q": "   "}, headers=headers).status_code == 422


def test_validation_occurs_before_any_indexing_or_embedding(tmp_path):
    from support_api.knowledge.ingest import ingest

    doc = write_document(tmp_path)
    doc.write_text(doc.read_text().replace("30-calendar-day", "14-calendar-day"))
    embedder, engine = Mock(), Mock()
    with pytest.raises(ValueError, match="consistency gate"):
        ingest(engine, tmp_path, embedder=embedder)
    embedder.embed.assert_not_called()


def test_embedding_two_uses_task_instructions_and_independent_content_objects(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from support_api.knowledge import embeddings

    client = MagicMock()
    client.models.embed_content.return_value = SimpleNamespace(
        embeddings=[
            SimpleNamespace(values=[1.0] + [0.0] * 767),
            SimpleNamespace(values=[0.0, 1.0] + [0.0] * 766),
        ]
    )
    monkeypatch.setattr(embeddings.genai, "Client", lambda **kwargs: client)
    cfg = Settings(
        google_api_key="test-only-placeholder", embedding_model="gemini-embedding-2", embedding_dimension=768
    )
    result = GoogleEmbedder(cfg).embed(["Title A\nBody A", "Title B\nBody B"], task="RETRIEVAL_DOCUMENT")
    args = client.models.embed_content.call_args.kwargs
    assert args["model"] == "gemini-embedding-2"
    assert args["config"].task_type is None
    assert args["config"].output_dimensionality == 768
    assert len(args["contents"]) == 2
    assert args["contents"][0].parts[0].text == "title: Title A | text: Body A"
    assert result[0] != result[1]
    assert (
        embeddings.format_input("मेरे पैसे कब आएंगे?", "RETRIEVAL_QUERY")
        == "task: search result | query: मेरे पैसे कब आएंगे?"
    )
    client.close.assert_called_once()


def test_dimension_must_match_vector_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(embedding_dimension=1536)


def test_evaluation_scores_do_not_double_count_a_document():
    from support_api.knowledge.evaluate import score_case

    case = {"id": "q", "language": "en", "query": "refund", "relevant_documents": ["a", "b"]}
    result = {
        "sources": [{"document_id": "a", "semantic_similarity": 0.8, "rrf_score": 0.02}] * 2,
        "mode": "hybrid",
        "status": "ready",
        "latency_ms": 10,
    }
    score = score_case(case, result)
    assert score["recall"] == 0.5
    assert score["reciprocal_rank"] == 1
    assert score["ndcg"] < 1


def test_evaluation_cannot_pass_with_empty_or_degraded_runs():
    from support_api.knowledge.evaluate import summarize

    assert summarize([])["targets_met"] is False
    assert summarize([])["p95_latency_ms"] is None
    row = {
        "id": "q",
        "language": "en",
        "expected": ["a"],
        "hit": True,
        "recall": 1.0,
        "reciprocal_rank": 1.0,
        "ndcg": 1.0,
        "abstained": False,
        "mode": "legacy",
        "status": "degraded",
        "latency_ms": 10,
    }
    assert summarize([row])["targets_met"] is False


def test_reviewed_corpus_paths_and_evaluation_labels_agree():
    docs, _ = validate_corpus(ROOT)
    ids = {doc.document_id for doc in docs}
    for filename in ["retrieval_cases.json", "retrieval_holdout.json"]:
        cases = json.loads((ROOT.parent / "services/api/evaluations" / filename).read_text())
        assert {c["language"] for c in cases} == {"en", "hi", "hinglish"}
        assert all(set(c["relevant_documents"]) <= ids for c in cases)
