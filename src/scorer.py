"""
Scores an agent's code review against the planted bugs in a task.

Algorithm:
  For each planted bug, check whether any of its keywords appear
  in the lowercased review text. No NLP required — just substring search.

  score = (bugs caught) / (total bugs)

Returns a ScoreResult with per-bug detail so the optimizer can see
exactly which bugs the agent missed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class BugResult:
    bug_id: str
    bug_key: str
    category: str
    caught: bool
    matched_keyword: str | None  # first keyword that triggered a hit


@dataclass
class ScoreResult:
    score: float                       # 0.0 – 1.0
    caught: list[BugResult] = field(default_factory=list)
    missed: list[BugResult] = field(default_factory=list)

    @property
    def n_bugs(self) -> int:
        return len(self.caught) + len(self.missed)

    @property
    def n_caught(self) -> int:
        return len(self.caught)

    def by_category(self) -> dict[str, dict]:
        """Return per-category catch rates for diagnostics."""
        cats: dict[str, dict[str, int]] = {}
        for r in self.caught + self.missed:
            c = cats.setdefault(r.category, {"caught": 0, "total": 0})
            c["total"] += 1
            if r.caught:
                c["caught"] += 1
        return {
            cat: {"caught": v["caught"], "total": v["total"],
                  "rate": v["caught"] / v["total"]}
            for cat, v in cats.items()
        }


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace for reliable substring search."""
    return re.sub(r"\s+", " ", text.lower())


def score_review(review: str, task: dict) -> ScoreResult:
    """
    Args:
        review: The agent's free-text code review (any format).
        task:   A task dict from tasks.json, containing a "bugs" list.

    Returns:
        ScoreResult with score, per-bug results, and category breakdown.
    """
    norm = _normalise(review)
    results: list[BugResult] = []

    for bug in task["bugs"]:
        matched: str | None = None
        for keyword in bug["keywords"]:
            if _normalise(keyword) in norm:
                matched = keyword
                break

        results.append(BugResult(
            bug_id=bug["id"],
            bug_key=bug["bug_key"],
            category=bug["category"],
            caught=matched is not None,
            matched_keyword=matched,
        ))

    caught = [r for r in results if r.caught]
    missed = [r for r in results if not r.caught]
    score = len(caught) / len(results) if results else 0.0

    return ScoreResult(score=score, caught=caught, missed=missed)


def score_batch(reviews: list[str], tasks: list[dict]) -> list[ScoreResult]:
    """Score a list of (review, task) pairs in order."""
    assert len(reviews) == len(tasks)
    return [score_review(r, t) for r, t in zip(reviews, tasks)]


def aggregate(results: list[ScoreResult]) -> dict:
    """Summarise a batch of ScoreResults for epoch-level reporting."""
    if not results:
        return {}
    scores = [r.score for r in results]
    total_bugs = sum(r.n_bugs for r in results)
    total_caught = sum(r.n_caught for r in results)

    # category breakdown across all tasks
    cat_totals: dict[str, dict[str, int]] = {}
    for result in results:
        for cat, data in result.by_category().items():
            acc = cat_totals.setdefault(cat, {"caught": 0, "total": 0})
            acc["caught"] += data["caught"]
            acc["total"]  += data["total"]

    return {
        "mean_score": sum(scores) / len(scores),
        "min_score":  min(scores),
        "max_score":  max(scores),
        "total_bugs":  total_bugs,
        "total_caught": total_caught,
        "overall_catch_rate": total_caught / total_bugs if total_bugs else 0.0,
        "by_category": {
            cat: {**v, "rate": v["caught"] / v["total"]}
            for cat, v in cat_totals.items()
        },
    }
