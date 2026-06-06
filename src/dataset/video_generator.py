"""
Generates data/video_tasks.json — 150 tasks across 6 scenarios.

Each scenario contributes exactly 25 variants:
  C(5,1) = 5   (single-step tasks)
  C(5,2) = 10  (two-step tasks)
  C(5,3) = 10  (three-step tasks)
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

from src.dataset.video_scenarios import SCENARIOS

SEED = 42
SPLIT_SIZES = {"train": 80, "selection": 20, "test": 50}
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _generate_variants(scenario_name: str, scenario: dict) -> list[dict]:
    """Return 25 task dicts for one scenario (all 1/2/3-step combos)."""
    step_ids = list(scenario["steps"].keys())
    assert len(step_ids) == 5, f"{scenario_name} must have exactly 5 steps"

    variants: list[dict] = []
    for size in (1, 2, 3):
        for combo in combinations(step_ids, size):
            active = set(combo)
            transcript = scenario["generate_transcript"](active)

            required_steps = [
                {
                    "id": f"step_{i + 1}",
                    "step_key": step_id,
                    "category": scenario["steps"][step_id]["category"],
                    "description": scenario["steps"][step_id]["description"],
                    "keywords": scenario["steps"][step_id]["keywords"],
                }
                for i, step_id in enumerate(sorted(combo))
            ]

            variants.append({
                "scenario": scenario_name,
                "title": scenario["title"],
                "workflow_description": scenario["description"],
                "transcript": transcript,
                "required_steps": required_steps,
            })

    assert len(variants) == 25
    return variants


def generate() -> None:
    all_tasks: list[dict] = []
    for scenario_name, scenario in SCENARIOS.items():
        all_tasks.extend(_generate_variants(scenario_name, scenario))

    assert len(all_tasks) == 150, f"Expected 150 tasks, got {len(all_tasks)}"

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
            "id": f"vtask_{idx + 1:03d}",
            "split": split,
            **task,
        })

    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / "video_tasks.json"
    out.write_text(json.dumps(tasks, indent=2))
    print(f"Wrote {len(tasks)} tasks to {out}")

    from collections import Counter
    split_counts = Counter(t["split"] for t in tasks)
    scenario_counts = Counter(t["scenario"] for t in tasks)
    total_steps = sum(len(t["required_steps"]) for t in tasks)
    cat_counts = Counter(
        s["category"] for t in tasks for s in t["required_steps"]
    )

    print(f"\nSplit distribution:    {dict(split_counts)}")
    print(f"Scenario distribution: {dict(scenario_counts)}")
    print(f"Total required steps:  {total_steps}")
    print(f"Step categories:       {dict(cat_counts)}")


if __name__ == "__main__":
    generate()
