"""
Six TypeScript scenario templates. Each has exactly 5 bugs so we get
C(5,1)+C(5,2)+C(5,3) = 25 variants × 6 scenarios = 150 tasks.

Each bug: {category, description, keywords, [line hint]}
generate_code(active_bugs: set[str]) -> TypeScript source string
"""

from __future__ import annotations


# ─── helpers ─────────────────────────────────────────────────────────────────

def _lines(*parts: str) -> str:
    return "\n".join(parts) + "\n"


# ─── Scenario 1: auth_service ─────────────────────────────────────────────────

_AUTH_BUGS: dict[str, dict] = {
    "hardcoded_secret": {
        "category": "security",
        "description": (
            "JWT_SECRET is hardcoded as a string literal instead of read from "
            "process.env — any engineer with repo access sees the production secret."
        ),
        "keywords": [
            "hardcoded", "hard-coded", "secret", "environment variable",
            "process.env", "JWT_SECRET", "plaintext",
        ],
    },
    "token_not_revoked": {
        "category": "security",
        "description": (
            "The old refresh token is never invalidated after rotation. "
            "A stolen token remains valid indefinitely."
        ),
        "keywords": [
            "revoke", "invalidate", "rotation", "old token",
            "reuse", "token rotation", "already used",
        ],
    },
    "missing_user_check": {
        "category": "null_safety",
        "description": (
            "No null check after db.users.findById — if the account was deleted, "
            "accessing user.role on the next line throws TypeError."
        ),
        "keywords": [
            "null check", "user not found", "undefined", "null pointer",
            "user is null", "missing check", "optional",
        ],
    },
    "wrong_expiry": {
        "category": "logic",
        "description": (
            "Access token expiry is '24h' instead of a short-lived value like '15m'. "
            "Long-lived access tokens widen the blast radius of leaks."
        ),
        "keywords": [
            "expiry", "expires", "15 minutes", "access token",
            "short-lived", "lifetime", "24h", "too long",
        ],
    },
    "swallow_error": {
        "category": "error_handling",
        "description": (
            "The jwt.verify catch block returns null instead of throwing. "
            "Invalid tokens silently pass control back to the caller."
        ),
        "keywords": [
            "swallowed", "silent failure", "return null", "catch",
            "error propagation", "exception", "swallow",
        ],
    },
}


def _auth_code(bugs: set[str]) -> str:
    secret      = "'jwt-secret-2024'"       if "hardcoded_secret"   in bugs else "process.env.JWT_SECRET!"
    expiry      = "'24h'"                   if "wrong_expiry"       in bugs else "'15m'"
    err_stmt    = "return null;"            if "swallow_error"      in bugs else "throw new Error('Invalid or expired refresh token');"
    revoke      = ""                        if "token_not_revoked"  in bugs else (
        "  // rotate: immediately invalidate the consumed token\n"
        "  await db.refreshTokens.update({ id: payload.tokenId }, { revoked: true });\n"
    )
    user_guard  = ""                        if "missing_user_check" in bugs else (
        "  if (!user) throw new Error('User not found');\n"
    )

    return _lines(
        "import jwt from 'jsonwebtoken';",
        "import crypto from 'crypto';",
        "import { db } from '../database';",
        "",
        f"const JWT_SECRET = {secret};",
        "const REFRESH_SECRET = process.env.REFRESH_SECRET!;",
        "",
        "export interface TokenPair {",
        "  accessToken: string;",
        "  refreshToken: string;",
        "}",
        "",
        "export async function refreshTokens(token: string): Promise<TokenPair | null> {",
        "  let payload: { userId: string; tokenId: string };",
        "",
        "  try {",
        "    payload = jwt.verify(token, REFRESH_SECRET) as { userId: string; tokenId: string };",
        "  } catch {",
        f"    {err_stmt}",
        "  }",
        "",
        "  const stored = await db.refreshTokens.findOne({",
        "    id: payload!.tokenId,",
        "    userId: payload!.userId,",
        "    revoked: false,",
        "  });",
        "  if (!stored) throw new Error('Token not found or already revoked');",
        "",
        revoke.rstrip("\n"),
        "  const user = await db.users.findById(payload!.userId);",
        user_guard.rstrip("\n"),
        "",
        "  const accessToken = jwt.sign(",
        "    { userId: user!.id, role: user!.role },",
        "    JWT_SECRET,",
        f"    {{ expiresIn: {expiry} }}",
        "  );",
        "",
        "  const refreshToken = jwt.sign(",
        "    { userId: user!.id, tokenId: crypto.randomUUID() },",
        "    REFRESH_SECRET,",
        "    { expiresIn: '7d' }",
        "  );",
        "",
        "  await db.refreshTokens.create({",
        "    id: crypto.randomUUID(),",
        "    userId: user!.id,",
        "    token: refreshToken,",
        "    expiresAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000),",
        "  });",
        "",
        "  return { accessToken, refreshToken };",
        "}",
    )


