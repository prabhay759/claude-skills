"""
Optimizer: iterates epochs of (train rollout → propose edit → selection gate → slow update).

Each epoch:
  1. Train rollout  — Haiku reviews 80 train tasks with current skill
  2. Propose edit   — Sonnet analyzes failures, proposes ONE targeted skill patch
  3. Apply & gate   — Haiku reviews 20 selection tasks; commit only if score improves
  4. Slow update    — Sonnet writes cross-epoch strategy into the SLOW_UPDATE block

Usage:
  python -m src.optimizer --epochs 5
  python -m src.optimizer --epochs 1 --dry-run        # propose but don't commit
  python -m src.optimizer --epochs 3 --start-epoch 4  # resume from epoch 4
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic

from src.runner import run_rollout, summarise, load_results

# ─── config ───────────────────────────────────────────────────────────────────

OPTIMIZER_MODEL = "claude-sonnet-4-6"
ROLLOUT_MODEL   = "claude-haiku-4-5-20251001"
EPOCHS_DIR      = Path("data/epochs")
SKILL_PATH      = Path("skill.md")

SLOW_UPDATE_RE  = re.compile(
    r"(<!-- SLOW_UPDATE_START -->)(.*?)(<!-- SLOW_UPDATE_END -->)",
    re.DOTALL,
)

# ─── data types ───────────────────────────────────────────────────────────────

@dataclass
class EditProposal:
    epoch: int
    target_step: str
    rationale: str
    old_text: str
    new_text: str


@dataclass
class EpochResult:
    epoch: int
    train_mean: float
    selection_before: float
    selection_after: float
    delta: float
    accepted: bool
    proposal: dict | None   # EditProposal serialised as dict; None if none proposed


# ─── task cache (for example lookup) ─────────────────────────────────────────

_TASK_MAP: dict[str, dict] | None = None

def _task_map() -> dict[str, dict]:
    global _TASK_MAP
    if _TASK_MAP is None:
        tasks = json.loads(Path("data/tasks.json").read_text())
        _TASK_MAP = {t["id"]: t for t in tasks}
    return _TASK_MAP


# ─── failure analysis ─────────────────────────────────────────────────────────

def _bar(rate: float, width: int = 20) -> str:
    filled = int(rate * width)
    return "█" * filled + "░" * (width - filled)


def build_failure_analysis(
    summary: dict,
    results: list[dict],
    n_examples: int = 3,
) -> str:
    """
    Build a structured text block for the optimizer model to read.
    Includes: category catch rates, top missed bugs, and verbatim review
    excerpts where the agent failed — so the model sees what went wrong.
    """
    lines = [
        "Failure analysis",
        "─" * 52,
        (
            f"Mean score: {summary['mean_score']:.2f}  |  "
            f"Catch rate: {summary['overall_catch_rate']:.0%}  |  "
            f"Tasks: {summary['n_tasks']}"
        ),
        "",
        "By category (catch rate, ascending):",
    ]

    for cat, v in sorted(summary["by_category"].items(), key=lambda kv: kv[1]["rate"]):
        lines.append(
            f"  {cat:<20} {_bar(v['rate'])}  "
            f"{v['rate']:.0%}  ({v['caught']}/{v['total']})"
        )

    lines += ["", "Top missed bugs:"]
    for bug_key, count in summary["top_missed_bugs"][:8]:
        lines.append(f"  {bug_key:<32}  missed {count}×")

    # 2-3 examples for the most-missed bug_key
    if summary["top_missed_bugs"] and results:
        top_key = summary["top_missed_bugs"][0][0]
        examples = [r for r in results if top_key in r["missed"]][:n_examples]

        if examples:
            lines += ["", f"Example reviews that missed '{top_key}':"]
            tasks = _task_map()
            for r in examples:
                task = tasks.get(r["task_id"])
                if not task:
                    continue
                bug = next((b for b in task["bugs"] if b["bug_key"] == top_key), None)
                if not bug:
                    continue

                review_excerpt = r["review"][:500].strip()
                lines += [
                    "",
                    f"  [Task {r['task_id']}, scenario: {r['scenario']}]",
                    f"  Bug: {bug['description']}",
                    f"  Score keywords: {bug['keywords'][:4]}",
                    f"  Agent's review (truncated to 500 chars):",
                    *[f"    {line}" for line in review_excerpt.splitlines()],
                ]

    return "\n".join(lines)


# ─── propose edit ─────────────────────────────────────────────────────────────

_PROPOSE_SYSTEM = """\
You are optimizing a code review skill used by an AI agent to detect bugs in pull requests.
You will receive the current skill text and a failure analysis showing which bugs the agent \
consistently misses.

