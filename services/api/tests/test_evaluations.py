import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("evaluation_report", ROOT / "evaluations/report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_unrun_and_unreviewed_results_cannot_pass_release():
    empty = module.report([])
    assert empty["release_ready"] is False
    assert empty["task_completion_rate"] is None
    result = {
        "scenario_id": "test",
        "automatic_errors": [],
        "review": {"task_success": None},
        "audio_latency_samples": [{"seconds": 0.5, "tool_turn": None}],
    }
    unreviewed = module.report([result])
    assert unreviewed["release_ready"] is False
    assert unreviewed["no_tool_audio_samples"] == 0


def test_automatic_failure_prevents_success_and_p95_excludes_tool_turns():
    results = [
        {
            "scenario_id": "test",
            "automatic_errors": ["Unauthorized write"],
            "review": {"task_success": True, "tool_accuracy": False},
            "audio_latency_samples": [
                {"seconds": 1.0, "tool_turn": False},
                {"seconds": 10.0, "tool_turn": True},
            ],
        }
    ]
    output = module.report(results)
    assert output["task_completion_rate"] == 0
    assert output["no_tool_audio_p95_seconds"] == 1.0
    assert output["tool_turn_audio_p95_seconds"] == 10.0
    assert output["release_ready"] is False


def test_scenario_manifest_covers_required_categories():
    from collections import Counter

    scenarios = json.loads((ROOT / "evaluations/scenarios.json").read_text())
    assert Counter(s["category"] for s in scenarios) == {
        "orders": 8,
        "returns": 8,
        "refunds": 8,
        "policies": 6,
        "handoff": 6,
        "language": 6,
        "resilience": 8,
    }
    assert len({s["id"] for s in scenarios}) == 50
    assert all(s["turns"] and s["expected"] and s["review_criteria"] for s in scenarios)