# ─── Scenario 2: user_repo ───────────────────────────────────────────────────

_USER_REPO_BUGS: dict[str, dict] = {
    "sql_injection": {
        "category": "security",
        "description": (
            "findByEmail builds the query via template literal string interpolation. "
            "An attacker can inject arbitrary SQL through the email parameter."
        ),
        "keywords": [
            "SQL injection", "parameterized", "prepared statement",
            "string interpolation", "user input", "sanitize", "template literal",
        ],
    },
    "n_plus_one": {
        "category": "performance",
        "description": (
            "findByIds issues one SELECT per ID inside a for-loop. "
            "With 100 IDs that's 100 round-trips; use ANY($1) for a single query."
        ),
        "keywords": [
            "N+1", "loop", "query in loop", "batch", "ANY", "performance",
            "database round trip", "findMany", "n plus one",
        ],
    },
    "null_deref": {
        "category": "null_safety",
        "description": (
            "getProfile accesses rows[0].name without checking whether rows[0] exists. "
            "A missing user causes 'Cannot read properties of undefined'."
        ),
        "keywords": [
            "null", "undefined", "optional chaining", "null check",
            "rows[0]", "not found", "missing row",
        ],
    },
    "missing_rollback": {
        "category": "error_handling",
        "description": (
            "transferCredits has no ROLLBACK in the catch block. "
            "If the second UPDATE throws, credits are already deducted and never restored."
        ),
        "keywords": [
            "rollback", "ROLLBACK", "transaction", "catch", "atomic",
            "partial update", "consistency",
        ],
    },
    "any_type": {
        "category": "type_safety",
        "description": (
            "The filters parameter of search() is typed as `any`, bypassing TypeScript's "
            "type checker and hiding invalid filter shapes until runtime."
        ),
        "keywords": [
            "any", "type safety", "unknown", "UserSearchFilters",
            "TypeScript", "strict", "typed parameter",
        ],
    },
}


