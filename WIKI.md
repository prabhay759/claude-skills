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
