"""
Rollout runner for the video-to-skill benchmark.

Calls the video-to-skill agent on a batch of video transcript tasks,
scores the generated skill documents, and writes results as JSONL.

Usage:
  python -m src.video_runner --split train --limit 10
  python -m src.video_runner --split selection
  python -m src.video_runner --split train --model claude-haiku-4-5-20251001 --output data/video_run.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from src.backend import complete
from src.video_scorer import score_skill_doc, aggregate

# ─── constants ────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DATA_DIR      = Path(__file__).parent.parent / "data"
SKILL_PATH    = Path(__file__).parent.parent / "video_skill.md"


# ─── prompt helpers ───────────────────────────────────────────────────────────

def _build_user_message(task: dict) -> str:
    return (
        f"Workflow: {task['workflow_description']}\n"
        "\n"
        f"{task['transcript']}"
    )


def _load_skill(path: Path) -> str:
    return path.read_text()


# ─── single-task rollout ──────────────────────────────────────────────────────

def run_task(task: dict, skill_text: str, model: str) -> dict:
    """Call the claude CLI for one task and return a scored result dict."""
    start = time.monotonic()

    call = complete(
        system=skill_text,
        user=_build_user_message(task),
        model=model,
    )

    elapsed   = time.monotonic() - start
    skill_doc = call.text
    result    = score_skill_doc(skill_doc, task)

    return {
        "task_id":        task["id"],
        "scenario":       task["scenario"],
        "split":          task["split"],
        "n_steps":        result.n_steps,
        "score":          result.score,
        "coverage_score": result.coverage_score,
        "structure_score": result.structure_score,
        "covered":        [r.step_key for r in result.covered],
        "missed":         [r.step_key for r in result.missed],
        "by_category": {
            cat: {"covered": v["covered"], "total": v["total"]}
            for cat, v in result.by_category().items()
        },
        "structure_checks": result.structure_checks,
        "skill_doc":      skill_doc,
        "model":          model,
        "elapsed_s":      round(elapsed, 2),
        "usage":          call.usage,
        "cost_usd":       round(call.cost_usd, 6),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


# ─── batch rollout ────────────────────────────────────────────────────────────

def run_rollout(
    split: str,
    limit: int | None = None,
    output_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    tasks_path: Path = DATA_DIR / "video_tasks.json",
    skill_path: Path = SKILL_PATH,
    verbose: bool = True,
    workers: int = 8,
) -> list[dict]:
    """
    Run the agent on every task in `split` (optionally capped at `limit`).

    Returns the list of result dicts. Also writes to `output_path` as JSONL
    if provided, skipping tasks whose IDs are already in the file.
    """
    skill_text = _load_skill(skill_path)
    all_tasks  = json.loads(tasks_path.read_text())

    tasks = [t for t in all_tasks if t["split"] == split]
    if limit:
        tasks = tasks[:limit]

    done_ids: set[str] = set()
    if output_path and output_path.exists():
        for line in output_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["task_id"])
        if done_ids and verbose:
            print(f"Resuming — {len(done_ids)} tasks already done, skipping.")

    pending = [t for t in tasks if t["id"] not in done_ids]
    if not pending:
        return []

    if verbose:
        print(f"Running {len(pending)} tasks ({workers} workers)…")

    results: list[dict] = []
    scores:  list[float] = []
    completed = 0
    write_lock = threading.Lock()

    def _run(task: dict) -> dict:
        return run_task(task, skill_text, model)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f"  Error on {task['id']}: {exc}", file=sys.stderr)
                continue

            with write_lock:
                completed += 1
                results.append(result)
                scores.append(result["score"])

                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("a") as f:
                        f.write(json.dumps(result) + "\n")

                if verbose:
                    mean = sum(scores) / len(scores)
                    cache_read = result["usage"]["cache_read_input_tokens"]
                    print(
                        f"[{completed:>3}/{len(pending)}] {result['task_id']} "
                        f"| {result['scenario']:<20} "
                        f"score={result['score']:.2f}  "
                        f"cov={result['coverage_score']:.2f}  "
                        f"struct={result['structure_score']:.2f}  "
                        f"mean={mean:.2f}  "
                        f"cache_read={cache_read:>5}  {result['elapsed_s']:.1f}s"
                    )

    return results


# ─── summary helpers (used by optimizer) ─────────────────────────────────────

def load_results(path: Path) -> list[dict]:
    """Load a JSONL results file into a list of result dicts."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarise(results: list[dict]) -> dict:
    """Aggregate stats over a completed rollout for the optimizer."""
    if not results:
        return {}

    scores           = [r["score"] for r in results]
    coverage_scores  = [r["coverage_score"] for r in results]
    structure_scores = [r["structure_score"] for r in results]
    total_steps      = sum(r["n_steps"] for r in results)
    total_covered    = sum(len(r["covered"]) for r in results)

    cat: dict[str, dict[str, int]] = {}
    for r in results:
        for c, v in r["by_category"].items():
            acc = cat.setdefault(c, {"covered": 0, "total": 0})
            acc["covered"] += v["covered"]
            acc["total"]   += v["total"]

    from collections import Counter
    missed_counts = Counter(key for r in results for key in r["missed"])

    return {
        "n_tasks":              len(results),
        "mean_score":           round(sum(scores) / len(scores), 4),
        "min_score":            round(min(scores), 4),
        "max_score":            round(max(scores), 4),
        "mean_coverage_score":  round(sum(coverage_scores) / len(coverage_scores), 4),
        "mean_structure_score": round(sum(structure_scores) / len(structure_scores), 4),
        "overall_coverage_rate": round(total_covered / total_steps, 4) if total_steps else 0.0,
        "by_category": {
            c: {
                "covered": v["covered"],
                "total":   v["total"],
                "rate":    round(v["covered"] / v["total"], 4),
            }
            for c, v in cat.items()
        },
        "top_missed_steps": missed_counts.most_common(10),
        "total_input_tokens":  sum(r["usage"]["input_tokens"]  for r in results),
        "total_output_tokens": sum(r["usage"]["output_tokens"] for r in results),
        "total_cache_reads":   sum(r["usage"]["cache_read_input_tokens"] for r in results),
        "total_cost_usd":      round(sum(r.get("cost_usd", 0.0) for r in results), 4),
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the video-to-skill agent on a task split."
    )
    p.add_argument("--split",  default="train",
                   choices=["train", "selection", "test"],
                   help="Which split to evaluate (default: train)")
    p.add_argument("--limit",  type=int, default=None,
                   help="Max tasks to process (default: all)")
    p.add_argument("--output", type=Path, default=None,
                   help="JSONL output path (default: data/video_<split>_results.jsonl)")
    p.add_argument("--model",  default=DEFAULT_MODEL,
                   help=f"Model to use (default: {DEFAULT_MODEL})")
    p.add_argument("--tasks",  type=Path, default=DATA_DIR / "video_tasks.json",
                   help="Path to video_tasks.json")
    p.add_argument("--skill",  type=Path, default=SKILL_PATH,
                   help="Path to video_skill.md")
    p.add_argument("--quiet",  action="store_true",
                   help="Suppress per-task output")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    output = args.output or DATA_DIR / f"video_{args.split}_results.jsonl"
    print(f"Split: {args.split}  |  Model: {args.model}  |  Output: {output}")
    print()

    results = run_rollout(
        split=args.split,
        limit=args.limit,
        output_path=output,
        model=args.model,
        tasks_path=args.tasks,
        skill_path=args.skill,
        verbose=not args.quiet,
    )

    if results:
        print()
        s = summarise(results)
        print(f"── Summary ─────────────────────────────────")
        print(f"  tasks:            {s['n_tasks']}")
        print(f"  mean score:       {s['mean_score']:.3f}")
        print(f"  mean coverage:    {s['mean_coverage_score']:.3f}")
        print(f"  mean structure:   {s['mean_structure_score']:.3f}")
        print(f"  coverage rate:    {s['overall_coverage_rate']:.3f}")
        print(f"  by category:")
        for cat, v in s["by_category"].items():
            bar = "█" * int(v["rate"] * 20)
            print(f"    {cat:<24} {v['covered']:>3}/{v['total']:<3}  {bar}")
        print(f"  top missed steps:")
        for step_key, count in s["top_missed_steps"][:5]:
            print(f"    {step_key:<32}  {count}x")
        print(f"  cache reads: {s['total_cache_reads']:,} tokens saved")


if __name__ == "__main__":
    main()