def _user_repo_code(bugs: set[str]) -> str:
    if "sql_injection" in bugs:
        find_by_email_query = (
            "    const query = `SELECT * FROM users WHERE email = '${email}'`;\n"
            "    const { rows } = await this.pool.query(query);"
        )
    else:
        find_by_email_query = (
            "    const { rows } = await this.pool.query(\n"
            "      'SELECT * FROM users WHERE email = $1',\n"
            "      [email]\n"
            "    );"
        )

    if "n_plus_one" in bugs:
        find_by_ids_body = (
            "    const users: User[] = [];\n"
            "    for (const id of ids) {\n"
            "      const { rows } = await this.pool.query(\n"
            "        'SELECT * FROM users WHERE id = $1', [id]\n"
            "      );\n"
            "      users.push(rows[0]);\n"
            "    }\n"
            "    return users;"
        )
    else:
        find_by_ids_body = (
            "    const { rows } = await this.pool.query(\n"
            "      'SELECT * FROM users WHERE id = ANY($1)',\n"
            "      [ids]\n"
            "    );\n"
            "    return rows;"
        )

    if "null_deref" in bugs:
        get_profile_return = "    return { name: rows[0].name, email: rows[0].email };"
    else:
        get_profile_return = (
            "    if (!rows[0]) throw new Error(`User ${userId} not found`);\n"
            "    return { name: rows[0].name, email: rows[0].email };"
        )

    rollback = "" if "missing_rollback" in bugs else "      await client.query('ROLLBACK');\n"

    filter_type = "any" if "any_type" in bugs else "UserSearchFilters"
    filter_typedef = "" if "any_type" in bugs else (
        "\nexport interface UserSearchFilters {\n"
        "  name?: string;\n"
        "  role?: string;\n"
        "  active?: boolean;\n"
        "}\n"
    )

    return _lines(
        "import { Pool } from 'pg';",
        "import { User } from '../types';",
        filter_typedef,
        "export class UserRepository {",
        "  constructor(private pool: Pool) {}",
        "",
        "  async findByEmail(email: string): Promise<User | null> {",
        find_by_email_query,
        "    return rows[0] ?? null;",
        "  }",
        "",
        "  async findByIds(ids: string[]): Promise<User[]> {",
        find_by_ids_body,
        "  }",
        "",
        "  async getProfile(userId: string): Promise<{ name: string; email: string }> {",
        "    const { rows } = await this.pool.query(",
        "      'SELECT name, email FROM users WHERE id = $1',",
        "      [userId]",
        "    );",
        get_profile_return,
        "  }",
        "",
        "  async transferCredits(fromId: string, toId: string, amount: number): Promise<void> {",
        "    const client = await this.pool.connect();",
        "    try {",
        "      await client.query('BEGIN');",
        "      await client.query(",
        "        'UPDATE users SET credits = credits - $1 WHERE id = $2',",
        "        [amount, fromId]",
        "      );",
        "      await client.query(",
        "        'UPDATE users SET credits = credits + $1 WHERE id = $2',",
        "        [amount, toId]",
        "      );",
        "      await client.query('COMMIT');",
        "    } catch (err) {",
        rollback.rstrip("\n"),
        "      throw err;",
        "    } finally {",
        "      client.release();",
        "    }",
        "  }",
        "",
        f"  async search(filters: {filter_type}): Promise<User[]> {{",
        "    const conditions: string[] = [];",
        "    const values: unknown[] = [];",
        "    let idx = 1;",
        "    if (filters.name) {",
        "      conditions.push(`name ILIKE $${idx++}`);",
        "      values.push(`%${filters.name}%`);",
        "    }",
        "    if (filters.role) {",
        "      conditions.push(`role = $${idx++}`);",
        "      values.push(filters.role);",
        "    }",
        "    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';",
        "    const { rows } = await this.pool.query(",
        "      `SELECT * FROM users ${where}`,",
        "      values",
        "    );",
        "    return rows;",
        "  }",
        "}",
    )


# ─── Scenario 3: api_middleware ───────────────────────────────────────────────

