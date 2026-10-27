"""A reviewed corpus + backend fingerprint gates indexing; no LLM guesses about policy authority."""

import ast
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from ..business_rules import policy_contract
from .documents import load_documents, sha

API_ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = Path(__file__).with_name("policy_review.json")
AUTHORITY = {
    "domain.py": {"eligibility", "validate_action", "prepare_action", "confirm_action"},
    "main.py": {"challenge", "complete_verification", "decide_refund", "agent_escalate", "agent_handoff_ack"},
    "seed.py": {"seed"},
}


def business_fingerprint():
    sources = {}
    for filename, names in AUTHORITY.items():
        tree = ast.parse((API_ROOT / filename).read_text())
        sources[filename] = [
            ast.dump(node, include_attributes=False)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
        ]
        if len(sources[filename]) != len(names):
            raise ValueError(f"Missing audited backend rule in {filename}")
    return sha(json.dumps({"contract": policy_contract(), "authority": sources}, sort_keys=True))


def semantic_issues(docs):
    """Supplement human review with checks for the known high-impact numeric contradictions."""
    issues = []
    for doc in docs:
        if doc.category == "product_guides":
            continue
        body = doc.body.lower()
        for match in re.finditer(
            r"(\d+)[ -](?:calendar[ -])?day(?:s)?[^.\n]{0,60}(?:return|request window)", body
        ):
            if int(match[1]) != policy_contract()["return_window_days"]:
                issues.append(f"{doc.path}: return-window value {match[1]} conflicts with backend")
        if re.search(r"\b14[ -](?:calendar[ -])?day", body):
            issues.append(f"{doc.path}: obsolete 14-day return assumption")
        if re.search(r"3\s*(?:to|–|-)\s*7\s+business days", body):
            issues.append(f"{doc.path}: shipping estimate conflicts with saved 3–5 day policy")
    return issues


def validate_corpus(root, *, review_path=REVIEW_PATH):
    docs = load_documents(Path(root))
    issues = semantic_issues(docs)
    if not Path(review_path).is_file():
        raise ValueError("Knowledge policy review is missing; review documents against backend rules first")
    review = json.loads(Path(review_path).read_text())
    if review["business_fingerprint"] != business_fingerprint():
        issues.append("Backend business rules changed since policy review; re-review the corpus")
    current = {d.path: d.checksum for d in docs}
    if review["documents"] != current:
        issues.append("Knowledge documents changed since policy review; re-review before indexing")
    if issues:
        raise ValueError("Policy consistency gate failed:\n" + "\n".join(issues))
    return docs, sha(json.dumps({"files": current, "rules": review["business_fingerprint"]}, sort_keys=True))


def approve_review(root, *, review_path=REVIEW_PATH):
    docs = load_documents(Path(root))
    issues = semantic_issues(docs)
    if issues:
        raise ValueError("\n".join(issues))
    data = {
        "reviewed_on": datetime.now(timezone.utc).date().isoformat(),
        "business_contract": policy_contract(),
        "business_fingerprint": business_fingerprint(),
        "documents": {d.path: d.checksum for d in docs},
        "review_method": "Source-level engineering review plus numeric checks; hashes require explicit re-review for any document or authority change",
    }
    Path(review_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data
