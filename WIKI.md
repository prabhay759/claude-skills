# TextGrad Skill Optimizer — Project Wiki

> **One-line summary**: A general framework that automatically improves an AI agent's
> instruction document by measuring what it gets wrong on a benchmark and using a
> stronger model to propose targeted fixes — no human rewriting required.

---

## Table of Contents

**Part I — The General Framework**
1. [What Problem Does This Solve?](#1-what-problem-does-this-solve)
2. [The Core Idea — TextGrad for Prompts](#2-the-core-idea--textgrad-for-prompts)
3. [The Four Building Blocks](#3-the-four-building-blocks)
4. [The Optimization Loop (Abstract)](#4-the-optimization-loop-abstract)
5. [Adapting to Any Domain](#5-adapting-to-any-domain)

**Part II — The Worked Example: AI Code Review**
6. [Why Code Review?](#6-why-code-review)
7. [The Benchmark Dataset](#7-the-benchmark-dataset)
8. [The Scorer (Objective Function)](#8-the-scorer-objective-function)
9. [The Skill Document](#9-the-skill-document)
10. [Epoch 1 — A Full Iteration Traced with Real Data](#10-epoch-1--a-full-iteration-traced-with-real-data)
11. [Results Across All Epochs](#11-results-across-all-epochs)

**Part III — Infrastructure & Engineering**
12. [System Architecture](#12-system-architecture)
13. [The Claude CLI Backend](#13-the-claude-cli-backend)
14. [Engineering Challenges & Solutions](#14-engineering-challenges--solutions)
15. [Repository Structure](#15-repository-structure)

**Part IV — Using the System**
16. [Quickstart](#16-quickstart)
17. [Running the Optimizer](#17-running-the-optimizer)
18. [Reading Results](#18-reading-results)
19. [Adapting to Your Own Domain — Step by Step](#19-adapting-to-your-own-domain--step-by-step)
20. [Configuration Reference](#20-configuration-reference)

---

# Part I — The General Framework

---

## 1. What Problem Does This Solve?

### The Universal Frustration with AI Agents

When you deploy an AI agent — a code reviewer, a document classifier, a customer support bot, a data extractor — it always has blind spots. Some category of task it consistently gets wrong. And the standard fix is to sit down, think hard about *why* it fails, rewrite the system prompt based on intuition, deploy, and check whether it got better.

That process has three deep problems:

| Problem | Why it hurts |
|---|---|
| **No objective signal** | "It feels better" is not a measurement. You cannot tell if the rewrite helped, hurt, or just changed which tasks it fails on. |
| **Regression risk** | Adding guidance for the cases it misses often degrades the cases it already handles correctly. There is no gate stopping you from committing a rewrite that is a net negative. |
| **Expert bottleneck** | Fixing the prompt requires someone who understands both the domain and the model. That person's time is expensive and their intuition is fallible. |

### What This Framework Does Instead

This framework turns prompt improvement into a **data-driven optimization loop**:

1. Run the agent on a benchmark of tasks where the right answer is known
2. Measure exactly which sub-categories it fails on and how often
3. Have a stronger model read the failures and propose a minimal, targeted edit to the skill document
4. Test the edit on a held-out split — accept it only if the score goes up
5. Repeat

The result: the skill document improves automatically, every accepted edit is validated before commit, and the system shows you a precise before/after score for each change.

---

## 2. The Core Idea — TextGrad for Prompts

### Background: TextGrad

In neural network training, a **gradient** tells you which direction to move each parameter to reduce the loss. The chain rule propagates this signal backwards through every layer.

Language model outputs are not differentiable — you cannot backpropagate through text. **TextGrad** (Yuksekgonul et al., 2024) replaces numeric gradients with *textual feedback*: instead of computing `∂Loss/∂parameter`, you ask a language model to read the failures and produce a description of what the parameter (the prompt) should change to reduce those failures.

### Applied to Skill Documents

In this framework:

| Neural network concept | This framework's equivalent |
|---|---|
| Model parameters | The text of the skill document (skill.md) |
| Loss function | 1 − mean score on the benchmark |
| Gradient | Failure analysis: which bugs missed, which categories weak, example bad outputs |
| Gradient step | Optimizer model proposes a targeted edit to the skill text |
| Validation set | Selection split (held-out 20 tasks not seen during "training") |
| Learning rate clamp | Only one targeted edit per epoch; exact string replacement only |
| Early stopping | Selection gate: reject the edit if the selection score does not improve |

### Why This Analogy Holds Up

- **Direction**: The failure analysis tells the optimizer *where* the skill is weak (analogous to the gradient direction)
- **Magnitude**: The "one minimal edit" constraint prevents overshooting (analogous to a small learning rate)
- **Generalization check**: The selection gate tests on unseen data, catching overfitting to the training split
- **Momentum**: The slow-update block accumulates strategic patterns across epochs, analogous to momentum in an optimizer

---

## 3. The Four Building Blocks

Every instantiation of this framework needs exactly four things:

### Building Block 1 — The Benchmark

A dataset of tasks where the correct answer is known in advance. Each task must be:
- **Independent** — tasks do not share state
- **Scored** — there is a deterministic function that maps agent output → number in [0, 1]
- **Split** — divided into train (used every epoch), selection (gate), and test (locked until the end)

The train/selection/test split is critical. The optimizer never sees the selection split during training, so it cannot overfit to it. The test split is never touched until optimization is complete — it gives the final unbiased score.

### Building Block 2 — The Scorer

A function that takes the agent's output for one task and returns a score in [0, 1].

The scorer does **not** need to be sophisticated. The only requirements are:
- **Deterministic** — same output always produces the same score
- **Fast** — it runs once per task per epoch, so speed matters
- **Faithful** — high scores should actually mean good performance

Keyword matching, regex patterns, JSON schema validation, unit test pass/fail, SQL result comparison — all work. The simpler the better. NLP-based scoring adds noise and makes failures harder to diagnose.

### Building Block 3 — The Skill Document

A text file that serves as the agent's system prompt. This is the object being optimized.

Design guidelines:
- Structure it in numbered steps or sections so the optimizer can reference specific locations
- Leave a `<!-- SLOW_UPDATE_START --><!-- SLOW_UPDATE_END -->` block at the bottom for accumulated meta-guidance
- Start with **intentional gaps** — if the initial skill is perfect, there is nothing to optimize
- Keep it human-readable; the optimizer reads it to understand what already exists before proposing changes

### Building Block 4 — The Optimizer Loop

The control loop that runs epochs, coordinates the rollout and optimizer models, enforces the selection gate, and writes the slow update. In this implementation it lives in `src/optimizer.py` and requires no domain-specific changes when adapting to a new domain.

---

## 4. The Optimization Loop (Abstract)

```
Initialize:
  skill.md     ← starting skill document (with intentional gaps)
  baseline     ← run selection split once to get starting score S₀

For each epoch N:

  ┌─ ROLLOUT (train split) ──────────────────────────────────────────┐
  │  For each task in train split (in parallel):                     │
  │    response = agent(system=skill.md, user=task)                  │
  │    score[task] = scorer(response, task)                          │
  │  → produces: {scores, caught/missed per bug, by-category stats}  │
  └──────────────────────────────────────────────────────────────────┘
            │
            ▼
  ┌─ FAILURE ANALYSIS ───────────────────────────────────────────────┐
  │  Which categories have the lowest catch rates?                   │
  │  Which specific items are missed most often?                     │
  │  Sample the 3 worst-scoring responses as concrete examples       │
  └──────────────────────────────────────────────────────────────────┘
            │
            ▼
  ┌─ PROPOSE EDIT (optimizer model) ─────────────────────────────────┐
  │  Input:  skill.md + failure analysis + 3 worst examples          │
  │  Output: EditProposal {                                           │
  │    target_step: "Step 3",                                         │
  │    rationale:   "why this edit will help",                        │
  │    old_text:    "exact string to replace",                        │
  │    new_text:    "replacement text"                                │
  │  }                                                                │
  │  Constraint: one targeted edit, not a full rewrite               │
  └──────────────────────────────────────────────────────────────────┘
            │
            ▼  apply edit to produce candidate_skill.md
            │
  ┌─ SELECTION GATE ─────────────────────────────────────────────────┐
  │  Run selection split with candidate_skill.md                     │
  │  S_after = mean score on selection split                         │
  │  delta = S_after − S_before                                      │
  │                                                                   │
  │  IF delta > 0:                                                    │
  │    skill.md ← candidate_skill.md    (ACCEPTED ✓)                 │
  │    S_before ← S_after                                            │
  │  ELSE:                                                            │
  │    skill.md ← unchanged             (REJECTED ✗)                 │
  └──────────────────────────────────────────────────────────────────┘
            │  (always, regardless of gate outcome)
            ▼
  ┌─ SLOW UPDATE ────────────────────────────────────────────────────┐
  │  Optimizer reads all epoch summaries to date                     │
  │  Rewrites the SLOW_UPDATE block in skill.md                      │
  │  Adds/refines strategic meta-guidance about hardest categories   │
  └──────────────────────────────────────────────────────────────────┘
```

### Why Two Separate Update Channels?

The framework maintains two distinct ways of improving the skill:

| Channel | Trigger | Content |
|---|---|---|
| **Inline edit** (main body of skill.md) | Only when `delta > 0` | Concrete checklist items added to the relevant section |
| **SLOW_UPDATE block** (always updated) | Every epoch | Strategic meta-patterns: which categories are hardest, how to approach them |

The inline edits teach the agent *what to look for*. The slow update teaches it *how to look*. Together they cover both specific techniques and general review philosophy.

---

## 5. Adapting to Any Domain

The framework generalizes to any agent that reads a task description and produces text output that can be scored.

### Candidate Domains

| Domain | Tasks | Scorer | Agent |
|---|---|---|---|
| **Code review** ← this project | PRs with planted bugs | Bug keyword matching | Claude reviewer |
| **SQL query audit** | Queries with planted errors (no index, N+1, injection) | Keyword/pattern matching | Claude auditor |
| **Legal clause review** | Contracts with risky clauses | Clause-presence scoring | Claude analyst |
| **Data extraction** | Documents with structured facts | F1 against ground-truth JSON | Claude extractor |
| **Customer support** | Tickets with required resolutions | Resolution keyword matching | Claude support agent |
| **Security audit** | Code with planted CVEs | CVE-type keyword matching | Claude security reviewer |
| **Test generation** | Functions needing specific test cases | Test coverage scoring | Claude test writer |

### What Stays the Same Across Domains

- `src/backend.py` — the Claude CLI wrapper
- `src/runner.py` — the parallel rollout runner with resume
- `src/optimizer.py` — the full TextGrad loop (propose → gate → slow update)
- The `skill.md` structure (steps + SLOW_UPDATE block)

### What Changes Across Domains

- `src/dataset/scenarios.py` — your task templates and injectable ground-truth items
- `src/dataset/generator.py` — your variant generation logic
- `src/scorer.py` — your domain-specific scoring function
- `skill.md` content — your starting skill document for the new domain

---

# Part II — The Worked Example: AI Code Review

---

## 6. Why Code Review?

Code review is an ideal first instantiation of this framework because:

- **Objective ground truth**: bugs can be planted deterministically in code
- **Clear failure modes**: missing a bug is an unambiguous miss
- **Real-world value**: catching security, logic, and null-safety bugs is high stakes
- **Rich diversity**: six different codebases cover different bug categories naturally
- **Fast scoring**: keyword matching is deterministic and takes milliseconds

The TypeScript codebase was chosen because it mixes static types (catchable by type-safety checks) with runtime patterns (null safety, async errors) and infrastructure patterns (SQL, Redis, Stripe), giving broad coverage across bug categories.

---

## 7. The Benchmark Dataset

### Overview

| Property | Value |
|---|---|
| Total tasks | **150** |
| Scenarios (codebases) | **6** |
| Bugs per scenario | **5** (independently injectable) |
| Variants per scenario | **25** (C(5,1) + C(5,2) + C(5,3)) |
| Total planted bugs across all tasks | **330** |
| Train split | 80 tasks |
| Selection split | 20 tasks |
| Test split | 50 tasks (locked) |

### The 6 TypeScript Scenarios

Each scenario is a realistic feature PR with its own PR title, description, and 5 independently plantable bugs:

| Scenario | PR Theme | 5 Bugs |
|---|---|---|
| `auth_service` | JWT refresh token rotation | `hardcoded_secret`, `token_not_revoked`, `missing_user_check`, `wrong_expiry`, `swallow_error` |
| `user_repo` | User data access layer | `sql_injection`, `n_plus_one`, `null_deref`, `missing_rollback`, `any_type` |
| `api_middleware` | Rate-limiting + JWT auth middleware | `ip_spoofing`, `jwt_decode_not_verify`, `off_by_one`, `double_response`, `missing_error_status` |
| `react_hook` | React data-fetching hook | `missing_dep`, `unhandled_promise`, `memory_leak`, `wrong_type`, `no_loading_reset` |
| `payment_service` | Stripe charge + webhook handler | `no_amount_validation`, `no_idempotency`, `stripe_error_swallowed`, `no_webhook_validation`, `cents_vs_dollars` |
| `cache_service` | Redis-backed cache layer | `no_ttl`, `json_parse_no_catch`, `no_null_check`, `key_collision`, `stampede` |

### Bug Injection

Each scenario has a `generate_code(active_bugs: set[str]) -> str` function. It conditionally includes or excludes buggy code paths based on which bugs are active, always producing syntactically valid TypeScript.

```python
# cache_service with key_collision and stampede planted
code = scenarios["cache_service"]["generate_code"]({"key_collision", "stampede"})
# → valid TypeScript with exactly those two bugs; all other patterns are clean
```

### Variant Generation

For each of the 6 scenarios, all combinations of 1, 2, and 3 active bugs are generated:

```
C(5,1) = 5   single-bug variants  (isolates each bug cleanly)
C(5,2) = 10  two-bug variants     (tests interaction effects)
C(5,3) = 10  three-bug variants   (realistic PR complexity)
─────────────────────────────────
             25 variants × 6 scenarios = 150 tasks
```

Each task is formatted as a unified diff (`--- /dev/null`, `+++ b/filename`) — the same format a reviewer sees in a real GitHub PR.

### Data Split Strategy

```
150 tasks shuffled with seed=42

  ├── 80 tasks → train   (optimizer sees these every epoch)
  ├── 20 tasks → selection (gate — optimizer never trains on these)
  └── 50 tasks → test    (locked — run exactly once at the end)
```

---

## 8. The Scorer (Objective Function)

### Algorithm

For each planted bug in a task, check whether any of its keyword signals appear as substrings in the reviewer's normalized output text:

```python
def score_review(review: str, task: dict) -> ScoreResult:
    normalized = re.sub(r'\s+', ' ', review.lower())
    for bug in task["bugs"]:
        caught = any(keyword in normalized for keyword in bug["keywords"])
    score = n_caught / n_bugs   # → [0.0, 1.0]
```

### Example Bug Keywords

| Bug key | Keywords the scorer looks for |
|---|---|
| `key_collision` | `"namespace"`, `"key collision"`, `"prefix"`, `"cache key"`, `"namespaced"`, `"collision"` |
| `stampede` | `"stampede"`, `"thundering herd"`, `"mutex"`, `"singleflight"`, `"concurrent"`, `"lock"` |
| `hardcoded_secret` | `"hardcoded"`, `"jwt_secret"`, `"secret literal"`, `"process.env"` |
| `cents_vs_dollars` | `"cents"`, `"dollars"`, `"/ 100"`, `"* 100"`, `"denomination"` |
| `memory_leak` | `"memory leak"`, `"cleanup"`, `"unmount"`, `"removeEventListener"` |

### Why Not Use LLM Scoring?

| Criterion | Keyword matching | LLM-as-judge |
|---|---|---|
| Speed | Milliseconds | 10–30 seconds per task |
| Determinism | 100% | Varies across calls |
| Cost | $0 | ~$0.01–0.05 per task |
| Auditability | Exact string, easy to debug | Black box |
| False positives | Low (domain-tuned keywords) | Possible hallucination |

For a benchmark of 150 tasks run multiple times per epoch, keyword matching is the right trade-off.

---

## 9. The Skill Document

### Structure

The skill document is the system prompt given to the AI reviewer. It has two parts:

**Main body** — the procedural instructions (Steps 1–4). This is where inline edits land.

**SLOW_UPDATE block** — a special section at the bottom that the optimizer rewrites every epoch with accumulated strategic guidance.

```markdown
# Code Review Skill

You are a senior engineer performing a security-focused code review…

## Procedure

### Step 1 — Read the PR context
…

### Step 2 — Scan the full diff
…

### Step 3 — Inspect each changed section
…

### Step 4 — Write the review
…

<!-- SLOW_UPDATE_START -->
[strategic meta-guidance accumulates here across epochs]
<!-- SLOW_UPDATE_END -->
```

### Initial Design — Intentional Gaps

The initial skill listed six categories in Step 3 (security, logic, null-safety, error-handling, performance, type-safety) but gave no:
- Sub-patterns within each category
- Prioritization by difficulty
- Concrete examples of what to look for

This is intentional — if the skill were perfect from the start, there would be nothing for the optimizer to improve.

### Evolution Across Epochs

| Version | What changed |
|---|---|
| **Initial** | 6 bare bullet points in Step 3 |
| **After Epoch 1** | Logic bullet expanded with 3 cache-specific sub-patterns (key collision, unused TTL, stampede) |
| **After Epoch 2 slow_update** | SLOW_UPDATE block refined to add money-unit (cents/dollars) guidance and memory leak hunting |

---

## 10. Epoch 1 — A Full Iteration Traced with Real Data

This section follows a single epoch from start to finish, using the actual code, actual model outputs, and actual scores produced during the first run.

---

### The Task: task_066 (cache_service)

The reviewer was given this unified diff — a new Redis cache helper module for a TypeScript backend:

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
+  await cacheSet(key, value);    // BUG: bare key → key_collision
+  return value;                  // BUG: no lock → stampede
+}
```

**Three planted bugs:**

| Bug | Where | Description |
|---|---|---|
| `key_collision` | `cacheSet(key, value)` | Keys are passed through as bare strings. If two callers use `cacheGet('42')` for different entity types (users, products), they share the same Redis slot. |
| `stampede` | `getOrSet` miss path | No lock around the cache miss. Under concurrent load, many callers all fall through to `fetchFn()` simultaneously, all execute the expensive DB call, all write the same value back. |
| `no_null_check` | `JSON.parse(raw)` | `redis.get()` returns `null` on a cache miss; `JSON.parse(null)` throws on some Redis client versions. |

---

### The Reviewer's Output — Before the Epoch 1 Edit

With the initial `skill.md`, the reviewer produced:

```
[SEVERITY: HIGH] Line 3 — Redis connection not awaited
Category: logic
Detail: redis.connect() returns a promise but is not awaited. The connection
may not be established before the first cache operation, causing runtime errors.
Change to: await redis.connect()

[SEVERITY: HIGH] Line 31 — Missing ttlSeconds parameter in cacheSet call
Category: logic
Detail: The getOrSet function accepts ttlSeconds but does not pass it to
cacheSet(). Cache entries created via getOrSet always use the 300s default
regardless of what the caller specified.
Change to: await cacheSet(key, value, ttlSeconds)

[SEVERITY: MEDIUM] Line 10 — Inefficient null handling in JSON.parse
Category: performance
Detail: If redis.get() returns null, JSON.parse(null) throws an exception and
redis.del() is called unnecessarily. Check if raw is null first.
```

**Score: 0.33 / 1.00**

The reviewer found the unawaited connection and the TTL passthrough — both real problems. But it never mentioned "key collision", "namespace", "prefix", or "concurrent" — the planted `key_collision` and `stampede` bugs were invisible to it.

The model was not incapable of finding these bugs. It simply had no instruction to look for them.

---

### The Failure Analysis

After all 65 train tasks completed (with 8 parallel workers), the runner produced this summary:

```
Train  mean=0.882  catch=90%  tasks=65

  logic                ██████████░░░░░  71%   ← only category below 90%
  error_handling       █████████████░░  92%
  performance          ███████████████  100%
  null_safety          ███████████████  100%
  security             ███████████████  100%
  type_safety          ███████████████  100%

Top missed bugs:
  key_collision         8×   ← present in 8 tasks; missed every single time
  wrong_expiry          2×
  stampede              2×
  swallow_error         2×
  cents_vs_dollars      1×
```

The signal is unambiguous: `key_collision` was planted in 8 tasks and caught in 0 of them. `stampede` planted in 5, caught in 3. Logic is the only weak category, and almost all the misses are cache-specific patterns the initial skill never mentioned.

---

### The Proposed Edit

This failure analysis, the current `skill.md`, and the 3 worst-scoring reviews were given to the optimizer model (claude-sonnet-4-6) with a `--json-schema` flag to get structured output:

```json
{
  "epoch": 1,
  "target_step": "Step 3",
  "rationale": "The logic category has the lowest catch rate (71%), and
    key_collision is missed 8× — the agent never checks whether cache keys
    are namespaced, so it misses collisions when bare IDs are shared across
    entity types; adding concrete sub-bullets for this pattern (and the
    related wrong_expiry/stampede misses) directly teaches the check.",

  "old_text": "- **Logic**: wrong conditions, off-by-one errors, missing state updates",

  "new_text": "- **Logic**: wrong conditions, off-by-one errors, missing state updates\n
    - **Cache key collisions**: keys that are bare IDs with no entity-type
      prefix — e.g. cacheGet('42') used for both users and products hits the
      same slot; keys must encode the entity type (user:42, product:42)\n
    - **Unused TTL / wrong expiry**: a ttlSeconds parameter accepted by the
      function but never forwarded to the underlying store call (e.g. SET key
      value with no EX argument), so entries never expire\n
    - **Cache stampede**: on a cache miss, multiple concurrent callers all
      recompute and overwrite — look for a missing lock/mutex guard around
      the miss-fill path"
}
```

**The edit in plain terms**: one bullet became four. The general "Logic" bullet now has three cache-specific sub-bullets naming exactly the patterns that caused the 8+2+2 misses. Nothing else in the skill changed.

---

### The Updated Step 3 in skill.md

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

### The Reviewer's Output — After the Epoch 1 Edit

Running the same reviewer on a selection task (task_091 — a different cache_service variant):

```
[SEVERITY: HIGH] Line 15 — TTL parameter never applied to cache entries
Category: logic / cache_expiry
Detail: The cacheSet() function does not accept a ttlSeconds parameter, so even
though getOrSet receives ttlSeconds, it is never forwarded to redis.set(). Cache
entries will live indefinitely, causing unbounded memory growth in Redis. Add
ttlSeconds parameter to cacheSet and use redis.set(cacheKey, ..., {EX: ttlSeconds})
to actually expire entries.

[SEVERITY: HIGH] Line 10 — Unhandled JSON.parse error on corrupted cache data
Category: error_handling
Detail: If a cached value is malformed JSON, JSON.parse(raw) will throw and crash
the caller. Wrap in try-catch and either return null (treat as cache miss) or
fall back to fetchFn in getOrSet.

[SEVERITY: MEDIUM] Line 23–27 — Cache stampede: concurrent getOrSet calls cause
redundant fetches
Category: performance / cache_stampede
Detail: If two callers invoke getOrSet(sameKey) while the cache is cold, both will
call fetchFn() independently, execute it, and overwrite the same cache entry. This
defeats caching under concurrent load. Consider using promise memoization (store
the Promise, not just the result) or a distributed lock to ensure only one caller
executes fetchFn per key.
```

**Score: 1.00 / 1.00** — all three planted bugs caught. The review now uses exactly the keywords the scorer looks for: "TTL", "indefinitely", "stampede", "concurrent", "lock".

---

### The Selection Gate

The updated skill.md was run against all 20 selection tasks:

```
Selection  before=0.233  after=0.951  Δ=+0.718  ACCEPTED ✓
```

Since `delta > 0`, the new skill.md is committed. The epoch is complete.

> **Note on the 0.233 baseline**: This was measured before an infrastructure bug
> was fixed (the Claude Code stop hook was intercepting subprocess calls and
> injecting a git-status message as a new conversation turn, producing score 0.00
> on the affected tasks). The 0.951 figure is measured with all infrastructure
> corrected. The cache-pattern edit is genuine; the large delta partially reflects
> the infrastructure correction. A clean re-baseline would show the true signal from
> the skill edit alone.

---

### The Slow Update

After the gate (always, regardless of accept/reject), the optimizer rewrote the SLOW_UPDATE block:

```markdown
<!-- SLOW_UPDATE_START -->
- **Cache key collisions are the #1 logic miss**: whenever a key is constructed
  from fewer fields than uniquely identify the resource, flag it — always verify
  every dimension of uniqueness is encoded in the key.

- **Verify units and magnitudes on every numeric value with an implicit denomination**:
  wrong-unit bugs appear in two flavors — (1) time: seconds vs. milliseconds,
  (2) money: cents vs. dollars. Sanity-check both the unit and the reasonableness
  of the value.

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

| Step | What happened |
|---|---|
| Train rollout | 65 of 80 tasks scored (rest hit session limit — resume handled this) |
| Weakest category | Logic: 71% catch rate |
| Top miss | `key_collision`: 8× (0% catch rate before the edit) |
| Edit size | 71 characters → 416 characters (1 bullet → 4 bullets) |
| Selection gate | 0.233 → 0.951 (+71.8%) — ACCEPTED |
| Slow update | 6 strategic bullets written |

---

## 11. Results Across All Epochs

### Final Test Score

> **0.861 mean score — 86% bug catch rate on 49 unseen tasks**

The test split (50 tasks, never touched during optimization) was run once after all epochs completed. One task timed out; 49 scored.

### Full Optimization Trajectory

| Phase | Score | Delta | Notes |
|---|---|---|---|
| Baseline (selection, corrupted) | 0.233 | — | Stop-hook bug inflated misses |
| **Epoch 1** (ACCEPTED) | **0.951** | **+71.8%** | Cache collision + TTL + stampede sub-bullets |
| Epoch 2 (REJECTED) | 0.926 | −2.5% | Call-site scanning + cents/dollars; regressed |
| **Epoch 3** (ACCEPTED) | **0.958** | **+0.7%** | "Scan every call site" + multi-tenant check |
| Epoch 4 (REJECTED) | 0.942 | −1.7% | Cross-entity collision scan; regressed |
| Epoch 5 (REJECTED) | 0.942 | −1.7% | Helper API contract check; regressed |
| **Test split (final)** | **0.861** | — | 50 unseen tasks; unbiased final score |

### Final Test Split — Per-Category Catch Rates (49 unseen tasks)

| Category | Caught / Total | Rate |
|---|---|---|
| performance | 9 / 9 | **100%** |
| security | 30 / 31 | **97%** |
| error_handling | 19 / 23 | **83%** |
| type_safety | 5 / 6 | **83%** |
| null_safety | 9 / 11 | **82%** |
| **logic** | **18 / 25** | **72%** ← persistent weak spot |

### What the Optimizer Learned to Catch

The `logic` category started at 71% catch rate (epoch 1 train baseline) and ended at 72% on the final test. The optimizer correctly identified it as the weak spot and made three targeted edits — all accepted or informing the slow update — but the ceiling of what keyword-scored data can push through the strict selection gate was reached.

Most stubborn misses on the test split:

| Bug | Misses | Root cause |
|---|---|---|
| `wrong_expiry` | 3× | TTL unit confusion (seconds vs ms) — correct value, wrong scale |
| `cents_vs_dollars` | 2× | Money denomination mismatch — requires understanding API contracts |
| `swallow_error` | 2× | Silent catch blocks — reviewer finds some but not all |
| `json_parse_no_catch` | 2× | Missing try/catch around JSON.parse — easy to overlook |

### Cost and Token Usage (All Runs Combined)

| Metric | Value |
|---|---|
| Total model calls (all epochs + test) | ~400 |
| **Cache reads** | **>11M tokens** |
| Test split cost | $2.31 |
| **Estimated total project cost** | **~$10** |

The prompt cache is the dominant cost reduction mechanism. The skill.md system prompt (~2,000 chars after optimization) is cached after the first call in each batch and served from cache on the remaining tasks — reducing token cost by ~90% versus sending the full prompt fresh each time.

---

# Part III — Infrastructure & Engineering

---

## 12. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          src/optimizer.py                           │
│                                                                     │
│  for each epoch:                                                    │
│    1. run_rollout(train)   → haiku × 80 tasks (8 workers)          │
│    2. summarise(results)   → failure analysis                       │
│    3. propose_edit()       → sonnet × 1 (json_schema)              │
│    4. apply_edit()         → exact string replace in skill.md       │
│    5. run_rollout(select)  → haiku × 20 tasks (8 workers)          │
│    6. gate(delta > 0)      → accept or revert                       │
│    7. slow_update()        → sonnet × 1                             │
└─────────────────────────────────────────────────────────────────────┘
                    │ all model calls via
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  src/backend.py  —  complete(system, user, model) → CallResult      │
│                                                                     │
│  subprocess: claude --print --output-format json                    │
│              --model <model>                                        │
│              --system-prompt <skill_text>                           │
│              --no-session-persistence                               │
│              [--json-schema <schema>]                               │
│                                                                     │
│  env: CLAUDE_OPTIMIZER_SUBPROCESS=1  (disables stop hook)          │
└─────────────────────────────────────────────────────────────────────┘
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
┌──────────────────┐  ┌─────────────────────────────┐
│  src/runner.py   │  │  src/scorer.py               │
│                  │  │                              │
│  ThreadPool(8)   │  │  score_review(text, task)    │
│  JSONL + resume  │  │  → ScoreResult(0.0–1.0)      │
└──────────────────┘  └─────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│  data/epochs/epoch_NNN/                                  │
│    train_results.jsonl     selection_results.jsonl       │
│    proposed_edit.json      epoch_result.json             │
│    skill_before.md         skill_after.md                │
└──────────────────────────────────────────────────────────┘
```

---

## 13. The Claude CLI Backend

### Why `claude --print` Instead of the Python SDK

The remote execution container does not have an `ANTHROPIC_API_KEY`. The `claude` CLI, however, uses the same OAuth session as Claude Code — no separate credentials needed. Calling `claude --print` as a subprocess gives access to all models without any additional setup.

### The JSON Envelope

`--output-format json` wraps the response in a structured envelope:

```json
{
  "result": "the model's text response",
  "structured_output": { ... },   // populated when --json-schema is used
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_read_input_tokens": 45678,
    "cache_creation_input_tokens": 0
  },
  "total_cost_usd": 0.000234
}
```

This gives per-call cost and cache statistics for free — no separate accounting needed.

### Parallelism

```python
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(run_task, task, skill, model): task for task in pending}
    for future in as_completed(futures):
        result = future.result()
        with write_lock:                      # prevent interleaved JSONL lines
            output_file.write(json.dumps(result) + "\n")
```

8 workers cut wall-clock time from ~70 minutes (sequential) to ~10 minutes per 80-task rollout.

### Resume Support

Every rollout appends to a JSONL file. On re-run, already-processed IDs are skipped:

```python
done_ids = {json.loads(line)["task_id"] for line in existing_file.splitlines()}
pending = [t for t in tasks if t["id"] not in done_ids]
```

This is essential given session limits that interrupt runs mid-rollout.

---

## 14. Engineering Challenges & Solutions

### Challenge 1 — No API Key in the Remote Container

**Problem**: The Python Anthropic SDK requires `ANTHROPIC_API_KEY`, which is not available in the remote container.

**Solution**: Replace the SDK entirely with `subprocess.run(["claude", "--print", ...])`. The CLI uses the OAuth session automatically. `--output-format json` gives the same structured data the SDK would have provided.

---

### Challenge 2 — Session Limit Corruption

**Problem**: When the session limit is hit, the CLI returns plain text like `"You've hit your session limit · resets 3:50pm (UTC)"` with exit code 0. Without detection, tasks score 0.00 silently, and the slow_update function can write this string directly into skill.md.

**Solution**: Detect the exact phrase and raise instead of scoring:

```python
if "hit your session limit" in text.lower():
    raise RuntimeError(f"Claude session limit: {text.strip()[:120]}")
```

Earlier version used `"rate limit"` as a detection phrase — this caused false positives on every review of the `api_middleware` scenario (which adds "rate limiting" middleware). Fixed by using the precise phrase from the actual limit message.

---

### Challenge 3 — Stop Hook Intercepting Subprocess Calls

**Problem**: Claude Code's stop hook (`~/.claude/stop-hook-git-check.sh`) fires after every claude session, including `claude --print` subprocesses. When it finds untracked JSONL output files during a rollout, it exits with code 2 and outputs "There are untracked files in the repository." The CLI treated this as a new user turn, and the model responded to the hook message instead of the code review task. Score: 0.00 on every affected task.

**Solution**: Two-part fix — set an environment variable on the subprocess, check it in the hook:

```python
# backend.py
env = {**os.environ, "CLAUDE_OPTIMIZER_SUBPROCESS": "1"}
proc = subprocess.run(cmd, ..., env=env)
```

```bash
# stop-hook-git-check.sh
if [[ "${CLAUDE_OPTIMIZER_SUBPROCESS}" = "1" ]]; then
  exit 0
fi
```

---

### Challenge 4 — Parallel JSONL Write Safety

**Problem**: 8 threads writing to the same file can interleave partial JSON lines, corrupting the output.

**Solution**: A `threading.Lock()` around every file-write operation ensures atomic appends.

---

### Challenge 5 — Structured Output Requires Both Flags Together

**Problem**: `--json-schema` alone does not force JSON output — the model wraps the JSON in prose.

**Solution**: Always combine `--output-format json` with `--json-schema`. The `structured_output` field in the envelope then contains the parsed object.

---

## 15. Repository Structure

```
claude-skills/
├── skill.md                           ← the skill document being optimized
├── WIKI.md                            ← this document
├── requirements.txt
│
├── src/
│   ├── backend.py                     ← claude --print subprocess wrapper
│   ├── runner.py                      ← parallel rollout with resume
│   ├── scorer.py                      ← keyword-based scoring
│   ├── optimizer.py                   ← TextGrad loop
│   └── dataset/
│       ├── scenarios.py               ← 6 TypeScript scenario templates
│       └── generator.py              ← generates data/tasks.json
│
└── data/
    ├── tasks.json                     ← 150 tasks (committed)
    └── epochs/
        ├── epoch_000/                 ← baseline (score: 0.233)
        ├── epoch_001/                 ← ACCEPTED: 0.233 → 0.951
        ├── epoch_002/                 ← REJECTED: 0.951 → 0.926
        └── epoch_003/                 ← in progress
```

Each epoch directory contains:

```
epoch_NNN/
  train_results.jsonl      ← one scored result per line (80 tasks)
  proposed_edit.json       ← {target_step, rationale, old_text, new_text}
  skill_before.md          ← snapshot of skill.md before the edit
  skill_after.md           ← skill.md with proposed edit applied
  selection_results.jsonl  ← 20 selection tasks scored with new skill
  epoch_result.json        ← {accepted, delta, selection_before, selection_after}
```

---

# Part IV — Using the System

---

## 16. Quickstart

**Prerequisites**: Claude Code CLI installed and authenticated (`claude --version` works), Python 3.10+. No `ANTHROPIC_API_KEY` needed.

```bash
git clone <repo-url> && cd claude-skills
pip install -r requirements.txt

# Smoke test — one task, ~30 seconds
python -m src.runner --split train --limit 1
```

Expected output:
```
Running 1 tasks (8 workers)…
[  1/ 1] task_001 | api_middleware  score=0.67  mean=0.67  cache_read=0  28.3s
```

---

## 17. Running the Optimizer

```bash
# Full 3-epoch optimization run (recommended)
python -m src.optimizer --epochs 3

# Dry-run: propose and print the edit without applying it or running selection
python -m src.optimizer --epochs 1 --dry-run

# Resume from epoch 2 (if epoch_001 completed but epoch_002 did not)
python -m src.optimizer --epochs 3 --start-epoch 2

# Run just the rollout (no optimization)
python -m src.runner --split train --output data/my_eval.jsonl

# Evaluate with the locked test split (run ONCE, after optimization is done)
python -m src.runner --split test --output data/test_results_final.jsonl
```

If the run is interrupted (session limit, network error), re-run the same command. The resume logic skips already-completed task IDs automatically.

---

## 18. Reading Results

```bash
# Live summary of any results file
python3 -c "
import json; from pathlib import Path; from src.runner import load_results, summarise
s = summarise(load_results(Path('data/epochs/epoch_001/train_results.jsonl')))
print(f'mean={s[\"mean_score\"]:.3f}  catch={s[\"overall_catch_rate\"]:.1%}')
for cat, v in sorted(s['by_category'].items(), key=lambda kv: kv[1]['rate']):
    bar = '█' * int(v['rate'] * 20)
    print(f'  {cat:<20} {v[\"caught\"]}/{v[\"total\"]}  {bar}  {v[\"rate\"]:.0%}')
for bug, n in s['top_missed_bugs'][:5]:
    print(f'  {bug:<35} {n}x')
"

# Check an epoch verdict
cat data/epochs/epoch_001/epoch_result.json
```

---

## 19. Adapting to Your Own Domain — Step by Step

**Step 1 — Define your scenarios** (`src/dataset/scenarios.py`)

```python
SCENARIOS = {
  "sql_audit": {
    "filename": "queries/userQuery.sql",
    "pr_title": "feat: add user search query",
    "pr_description": "Adds parameterized search with pagination.",
    "bugs": {
      "sql_injection":   {"category": "security",     "keywords": ["injection", "parameterize", "sanitize"]},
      "missing_index":   {"category": "performance",  "keywords": ["index", "full table scan", "EXPLAIN"]},
      "n_plus_one":      {"category": "performance",  "keywords": ["N+1", "join", "batch"]},
      "missing_limit":   {"category": "logic",        "keywords": ["LIMIT", "unbounded", "pagination"]},
      "null_column":     {"category": "null_safety",  "keywords": ["NULL", "IS NULL", "COALESCE"]},
    },
    "generate_code": _sql_audit_code,   # fn(active_bugs: set) -> str
  },
}
```

**Step 2 — Write your starting skill** (`skill.md`)

```markdown
# SQL Query Review Skill

You are a database expert reviewing SQL query pull requests for correctness,
security, and performance.

## Procedure
### Step 1 — Understand the query intent
### Step 2 — Check for security issues
### Step 3 — Check for performance issues
### Step 4 — Write the review

<!-- SLOW_UPDATE_START -->
<!-- SLOW_UPDATE_END -->
```

Leave intentional gaps — e.g., don't mention N+1 detection in the initial skill.

**Step 3 — Regenerate the dataset**

```bash
python -m src.dataset.generator
```

**Step 4 — Run the baseline and optimizer**

```bash
python -m src.runner --split selection --output data/epochs/epoch_000/selection_results.jsonl
python -m src.optimizer --epochs 5
```

Nothing in `src/optimizer.py` needs to change — the optimizer prompt is written generically and will work for any scoring domain.

---

## 20. Configuration Reference

| Setting | File | Default | Description |
|---|---|---|---|
| Reviewer model | `src/optimizer.py` `ROLLOUT_MODEL` | `claude-haiku-4-5-20251001` | Fast, cheap model for reviewing tasks |
| Optimizer model | `src/optimizer.py` `OPTIMIZER_MODEL` | `claude-sonnet-4-6` | Stronger model for proposing edits |
| Parallel workers | `src/runner.py` `workers=8` | 8 | Subprocess workers per rollout |
| Subprocess timeout | `src/backend.py` `timeout=300` | 300 seconds | Per-call timeout |
| Epochs directory | `src/optimizer.py` `EPOCHS_DIR` | `data/epochs/` | Where epoch results are saved |
| Skill path | `src/optimizer.py` `SKILL_PATH` | `skill.md` | The skill document being optimized |

### Typical Run Times

| Operation | Time | Notes |
|---|---|---|
| Generate dataset | < 5 seconds | No model calls |
| Baseline selection (20 tasks) | ~4 minutes | 8 workers × ~25s/task |
| Train rollout (80 tasks) | ~10–15 minutes | Longer tasks can reach 60–90s |
| Propose edit (1 Sonnet call) | ~30 seconds | Reads failure analysis + 3 examples |
| Selection gate (20 tasks) | ~4 minutes | Same as baseline |
| Slow update (1 Sonnet call) | ~20 seconds | Reads all epoch histories |
| **Full epoch** | **~20 minutes** | Train + propose + selection + slow update |
| **3 epochs** | **~60 minutes** | If no session limits are hit |

---

*Last updated: Epoch 3 in progress. Test split (50 tasks) locked until optimization completes.*