Your task: propose ONE targeted edit to the skill that closes the most common failure mode.

Rules:
- Edit Step 3 ("Inspect Each Changed Section") unless there is a compelling reason to edit elsewhere
- Use the propose_edit tool — old_text must appear VERBATIM in the skill (copy it exactly)
- new_text should add specific, actionable guidance — concrete patterns, not vague advice
- Prefer inserting 2-4 precise bullet examples over rewriting entire sections
- Do NOT modify the <!-- SLOW_UPDATE_START --> ... <!-- SLOW_UPDATE_END --> block
- Make exactly ONE focused change — no rewrites, no multi-section edits

Think step by step:
1. Which category has the lowest catch rate?
2. What specific pattern is the agent missing in reviews for that category?
3. What one concrete addition to Step 3 would teach it to check for that pattern?
"""

_PROPOSE_TOOL = {
    "name": "propose_edit",
    "description": "Propose a single targeted edit to the skill to improve bug detection.",
    "input_schema": {
        "type": "object",
        "properties": {
            "target_step": {
                "type": "string",
                "description": "Which step you are editing (e.g. 'Step 3')",
            },
            "rationale": {
                "type": "string",
                "description": "One sentence: why this edit will improve the top failure mode.",
            },
            "old_text": {
                "type": "string",
                "description": "The exact text to replace (must appear verbatim in the skill).",
            },
            "new_text": {
                "type": "string",
                "description": "The replacement text.",
            },
        },
        "required": ["target_step", "rationale", "old_text", "new_text"],
    },
}


def propose_edit(
    client: anthropic.Anthropic,
    skill_text: str,
    summary: dict,
    results: list[dict],
    epoch: int,
) -> EditProposal | None:
    """Ask Sonnet to propose a targeted patch. Returns None if the model declines."""
    analysis = build_failure_analysis(summary, results)
    user_msg = (
        f"Current skill:\n\n<skill>\n{skill_text}\n</skill>\n\n"
        f"{analysis}"
    )

    response = client.messages.create(
        model=OPTIMIZER_MODEL,
        max_tokens=2048,
        system=_PROPOSE_SYSTEM,
        tools=[_PROPOSE_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": user_msg}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "propose_edit":
            inp = block.input
            return EditProposal(
                epoch=epoch,
                target_step=inp["target_step"],
                rationale=inp["rationale"],
                old_text=inp["old_text"],
                new_text=inp["new_text"],
            )
    return None


# ─── apply edit ───────────────────────────────────────────────────────────────

def apply_edit(skill_text: str, proposal: EditProposal) -> str | None:
    """Return updated skill text, or None if old_text not found verbatim."""
    if proposal.old_text not in skill_text:
        return None
    return skill_text.replace(proposal.old_text, proposal.new_text, 1)


# ─── slow update ──────────────────────────────────────────────────────────────

_SLOW_UPDATE_SYSTEM = """\
You maintain the strategic guidance block of a code review skill.
This block accumulates cross-epoch lessons that persist across all future epochs.

Task: given summaries from all epochs so far, write 3–6 bullet points of strategic
insight that the agent should keep in mind during every review.

Rules:
- Each bullet must be specific and actionable, not generic
  BAD:  "Check for null values"
  GOOD: "After any db call that can return null (findById, findOne, get), verify the
         result before accessing any property — missing this is the #1 null_safety miss"