_API_MIDDLEWARE_BUGS: dict[str, dict] = {
    "ip_spoofing": {
        "category": "security",
        "description": (
            "Rate limiting uses req.headers['x-forwarded-for'] directly. "
            "Any client can spoof this header to bypass per-IP limits."
        ),
        "keywords": [
            "X-Forwarded-For", "IP spoofing", "header manipulation",
            "rate limit bypass", "trust proxy", "client IP", "x-forwarded-for",
        ],
    },
    "jwt_decode_not_verify": {
        "category": "security",
        "description": (
            "jwt.decode() is used instead of jwt.verify(). decode() does not validate "
            "the signature — any crafted token with a valid shape will be accepted."
        ),
        "keywords": [
            "jwt.decode", "jwt.verify", "signature", "verification",
            "decode instead of verify", "unsigned", "forged token",
        ],
    },
    "off_by_one": {
        "category": "logic",
        "description": (
            "Rate limit check is `count > RATE_LIMIT` instead of `>= RATE_LIMIT`. "
            "Clients get one extra request before being blocked."
        ),
        "keywords": [
            "off-by-one", "greater than", ">= RATE_LIMIT", "rate limit",
            "boundary", "fencepost", "one extra request",
        ],
    },
    "double_response": {
        "category": "error_handling",
        "description": (
            "next() is called after res.status().json(), causing Express to attempt "
            "a second response and throw 'Cannot set headers after they are sent'."
        ),
        "keywords": [
            "double response", "next()", "headers sent", "Cannot set headers",
            "response sent", "express", "next after send",
        ],
    },
    "missing_error_status": {
        "category": "logic",
        "description": (
            "When rate limit is exceeded the response uses the default 200 status. "
            "Clients receive no machine-readable signal that they were throttled."
        ),
        "keywords": [
            "429", "status code", "Too Many Requests", "rate limit status",
            "HTTP status", "401", "403",
        ],
    },
}


def _api_middleware_code(bugs: set[str]) -> str:
    ip_line = (
        "  const clientIp = (req.headers['x-forwarded-for'] as string) || req.ip;"
        if "ip_spoofing" in bugs else
        "  const clientIp = req.ip;"
    )

    verify_fn = "jwt.decode" if "jwt_decode_not_verify" in bugs else "jwt.verify"

    limit_op = ">" if "off_by_one" in bugs else ">="

    if "double_response" in bugs:
        rate_limit_block = (
            "    res.json({ error: 'Rate limit exceeded' });\n"
            "    next();"
        )
    else:
        rate_limit_block = "    return res.status(429).json({ error: 'Rate limit exceeded' });"

    if "missing_error_status" in bugs:
        rate_limit_status = "res.json"
        rate_limit_block = rate_limit_block.replace("res.status(429).json", "res.json")

    return _lines(
        "import { Request, Response, NextFunction } from 'express';",
        "import jwt from 'jsonwebtoken';",
        "import { redisClient } from '../redis';",
        "",
        "const RATE_LIMIT = 100;",
        "const WINDOW_SECONDS = 60;",
        "const JWT_SECRET = process.env.JWT_SECRET!;",
        "",
        "export async function rateLimitMiddleware(",
        "  req: Request,",
        "  res: Response,",
        "  next: NextFunction",
        "): Promise<void> {",
        ip_line,
        "  const key = `rate:${clientIp}`;",
        "  const count = parseInt(await redisClient.get(key) ?? '0', 10);",
        "",
        f"  if (count {limit_op} RATE_LIMIT) {{",
        "  " + rate_limit_block,
        "    return;",
        "  }",
        "",
        "  await redisClient.multi()",
        "    .incr(key)",
        "    .expire(key, WINDOW_SECONDS)",
        "    .exec();",
        "",
        "  next();",
        "}",
        "",
        "export function authMiddleware(",
        "  req: Request,",
        "  res: Response,",
        "  next: NextFunction",
        "): void {",
        "  const header = req.headers.authorization;",
        "  if (!header?.startsWith('Bearer ')) {",
        "    res.status(401).json({ error: 'Missing token' });",
        "    return;",
        "  }",
        "",
        "  const token = header.slice(7);",
        "  try {",
        f"    const payload = {verify_fn}(token, JWT_SECRET);",
        "    (req as any).user = payload;",
        "    next();",
        "  } catch {",
        "    res.status(401).json({ error: 'Invalid token' });",
        "  }",
        "}",
    )


# ─── Scenario 4: react_hook ───────────────────────────────────────────────────

