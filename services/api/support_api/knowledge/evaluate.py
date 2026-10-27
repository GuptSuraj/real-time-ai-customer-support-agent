"""Document-level relevance and latency evaluation through the same retrieval function Mira uses."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import settings
from ..db import engine
from ..models import KnowledgeIndex
from ..telemetry import configure
from .retrieval import retrieve

DEFAULT_CASES = Path(__file__).resolve().parents[2] / "evaluations/retrieval_cases.json"


def score_case(case, result):
    relevant = set(case["relevant_documents"])
    sources = result["sources"]
    ids = [s["document_id"] for s in sources]
    seen, gains = set(), []
    for doc_id in ids:
        gains.append(int(doc_id in relevant and doc_id not in seen))
        seen.add(doc_id)
    first = next((i + 1 for i, gain in enumerate(gains) if gain), None)
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), settings().rag_top_k)))
    return {
        "id": case["id"],
        "language": case["language"],
        "query": case["query"],
        "expected": sorted(relevant),
        "retrieved": ids,
        "source_scores": [
            {
                "document_id": s["document_id"],
                "similarity": s["semantic_similarity"],
                "rrf_score": s["rrf_score"],
            }
            for s in sources
        ],
        "mode": result["mode"],
        "status": result["status"],
        "reason": result.get("reason"),
        "latency_ms": result["latency_ms"],
        "hit": bool(first) if relevant else None,
        "recall": len(relevant.intersection(ids)) / len(relevant) if relevant else None,
        "reciprocal_rank": 1 / first if first else 0.0,
        "ndcg": dcg / ideal if ideal else None,
        "abstained": not sources,
    }


def summarize(rows):
    relevant = [r for r in rows if r["expected"]]
    negative = [r for r in rows if not r["expected"]]
    successful = [r for r in rows if "error" not in r]
    latencies = sorted(r["latency_ms"] for r in successful)
    by_language = {}
    for lang in sorted({r["language"] for r in rows}):
        group = [r for r in relevant if r["language"] == lang]
        by_language[lang] = {
            "queries": len(group),
            "hit_at_k": mean(r["hit"] for r in group) if group else None,
            "mrr": mean(r["reciprocal_rank"] for r in group) if group else None,
        }
    summary = {
        "queries": len(rows),
        "errors": len(rows) - len(successful),
        "hit_at_k": mean(r["hit"] for r in relevant) if relevant else None,
        "recall_at_k": mean(r["recall"] for r in relevant) if relevant else None,
        "mrr": mean(r["reciprocal_rank"] for r in relevant) if relevant else None,
        "ndcg_at_k": mean(r["ndcg"] for r in relevant) if relevant else None,
        "out_of_domain_abstention": mean(r["abstained"] for r in negative) if negative else None,
        "p50_latency_ms": latencies[len(latencies) // 2] if latencies else None,
        "p95_latency_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
        "hybrid_ready_queries": sum(r["mode"] == "hybrid" and r["status"] == "ready" for r in rows),
        "by_language": by_language,
        "targets_met": False,
    }
    summary["targets_met"] = bool(
        relevant
        and negative
        and summary["errors"] == 0
        and summary["hybrid_ready_queries"] == len(rows)
        and summary["hit_at_k"] >= 0.85
        and summary["mrr"] >= 0.65
        and summary["p95_latency_ms"] < 3500
        and summary["out_of_domain_abstention"] == 1
        and all(g["hit_at_k"] is not None and g["hit_at_k"] >= 0.8 for g in by_language.values())
        and {"en", "hi", "hinglish"} <= set(by_language)
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=Path("evaluations/results/retrieval.json"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--require-targets", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if len({c["id"] for c in cases}) != len(cases):
        raise SystemExit("Duplicate evaluation IDs")
    if args.limit:
        cases = cases[: args.limit]
    if args.check:
        print(
            json.dumps(
                {"cases": len(cases), "languages": sorted({c["language"] for c in cases}), "live_run": False}
            )
        )
        return
    if engine.dialect.name != "postgresql":
        raise SystemExit("Retrieval evaluations require PostgreSQL + pgvector")
    configure("support-retrieval-evaluation")
    with Session(engine) as db:
        active = db.scalar(select(KnowledgeIndex).where(KnowledgeIndex.status == "active"))
        if not active:
            raise SystemExit("Index the reviewed corpus before evaluating retrieval")
        index_id = active.id
    rows = []
    for case in cases:
        try:
            with Session(engine) as db:
                result = retrieve(db, case["query"])
            row = score_case(case, result)
        except Exception as exc:
            row = {
                "id": case["id"],
                "language": case["language"],
                "expected": case["relevant_documents"],
                "hit": False,
                "recall": 0.0,
                "reciprocal_rank": 0.0,
                "ndcg": 0.0,
                "abstained": False,
                "mode": "unavailable",
                "status": "failed",
                "error": type(exc).__name__,
            }
        rows.append(row)
        print(
            json.dumps(
                {"id": row["id"], "hit": row["hit"], "mode": row["mode"], "latency_ms": row.get("latency_ms")}
            ),
            flush=True,
        )
    summary = summarize(rows)
    output = {
        "embedding_model": settings().embedding_model,
        "dimensions": settings().embedding_dimension,
        "index_id": index_id,
        "top_k": settings().rag_top_k,
        "summary": summary,
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if args.require_targets and not summary["targets_met"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
