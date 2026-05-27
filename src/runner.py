"""
Rollout runner: calls the review agent on a batch of tasks and scores results.

Usage:
  python -m src.runner --split train --limit 10
  python -m src.runner --split selection
  python -m src.runner --split train --model claude-haiku-4-5-20251001 --output data/run_001.jsonl

The system prompt (skill.md) is sent with cache_control so the full-text is
only billed once per rollout; subsequent tasks reuse the cached prefix.

Output is JSONL — one result per line — so interrupted runs are resumable:
pass --output to an existing file and already-processed task IDs are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from src.scorer import score_review, aggregate

# ─── constants ────────────────────────────────────────────────────────────────

DEFAULT_MODEL  = "claude-haiku-4-5-20251001"
MAX_TOKENS     = 1024
DATA_DIR       = Path(__file__).parent.parent / "data"
SKILL_PATH     = Path(__file__).parent.parent / "skill.md"


# ─── prompt helpers ───────────────────────────────────────────────────────────

def _build_user_message(task: dict) -> str:
    return (
        f"PR Title: {task['pr_title']}\n"
        "\n"
        f"PR Description:\n{task['pr_description']}\n"
        "\n"
        "Diff:\n"
        "```diff\n"
        f"{task['diff']}\n"
        "```"
    )


def _load_skill(path: Path) -> str:
    return path.read_text()


# ─── single-task rollout ──────────────────────────────────────────────────────

def run_task(
    client: anthropic.Anthropic,
    task: dict,
    skill_text: str,
    model: str,
) -> dict:
    """Call the API for one task and return a scored result dict."""
    start = time.monotonic()

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": skill_text,
                # cache the skill — same for every task in a rollout
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": _build_user_message(task)},
        ],
    )

    elapsed = time.monotonic() - start
    review  = response.content[0].text

    result  = score_review(review, task)

    usage = response.usage
    return {
        "task_id":   task["id"],
        "scenario":  task["scenario"],
        "split":     task["split"],
        "n_bugs":    result.n_bugs,
        "score":     round(result.score, 4),
        "caught":    [r.bug_key for r in result.caught],
        "missed":    [r.bug_key for r in result.missed],
        "by_category": {
            cat: {"caught": v["caught"], "total": v["total"]}
            for cat, v in result.by_category().items()
        },
        "review":    review,
        "model":     model,
        "elapsed_s": round(elapsed, 2),
        "usage": {
            "input_tokens":              usage.input_tokens,
            "output_tokens":             usage.output_tokens,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens":     getattr(usage, "cache_read_input_tokens", 0),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── batch rollout ────────────────────────────────────────────────────────────

def run_rollout(
    split: str,
    limit: int | None = None,
    output_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    tasks_path: Path = DATA_DIR / "tasks.json",
    skill_path: Path = SKILL_PATH,
    verbose: bool = True,
) -> list[dict]:
    """
    Run the agent on every task in `split` (optionally capped at `limit`).

    Returns the list of result dicts. Also writes to `output_path` as JSONL
    if provided, skipping tasks whose IDs are already in the file.
    """
    client     = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    skill_text = _load_skill(skill_path)
    all_tasks  = json.loads(tasks_path.read_text())

    tasks = [t for t in all_tasks if t["split"] == split]
    if limit:
        tasks = tasks[:limit]

    # resume support: skip already-processed task IDs
    done_ids: set[str] = set()
    if output_path and output_path.exists():
        for line in output_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["task_id"])
        if done_ids and verbose:
            print(f"Resuming — {len(done_ids)} tasks already done, skipping.")

    pending = [t for t in tasks if t["id"] not in done_ids]

    results: list[dict] = []
    scores:  list[float] = []

    for i, task in enumerate(pending):
        try:
            result = run_task(client, task, skill_text, model)
        except anthropic.APIError as exc:
            print(f"  API error on {task['id']}: {exc}", file=sys.stderr)
            continue

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
                f"[{i+1:>3}/{len(pending)}] {task['id']} | {task['scenario']:<18} "
                f"score={result['score']:.2f}  mean={mean:.2f}  "
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

    scores = [r["score"] for r in results]
    total_bugs   = sum(r["n_bugs"] for r in results)
    total_caught = sum(len(r["caught"]) for r in results)

    # per-category catch rate
    cat: dict[str, dict[str, int]] = {}
    for r in results:
        for c, v in r["by_category"].items():
            acc = cat.setdefault(c, {"caught": 0, "total": 0})
            acc["caught"] += v["caught"]
            acc["total"]  += v["total"]

    # which bug_keys were most often missed
    from collections import Counter
    missed_counts = Counter(key for r in results for key in r["missed"])

    return {
        "n_tasks":    len(results),
        "mean_score": round(sum(scores) / len(scores), 4),
        "min_score":  round(min(scores), 4),
        "max_score":  round(max(scores), 4),
        "overall_catch_rate": round(total_caught / total_bugs, 4) if total_bugs else 0.0,
        "by_category": {
            c: {
                "caught": v["caught"],
                "total":  v["total"],
                "rate":   round(v["caught"] / v["total"], 4),
            }
            for c, v in cat.items()
        },
        "top_missed_bugs": missed_counts.most_common(10),
        "total_input_tokens":  sum(r["usage"]["input_tokens"]  for r in results),
        "total_output_tokens": sum(r["usage"]["output_tokens"] for r in results),
        "total_cache_reads":   sum(r["usage"]["cache_read_input_tokens"] for r in results),
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the code-review agent on a task split.")
    p.add_argument("--split",  default="train",
                   choices=["train", "selection", "test"],
                   help="Which split to evaluate (default: train)")
    p.add_argument("--limit",  type=int, default=None,
                   help="Max tasks to process (default: all)")
    p.add_argument("--output", type=Path, default=None,
                   help="JSONL output path (default: data/<split>_results.jsonl)")
    p.add_argument("--model",  default=DEFAULT_MODEL,
                   help=f"Model to use (default: {DEFAULT_MODEL})")
    p.add_argument("--tasks",  type=Path, default=DATA_DIR / "tasks.json",
                   help="Path to tasks.json")
    p.add_argument("--skill",  type=Path, default=SKILL_PATH,
                   help="Path to skill.md")
    p.add_argument("--quiet",  action="store_true",
                   help="Suppress per-task output")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    output = args.output or DATA_DIR / f"{args.split}_results.jsonl"
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
        print(f"  tasks:       {s['n_tasks']}")
        print(f"  mean score:  {s['mean_score']:.3f}")
        print(f"  catch rate:  {s['overall_catch_rate']:.3f}")
        print(f"  by category:")
        for cat, v in s["by_category"].items():
            bar = "█" * int(v["rate"] * 20)
            print(f"    {cat:<20} {v['caught']:>3}/{v['total']:<3}  {bar}")
        print(f"  top missed:")
        for bug_key, count in s["top_missed_bugs"][:5]:
            print(f"    {bug_key:<30}  {count}x")
        print(f"  cache reads: {s['total_cache_reads']:,} tokens saved")


if __name__ == "__main__":
    main()
