"""Explicit local reset. Refuses to touch a database not named support_eval(.db)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluations.run_audio import reset_evaluation_database

if __name__ == "__main__":
    reset_evaluation_database()
    print("Dedicated evaluation database reset and seeded.")