_REACT_HOOK_BUGS: dict[str, dict] = {
    "missing_dep": {
        "category": "logic",
        "description": (
            "useEffect dependency array omits `userId`. After the initial render, "
            "changing userId does not re-fetch — the hook returns stale data."
        ),
        "keywords": [
            "dependency array", "useEffect", "stale", "userId",
            "exhaustive-deps", "missing dependency", "re-fetch",
        ],
    },
    "unhandled_promise": {
        "category": "error_handling",
        "description": (
            "fetchUser() is awaited inside useEffect without a catch. "
            "Network errors cause an unhandled promise rejection."
        ),
        "keywords": [
            "unhandled", "promise rejection", "catch", ".catch()",
            "error handling", "async", "try-catch",
        ],
    },
    "memory_leak": {
        "category": "performance",
        "description": (
            "No AbortController cleanup returned from useEffect. "
            "If the component unmounts mid-request, setState is called on an unmounted component."
        ),
        "keywords": [
            "memory leak", "cleanup", "AbortController", "abort",
            "unmount", "return function", "cancel request",
        ],
    },
    "wrong_type": {
        "category": "type_safety",
        "description": (
            "useState is initialised as useState<any>(null). The `any` type hides "
            "shape mismatches between the API response and the rest of the component."
        ),
        "keywords": [
            "any", "useState", "type parameter", "generic",
            "User | null", "typed", "type annotation",
        ],
    },
    "no_loading_reset": {
        "category": "logic",
        "description": (
            "setLoading(false) is only called on the success path inside the try block. "
            "On error, isLoading remains true and the spinner never disappears."
        ),
        "keywords": [
            "loading", "isLoading", "setLoading", "finally",
            "error state", "spinner", "reset loading",
        ],
    },
}


def _react_hook_code(bugs: set[str]) -> str:
    state_type = "any" if "wrong_type" in bugs else "User | null"
    deps = "[]" if "missing_dep" in bugs else "[userId]"

    if "unhandled_promise" in bugs:
        fetch_call = (
            "      const data = await fetchUser(userId);\n"
            "      setUser(data);"
        )
    else:
        fetch_call = (
            "      try {\n"
            "        const data = await fetchUser(userId);\n"
            "        setUser(data);\n"
            "      } catch (err) {\n"
            "        setError(err instanceof Error ? err : new Error('Fetch failed'));\n"
            "      }"
        )

    if "no_loading_reset" in bugs:
        loading_finally = ""
        fetch_wrapper_open  = "    const load = async () => {\n      setLoading(true);"
        fetch_wrapper_close = "    };\n    load();"
    else:
        fetch_wrapper_open  = "    const load = async () => {\n      setLoading(true);\n      try {"
        fetch_call = "        " + fetch_call.replace("\n      ", "\n        ")
        fetch_wrapper_close = "      } finally {\n        setLoading(false);\n      }\n    };\n    load();"

    if "memory_leak" in bugs:
        abort_setup   = ""
        abort_cleanup = ""
        abort_signal  = ""
    else:
        abort_setup   = "    const controller = new AbortController();\n"
        abort_signal  = ", { signal: controller.signal }"
        abort_cleanup = "\n    return () => controller.abort();"

    return _lines(
        "import { useState, useEffect } from 'react';",
        "",
        "interface User {",
        "  id: string;",
        "  name: string;",
        "  email: string;",
        "}",
        "",
        f"async function fetchUser(userId: string{abort_signal.replace(', ', ', signal?: AbortSignal')}): Promise<User> {{",
        "  const res = await fetch(`/api/users/${userId}`);",
        "  if (!res.ok) throw new Error(`HTTP ${res.status}`);",
        "  return res.json();",
        "}",
        "",
        f"export function useUser(userId: string) {{",
        f"  const [user, setUser] = useState<{state_type}>(null);",
        "  const [isLoading, setLoading] = useState(false);",
        "  const [error, setError] = useState<Error | null>(null);",
        "",
        f"  useEffect(() => {{",
        f"{abort_setup}",
        "    const load = async () => {",
        "      setLoading(true);",
        fetch_call,
        "    };",
        "    load();",
        f"{abort_cleanup}",
        f"  }}, {deps});",
        "",
        "  return { user, isLoading, error };",
        "}",
    )