- Focus on patterns the agent TENDS TO MISS, not what it already catches well
- Build on the existing content rather than replacing it wholesale
- Return ONLY the bullet point lines — no headers, no block markers
"""


def slow_update(
    client: anthropic.Anthropic,
    skill_path: Path,
    epoch_summaries: list[dict],
) -> None:
    """Rewrite the SLOW_UPDATE block with cross-epoch strategic guidance."""
    skill_text = skill_path.read_text()
    match = SLOW_UPDATE_RE.search(skill_text)
    if not match:
        return

    current_content = match.group(2).strip()

    epoch_lines = []
    for i, s in enumerate(epoch_summaries, 1):
        top = [k for k, _ in s.get("top_missed_bugs", [])[:4]]
        cats = {
            c: f"{v['rate']:.0%}"
            for c, v in sorted(s.get("by_category", {}).items(), key=lambda kv: kv[1]["rate"])
        }
        epoch_lines.append(
            f"Epoch {i}: mean={s.get('mean_score', 0):.2f}  "
            f"catch={s.get('overall_catch_rate', 0):.0%}  "
            f"top_missed={top}  cats={cats}"
        )

    user_msg = (
        f"Current guidance block:\n{current_content or '(empty)'}\n\n"
        f"Epoch summaries:\n" + "\n".join(epoch_lines)
    )

    response = client.messages.create(
        model=OPTIMIZER_MODEL,
        max_tokens=512,
        system=_SLOW_UPDATE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    new_content = response.content[0].text.strip()
    replacement = (
        f"<!-- SLOW_UPDATE_START -->\n"
        f"{new_content}\n"
        f"<!-- SLOW_UPDATE_END -->"
    )
    skill_path.write_text(SLOW_UPDATE_RE.sub(replacement, skill_text))
    print(f"   Slow update written ({len(new_content)} chars).")


# ─── single epoch ─────────────────────────────────────────────────────────────

def run_epoch(
    client: anthropic.Anthropic,
    epoch: int,
    prev_selection_score: float,
    epoch_dir: Path,
    dry_run: bool = False,
) -> EpochResult:
    epoch_dir.mkdir(parents=True, exist_ok=True)
    skill_text = SKILL_PATH.read_text()

    # ── 1. train rollout ──────────────────────────────────────────────────────
    print(f"\n══ Epoch {epoch} / train rollout {'(dry-run) ' if dry_run else ''}{'═' * 30}")
    train_path = epoch_dir / "train_results.jsonl"
    run_rollout("train", output_path=train_path, model=ROLLOUT_MODEL)
    train_results = load_results(train_path)
    train_summary = summarise(train_results)

    print(
        f"\n   Train  mean={train_summary['mean_score']:.3f}  "
        f"catch={train_summary['overall_catch_rate']:.0%}  "
        f"tasks={train_summary['n_tasks']}"
    )
    for cat, v in sorted(train_summary["by_category"].items(), key=lambda kv: kv[1]["rate"]):
        print(f"     {cat:<20} {_bar(v['rate'], 15)}  {v['rate']:.0%}")

    # ── 2. propose edit ───────────────────────────────────────────────────────
    print(f"\n── Propose edit {'─' * 40}")
    proposal = propose_edit(client, skill_text, train_summary, train_results, epoch)

    if proposal is None:
        print("   Model declined to propose an edit.")
        (epoch_dir / "epoch_result.json").write_text(
            json.dumps(asdict(EpochResult(
                epoch=epoch, train_mean=train_summary["mean_score"],
                selection_before=prev_selection_score, selection_after=prev_selection_score,
                delta=0.0, accepted=False, proposal=None,
            )), indent=2)
        )
        return EpochResult(
            epoch=epoch, train_mean=train_summary["mean_score"],
            selection_before=prev_selection_score, selection_after=prev_selection_score,
            delta=0.0, accepted=False, proposal=None,
        )

    print(f"   Target:    {proposal.target_step}")
    print(f"   Rationale: {proposal.rationale}")
    print(f"   old_text ({len(proposal.old_text)} chars): {proposal.old_text[:80]!r}…")
    (epoch_dir / "proposed_edit.json").write_text(json.dumps(asdict(proposal), indent=2))
    (epoch_dir / "skill_before.md").write_text(skill_text)

    # apply the edit
    new_skill = apply_edit(skill_text, proposal)
    if new_skill is None:
        print("   APPLY FAILED: old_text not found verbatim in skill.md — skipping epoch.")
        result = EpochResult(
            epoch=epoch, train_mean=train_summary["mean_score"],
            selection_before=prev_selection_score, selection_after=prev_selection_score,
            delta=0.0, accepted=False, proposal=asdict(proposal),
        )
        (epoch_dir / "epoch_result.json").write_text(json.dumps(asdict(result), indent=2))
        return result

    SKILL_PATH.write_text(new_skill)
    (epoch_dir / "skill_after.md").write_text(new_skill)

    if dry_run:
        print("   Dry run — reverting skill.md.")
        SKILL_PATH.write_text(skill_text)
        result = EpochResult(
            epoch=epoch, train_mean=train_summary["mean_score"],
            selection_before=prev_selection_score, selection_after=prev_selection_score,
            delta=0.0, accepted=False, proposal=asdict(proposal),
        )
        (epoch_dir / "epoch_result.json").write_text(json.dumps(asdict(result), indent=2))
        return result

    # ── 3. selection gate ─────────────────────────────────────────────────────
    print(f"\n── Selection gate {'─' * 38}")
    sel_path = epoch_dir / "selection_results.jsonl"
    run_rollout("selection", output_path=sel_path, model=ROLLOUT_MODEL)
    sel_results  = load_results(sel_path)
    sel_summary  = summarise(sel_results)
    sel_score    = sel_summary["mean_score"]

    delta    = sel_score - prev_selection_score
    accepted = delta > 0.0

    print(
        f"\n   Selection  before={prev_selection_score:.3f}  "
        f"after={sel_score:.3f}  Δ={delta:+.3f}  "
        f"{'ACCEPTED ✓' if accepted else 'REJECTED ✗'}"
    )

    if not accepted:
        SKILL_PATH.write_text(skill_text)
        print("   Reverted skill.md to pre-epoch version.")

    result = EpochResult(
        epoch=epoch,
        train_mean=train_summary["mean_score"],
        selection_before=prev_selection_score,
        selection_after=sel_score,
        delta=delta,
        accepted=accepted,
        proposal=asdict(proposal),
    )
    (epoch_dir / "epoch_result.json").write_text(json.dumps(asdict(result), indent=2))
    return result


# ─── optimizer loop ───────────────────────────────────────────────────────────

def run_optimizer(
    n_epochs: int = 5,
    dry_run: bool = False,
    start_epoch: int = 1,
) -> None:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    EPOCHS_DIR.mkdir(parents=True, exist_ok=True)

    # ── baseline selection score ───────────────────────────────────────────────
    baseline_dir      = EPOCHS_DIR / "epoch_000"
    baseline_dir.mkdir(exist_ok=True)
    baseline_sel_path = baseline_dir / "selection_results.jsonl"

    if not baseline_sel_path.exists():
        print("── Baseline: selection rollout ───────────────────────────────────")
        run_rollout("selection", output_path=baseline_sel_path, model=ROLLOUT_MODEL)

    baseline_score = summarise(load_results(baseline_sel_path)).get("mean_score", 0.0)
    print(f"\nBaseline selection score: {baseline_score:.3f}")

    # ── if resuming, find the last accepted score ─────────────────────────────
    prev_score = baseline_score
    if start_epoch > 1:
        for e in range(start_epoch - 1, 0, -1):
            rp = EPOCHS_DIR / f"epoch_{e:03d}" / "epoch_result.json"
            if rp.exists():
                prev = json.loads(rp.read_text())
                if prev.get("accepted"):
                    prev_score = prev["selection_after"]
                    print(f"Resuming: last accepted selection score = {prev_score:.3f} (epoch {e})")
                    break

    # ── epoch loop ────────────────────────────────────────────────────────────
    epoch_summaries: list[dict] = []
    epoch_results:   list[EpochResult] = []

    for epoch in range(start_epoch, start_epoch + n_epochs):
        epoch_dir = EPOCHS_DIR / f"epoch_{epoch:03d}"

        result = run_epoch(client, epoch, prev_score, epoch_dir, dry_run=dry_run)
        epoch_results.append(result)

        if result.accepted:
            prev_score = result.selection_after

        # collect train summary for slow_update
        train_path = epoch_dir / "train_results.jsonl"
        if train_path.exists():
            epoch_summaries.append(summarise(load_results(train_path)))

        # slow update (always runs, regardless of gate outcome)
        if not dry_run and epoch_summaries:
            print(f"\n── Slow update {'─' * 42}")
            slow_update(client, SKILL_PATH, epoch_summaries)

    # ── final report ──────────────────────────────────────────────────────────
    print("\n══ Optimizer complete ════════════════════════════════════════════")
    for r in epoch_results:
        status = "✓ accepted" if r.accepted else "✗ rejected"
        print(
            f"  Epoch {r.epoch:>2}: train={r.train_mean:.3f}  "
            f"sel {r.selection_before:.3f}→{r.selection_after:.3f}  "
            f"Δ={r.delta:+.4f}  {status}"
        )
    print(f"\n  Final skill: {SKILL_PATH}")
    print(f"  Epoch logs:  {EPOCHS_DIR}/")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optimize skill.md via iterative rollout + edit.")
    p.add_argument("--epochs",      type=int, default=5,
                   help="Number of optimization epochs (default: 5)")
    p.add_argument("--start-epoch", type=int, default=1,
                   help="Resume from this epoch number (default: 1)")
    p.add_argument("--dry-run",     action="store_true",
                   help="Propose edits and log them but do not commit or run selection")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    run_optimizer(n_epochs=args.epochs, dry_run=args.dry_run, start_epoch=args.start_epoch)


if __name__ == "__main__":
    main()
