import argparse
import json
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from ..config import settings
from ..db import engine
from ..telemetry import configure
from .ingest import ingest
from .policy_guard import approve_review, validate_corpus


def main():
    parser = argparse.ArgumentParser(
        description="API-owned knowledge policy review and atomic hybrid indexing"
    )
    parser.add_argument("command", choices=["audit", "index", "review"])
    parser.add_argument("--root", type=Path, default=Path(settings().knowledge_base_dir))
    parser.add_argument(
        "--approve-reviewed",
        action="store_true",
        help="Record explicit source review after reading all changed documents and backend rules",
    )
    args = parser.parse_args()
    try:
        if args.command == "review":
            if not args.approve_reviewed:
                parser.error(
                    "Read the policy reconciliation report, then use --approve-reviewed to record your review"
                )
            result = approve_review(args.root)
            print(json.dumps({"status": "review_recorded", "documents": len(result["documents"])}))
        elif args.command == "audit":
            docs, corpus_hash = validate_corpus(args.root)
            print(json.dumps({"status": "consistent", "documents": len(docs), "corpus_hash": corpus_hash}))
        else:
            configure("support-knowledge-indexer")
            print(json.dumps(ingest(engine, args.root), indent=2))
    except SQLAlchemyError as exc:
        raise SystemExit(
            f"Index database operation failed ({type(exc).__name__}); verify migrations, pgvector, and connectivity"
        ) from None
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