# ─── Scenario 5: payment_service ─────────────────────────────────────────────

_PAYMENT_BUGS: dict[str, dict] = {
    "no_amount_validation": {
        "category": "security",
        "description": (
            "The amount parameter is passed directly to Stripe without validation. "
            "A negative amount could result in a refund being issued instead of a charge."
        ),
        "keywords": [
            "amount validation", "negative", "zero", "validate",
            "minimum charge", "amount check", "non-positive",
        ],
    },
    "no_idempotency": {
        "category": "logic",
        "description": (
            "Stripe charge is created without an idempotency key. "
            "On network retry or double-submit, the customer is charged twice."
        ),
        "keywords": [
            "idempotency", "idempotencyKey", "double charge", "retry",
            "Stripe", "duplicate", "idempotent",
        ],
    },
    "stripe_error_swallowed": {
        "category": "error_handling",
        "description": (
            "Stripe errors are caught and logged but the function returns undefined "
            "instead of re-throwing. Callers cannot distinguish success from failure."
        ),
        "keywords": [
            "Stripe error", "StripeError", "swallowed", "re-throw",
            "payment failure", "error handling", "catch",
        ],
    },
    "no_webhook_validation": {
        "category": "security",
        "description": (
            "Webhook handler uses req.body directly without calling "
            "stripe.webhooks.constructEvent(). Any caller can forge payment events."
        ),
        "keywords": [
            "webhook", "signature", "verify", "constructEvent",
            "STRIPE_WEBHOOK_SECRET", "forged", "stripe-signature",
        ],
    },
    "cents_vs_dollars": {
        "category": "logic",
        "description": (
            "Amount is passed to Stripe in dollars. Stripe expects the smallest currency "
            "unit (cents for USD) — a $10 charge becomes $0.10."
        ),
        "keywords": [
            "cents", "currency", "smallest unit", "multiply by 100",
            "Stripe amount", "dollars", "100",
        ],
    },
}


def _payment_code(bugs: set[str]) -> str:
    amount_guard = "" if "no_amount_validation" in bugs else (
        "  if (amount <= 0) throw new Error('Amount must be positive');\n"
    )

    stripe_amount = "amount" if "cents_vs_dollars" in bugs else "Math.round(amount * 100)"

    idempotency_opt = (
        ""
        if "no_idempotency" in bugs else
        "\n      idempotencyKey: idempotencyKey,"
    )

    idempotency_param = (
        "amount: number, currency: string, source: string"
        if "no_idempotency" in bugs else
        "amount: number, currency: string, source: string, idempotencyKey: string"
    )

    if "stripe_error_swallowed" in bugs:
        stripe_try = (
            "  try {\n"
            "    const charge = await stripe.charges.create({\n"
            f"      amount: {stripe_amount},\n"
            "      currency,\n"
            "      source," +
            idempotency_opt + "\n"
            "    });\n"
            "    return charge;\n"
            "  } catch (err) {\n"
            "    console.error('Stripe error:', err);\n"
            "    // swallowed — caller gets undefined\n"
            "  }"
        )
    else:
        stripe_try = (
            "  const charge = await stripe.charges.create({\n"
            f"    amount: {stripe_amount},\n"
            "    currency,\n"
            "    source," +
            idempotency_opt + "\n"
            "  });\n"
            "  return charge;"
        )

    if "no_webhook_validation" in bugs:
        webhook_body = (
            "  const event = req.body as Stripe.Event;\n"
            "  return event;"
        )
    else:
        webhook_body = (
            "  const sig = req.headers['stripe-signature'] as string;\n"
            "  const event = stripe.webhooks.constructEvent(\n"
            "    req.rawBody,\n"
            "    sig,\n"
            "    process.env.STRIPE_WEBHOOK_SECRET!\n"
            "  );\n"
            "  return event;"
        )

    return _lines(
        "import Stripe from 'stripe';",
        "import { Request } from 'express';",
        "",
        "const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {",
        "  apiVersion: '2023-10-16',",
        "});",
        "",
        f"export async function createCharge({idempotency_param}): Promise<Stripe.Charge | undefined> {{",
        amount_guard.rstrip("\n"),
        stripe_try,
        "}",
        "",
        "export function parseWebhookEvent(req: Request): Stripe.Event {",
        webhook_body,
        "}",
    )


