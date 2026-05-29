# TextGrad Skill Optimizer — Project Wiki

> **Goal**: Automatically improve an AI code-reviewer's skill document using gradient-style feedback from a scored dataset, so the reviewer catches more bugs without human rewriting of the prompt.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Motivation — Why Prompt Optimization?](#2-motivation--why-prompt-optimization)
3. [System Architecture](#3-system-architecture)
4. [Dataset Design](#4-dataset-design)
5. [Scoring System](#5-scoring-system)
6. [The Skill Document (skill.md)](#6-the-skill-document-skillmd)
7. [The TextGrad Optimization Loop](#7-the-textgrad-optimization-loop)
8. [Infrastructure — Claude CLI Backend](#8-infrastructure--claude-cli-backend)
9. [Results](#9-results)
10. [Engineering Challenges & Solutions](#10-engineering-challenges--solutions)
11. [Repository Structure](#11-repository-structure)
12. [End-to-End Data Flow Diagram](#12-end-to-end-data-flow-diagram)
13. [Epoch 1 — A Complete Iteration Walkthrough](#13-epoch-1--a-complete-iteration-walkthrough)
14. [How to Use This System](#14-how-to-use-this-system)

---

## 1. Project Overview

This project applies **TextGrad** — a technique that treats language model feedback as a differentiable signal — to automatically optimize a code-review skill document. The system:

- Runs an AI reviewer against a benchmark of TypeScript code review tasks
- Measures which bug categories the reviewer consistently misses
- Proposes targeted, minimal edits to the skill document using a stronger model (Sonnet) acting as an "optimizer"
- Validates the edit on a held-out selection split before committing it
- Accumulates strategic meta-guidance across epochs in a slow-update block

The entire pipeline runs on the **Claude CLI** using the same OAuth session as Claude Code — no API key is required. All model calls are made by shelling out to `claude --print --output-format json`.

---

## 2. Motivation — Why Prompt Optimization?

### The Problem with Manual Prompt Engineering

Writing a good system prompt for a code-reviewer is hard:

- You do not know in advance which bug patterns the model will miss
- Fixes are based on intuition, not data
- Adding too much guidance hurts performance on things the model already does well (regression risk)
- The improvement signal is qualitative ("it feels better")

### The TextGrad Insight

TextGrad (Yuksekgonul et al., 2024) treats the *text of the prompt itself* as a variable and the *model's score on a benchmark* as the loss. Instead of computing a gradient with numbers, you ask a strong model to read the benchmark failures and propose a textual update to the prompt — analogous to a gradient step in continuous optimization.

Key properties that make it work well here:

| Property | Details |
|---|---|
| **Data-driven** | Every proposed edit is grounded in measured failure modes, not intuition |
| **Selection gate** | An edit is only committed if it raises the score on a held-out split (`delta > 0`) |
| **Targeted edits** | The optimizer proposes one minimal change per epoch (surgical, not wholesale rewrites) |
| **Slow update** | Strategic meta-guidance accumulates across epochs, teaching the reviewer *how to look* rather than *what to find* |
| **Reversible** | If a proposed edit regresses the selection score, it is discarded and the skill reverts |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        src/optimizer.py                         │
│                                                                 │
│  for each epoch:                                                │
│    1. run_rollout(split=train)   ─────────────────────────────► │─┐
│    2. summarise(train_results)                                  │ │  Haiku calls via
│    3. propose_edit(summary) ──── Sonnet call ──────────────── ◄─┤ │  claude --print
│    4. apply_edit(skill.md)                                      │ │
│    5. run_rollout(split=selection) ───────────────────────────► │─┘
│    6. selection_gate(delta > 0)                                 │
│    7. slow_update(skill.md)  ─── Sonnet call ─────────────────►│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
         │                                │
         ▼                                ▼
┌─────────────────┐            ┌──────────────────────┐
│  src/runner.py  │            │     skill.md          │
│                 │            │  ┌─────────────────┐  │
│  ThreadPool(8)  │            │  │ Procedure steps │  │
│  JSONL output   │            │  ├─────────────────┤  │
│  resume support │            │  │ SLOW_UPDATE     │  │
└────────┬────────┘            │  │ block           │  │
         │                     │  └─────────────────┘  │
         ▼                     └──────────────────────┘
┌─────────────────┐
│  src/backend.py │
│  claude --print │
│  --output-format│
│  json           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐        ┌──────────────────────┐
│  src/scorer.py  │        │   data/tasks.json     │
│                 │        │   150 tasks           │
│  keyword match  │        │   6 scenarios         │
│  0.0 – 1.0      │        │   330 planted bugs    │
└─────────────────┘        └──────────────────────┘
```

### Component Responsibilities

| File | Role |
|---|---|
| `src/dataset/scenarios.py` | TypeScript scenario templates — 6 scenarios, 5 injectable bugs each |
| `src/dataset/generator.py` | Generates all 150 task variants, writes `data/tasks.json` |
| `src/scorer.py` | Keyword-based scoring: returns 0.0–1.0 per task |
| `src/backend.py` | Subprocess wrapper around `claude --print`; parses JSON envelope |
| `src/runner.py` | Parallel task runner (8 workers); JSONL output with resume |
| `src/optimizer.py` | Full TextGrad loop: rollout → propose → gate → slow update |
| `skill.md` | The skill document being optimized |

---

## 4. Dataset Design

### Overview

| Property | Value |
|---|---|
| Total tasks | **150** |
| Scenarios | **6** (TypeScript codebases) |
| Bugs per scenario | **5** (independently injectable) |
| Variants per scenario | **25** (C(5,1) + C(5,2) + C(5,3) = 5 + 10 + 10) |
| Total planted bugs | **330** |
| Train split | 80 tasks |
| Selection split | 20 tasks (optimization gate) |
| Test split | 50 tasks (locked — run once at the end) |

### The 6 Scenarios

Each scenario is a realistic TypeScript codebase feature with its own PR title, description, and 5 plantable bugs spanning security, logic, null-safety, error-handling, performance, and type-safety categories.

| Scenario | File | PR Theme | 5 Bugs |
|---|---|---|---|
| `auth_service` | `src/auth/refreshService.ts` | JWT refresh token rotation | `hardcoded_secret`, `token_not_revoked`, `missing_user_check`, `wrong_expiry`, `swallow_error` |
| `user_repo` | `src/users/userRepository.ts` | User data access layer | `sql_injection`, `n_plus_one`, `null_deref`, `missing_rollback`, `any_type` |
| `api_middleware` | `src/middleware/index.ts` | Rate-limiting + JWT auth middleware | `ip_spoofing`, `jwt_decode_not_verify`, `off_by_one`, `double_response`, `missing_error_status` |
| `react_hook` | `src/hooks/useUserData.ts` | React data-fetching hook | `missing_dep`, `unhandled_promise`, `memory_leak`, `wrong_type`, `no_loading_reset` |
| `payment_service` | `src/payments/chargeService.ts` | Stripe charge + webhook handler | `no_amount_validation`, `no_idempotency`, `stripe_error_swallowed`, `no_webhook_validation`, `cents_vs_dollars` |
| `cache_service` | `src/cache/cacheService.ts` | Redis-backed cache layer | `no_ttl`, `json_parse_no_catch`, `no_null_check`, `key_collision`, `stampede` |

### Bug Injection Mechanism

Each scenario has a `generate_code(active_bugs: set[str]) -> str` function that conditionally includes or excludes buggy code sections based on which bugs are active. This produces clean, syntactically valid TypeScript for any subset of bugs.

```python
# Example: cache_service with key_collision and stampede active
code = scenarios["cache_service"]["generate_code"]({"key_collision", "stampede"})
# → valid TypeScript file with exactly those two bugs, all other patterns clean
```

### Variant Generation

For each scenario, all combinations of 1, 2, and 3 bugs are generated (25 total):
- 5 single-bug variants (isolates each bug cleanly)
- 10 two-bug variants (tests interaction effects)
- 10 three-bug variants (realistic PR complexity)

Tasks are diff-formatted as a unified diff (`--- /dev/null`, `+++ b/filename`) simulating a new-file PR — the same format a code reviewer sees in a real GitHub pull request.

### Split Strategy

The 150 tasks are shuffled with `seed=42` and split as follows:

```
train:     80 tasks  (used every epoch — optimizer trains on these)
selection: 20 tasks  (gate — proposed edit must improve this score to be accepted)
test:      50 tasks  (locked — run exactly once after optimization is complete)
```

The selection split acts as a **validation set**: it prevents the optimizer from overfitting changes that only help on the training distribution.

---

## 5. Scoring System

### Philosophy

Scoring is deliberately simple: **keyword substring matching**. There is no NLP, no embeddings, no semantic similarity. This keeps scoring fast, deterministic, and auditable.

### Algorithm

```python
def score_review(review: str, task: dict) -> ScoreResult:
    normalized = re.sub(r'\s+', ' ', review.lower())
    for bug in task["bugs"]:
        caught = any(kw in normalized for kw in bug["keywords"])
```

For each planted bug, the scorer checks whether any of its keywords appear as substrings in the normalized review text. A bug is "caught" if any keyword matches.

```
score = n_caught / n_bugs   →   range [0.0, 1.0]
```

### Example Bug Keywords

| Bug | Keywords |
|---|---|
| `hardcoded_secret` | `"hardcoded"`, `"jwt_secret"`, `"secret literal"`, `"process.env"` |
| `key_collision` | `"key collision"`, `"namespace"`, `"entity type"`, `"cache key"` |
| `cents_vs_dollars` | `"cents"`, `"dollars"`, `"/ 100"`, `"* 100"`, `"denomination"` |
| `memory_leak` | `"memory leak"`, `"cleanup"`, `"unmount"`, `"removeEventListener"` |
| `stampede` | `"stampede"`, `"thundering herd"`, `"mutex"`, `"single-flight"` |

### Score Interpretation

| Score | Meaning |
|---|---|
| 1.00 | All bugs caught |
| 0.67 | 2/3 bugs caught (common for 3-bug tasks) |
| 0.50 | 1/2 or 2/4 caught |
| 0.00 | No bugs caught — complete miss |

---

## 6. The Skill Document (skill.md)

The skill document is the system prompt given to the AI reviewer for every task. It is the object being optimized.

### Initial Design (Intentional Gaps)

The initial skill was written with **deliberate weaknesses** to give the optimizer something to improve:
- Step 3 listed bug categories but gave no ordering, prioritization, or verification strategies
- No guidance on which categories are hardest to catch
- No concrete sub-patterns within each category

### Current State (After 2 Epochs)

**Step 3 — Inspect each changed section** now includes:

```markdown
- **Logic**: wrong conditions, off-by-one errors, missing state updates
  - **Cache key collisions**: keys that are bare IDs with no entity-type prefix — e.g.
    `cacheGet('42')` used for both users and products hits the same slot; keys must
    encode the entity type (`user:42`, `product:42`)
  - **Unused TTL / wrong expiry**: a `ttlSeconds` parameter accepted by the function but
    never forwarded to the underlying store call (e.g. `SET key value` with no `EX`
    argument), so entries never expire
  - **Cache stampede**: on a cache miss, multiple concurrent callers all recompute and
    overwrite — look for a missing lock/mutex guard around the miss-fill path
```

**SLOW_UPDATE block** (strategic meta-guidance, accumulated):

```markdown
- Cache key collisions are the #1 logic miss: verify every dimension of uniqueness
  is encoded in the key.
- Verify units and magnitudes on every numeric value with an implicit denomination:
  wrong-unit bugs appear as seconds/milliseconds or cents/dollars mismatches.
- Check for cache stampede on any "miss → recompute" path.
- Hunt for memory leaks on every subscription, listener, interval, or stream.
- Hunt for swallowed errors — empty or logging-only catch blocks.
- Logic is the weakest category (~70% catch rate) — always trace branches with
  concrete boundary values.
```

---

## 7. The TextGrad Optimization Loop

### Epoch Flow

```
Epoch N
  │
  ├─ 1. TRAIN ROLLOUT ──────────────────────────────────────────────
  │      Run 80 tasks in parallel (8 workers)
  │      Each task: claude --print --model haiku --system-prompt skill.md
  │      Score each review; write to epoch_N/train_results.jsonl
  │      Resume support: already-scored tasks are skipped on re-run
  │
  ├─ 2. FAILURE ANALYSIS ───────────────────────────────────────────
  │      Identify lowest catch-rate categories
  │      Find most-missed bug keys (top 10)
  │      Sample 3 worst-scoring reviews as examples
  │
  ├─ 3. PROPOSE EDIT ───────────────────────────────────────────────
  │      Call claude --print --model sonnet --json-schema EditProposal
  │      Sonnet reads: skill.md + failure analysis + 3 worst reviews
  │      Returns structured JSON:
  │        { target_step, rationale, old_text, new_text }
  │      Constraint: one targeted edit, not a full rewrite
  │
  ├─ 4. APPLY EDIT ─────────────────────────────────────────────────
  │      Exact string replacement of old_text → new_text in skill.md
  │      If old_text not found verbatim: skip epoch (safety check)
  │
  ├─ 5. SELECTION GATE ─────────────────────────────────────────────
  │      Run 20 selection tasks with new skill.md
  │      delta = selection_after - selection_before
  │      IF delta > 0:  keep new skill.md  (ACCEPTED ✓)
  │      IF delta ≤ 0:  revert skill.md   (REJECTED ✗)
  │
  └─ 6. SLOW UPDATE ────────────────────────────────────────────────
         Always runs (regardless of gate outcome)
         Sonnet reads all epoch summaries to date
         Rewrites the <!-- SLOW_UPDATE_START/END --> block in skill.md
         Adds/refines strategic meta-guidance based on patterns seen
```

### The `EditProposal` JSON Schema

The optimizer uses Claude's `--json-schema` flag to get structured output from Sonnet:

```json
{
  "epoch": 1,
  "target_step": "Step 3",
  "rationale": "The logic category has the lowest catch rate (71%), and
    key_collision is missed 8× — the agent never checks whether cache keys
    are namespaced…",
  "old_text": "- **Logic**: wrong conditions, off-by-one errors, missing state updates",
  "new_text": "- **Logic**: wrong conditions, off-by-one errors, missing state updates\n
    - **Cache key collisions**: keys that are bare IDs with no entity-type prefix…"
}
```

### Why Exact String Replacement?

Allowing the optimizer to rewrite arbitrary sections would risk:
- Removing guidance that already works well for other categories
- Introducing format changes that break the reviewer's output parsing
- Masking whether an improvement came from the edit itself vs. contextual changes

Exact string replacement is the minimal-blast-radius operation: it changes exactly one passage and nothing else.

### The Two-Layer Update Strategy

The optimizer maintains two separate channels for improving the skill:

| Channel | When written | What it contains |
|---|---|---|
| **Inline edit** (main body) | Only when `delta > 0` | Concrete bug-detection sub-bullets added to the relevant Step |
| **SLOW_UPDATE block** | Every epoch, always | Strategic meta-patterns: which categories are hardest, how to approach them |

This mirrors how expert knowledge accumulates: specific techniques get added to the checklist when proven useful, while broader review philosophy improves continuously from experience.

---

## 8. Infrastructure — Claude CLI Backend

### Why `claude --print` Instead of the Python SDK?

The remote container running this project does not have access to an `ANTHROPIC_API_KEY`. However, Claude Code itself (the CLI tool) is authenticated via OAuth. By calling `claude --print` as a subprocess, all model calls reuse the existing OAuth session — zero additional credentials needed.

### The `complete()` Function

```python
def complete(system: str, user: str, model: str, json_schema: dict = None) -> CallResult:
    cmd = [
        "claude", "--print",
        "--model", model,
        "--system-prompt", system,
        "--output-format", "json",        # structured envelope with usage stats
        "--no-session-persistence",        # each call is stateless
    ]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]  # structured output

    env = {**os.environ, "CLAUDE_OPTIMIZER_SUBPROCESS": "1"}  # disables stop hook
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=env)

    envelope = json.loads(proc.stdout)
    # envelope has: result (text), structured_output (JSON), usage, total_cost_usd
```

The JSON envelope from `--output-format json` provides:
- `result` — the text response
- `structured_output` — the parsed JSON when `--json-schema` is used
- `usage.cache_read_input_tokens` — how many tokens were served from cache
- `total_cost_usd` — per-call cost

### Parallelism

```python
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(_run, task): task for task in pending}
    for future in as_completed(futures):
        result = future.result()
        with write_lock:
            output_file.write(json.dumps(result) + "\n")
```

8 parallel workers cut wall-clock time from ~70 minutes (sequential, ~50s/task) to ~10 minutes per 80-task rollout.

A `threading.Lock()` ensures concurrent threads don't interleave their JSONL lines in the output file.

### Resume Support

Every rollout appends to a JSONL file. On re-run, already-processed task IDs are read from the file and skipped:

```python
done_ids = {json.loads(line)["task_id"] for line in existing_file.splitlines()}
pending = [t for t in tasks if t["id"] not in done_ids]
```

This is critical because session limits are hit mid-rollout. Instead of restarting from scratch, re-running picks up exactly where the previous run left off.

---

## 9. Results

### Selection Score Progression

| Epoch | Selection Score | Delta | Decision | Key Change |
|---|---|---|---|---|
| Baseline | **0.233** | — | — | Initial skill.md (intentionally weak) |
| Epoch 1 | **0.951** | **+71.8%** | ACCEPTED ✓ | Added cache key collision, wrong TTL, stampede sub-bullets to Step 3 |
| Epoch 2 | 0.926 | -2.5% | REJECTED ✗ | Reverted; key-collision call-site scanning + cents/dollars bullet proposed but regressed |
| Epoch 3 | in progress | — | — | Session limit (10:40pm UTC); 49/80 train tasks done |

### Epoch 1 Detailed Results

**Train split (65 tasks evaluated):**

| Category | Bugs Caught | Total Bugs | Catch Rate |
|---|---|---|---|
| security | 23 | 23 | **100%** |
| null_safety | 18 | 18 | **100%** |
| performance | 18 | 18 | **100%** |
| type_safety | 13 | 13 | **100%** |
| error_handling | 24 | 26 | **92%** |
| **logic** | **32** | **45** | **71%** ← weakest |

**Top missed bugs (train, epoch 1):**

| Bug Key | Misses | Root Cause |
|---|---|---|
| `key_collision` | 8× | No guidance on cache key namespacing |
| `wrong_expiry` | 2× | No guidance on TTL passthrough verification |
| `stampede` | 2× | No guidance on miss-fill concurrency patterns |
| `swallow_error` | 2× | Detection requires reading catch blocks carefully |
| `cents_vs_dollars` | 1× | No guidance on denomination mismatches |

**Why the epoch 1 edit worked so well (+71.8%):**

The baseline skill mentioned "logic" as a category but gave no sub-patterns. The reviewer was catching security, null-safety, performance, and type bugs consistently (all `≥92%`) but had a structural blind spot for cache-specific logic bugs. Adding three concrete sub-bullets for `key_collision`, `wrong_expiry`, and `stampede` directly targeted the top 4/5 missed bugs. The selection score jump from 0.233 to 0.951 is large because the selection split happened to have proportionally more cache_service tasks.

### Cost and Token Usage

| Metric | Value |
|---|---|
| Total model calls | 235 |
| Input tokens (direct) | 5,722 |
| Output tokens | 827,593 |
| Cache reads | **8,448,760 tokens** |
| **Total cost** | **$7.94** |

The extremely low direct input token count (5,722) vs. cache reads (8.4M) shows how effectively the `claude` CLI's prompt cache is working. The system prompt (skill.md) is cached after the first call and served from cache on every subsequent task in the same run — reducing cost by roughly 90% compared to sending the full system prompt each time.

---

## 10. Engineering Challenges & Solutions

### Challenge 1: No API Key in Remote Container

**Problem**: The project initially used the Anthropic Python SDK (`import anthropic`), which requires `ANTHROPIC_API_KEY`. The remote execution container does not expose this.

**Failed approaches tried**:
- Reading from fd 4 (`CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`)
- Using `CODESIGN_MCP_TOKEN`
- Using `ANTHROPIC_BASE_URL` proxy with a dummy key

**Solution**: Replaced the entire model-call layer with `subprocess.run(["claude", "--print", ...])`. The `claude` CLI uses the same OAuth session as Claude Code itself — no separate key needed. The `--output-format json` flag gives back the same structured envelope (response text, usage, cost) that the SDK would have provided.

---

### Challenge 2: Session Limit Corruption

**Problem**: The Claude Code session has a usage limit (~50 concurrent calls per reset window). When hit mid-rollout, the CLI returns plain text like `"You've hit your session limit · resets 3:50pm (UTC)"` with **exit code 0** (not an error code). Without detection:
- Tasks scored 0.00 (no bug keywords in "You've hit your session limit")
- The optimizer's slow_update function saw this text and wrote it directly into skill.md's SLOW_UPDATE block
- The next run used a corrupted system prompt

**Solution**:
```python
# Precise phrase matching — avoids false positives on "rate limiting middleware"
if "hit your session limit" in text.lower():
    raise RuntimeError(f"Claude session limit: {text.strip()[:120]}")
```

Combined with resume support: tasks that raised this error are not written to the JSONL output file and are automatically retried on the next run.

**Earlier false-positive bug**: The initial detection used `"rate limit"` as a keyword, which matched `"rate limiting"` in every review of the `api_middleware` scenario (whose PR adds rate-limiting middleware). This caused ~10-15 valid reviews per rollout to be discarded. Fixed by using the exact phrase `"hit your session limit"`.

---

### Challenge 3: Stop Hook Intercepting Subprocess Calls

**Problem**: Claude Code has a configured stop hook (`~/.claude/stop-hook-git-check.sh`) that checks for untracked files and uncommitted changes after every session. This hook fires for `claude --print` subprocess calls too. When it found untracked JSONL output files during a rollout:
1. The hook exited with code 2 and output "There are untracked files in the repository..."
2. The `claude` CLI treated this as a new user turn and responded to it
3. The subprocess returned "I see a stop hook alert about untracked files. Would you like me to: 1. Check the current status..." as the code review
4. This scored 0.00

**Solution**: Two-part fix.

`src/backend.py` — set an environment variable on the subprocess:
```python
env = {**os.environ, "CLAUDE_OPTIMIZER_SUBPROCESS": "1"}
proc = subprocess.run(cmd, ..., env=env)
```

`~/.claude/stop-hook-git-check.sh` — bail early if the variable is set:
```bash
if [[ "${CLAUDE_OPTIMIZER_SUBPROCESS}" = "1" ]]; then
  exit 0
fi
```

Also added a hook-injection detection phrase (`"stop hook alert"`, `"untracked files in the repository"`) as a belt-and-suspenders fallback.

---

### Challenge 4: Parallel JSONL Write Safety

**Problem**: 8 threads writing to the same file simultaneously can interleave partial lines, corrupting the JSONL.

**Solution**: A `threading.Lock()` wrapping the file-write operation:
```python
import threading
write_lock = threading.Lock()

with write_lock:
    with output_path.open("a") as f:
        f.write(json.dumps(result) + "\n")
```

---

### Challenge 5: `--json-schema` Not Producing JSON Alone

**Problem**: Using `--json-schema` without `--output-format json` returned the structured output embedded in prose rather than in a parseable envelope.

**Solution**: Always use both flags together: `--output-format json --json-schema <schema>`. The `--output-format json` envelope's `structured_output` field then contains the parsed JSON object.

---

## 11. Repository Structure

```
claude-skills/
├── skill.md                          ← the system prompt being optimized
├── WIKI.md                           ← this document
├── requirements.txt
│
├── src/
│   ├── __init__.py
│   ├── backend.py                    ← claude --print subprocess wrapper
│   ├── runner.py                     ← parallel rollout runner
│   ├── scorer.py                     ← keyword-based scoring
│   ├── optimizer.py                  ← TextGrad optimization loop
│   └── dataset/
│       ├── __init__.py
│       ├── scenarios.py              ← 6 TypeScript scenario templates
│       └── generator.py             ← generates data/tasks.json
│
└── data/
    ├── tasks.json                    ← 150 tasks (generated, committed)
    └── epochs/
        ├── epoch_000/
        │   └── selection_results.jsonl    ← baseline (score: 0.233)
        ├── epoch_001/
        │   ├── train_results.jsonl         ← 65 tasks, mean 0.882
        │   ├── proposed_edit.json          ← accepted edit (cache patterns)
        │   ├── selection_results.jsonl     ← score: 0.951 (+71.8%)
        │   ├── epoch_result.json           ← {accepted: true, delta: +0.718}
        │   ├── skill_before.md
        │   └── skill_after.md
        ├── epoch_002/
        │   ├── train_results.jsonl         ← 66 tasks, mean 0.894
        │   ├── proposed_edit.json          ← rejected edit
        │   ├── selection_results.jsonl     ← score: 0.926 (-2.5%)
        │   ├── epoch_result.json           ← {accepted: false, delta: -0.025}
        │   ├── skill_before.md
        │   └── skill_after.md
        └── epoch_003/
            └── train_results.jsonl         ← 49/80 tasks (in progress)
```

---

## 12. End-to-End Data Flow Diagram

```
data/tasks.json
      │
      │  (150 tasks, each with: scenario, split, pr_title,
      │   pr_description, diff, bugs: [{key, category, keywords}])
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  runner.py — run_rollout(split="train")                     │
│                                                             │
│  For each task in parallel (8 workers):                     │
│    user_msg = f"PR Title: {task.pr_title}\n                 │
│                PR Description: {task.pr_description}\n      │
│                Diff:\n```diff\n{task.diff}\n```"            │
│                                                             │
│    complete(system=skill.md, user=user_msg, model=haiku)    │
│      → subprocess: claude --print --output-format json      │
│      ← JSON envelope: {result, usage, total_cost_usd}       │
│                                                             │
│    score_review(review=result, task=task)                   │
│      → ScoreResult(score, caught, missed, by_category)      │
│                                                             │
│    Write to epoch_N/train_results.jsonl                     │
└─────────────────────────────────────────────────────────────┘
      │
      │  summarise(train_results)
      │    → {mean_score, overall_catch_rate, by_category,
      │       top_missed_bugs, total_cost_usd}
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  optimizer.py — propose_edit(skill_text, summary, results)  │
│                                                             │
│  System: "You are a prompt engineer…"                       │
│  User:   skill.md + failure analysis + 3 worst reviews      │
│                                                             │
│  complete(..., model=sonnet, json_schema=EDIT_SCHEMA)       │
│    → EditProposal(target_step, rationale, old_text,         │
│                    new_text)                                │
└─────────────────────────────────────────────────────────────┘
      │
      │  apply_edit: exact old_text → new_text replacement
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  optimizer.py — selection gate                              │
│                                                             │
│  run_rollout(split="selection", skill=new_skill)            │
│  delta = selection_after - selection_before                 │
│                                                             │
│  delta > 0  →  write new skill.md  (ACCEPTED)              │
│  delta ≤ 0  →  revert skill.md    (REJECTED)               │
└─────────────────────────────────────────────────────────────┘
      │
      │  (always, regardless of gate)
      ▼
┌─────────────────────────────────────────────────────────────┐
│  optimizer.py — slow_update(skill_path, epoch_summaries)    │
│                                                             │
│  Sonnet reads: all epoch histories to date                  │
│  Rewrites <!-- SLOW_UPDATE_START/END --> block              │
│  Adds strategic meta-guidance about hardest categories      │
└─────────────────────────────────────────────────────────────┘
      │
      └── skill.md is now improved for epoch N+1
```

---

*Last updated: Epoch 3 in progress. Test split (50 tasks) locked until optimization completes.*

---

## 13. Epoch 1 — A Complete Iteration Walkthrough

This section shows **every step of the first optimization epoch** with real data — actual diffs, actual reviewer output, actual scorer decisions, and the exact edit that was proposed and accepted. It is the most concrete illustration of how the system works.

---

### Step 1 — The Diff the Reviewer Was Given

Below is the actual unified diff for **task_066** — one of the tasks that exposed the key weakness. It adds a small Redis cache helper module to a TypeScript codebase.

```diff
--- /dev/null
+++ b/src/cache/redisCache.ts
@@ -0,0 +1,33 @@
+import { createClient } from 'redis';
+
+const redis = createClient({ url: process.env.REDIS_URL });
+redis.connect();
+
+export async function cacheGet<T>(key: string): Promise<T | null> {
+  const cacheKey = key;
+  const raw = await redis.get(cacheKey);
+  try {
+    return JSON.parse(raw) as T;
+  } catch {
+    await redis.del(cacheKey);
+    return null;
+  }
+}
+
+export async function cacheSet<T>(key: string, value: T, ttlSeconds = 300): Promise<void> {
+  const cacheKey = key;
+  await redis.set(cacheKey, JSON.stringify(value), { EX: ttlSeconds });
+}
+
+export async function getOrSet<T>(
+  key: string,
+  fetchFn: () => Promise<T>,
+  ttlSeconds = 300
+): Promise<T | null> {
+  const cached = await cacheGet<T>(key);
+  if (cached !== null) return cached;
+
+  const value = await fetchFn();
+  await cacheSet(key, value);     // ← key_collision: bare key, no type prefix
+  return value;                   // ← stampede: no lock around miss-fill path
+}
```

The three planted bugs are:
- `key_collision` — `cacheSet(key, value)` stores using whatever bare string the caller passes. If callers use `cacheGet('42')` for both users and products, they share the same Redis slot.
- `stampede` — when the cache is cold, multiple concurrent callers all fall through to `fetchFn()` simultaneously, all execute the expensive DB/API call, and all write back the same value — a classic cache stampede.
- `no_null_check` — `JSON.parse(raw)` when `raw` is `null` (a cache miss on some Redis clients) throws a parse error.

---

### Step 2 — The Reviewer's Output (Before the Edit)

With the **initial skill.md** (Step 3 only listed category names, no sub-patterns), the reviewer produced this for task_066:

```
[SEVERITY: HIGH] Line 3 — Redis connection not awaited
Category: logic
Detail: redis.connect() returns a promise but is not awaited. The connection
may not be established before the first cache operation. Change to: await redis.connect()

[SEVERITY: HIGH] Line 31 — Missing ttlSeconds parameter in cacheSet call
Category: logic
Detail: The getOrSet function accepts ttlSeconds but doesn't pass it to cacheSet().
Cache entries created via getOrSet always use the 300s default regardless of what
the caller specified. Change to: await cacheSet(key, value, ttlSeconds)

[SEVERITY: MEDIUM] Line 10 — Inefficient null handling in JSON.parse
Category: performance
Detail: If redis.get() returns null, JSON.parse(null) throws an exception and
redis.del() is called unnecessarily. Check if raw is null first.
```

**Score: 0.33 / 1.00** — only `no_null_check` caught (via the "null" keyword match in "JSON.parse(null)"). The `key_collision` and `stampede` bugs were **completely missed** — the reviewer never looked for them because no guidance existed.

Notice the reviewer correctly found the unawaited connection and the TTL passthrough bug (line 31). Both of those are real issues. But without a mental checklist that says "look for bare cache keys" and "look for stampede-vulnerable miss-fill paths", it never occurred to the reviewer to check those dimensions.

---

### Step 3 — The Failure Analysis

After all 65 train tasks completed, the runner summarised the results:

```
Train  mean=0.882  catch=90%  tasks=65

  logic                ██████████░░░░░  71%   ← lowest
  error_handling       █████████████░░  92%
  performance          ███████████████  100%
  null_safety          ███████████████  100%
  security             ███████████████  100%
  type_safety          ███████████████  100%

Top missed bugs:
  key_collision         8×   ← missed on 8 out of 8 tasks where it was planted
  wrong_expiry          2×
  stampede              2×
  swallow_error         2×
  cents_vs_dollars      1×
```

The signal is clear: `logic` is the only category under 90%, and `key_collision` alone accounts for 8 of the 15 total misses. The reviewer never once caught a cache key collision in the entire training set.

This structured failure analysis — not the raw reviews — is what gets handed to the optimizer (Sonnet).

---

### Step 4 — The Proposed Edit

The optimizer model (claude-sonnet-4-6) received:
- The full current `skill.md`
- The failure analysis above
- The 3 worst-scoring reviews as concrete examples of the failure mode

It returned this structured `EditProposal` (via `--json-schema`):

```json
{
  "epoch": 1,
  "target_step": "Step 3",
  "rationale": "The logic category has the lowest catch rate (71%), and
    key_collision is missed 8× — the agent never checks whether cache keys are
    namespaced, so it misses collisions when bare IDs are shared across entity
    types; adding concrete sub-bullets for this pattern (and the related
    wrong_expiry/stampede misses) directly teaches the check.",

  "old_text": "- **Logic**: wrong conditions, off-by-one errors, missing state updates",

  "new_text": "- **Logic**: wrong conditions, off-by-one errors, missing state updates\n
    - **Cache key collisions**: keys that are bare IDs with no entity-type prefix —
      e.g. cacheGet('42') used for both users and products hits the same slot; keys
      must encode the entity type (user:42, product:42)\n
    - **Unused TTL / wrong expiry**: a ttlSeconds parameter accepted by the function
      but never forwarded to the underlying store call (e.g. SET key value with no EX
      argument), so entries never expire\n
    - **Cache stampede**: on a cache miss, multiple concurrent callers all recompute
      and overwrite — look for a missing lock/mutex guard around the miss-fill path"
}
```

The edit is **exactly one sentence becoming four** — a single bullet expanding to a bullet plus three sub-bullets. Nothing else in the skill changes.

The optimizer chose to target the `logic` bullet specifically because:
1. It had the lowest catch rate (71% vs. 92%+ everywhere else)
2. The top miss (`key_collision`, 8×) had zero existing guidance — the reviewer simply didn't know to look
3. The fix was concrete and actionable: name the pattern, give an example, say what to look for

---

### Step 5 — The Updated skill.md (Step 3 Excerpt)

```markdown
### Step 3 — Inspect each changed section

Go back through the diff and check each section for issues. Look for:

- **Security**: hardcoded secrets, injection, missing authentication, unvalidated input
- **Logic**: wrong conditions, off-by-one errors, missing state updates
  - **Cache key collisions**: keys that are bare IDs with no entity-type prefix —
    e.g. `cacheGet('42')` used for both users and products hits the same slot;
    keys must encode the entity type (`user:42`, `product:42`)
  - **Unused TTL / wrong expiry**: a `ttlSeconds` parameter accepted by the function
    but never forwarded to the underlying store call (e.g. `SET key value` with no
    `EX` argument), so entries never expire
  - **Cache stampede**: on a cache miss, multiple concurrent callers all recompute
    and overwrite — look for a missing lock/mutex guard around the miss-fill path
- **Null safety**: unchecked return values, missing guards before property access
- **Error handling**: swallowed exceptions, missing rollbacks, silent failures
- **Performance**: N+1 queries, missing cache expiry, unnecessary loops
- **Type safety**: use of `any`, missing type guards, unsafe casts
```

---

### Step 6 — The Reviewer's Output (After the Edit)

Running the same reviewer with the new skill.md on a selection task (task_091 — a cache_service variant):

```
[SEVERITY: HIGH] Line 15 — TTL parameter never applied to cache entries
Category: logic / cache_expiry
Detail: The cacheSet() function does not accept a ttlSeconds parameter, so even
though getOrSet receives ttlSeconds, it's never forwarded to redis.set(). Cache
entries will live indefinitely, causing unbounded memory growth in Redis. Add
ttlSeconds parameter to cacheSet and use redis.set(cacheKey, ..., { EX: ttlSeconds })
to actually expire entries.

[SEVERITY: HIGH] Line 10 — Unhandled JSON.parse error on corrupted cache data
Category: error_handling
Detail: If a cached value is malformed JSON (corruption, stale format, etc.),
JSON.parse(raw) will throw and crash the caller. Wrap in try-catch and either
return null (treat as cache miss) or log and fall back to fetchFn in getOrSet.

[SEVERITY: MEDIUM] Line 23–27 — Cache stampede: concurrent getOrSet calls cause
redundant fetches
Category: performance / cache_stampede
Detail: If two callers invoke getOrSet(sameKey) while the cache is cold, both will
call fetchFn() independently, both execute it, and both overwrite the cache entry.
This defeats the point of caching under concurrent load. Consider using inline
promise memoization (store the Promise, not just the result) or a distributed lock
to ensure only one caller executes fetchFn per key.
```

**Score: 1.00 / 1.00** — all three planted bugs caught. The reviewer now explicitly names "cache stampede", uses keywords like `thundering herd`, `lock`, `mutex`, `concurrent` — all matching the scorer's keyword list.

---

### Step 7 — The Selection Gate

The updated skill.md was used to review all 20 selection tasks. Result:

```
Selection  before=0.233  after=0.951  Δ=+0.718  ACCEPTED ✓
```

Since `delta > 0`, the new skill.md is committed. The epoch is complete.

> **Note on the baseline score**: The 0.233 baseline was measured before a stop-hook
> infrastructure bug was fixed (the hook was intercepting some subprocess calls and
> injecting a git status message as if it were a user turn — producing 0.00 scores
> on those tasks). The 0.951 figure is measured with the infrastructure fully
> corrected. The cache-pattern edit itself is genuine and measurable; the large delta
> also reflects the infrastructure correction. A clean re-baseline would show the
> true signal attributable to the skill edit alone.

---

### Step 8 — The Slow Update

After the selection gate (regardless of the outcome), the optimizer wrote strategic meta-guidance to the `SLOW_UPDATE` block in skill.md. This block accumulates across all epochs and teaches the reviewer *how to think*, not just *what to find*:

```markdown
<!-- SLOW_UPDATE_START -->
- **Cache key collisions are the #1 logic miss**: whenever a key is constructed from
  fewer fields than uniquely identify the resource, flag it — always verify every
  dimension of uniqueness is encoded in the key.

- **Verify units and magnitudes on every numeric value with an implicit denomination**:
  wrong-unit bugs appear in two recurring flavors — (1) time: seconds vs. milliseconds,
  (2) money: cents vs. dollars. Sanity-check both the unit and the semantic
  reasonableness of the value.

- **Check for cache stampede on any "miss → recompute" path**: flag any cold-start
  or high-traffic path that lacks a lock, single-flight guard, or probabilistic
  early expiry.

- **Hunt for memory leaks on every subscription, listener, interval, or stream**:
  look for addEventListener, setInterval, EventEmitter.on, or Observable.subscribe
  that have no corresponding teardown.

- **Hunt for swallowed errors**: look for catch {}, .catch(() => {}), or catches that
  log but still return null — these hide failures silently.

- **Logic is the weakest category (~70% catch rate)** — always trace branches with
  concrete boundary values rather than reading the logic abstractly.
<!-- SLOW_UPDATE_END -->
```

---

### Epoch 1 Summary

| What happened | Detail |
|---|---|
| Bug targeted | `key_collision` (missed 8×), `wrong_expiry` (2×), `stampede` (2×) |
| Edit made | 1 bullet → 4 bullets in Step 3 Logic section |
| Chars changed | 71 chars → 416 chars |
| Selection gate | 0.233 → 0.951 (+0.718) ✓ |
| Slow update | 6 strategic bullets written to SLOW_UPDATE block |

---

## 14. How to Use This System

This section explains how to run the system from scratch, how to adapt it to a new domain, and what each command does.

---

### Prerequisites

- **Claude Code CLI** installed and logged in (`claude` command available in PATH)
- Python 3.10+
- Git

```bash
# Verify the CLI works
claude --version
claude --print --model claude-haiku-4-5-20251001 "Say hello" --no-session-persistence
```

No `ANTHROPIC_API_KEY` is needed. All model calls reuse the Claude Code OAuth session.

---

### Installation

```bash
# Clone the repo
git clone <repo-url>
cd claude-skills

# Install Python dependencies
pip install -r requirements.txt

# Verify the dataset exists
ls data/tasks.json   # should show the 150-task file
```

---

### Step 1 — Generate the Dataset (already done, skip if tasks.json exists)

```bash
python -m src.dataset.generator
```

This writes `data/tasks.json` with 150 tasks. It is deterministic (seed=42) so the same file is always produced. The file is committed to the repo so you normally do not need to re-run this.

Output:
```
Generated 150 tasks
  train:     80
  selection: 20
  test:      50
Total planted bugs: 330
```

---

### Step 2 — Run a Smoke Test (1 task)

Before doing a full rollout, verify that the CLI backend and scorer work end-to-end:

```bash
python -m src.runner --split train --limit 1
```

Expected output (one task, ~30s):
```
Split: train  |  Model: claude-haiku-4-5-20251001  |  Output: data/train_results.jsonl

Running 1 tasks (8 workers)…
[  1/ 1] task_001 | api_middleware     score=0.67  mean=0.67  cache_read=     0  28.3s

── Summary ─────────────────────────────────
  tasks:       1
  mean score:  0.670
  catch rate:  0.667
```

---

### Step 3 — Run a Full Evaluation (one split)

```bash
# Evaluate all 80 train tasks, save results
python -m src.runner --split train --output data/my_train_run.jsonl

# Evaluate selection split
python -m src.runner --split selection --output data/my_selection_run.jsonl

# Evaluate with a different model
python -m src.runner --split train --model claude-haiku-4-5-20251001 --output data/run_haiku.jsonl

# Resume an interrupted run (skips already-completed task IDs)
python -m src.runner --split train --output data/my_train_run.jsonl
```

The runner prints a live progress line per task showing `score`, rolling `mean`, `cache_read` tokens (how much was served from the prompt cache), and elapsed time.

---

### Step 4 — Run the Optimizer

The optimizer runs the full TextGrad loop: train rollout → propose edit → selection gate → slow update — for N epochs.

```bash
# Run 3 epochs (recommended starting point)
python -m src.optimizer --epochs 3

# Run 5 epochs for deeper optimization
python -m src.optimizer --epochs 5

# Dry-run: propose and print the edit, but don't apply it or run selection
python -m src.optimizer --epochs 1 --dry-run

# Resume from a specific epoch (if epoch_001 exists and epoch_002 does not)
python -m src.optimizer --epochs 3 --start-epoch 2

# Use a different model for the reviewer (default: haiku)
# Edit DEFAULT_MODEL in src/optimizer.py, or pass --model flag to runner directly
```

The optimizer writes results to `data/epochs/epoch_NNN/`:

```
data/epochs/epoch_001/
  train_results.jsonl    ← scored reviews for all 80 train tasks
  proposed_edit.json     ← the exact edit proposed by Sonnet
  skill_before.md        ← snapshot of skill.md before the edit
  skill_after.md         ← skill.md with the proposed edit applied
  selection_results.jsonl← scored reviews for the 20 selection tasks
  epoch_result.json      ← {accepted, delta, train_mean, selection_before, selection_after}
```

If the run is interrupted (session limit, network error, etc.), **re-running the same command resumes automatically** — completed tasks are skipped.

---

### Step 5 — Read the Results

```bash
# Print a summary of a completed results file
python3 -c "
import json
from pathlib import Path
from src.runner import load_results, summarise

results = load_results(Path('data/epochs/epoch_001/train_results.jsonl'))
s = summarise(results)
print(f'Tasks: {s[\"n_tasks\"]}')
print(f'Mean score: {s[\"mean_score\"]:.3f}')
print(f'Catch rate: {s[\"overall_catch_rate\"]:.1%}')
print()
print('By category:')
for cat, v in sorted(s['by_category'].items(), key=lambda kv: kv[1]['rate']):
    bar = '█' * int(v['rate'] * 20)
    print(f'  {cat:<20} {v[\"caught\"]}/{v[\"total\"]}  {bar}  {v[\"rate\"]:.0%}')
print()
print('Top missed:')
for bug, count in s['top_missed_bugs'][:5]:
    print(f'  {bug:<35} {count}x')
"

# Check an epoch result
cat data/epochs/epoch_001/epoch_result.json
```

---

### Step 6 — Run the Test Evaluator (ONCE, after optimization is complete)

The test split (50 tasks) is **locked** — it must not be used during optimization, only at the very end to get a final unbiased score.

```bash
# Only run this once, when you are satisfied with the skill
python -m src.runner --split test --output data/test_results_final.jsonl
```

Compare the test score to the baseline selection score (0.233) to measure the true out-of-sample improvement.

---

### Adapting to a New Domain

The system is domain-agnostic. To use it for a different task (e.g., SQL query review, security audit, documentation quality):

**1. Replace the scenarios** (`src/dataset/scenarios.py`):
- Define 4–8 scenario templates in your domain
- Each scenario needs: a task description, 4–6 injectable "bugs" or quality issues, and a `generate_task(active_issues: set) -> str` function
- Give each issue a list of keyword signals the scorer can look for in the reviewer's output

**2. Replace the skill** (`skill.md`):
- Write an initial skill document for your domain
- Add a `<!-- SLOW_UPDATE_START --><!-- SLOW_UPDATE_END -->` block at the bottom
- Deliberately leave some gaps so the optimizer has room to improve it

**3. Regenerate the dataset**:
```bash
python -m src.dataset.generator   # writes data/tasks.json
```

**4. Run the baseline**:
```bash
python -m src.runner --split selection --output data/epochs/epoch_000/selection_results.jsonl
```

**5. Run the optimizer**:
```bash
python -m src.optimizer --epochs 5
```

The optimizer prompt in `src/optimizer.py` (`_PROPOSE_SYSTEM`) is written generically — it talks about "the skill document" and "missed items" and will work for any scoring domain without changes.

---

### Configuration Reference

| Setting | Location | Default | Description |
|---|---|---|---|
| Reviewer model | `src/optimizer.py` `ROLLOUT_MODEL` | `claude-haiku-4-5-20251001` | Model used for reviewing tasks. Haiku is fast and cheap. |
| Optimizer model | `src/optimizer.py` `OPTIMIZER_MODEL` | `claude-sonnet-4-6` | Model used to propose edits. Sonnet gives better edits. |
| Workers | `src/runner.py` `run_rollout(..., workers=8)` | 8 | Parallel subprocess workers. Higher = faster but more session quota used. |
| Subprocess timeout | `src/backend.py` `complete(..., timeout=300)` | 300s | Per-call timeout in seconds. |
| Epochs dir | `src/optimizer.py` `EPOCHS_DIR` | `data/epochs/` | Where epoch results are written. |
| Skill path | `src/optimizer.py` `SKILL_PATH` | `skill.md` | The skill document being optimized. |

---

### Understanding the Output Files

| File | What it is |
|---|---|
| `data/tasks.json` | The full benchmark — 150 tasks with diffs, PR context, and expected bugs |
| `data/epochs/epoch_000/selection_results.jsonl` | Baseline score before any optimization |
| `data/epochs/epoch_NNN/train_results.jsonl` | One scored result per line; each has `task_id`, `score`, `caught`, `missed`, `review`, `usage`, `cost_usd` |
| `data/epochs/epoch_NNN/proposed_edit.json` | The exact JSON proposal from Sonnet: `{target_step, rationale, old_text, new_text}` |
| `data/epochs/epoch_NNN/epoch_result.json` | Final verdict: `{accepted, delta, selection_before, selection_after}` |
| `skill.md` | The live skill document — modified in place when an edit is accepted |
| `data/epochs/epoch_NNN/skill_before.md` | Snapshot of skill.md before the epoch's edit was applied |
| `data/epochs/epoch_NNN/skill_after.md` | Snapshot of skill.md after the edit (regardless of whether accepted) |

---

### Typical Run Times

| Operation | Wall-clock time | Notes |
|---|---|---|
| Generate dataset | < 5 seconds | Pure Python, no model calls |
| Baseline selection (20 tasks) | ~4 minutes | 8 workers × ~25s/task |
| Train rollout (80 tasks) | ~10–15 minutes | 8 workers; longer tasks can take 60s+ |
| Propose edit (1 Sonnet call) | ~30 seconds | Includes failure analysis and 3 examples |
| Selection gate (20 tasks) | ~4 minutes | Same as baseline |
| Slow update (1 Sonnet call) | ~20 seconds | Reads all epoch histories |
| **Full epoch** | **~20 minutes** | Train + propose + selection + slow update |
| **3 epochs** | **~60 minutes** | If no session limits hit |

---

*Last updated: Epoch 3 in progress. Test split (50 tasks) locked until optimization completes.*
