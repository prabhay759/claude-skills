"""
Thin wrapper around the `claude` CLI for non-interactive model calls.

Uses the same OAuth session as Claude Code itself — no ANTHROPIC_API_KEY needed.
Output is always parsed from --output-format json, giving us structured_output,
result text, and usage stats (including cache hit counts) for free.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass
class CallResult:
    text: str           # response text  (result field, or str(structured_output))
    structured: dict | None   # parsed JSON when json_schema was provided
    usage: dict         # {input_tokens, output_tokens, cache_read_input_tokens, ...}
    cost_usd: float


def complete(
    system: str,
    user: str,
    model: str,
    json_schema: dict | None = None,
    timeout: int = 300,
) -> CallResult:
    """
    Call `claude --print` with a system prompt and user message.

    Args:
        system:      System prompt text (e.g. skill.md content).
        user:        User message text (e.g. task prompt).
        model:       Full model ID, e.g. 'claude-haiku-4-5-20251001'.
        json_schema: If provided, passed as --json-schema; the model outputs
                     JSON matching this schema (returned in CallResult.structured).
        timeout:     Subprocess timeout in seconds.

    Returns:
        CallResult with the response and usage metadata.
    """
    cmd = [
        "claude", "--print",
        "--model", model,
        "--system-prompt", system,
        "--output-format", "json",
        "--no-session-persistence",
    ]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]

    proc = subprocess.run(
        cmd,
        input=user,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(
            f"claude CLI exited {proc.returncode}: {proc.stderr[:300]}"
        )

    envelope = json.loads(proc.stdout)

    # structured_output is populated when --json-schema is used
    structured = envelope.get("structured_output") or None

    # result field holds the text response otherwise
    text = envelope.get("result", "")
    if structured and not text:
        text = json.dumps(structured)

    raw_usage = envelope.get("usage", {})
    usage = {
        "input_tokens":               raw_usage.get("input_tokens", 0),
        "output_tokens":              raw_usage.get("output_tokens", 0),
        "cache_creation_input_tokens": raw_usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens":    raw_usage.get("cache_read_input_tokens", 0),
    }

    return CallResult(
        text=text,
        structured=structured,
        usage=usage,
        cost_usd=envelope.get("total_cost_usd", 0.0),
    )