# ─── Scenario 6: cache_service ────────────────────────────────────────────────

_CACHE_BUGS: dict[str, dict] = {
    "no_ttl": {
        "category": "performance",
        "description": (
            "redis.set() is called without an EX option. Entries never expire, "
            "causing unbounded memory growth on the Redis instance."
        ),
        "keywords": [
            "TTL", "expiry", "EX", "expire", "memory leak",
            "eviction", "Redis SET", "no expiry",
        ],
    },
    "json_parse_no_catch": {
        "category": "error_handling",
        "description": (
            "JSON.parse(raw) is called without a try-catch. Corrupted or non-JSON "
            "cache values throw SyntaxError and crash the request handler."
        ),
        "keywords": [
            "JSON.parse", "try-catch", "SyntaxError", "malformed",
            "parse error", "invalid JSON", "corrupt",
        ],
    },
    "no_null_check": {
        "category": "null_safety",
        "description": (
            "redis.get() returns null on a cache miss, but the code calls "
            "JSON.parse(raw) unconditionally — JSON.parse(null) returns null but "
            "downstream code may not expect it, and raw could be null on some Redis versions."
        ),
        "keywords": [
            "null", "redis.get", "null check", "cache miss",
            "if (raw)", "optional", "null return",
        ],
    },
    "key_collision": {
        "category": "logic",
        "description": (
            "Cache keys are bare IDs with no namespace prefix. "
            "cacheGet('42') for users and cacheGet('42') for products return the same entry."
        ),
        "keywords": [
            "namespace", "key collision", "prefix", "cache key",
            "conflict", "namespaced", "collision",
        ],
    },
    "stampede": {
        "category": "logic",
        "description": (
            "On a cache miss all concurrent requests hit the database simultaneously. "
            "Under load this causes a cache stampede; a distributed lock or singleflight is needed."
        ),
        "keywords": [
            "stampede", "cache stampede", "race condition", "lock",
            "mutex", "concurrent", "singleflight", "thundering herd",
        ],
    },
}


def _cache_code(bugs: set[str]) -> str:
    key_expr = (
        "key"
        if "key_collision" in bugs else
        "`cache:${key}`"
    )

    set_options = "" if "no_ttl" in bugs else ", { EX: ttlSeconds }"

    ttl_param = (
        "key: string, value: T"
        if "no_ttl" in bugs else
        "key: string, value: T, ttlSeconds = 300"
    )

    if "no_null_check" in bugs:
        null_guard = ""
    else:
        null_guard = "  if (!raw) return null;\n  "

    if "json_parse_no_catch" in bugs:
        parse_block = (
            f"  {null_guard}return JSON.parse(raw) as T;"
        )
    else:
        parse_block = (
            f"  {null_guard}try {{\n"
            "    return JSON.parse(raw) as T;\n"
            "  } catch {\n"
            "    await redis.del(cacheKey);\n"
            "    return null;\n"
            "  }"
        )

    if "stampede" in bugs:
        get_or_set_body = (
            "  const cached = await cacheGet<T>(key);\n"
            "  if (cached !== null) return cached;\n"
            "\n"
            "  const value = await fetchFn();\n"
            "  await cacheSet(key, value);\n"
            "  return value;"
        )
    else:
        get_or_set_body = (
            "  const cached = await cacheGet<T>(key);\n"
            "  if (cached !== null) return cached;\n"
            "\n"
            "  // acquire a short-lived lock to prevent stampede\n"
            "  const lockKey = `lock:${key}`;\n"
            "  const locked = await redis.set(lockKey, '1', { NX: true, EX: 5 });\n"
            "  if (!locked) {\n"
            "    // another process is fetching — brief wait then re-check cache\n"
            "    await new Promise((r) => setTimeout(r, 50));\n"
            "    return cacheGet<T>(key);\n"
            "  }\n"
            "\n"
            "  try {\n"
            "    const value = await fetchFn();\n"
            "    await cacheSet(key, value);\n"
            "    return value;\n"
            "  } finally {\n"
            "    await redis.del(lockKey);\n"
            "  }"
        )

    return _lines(
        "import { createClient } from 'redis';",
        "",
        "const redis = createClient({ url: process.env.REDIS_URL });",
        "redis.connect();",
        "",
        "export async function cacheGet<T>(key: string): Promise<T | null> {",
        f"  const cacheKey = {key_expr};",
        "  const raw = await redis.get(cacheKey);",
        parse_block,
        "}",
        "",
        f"export async function cacheSet<T>({ttl_param}): Promise<void> {{",
        f"  const cacheKey = {key_expr};",
        f"  await redis.set(cacheKey, JSON.stringify(value){set_options});",
        "}",
        "",
        "export async function getOrSet<T>(",
        "  key: string,",
        "  fetchFn: () => Promise<T>,",
        "  ttlSeconds = 300",
        "): Promise<T | null> {",
        get_or_set_body,
        "}",
    )


