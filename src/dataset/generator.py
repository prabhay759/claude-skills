"""
Generates data/tasks.json — 150 tasks across 6 scenarios.

Each scenario contributes exactly 25 variants:
  C(5,1) = 5   (single-bug tasks)
  C(5,2) = 10  (two-bug tasks)
  C(5,3) = 10  (three-bug tasks)
  Total  = 25

Splits (deterministic, seeded shuffle):
  train:     80  (optimizer sees these and learns from failures)
  selection: 20  (validation gate, never used for training)
  test:      50  (locked until final reporting)
"""

from __future__ import annotations

import json
import random
from itertools import combinations
from pathlib import Path

from src.dataset.scenarios import SCENARIOS

SEED = 42
SPLIT_SIZES = {"train": 80, "selection": 20, "test": 50}
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _make_diff(filename: str, code: str) -> str:
    """Wrap TypeScript source in a unified diff for a new file."""
    lines = code.splitlines()
    hunk_header = f"@@ -0,0 +1,{len(lines)} @@"
    diff_lines = [f"+{line}" for line in lines]
    return "\n".join([
        f"--- /dev/null",
        f"+++ b/{filename}",
        hunk_header,
        *diff_lines,
    ])


def _generate_variants(scenario_name: str, scenario: dict) -> list[dict]:
    """Return 25 task dicts for one scenario (all 1/2/3-bug combos)."""
    bug_ids = list(scenario["bugs"].keys())
    assert len(bug_ids) == 5, f"{scenario_name} must have exactly 5 bugs"

    variants: list[dict] = []
    for size in (1, 2, 3):
        for combo in combinations(bug_ids, size):
            active = set(combo)
            code = scenario["generate_code"](active)
            diff = _make_diff(scenario["filename"], code)

            bugs = [
                {
                    "id": f"bug_{i + 1}",
                    "bug_key": bug_id,
                    "category": scenario["bugs"][bug_id]["category"],
                    "description": scenario["bugs"][bug_id]["description"],
                    "keywords": scenario["bugs"][bug_id]["keywords"],
                }
                for i, bug_id in enumerate(sorted(combo))
            ]

            variants.append({
                "scenario": scenario_name,
                "pr_title": scenario["pr_title"],
                "pr_description": scenario["pr_description"],
                "diff": diff,
                "bugs": bugs,
            })

    assert len(variants) == 25
    return variants


def generate() -> None:
    all_tasks: list[dict] = []
    for scenario_name, scenario in SCENARIOS.items():
        all_tasks.extend(_generate_variants(scenario_name, scenario))

    assert len(all_tasks) == 150, f"Expected 150 tasks, got {len(all_tasks)}"

    # deterministic shuffle before assigning splits
    rng = random.Random(SEED)
    rng.shuffle(all_tasks)

    splits = (
        ["train"] * SPLIT_SIZES["train"]
        + ["selection"] * SPLIT_SIZES["selection"]
        + ["test"] * SPLIT_SIZES["test"]
    )
    assert len(splits) == 150

    tasks: list[dict] = []
    for idx, (task, split) in enumerate(zip(all_tasks, splits)):
        tasks.append({
            "id": f"task_{idx + 1:03d}",
            "split": split,
            **task,
        })

    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "tasks.json"
    out.write_text(json.dumps(tasks, indent=2))
    print(f"Wrote {len(tasks)} tasks to {out}")

    # summary
    from collections import Counter
    split_counts = Counter(t["split"] for t in tasks)
    scenario_counts = Counter(t["scenario"] for t in tasks)
    total_bugs = sum(len(t["bugs"]) for t in tasks)
    cat_counts = Counter(
        b["category"] for t in tasks for b in t["bugs"]
    )

    print(f"\nSplit distribution:    {dict(split_counts)}")
    print(f"Scenario distribution: {dict(scenario_counts)}")
    print(f"Total planted bugs:    {total_bugs}")
    print(f"Bug categories:        {dict(cat_counts)}")


if __name__ == "__main__":
    generate()