# ─── Registry ─────────────────────────────────────────────────────────────────

SCENARIOS: dict[str, dict] = {
    "auth_service": {
        "filename": "src/auth/refreshService.ts",
        "pr_title": "feat: add JWT refresh token rotation",
        "pr_description": (
            "Implements secure refresh token rotation. Each refresh token is "
            "single-use: consuming it immediately issues a new pair and revokes "
            "the old one, protecting against stolen-token reuse attacks."
        ),
        "bugs": _AUTH_BUGS,
        "generate_code": _auth_code,
    },
    "user_repo": {
        "filename": "src/db/userRepository.ts",
        "pr_title": "feat: add UserRepository class",
        "pr_description": (
            "Introduces a typed UserRepository over the raw pg Pool. "
            "Provides findByEmail, findByIds, getProfile, transferCredits, and search."
        ),
        "bugs": _USER_REPO_BUGS,
        "generate_code": _user_repo_code,
    },
    "api_middleware": {
        "filename": "src/middleware/rateLimitAuth.ts",
        "pr_title": "feat: add rate-limiting and JWT auth middleware",
        "pr_description": (
            "Two Express middlewares: rateLimitMiddleware enforces 100 req/min per IP "
            "via Redis counters; authMiddleware validates Bearer JWTs on protected routes."
        ),
        "bugs": _API_MIDDLEWARE_BUGS,
        "generate_code": _api_middleware_code,
    },
    "react_hook": {
        "filename": "src/hooks/useUser.ts",
        "pr_title": "feat: add useUser data-fetching hook",
        "pr_description": (
            "Custom React hook that fetches a user by ID, exposes isLoading / error state, "
            "and re-fetches whenever userId changes."
        ),
        "bugs": _REACT_HOOK_BUGS,
        "generate_code": _react_hook_code,
    },
    "payment_service": {
        "filename": "src/payments/stripeService.ts",
        "pr_title": "feat: add Stripe charge and webhook integration",
        "pr_description": (
            "Wraps Stripe's charge creation with basic validation and adds a "
            "webhook event parser for fulfillment flows."
        ),
        "bugs": _PAYMENT_BUGS,
        "generate_code": _payment_code,
    },
    "cache_service": {
        "filename": "src/cache/redisCache.ts",
        "pr_title": "feat: add Redis cache helpers",
        "pr_description": (
            "Generic cacheGet / cacheSet helpers over the Redis client, plus "
            "a getOrSet combinator that handles cache-miss fetching."
        ),
        "bugs": _CACHE_BUGS,
        "generate_code": _cache_code,
    },
}
